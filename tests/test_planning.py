"""Iterative and collective planning over stored representations.

Both planners take the LLM as a callable (system, user) -> dict, so these
tests run offline with a fake model.
"""

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from intact.planner import planning as P
from intact.planner.plan_collective import plan_collective
from intact.planner.plan_iterative import chunk, plan_iterative

DOC = {"url": "https://www.shop.com/", "scope": "1p"}


def _el(bni, tag, attrs=None, text=None, parent=None, prov=None):
    e = {"bni": bni, "tag": tag, "attrs": attrs or {}, "document": DOC,
         "parent_bni": parent, "provenance": prov,
         "classification": {"authority": {"effective": ["click"]}}}
    if text is not None:
        e["text"] = text
    return e


REP = {"url": "https://www.shop.com/", "elements": [
    _el(1, "input", {"type": "search", "name": "q"}, prov={"creator": "3p:widgets.net/w.js#1"}),
    _el(2, "button", {"type": "submit"}, text="Search"),
    _el(3, "div"),
    _el(4, "select", {"name": "sort"}),
    _el(5, "option", {"value": "asc"}, text="Price: low to high", parent=4),
    _el(6, "p", text="£144.99"),
    _el(7, "script", {"src": "https://t.net/t.js"}, text="track()"),
]}


# --------------------------------------------------------------------------- #
# shared: the page as markup only
# --------------------------------------------------------------------------- #
def test_candidates_are_markup_only_and_skip_scaffolding():
    cands = P.candidates(REP)
    assert [e["bni"] for e, _ in cands] == [1, 2, 4, 5, 6]
    for _, m in cands:
        for leaked in ("bni", "provenance", "3p:", "scope", "classification", "track()"):
            assert leaked not in m


def test_page_view_tags_each_line_with_its_bni():
    view = P.page_view(P.candidates(REP))
    assert view.splitlines()[0] == '[bni=1] <input type="search" name="q">'
    assert len(view.splitlines()) == 5


# --------------------------------------------------------------------------- #
# iterative planning
# --------------------------------------------------------------------------- #
def test_chunk_splits_by_markup_size():
    cands = P.candidates(REP)
    chunks = chunk(cands, chunk_chars=40)
    assert len(chunks) > 1 and sum(len(c) for c in chunks) == len(cands)


def test_plan_iterative_links_steps_to_bnis_outside_the_llm():
    seen, lock = [], threading.Lock()

    def llm(system, user):
        with lock:
            seen.append(user)
        if "Part of the page" in user:
            return {"relevant": True}
        current = user.rsplit("Current element:\n", 1)[1]
        if "search" in current:
            return {"needed": True, "operation": "type", "value": "shoes"}
        if "£144.99" in current:
            return {"needed": True, "operation": "none", "value": ""}
        if "Search" in current:
            return {"needed": True, "operation": "click", "value": ""}
        return {"needed": False}

    out = plan_iterative(REP, "Search for shoes", llm, chunk_chars=10_000)
    assert [(s["bni"], s["operation"]) for s in out["steps"]] == [(1, "type"), (2, "click"), (6, "none")]
    assert out["steps"][0]["value"] == "shoes"
    assert out["steps"][0]["markup"] == '<input type="search" name="q">'
    assert out["elements_shown"] == 5 and out["relevant_chunks"] == 1
    # the model never sees an id; each element sees only the operations decided
    # before it -- no earlier markup, text, or values
    assert not any("bni" in u for u in seen)
    step_msgs = [u for u in seen if "Current element" in u]

    def log(u):
        return u.split("Operations decided so far:\n")[1].split("\n\nForm:")[0]

    assert log(step_msgs[0]) == "(none)"
    assert log(step_msgs[1]) == "1. type on input, 1 element back"
    assert log(step_msgs[-1]) == "1. type on input, 4 elements back\n2. click on button, 3 elements back"
    assert not any(ch in log(step_msgs[-1]) for ch in '"=<>')  # no earlier markup or values


def test_plan_iterative_skips_irrelevant_chunks():
    def llm(system, user):
        if "Part of the page" in user:
            return {"relevant": False}
        raise AssertionError("no element should be shown")

    out = plan_iterative(REP, "anything", llm, chunk_chars=10_000)
    assert out["steps"] == [] and out["elements_shown"] == 0


# --------------------------------------------------------------------------- #
# collective planning
# --------------------------------------------------------------------------- #
def test_plan_collective_returns_the_models_steps():
    seen = {}

    def llm(system, user):
        seen["user"] = user
        return {"steps": [{"bni": 1, "operation": "type", "value": "shoes"},
                          {"bni": 999, "operation": "click"},
                          {"bni": "2", "operation": "click"}]}

    out = plan_collective(REP, "Search for shoes", llm)
    assert [(s["bni"], s["operation"]) for s in out["steps"]] == [(1, "type"), (999, "click"), (2, "click")]
    assert out["steps"][2]["markup"] == '<button type="submit"> "Search"'
    # the page, then the task
    assert seen["user"].startswith("Page:\n[bni=1]")
    assert seen["user"].rstrip().endswith("Task: Search for shoes")


