"""Capture of site-isolated (out-of-process) iframes.

With site isolation, Chromium runs a cross-site iframe in its own renderer
process, behind its own DevTools target. A CDP session attached to the page
does not see inside it: DOMSnapshot, the AX tree, and provenance collection
all stop at the <iframe> element. We therefore attach a separate session to
every isolated frame, capture it with the same steps as the page, and merge
the result into the page's state.

Each renderer numbers its DOM nodes independently, so an isolated frame's
backendNodeIds collide with the page's. Segment k (k >= 1) is namespaced as
``k * NS + local id``; the page itself (segment 0) keeps its ids, so captures
without isolated frames are unchanged.
"""

from __future__ import annotations

from typing import Any

from intact.instrumentation.cdp_provenance import _attribution_coverage

NS = 1_000_000_000


# --------------------------------------------------------------------------- #
# id namespacing
# --------------------------------------------------------------------------- #
def namespaced(bni: int | None, segment: int) -> int | None:
    if bni is None:
        return None
    return bni if segment == 0 else segment * NS + bni


def split(nid: int) -> tuple[int, int]:
    """(segment, local backendNodeId) for a possibly namespaced id."""
    return divmod(nid, NS)


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #
def _ns_ax_node(node: dict, segment: int) -> dict:
    out = dict(node)
    if out.get("backendDOMNodeId"):
        out["backendDOMNodeId"] = namespaced(out["backendDOMNodeId"], segment)
    for key in ("nodeId", "parentId"):
        if out.get(key) is not None:
            out[key] = f"f{segment}:{out[key]}"
    if out.get("childIds"):
        out["childIds"] = [f"f{segment}:{c}" for c in out["childIds"]]
    return out


def _merge_provenance(prov: dict, seg: dict, segment: int) -> None:
    elements = prov.setdefault("elements", {})
    for bni, rec in (seg.get("elements") or {}).items():
        elements[namespaced(bni, segment)] = rec
    prov.setdefault("network", []).extend(seg.get("network") or [])
    scripts = prov.setdefault("scripts", {})
    for url, info in (seg.get("scripts") or {}).items():
        if url not in scripts:
            scripts[url] = info
            continue
        loads = scripts[url].setdefault("3p_loads", [])
        for entry in info.get("3p_loads") or []:
            if entry not in loads:
                loads.append(entry)
    instances = prov.setdefault("script_instances", {})
    for sid, info in (seg.get("script_instances") or {}).items():
        instances[f"f{segment}:{sid}"] = info
    prov.setdefault("inline_scripts", {}).update(seg.get("inline_scripts") or {})
    prov["coverage"] = _attribution_coverage(elements)


def merge_segment(state: dict[str, Any], seg: dict[str, Any], segment: int,
                  frame_url: str = "", owner_bni: int | None = None) -> dict:
    """Merge one isolated frame's capture (dom_records, classification,
    ax_nodes, provenance) into ``state`` in place, namespacing its ids.
    ``owner_bni`` is the (already namespaced) id of the <iframe> element that
    embeds the frame in its parent."""
    records = state.setdefault("dom_records", [])
    doc_offset = 1 + max((r.get("doc_index", 0) for r in records), default=-1)
    for rec in seg.get("dom_records") or []:
        out = dict(rec)
        out["bni"] = namespaced(rec.get("bni"), segment)
        out["parent_bni"] = namespaced(rec.get("parent_bni"), segment)
        out["doc_index"] = rec.get("doc_index", 0) + doc_offset
        records.append(out)
    classification = state.setdefault("classification", {})
    for bni, cls in (seg.get("classification") or {}).items():
        classification[namespaced(bni, segment)] = cls
    state.setdefault("ax_nodes", []).extend(
        _ns_ax_node(n, segment) for n in seg.get("ax_nodes") or [])
    _merge_provenance(state.setdefault("provenance", {}),
                      seg.get("provenance") or {}, segment)
    state.setdefault("frames", []).append(
        {"segment": segment, "url": frame_url, "owner_bni": owner_bni,
         "doc_index": doc_offset})
    return state


# --------------------------------------------------------------------------- #
# guard
# --------------------------------------------------------------------------- #
def uncaptured_frames(targets: list[dict], captured_ids: set[str]) -> list[dict]:
    """Isolated-frame targets whose content did not make it into the capture."""
    return [{"target_id": t.get("targetId"), "url": t.get("url", "")}
            for t in targets
            if t.get("type") == "iframe" and t.get("targetId") not in captured_ids]


# --------------------------------------------------------------------------- #
# browser side: attach, capture, locate owner
# --------------------------------------------------------------------------- #
def attach_isolated_frames(context, page, entries: dict, page_origin: str,
                           next_segment: int) -> int:
    """Attach a DevTools session and a provenance tracker to every
    site-isolated frame of ``page`` not yet in ``entries`` (keyed by the
    Playwright frame). Frames that share their parent's process are skipped:
    their content is already in the parent's snapshot (Playwright refuses a
    separate session for them). Returns the next free segment number."""
    from intact.instrumentation.cdp_provenance import CDPProvenance

    for fr in page.frames:
        if fr is page.main_frame or fr in entries:
            continue
        try:
            sess = context.new_cdp_session(fr)
        except Exception:
            continue  # in-process frame, or already detached
        try:
            fid = sess.send("Page.getFrameTree", {})["frameTree"]["frame"]["id"]
            tracker = CDPProvenance(page_origin)
            tracker.enable_network_tracking(sess)
        except Exception as e:
            print(f"  isolated frame attach failed ({fr.url[:60]}): {e}")
            continue
        entries[fr] = {"frame": fr, "session": sess, "tracker": tracker,
                       "fid": fid, "segment": next_segment}
        next_segment += 1
    return next_segment


def capture_segment(cdp, tracker) -> dict:
    """Capture one isolated frame (and any frames sharing its process) with the
    same steps as the page: provenance, AX tree, DOMSnapshot + classification."""
    from intact.browser.launch import collect_frame_ids
    from intact.gentree.classification_pass import attach_classifications

    provenance = tracker.collect(cdp) if tracker else {}
    ax_nodes: list = []
    try:
        cdp.send("Accessibility.enable", {})
        tree = cdp.send("Page.getFrameTree", {})
        for fid in collect_frame_ids(tree.get("frameTree", {})):
            try:
                ax_nodes.extend(cdp.send("Accessibility.getFullAXTree",
                                         {"frameId": fid}).get("nodes", []))
            except Exception as e:
                print(f"  isolated frame AX fetch failed ({fid[:8]}): {e}")
    except Exception as e:
        print(f"  isolated frame AX capture failed: {e}")
    sub = {"ax_nodes": ax_nodes, "provenance": provenance}
    attach_classifications(sub, cdp)
    return sub


def parent_session(frame, entries: dict, main_cdp):
    """(session, segment) of the process that holds ``frame``'s <iframe>."""
    p = frame.parent_frame
    while p is not None:
        if p in entries:
            return entries[p]["session"], entries[p]["segment"]
        p = p.parent_frame
    return main_cdp, 0


def frame_owner(parent_cdp, frame_id: str) -> int | None:
    """Local backendNodeId of the <iframe> element embedding ``frame_id``."""
    try:
        parent_cdp.send("DOM.enable", {})
        return parent_cdp.send("DOM.getFrameOwner",
                               {"frameId": frame_id}).get("backendNodeId")
    except Exception:
        return None
