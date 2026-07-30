#!/usr/bin/env python3
"""Export posed actor meshes for Blender visual-validation samples.

This batch exporter consumes actor_validation_samples.json and writes one
world-space PLY per validation sample. It is intentionally separate from the
validated RT composition path and does not touch unrelated static-scene stages.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from runtime_config import (  # noqa: E402
    PROJECT_ROOT,
    RuntimeConfigError,
    SCRIPT_ACTOR_BLENDER_EXPORT_FRAME_MESHES,
    find_blender,
)

DEFAULT_VALIDATION_SAMPLES = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_validation_samples.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_validation"
BLENDER_WORKER = SCRIPT_ACTOR_BLENDER_EXPORT_FRAME_MESHES
ROOM_XY_LIMIT = 10.0
ROOM_Z_MIN = -0.5
ROOM_Z_MAX = 4.0
SUPPORTED_ALIGNMENT_POLICIES = {"none", "bounds_center_xy_to_root"}
SUPPORTED_Z_ALIGNMENT_POLICIES = {"none", "bounds_min_z_to_floor"}


class ActorValidationMeshExportError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export validation actor meshes from sample metadata.")
    parser.add_argument("--validation-samples", type=Path, default=DEFAULT_VALIDATION_SAMPLES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--blender", type=Path, default=None)
    parser.add_argument(
        "--alignment-policy",
        choices=sorted(SUPPORTED_ALIGNMENT_POLICIES),
        default="none",
        help=(
            "Experimental post-evaluation alignment policy. "
            "Default 'none' preserves existing export behavior; "
            "'bounds_center_xy_to_root' shifts baked vertices in XY so their bounds center matches root_pose6."
        ),
    )
    parser.add_argument(
        "--z-alignment-policy",
        choices=sorted(SUPPORTED_Z_ALIGNMENT_POLICIES),
        default="none",
        help=(
            "Experimental post-evaluation vertical alignment policy. "
            "Default 'none' preserves existing validation behavior; "
            "'bounds_min_z_to_floor' shifts baked vertices in Z so bounds_min_z matches --floor-z."
        ),
    )
    parser.add_argument(
        "--floor-z",
        type=float,
        default=None,
        help="Floor Z used by --z-alignment-policy bounds_min_z_to_floor.",
    )
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
        raise ActorValidationMeshExportError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorValidationMeshExportError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorValidationMeshExportError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActorValidationMeshExportError(f"{label} must be a non-empty string")
    return value.strip()


def require_pose6(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 6:
        raise ActorValidationMeshExportError(f"{label} must contain 6 numeric values")
    try:
        pose = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ActorValidationMeshExportError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in pose):
        raise ActorValidationMeshExportError(f"{label} contains non-finite values")
    return pose


def safe_filename(value: Any) -> str:
    chars = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value)]
    return "".join(chars).strip("_") or "actor"


def resolve_blender_or_raise(explicit: Path | None) -> Path:
    requested = None if explicit is None else resolve_path(explicit)
    try:
        return find_blender(requested)
    except RuntimeConfigError as exc:
        raise ActorValidationMeshExportError(str(exc)) from exc


def validate_asset(path_value: Any, label: str) -> str:
    path = Path(require_non_empty_string(path_value, label))
    if not path.exists():
        raise ActorValidationMeshExportError(f"{label} does not exist: {path}")
    return str(path.resolve())


def validation_frame_dir(output_root: Path, validation_frame_id: int) -> Path:
    return output_root / "meshes" / f"frame_{validation_frame_id:03d}"


def build_worker_samples(
    samples: list[dict[str, Any]],
    output_root: Path,
    *,
    alignment_policy: str,
    z_alignment_policy: str,
    floor_z: float | None,
) -> list[dict[str, Any]]:
    if alignment_policy not in SUPPORTED_ALIGNMENT_POLICIES:
        raise ActorValidationMeshExportError(f"Unsupported alignment policy: {alignment_policy}")
    if z_alignment_policy not in SUPPORTED_Z_ALIGNMENT_POLICIES:
        raise ActorValidationMeshExportError(f"Unsupported z alignment policy: {z_alignment_policy}")
    if z_alignment_policy == "bounds_min_z_to_floor":
        if floor_z is None or not math.isfinite(floor_z):
            raise ActorValidationMeshExportError(
                "--floor-z must be finite when --z-alignment-policy bounds_min_z_to_floor"
            )
    elif floor_z is not None and not math.isfinite(floor_z):
        raise ActorValidationMeshExportError("--floor-z must be finite when provided")
    worker_samples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_sample in enumerate(samples):
        sample = require_object(raw_sample, f"samples[{index}]")
        validation_frame_id = sample.get("validation_frame_id")
        if isinstance(validation_frame_id, bool) or not isinstance(validation_frame_id, int) or validation_frame_id < 0:
            raise ActorValidationMeshExportError(f"samples[{index}].validation_frame_id must be a non-negative integer")
        actor_name = require_non_empty_string(sample.get("actor_name"), f"samples[{index}].actor_name")
        actor_id = f"actor__{safe_filename(actor_name)}__validation_frame_{validation_frame_id:03d}"
        if actor_id in seen_ids:
            raise ActorValidationMeshExportError(f"Duplicate validation export id: {actor_id}")
        seen_ids.add(actor_id)
        mesh_path = validation_frame_dir(output_root, validation_frame_id) / f"{actor_id}.ply"

        actor_time_seconds = float(sample.get("actor_time_seconds"))
        animation_time_seconds = float(sample.get("animation_time_seconds"))
        if not math.isfinite(actor_time_seconds) or actor_time_seconds < 0.0:
            raise ActorValidationMeshExportError(f"{actor_id} actor_time_seconds must be finite and non-negative")
        if not math.isfinite(animation_time_seconds) or animation_time_seconds < 0.0:
            raise ActorValidationMeshExportError(f"{actor_id} animation_time_seconds must be finite and non-negative")

        worker_samples.append(
            {
                "id": actor_id,
                "validation_frame_id": validation_frame_id,
                "actor_name": actor_name,
                "actor_time_seconds": actor_time_seconds,
                "animation_time_seconds": animation_time_seconds,
                "root_pose_source": sample.get("root_pose_source"),
                "actor_pose6": require_pose6(sample.get("actor_pose6"), f"{actor_id}.actor_pose6"),
                "root_pose6": require_pose6(sample.get("root_pose6"), f"{actor_id}.root_pose6"),
                "skin_scale": float(sample.get("skin_scale")),
                "skin_path_resolved": validate_asset(sample.get("skin_path_resolved"), f"{actor_id}.skin_path_resolved"),
                "animation_path_resolved": validate_asset(
                    sample.get("animation_path_resolved"),
                    f"{actor_id}.animation_path_resolved",
                ),
                "material_label": sample.get("material_label"),
                "animation_time_policy": sample.get("animation_time_policy"),
                "animation_loop_duration_seconds": sample.get("animation_loop_duration_seconds"),
                "alignment_policy": alignment_policy,
                "z_alignment_policy": z_alignment_policy,
                "floor_z": floor_z,
                "output_mesh_path": str(mesh_path.resolve()),
                "sample_record": sample,
            }
        )
    return worker_samples


def clean_output_dirs(output_root: Path) -> None:
    meshes_root = output_root / "meshes"
    metadata_root = output_root / "metadata"
    if meshes_root.exists():
        for stale_ply in meshes_root.glob("frame_*/*.ply"):
            stale_ply.unlink()
    meshes_root.mkdir(parents=True, exist_ok=True)
    metadata_root.mkdir(parents=True, exist_ok=True)


def run_blender(blender: Path, spec_path: Path) -> None:
    command = [
        str(blender),
        "--background",
        "--python",
        str(BLENDER_WORKER),
        "--",
        "--spec",
        str(spec_path),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        raise ActorValidationMeshExportError(f"Blender validation actor export failed with exit code {result.returncode}")


def finite_bounds(bounds: Any, label: str) -> list[float]:
    if not isinstance(bounds, list) or len(bounds) != 3:
        raise ActorValidationMeshExportError(f"{label} must contain 3 values")
    try:
        values = [float(item) for item in bounds]
    except (TypeError, ValueError) as exc:
        raise ActorValidationMeshExportError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in values):
        raise ActorValidationMeshExportError(f"{label} contains non-finite values")
    return values


def center(bounds_min: list[float], bounds_max: list[float]) -> list[float]:
    return [(bounds_min[index] + bounds_max[index]) * 0.5 for index in range(3)]


def root_translation(a: dict[str, Any], b: dict[str, Any]) -> float:
    pa = require_pose6(a["root_pose6"], f"{a['id']}.root_pose6")
    pb = require_pose6(b["root_pose6"], f"{b['id']}.root_pose6")
    return math.sqrt(sum((pb[index] - pa[index]) ** 2 for index in range(3)))


def validate_entry(entry: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    bounds_min = finite_bounds(entry["bounds_min"], f"{entry['id']}.bounds_min")
    bounds_max = finite_bounds(entry["bounds_max"], f"{entry['id']}.bounds_max")
    root_pose6 = require_pose6(entry["root_pose6"], f"{entry['id']}.root_pose6")
    z_alignment_policy = str(entry.get("z_alignment_policy") or "none")
    floor_z = entry.get("floor_z")

    if any(abs(value) > ROOM_XY_LIMIT for value in bounds_min[:2] + bounds_max[:2]):
        raise ActorValidationMeshExportError(f"{entry['id']} is wildly outside expected room XY bounds")
    if bounds_min[2] < ROOM_Z_MIN or bounds_max[2] > ROOM_Z_MAX:
        raise ActorValidationMeshExportError(f"{entry['id']} is wildly outside expected room Z bounds")
    height = bounds_max[2] - bounds_min[2]
    if height <= 0.5 or height > 2.5:
        warnings.append(f"{entry['id']} height {height:.3f}m is outside broad human plausibility range")
    if z_alignment_policy == "bounds_min_z_to_floor":
        if isinstance(floor_z, bool):
            raise ActorValidationMeshExportError(f"{entry['id']}.floor_z must be finite when using floor alignment")
        try:
            floor_z_value = float(floor_z)
        except (TypeError, ValueError) as exc:
            raise ActorValidationMeshExportError(
                f"{entry['id']}.floor_z must be finite when using floor alignment"
            ) from exc
        if not math.isfinite(floor_z_value):
            raise ActorValidationMeshExportError(
                f"{entry['id']}.floor_z must be finite when using floor alignment"
            )
        if abs(bounds_min[2] - floor_z_value) > 0.02:
            warnings.append(
                f"{entry['id']} lower z {bounds_min[2]:.3f} differs from floor z {floor_z_value:.3f}"
            )
    else:
        if abs(bounds_min[2] - root_pose6[2]) > 0.35:
            warnings.append(
                f"{entry['id']} lower z {bounds_min[2]:.3f} differs from root z {root_pose6[2]:.3f}"
            )
    return warnings


def build_index(
    *,
    validation_samples_path: Path,
    output_root: Path,
    alignment_policy: str,
    z_alignment_policy: str,
    floor_z: float | None,
    worker_samples: list[dict[str, Any]],
    worker_summary: dict[str, Any],
    sample_warnings: list[str],
) -> dict[str, Any]:
    exports_by_id = {export["id"]: export for export in worker_summary.get("exports", [])}
    entries: list[dict[str, Any]] = []
    warnings: list[str] = list(sample_warnings)

    for sample in worker_samples:
        export = exports_by_id.get(sample["id"])
        if export is None:
            raise ActorValidationMeshExportError(f"Missing Blender export summary for {sample['id']}")
        mesh_path = Path(sample["output_mesh_path"])
        if not mesh_path.exists() or mesh_path.stat().st_size <= 0:
            raise ActorValidationMeshExportError(f"Missing or empty output mesh: {mesh_path}")
        vertex_count = int(export.get("mesh_vertex_count", 0))
        face_count = int(export.get("mesh_face_count", 0))
        if vertex_count <= 0:
            raise ActorValidationMeshExportError(f"{sample['id']} vertex count must be positive")
        if face_count <= 0:
            raise ActorValidationMeshExportError(f"{sample['id']} face count must be positive")
        bounds_min = finite_bounds(export.get("bounds_min"), f"{sample['id']}.bounds_min")
        bounds_max = finite_bounds(export.get("bounds_max"), f"{sample['id']}.bounds_max")

        entry = {
            "id": sample["id"],
            "validation_frame_id": sample["validation_frame_id"],
            "actor_name": sample["actor_name"],
            "actor_time_seconds": sample["actor_time_seconds"],
            "animation_time_seconds": sample["animation_time_seconds"],
            "animation_time_policy": sample.get("animation_time_policy"),
            "animation_loop_duration_seconds": sample.get("animation_loop_duration_seconds"),
            "root_pose_source": sample["root_pose_source"],
            "root_pose6": sample["root_pose6"],
            "alignment_policy": alignment_policy,
            "z_alignment_policy": z_alignment_policy,
            "floor_z": floor_z,
            "output_mesh_path": str(mesh_path.resolve()),
            "mesh_vertex_count": vertex_count,
            "mesh_face_count": face_count,
            "bounds_min": bounds_min,
            "bounds_max": bounds_max,
            "warnings": [],
        }
        entry["warnings"].extend(validate_entry(entry))
        warnings.extend(entry["warnings"])
        entries.append(entry)

    entries.sort(key=lambda item: (item["validation_frame_id"], item["actor_name"]))
    bounds_global_min = [
        min(entry["bounds_min"][axis] for entry in entries)
        for axis in range(3)
    ]
    bounds_global_max = [
        max(entry["bounds_max"][axis] for entry in entries)
        for axis in range(3)
    ]

    max_root_step = 0.0
    max_center_step = 0.0
    for previous, current in zip(entries, entries[1:]):
        if previous["actor_name"] != current["actor_name"]:
            continue
        max_root_step = max(max_root_step, root_translation(previous, current))
        prev_center = center(previous["bounds_min"], previous["bounds_max"])
        curr_center = center(current["bounds_min"], current["bounds_max"])
        max_center_step = max(
            max_center_step,
            math.sqrt(sum((curr_center[index] - prev_center[index]) ** 2 for index in range(3))),
        )

    return {
        "generated_by": Path(__file__).name,
        "validation_samples": str(validation_samples_path),
        "output_root": str(output_root),
        "alignment_policy": alignment_policy,
        "z_alignment_policy": z_alignment_policy,
        "floor_z": floor_z,
        "alignment_policy_note": (
            "Experimental visual-validation correction only; not claimed to be Gazebo-runtime-faithful actor animation."
            if alignment_policy != "none" or z_alignment_policy != "none"
            else "No post-evaluation actor alignment correction applied."
        ),
        "blender_worker_summary": str(output_root / "metadata" / "actor_validation_blender_summary.json"),
        "entries": entries,
        "validation_summary": {
            "alignment_policy": alignment_policy,
            "z_alignment_policy": z_alignment_policy,
            "floor_z": floor_z,
            "expected_sample_count": len(worker_samples),
            "exported_mesh_count": len(entries),
            "failed_export_count": 0,
            "warning_count": len(warnings),
            "warnings": warnings,
            "bounds_global_min": bounds_global_min,
            "bounds_global_max": bounds_global_max,
            "max_frame_to_frame_root_translation": max_root_step,
            "max_frame_to_frame_bounds_center_translation": max_center_step,
        },
    }


def main() -> int:
    args = parse_args()
    validation_samples_path = resolve_path(args.validation_samples)
    output_root = resolve_path(args.output_root)
    data = require_object(load_json(validation_samples_path, "validation samples"), "actor_validation_samples.json")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ActorValidationMeshExportError("actor_validation_samples.json must contain a non-empty samples list")

    clean_output_dirs(output_root)
    worker_samples = build_worker_samples(
        samples,
        output_root,
        alignment_policy=args.alignment_policy,
        z_alignment_policy=args.z_alignment_policy,
        floor_z=args.floor_z,
    )
    metadata_root = output_root / "metadata"
    spec_path = metadata_root / "actor_validation_blender_spec.json"
    summary_path = metadata_root / "actor_validation_blender_summary.json"
    index_path = output_root / "actor_validation_mesh_index.json"
    if summary_path.exists():
        summary_path.unlink()

    spec = {
        "generated_by": Path(__file__).name,
        "validation_batch": True,
        "alignment_policy": args.alignment_policy,
        "z_alignment_policy": args.z_alignment_policy,
        "floor_z": args.floor_z,
        "alignment_policy_note": (
            "Experimental visual-validation correction only; not claimed to be Gazebo-runtime-faithful actor animation."
            if args.alignment_policy != "none" or args.z_alignment_policy != "none"
            else "No post-evaluation actor alignment correction applied."
        ),
        "sample_count": len(worker_samples),
        "samples": worker_samples,
        "summary_path": str(summary_path),
    }
    save_json(spec_path, spec)

    blender = resolve_blender_or_raise(args.blender)
    run_blender(blender, spec_path)
    if not summary_path.exists():
        raise ActorValidationMeshExportError(f"Blender worker did not write summary: {summary_path}")
    worker_summary = require_object(load_json(summary_path, "Blender worker summary"), "Blender worker summary")

    sample_warnings = []
    validation_summary = data.get("validation_summary")
    if isinstance(validation_summary, dict):
        raw_warnings = validation_summary.get("warnings", [])
        if isinstance(raw_warnings, list):
            sample_warnings = [str(warning) for warning in raw_warnings]

    index = build_index(
        validation_samples_path=validation_samples_path,
        output_root=output_root,
        alignment_policy=args.alignment_policy,
        z_alignment_policy=args.z_alignment_policy,
        floor_z=args.floor_z,
        worker_samples=worker_samples,
        worker_summary=worker_summary,
        sample_warnings=sample_warnings,
    )
    save_json(index_path, index)

    summary = index["validation_summary"]
    print("Actor validation mesh export")
    print(f"validation_samples: {validation_samples_path}")
    print(f"output_root: {output_root}")
    print(f"alignment_policy: {summary['alignment_policy']}")
    print(f"z_alignment_policy: {summary['z_alignment_policy']}")
    print(f"floor_z: {summary['floor_z']}")
    print(f"expected_sample_count: {summary['expected_sample_count']}")
    print(f"exported_mesh_count: {summary['exported_mesh_count']}")
    print(f"failed_export_count: {summary['failed_export_count']}")
    print(f"warning_count: {summary['warning_count']}")
    print(f"bounds_global_min: {summary['bounds_global_min']}")
    print(f"bounds_global_max: {summary['bounds_global_max']}")
    print(f"max_frame_to_frame_root_translation: {summary['max_frame_to_frame_root_translation']}")
    print(f"max_frame_to_frame_bounds_center_translation: {summary['max_frame_to_frame_bounds_center_translation']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    print(f"index: {index_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ActorValidationMeshExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