# --------------------------------------------------------------------------- #
# running over stored pages and their functionalities
# --------------------------------------------------------------------------- #
def test_plan_pages_writes_one_file_per_page(tmp_path):
    (tmp_path / "caps" / "shop.com").mkdir(parents=True)
    (tmp_path / "caps" / "shop.com" / "representation.json").write_text(json.dumps(REP))
    (tmp_path / "funcs").mkdir()
    funcs = [{"functionality": f"f{i}", "prompt": f"task {i}", "interaction": "single action"}
             for i in range(5)]
    (tmp_path / "funcs" / "shop.com.json").write_text(json.dumps({"functionalities": funcs}))

    class FakeLLM:
        def __init__(self):
            self.usage = {"calls": 1, "cost_usd": 0.001}

    def planner(rep, prompt, llm):
        return {"steps": [{"bni": 1, "operation": "click", "value": "", "markup": prompt}]}

    paths = P.plan_pages(["shop.com"], planner, "collective", captures=tmp_path / "caps",
                         functionalities=tmp_path / "funcs", out=tmp_path / "out",
                         workers=3, llm_factory=FakeLLM)
    record = json.loads(paths[0].read_text())
    assert paths[0] == tmp_path / "out" / "collective" / "shop.com.json"
    assert record["mode"] == "collective" and record["url"] == REP["url"]
    assert [p["prompt"] for p in record["plans"]] == [f"task {i}" for i in range(5)]
    assert record["plans"][0]["steps"][0]["markup"] == "task 0"
    assert record["plans"][0]["usage"]["cost_usd"] == 0.001


def test_plan_one_records_a_plan_and_a_planner_failure():
    """One stored functionality's plan as plan_pages saves it: the
    functionality, the planner's result, then the usage (cost rounded, time
    taken). A planner failure keeps the trace so far and the error."""
    class FakeLLM:
        def __init__(self):
            self.usage = {"calls": 2, "cost_usd": 0.0012345678}

    f = {"functionality": "Search", "prompt": "Search for shoes", "interaction": "several actions"}

    def planner(rep, prompt, llm):
        assert rep is REP and prompt == f["prompt"] and llm.trace == []
        return {"steps": [{"bni": 1}], "chosen_chunk": 0}

    plan = P.plan_one(REP, f, planner, FakeLLM)
    assert list(plan) == ["functionality", "prompt", "interaction", "steps", "chosen_chunk", "usage"]
    assert plan["functionality"] == "Search" and plan["interaction"] == "several actions"
    assert list(plan["usage"]) == ["calls", "cost_usd", "seconds"]
    assert plan["usage"]["calls"] == 2 and plan["usage"]["cost_usd"] == 0.00123
    assert isinstance(plan["usage"]["seconds"], float)

    def failing(rep, prompt, llm):
        llm.trace.append({"stage": "relevance"})
        raise RuntimeError("API down")

    plan = P.plan_one(REP, {"prompt": "Search"}, failing, FakeLLM)
    assert plan == {"functionality": None, "prompt": "Search", "interaction": None, "steps": [],
                    "error": "RuntimeError: API down", "trace": [{"stage": "relevance"}],
                    "usage": {"calls": 2, "cost_usd": 0.00123, "seconds": plan["usage"]["seconds"]}}


