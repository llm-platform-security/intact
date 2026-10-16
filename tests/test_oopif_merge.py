"""Merging captures of site-isolated (out-of-process) iframes into one state.

Each isolated iframe runs in its own renderer process, so its DOMSnapshot,
AX tree, and provenance come from a separate CDP session whose
backendNodeIds are numbered independently (they collide with the main
page's). The merge namespaces every id of segment k (k >= 1) as
k * NS + local id; the main page (segment 0) keeps its ids unchanged.
"""

from intact.instrumentation import oopif as O
from intact.gentree.unified_view import build_unified_elements

TOP = "https://firstparty.test/"
FRAME = "https://thirdparty.test/frame.html"


def _main_state():
    return {
        "dom_records": [
            {"bni": 1, "tag": "html", "attrs": {}, "depth": 0, "parent_bni": None,
             "doc_index": 0, "doc_url": TOP},
            {"bni": 2, "tag": "iframe", "attrs": {"src": FRAME}, "depth": 1,
             "parent_bni": 1, "doc_index": 0, "doc_url": TOP},
        ],
        "classification": {1: "cls-html", 2: "cls-iframe"},
        "ax_nodes": [{"nodeId": "7", "backendDOMNodeId": 2,
                      "role": {"value": "Iframe"}}],
        "provenance": {"page_origin": "firstparty.test", "elements": {},
                       "scripts": {}, "network": [], "script_instances": {"9": {}},
                       "inline_scripts": {}, "coverage": {}},
    }


def _frame_state():
    return {
        "dom_records": [
            {"bni": 1, "tag": "html", "attrs": {}, "depth": 0, "parent_bni": None,
             "doc_index": 0, "doc_url": FRAME},
            {"bni": 2, "tag": "div", "attrs": {"id": "made-in-frame"}, "depth": 1,
             "parent_bni": 1, "doc_index": 0, "doc_url": FRAME},
        ],
        "classification": {1: "cls-f-html", 2: "cls-f-div"},
        "ax_nodes": [{"nodeId": "7", "backendDOMNodeId": 2,
                      "role": {"value": "generic"}}],
        "provenance": {"page_origin": "firstparty.test",
                       "elements": {2: {"tag": "div", "creator": "3p:thirdparty.test/frame.html",
                                        "via": "createElement", "inserter": None,
                                        "attr_mods": [], "text_mods": [],
                                        "listeners": [], "loads": []}},
                       "scripts": {"https://thirdparty.test/a.js": {"cls": "3p:thirdparty.test/a.js",
                                                                     "3p_loads": []}},
                       "network": [{"url": "https://ads.test/x", "domain": "ads.test",
                                    "initiator_script": ""}],
                       "script_instances": {"9": {"url": FRAME}},
                       "inline_scripts": {}, "coverage": {}},
    }


def test_namespaced_ids_round_trip():
    nid = O.namespaced(42, 3)
    assert nid == 3 * O.NS + 42
    assert O.split(nid) == (3, 42)
    assert O.namespaced(42, 0) == 42


def test_merge_namespaces_dom_records_and_offsets_documents():
    state = _main_state()
    O.merge_segment(state, _frame_state(), segment=1, frame_url=FRAME, owner_bni=2)
    recs = {r["bni"]: r for r in state["dom_records"]}
    assert set(recs) == {1, 2, O.NS + 1, O.NS + 2}
    div = recs[O.NS + 2]
    assert div["parent_bni"] == O.NS + 1
    assert div["doc_index"] == 1          # after the main page's one document
    assert div["doc_url"] == FRAME
    assert recs[O.NS + 1]["parent_bni"] is None


def test_merge_namespaces_classification_ax_and_provenance():
    state = _main_state()
    O.merge_segment(state, _frame_state(), segment=1, frame_url=FRAME, owner_bni=2)
    assert state["classification"][O.NS + 2] == "cls-f-div"
    assert state["classification"][2] == "cls-iframe"
    ax = {n["backendDOMNodeId"]: n for n in state["ax_nodes"]}
    assert ax[O.NS + 2]["nodeId"] == "f1:7"
    assert ax[2]["nodeId"] == "7"
    prov = state["provenance"]
    assert prov["elements"][O.NS + 2]["creator"].startswith("3p:thirdparty.test")
    assert prov["network"][-1]["domain"] == "ads.test"
    assert "https://thirdparty.test/a.js" in prov["scripts"]
    assert "f1:9" in prov["script_instances"] and "9" in prov["script_instances"]
    assert prov["coverage"]["third_party"] == 1


def test_merge_records_frame_with_its_owner_iframe():
    state = _main_state()
    O.merge_segment(state, _frame_state(), segment=1, frame_url=FRAME, owner_bni=2)
    assert state["frames"] == [{"segment": 1, "url": FRAME, "owner_bni": 2,
                                "doc_index": 1}]


def test_merged_state_builds_unified_elements_for_the_iframe():
    state = _main_state()
    O.merge_segment(state, _frame_state(), segment=1, frame_url=FRAME, owner_bni=2)
    els = {e["bni"]: e for e in build_unified_elements(state)}
    div = els[O.NS + 2]
    assert div["document"] == {"url": FRAME, "scope": "3p"}
    assert div["provenance"]["creator"].startswith("3p:thirdparty.test")
    assert len(els) == 4


def test_uncaptured_frames_lists_isolated_frames_that_were_not_captured():
    targets = [{"type": "page", "targetId": "P", "url": TOP},
               {"type": "iframe", "targetId": "A", "url": FRAME},
               {"type": "iframe", "targetId": "B", "url": "https://other.test/"},
               {"type": "service_worker", "targetId": "S", "url": "https://x.test/sw.js"}]
    assert O.uncaptured_frames(targets, captured_ids={"A"}) == [
        {"target_id": "B", "url": "https://other.test/"}]
