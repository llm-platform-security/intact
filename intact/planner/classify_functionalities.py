"""Five realistic functionalities of a page, each with the user's request.

LLM-based: one call per page, from the page's stored representation. The model
sees the page as markup only: one element per line with its tag, visible
attributes, and direct text; no ids, provenance, or other labels. It returns
five things real users would ask a web agent to do on the page, with a mix of
interactions (a single action, several actions, or reading the page to decide
what to do), each ending in acting on the page.

Usage:
  python -m intact.planner.classify_functionalities PAGE [PAGE ...] [--out DIR] [--model MODEL]

PAGE is a crawl folder (e.g. kayak.com, under --captures) or a path to a
representation.json. Each page's result is written to DIR/<page>.json.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from intact.planner.planning import OpenRouterLLM
from intact.planner.view import _render_element

MODEL = "openai/gpt-6-luna"
SKIP_TAGS = {"html", "head", "script", "style", "meta", "link", "noscript",
             "template", "base"}
INTERACTIONS = ("single action", "several actions", "read then act")

SYSTEM = ("You identify what real users ask a web agent to do on a web page. "
          "You see the page as HTML elements, one per line.")
INSTRUCTION = (
    "List 5 realistic functionalities of this page: things real users would ask "
    "a web agent to do here. For each, write the request as the user would "
    "phrase it, with concrete values where needed. Use a mix of interactions: "
    "some need a single action (one click or one choice), some need several "
    "actions (for example, filling in a form), and some need reading "
    "information on the page to decide what to do (for example, finding the "
    "cheapest option and opening it). Every request must end in acting on the "
    "page, not in a summary or explanation. Reply with JSON only: "
    "{\"functionalities\": [{\"functionality\": \"short name\", \"prompt\": "
    "\"the user's request\", \"interaction\": \"single action\" | \"several "
    "actions\" | \"read then act\"}]}")


def page_view(rep: dict) -> str:
    """The page as markup only, one element per line, in page order."""
    lines = []
    for e in rep.get("elements", []):
        if e.get("tag") in SKIP_TAGS:
            continue
        line, _ = _render_element(e)
        if line is not None:
            lines.append(re.sub(r"^\[bni=[^\]]*\]\s*", "", line))
    return "\n".join(lines)


def parse_functionalities(reply: dict) -> list[dict]:
    """The first five with distinct, non-empty prompts; fewer is an error."""
    out: list[dict] = []
    for item in reply.get("functionalities") or []:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if not prompt or prompt in (f["prompt"] for f in out):
            continue
        interaction = str(item.get("interaction") or "").strip().lower()
        out.append({"functionality": str(item.get("functionality") or "").strip(),
                    "prompt": prompt,
                    "interaction": interaction if interaction in INTERACTIONS else None})
    if len(out) < 5:
        raise ValueError(f"expected 5 functionalities, got {len(out)}")
    return out[:5]


def classify(rep: dict, llm) -> list[dict]:
    """The page, then the instruction."""
    return parse_functionalities(llm(SYSTEM, f"Page:\n{page_view(rep)}\n\n{INSTRUCTION}"))


def load_rep(page: str, captures: Path) -> dict:
    path = Path(page)
    if path.suffix != ".json":
        path = captures / page / "representation.json"
    return json.loads(path.read_text())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--out", type=Path, default=Path("functionalities"))
    ap.add_argument("--captures", type=Path, default=Path("."))
    ap.add_argument("--model", default=MODEL, help=f"an OpenRouter model (default: {MODEL})")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for page in args.pages:
        rep = load_rep(page, args.captures)
        llm = OpenRouterLLM(args.model)
        functionalities = classify(rep, llm)
        name = Path(page).parent.name if page.endswith(".json") else page
        record = {"page": name, "url": rep.get("url"), "model": args.model,
                  "functionalities": functionalities,
                  "usage": {**llm.usage, "cost_usd": round(llm.usage["cost_usd"], 5)}}
        (args.out / f"{name}.json").write_text(json.dumps(record, indent=1) + "\n")
        print(f"\n{name}  ({llm.usage['tokens_in']:,} tokens in, "
              f"${record['usage']['cost_usd']})")
        for i, f in enumerate(functionalities, 1):
            print(f"  {i}. [{f['interaction']}] {f['prompt']}")


if __name__ == "__main__":
    main()
