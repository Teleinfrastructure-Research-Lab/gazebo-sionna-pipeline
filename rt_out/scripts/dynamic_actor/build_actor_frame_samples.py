#!/usr/bin/env python3
"""Build explicit per-frame actor samples for the actor dynamic branch.

This stage consumes the actor metadata extracted by extract_actor_manifest.py and the separate
actor dynamic config. It does not export meshes. The output is a reproducible
sampling contract for later Blender visual validation and, eventually, RT
composition.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACTOR_MANIFEST = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "manifests" / "actor_manifest.json"
DEFAULT_CONFIG_ROOT = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "config"
DEFAULT_ACTOR_CONFIG = DEFAULT_CONFIG_ROOT / "actor_dynamic_config.json"
DEFAULT_DYNAMIC_CONFIG = DEFAULT_CONFIG_ROOT / "dynamic_prototype_config.json"
DEFAULT_RT_MATERIAL_CONFIG = DEFAULT_CONFIG_ROOT / "rt_material_mapping.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "dynamic_frames" / "actor_frame_samples.json"
EXACT_TIME_TOLERANCE_SECONDS = 1e-9


class ActorFrameSampleError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildConfig:
    actor_manifest_path: Path
    actor_config_path: Path
    dynamic_prototype_config_path: Path
    rt_material_config_path: Path
    output_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build actor_frame_samples.json from explicit configured actor times."
    )
    parser.add_argument("--actor-manifest", type=Path, default=DEFAULT_ACTOR_MANIFEST)
    parser.add_argument("--actor-config", type=Path, default=DEFAULT_ACTOR_CONFIG)
    parser.add_argument("--dynamic-prototype-config", type=Path, default=DEFAULT_DYNAMIC_CONFIG)
    parser.add_argument("--rt-material-config", type=Path, default=DEFAULT_RT_MATERIAL_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def resolve_cli_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def build_config(args: argparse.Namespace) -> BuildConfig:
    return BuildConfig(
        actor_manifest_path=resolve_cli_path(args.actor_manifest),
        actor_config_path=resolve_cli_path(args.actor_config),
        dynamic_prototype_config_path=resolve_cli_path(args.dynamic_prototype_config),
        rt_material_config_path=resolve_cli_path(args.rt_material_config),
        output_path=resolve_cli_path(args.output),
    )


def load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ActorFrameSampleError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorFrameSampleError(f"Invalid JSON in {label} {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorFrameSampleError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActorFrameSampleError(f"{label} must be a non-empty string")
    return value.strip()


def require_bool(value: Any, label: str, *, default: bool | None = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise ActorFrameSampleError(f"{label} must be a boolean")
    return value


def require_non_negative_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ActorFrameSampleError(f"{label} must be a non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ActorFrameSampleError(f"{label} must be a non-negative number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ActorFrameSampleError(f"{label} must be finite and non-negative")
    return number


def parse_frame_id(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ActorFrameSampleError(f"{label} must be a non-negative integer")
    try:
        frame_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ActorFrameSampleError(f"{label} must be a non-negative integer") from exc
    if str(frame_id) != str(value).strip() and not isinstance(value, int):
        raise ActorFrameSampleError(f"{label} must be an integer frame id, got {value!r}")
    if frame_id < 0:
        raise ActorFrameSampleError(f"{label} must be non-negative")
    return frame_id


def load_frame_source_samples(dynamic_config: dict[str, Any]) -> dict[int, int]:
    raw_frames = dynamic_config.get("prototype_frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ActorFrameSampleError("dynamic_prototype_config.prototype_frames must be a non-empty list")

    mapping: dict[int, int] = {}
    for index, raw_frame in enumerate(raw_frames):
        frame = require_object(raw_frame, f"prototype_frames[{index}]")
        frame_id = parse_frame_id(frame.get("frame_id"), f"prototype_frames[{index}].frame_id")
        source_sample_index = parse_frame_id(
            frame.get("source_sample_index"),
            f"prototype_frames[{index}].source_sample_index",
        )
        if frame_id in mapping:
            raise ActorFrameSampleError(f"Duplicate prototype frame_id: {frame_id}")
        mapping[frame_id] = source_sample_index
    return mapping


def load_material_labels(rt_material_config: dict[str, Any]) -> set[str]:
    materials = rt_material_config.get("materials")
    if not isinstance(materials, dict) or not materials:
        raise ActorFrameSampleError("rt_material_mapping.json must contain a non-empty materials object")
    return set(materials)


def actors_by_name(actor_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_actors = actor_manifest.get("actors")
    if not isinstance(raw_actors, list):
        raise ActorFrameSampleError("actor_manifest.json must contain an actors list")

    result: dict[str, dict[str, Any]] = {}
    for index, actor in enumerate(raw_actors):
        actor = require_object(actor, f"actor_manifest.actors[{index}]")
        actor_name = require_non_empty_string(
            actor.get("actor_name"),
            f"actor_manifest.actors[{index}].actor_name",
        )
        if actor_name in result:
            raise ActorFrameSampleError(f"Duplicate actor in actor manifest: {actor_name}")
        result[actor_name] = actor
    return result


def validate_actor_assets_resolved(actor: dict[str, Any], actor_name: str) -> None:
    skin = require_object(actor.get("skin"), f"actor {actor_name}.skin")
    if skin.get("uri_status") != "resolved":
        raise ActorFrameSampleError(
            f"Actor {actor_name} skin URI is unresolved: status={skin.get('uri_status')!r}"
        )
    animations = actor.get("animations")
    if not isinstance(animations, list) or not animations:
        raise ActorFrameSampleError(f"Actor {actor_name} must have at least one animation")
    for index, animation in enumerate(animations):
        animation = require_object(animation, f"actor {actor_name}.animations[{index}]")
        if animation.get("uri_status") != "resolved":
            raise ActorFrameSampleError(
                f"Actor {actor_name} animation[{index}] URI is unresolved: "
                f"status={animation.get('uri_status')!r}"
            )


def first_trajectory(actor: dict[str, Any], actor_name: str) -> dict[str, Any] | None:
    script = require_object(actor.get("script"), f"actor {actor_name}.script")
    trajectories = script.get("trajectories")
    if not isinstance(trajectories, list):
        raise ActorFrameSampleError(f"actor {actor_name}.script.trajectories must be a list")
    for index, trajectory in enumerate(trajectories):
        trajectory = require_object(trajectory, f"actor {actor_name}.script.trajectories[{index}]")
        if trajectory.get("waypoint_count", 0) > 0:
            return trajectory
    return None


def find_exact_waypoint(
    actor_name: str,
    trajectory: dict[str, Any],
    actor_time_seconds: float,
) -> dict[str, Any]:
    waypoints = trajectory.get("waypoints")
    if not isinstance(waypoints, list) or not waypoints:
        raise ActorFrameSampleError(f"Actor {actor_name} trajectory has no waypoints")

    for index, raw_waypoint in enumerate(waypoints):
        waypoint = require_object(raw_waypoint, f"actor {actor_name}.waypoints[{index}]")
        waypoint_time = require_non_negative_float(
            waypoint.get("time_seconds"),
            f"actor {actor_name}.waypoints[{index}].time_seconds",
        )
        if math.isclose(waypoint_time, actor_time_seconds, abs_tol=EXACT_TIME_TOLERANCE_SECONDS):
            return waypoint

    known = ", ".join(str(item.get("time_seconds")) for item in waypoints[:20])
    raise ActorFrameSampleError(
        f"Actor {actor_name} configured time {actor_time_seconds:g}s does not exactly match "
        f"a trajectory waypoint. Known waypoint times: {known}"
    )


def sorted_configured_frame_times(raw_frame_times: Any, actor_name: str) -> list[tuple[int, float]]:
    if not isinstance(raw_frame_times, dict):
        raise ActorFrameSampleError(f"actor_config.actors.{actor_name}.frame_times_seconds must be an object")

    parsed: list[tuple[int, float]] = []
    seen: set[int] = set()
    for raw_frame_id, raw_time in raw_frame_times.items():
        frame_id = parse_frame_id(raw_frame_id, f"actor {actor_name} frame_times_seconds key")
        if frame_id in seen:
            raise ActorFrameSampleError(f"Duplicate frame id for actor {actor_name}: {frame_id}")
        seen.add(frame_id)
        parsed.append(
            (
                frame_id,
                require_non_negative_float(
                    raw_time,
                    f"actor_config.actors.{actor_name}.frame_times_seconds.{frame_id}",
                ),
            )
        )
    return sorted(parsed)


def make_empty_manifest(config: BuildConfig, phase_strategy: str) -> dict[str, Any]:
    return {
        "generated_by": Path(__file__).name,
        "actor_manifest": str(config.actor_manifest_path),
        "actor_config": str(config.actor_config_path),
        "dynamic_prototype_config": str(config.dynamic_prototype_config_path),
        "rt_material_config": str(config.rt_material_config_path),
        "phase_strategy": phase_strategy,
        "runtime_phase_claim": False,
        "enabled": False,
        "frames": [],
        "validation_summary": {
            "enabled_actor_count": 0,
            "frame_count": 0,
            "actor_sample_count": 0,
            "warning_count": 0,
            "warnings": [],
        },
    }


def build_actor_sample(
    *,
    actor_name: str,
    actor: dict[str, Any],
    actor_config: dict[str, Any],
    frame_id: int,
    source_sample_index: int,
    actor_time_seconds: float,
) -> dict[str, Any]:
    material_label = require_non_empty_string(
        actor_config.get("material_label"),
        f"actor_config.actors.{actor_name}.material_label",
    )
    animation_time_policy = require_non_empty_string(
        actor_config.get("animation_time_policy", "same_as_actor_time"),
        f"actor_config.actors.{actor_name}.animation_time_policy",
    )
    loop_policy = require_non_empty_string(
        actor_config.get("loop_policy", "mod_actor_script_duration"),
        f"actor_config.actors.{actor_name}.loop_policy",
    )

    trajectory = first_trajectory(actor, actor_name)
    if trajectory is None:
        if loop_policy != "static_pose":
            raise ActorFrameSampleError(
                f"Actor {actor_name} has no trajectory; enabled no-trajectory actors require "
                "loop_policy == 'static_pose'"
            )
        pose6 = actor.get("pose6")
        if not isinstance(pose6, list) or len(pose6) != 6:
            raise ActorFrameSampleError(f"Actor {actor_name} static pose6 is invalid")
        root_pose_source = "static_actor_pose"
        trajectory_id = None
        trajectory_type = None
        waypoint_time_seconds = None
    else:
        waypoint = find_exact_waypoint(actor_name, trajectory, actor_time_seconds)
        pose6 = waypoint.get("pose6")
        if not isinstance(pose6, list) or len(pose6) != 6:
            raise ActorFrameSampleError(
                f"Actor {actor_name} waypoint at {actor_time_seconds:g}s has invalid pose6"
            )
        root_pose_source = "trajectory_exact_waypoint"
        trajectory_id = trajectory.get("id")
        trajectory_type = trajectory.get("type")
        waypoint_time_seconds = waypoint.get("time_seconds")

    animation_time_seconds = actor_time_seconds
    if animation_time_policy != "same_as_actor_time":
        raise ActorFrameSampleError(
            f"Unsupported animation_time_policy for actor {actor_name}: {animation_time_policy!r}"
        )

    return {
        "actor_name": actor_name,
        "frame_id": frame_id,
        "source_sample_index": source_sample_index,
        "actor_time_seconds": actor_time_seconds,
        "animation_time_seconds": animation_time_seconds,
        "animation_time_policy": animation_time_policy,
        "loop_policy": loop_policy,
        "runtime_phase_claim": False,
        "root_pose_source": root_pose_source,
        "root_pose6": [float(value) for value in pose6],
        "material_label": material_label,
        "skin_uri": actor["skin"].get("uri"),
        "skin_path_resolved": actor["skin"].get("resolved_path"),
        "skin_scale": actor["skin"].get("scale"),
        "animation_name": actor["animation"].get("name") if isinstance(actor.get("animation"), dict) else None,
        "animation_uri": actor["animation"].get("uri") if isinstance(actor.get("animation"), dict) else None,
        "animation_path_resolved": (
            actor["animation"].get("resolved_path") if isinstance(actor.get("animation"), dict) else None
        ),
        "animation_interpolate_x": (
            actor["animation"].get("interpolate_x") if isinstance(actor.get("animation"), dict) else None
        ),
        "trajectory_id": trajectory_id,
        "trajectory_type": trajectory_type,
        "waypoint_time_seconds": waypoint_time_seconds,
    }


def build_manifest(config: BuildConfig) -> dict[str, Any]:
    actor_manifest = require_object(
        load_json(config.actor_manifest_path, "actor manifest"),
        "actor_manifest.json",
    )
    actor_config = require_object(
        load_json(config.actor_config_path, "actor dynamic config"),
        "actor_dynamic_config.json",
    )
    dynamic_config = require_object(
        load_json(config.dynamic_prototype_config_path, "dynamic prototype config"),
        "dynamic_prototype_config.json",
    )
    rt_material_config = require_object(
        load_json(config.rt_material_config_path, "RT material config"),
        "rt_material_mapping.json",
    )

    phase_strategy = require_non_empty_string(
        actor_config.get("metadata", {}).get("phase_strategy", "explicit_config_time")
        if isinstance(actor_config.get("metadata", {}), dict)
        else "explicit_config_time",
        "actor_dynamic_config.metadata.phase_strategy",
    )
    if phase_strategy != "explicit_config_time":
        raise ActorFrameSampleError(f"Unsupported actor phase_strategy: {phase_strategy!r}")

    global_enabled = require_bool(actor_config.get("enabled"), "actor_dynamic_config.enabled", default=True)
    if not global_enabled:
        return make_empty_manifest(config, phase_strategy)

    manifest_actors = actors_by_name(actor_manifest)
    material_labels = load_material_labels(rt_material_config)
    source_sample_by_frame = load_frame_source_samples(dynamic_config)

    raw_actor_configs = actor_config.get("actors")
    if not isinstance(raw_actor_configs, dict):
        raise ActorFrameSampleError("actor_dynamic_config.actors must be an object")

    frame_records: dict[int, dict[str, Any]] = {}
    enabled_actor_names: list[str] = []

    for actor_name, raw_actor_config in raw_actor_configs.items():
        actor_name = require_non_empty_string(actor_name, "actor config actor name")
        actor_cfg = require_object(raw_actor_config, f"actor_config.actors.{actor_name}")
        enabled = require_bool(actor_cfg.get("enabled"), f"actor_config.actors.{actor_name}.enabled", default=False)
        if not enabled:
            continue

        if actor_name not in manifest_actors:
            raise ActorFrameSampleError(f"Configured actor {actor_name!r} is missing from actor_manifest.json")
        actor = manifest_actors[actor_name]
        validate_actor_assets_resolved(actor, actor_name)

        material_label = require_non_empty_string(
            actor_cfg.get("material_label"),
            f"actor_config.actors.{actor_name}.material_label",
        )
        if material_label not in material_labels:
            known = ", ".join(sorted(material_labels))
            raise ActorFrameSampleError(
                f"Actor {actor_name} material_label={material_label!r} is not in RT material config. "
                f"Known labels: {known}"
            )

        frame_times = sorted_configured_frame_times(actor_cfg.get("frame_times_seconds"), actor_name)
        enabled_actor_names.append(actor_name)

        if not frame_times and first_trajectory(actor, actor_name) is not None:
            raise ActorFrameSampleError(f"Enabled trajectory actor {actor_name} has no configured frame times")

        for frame_id, actor_time_seconds in frame_times:
            if frame_id not in source_sample_by_frame:
                known = ", ".join(str(item) for item in sorted(source_sample_by_frame))
                raise ActorFrameSampleError(
                    f"Actor {actor_name} frame_id={frame_id} is missing from dynamic prototype frames. "
                    f"Known frame ids: {known}"
                )
            source_sample_index = source_sample_by_frame[frame_id]
            sample = build_actor_sample(
                actor_name=actor_name,
                actor=actor,
                actor_config=actor_cfg,
                frame_id=frame_id,
                source_sample_index=source_sample_index,
                actor_time_seconds=actor_time_seconds,
            )
            if frame_id not in frame_records:
                frame_records[frame_id] = {
                    "frame_id": frame_id,
                    "source_sample_index": source_sample_index,
                    "runtime_phase_claim": False,
                    "actors": [],
                }
            frame_records[frame_id]["actors"].append(sample)

    frames = [frame_records[frame_id] for frame_id in sorted(frame_records)]
    for frame in frames:
        actor_names = [sample["actor_name"] for sample in frame["actors"]]
        if len(actor_names) != len(set(actor_names)):
            raise ActorFrameSampleError(f"Frame {frame['frame_id']} contains duplicate actor samples")

    actor_sample_count = sum(len(frame["actors"]) for frame in frames)
    return {
        "generated_by": Path(__file__).name,
        "actor_manifest": str(config.actor_manifest_path),
        "actor_config": str(config.actor_config_path),
        "dynamic_prototype_config": str(config.dynamic_prototype_config_path),
        "rt_material_config": str(config.rt_material_config_path),
        "phase_strategy": phase_strategy,
        "runtime_phase_claim": False,
        "enabled": True,
        "frames": frames,
        "validation_summary": {
            "enabled_actor_count": len(enabled_actor_names),
            "enabled_actor_names": enabled_actor_names,
            "frame_count": len(frames),
            "actor_sample_count": actor_sample_count,
            "material_labels_used": sorted(
                {sample["material_label"] for frame in frames for sample in frame["actors"]}
            ),
            "root_pose_sources": sorted(
                {sample["root_pose_source"] for frame in frames for sample in frame["actors"]}
            ),
            "warning_count": 0,
            "warnings": [],
        },
    }


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    config = build_config(parse_args())
    try:
        manifest = build_manifest(config)
        save_json(config.output_path, manifest)
    except ActorFrameSampleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = manifest["validation_summary"]
    print("Actor frame sample build")
    print(f"actor_manifest: {config.actor_manifest_path}")
    print(f"actor_config: {config.actor_config_path}")
    print(f"dynamic_prototype_config: {config.dynamic_prototype_config_path}")
    print(f"rt_material_config: {config.rt_material_config_path}")
    print(f"output: {config.output_path}")
    print(f"enabled: {manifest['enabled']}")
    print(f"phase_strategy: {manifest['phase_strategy']}")
    print(f"runtime_phase_claim: {manifest['runtime_phase_claim']}")
    print(f"enabled_actor_count: {summary['enabled_actor_count']}")
    print(f"frame_count: {summary['frame_count']}")
    print(f"actor_sample_count: {summary['actor_sample_count']}")
    if summary.get("material_labels_used"):
        print("material_labels_used: " + ", ".join(summary["material_labels_used"]))
    if summary.get("root_pose_sources"):
        print("root_pose_sources: " + ", ".join(summary["root_pose_sources"]))
    print(f"warning_count: {summary['warning_count']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
