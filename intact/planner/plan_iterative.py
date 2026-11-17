"""Iterative planning: the model sees the page one element at a time.

For each functionality of a page: split the page's markup into chunks and keep
the chunks the model says pertain to the task. If more than one does, one call
shows the model those chunks as numbered parts and it picks the part where the
task can best be done. Then show the model each element of that chunk, one at
a time, with the log of operations decided so far. If the chunk ends inside a
form, the walk continues, element by element, until the form ends.
For each element it says whether the task needs it and with which operation
(click, type, select, or none = needed only for its content). The model sees
only the element's own markup; for each operation decided before it, the
operation, the standard tag name it was on, how many elements back, and whether
it shares the current element's form; and a Form line saying whether the
element is inside a form and where that form started. Our code sets the log
and the Form line from the page's tags -- never an earlier element's markup,
text, or typed value -- and links each step to the element's bni. Elements are
decided in page order, one after another; only the relevance checks run in
parallel.

Usage:
  python -m intact.planner.plan_iterative PAGE [PAGE ...] [--workers N] [--model MODEL]
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from intact.planner.planning import OPS, acts_on, candidates, cli, form_of, logged_call, saved_value, standard_tag

CHUNK_CHARS = 1500
RELEVANCE_WORKERS = 4  # relevance checks running at once

RELEVANCE_SYSTEM = (
    "You help a web agent find where on a page a task can be done. You see part "
    "of the page as HTML elements, one per line. Reply with JSON only: "
    "{\"relevant\": true or false} -- true if any element here must be acted on "
    "or read to do the task.")

def log_line(n: int, op: str, tag: str, back: int, same_form: bool) -> str:
    """One decided step: its operation, the standard tag name it was on, how
    many elements back it was, and whether it shares the current element's
    form. No text, attributes, or values."""
    return (f"{n}. {op} on {standard_tag(tag)}, {back} element{'' if back == 1 else 's'} back"
            + (", same form" if same_form else ""))


def form_line(back: int | None) -> str:
    """Whether the element is inside a form (None: not) and how many elements
    back that form started."""
    if back is None:
        return "none"
    if back == 0:
        return "a form starts at this element"
    return f"inside a form that started {back} element{'' if back == 1 else 's'} back"


def step_message(task: str, lines: list[str], markup: str, form: str = "none") -> str:
    """One element's question: the task, the log lines, the Form line, and the
    element's own markup."""
    log = "\n".join(lines) or "(none)"
    return (f"Task: {task}\n\nOperations decided so far:\n{log}\n\nForm: {form}"
            f"\n\nCurrent element:\n{markup}")


# Few-shot examples in the planner's own format, from pages we do not test
# (Lowe's, iHerb, Home Depot, PriceRunner), for the patterns that inflated
# plans: detours through menus and icons, clicking a target's parts, marking
# labels as content, and continuing after a single action is planned.
FEW_SHOT = [
    {"task": "Search Lowe's for cordless drills.", "log": [],
     "form": form_line(0),
     "element": '<input aria-label="Search Query" placeholder="What can we help you find?" type="text" name="searchTerm">',
     "answer": {"needed": True, "operation": "type", "value": "cordless drills"}},
    {"task": "Search Lowe's for cordless drills.",
     "log": [log_line(1, "type", "input", 1, True)], "form": form_line(1),
     "element": '<button aria-label="Search" type="submit">',
     "answer": {"needed": True, "operation": "click", "value": ""}},
    {"task": "Search iHerb for vitamin D.",
     "log": [log_line(1, "type", "input", 1, True)], "form": form_line(1),
     "element": '<button aria-label="clear search button" type="button">',
     "answer": {"needed": False, "operation": "none", "value": ""}},
    {"task": "Open the Tools department.", "log": [], "form": form_line(None),
     "element": '<a href="/b/Tools/N-5yc1vZc1xy"> "Tools"',
     "answer": {"needed": True, "operation": "click", "value": ""}},
    {"task": "Open the Tools department.",
     "log": [log_line(1, "click", "a", 1, False)], "form": form_line(None),
     "element": '<a href="/b/Automotive/N-5yc1vZc8o1"> "Automotive"',
     "answer": {"needed": False, "operation": "none", "value": ""}},
    {"task": "Open the Paint department.", "log": [], "form": form_line(None),
     "element": '<a href="https://www.homedepot.com/b/Paint/N-5yc1vZar2d">',
     "answer": {"needed": False, "operation": "none", "value": ""}},
    {"task": "Open the Paint department.", "log": [], "form": form_line(None),
     "element": '<span> "Paint"',
     "answer": {"needed": True, "operation": "click", "value": ""}},
    {"task": "Open the Reviews tab for these AirPods.", "log": [], "form": form_line(None),
     "element": '<button aria-label="Filter">',
     "answer": {"needed": False, "operation": "none", "value": ""}},
    {"task": "Find the cheapest offer for these AirPods and open it.", "log": [],
     "form": form_line(None),
     "element": '<span> "£144.99"',
     "answer": {"needed": True, "operation": "none", "value": ""}},
    {"task": "Find the cheapest offer for these AirPods and open it.",
     "log": [log_line(1, "none", "span", 12, False)], "form": form_line(None),
     "element": '<button role="tab" type="button"> "Reviews"',
     "answer": {"needed": False, "operation": "none", "value": ""}},
]


def _example(x: dict) -> str:
    return (step_message(x["task"], x["log"], x["element"], x["form"])
            + f"\nAnswer: {json.dumps(x['answer'])}")


