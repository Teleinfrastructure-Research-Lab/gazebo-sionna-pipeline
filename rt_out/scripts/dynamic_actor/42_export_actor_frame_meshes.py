#!/usr/bin/env python3
"""Export posed actor meshes for one sampled actor frame."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
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

DEFAULT_ACTOR_SAMPLES = PROJECT_ROOT / "rt_out" / "dynamic_frames" / "actor_frame_samples.json"
DEFAULT_ACTOR_MANIFEST = PROJECT_ROOT / "rt_out" / "manifests" / "actor_manifest.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "rt_out" / "dynamic_scene"
BLENDER_WORKER = SCRIPT_ACTOR_BLENDER_EXPORT_FRAME_MESHES
ROOM_XY_LIMIT = 10.0
ROOM_Z_MIN = -0.5
ROOM_Z_MAX = 4.0
SUPPORTED_ALIGNMENT_POLICIES = {"none", "bounds_center_xy_to_root"}
SUPPORTED_Z_ALIGNMENT_POLICIES = {"none", "bounds_min_z_to_floor"}


class ActorFrameExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportConfig:
    frame_id: int
    actor_samples_path: Path
    actor_manifest_path: Path
    output_root: Path
    frame_dir: Path
    actor_mesh_dir: Path
    metadata_dir: Path
    worker_spec_path: Path
    worker_summary_path: Path
    output_manifest_path: Path
    alignment_policy: str
    z_alignment_policy: str
    floor_z: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export posed actor meshes for one frame.")
    parser.add_argument("--frame-id", type=int, required=True)
    parser.add_argument("--actor-samples", type=Path, default=DEFAULT_ACTOR_SAMPLES)
    parser.add_argument("--actor-manifest", type=Path, default=DEFAULT_ACTOR_MANIFEST)
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
            "Experimental vertical post-evaluation alignment policy. "
            "Default 'none' preserves existing export behavior; "
            "'bounds_min_z_to_floor' shifts baked vertices in Z so bounds_min_z equals --floor-z."
        ),
    )
    parser.add_argument("--floor-z", type=float, default=None, help="Floor Z used by bounds_min_z_to_floor.")
    return parser.parse_args()


def resolve_cli_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def safe_filename(value: Any) -> str:
    chars = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value)]
    return "".join(chars).strip("_") or "actor"


def build_config(args: argparse.Namespace) -> ExportConfig:
    if args.frame_id < 0:
        raise ActorFrameExportError("--frame-id must be non-negative")
    floor_z = args.floor_z
    if args.z_alignment_policy == "bounds_min_z_to_floor":
        if floor_z is None:
            raise ActorFrameExportError("--floor-z is required when --z-alignment-policy bounds_min_z_to_floor")
        if not math.isfinite(floor_z):
            raise ActorFrameExportError("--floor-z must be finite")
    elif floor_z is not None and not math.isfinite(floor_z):
        raise ActorFrameExportError("--floor-z must be finite")
    output_root = resolve_cli_path(args.output_root)
    frame_dir = output_root / frame_dir_name(args.frame_id)
    metadata_dir = frame_dir / "actor_metadata"
    return ExportConfig(
        frame_id=args.frame_id,
        actor_samples_path=resolve_cli_path(args.actor_samples),
        actor_manifest_path=resolve_cli_path(args.actor_manifest),
        output_root=output_root,
        frame_dir=frame_dir,
        actor_mesh_dir=frame_dir / "actor_meshes",
        metadata_dir=metadata_dir,
        worker_spec_path=metadata_dir / f"actor_frame_{args.frame_id:03d}_blender_spec.json",
        worker_summary_path=metadata_dir / f"actor_frame_{args.frame_id:03d}_blender_summary.json",
        output_manifest_path=frame_dir / f"actor_frame_{args.frame_id:03d}_manifest.json",
        alignment_policy=args.alignment_policy,
        z_alignment_policy=args.z_alignment_policy,
        floor_z=floor_z,
    )


def load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ActorFrameExportError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorFrameExportError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorFrameExportError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActorFrameExportError(f"{label} must be a non-empty string")
    return value.strip()


def require_pose6(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 6:
        raise ActorFrameExportError(f"{label} must contain 6 values")
    try:
        pose = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ActorFrameExportError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in pose):
        raise ActorFrameExportError(f"{label} contains non-finite values")
    return pose


def resolve_blender_or_raise(explicit: Path | None) -> Path:
    requested = None if explicit is None else resolve_cli_path(explicit)
    try:
        return find_blender(requested)
    except RuntimeConfigError as exc:
        raise ActorFrameExportError(str(exc)) from exc


def actors_by_name(actor_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    actors = actor_manifest.get("actors")
    if not isinstance(actors, list):
        raise ActorFrameExportError("actor_manifest.json must contain an actors list")
    result: dict[str, dict[str, Any]] = {}
    for index, raw_actor in enumerate(actors):
        actor = require_object(raw_actor, f"actor_manifest.actors[{index}]")
        actor_name = require_non_empty_string(actor.get("actor_name"), f"actor_manifest.actors[{index}].actor_name")
        result[actor_name] = actor
    return result


def selected_frame(actor_samples: dict[str, Any], frame_id: int) -> dict[str, Any]:
    frames = actor_samples.get("frames")
    if not isinstance(frames, list):
        raise ActorFrameExportError("actor_frame_samples.json must contain a frames list")
    for raw_frame in frames:
        frame = require_object(raw_frame, "actor frame sample")
        if frame.get("frame_id") == frame_id:
            return frame
    raise ActorFrameExportError(f"Frame {frame_id} not found in actor_frame_samples.json")


def validate_asset(path_value: Any, label: str) -> str:
    path = Path(require_non_empty_string(path_value, label))
    if not path.exists():
        raise ActorFrameExportError(f"{label} does not exist: {path}")
    return str(path.resolve())


def build_worker_samples(
    frame: dict[str, Any],
    manifest_actors: dict[str, dict[str, Any]],
    config: ExportConfig,
) -> list[dict[str, Any]]:
    samples = frame.get("actors")
    if not isinstance(samples, list) or not samples:
        raise ActorFrameExportError(f"Frame {config.frame_id} has no actor samples")

    worker_samples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_sample in enumerate(samples):
        sample = require_object(raw_sample, f"frame {config.frame_id}.actors[{index}]")
        actor_name = require_non_empty_string(sample.get("actor_name"), f"frame actor sample[{index}].actor_name")
        if actor_name not in manifest_actors:
            raise ActorFrameExportError(f"Actor {actor_name!r} is missing from actor_manifest.json")
        actor = manifest_actors[actor_name]
        actor_pose6 = require_pose6(actor.get("pose6"), f"actor_manifest actor {actor_name}.pose6")
        root_pose6 = require_pose6(sample.get("root_pose6"), f"actor sample {actor_name}.root_pose6")
        source_sample_index = frame.get("source_sample_index")
        if sample.get("source_sample_index") != source_sample_index:
            raise ActorFrameExportError(f"Actor {actor_name} source_sample_index mismatches frame record")

        actor_id = f"actor__{safe_filename(actor_name)}__frame_{config.frame_id:03d}"
        if actor_id in seen_ids:
            raise ActorFrameExportError(f"Duplicate actor export id: {actor_id}")
        seen_ids.add(actor_id)

        output_mesh_path = config.actor_mesh_dir / f"{actor_id}.ply"
        worker_samples.append(
            {
                "id": actor_id,
                "actor_name": actor_name,
                "frame_id": config.frame_id,
                "source_sample_index": source_sample_index,
                "actor_time_seconds": float(sample["actor_time_seconds"]),
                "animation_time_seconds": float(sample["animation_time_seconds"]),
                "root_pose_source": sample["root_pose_source"],
                "actor_pose6": actor_pose6,
                "root_pose6": root_pose6,
                "skin_scale": float(sample["skin_scale"]),
                "skin_path_resolved": validate_asset(sample.get("skin_path_resolved"), f"{actor_name}.skin_path_resolved"),
                "animation_path_resolved": validate_asset(
                    sample.get("animation_path_resolved"),
                    f"{actor_name}.animation_path_resolved",
                ),
                "material_label": sample["material_label"],
                "alignment_policy": config.alignment_policy,
                "z_alignment_policy": config.z_alignment_policy,
                "floor_z": config.floor_z,
                "output_mesh_path": str(output_mesh_path.resolve()),
                "sample_record": sample,
            }
        )
    return worker_samples


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
        raise ActorFrameExportError(f"Blender actor export failed with exit code {result.returncode}")


def finite_bounds(bounds: Any, label: str) -> list[float]:
    if not isinstance(bounds, list) or len(bounds) != 3:
        raise ActorFrameExportError(f"{label} must contain 3 values")
    try:
        values = [float(item) for item in bounds]
    except (TypeError, ValueError) as exc:
        raise ActorFrameExportError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in values):
        raise ActorFrameExportError(f"{label} contains non-finite values")
    return values


def validate_export_bounds(export: dict[str, Any], sample: dict[str, Any], config: ExportConfig) -> list[str]:
    warnings: list[str] = []
    bounds_min = finite_bounds(export.get("bounds_min"), f"{export['id']}.bounds_min")
    bounds_max = finite_bounds(export.get("bounds_max"), f"{export['id']}.bounds_max")
    root_pose6 = require_pose6(sample["root_pose6"], f"{export['id']}.root_pose6")

    if any(abs(value) > ROOM_XY_LIMIT for value in bounds_min[:2] + bounds_max[:2]):
        raise ActorFrameExportError(f"{export['id']} is wildly outside expected room XY bounds")
    if bounds_min[2] < ROOM_Z_MIN or bounds_max[2] > ROOM_Z_MAX:
        raise ActorFrameExportError(f"{export['id']} is wildly outside expected room Z bounds")

    height = bounds_max[2] - bounds_min[2]
    if height <= 0.5 or height > 2.5:
        warnings.append(f"{export['id']} height {height:.3f}m is outside the broad human plausibility range")
    if config.z_alignment_policy == "bounds_min_z_to_floor":
        if config.floor_z is None:
            raise ActorFrameExportError("floor_z is required for floor-aligned export validation")
        if abs(bounds_min[2] - config.floor_z) > 0.02:
            warnings.append(
                f"{export['id']} lower z bound {bounds_min[2]:.3f} differs from floor z {config.floor_z:.3f}"
            )
    elif abs(bounds_min[2] - root_pose6[2]) > 0.35:
        warnings.append(
            f"{export['id']} lower z bound {bounds_min[2]:.3f} differs from root z {root_pose6[2]:.3f}"
        )
    return warnings


def build_output_manifest(
    config: ExportConfig,
    frame: dict[str, Any],
    worker_samples: list[dict[str, Any]],
    worker_summary: dict[str, Any],
) -> dict[str, Any]:
    exports_by_id = {export["id"]: export for export in worker_summary.get("exports", [])}
    exported_actors: list[dict[str, Any]] = []
    warnings: list[str] = []

    for sample in worker_samples:
        export = exports_by_id.get(sample["id"])
        if export is None:
            raise ActorFrameExportError(f"Worker summary is missing export for {sample['id']}")
        mesh_path = Path(sample["output_mesh_path"])
        if not mesh_path.exists() or mesh_path.stat().st_size <= 0:
            raise ActorFrameExportError(f"Missing or empty actor PLY: {mesh_path}")

        vertex_count = int(export.get("mesh_vertex_count", 0))
        face_count = int(export.get("mesh_face_count", 0))
        if vertex_count <= 0:
            raise ActorFrameExportError(f"{sample['id']} vertex count must be positive")
        if face_count <= 0:
            raise ActorFrameExportError(f"{sample['id']} face count must be positive")
        warnings.extend(validate_export_bounds(export, sample, config))

        exported_actors.append(
            {
                "id": sample["id"],
                "source": "actor",
                "actor_name": sample["actor_name"],
                "frame_id": config.frame_id,
                "source_sample_index": sample["source_sample_index"],
                "actor_time_seconds": sample["actor_time_seconds"],
                "animation_time_seconds": sample["animation_time_seconds"],
                "root_pose_source": sample["root_pose_source"],
                "alignment_policy": config.alignment_policy,
                "z_alignment_policy": config.z_alignment_policy,
                "floor_z": config.floor_z,
                "applied_z_alignment_translation": export.get("applied_z_alignment_translation"),
                "pre_z_alignment_bounds_min": export.get("pre_z_alignment_bounds_min"),
                "pre_z_alignment_bounds_max": export.get("pre_z_alignment_bounds_max"),
                "post_z_alignment_bounds_min": export.get("post_z_alignment_bounds_min"),
                "post_z_alignment_bounds_max": export.get("post_z_alignment_bounds_max"),
                "actor_pose6": sample["actor_pose6"],
                "root_pose6": sample["root_pose6"],
                "skin_scale": sample["skin_scale"],
                "exported_mesh_path": str(mesh_path.resolve()),
                "baked_world_geometry": True,
                "material_label": sample["material_label"],
                "mesh_vertex_count": vertex_count,
                "mesh_face_count": face_count,
                "bounds_min": export["bounds_min"],
                "bounds_max": export["bounds_max"],
                "blender_export": export,
            }
        )

    return {
        "generated_by": Path(__file__).name,
        "actor_samples_file": str(config.actor_samples_path),
        "actor_manifest_file": str(config.actor_manifest_path),
        "blender_worker_summary": str(config.worker_summary_path),
        "frame_id": config.frame_id,
        "source_sample_index": frame.get("source_sample_index"),
        "alignment_policy": config.alignment_policy,
        "z_alignment_policy": config.z_alignment_policy,
        "floor_z": config.floor_z,
        "alignment_policy_note": (
            "Experimental visual-validation correction only; not claimed to be Gazebo-runtime-faithful actor animation."
            if config.alignment_policy != "none" or config.z_alignment_policy != "none"
            else "No post-evaluation actor alignment correction applied."
        ),
        "actor_mesh_dir": str(config.actor_mesh_dir),
        "exported_actors": exported_actors,
        "validation": {
            "alignment_policy": config.alignment_policy,
            "z_alignment_policy": config.z_alignment_policy,
            "floor_z": config.floor_z,
            "expected_actor_count": len(worker_samples),
            "exported_actor_count": len(exported_actors),
            "missing_paths": 0,
            "failed_exports": 0,
            "warning_count": len(warnings),
            "warnings": warnings,
        },
    }


def main() -> int:
    args = parse_args()
    config = build_config(args)
    actor_samples = require_object(load_json(config.actor_samples_path, "actor samples"), "actor_frame_samples.json")
    actor_manifest = require_object(load_json(config.actor_manifest_path, "actor manifest"), "actor_manifest.json")
    frame = selected_frame(actor_samples, config.frame_id)
    manifest_actors = actors_by_name(actor_manifest)
    worker_samples = build_worker_samples(frame, manifest_actors, config)

    config.actor_mesh_dir.mkdir(parents=True, exist_ok=True)
    config.metadata_dir.mkdir(parents=True, exist_ok=True)
    for stale_ply in config.actor_mesh_dir.glob("*.ply"):
        stale_ply.unlink()
    if config.worker_summary_path.exists():
        config.worker_summary_path.unlink()

    spec = {
        "generated_by": Path(__file__).name,
        "frame_id": config.frame_id,
        "source_sample_index": frame.get("source_sample_index"),
        "alignment_policy": config.alignment_policy,
        "z_alignment_policy": config.z_alignment_policy,
        "floor_z": config.floor_z,
        "alignment_policy_note": (
            "Experimental visual-validation correction only; not claimed to be Gazebo-runtime-faithful actor animation."
            if config.alignment_policy != "none" or config.z_alignment_policy != "none"
            else "No post-evaluation actor alignment correction applied."
        ),
        "samples": worker_samples,
        "summary_path": str(config.worker_summary_path),
    }
    save_json(config.worker_spec_path, spec)

    blender = resolve_blender_or_raise(args.blender)
    run_blender(blender, config.worker_spec_path)
    if not config.worker_summary_path.exists():
        raise ActorFrameExportError(f"Blender worker did not write summary: {config.worker_summary_path}")

    worker_summary = require_object(
        load_json(config.worker_summary_path, "Blender worker summary"),
        "worker summary",
    )
    output_manifest = build_output_manifest(config, frame, worker_samples, worker_summary)
    save_json(config.output_manifest_path, output_manifest)

    print(f"Actor frame-{config.frame_id} mesh export")
    print(f"frame_id: {output_manifest['frame_id']}")
    print(f"source_sample_index: {output_manifest['source_sample_index']}")
    print(f"alignment_policy: {output_manifest['alignment_policy']}")
    print(f"z_alignment_policy: {output_manifest['z_alignment_policy']}")
    print(f"floor_z: {output_manifest['floor_z']}")
    print(f"exported_actor_count: {output_manifest['validation']['exported_actor_count']}")
    for actor in output_manifest["exported_actors"]:
        print(
            f"{actor['id']}: vertices={actor['mesh_vertex_count']} "
            f"faces={actor['mesh_face_count']} bounds_min={actor['bounds_min']} "
            f"bounds_max={actor['bounds_max']}"
        )
    print(f"warning_count: {output_manifest['validation']['warning_count']}")
    for warning in output_manifest["validation"]["warnings"]:
        print(f"WARNING: {warning}")
    print(f"output_manifest: {config.output_manifest_path}")
    print(f"actor_mesh_dir: {config.actor_mesh_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ActorFrameExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
