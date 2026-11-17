"""Persistent browser session for multi-step web interaction."""

import json
import time
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from playwright._impl._errors import TargetClosedError

from intact.browser.launch import collect_frame_ids
from intact.instrumentation.oopif import (attach_isolated_frames, capture_segment, frame_owner,
                           merge_segment, namespaced, parent_session, split,
                           uncaptured_frames)
from intact.instrumentation.cdp_provenance import CDPProvenance, _etld1
from intact.gentree.classification_pass import attach_classifications
from intact.gentree.unified_view import build_unified_elements


class BrowserSession:

    def __init__(self, headless: bool = False,
                 ignore_https_errors: bool = False,
                 browser_args: list[str] | None = None):
        self._pw                  = sync_playwright().start()
        self._tracker             = None   # CDPProvenance, reset on each navigation
        self._isolated: dict      = {}     # Playwright frame -> isolated-frame session
        self._next_segment        = 1
        self._headless            = headless
        self._ignore_https_errors = ignore_https_errors
        self._browser_args        = browser_args or []
        self._launch()

    def _launch(self) -> None:
        self.browser  = self._pw.chromium.launch(headless=self._headless,
                                                 args=self._browser_args)
        self._context = self.browser.new_context(ignore_https_errors=self._ignore_https_errors)
        self.page     = self._context.new_page()
        self.cdp      = self._context.new_cdp_session(self.page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate(self, url: str, wait: float = 8.0) -> None:
        print(f"Navigating to {url}...")

        self._tracker = CDPProvenance(_etld1(url))
        self._isolated = {}
        self._next_segment = 1

        # add_init_script injects into the main world before any page scripts
        self.page.add_init_script(self._tracker.inject_script())
        self._tracker.enable_network_tracking(self.cdp)

        try:
            self.page.goto(url, wait_until="commit", timeout=60_000)
        except TargetClosedError as e:
            # The browser/page target itself is gone — only this case actually
            # warrants a relaunch.
            print(f"  target closed (relaunching): {e}")
            self.recover(url, wait)
            return
        except PlaywrightError as e:
            # Navigation failed but the browser is still alive (timeout, net
            # error, etc.). Don't relaunch — just continue with whatever
            # state we have. The settle wait and capture will see the
            # partial DOM.
            print(f"  goto error (continuing): {e}")

        self._rebase_to_final_url()
        time.sleep(wait)
        # Attach to site-isolated frames now, so their trackers record network
        # activity during the rest of the visit; capture() attaches late ones.
        self._attach_isolated()

    def _rebase_to_final_url(self) -> None:
        """Label provenance against the site the page landed on: a cross-site
        redirect changes which party is first."""
        try:
            final = self.page.url
        except Exception:
            return
        if not final.startswith("http"):
            return
        origin = _etld1(final)
        if not origin:
            return
        if self._tracker:
            self._tracker.rebase(origin)
        for entry in self._isolated.values():
            entry["tracker"].rebase(origin)

    def _attach_isolated(self) -> None:
        try:
            origin = self._tracker.page_origin if self._tracker else ""
            self._next_segment = attach_isolated_frames(
                self._context, self.page, self._isolated, origin,
                self._next_segment)
        except Exception as e:
            print(f"  isolated frame discovery failed: {e}")

    def recover(self, url: str, wait: float = 8.0) -> None:
        """Relaunch the browser and re-navigate after a crash."""
        print("  Browser crashed — restarting...")
        try:
            self.browser.close()
        except BaseException:
            pass
        time.sleep(2.0)
        self._launch()
        try:
            self.navigate(url, wait)
        except Exception as e:
            print(f"  Recovery failed: {e}")

    # ------------------------------------------------------------------
    # State capture
    # ------------------------------------------------------------------

    def capture(self) -> dict:
        """
        Returns {
            "elements":       [unified record per DOM element in document-tree pre-order],
            "ax_nodes":       [raw AX tree from CDP — kept for power-users],
            "classification": {bni → ElementClassification — full DOM-wide map},
            "provenance":     {elements: {bni → creator info}, network, scripts},
            "dom_records":    [raw DOM tree records — input to unified_view],
        }

        `state["elements"]` is the canonical per-page representation. It
        walks the full DOM (across every frame) in pre-order, attaching AX
        role/name/properties when the element is in the AX tree, the
        classification (always — every DOM element classifies), and
        provenance when the element was JS-tracked. Elements that AX
        doesn't surface (script/meta/hidden/aria-hidden/etc.) are still
        present — `ax_in_tree=False` flags them.
        """
        self._rebase_to_final_url()  # late (JS) redirects
        provenance = {}
        if self._tracker:
            provenance = self._tracker.collect(self.cdp)

        ax_nodes = []
        try:
            self.cdp.send("Accessibility.enable", {})
            frame_tree = self.cdp.send("Page.getFrameTree", {})
            frame_ids  = collect_frame_ids(frame_tree.get("frameTree", {}))
            for fid in frame_ids:
                try:
                    result = self.cdp.send("Accessibility.getFullAXTree", {"frameId": fid})
                    ax_nodes.extend(result.get("nodes", []))
                except Exception as e:
                    print(f"  AX fetch failed ({fid[:8]}): {e}")
        except Exception as e:
            print(f"  AX capture failed: {e}")

        state = {
            "ax_nodes":   ax_nodes,
            "provenance": provenance,
        }
        attach_classifications(state, self.cdp)
        state["frames"] = []
        self._capture_isolated(state)
        state["elements"] = build_unified_elements(state)
        return state

    def _capture_isolated(self, state: dict) -> None:
        """Capture every site-isolated frame through its own session and merge
        it into ``state``; record any isolated frame that could not be reached."""
        self._attach_isolated()
        captured: set[str] = set()
        for entry in sorted(self._isolated.values(), key=lambda e: e["segment"]):
            fr = entry["frame"]
            try:
                sub = capture_segment(entry["session"], entry["tracker"])
                pcdp, pseg = parent_session(fr, self._isolated, self.cdp)
                owner = namespaced(frame_owner(pcdp, entry["fid"]), pseg)
                merge_segment(state, sub, entry["segment"], frame_url=fr.url,
                              owner_bni=owner)
                captured.add(entry["fid"])
            except Exception as e:
                print(f"  isolated frame capture failed ({fr.url[:60]}): {e}")
        try:
            targets = self.cdp.send("Target.getTargets", {}).get("targetInfos", [])
        except Exception:
            targets = []
        state["uncaptured_frames"] = uncaptured_frames(targets, captured)
        if state["uncaptured_frames"]:
            print(f"  WARNING: {len(state['uncaptured_frames'])} isolated frame(s) "
                  f"not captured: {[f['url'][:60] for f in state['uncaptured_frames']]}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click(self, backend_node_id: int) -> None:
        old_url = self.page.url
        self._call(backend_node_id,
                   "function() { this.scrollIntoViewIfNeeded(); this.click(); }")
        time.sleep(1.0)
        if self.page.url != old_url:
            time.sleep(4.0)

    def type_text(self, backend_node_id: int, text: str) -> None:
        self._call(backend_node_id,
                   "function() { this.scrollIntoViewIfNeeded(); this.focus(); this.select(); }")
        self.page.keyboard.type(text)

    def select_option(self, backend_node_id: int, value: str) -> None:
        self._call(backend_node_id, f"""function() {{
            this.value = {json.dumps(value)};
            this.dispatchEvent(new Event('change', {{bubbles: true}}));
            this.dispatchEvent(new Event('input',  {{bubbles: true}}));
        }}""")

    def set_checked(self, backend_node_id: int, checked: bool) -> None:
        state = "true" if checked else "false"
        self._call(backend_node_id,
                   f"function() {{ if (this.checked !== {state}) this.click(); }}")

    def scroll(self, direction: str = "down", amount: int = 500) -> None:
        dy = amount if direction == "down" else -amount
        try:
            self.page.evaluate(f"window.scrollBy(0, {dy})")
        except Exception as e:
            print(f"  scroll failed: {e}")
        time.sleep(0.3)

    def press_key(self, key: str) -> None:
        try:
            self.page.keyboard.press(key)
        except Exception as e:
            print(f"  press_key failed: {e}")
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _session_for(self, backend_node_id: int):
        """(CDP session, local backendNodeId) for a possibly namespaced id:
        elements inside a site-isolated frame live behind that frame's session."""
        segment, local = split(backend_node_id)
        if segment == 0:
            return self.cdp, backend_node_id
        for entry in self._isolated.values():
            if entry["segment"] == segment:
                return entry["session"], local
        raise ValueError(f"no isolated-frame session for element {backend_node_id}")

    def _resolve(self, backend_node_id: int) -> str:
        cdp, local = self._session_for(backend_node_id)
        result = cdp.send("DOM.resolveNode", {"backendNodeId": local})
        return result["object"]["objectId"]

    def _call(self, backend_node_id: int, fn: str) -> None:
        obj = self._resolve(backend_node_id)
        cdp, _ = self._session_for(backend_node_id)
        cdp.send("Runtime.callFunctionOn", {
            "objectId":            obj,
            "functionDeclaration": fn,
            "returnByValue":       True,
        })

    def close(self) -> None:
        try:
            self._context.close()
        except BaseException:
            pass
        try:
            self.browser.close()
        except BaseException:
            pass
        try:
            self._pw.stop()
        except BaseException:
            pass
