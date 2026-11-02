"""The hook of the built-in ``yolo`` layout: what its declarative rules cannot say.

``validate``: class ids against ``names`` (ids 0..n-1, ``nc`` agreeing), ``kpt_shape``'s dimension, the
splits ``data.yaml`` names holding images, and per label line the value count (detection, segmentation or
pose), the class id range, coordinates within [0,1] and keypoint visibility. Lines the declarative line rule
already refuses are skipped here, so each problem is reported once.

``materialize``: a ``data.yaml`` whose ``path:`` is the folder holding the data, which training code reads.
"""
from __future__ import annotations

import pathlib
import re
from typing import Optional

import yaml

from ..errors import DatasetError

SPLITS = ("train", "val", "test")
REQUIRED_SPLITS = ("train", "val")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _data_yaml(root: pathlib.Path) -> Optional[dict]:
    try:
        data = yaml.safe_load((root / "data.yaml").read_text())
    except (OSError, yaml.YAMLError):
        return None   # missing or broken: the declarative rules report it
    return data if isinstance(data, dict) else None


def _class_count(data: dict, errors: list) -> Optional[int]:
    names, nc = data.get("names"), data.get("nc")
    if isinstance(names, dict):
        keys = list(names)
        if any(isinstance(k, bool) or not isinstance(k, int) for k in keys):
            errors.append("data.yaml: names keys must be integer class ids (0, 1, 2, ...)")
        elif sorted(keys) != list(range(len(keys))):
            errors.append(f"data.yaml: names ids must be exactly 0..{len(keys) - 1}, got {sorted(keys)}")
    count = len(names) if isinstance(names, (dict, list)) else None
    if isinstance(nc, int) and not isinstance(nc, bool) and count is not None and nc != count:
        errors.append(f"data.yaml: nc is {nc} but names has {count} entries")
    return count


def _kpt_shape(data: dict, errors: list) -> Optional[tuple]:
    shape = data.get("kpt_shape")
    if not (isinstance(shape, list) and len(shape) == 2 and all(isinstance(v, int) for v in shape)):
        return None   # absent or malformed: the manifest schema reports a malformed one
    if shape[1] not in (2, 3):
        errors.append(f"data.yaml: kpt_shape [K, D] needs D 2 or 3 (got {shape[1]})")
        return None
    return shape[0], shape[1]


def _line_problems(parts: list, nc: Optional[int], kpt: Optional[tuple]) -> list:
    """Problems of one label line that already reads as '<int> <number> ...'."""
    if kpt:
        k, d = kpt
        if len(parts) != 5 + k * d:
            return [f"expected '<class-id> <x> <y> <w> <h>' + {k} keypoints x {d} values "
                    f"({5 + k * d} values), got {len(parts)}"]
    elif len(parts) != 5 and not (len(parts) >= 7 and len(parts) % 2 == 1):
        return [f"expected '<class-id> <x> <y> <w> <h>' (detection) or '<class-id> x1 y1 x2 y2 ...' "
                f"(segmentation: an even number >= 6 of coordinates), got {len(parts)} values"]
    cid, vals = int(parts[0]), [float(p) for p in parts[1:]]
    problems = []
    if nc is not None and cid >= nc:
        problems.append(f"class id {cid} is outside 0..{nc - 1}")
    if kpt and kpt[1] == 3:
        coords = vals[:4] + [v for i, v in enumerate(vals[4:]) if i % 3 != 2]
        if any(v not in (0.0, 1.0, 2.0) for i, v in enumerate(vals[4:]) if i % 3 == 2):
            problems.append("keypoint visibility must be 0, 1 or 2")
    else:
        coords = vals
    if any(not 0.0 <= c <= 1.0 for c in coords):
        problems.append("coordinates must be within [0,1]")
    return problems


def _labels(root: pathlib.Path, line_rx, nc: Optional[int], kpt: Optional[tuple], errors: list) -> None:
    for label in sorted((root / "labels").rglob("*.txt")) if (root / "labels").is_dir() else []:
        rel = label.relative_to(root).as_posix()
        if any(s.startswith(".") for s in rel.split("/")):
            continue
        try:
            lines = label.read_text().split("\n")
        except (OSError, UnicodeDecodeError):
            continue   # the declarative line rule reports unreadable text
        for n, line in enumerate(lines, 1):
            line = line.strip(" \t\r")
            if line and (line_rx is None or line_rx.fullmatch(line)):
                for problem in _line_problems(line.split(), nc, kpt):
                    errors.append(f"{rel}:{n}: {problem}: {line[:80]}")


def _splits(root: pathlib.Path, data: dict, errors: list) -> None:
    for split in REQUIRED_SPLITS:
        entry = data.get(split)
        if not isinstance(entry, str):
            continue   # missing or malformed: the manifest schema reports it
        folder = root / entry.strip("/")
        if not any(p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
                   for p in (folder.rglob("*") if folder.is_dir() else [])):
            errors.append(f"{entry.strip('/')}/ has no images")


def validate(root: pathlib.Path, layout) -> list:
    """The yolo checks the declarative rules cannot express."""
    data = _data_yaml(root)
    if data is None:
        return []
    errors: list = []
    nc, kpt = _class_count(data, errors), _kpt_shape(data, errors)
    _splits(root, data, errors)
    line_rules = layout.spec.get("rules", {}).get("lines", [])
    line_rx = re.compile(line_rules[0]["pattern"], re.ASCII) if line_rules else None
    _labels(root, line_rx, nc, kpt, errors)
    return errors


def materialize(data_dir: pathlib.Path, out_dir: pathlib.Path, layout) -> pathlib.Path:
    """``out_dir/data.yaml``: the dataset's data.yaml with ``path:`` set to ``data_dir`` (absolute)."""
    source = data_dir / "data.yaml"
    try:
        data = yaml.safe_load(source.read_text()) or {}
    except OSError:
        raise DatasetError(f"{data_dir} holds no data.yaml; is it a yolo dataset?") from None
    data["path"] = str(pathlib.Path(data_dir).resolve())
    out = out_dir / "data.yaml"
    text = yaml.safe_dump(data, sort_keys=False)
    if not out.is_file() or out.read_text() != text:
        out_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return out
