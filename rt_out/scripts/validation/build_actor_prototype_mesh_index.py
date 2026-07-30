#!/usr/bin/env python3
"""Adapt 3-frame actor export manifests into the Blender validation mesh-index schema."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_prototype_validation" / "actor_prototype_mesh_index.json"
EXPECTED_ACTOR_MESH_COUNT = 3
ACCEPTED_ALIGNMENT_POLICY = "bounds_center_xy_to_root"


class ActorPrototypeMeshIndexError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert prototype actor frame manifests into a 42-compatible mesh index."
    )
    parser.add_argument(
        "--actor-frame-manifests",
        type=Path,
        nargs="+",
        required=True,
        help="Actor frame manifest JSON files from the selected experiment run's dynamic_scene/frame_*/.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ActorPrototypeMeshIndexError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorPrototypeMeshIndexError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorPrototypeMeshIndexError(f"{label} must be an object")
    return value


def finite_vec(values: Any, length: int, label: str) -> list[float]:
    if not isinstance(values, list) or len(values) != length:
        raise ActorPrototypeMeshIndexError(f"{label} must contain {length} values")
    try:
        out = [float(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ActorPrototypeMeshIndexError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in out):
        raise ActorPrototypeMeshIndexError(f"{label} contains non-finite values")
    return out


def finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ActorPrototypeMeshIndexError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ActorPrototypeMeshIndexError(f"{label} must be finite")
    return number


def center(bounds_min: list[float], bounds_max: list[float]) -> list[float]:
    return [(bounds_min[index] + bounds_max[index]) * 0.5 for index in range(3)]


def center_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    center_a = center(a["bounds_min"], a["bounds_max"])
    center_b = center(b["bounds_min"], b["bounds_max"])
    return math.sqrt(sum((center_b[index] - center_a[index]) ** 2 for index in range(3)))


def actor_entries_from_manifest(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    frame_id = manifest.get("frame_id")
    if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
        raise ActorPrototypeMeshIndexError(f"{path} frame_id must be a non-negative integer")
    exported_actors = manifest.get("exported_actors")
    if not isinstance(exported_actors, list):
        raise ActorPrototypeMeshIndexError(f"{path} must contain exported_actors list")

    entries: list[dict[str, Any]] = []
    for actor_index, raw_actor in enumerate(exported_actors):
        actor = require_object(raw_actor, f"{path}.exported_actors[{actor_index}]")
        mesh_path = resolve_path(Path(str(actor.get("exported_mesh_path", ""))))
        if not mesh_path.exists():
            raise ActorPrototypeMeshIndexError(f"Missing actor mesh path: {mesh_path}")

        vertex_count = int(actor.get("mesh_vertex_count", 0))
        face_count = int(actor.get("mesh_face_count", 0))
        if vertex_count <= 0:
            raise ActorPrototypeMeshIndexError(f"{actor.get('id')} mesh_vertex_count must be positive")
        if face_count <= 0:
            raise ActorPrototypeMeshIndexError(f"{actor.get('id')} mesh_face_count must be positive")

        alignment_policy = str(actor.get("alignment_policy") or manifest.get("alignment_policy") or "none")
        entry = {
            "id": actor.get("id"),
            "validation_frame_id": frame_id,
            "frame_id": frame_id,
            "actor_name": actor.get("actor_name"),
            "actor_time_seconds": finite_number(actor.get("actor_time_seconds"), f"{actor.get('id')}.actor_time_seconds"),
            "animation_time_seconds": finite_number(
                actor.get("animation_time_seconds"),
                f"{actor.get('id')}.animation_time_seconds",
            ),
            "root_pose_source": actor.get("root_pose_source"),
            "root_pose6": finite_vec(actor.get("root_pose6"), 6, f"{actor.get('id')}.root_pose6"),
            "output_mesh_path": str(mesh_path),
            "mesh_vertex_count": vertex_count,
            "mesh_face_count": face_count,
            "bounds_min": finite_vec(actor.get("bounds_min"), 3, f"{actor.get('id')}.bounds_min"),
            "bounds_max": finite_vec(actor.get("bounds_max"), 3, f"{actor.get('id')}.bounds_max"),
            "alignment_policy": alignment_policy,
            "material_label": actor.get("material_label"),
            "source_actor_frame_manifest": str(path),
        }
        entries.append(entry)
    return entries


def build_mesh_index(manifest_paths: list[Path], output_path: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []

    for path in manifest_paths:
        manifest = require_object(load_json(path, "actor frame manifest"), str(path))
        entries.extend(actor_entries_from_manifest(path, manifest))

    if len(entries) != EXPECTED_ACTOR_MESH_COUNT:
        raise ActorPrototypeMeshIndexError(
            f"Expected exactly {EXPECTED_ACTOR_MESH_COUNT} actor meshes, found {len(entries)}"
        )

    entries.sort(key=lambda item: (item["validation_frame_id"], str(item.get("actor_name"))))
    seen_frames: set[int] = set()
    for entry in entries:
        frame_id = int(entry["validation_frame_id"])
        if frame_id in seen_frames:
            raise ActorPrototypeMeshIndexError(f"Duplicate validation_frame_id: {frame_id}")
        seen_frames.add(frame_id)
        if entry["alignment_policy"] != ACCEPTED_ALIGNMENT_POLICY:
            warnings.append(
                f"{entry['id']} alignment_policy is {entry['alignment_policy']!r}, expected {ACCEPTED_ALIGNMENT_POLICY!r}"
            )

    bounds_global_min = [min(entry["bounds_min"][axis] for entry in entries) for axis in range(3)]
    bounds_global_max = [max(entry["bounds_max"][axis] for entry in entries) for axis in range(3)]
    max_center_step = 0.0
    for previous, current in zip(entries, entries[1:]):
        max_center_step = max(max_center_step, center_distance(previous, current))

    alignment_policies_used = sorted({str(entry["alignment_policy"]) for entry in entries})
    return {
        "generated_by": Path(__file__).name,
        "purpose": "3-frame actor prototype visual validation mesh index for build_actor_blender_validation_scene.py",
        "actor_frame_manifests": [str(path) for path in manifest_paths],
        "output": str(output_path),
        "entries": entries,
        "validation_summary": {
            "expected_sample_count": EXPECTED_ACTOR_MESH_COUNT,
            "exported_mesh_count": len(entries),
            "failed_export_count": 0,
            "warning_count": len(warnings),
            "warnings": warnings,
            "bounds_global_min": bounds_global_min,
            "bounds_global_max": bounds_global_max,
            "max_frame_to_frame_bounds_center_translation": max_center_step,
            "alignment_policies_used": alignment_policies_used,
        },
    }


def main() -> int:
    args = parse_args()
    manifest_paths = [resolve_path(path) for path in args.actor_frame_manifests]
    output_path = resolve_path(args.output)
    mesh_index = build_mesh_index(manifest_paths, output_path)
    save_json(output_path, mesh_index)

    summary = mesh_index["validation_summary"]
    print("Actor prototype mesh index build")
    print(f"output: {output_path}")
    print(f"expected_sample_count: {summary['expected_sample_count']}")
    print(f"exported_mesh_count: {summary['exported_mesh_count']}")
    print(f"failed_export_count: {summary['failed_export_count']}")
    print(f"warning_count: {summary['warning_count']}")
    print(f"bounds_global_min: {summary['bounds_global_min']}")
    print(f"bounds_global_max: {summary['bounds_global_max']}")
    print(f"max_frame_to_frame_bounds_center_translation: {summary['max_frame_to_frame_bounds_center_translation']}")
    print(f"alignment_policies_used: {summary['alignment_policies_used']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ActorPrototypeMeshIndexError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
