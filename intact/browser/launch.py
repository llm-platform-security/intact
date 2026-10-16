"""Browser launch helpers."""

from pathlib import Path


def collect_frame_ids(frame_tree: dict) -> list[str]:
    ids = []
    frame = frame_tree.get("frame", {})
    if fid := frame.get("id"):
        ids.append(fid)
    for child in frame_tree.get("childFrames", []):
        ids.extend(collect_frame_ids(child))
    return ids