STEP_SYSTEM = (
    "You are a web agent planning a task on a web page. You see the page one "
    "element at a time, in page order, as HTML markup, together with the "
    "operations decided so far. Decide whether the task needs the current "
    "element.\n"
    + OPS + "\n"
    "Most elements are not needed. For a single action, choose only the element "
    "that performs it -- not menus, icons, close buttons, or text and images "
    "inside it -- and once it is planned, nothing else is needed. Use \"none\" "
    "only for values the task must compare or copy. A link or button with no "
    "text of its own is labeled by the text inside it, which comes next as "
    "separate elements: do not choose it; choose the text that matches the "
    "task, since clicking text inside a link or button activates it.\n"
    "The Form line, set from the page's structure, says whether the current "
    "element is inside a form and where that form started; the elements after "
    "a form starts belong to it until it ends. A search form needs its field "
    "typed and its submit button clicked. Fill only the fields the task asks "
    "for: a script on the page may have added other fields to a form.\n"
    "Reply with JSON only: {\"needed\": true or false, \"operation\": \"click\" | "
    "\"type\" | \"select\" | \"none\", \"value\": \"text to type or option to "
    "choose, else empty\"}. Mark an element as needed only if the task requires "
    "acting on it or using its content.\n\n"
    "Examples from other sites:\n\n" + "\n\n".join(_example(x) for x in FEW_SHOT))

CHOOSE_SYSTEM = (
    "You help a web agent choose where on a page to do a task. You see several "
    "parts of the page, each as HTML elements, one per line. Reply with JSON "
    "only: {\"part\": N} -- the number of the part where the task can best be "
    "done.")


def chunk(cands, chunk_chars: int = CHUNK_CHARS):
    """Consecutive elements, grouped until their markup reaches chunk_chars."""
    chunks, cur, size = [], [], 0
    for e, m in cands:
        if cur and size + len(m) > chunk_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append((e, m))
        size += len(m) + 1
    if cur:
        chunks.append(cur)
    return chunks


def plan_iterative(rep: dict, prompt: str, llm, chunk_chars: int = CHUNK_CHARS,
                   workers: int = RELEVANCE_WORKERS) -> dict:
    trace = []
    if hasattr(llm, "trace"):
        llm.trace = trace
    cands = candidates(rep)
    by_bni = {e["bni"]: e for e in rep.get("elements", [])}
    forms = {e["bni"]: form_of(e, by_bni) for e, _ in cands}
    form_start: dict = {}  # form bni -> position of its first element
    for i, (e, _) in enumerate(cands):
        if forms[e["bni"]] is not None:
            form_start.setdefault(forms[e["bni"]], i)
    chunks = chunk(cands, chunk_chars)

    def check_chunk(item):
        i, ch = item
        reply, event = logged_call(llm, RELEVANCE_SYSTEM,
            "Part of the page:\n" + "\n".join(m for _, m in ch) + f"\n\nTask: {prompt}",
            trace, "relevance", chunk_index=i)
        relevant = bool(reply.get("relevant"))
        event["decision"] = "kept" if relevant else "discarded"
        return relevant

    with ThreadPoolExecutor(workers) as pool:
        relevant = list(pool.map(check_chunk, enumerate(chunks)))
    kept = [i for i, r in enumerate(relevant) if r]
    chosen = kept[0] if kept else None
    if len(kept) > 1:
        parts = "\n\n".join(f"Part {n}:\n" + "\n".join(m for _, m in chunks[i])
                            for n, i in enumerate(kept, 1))
        try:
            reply, event = logged_call(llm, CHOOSE_SYSTEM, f"{parts}\n\nTask: {prompt}",
                                       trace, "choice", relevant_chunks=kept)
            n = int(reply.get("part"))
        except (TypeError, ValueError):
            n = 0
            event = trace[-1]
        if 1 <= n <= len(kept):
            chosen = kept[n - 1]
        event.update(selected_chunk=chosen,
                     decision="selected" if 1 <= n <= len(kept) else "fallback_first_relevant_chunk")
    pos = {e["bni"]: i for i, (e, _) in enumerate(cands)}
    walk = list(chunks[chosen]) if chosen is not None else []
    if walk:  # the chunk ended inside a form: continue until the form ends
        open_form, j = forms[walk[-1][0]["bni"]], pos[walk[-1][0]["bni"]] + 1
        while open_form is not None and j < len(cands) and forms[cands[j][0]["bni"]] == open_form:
            walk.append(cands[j])
            j += 1
    steps, decided, shown = [], [], 0  # decided: (operation, tag, position, form)
    if walk:
        for e, m in walk:
            here, form = pos[e["bni"]], forms[e["bni"]]
            lines = [log_line(n, op, tag, here - at, f is not None and f == form)
                     for n, (op, tag, at, f) in enumerate(decided, 1)]
            back = None if form is None else here - form_start[form]
            d, event = logged_call(llm, STEP_SYSTEM, step_message(prompt, lines, m, form_line(back)),
                                   trace, "element", bni=e["bni"], element_index=here)
            shown += 1
            event["decision"] = "needed" if d.get("needed") else "not_needed"
            if d.get("needed"):
                op = d.get("operation") or "none"
                steps.append({"bni": e["bni"], "operation": op,
                              "value": saved_value(d), "markup": m,
                              "acts_on": acts_on(e, op, by_bni)})
                event["plan_entries"].append(steps[-1])
                decided.append((op, e.get("tag", ""), here, form))
    return {"steps": steps, "chunks": len(chunks), "relevant_chunks": len(kept),
            "chosen_chunk": chosen, "elements_shown": shown, "trace": trace}


if __name__ == "__main__":
    cli(plan_iterative, "iterative", default_workers=10, doc=__doc__.split("\n\n")[0])
