"""Collective planning: the model sees the whole page at once.

For each functionality of a page, one call: the page's markup, one element
per line, each tagged [bni=N], followed by the task. The model returns the
steps in the order it would perform them, citing each element's bni, with the
operation (click, type, select, or none = needed only for its content).

Usage:
  python -m intact.planner.plan_collective PAGE [PAGE ...] [--workers N] [--model MODEL]
"""
from __future__ import annotations

from intact.planner.planning import OPS, acts_on, candidates, cli, logged_call, page_view, saved_value

FULL_SYSTEM = (
    "You are a web agent planning a task on a web page. You see the whole page "
    "as HTML elements, one per line, each tagged [bni=N]. Plan the steps in the "
    "order you would perform them.\n" + OPS + "\n"
    "Reply with JSON only: {\"steps\": [{\"bni\": N, \"operation\": \"click\" | "
    "\"type\" | \"select\" | \"none\", \"value\": \"text to type or option to "
    "choose, else empty\"}]}.")


def plan_collective(rep: dict, prompt: str, llm) -> dict:
    trace = []
    if hasattr(llm, "trace"):
        llm.trace = trace
    cands = candidates(rep)
    marks = {e["bni"]: m for e, m in cands}
    by_bni = {e["bni"]: e for e in rep.get("elements", [])}
    reply, event = logged_call(llm, FULL_SYSTEM, f"Page:\n{page_view(cands)}\n\nTask: {prompt}",
                               trace, "collective")
    steps = []
    event["plan_entries"] = steps
    for st in reply.get("steps") or []:
        bni = st.get("bni")
        try:
            bni = int(bni)
        except (TypeError, ValueError):
            pass
        op = st.get("operation") or "none"
        e = by_bni.get(bni)
        steps.append({"bni": bni, "operation": op, "value": saved_value(st),
                      "markup": marks.get(bni, ""),
                      "acts_on": acts_on(e, op, by_bni) if e else None})
    event["decision"] = "plan_built"
    return {"steps": steps, "trace": trace}


if __name__ == "__main__":
    cli(plan_collective, "collective", default_workers=5, doc=__doc__.split("\n\n")[0])
