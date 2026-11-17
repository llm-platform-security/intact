"""Five realistic functionalities per page, from its stored representation."""

import json

import pytest

from intact.planner import classify_functionalities as CF

REP = {"url": "https://www.example.com/", "elements": [
    {"bni": 1, "tag": "title", "text": "Example Store", "attrs": {}},
    {"bni": 2, "tag": "script", "text": "track()", "attrs": {"src": "https://t.example.net/t.js"}},
    {"bni": 3, "tag": "meta", "attrs": {"name": "viewport", "content": "width=device-width"}},
    {"bni": 4, "tag": "input", "attrs": {"type": "search", "name": "q", "placeholder": "Search"},
     "provenance": {"creator": "3p:widgets.example.net/w.js#1"},
     "classification": {"authority": {"effective": ["type"]}},
     "document": {"url": "https://www.example.com/", "scope": "1p"}},
    {"bni": 5, "tag": "a", "text": "Deals", "attrs": {"href": "/deals"}},
    {"bni": 6, "tag": "div", "attrs": {}},
]}


def _item(prompt, interaction="single action"):
    return {"functionality": f"do {prompt}", "prompt": prompt, "interaction": interaction}


def test_page_view_is_markup_only():
    view = CF.page_view(REP)
    assert '<input placeholder="Search" type="search" name="q">' in view
    assert '<a href="/deals"> "Deals"' in view
    assert '<title> "Example Store"' in view
    for leaked in ("bni", "provenance", "3p:", "scope", "classification", "track()", "viewport"):
        assert leaked not in view
    assert len(view.splitlines()) == 3


def test_parse_keeps_five_distinct_functionalities():
    reply = {"functionalities": [
        _item(" Search for red shoes "), _item("Open the deals page"),
        _item("Search for red shoes"), _item("b", "several actions"),
        _item("c", "read then act"), _item("d"), _item("e")]}
    out = CF.parse_functionalities(reply)
    assert [f["prompt"] for f in out] == ["Search for red shoes", "Open the deals page",
                                          "b", "c", "d"]
    assert out[0] == {"functionality": "do  Search for red shoes ".strip(),
                      "prompt": "Search for red shoes", "interaction": "single action"}
    assert [f["interaction"] for f in out[2:4]] == ["several actions", "read then act"]


def test_parse_marks_unknown_interaction_as_none():
    reply = {"functionalities": [_item(p, "weird") for p in "abcde"]}
    assert all(f["interaction"] is None for f in CF.parse_functionalities(reply))


def test_parse_rejects_fewer_than_five():
    with pytest.raises(ValueError):
        CF.parse_functionalities({"functionalities": [_item("a"), _item("a"), {"prompt": ""}]})


def test_classify_puts_the_page_first():
    # the page, then the instruction
    seen = {}

    def llm(system, user):
        seen["user"] = user
        return {"functionalities": [_item(p) for p in "abcde"]}

    assert [f["prompt"] for f in CF.classify(REP, llm)] == list("abcde")
    assert seen["user"].startswith("Page:\n")
    assert seen["user"].rstrip().endswith(CF.INSTRUCTION)
    assert "mix" in CF.INSTRUCTION and "read" in CF.INSTRUCTION


def test_load_rep_from_crawl_folder_or_path(tmp_path):
    (tmp_path / "example.com").mkdir()
    path = tmp_path / "example.com" / "representation.json"
    path.write_text(json.dumps(REP))
    assert CF.load_rep("example.com", tmp_path)["url"] == REP["url"]
    assert CF.load_rep(str(path), tmp_path)["url"] == REP["url"]
