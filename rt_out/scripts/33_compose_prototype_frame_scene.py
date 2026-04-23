#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_MANIFEST_PATH = PROJECT_ROOT / "rt_out" / "static_scene" / "export" / "merged_static_manifest.json"
DEFAULT_DYNAMIC_SCENE_ROOT = PROJECT_ROOT / "rt_out" / "dynamic_scene"
DEFAULT_COMPOSED_SCENE_ROOT = PROJECT_ROOT / "rt_out" / "composed_scene"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
EXPECTED_DYNAMIC_COUNT = PROTOTYPE_CONFIG["expected_renderable_visual_count_total"]


class ComposeFrameSceneError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComposeConfig:
    frame_id: int
    static_manifest_path: Path
    dynamic_manifest_path: Path
    output_manifest_path: Path


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def default_dynamic_manifest_path(frame_id: int) -> Path:
    return (
        DEFAULT_DYNAMIC_SCENE_ROOT
        / frame_dir_name(frame_id)
        / f"dynamic_frame_{frame_id:03d}_manifest.json"
    )


def default_output_manifest_path(frame_id: int) -> Path:
    return (
        DEFAULT_COMPOSED_SCENE_ROOT
        / frame_dir_name(frame_id)
        / f"composed_frame_{frame_id:03d}_manifest.json"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose frozen static geometry with one dynamic prototype frame manifest."
    )
    parser.add_argument("--frame-id", type=int, default=0, help="Prototype frame id to compose")
    parser.add_argument(
        "--static-manifest",
        type=Path,
        default=STATIC_MANIFEST_PATH,
        help="Frozen merged_static_manifest.json path",
    )
    parser.add_argument(
        "--dynamic-manifest",
        type=Path,
        default=None,
        help="dynamic_frame_XXX_manifest.json path",
    )
    parser.add_argument(
        "--output-manifest",
        type=Path,
        default=None,
        help="Output composed_frame_XXX_manifest.json path",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> ComposeConfig:
    dynamic_manifest_path = (
        default_dynamic_manifest_path(args.frame_id)
        if args.dynamic_manifest is None
        else args.dynamic_manifest
    )
    output_manifest_path = (
        default_output_manifest_path(args.frame_id)
        if args.output_manifest is None
        else args.output_manifest
    )
    return ComposeConfig(
        frame_id=args.frame_id,
        static_manifest_path=args.static_manifest.expanduser().resolve(),
        dynamic_manifest_path=dynamic_manifest_path.expanduser().resolve(),
        output_manifest_path=output_manifest_path.expanduser().resolve(),
    )


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ComposeFrameSceneError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ComposeFrameSceneError(f"Invalid JSON in {path}: {exc}") from exc


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def slug(value: Any) -> str:
    text = str(value or "unnamed")
    chars = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text]
    return "".join(chars).strip("_") or "unnamed"


def project_local_candidate(path: Path) -> Path | None:
    parts = path.parts
    if "my_world" in parts:
        suffix = Path(*parts[parts.index("my_world") + 1 :])
        return PROJECT_ROOT / suffix
    if "rt_out" in parts:
        suffix = Path(*parts[parts.index("rt_out") :])
        return PROJECT_ROOT / suffix
    return None


def resolve_existing_path(raw_path: Any, label: str) -> tuple[Path, bool]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ComposeFrameSceneError(f"{label} must be a non-empty path string")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    if candidate.exists():
        return candidate.resolve(), False

    local_candidate = project_local_candidate(Path(raw_path))
    if local_candidate is not None and local_candidate.exists():
        return local_candidate.resolve(), True

    raise ComposeFrameSceneError(f"{label} does not exist: {raw_path}")