# --------------------------------------------------------------------------- #
# robustness: retry calls that come back without an answer; resume runs
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, content=None, error=None):
        self.choices = None if content is None else [
            type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = None
        self.model_extra = {"error": error} if error else {}


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        return self.responses.pop(0)


def test_llm_retries_a_call_without_an_answer(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    llm = P.OpenRouterLLM(client=_Client([_Resp(error={"code": 429}), _Resp('{"relevant": true}')]))
    assert llm("sys", "user") == {"relevant": True}
    assert len(llm.last_reply["attempt_errors"]) == 1
    assert llm.last_reply["raw_reply"] == '{"relevant": true}'


def test_llm_reports_the_api_error_after_the_last_retry(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    llm = P.OpenRouterLLM(client=_Client([_Resp(error={"code": 429, "message": "rate limited"})] * 3))
    try:
        llm("sys", "user")
    except RuntimeError as exc:
        assert "rate limited" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_plan_pages_replans_only_missing_or_failed_plans(tmp_path):
    (tmp_path / "caps" / "shop.com").mkdir(parents=True)
    (tmp_path / "caps" / "shop.com" / "representation.json").write_text(json.dumps(REP))
    (tmp_path / "funcs").mkdir()
    funcs = [{"functionality": f"f{i}", "prompt": f"task {i}"} for i in range(5)]
    (tmp_path / "funcs" / "shop.com.json").write_text(json.dumps({"functionalities": funcs}))
    old = [{"prompt": f"task {i}", "steps": [{"bni": 9}], "usage": {}} for i in range(5)]
    old[2] = {"prompt": "task 2", "steps": [], "error": "TypeError", "usage": {}}
    (tmp_path / "out" / "iterative").mkdir(parents=True)
    (tmp_path / "out" / "iterative" / "shop.com.json").write_text(json.dumps({"plans": old}))

    class FakeLLM:
        usage = {"calls": 1, "cost_usd": 0.0}

    planned = []

    def planner(rep, prompt, llm):
        planned.append(prompt)
        return {"steps": [{"bni": 1}]}

    paths = P.plan_pages(["shop.com"], planner, "iterative", captures=tmp_path / "caps",
                         functionalities=tmp_path / "funcs", out=tmp_path / "out",
                         workers=2, llm_factory=FakeLLM)
    plans = json.loads(paths[0].read_text())["plans"]
    assert planned == ["task 2"]
    assert [p["steps"][0]["bni"] for p in plans] == [9, 9, 1, 9, 9]
    assert not any(p.get("error") for p in plans)


# --------------------------------------------------------------------------- #
# two steps: pick the most appropriate relevant chunk, then walk only it
# --------------------------------------------------------------------------- #
def _chunk_llm(seen, part):
    def llm(system, user):
        seen.append(user)
        if "Part of the page" in user:
            page_part = user.split("\n\nTask:")[0]
            return {"relevant": any(k in page_part for k in ("search", "Search", "£144.99"))}
        if user.startswith("Part 1:"):
            return {"part": part}
        current = user.rsplit("Current element:\n", 1)[1]
        return {"needed": True, "operation": "none" if "£" in current else "click", "value": ""}
    return llm


def test_plan_iterative_walks_only_the_chosen_chunk():
    seen = []
    # one element per chunk; chunks with the input, the button, and the price are relevant
    out = plan_iterative(REP, "Click search", _chunk_llm(seen, part=2), chunk_chars=40, workers=1)
    choose = [u for u in seen if u.startswith("Part 1:")]
    assert len(choose) == 1
    assert 'Part 1:\n<input type="search" name="q">' in choose[0]
    assert 'Part 3:\n<p> "£144.99"' in choose[0] and "Part 4:" not in choose[0]
    assert out["relevant_chunks"] == 3 and out["chosen_chunk"] == 1
    assert [(s["bni"], s["operation"]) for s in out["steps"]] == [(2, "click")]
    assert out["elements_shown"] == 1


def test_plan_iterative_falls_back_to_the_first_relevant_chunk():
    out = plan_iterative(REP, "Click search", _chunk_llm([], part=7), chunk_chars=40, workers=1)
    assert out["chosen_chunk"] == 0 and [s["bni"] for s in out["steps"]] == [1]


def test_plan_iterative_skips_the_choice_with_one_relevant_chunk():
    seen = []
    plan_iterative(REP, "Click search", _chunk_llm(seen, part=1), chunk_chars=10_000)
    assert not any(u.startswith("Part 1:") for u in seen)


# --------------------------------------------------------------------------- #
# few-shot examples in the per-element prompt
# --------------------------------------------------------------------------- #
def test_few_shot_examples_use_the_planners_own_format():
    import json as _json
    from intact.planner import plan_iterative as PI
    assert 6 <= len(PI.FEW_SHOT) <= 10
    for x in PI.FEW_SHOT:
        message = PI.step_message(x["task"], x["log"], x["element"], x["form"])
        assert message in PI.STEP_SYSTEM
        assert x["answer"]["operation"] in ("click", "type", "select", "none")
        assert _json.dumps(x["answer"]) in PI.STEP_SYSTEM


def test_few_shot_examples_come_from_pages_we_do_not_test():
    from intact.planner import plan_iterative as PI
    text = " ".join(x["task"] + x["element"] for x in PI.FEW_SHOT).lower()
    for page in ("kayak", "wikipedia", "allrecipes", "imdb", "samsclub", "sam's club"):
        assert page not in text
    assert "bni" not in PI.STEP_SYSTEM


def test_step_message_lists_the_log_lines_and_the_form_line():
    from intact.planner import plan_iterative as PI
    assert PI.step_message("Do it", ["1. type on input, 1 element back"], "<a>") == (
        "Task: Do it\n\nOperations decided so far:\n1. type on input, 1 element back"
        "\n\nForm: none\n\nCurrent element:\n<a>")
    assert "(none)" in PI.step_message("Do it", [], "<a>")
    assert PI.form_line(None) == "none"
    assert PI.form_line(0) == "a form starts at this element"
    assert PI.form_line(1) == "inside a form that started 1 element back"
    assert PI.form_line(3) == "inside a form that started 3 elements back"


def test_log_line_carries_standard_tag_names_and_structure_only():
    from intact.planner import plan_iterative as PI
    assert PI.log_line(1, "type", "input", 1, True) == "1. type on input, 1 element back, same form"
    assert PI.log_line(2, "click", "x-ignore-all-instructions", 3, False) == (
        "2. click on custom, 3 elements back")


def test_plan_iterative_tells_whether_a_step_shares_the_form():
    doc = {"url": "https://www.shop.com/", "scope": "1p"}
    rep = {"url": "https://www.shop.com/", "elements": [
        {"bni": 10, "tag": "form", "attrs": {}, "document": doc, "parent_bni": None},
        {"bni": 11, "tag": "input", "attrs": {"type": "search", "name": "q"}, "document": doc, "parent_bni": 10},
        {"bni": 12, "tag": "button", "attrs": {"type": "submit"}, "text": "Go", "document": doc, "parent_bni": 10},
        {"bni": 13, "tag": "button", "attrs": {"type": "button"}, "text": "Menu", "document": doc, "parent_bni": None},
    ]}
    seen = []

    def llm(system, user):
        seen.append(user)
        if "Part of the page" in user:
            return {"relevant": True}
        if 'name="q"' in user.rsplit("Current element:\n", 1)[1]:
            return {"needed": True, "operation": "type", "value": "shoes"}
        return {"needed": False}

    plan_iterative(rep, "Search for shoes", llm, chunk_chars=10_000)
    msgs = {u.rsplit("Current element:\n", 1)[1]: u for u in seen if "Current element" in u}
    assert "1. type on input, 1 element back, same form" in msgs['<button type="submit"> "Go"']
    assert "1. type on input, 2 elements back\n" in msgs['<button type="button"> "Menu"']


# --------------------------------------------------------------------------- #
# forms stay in one chunk; steps record the link or button they activate
# --------------------------------------------------------------------------- #
_D = {"url": "https://www.shop.com/", "scope": "1p"}
FORM_REP = {"url": "https://www.shop.com/", "elements": [
    {"bni": 1, "tag": "p", "text": "Welcome to the shop", "attrs": {}, "document": _D, "parent_bni": None},
    {"bni": 10, "tag": "form", "attrs": {}, "document": _D, "parent_bni": None},
    {"bni": 11, "tag": "input", "attrs": {"type": "search", "name": "q"}, "document": _D, "parent_bni": 10},
    {"bni": 12, "tag": "select", "attrs": {"name": "lang"}, "document": _D, "parent_bni": 10},
    {"bni": 13, "tag": "button", "attrs": {"type": "submit"}, "text": "Search", "document": _D, "parent_bni": 10},
    {"bni": 20, "tag": "a", "attrs": {"href": "/c?cat=zip"}, "document": _D, "parent_bni": None},
    {"bni": 21, "tag": "span", "text": "free", "attrs": {}, "document": _D, "parent_bni": 20},
    {"bni": 30, "tag": "p", "text": "About us", "attrs": {}, "document": _D, "parent_bni": None},
]}


def test_chunk_cuts_by_size_only():
    chunks = chunk(P.candidates(FORM_REP), chunk_chars=10)
    assert [[e["bni"] for e, _ in c] for c in chunks] == [[1], [11], [12], [13], [20], [21], [30]]


def _form_llm(seen, relevant_marker):
    def llm(system, user):
        if "Part of the page" in user:
            return {"relevant": relevant_marker in user.split("\n\nTask:")[0]}
        seen.append(user)
        return {"needed": False}
    return llm


def test_walk_continues_past_the_chunk_until_the_form_ends():
    seen = []
    # one element per chunk; only the chunk with the search field is relevant
    out = plan_iterative(FORM_REP, "Search for shoes", _form_llm(seen, 'name="q"'), chunk_chars=10)
    shown = [u.rsplit("Current element:\n", 1)[1] for u in seen]
    assert shown == ['<input type="search" name="q">', '<select name="lang">',
                     '<button type="submit"> "Search"']
    assert out["elements_shown"] == 3


def test_form_line_is_set_by_the_page_structure():
    seen = []
    plan_iterative(FORM_REP, "anything", _form_llm(seen, "<"), chunk_chars=10_000)
    form = {u.rsplit("Current element:\n", 1)[1]: u.split("Form: ")[1].split("\n")[0] for u in seen}
    assert form['<input type="search" name="q">'] == "a form starts at this element"
    assert form['<select name="lang">'] == "inside a form that started 1 element back"
    assert form['<button type="submit"> "Search"'] == "inside a form that started 2 elements back"
    assert form['<p> "About us"'] == "none"


def test_acts_on_is_the_link_or_button_a_click_activates():
    by = {e["bni"]: e for e in FORM_REP["elements"]}
    assert P.acts_on(by[21], "click", by) == 20   # text inside a link
    assert P.acts_on(by[13], "click", by) == 13   # a button itself
    assert P.acts_on(by[11], "type", by) == 11    # typing acts on the field
    assert P.acts_on(by[30], "click", by) is None  # plain text activates nothing
    assert P.acts_on(by[21], "none", by) is None


def test_both_planners_record_acts_on():
    def iterative_llm(system, user):
        if "Part of the page" in user:
            return {"relevant": "free" in user.split("\n\nTask:")[0]}
        if user.rsplit("Current element:\n", 1)[1] == '<span> "free"':
            return {"needed": True, "operation": "click", "value": ""}
        return {"needed": False}

    out = plan_iterative(FORM_REP, "Show free stuff", iterative_llm, chunk_chars=10_000)
    assert [(s["bni"], s["acts_on"]) for s in out["steps"]] == [(21, 20)]

    out = plan_collective(FORM_REP, "Show free stuff",
                          lambda system, user: {"steps": [{"bni": 21, "operation": "click"}]})
    assert [(s["bni"], s["acts_on"]) for s in out["steps"]] == [(21, 20)]


def test_prompt_teaches_to_choose_the_label_of_an_unlabeled_link():
    from intact.planner import plan_iterative as PI
    assert "no text of its own" in PI.STEP_SYSTEM
    unlabeled = [x for x in PI.FEW_SHOT if x["element"].startswith("<a ") and '"' not in x["element"].split(">", 1)[1]]
    assert unlabeled and not unlabeled[0]["answer"]["needed"]


# --------------------------------------------------------------------------- #
# default audit trail: raw reply -> parsed fields -> plan entries
# --------------------------------------------------------------------------- #
def test_default_iterative_trace_records_rejected_and_accepted_raw_replies():
    rep = {"elements": [REP["elements"][0], REP["elements"][1]]}
    raw = ['{"relevant": true}',
           '{"needed": false, "operation": "type", "value": "discarded"}',
           'Answer: {"needed": true, "operation": "click", "value": ""}']
    llm = P.OpenRouterLLM(client=_Client([_Resp(s) for s in raw]))
    plan = plan_iterative(rep, "Search", llm, chunk_chars=10_000, workers=1)
    trace = plan["trace"]
    assert [e["raw_reply"] for e in trace] == raw
    assert [e["stage"] for e in trace] == ["relevance", "element", "element"]
    assert trace[0]["chunk_index"] == 0 and trace[0]["decision"] == "kept"
    assert trace[1]["bni"] == 1
    assert trace[1]["parsed_fields"]["operation"] == "type"
    assert trace[1]["decision"] == "not_needed" and trace[1]["plan_entries"] == []
    assert trace[2]["parse_status"] == "extracted_json"
    assert trace[2]["plan_entries"] == plan["steps"]
    assert plan["steps"][0]["bni"] == 2
    assert all("bni" not in e["request"]["user"] for e in trace)


def test_default_trace_distinguishes_invalid_json_from_missing_needed():
    rep = {"elements": [REP["elements"][0], REP["elements"][1]]}
    llm = P.OpenRouterLLM(client=_Client([_Resp('{"relevant": true}'),
        _Resp('not JSON'), _Resp('{"operation": "click"}')]))
    plan = plan_iterative(rep, "Search", llm, chunk_chars=10_000, workers=1)
    decisions = [e for e in plan["trace"] if e["stage"] == "element"]
    assert plan["steps"] == []
    assert decisions[0]["raw_reply"] == "not JSON"
    assert decisions[0]["parse_status"] == "invalid_json"
    assert decisions[0]["parsed_fields"] == {}
    assert decisions[1]["parse_status"] == "json"
    assert decisions[1]["parsed_fields"] == {"operation": "click"}
    assert all(e["decision"] == "not_needed" for e in decisions)


def test_parallel_relevance_trace_binds_raw_replies_to_their_chunk():
    class Client:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": self})()
        def create(self, **kwargs):
            user = kwargs["messages"][1]["content"]
            if user.startswith("Part of the page:"):
                return _Resp(json.dumps({"relevant": False, "echo": user}))
            raise AssertionError("No element should be shown")
    llm = P.OpenRouterLLM(client=Client())
    plan = plan_iterative(REP, "Search", llm, chunk_chars=40, workers=4)
    assert len(plan["trace"]) == plan["chunks"]
    assert sorted(e["chunk_index"] for e in plan["trace"]) == list(range(plan["chunks"]))
    for e in plan["trace"]:
        assert json.loads(e["raw_reply"])["echo"] == e["request"]["user"]
        assert e["decision"] == "discarded"


def test_choice_trace_records_invalid_part_and_actual_fallback():
    plan = plan_iterative(REP, "Search", _chunk_llm([], part=7), chunk_chars=40, workers=1)
    choice = next(e for e in plan["trace"] if e["stage"] == "choice")
    assert choice["parsed_fields"] == {"part": 7}
    assert choice["selected_chunk"] == plan["chosen_chunk"] == 0
    assert choice["decision"] == "fallback_first_relevant_chunk"
    assert choice["raw_reply"] is None and choice["parse_status"] == "unavailable"


def test_default_collective_trace_records_raw_fields_and_normalized_steps():
    raw = '{"steps": [{"bni": "2", "operation": "click"}, {"bni": 999, "operation": "type", "value": "x"}]}'
    plan = plan_collective(REP, "Search", P.OpenRouterLLM(client=_Client([_Resp(raw)])))
    event, = plan["trace"]
    assert event["raw_reply"] == raw and event["parse_status"] == "json"
    assert event["parsed_fields"]["steps"][0]["bni"] == "2"
    assert event["plan_entries"] == plan["steps"]
    assert event["plan_entries"][0]["bni"] == 2
    assert event["plan_entries"][1]["bni"] == 999


def test_plan_pages_saves_trace_when_a_later_model_call_fails(tmp_path):
    (tmp_path / "caps" / "shop.com").mkdir(parents=True)
    (tmp_path / "caps" / "shop.com" / "representation.json").write_text(json.dumps(
        {"elements": [REP["elements"][0], REP["elements"][1]]}))
    (tmp_path / "funcs").mkdir()
    (tmp_path / "funcs" / "shop.com.json").write_text(json.dumps(
        {"functionalities": [{"prompt": "Search"}]}))
    client = _Client([_Resp('{"relevant": true}'),
                     _Resp('{"needed": true, "operation": "type", "value": "shoes"}'),
                     _Resp(error={"message": "test failure"})])
    paths = P.plan_pages(["shop.com"], plan_iterative, "iterative",
        captures=tmp_path / "caps", functionalities=tmp_path / "funcs",
        out=tmp_path / "out", workers=1,
        llm_factory=lambda: P.OpenRouterLLM(client=client, retries=1))
    plan = json.loads(paths[0].read_text())["plans"][0]
    assert "test failure" in plan["error"]
    assert plan["trace"][1]["plan_entries"][0]["value"] == "shoes"
    assert plan["trace"][-1]["decision"] == "model_call_failed"
    assert "test failure" in plan["trace"][-1]["error"]


# --------------------------------------------------------------------------- #
# crash safety: each page's record is written whole, finished, and at once
# --------------------------------------------------------------------------- #
def _pages(tmp_path, sites, tasks=1):
    """The captures (each the page REP) and stored functionalities of `sites`:
    plan_pages' keyword arguments for them."""
    for site in sites:
        (tmp_path / "caps" / site).mkdir(parents=True)
        (tmp_path / "caps" / site / "representation.json").write_text(json.dumps(REP))
    (tmp_path / "funcs").mkdir()
    for site in sites:
        (tmp_path / "funcs" / f"{site}.json").write_text(json.dumps(
            {"functionalities": [{"prompt": f"{site} task {i}"} for i in range(tasks)]}))
    return dict(captures=tmp_path / "caps", functionalities=tmp_path / "funcs", out=tmp_path / "out")


class _Counted:
    def __init__(self):
        self.usage = {"calls": 1, "cost_usd": 0.0}


def test_plan_pages_writes_each_record_finished_as_soon_as_its_page_is_planned(tmp_path):
    """The finisher completes a page's record (e.g., with the model and the
    page's hash) before the record is written, in write_json's bytes: when
    the next page's planning is interrupted, the first page's record is
    already whole and finished, and no temporary file is left."""
    kw = _pages(tmp_path, ["a.com", "b.com"])
    finished = threading.Event()

    def planner(rep, prompt, llm):
        if prompt.startswith("b.com"):
            assert finished.wait(timeout=60), "a.com's record was never finished"
            raise KeyboardInterrupt  # as Ctrl-C would, once a.com is planned
        return {"steps": [{"bni": 1}]}

    def finish(page, record):
        record.update(model="the model", stamp=f"finished {page}")
        finished.set()
        return record

    with pytest.raises(KeyboardInterrupt):
        P.plan_pages(["a.com", "b.com"], planner, "iterative", workers=1, llm_factory=_Counted,
                     finish=finish, **kw)
    folder = tmp_path / "out" / "iterative"
    assert [p.name for p in folder.iterdir()] == ["a.com.json"]
    record = json.loads((folder / "a.com.json").read_text())
    assert list(record) == ["page", "url", "model", "mode", "plans", "stamp"]
    assert (record["model"], record["stamp"]) == ("the model", "finished a.com")
    assert (folder / "a.com.json").read_text() == json.dumps(record, indent=1, ensure_ascii=False) + "\n"
    # Without a finisher, the record as before.
    [path] = P.plan_pages(["a.com"], lambda rep, prompt, llm: {"steps": []}, "collective", workers=1,
                          llm_factory=_Counted, **kw)
    assert list(json.loads(path.read_text())) == ["page", "url", "model", "mode", "plans"]


def test_plan_pages_replaces_a_record_atomically(monkeypatch, tmp_path):
    """A record goes to a temporary file in its folder, which then replaces
    it: a failure before the replace leaves no part of a record (here, none
    at all) and no temporary file."""
    kw = _pages(tmp_path, ["a.com"])

    def crash(source, target):
        raise OSError("crash before the replace")
    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="crash before the replace"):
        P.plan_pages(["a.com"], lambda rep, prompt, llm: {"steps": []}, "iterative", workers=1,
                     llm_factory=_Counted, **kw)
    assert list((tmp_path / "out" / "iterative").iterdir()) == []


def test_plan_pages_cancels_the_queued_plans_when_interrupted(monkeypatch, tmp_path):
    """An interrupt while plans are pending (here while waiting for the first,
    as Ctrl-C would come) cancels the plans still queued, rather than making
    every one of them before the interrupt reaches the caller. The first
    plan returns only once the others are cancelled (or after a few seconds,
    so that without the cancel it does not hang)."""
    kw = _pages(tmp_path, ["a.com"], tasks=5)
    submitted, planned = [], []

    class Pool(P.ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            submitted.append(super().submit(fn, *args, **kwargs))
            return submitted[-1]

    def interrupted(futures):
        raise KeyboardInterrupt
        yield  # a generator, as as_completed is

    def planner(rep, prompt, llm):
        planned.append(prompt)
        deadline = time.monotonic() + 3
        while (len(planned) == 1 and (len(submitted) < 5 or not all(f.cancelled() for f in submitted[1:]))
               and time.monotonic() < deadline):
            threading.Event().wait(0.01)
        return {"steps": []}

    monkeypatch.setattr(P, "ThreadPoolExecutor", Pool)
    monkeypatch.setattr(P, "as_completed", interrupted)
    with pytest.raises(KeyboardInterrupt):
        P.plan_pages(["a.com"], planner, "iterative", workers=1, llm_factory=_Counted, **kw)
    assert planned == ["a.com task 0"]
    assert len(submitted) == 5 and all(f.cancelled() for f in submitted[1:])


# --------------------------------------------------------------------------- #
# each call's usage and identity, recorded with it (recording only: the
# request the model sees is today's, byte for byte)
# --------------------------------------------------------------------------- #
TODAYS_REQUEST = (
    '{"model": "openai/gpt-6-luna", "response_format": {"type": "json_object"}, "messages": [{"role": "system", '
    '"content": "System text ü"}, {"role": "user", "content": "User text\\nwith a newline"}], "extra_body": '
    '{"reasoning": {"effort": "low"}, "usage": {"include": true}}}')


class _Billed(_Resp):
    """A response as the OpenAI SDK gives OpenRouter's: the usage (the cost
    an extra field), the model that answered, and the provider (an extra
    field), when given."""
    def __init__(self, content, *, tokens=(1200, 300, 15), cost=0.00042, model="openai/gpt-6-luna-20260901",
                 provider="OpenAI"):
        super().__init__(content)
        prompt, cached, completion = tokens
        self.usage = type("Usage", (), {"prompt_tokens": prompt, "completion_tokens": completion,
                                        "prompt_tokens_details": type("Details", (), {"cached_tokens": cached})(),
                                        "model_extra": {"cost": cost}})()
        self.model = model
        self.model_extra = {"provider": provider} if provider else {}


class _Recording(_Client):
    def __init__(self, responses):
        super().__init__(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return super().create(**kwargs)


def test_each_call_records_its_usage_model_provider_and_time_and_sends_todays_request(monkeypatch):
    """OpenRouterLLM records, for every call, the call's usage as the API
    reports it (tokens_in, cached_in, tokens_out, cost_usd), the model that
    answered, the provider when the response names one, and when the call
    was made (UTC); logged_call puts them on the call's trace event. The
    requests, retries included, are today's bytes."""
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    client = _Recording([_Resp(error={"code": 429}), _Billed('{"needed": true}')])
    llm = P.OpenRouterLLM(client=client)
    before = datetime.now(timezone.utc)
    assert llm("System text ü", "User text\nwith a newline") == {"needed": True}
    assert [json.dumps(r, ensure_ascii=False) for r in client.requests] == [TODAYS_REQUEST] * 2
    reply = llm.last_reply
    assert reply["usage"] == {"tokens_in": 1200, "cached_in": 300, "tokens_out": 15, "cost_usd": 0.00042}
    assert (reply["model"], reply["provider"]) == ("openai/gpt-6-luna-20260901", "OpenAI")
    called = datetime.fromisoformat(reply["called_at"])
    assert called.utcoffset() == timedelta(0) and before - timedelta(seconds=1) <= called <= datetime.now(timezone.utc)
    assert len(reply["attempt_errors"]) == 1
    assert llm.usage == {"calls": 1, "tokens_in": 1200, "cached_in": 300, "tokens_out": 15, "cost_usd": 0.00042}
    # What the API does not report is not invented: a usage without a cost,
    unpriced = P.OpenRouterLLM(client=_Client([_Billed('{"x": 1}', cost=None)]))
    unpriced("s", "u")
    assert unpriced.last_reply["usage"] == {"tokens_in": 1200, "cached_in": 300, "tokens_out": 15, "cost_usd": None}
    assert unpriced.usage["cost_usd"] == 0.0  # the plan's total, as before
    # and a response without usage, model, or provider.
    bare = P.OpenRouterLLM(client=_Client([_Resp('{"x": 1}')]))
    bare("s", "u")
    assert bare.last_reply["usage"] is None and bare.last_reply["model"] is None
    assert "provider" not in bare.last_reply and "called_at" in bare.last_reply
    # On every trace event.
    plain = P.OpenRouterLLM(client=_Client([_Billed('{"relevant": true}', cost=0.0001, provider=None)]))
    _, event = P.logged_call(plain, "sys", "user", [], "relevance")
    assert event["usage"] == {"tokens_in": 1200, "cached_in": 300, "tokens_out": 15, "cost_usd": 0.0001}
    assert event["model"] == "openai/gpt-6-luna-20260901" and "provider" not in event and event["called_at"]


def test_a_call_that_fails_records_when_it_was_made_and_no_usage():
    client = _Client([_Resp(error={"code": 500, "message": "down"})])
    llm = P.OpenRouterLLM(client=client, retries=1)
    trace = []
    with pytest.raises(RuntimeError, match="down"):
        P.logged_call(llm, "sys", "user", trace, "element")
    event, = trace
    assert event["decision"] == "model_call_failed" and event["called_at"]
    assert event["usage"] is None and event["model"] is None


# --------------------------------------------------------------------------- #
# step values: each planner saves the model's value as
# given, "" only when it is missing or null; no saved value is ever sent
# --------------------------------------------------------------------------- #
MISSING = object()  # a reply without a value
# (the model's value, the value saved), falsy values included
SAVED_VALUES = [("PLANNED-VALUE", "PLANNED-VALUE"), ("", ""), (0, 0), (0.0, 0.0), (False, False), ([], []),
                ({}, {}), (None, ""), (MISSING, "")]


def _with_value(value, **fields):
    """A reply, or one step of a whole-page reply, with `value` (none at all
    for MISSING)."""
    return {**fields, **({} if value is MISSING else {"value": value})}


def _valued_model(value):
    """A fake model for REP whose every step carries `value`: every part of
    the page is relevant; the walk types into the search box, clicks the
    button, and chooses in the select, and the whole-page plan does the same
    by ID."""
    def model(system, user):
        if user.startswith("Part of the page:"):
            return {"relevant": True}
        if user.startswith("Part 1:"):
            return {"part": 1}
        if user.startswith("Page:"):
            return {"steps": [_with_value(value, bni=bni, operation=op)
                              for bni, op in ((1, "type"), (2, "click"), (4, "select"))]}
        current = user.rsplit("Current element:\n", 1)[1]
        for marker, op in (('name="q"', "type"), ('"Search"', "click"), ('name="sort"', "select")):
            if marker in current:
                return _with_value(value, needed=True, operation=op)
        return {"needed": False}
    return model


def _same(value, saved):
    """`value` is `saved`, of its type too (0, 0.0, and false are equal in Python)."""
    return type(value) is type(saved) and value == saved


class _ValuedLLM(_Counted):
    """_valued_model with the usage that plan_pages records."""
    def __init__(self, value):
        super().__init__()
        self.model = _valued_model(value)

    def __call__(self, system, user):
        return self.model(system, user)


@pytest.mark.parametrize("value, saved", SAVED_VALUES)
def test_both_planners_save_the_models_value_as_given(tmp_path, value, saved):
    """0 is saved as 0, 0.0 as 0.0, and false, [], and {} as given; "" only
    for a null value or none at all. The trace records the saved steps, and
    the plan record holds the values as JSON."""
    model = _valued_model(value)
    iterative = plan_iterative(REP, "Search for shoes", model, chunk_chars=10_000, workers=1)
    collective = plan_collective(REP, "Search for shoes", model)
    for plan in (iterative, collective):
        assert [(s["bni"], s["operation"]) for s in plan["steps"]] == [(1, "type"), (2, "click"), (4, "select")]
        assert all(_same(s["value"], saved) for s in plan["steps"])
        assert [s for e in plan["trace"] for s in e["plan_entries"]] == plan["steps"]
    kw = _pages(tmp_path, ["shop.com"])
    for planner, mode in ((plan_iterative, "iterative"), (plan_collective, "collective")):
        [path] = P.plan_pages(["shop.com"], planner, mode, workers=1, llm_factory=lambda: _ValuedLLM(value), **kw)
        [plan] = json.loads(path.read_text())["plans"]
        assert len(plan["steps"]) == 3 and all(_same(s["value"], saved) for s in plan["steps"])


def test_no_saved_value_reaches_a_later_request():
    """The markup-only rule: whatever value the model returns, falsy ones
    included, each planner's requests are the same, byte for byte. The
    walk's later calls see the current element's markup and the names of the
    operations decided so far, never a value; the whole-page plan's one call
    comes before any value."""
    def requests(planner, value, **kw):
        seen, model = [], _valued_model(value)

        def llm(system, user):
            seen.append((system, user))
            return model(system, user)
        assert len(planner(REP, "Search for shoes", llm, **kw)["steps"]) == 3
        return seen

    for planner, kw in ((plan_iterative, {"chunk_chars": 10_000, "workers": 1}), (plan_collective, {})):
        baseline = requests(planner, "PLANNED-VALUE", **kw)
        assert not any("PLANNED-VALUE" in system + user for system, user in baseline)
        for value, _ in SAVED_VALUES:
            assert requests(planner, value, **kw) == baseline
    walk = requests(plan_iterative, 0, chunk_chars=10_000, workers=1)
    assert len(walk) == 6 and walk[-1][1].split("Operations decided so far:\n")[1].split("\n\nForm:")[0] == (
        "1. type on input, 4 elements back\n2. click on button, 3 elements back\n3. select on select, 2 elements back")


class _Answering:
    """A fake API client that answers each request as `model` does, as JSON
    text, and records the bytes of every request it is sent."""
    def __init__(self, model):
        self.model, self.sent, self.lock = model, [], threading.Lock()
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        with self.lock:
            self.sent.append(json.dumps(kwargs, ensure_ascii=False))
        system, user = (m["content"] for m in kwargs["messages"])
        return _Resp(json.dumps(self.model(system, user)))


def test_plan_pages_sends_the_same_bytes_whatever_the_values(tmp_path):
    """As plan_pages sends them through OpenRouterLLM, with the replies
    parsed from JSON text, for two tasks of a page: the same requests for
    every value, and the plan records hold the values as given."""
    kw = _pages(tmp_path, ["shop.com"], tasks=2)
    sent = []
    for n, (value, saved) in enumerate(SAVED_VALUES):
        client = _Answering(_valued_model(value))
        kw["out"] = tmp_path / f"out{n}"
        for planner, mode in ((plan_iterative, "iterative"), (plan_collective, "collective")):
            [path] = P.plan_pages(["shop.com"], planner, mode, workers=1,
                                  llm_factory=lambda: P.OpenRouterLLM(client=client), **kw)
            plans = json.loads(path.read_text())["plans"]
            assert [len(p["steps"]) for p in plans] == [3, 3]
            assert all(_same(s["value"], saved) for p in plans for s in p["steps"])
        sent.append(sorted(client.sent))  # the relevance checks run in parallel
    assert len(sent[0]) == 2 * (1 + 5) + 2  # per task: one relevance check and five elements; then two whole-page calls
    assert all(requests == sent[0] for requests in sent)


# --------------------------------------------------------------------------- #
# run_each: independent jobs, a few at a time, that stop at the first failure
# --------------------------------------------------------------------------- #
def test_run_each_with_one_worker_is_a_loop_that_stops_at_the_first_failure():
    """One worker: the items in their order, one after another, and none
    after the first that fails, whose error is raised."""
    done = []

    def work(item):
        done.append(item)
        if item == 2:
            raise ValueError("item 2 failed")
    with pytest.raises(ValueError, match="item 2 failed"):
        P.run_each(range(6), work, workers=1)
    assert done == [0, 1, 2]
    done.clear()
    assert P.run_each(["a", "b", "c"], done.append, workers=1) is None
    assert done == ["a", "b", "c"]
    P.run_each([], lambda item: pytest.fail("no item"), workers=3)
    for workers in (0, -1):
        with pytest.raises(ValueError, match="workers"):
            P.run_each(["a"], done.append, workers=workers)


def test_run_each_lets_the_items_under_way_finish_after_a_failure_and_begins_no_other():
    """Four workers: items 0-3 begin together (a barrier); item 3 fails at
    once, item 1 then fails too, and items 0 and 2 finish well after both:
    no later item begins, and the error raised is that of the first failed
    item in the items' order (item 1's), not the first in time (item 3's)."""
    lock, begun, finished = threading.Lock(), [], []
    together, failed = threading.Barrier(4, timeout=10), threading.Event()

    def work(item):
        with lock:
            begun.append(item)
        together.wait()
        if item == 3:
            failed.set()
            raise RuntimeError("item 3 failed")
        assert failed.wait(timeout=10)
        if item == 1:
            raise RuntimeError("item 1 failed")
        time.sleep(0.3)  # long after both failures: no worker is free to begin another item before then
        with lock:
            finished.append(item)
    with pytest.raises(RuntimeError, match="item 1 failed"):
        P.run_each(range(10), work, workers=4)
    assert sorted(begun) == [0, 1, 2, 3] and sorted(finished) == [0, 2]


def test_run_each_on_an_interrupt_begins_no_other_item_and_lets_those_under_way_finish(monkeypatch):
    """An interrupt while the items run (here raised where run_each waits
    for them, as Ctrl-C would come) cancels the items not yet begun; the two
    under way finish (each waits until the others are cancelled, or a few
    seconds) before the interrupt reaches the caller."""
    submitted, lock, begun, finished = [], threading.Lock(), [], []

    class Pool(P.ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            submitted.append(super().submit(fn, *args, **kwargs))
            return submitted[-1]

    def interrupted(futures):
        deadline = time.monotonic() + 10
        while len(begun) < 2 and time.monotonic() < deadline:  # once both workers are under way
            threading.Event().wait(0.01)
        raise KeyboardInterrupt
        yield  # a generator, as as_completed is

    def work(item):
        with lock:
            begun.append(item)
        deadline = time.monotonic() + 3
        while ((len(submitted) < 6 or not all(f.cancelled() for f in submitted[2:]))
               and time.monotonic() < deadline):
            threading.Event().wait(0.01)
        with lock:
            finished.append(item)

    monkeypatch.setattr(P, "ThreadPoolExecutor", Pool)
    monkeypatch.setattr(P, "as_completed", interrupted)
    with pytest.raises(KeyboardInterrupt):
        P.run_each(range(6), work, workers=2)
    assert sorted(begun) == sorted(finished) == [0, 1]
    assert len(submitted) == 6 and all(f.cancelled() for f in submitted[2:])


def test_run_each_on_an_interrupt_while_submitting_cancels_the_items_queued(monkeypatch):
    """An interrupt while run_each still submits the items (here raised by
    the fourth submit once both workers are under way, as Ctrl-C can come
    between two submits) cancels the item already queued, submits no other,
    and lets the two under way finish (each waits until the queued one is
    cancelled, or a few seconds) before the interrupt reaches the caller."""
    submitted, lock, begun, finished = [], threading.Lock(), [], []

    class Pool(P.ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            if len(submitted) == 3:
                deadline = time.monotonic() + 10
                while len(begun) < 2 and time.monotonic() < deadline:  # once both workers are under way
                    threading.Event().wait(0.01)
                raise KeyboardInterrupt
            submitted.append(super().submit(fn, *args, **kwargs))
            return submitted[-1]

    def work(item):
        with lock:
            begun.append(item)
        deadline = time.monotonic() + 3
        while (len(submitted) < 3 or not submitted[2].cancelled()) and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        with lock:
            finished.append(item)

    monkeypatch.setattr(P, "ThreadPoolExecutor", Pool)
    with pytest.raises(KeyboardInterrupt):
        P.run_each(range(6), work, workers=2)
    assert sorted(begun) == sorted(finished) == [0, 1]
    assert len(submitted) == 3 and submitted[2].cancelled()
