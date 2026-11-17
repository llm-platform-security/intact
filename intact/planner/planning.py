"""Shared pieces of the two planners (plan_iterative, plan_collective).

The model sees the page as markup only: each element's tag, visible
attributes, and direct text; no provenance or other labels. Plans are built
for the five functionalities stored per page (classify_functionalities)
and written to one JSON file per page and planning mode.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from intact.planner.view import _render_element

MODEL = "openai/gpt-6-luna"
SKIP_TAGS = {"html", "head", "meta", "link", "script", "style", "title",
             "noscript", "template", "base"}
OPS = ("Operations: click, type, select. Use \"none\" when an element is needed "
       "only for its content (for example, a value you must read or copy).")


def markup(e: dict) -> str | None:
    """The element's own markup, without its id; None if nothing is visible."""
    line, _ = _render_element(e)
    return None if line is None else re.sub(r"^\[bni=[^\]]*\]\s*", "", line)


def candidates(rep: dict) -> list[tuple[dict, str]]:
    """(element, markup) for every element with visible markup, in page order."""
    return [(e, m) for e in rep.get("elements", []) if e.get("tag") not in SKIP_TAGS
            for m in [markup(e)] if m is not None]


def standard_tag(tag: str) -> str:
    """The tag name if it is a standard HTML, SVG, or MathML element, else
    "custom" (a page can name custom elements anything)."""
    from intact.planner.tags import _STANDARD_TAGS

    t = (tag or "").lower()
    return t if t in _STANDARD_TAGS else "custom"


def form_of(e: dict, by_bni: dict):
    """The bni of the element's nearest <form> ancestor, or None."""
    cur = by_bni.get(e.get("parent_bni"))
    while cur is not None:
        if cur.get("tag") == "form":
            return cur["bni"]
        cur = by_bni.get(cur.get("parent_bni"))
    return None


_ACTIVATABLE_TAGS = {"a", "button", "summary", "label", "input", "select", "option", "textarea"}
_ACTIVATABLE_ROLES = {"button", "link", "tab", "menuitem", "option", "checkbox", "radio", "switch"}


def acts_on(e: dict, op: str, by_bni: dict):
    """The bni an operation actually acts on. A click on text inside a link or
    button activates that link or button; typing and choosing act on the
    element itself. None for content-only steps and clicks that activate
    nothing."""
    if op == "none":
        return None
    if op in ("type", "select"):
        return e["bni"]
    cur = e
    while cur is not None:
        role = ((cur.get("attrs") or {}).get("role") or "").lower()
        if cur.get("tag") in _ACTIVATABLE_TAGS or role in _ACTIVATABLE_ROLES:
            return cur["bni"]
        cur = by_bni.get(cur.get("parent_bni"))
    return None


def saved_value(reply: dict):
    """The value that a planner saves for a step, from the model's `reply`
    (an element's decision, or one step of a whole-page plan): the model's
    value as given, any JSON value (0, false, [], ...), and "" only when the
    reply has none or a null one. It is saved, never sent: no request
    shows a saved value."""
    value = reply.get("value")
    return "" if value is None else value


def page_view(cands: list[tuple[dict, str]]) -> str:
    """The whole page, one element per line, each tagged with its bni."""
    return "\n".join(f"[bni={e['bni']}] {m}" for e, m in cands)


def parse_json(text: str, *, log=None) -> dict:
    status = "json"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        found = re.search(r"\{.*\}", text, re.S)
        try:
            parsed = json.loads(found.group(0)) if found else {}
            status = "extracted_json" if found else "invalid_json"
        except json.JSONDecodeError:
            parsed, status = {}, "invalid_json"
    if log is not None:
        log["parse_status"] = status
    return parsed


def logged_call(llm, system, user, trace, stage, **context):
    """Audit a call locally; no trace fields are sent to the model."""
    event = {"stage": stage, **context, "request": {"system": system, "user": user},
             "raw_reply": None, "parse_status": "unavailable", "parsed_fields": None,
             "plan_entries": [], "decision": None}
    trace.append(event)
    try:
        reply = llm(system, user)
    except Exception as exc:
        event.update(getattr(llm, "last_reply", None) or {})
        event.update(decision="model_call_failed", error=f"{type(exc).__name__}: {exc}")
        raise
    event.update(getattr(llm, "last_reply", None) or {})
    event["parsed_fields"] = copy.deepcopy(reply)
    return reply, event


def openrouter_client():
    """The API client that OpenRouterLLM calls when given none: OpenRouter's,
    through OpenAI's client. Without OPENROUTER_API_KEY in the environment it
    raises RuntimeError. One client may serve many OpenRouterLLMs, in many
    threads, as one OpenRouterLLM's client serves its parallel calls."""
    from openai import OpenAI

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1")