def build_static_entries(static_manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    groups = static_manifest.get("merged_groups")
    if not isinstance(groups, list) or not groups:
        raise ComposeFrameSceneError("Static manifest must contain a non-empty merged_groups list")

    entries: list[dict[str, Any]] = []
    rerooted_paths = 0

    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ComposeFrameSceneError(f"Static merged_groups[{index}] is not an object")

        material_label = group.get("material_class")
        manifest_mesh_path = group.get("merged_mesh_path")
        mesh_path, rerooted = resolve_existing_path(
            manifest_mesh_path, f"static merged_groups[{index}].merged_mesh_path"
        )
        rerooted_paths += int(rerooted)

        entry = {
            "id": f"static__merged_material__{slug(material_label)}",
            "source": "static",
            "model_name": None,
            "link_name": None,
            "visual_name": None,
            "mesh_path": str(mesh_path),
            "manifest_mesh_path": manifest_mesh_path,
            "path_resolved_from_current_project_root": rerooted,
            "transform": None,
            "baked_world_geometry": True,
            "material_label": material_label,
            "static_entry_kind": "merged_material_group",
            "static_record": group,
        }
        entries.append(entry)

    return entries, rerooted_paths


def build_dynamic_entries(
    dynamic_manifest: dict[str, Any],
    *,
    frame_id: int,
) -> tuple[list[dict[str, Any]], int]:
    if dynamic_manifest.get("frame_id") != frame_id:
        raise ComposeFrameSceneError(
            f"Dynamic manifest frame_id={dynamic_manifest.get('frame_id')}, expected {frame_id}"
        )

    source_sample_index = dynamic_manifest.get("source_sample_index")
    if not isinstance(source_sample_index, int):
        raise ComposeFrameSceneError(
            f"Dynamic manifest source_sample_index must be an integer, got {source_sample_index!r}"
        )

    visuals = dynamic_manifest.get("exported_visuals")
    if not isinstance(visuals, list):
        raise ComposeFrameSceneError("Dynamic manifest must contain exported_visuals list")
    if len(visuals) != EXPECTED_DYNAMIC_COUNT:
        raise ComposeFrameSceneError(
            f"Dynamic exported_visuals count={len(visuals)}, expected {EXPECTED_DYNAMIC_COUNT}"
        )

    entries: list[dict[str, Any]] = []
    for index, visual in enumerate(visuals):
        if not isinstance(visual, dict):
            raise ComposeFrameSceneError(f"Dynamic exported_visuals[{index}] is not an object")
        if visual.get("frame_id") != frame_id:
            raise ComposeFrameSceneError(
                f"Dynamic visual {visual.get('id')} has frame_id={visual.get('frame_id')}"
            )
        if visual.get("source_sample_index") != source_sample_index:
            raise ComposeFrameSceneError(
                f"Dynamic visual {visual.get('id')} has source_sample_index="
                f"{visual.get('source_sample_index')}, expected {source_sample_index}"
            )
        if visual.get("geometry_type") != "mesh":
            raise ComposeFrameSceneError(
                f"Dynamic visual {visual.get('id')} has non-mesh geometry_type="
                f"{visual.get('geometry_type')}"
            )
        if visual.get("export_success") is not True:
            raise ComposeFrameSceneError(f"Dynamic visual {visual.get('id')} was not exported")

        mesh_path, rerooted = resolve_existing_path(
            visual.get("exported_mesh_path"), f"dynamic visual {visual.get('id')}.exported_mesh_path"
        )
        if rerooted:
            raise ComposeFrameSceneError(
                f"Dynamic visual {visual.get('id')} unexpectedly required path rerooting"
            )

        entries.append(
            {
                "id": visual.get("id"),
                "source": "dynamic",
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "model_name": visual.get("model_name"),
                "link_name": visual.get("link_name"),
                "visual_name": visual.get("visual_name"),
                "mesh_path": str(mesh_path),
                "material_label": visual.get("material_label") or visual.get("material_class"),
                "baked_world_geometry": True,
                "geometry_type": visual.get("geometry_type"),
                "source_mesh_path": visual.get("source_mesh_path"),
                "cached_source_mesh_path": visual.get("cached_source_mesh_path"),
                "link_to_world": visual.get("link_to_world"),
                "visual_pose_matrix": visual.get("visual_pose_matrix"),
                "scale_xyz": visual.get("scale_xyz"),
                "final_transform": visual.get("final_transform"),
                "mesh_vertex_count": visual.get("mesh_vertex_count"),
                "mesh_face_count": visual.get("mesh_face_count"),
                "bounds_min": visual.get("bounds_min"),
                "bounds_max": visual.get("bounds_max"),
            }
        )

    return entries, source_sample_index


def validate_entries(entries: list[dict[str, Any]], static_count: int, dynamic_count: int) -> None:
    ids: set[str] = set()
    duplicate_ids: list[str] = []
    missing_paths: list[str] = []

    for entry in entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ComposeFrameSceneError(f"Composed entry has invalid id: {entry_id!r}")
        if entry_id in ids:
            duplicate_ids.append(entry_id)
        ids.add(entry_id)

        mesh_path = entry.get("mesh_path")
        if not isinstance(mesh_path, str) or not Path(mesh_path).exists():
            missing_paths.append(str(mesh_path))

    if duplicate_ids:
        raise ComposeFrameSceneError(f"Duplicate composed ids: {duplicate_ids}")
    if missing_paths:
        raise ComposeFrameSceneError(f"Missing composed mesh paths: {missing_paths[:10]}")
    if static_count + dynamic_count != len(entries):
        raise ComposeFrameSceneError("Composed entry count mismatch")


def build_manifest(config: ComposeConfig) -> dict[str, Any]:
    static_manifest = load_json(config.static_manifest_path)
    dynamic_manifest = load_json(config.dynamic_manifest_path)
    if not isinstance(static_manifest, dict):
        raise ComposeFrameSceneError("Static manifest root must be an object")
    if not isinstance(dynamic_manifest, dict):
        raise ComposeFrameSceneError("Dynamic manifest root must be an object")

    static_entries, static_paths_rerooted = build_static_entries(static_manifest)
    dynamic_entries, source_sample_index = build_dynamic_entries(
        dynamic_manifest,
        frame_id=config.frame_id,
    )
    entries = static_entries + dynamic_entries

    static_count = len(static_entries)
    dynamic_count = len(dynamic_entries)
    validate_entries(entries, static_count, dynamic_count)

    static_summary = static_manifest.get("summary", {})
    static_ready_input_entries = None
    if isinstance(static_summary, dict):
        static_ready_input_entries = static_summary.get("ready_input_entries")

    return {
        "generated_by": Path(__file__).name,
        "frame_id": config.frame_id,
        "source_sample_index": source_sample_index,
        "static_source_manifest": relpath(config.static_manifest_path),
        "dynamic_source_manifest": relpath(config.dynamic_manifest_path),
        "static_entry_kind": "merged_material_group",
        "static_ready_input_entries": static_ready_input_entries,
        "static_count": static_count,
        "dynamic_count": dynamic_count,
        "total_count": static_count + dynamic_count,
        "entries": entries,
        "validation": {
            "frame_id": config.frame_id,
            "source_sample_index": source_sample_index,
            "static_count_preserved": static_count == len(static_manifest.get("merged_groups", [])),
            "dynamic_count_expected": dynamic_count == EXPECTED_DYNAMIC_COUNT,
            "missing_paths": 0,
            "duplicate_ids": 0,
            "static_paths_resolved_from_current_project_root": static_paths_rerooted,
            "warnings": [],
        },
    }


def main() -> int:
    args = parse_args()
    config = build_config(args)
    try:
        manifest = build_manifest(config)
        save_json(config.output_manifest_path, manifest)
    except ComposeFrameSceneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Frame-{config.frame_id} scene composition")
    print(f"frame_id: {manifest['frame_id']}")
    print(f"source_sample_index: {manifest['source_sample_index']}")
    print(f"static_count: {manifest['static_count']}")
    print(f"dynamic_count: {manifest['dynamic_count']}")
    print(f"total_count: {manifest['total_count']}")
    print(f"missing_paths: {manifest['validation']['missing_paths']}")
    print(f"output: {config.output_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
