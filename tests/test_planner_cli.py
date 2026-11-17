"""The planners' model client and command lines, with stand-in API clients."""

import json
import sys
from pathlib import Path

import pytest

from intact.planner import classify_functionalities as CF
from intact.planner import planning as P
from intact.planner.plan_collective import plan_collective
from intact.planner.plan_iterative import plan_iterative

PAGE = {"url": "https://shop.test/", "elements": [
    {"bni": 1, "tag": "input", "attrs": {"type": "search", "name": "q"}, "parent_bni": None},
    {"bni": 2, "tag": "button", "attrs": {"type": "submit"}, "text": "Search", "parent_bni": None},
]}
PLANNERS = [(plan_iterative, "iterative"), (plan_collective, "collective")]


def _answer(system, user):
    """A stand-in model: every part of the page is relevant, the walk types
    into the search box, the whole-page plan does the same by ID, and
    extraction returns five tasks."""
    if user.startswith("Part of the page:"):
        return {"relevant": True}
    if CF.INSTRUCTION in user:
        return {"functionalities": [{"functionality": f"f{i}", "prompt": f"task {i}",
                                     "interaction": "single action"} for i in range(5)]}
    if user.startswith("Page:"):
        return {"steps": [{"bni": 1, "operation": "type", "value": "shoes"}]}
    if 'name="q"' in user.rsplit("Current element:\n", 1)[1]:
        return {"needed": True, "operation": "type", "value": "shoes"}
    return {"needed": False}


class _Client:
    """Stands in for OpenAI's client: records every request and answers it as
    `answer` does, as JSON text. The first `fail` requests get a response
    without an answer, as an API error gives."""
    def __init__(self, answer, fail=0):
        self.answer, self.fail, self.requests = answer, fail, []
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) <= self.fail:
            return type("R", (), {"choices": [], "model_extra": {"error": {"code": 500}}})()
        system, user = (m["content"] for m in kwargs["messages"])
        message = type("M", (), {"content": json.dumps(self.answer(system, user))})()
        return type("R", (), {"choices": [type("C", (), {"message": message})()], "usage": None,
                              "model": kwargs["model"], "model_extra": {}})()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """The current directory holds one page, as capture writes it, and the
    page's stored task; every model call goes to a stand-in client."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "shop.test").mkdir()
    (tmp_path / "shop.test" / "representation.json").write_text(json.dumps(PAGE))
    (tmp_path / "functionalities").mkdir()
    (tmp_path / "functionalities" / "shop.test.json").write_text(
        json.dumps({"functionalities": [{"prompt": "Search for shoes"}]}))
    client = _Client(_answer)
    monkeypatch.setattr(P, "openrouter_client", lambda: client)
    monkeypatch.setattr(P.time, "sleep", lambda seconds: None)
    return client


def _run(monkeypatch, main, *argv):
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    main()


def test_the_client_needs_the_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY not set"):
        P.openrouter_client()


def test_the_client_is_openrouters_through_openais_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = P.openrouter_client()
    assert str(client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    assert client.api_key == "test-key"


@pytest.mark.parametrize("planner, mode", PLANNERS)
def test_the_planners_read_and_write_relative_to_the_current_directory(workdir, monkeypatch, planner, mode):
    _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test")
    record = json.loads((Path("plans") / mode / "shop.test.json").read_text())
    assert [p["prompt"] for p in record["plans"]] == ["Search for shoes"]
    assert [(s["bni"], s["operation"], s["value"]) for s in record["plans"][0]["steps"]] == [(1, "type", "shoes")]
    assert record["model"] == "openai/gpt-6-luna"
    assert workdir.requests and {r["model"] for r in workdir.requests} == {"openai/gpt-6-luna"}


@pytest.mark.parametrize("planner, mode", PLANNERS)
def test_model_reaches_every_request_and_the_record(workdir, monkeypatch, planner, mode):
    _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test", "--model", "vendor/other-model")
    record = json.loads((Path("plans") / mode / "shop.test.json").read_text())
    assert record["model"] == "vendor/other-model"
    assert workdir.requests and {r["model"] for r in workdir.requests} == {"vendor/other-model"}


def test_extraction_writes_to_functionalities_with_the_model_given(workdir, monkeypatch):
    (Path("functionalities") / "shop.test.json").unlink()
    _run(monkeypatch, CF.main, "shop.test")
    record = json.loads((Path("functionalities") / "shop.test.json").read_text())
    assert [f["prompt"] for f in record["functionalities"]] == [f"task {i}" for i in range(5)]
    assert record["model"] == workdir.requests[-1]["model"] == "openai/gpt-6-luna"
    _run(monkeypatch, CF.main, "shop.test", "--model", "vendor/other-model")
    record = json.loads((Path("functionalities") / "shop.test.json").read_text())
    assert record["model"] == workdir.requests[-1]["model"] == "vendor/other-model"


def test_extraction_calls_the_model_through_the_planners_client(tmp_path, monkeypatch):
    """The command line uses OpenRouterLLM, so a call that comes back without
    an answer is retried, with the request that the planners send."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "shop.test").mkdir()
    (tmp_path / "shop.test" / "representation.json").write_text(json.dumps(PAGE))
    client = _Client(_answer, fail=1)
    monkeypatch.setattr(P, "openrouter_client", lambda: client)
    monkeypatch.setattr(P.time, "sleep", lambda seconds: None)
    _run(monkeypatch, CF.main, "shop.test")
    first, second = client.requests
    assert first == second
    assert first["response_format"] == {"type": "json_object"}
    assert first["extra_body"] == {"reasoning": {"effort": "low"}, "usage": {"include": True}}
    assert not hasattr(CF, "openrouter_llm")


@pytest.mark.parametrize("planner, mode", PLANNERS)
def test_a_rerun_with_another_model_refuses_before_any_call(workdir, monkeypatch, planner, mode):
    _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test")
    sent = len(workdir.requests)
    with pytest.raises(ValueError, match="holds plans made with openai/gpt-6-luna, not vendor/other-model"):
        _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test", "--model", "vendor/other-model")
    assert len(workdir.requests) == sent
    # The same model resumes as before: the finished plan is kept and nothing is replanned.
    _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test")
    assert len(workdir.requests) == sent


@pytest.mark.parametrize("planner, mode", PLANNERS)
def test_a_rerun_with_another_model_refuses_before_planning_a_missing_task(workdir, monkeypatch, planner, mode):
    """With a task still unplanned, a rerun without the guard would plan it with the new model and mix two
    models' plans in one record."""
    _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test")
    record = Path("plans") / mode / "shop.test.json"
    saved = record.read_text()
    (Path("functionalities") / "shop.test.json").write_text(json.dumps(
        {"functionalities": [{"prompt": "Search for shoes"}, {"prompt": "Search for hats"}]}))
    sent = len(workdir.requests)
    with pytest.raises(ValueError, match=r"shop\.test\.json holds plans made with openai/gpt-6-luna, "
                                         r"not vendor/other-model; use another --out$"):
        _run(monkeypatch, lambda: P.cli(planner, mode, 1, "Plan."), "shop.test", "--model", "vendor/other-model")
    assert len(workdir.requests) == sent
    assert record.read_text() == saved