class OpenRouterLLM:
    """JSON-returning chat calls via OpenRouter, with usage accounting.

    A call that fails or comes back without an answer is retried; after the
    last attempt the error (with the API's message) is raised.

    last_reply records each call, for logged_call to put on its trace event:
    besides the request, the raw reply, and the attempts' errors, when the
    call was made (called_at, UTC), the model that answered (the response's
    `model`), the provider when the response names one, and the call's usage
    as the API reports it (tokens_in, cached_in, tokens_out, cost_usd; None
    where it reports none). Recording only: the request is the same.
    """

    def __init__(self, model: str = MODEL, client=None, retries: int = 3):
        self.client = openrouter_client() if client is None else client
        self.model, self.retries = model, retries
        self.lock = threading.Lock()
        self._reply = threading.local()
        self.usage = {"calls": 0, "tokens_in": 0, "cached_in": 0, "tokens_out": 0,
                      "cost_usd": 0.0}

    @property
    def last_reply(self):
        """Per-thread metadata, so parallel relevance calls cannot mix replies."""
        return getattr(self._reply, "value", None)

    def __call__(self, system: str, user: str) -> dict:
        self._reply.value = {"request": {"system": system, "user": user},
                             "raw_reply": None, "parse_status": "not_received", "attempt_errors": [],
                             "called_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                             "usage": None, "model": None}
        for attempt in range(self.retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    extra_body={"reasoning": {"effort": "low"}, "usage": {"include": True}})
                if not resp.choices:
                    error = (getattr(resp, "model_extra", None) or {}).get("error")
                    raise RuntimeError(f"no answer from the API: {error}")
                break
            except Exception as exc:
                self.last_reply["attempt_errors"].append(
                    {"attempt": attempt + 1, "error": f"{type(exc).__name__}: {exc}"})
                if attempt == self.retries - 1:
                    raise
                time.sleep(2 * 2 ** attempt)
        raw = resp.choices[0].message.content
        self.last_reply["raw_reply"] = raw
        u = resp.usage
        if u:
            details = getattr(u, "prompt_tokens_details", None)
            cost = getattr(u, "cost", None)
            if cost is None:
                cost = (getattr(u, "model_extra", None) or {}).get("cost")
            self.last_reply["usage"] = {
                "tokens_in": u.prompt_tokens, "cached_in": getattr(details, "cached_tokens", None) if details else None,
                "tokens_out": u.completion_tokens, "cost_usd": None if cost is None else float(cost)}
        self.last_reply["model"] = getattr(resp, "model", None)
        provider = getattr(resp, "provider", None) or (getattr(resp, "model_extra", None) or {}).get("provider")
        if provider is not None:
            self.last_reply["provider"] = provider
        with self.lock:
            self.usage["calls"] += 1
            if u:
                self.usage["tokens_in"] += u.prompt_tokens or 0
                self.usage["tokens_out"] += u.completion_tokens or 0
                self.usage["cached_in"] += (getattr(details, "cached_tokens", 0) or 0) if details else 0
                self.usage["cost_usd"] += float(cost or 0)
        parsed = parse_json(raw or "{}", log=self.last_reply)
        if not raw:
            self.last_reply["parse_status"] = "empty_reply"
        return parsed


def _write_atomically(path, fill):
    """`fill` writes a temporary file in path's folder, which then replaces
    `path`, so a reader or a resumed run sees the old file or the new one,
    never part of one. The temporary is removed if anything fails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fill(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    """Atomic (_write_atomically)."""
    def fill(temporary):
        text = json.dumps(value, indent=1, ensure_ascii=False) + "\n"
        with open(temporary, "x") as stream:  # the encoding Path.write_text uses
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    _write_atomically(path, fill)


def write_text(path, text):
    """`text` written atomically (_write_atomically), in the encoding
    Path.write_text uses."""
    def fill(temporary):
        with open(temporary, "x") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    _write_atomically(path, fill)


def page_name(page: str) -> str:
    return Path(page).parent.name if page.endswith(".json") else page


def load_rep(page: str, captures: Path) -> dict:
    path = Path(page) if page.endswith(".json") else captures / page / "representation.json"
    return json.loads(path.read_text())


def load_functionalities(page: str, directory: Path) -> list[dict]:
    return json.loads((directory / f"{page_name(page)}.json").read_text())["functionalities"]


def plan_one(rep: dict, functionality: dict, planner, llm_factory) -> dict:
    """One plan for one stored functionality, as plan_pages saves it: the
    functionality, the planner's result, and the usage with the time taken.
    A planner failure is recorded (no steps, the error, the trace so far)."""
    llm, t0 = llm_factory(), time.time()
    llm.trace = []
    try:
        result = planner(rep, functionality["prompt"], llm)
    except Exception as exc:  # keep going; the file records the failure
        result = {"steps": [], "error": f"{type(exc).__name__}: {exc}", "trace": llm.trace}
    usage = {**llm.usage, "cost_usd": round(llm.usage.get("cost_usd", 0.0), 5),
             "seconds": round(time.time() - t0, 1)}
    return {"functionality": functionality.get("functionality"), "prompt": functionality["prompt"],
            "interaction": functionality.get("interaction"), **result, "usage": usage}


def plan_pages(pages, planner, mode, *, captures: Path, functionalities: Path,
               out: Path, workers: int, llm_factory=OpenRouterLLM, finish=None,
               model: str = MODEL) -> list[Path]:
    """Plan every stored functionality of every page; one file per page.

    A page's record is written as soon as all its functionalities are
    planned, whole (write_json: atomically): finish(page name, record), if
    given, completes it first and returns it (e.g., to stamp the run's
    setting and the page's hash), so a run that stops early leaves only
    finished records and the next one plans the rest. The record names
    `model`, the model that llm_factory's clients call. A saved record
    that names another model stops the run with ValueError, before any
    model call. An exception or an interrupt cancels the plans still
    queued."""
    (out / mode).mkdir(parents=True, exist_ok=True)
    reps = {p: load_rep(p, captures) for p in pages}
    jobs, slots, written = [], {}, []
    for p in pages:
        funcs = load_functionalities(p, functionalities)
        path = out / mode / f"{page_name(p)}.json"
        done = {}
        if path.exists():  # resume: keep successful plans, replan the rest
            saved = json.loads(path.read_text())
            if saved.get("model", model) != model:
                raise ValueError(f"{path} holds plans made with {saved['model']}, not {model}; "
                                 "use another --out")
            done = {pl["prompt"]: pl for pl in saved.get("plans", []) if pl and not pl.get("error")}
        slots[p] = [done.get(f["prompt"]) for f in funcs]
        jobs += [(p, i, f) for i, f in enumerate(funcs) if slots[p][i] is None]
        if all(s is not None for s in slots[p]):
            written.append(path)

    def one(job):
        page, _, f = job
        return plan_one(reps[page], f, planner, llm_factory)

    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(one, job): job for job in jobs}
        try:
            for fut in as_completed(futures):
                page, i, _ = futures[fut]
                plan = fut.result()
                slots[page][i] = plan
                print(f"  {mode} {page_name(page)} #{i + 1}: {len(plan['steps'])} steps, "
                      f"{plan['usage'].get('seconds', 0)}s"
                      + (f", error: {plan['error']}" if plan.get("error") else ""), flush=True)
                if all(s is not None for s in slots[page]):
                    path = out / mode / f"{page_name(page)}.json"
                    record = {"page": page_name(page), "url": reps[page].get("url"), "model": model,
                              "mode": mode, "plans": slots[page]}
                    write_json(path, record if finish is None else finish(page_name(page), record))
                    written.append(path)
        except BaseException:
            for fut in futures:
                fut.cancel()
            raise
    return written


def run_each(items, work, *, workers: int = 1) -> None:
    """Call work(item) for each of `items`, up to `workers` at a time, begun
    in the items' order; with one worker, one after another, as a loop would.

    The first call to fail stops the run: no item is begun after it, the
    calls under way finish (whatever they write is whole), and then the
    error of the first failed item in the items' order is raised. An
    interrupt likewise cancels the items not begun and lets those under way
    finish before it reaches the caller, also one that comes while the
    items are still being submitted. work keeps its own results."""
    if workers < 1:
        raise ValueError(f"workers must be at least 1, not {workers}")
    stop, failed, futures = threading.Event(), {}, []

    def one(index, item):
        if stop.is_set():
            return
        try:
            work(item)
        except BaseException as exc:  # recorded before the worker takes another item
            failed[index] = exc
            stop.set()

    with ThreadPoolExecutor(workers) as pool:
        try:
            for index, item in enumerate(items):
                futures.append(pool.submit(one, index, item))
            for _ in as_completed(futures):
                pass
        except BaseException:  # stop: an item submitted but not yet in `futures` sees it and does no work
            stop.set()
            for future in futures:
                future.cancel()
            raise
    if failed:
        raise failed[min(failed)]


def cli(planner, mode: str, default_workers: int, doc: str) -> None:
    ap = argparse.ArgumentParser(description=doc)
    ap.add_argument("pages", nargs="+", help="crawl folders (e.g. kayak.com) or representation.json paths")
    ap.add_argument("--captures", type=Path, default=Path("."))
    ap.add_argument("--functionalities", type=Path, default=Path("functionalities"))
    ap.add_argument("--out", type=Path, default=Path("plans"))
    ap.add_argument("--workers", type=int, default=default_workers)
    ap.add_argument("--model", default=MODEL, help=f"an OpenRouter model (default: {MODEL})")
    args = ap.parse_args()
    for path in plan_pages(args.pages, planner, mode, captures=args.captures,
                           functionalities=args.functionalities, out=args.out,
                           workers=args.workers, llm_factory=lambda: OpenRouterLLM(args.model),
                           model=args.model):
        print(f"wrote {path}")
