#!/usr/bin/env python3
"""Build actor samples for Blender visual validation.

This script intentionally does not export meshes and does not feed Sionna. It
creates a larger, explicit actor-time sample set so a later Blender validation
scene can check scale, floor contact, orientation, and trajectory plausibility.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACTOR_MANIFEST = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "manifests" / "actor_manifest.json"
DEFAULT_ACTOR_CONFIG = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "config" / "actor_dynamic_config.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_validation_samples.json"
EXACT_TIME_TOLERANCE_SECONDS = 1e-9
LARGE_ROOT_JUMP_METERS = 1.0
YAW_DISCONTINUITY_RADIANS = math.pi / 2.0


class ActorValidationSampleError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate actor samples for Blender visual validation."
    )
    parser.add_argument("--actor-manifest", type=Path, default=DEFAULT_ACTOR_MANIFEST)
    parser.add_argument("--actor-config", type=Path, default=DEFAULT_ACTOR_CONFIG)
    parser.add_argument("--actor-name", default=None, help="Optional enabled actor name to sample.")
    parser.add_argument("--num-frames", type=int, default=80)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument("--end-time", type=float, default=None)
    parser.add_argument(
        "--animation-time-policy",
        choices=("same_as_actor_time", "mod_clip_duration"),
        default="same_as_actor_time",
        help="How to convert actor trajectory time into animation clip time.",
    )
    parser.add_argument(
        "--animation-loop-duration-seconds",
        type=float,
        default=None,
        help="Positive clip loop duration required when --animation-time-policy=mod_clip_duration.",
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
        raise ActorValidationSampleError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorValidationSampleError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorValidationSampleError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActorValidationSampleError(f"{label} must be a non-empty string")
    return value.strip()


def require_bool(value: Any, label: str, default: bool | None = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise ActorValidationSampleError(f"{label} must be a boolean")
    return value


def require_pose6(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 6:
        raise ActorValidationSampleError(f"{label} must contain 6 values")
    try:
        pose = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ActorValidationSampleError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in pose):
        raise ActorValidationSampleError(f"{label} contains non-finite values")
    return pose


def actors_by_name(actor_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_actors = actor_manifest.get("actors")
    if not isinstance(raw_actors, list):
        raise ActorValidationSampleError("actor_manifest.json must contain an actors list")
    result: dict[str, dict[str, Any]] = {}
    for index, raw_actor in enumerate(raw_actors):
        actor = require_object(raw_actor, f"actor_manifest.actors[{index}]")
        actor_name = require_non_empty_string(
            actor.get("actor_name"),
            f"actor_manifest.actors[{index}].actor_name",
        )
        result[actor_name] = actor
    return result


def enabled_actor_configs(actor_config: dict[str, Any], requested_actor_name: str | None) -> dict[str, dict[str, Any]]:
    if require_bool(actor_config.get("enabled"), "actor_dynamic_config.enabled", default=True) is False:
        return {}
    raw_actor_configs = actor_config.get("actors")
    if not isinstance(raw_actor_configs, dict):
        raise ActorValidationSampleError("actor_dynamic_config.actors must be an object")

    selected: dict[str, dict[str, Any]] = {}
    for actor_name, raw_config in raw_actor_configs.items():
        actor_name = require_non_empty_string(actor_name, "actor config actor name")
        actor_cfg = require_object(raw_config, f"actor_dynamic_config.actors.{actor_name}")
        enabled = require_bool(
            actor_cfg.get("enabled"),
            f"actor_dynamic_config.actors.{actor_name}.enabled",
            default=False,
        )
        if not enabled:
            continue
        if requested_actor_name is not None and actor_name != requested_actor_name:
            continue
        selected[actor_name] = actor_cfg

    if requested_actor_name is not None and requested_actor_name not in selected:
        raise ActorValidationSampleError(
            f"Requested actor {requested_actor_name!r} is not enabled in actor_dynamic_config.json"
        )
    return selected


def first_trajectory(actor: dict[str, Any], actor_name: str) -> dict[str, Any]:
    script = require_object(actor.get("script"), f"actor {actor_name}.script")
    trajectories = script.get("trajectories")
    if not isinstance(trajectories, list):
        raise ActorValidationSampleError(f"actor {actor_name}.script.trajectories must be a list")
    for index, raw_trajectory in enumerate(trajectories):
        trajectory = require_object(raw_trajectory, f"actor {actor_name}.trajectory[{index}]")
        waypoints = trajectory.get("waypoints")
        if isinstance(waypoints, list) and waypoints:
            return trajectory
    raise ActorValidationSampleError(f"Actor {actor_name} has no trajectory for visual validation sampling")


def sorted_waypoints(trajectory: dict[str, Any], actor_name: str) -> list[dict[str, Any]]:
    raw_waypoints = trajectory.get("waypoints")
    if not isinstance(raw_waypoints, list) or len(raw_waypoints) < 2:
        raise ActorValidationSampleError(f"Actor {actor_name} trajectory must contain at least two waypoints")
    waypoints: list[dict[str, Any]] = []
    for index, raw_waypoint in enumerate(raw_waypoints):
        waypoint = require_object(raw_waypoint, f"actor {actor_name}.waypoints[{index}]")
        time_seconds = float(waypoint.get("time_seconds"))
        if not math.isfinite(time_seconds):
            raise ActorValidationSampleError(f"Actor {actor_name} waypoint[{index}] time is not finite")
        waypoints.append(
            {
                "time_seconds": time_seconds,
                "pose6": require_pose6(waypoint.get("pose6"), f"actor {actor_name}.waypoints[{index}].pose6"),
            }
        )
    waypoints.sort(key=lambda item: item["time_seconds"])
    return waypoints


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def shortest_angle_delta(start: float, end: float) -> float:
    return normalize_angle(end - start)


def interpolate_pose6(start_pose: list[float], end_pose: list[float], fraction: float) -> list[float]:
    pose = [
        start_pose[index] + fraction * (end_pose[index] - start_pose[index])
        for index in range(5)
    ]
    yaw = normalize_angle(start_pose[5] + fraction * shortest_angle_delta(start_pose[5], end_pose[5]))
    pose.append(yaw)
    return pose


def sample_time_grid(start_time: float, end_time: float, num_frames: int) -> list[float]:
    if num_frames < 50 or num_frames > 100:
        raise ActorValidationSampleError("--num-frames must be between 50 and 100 for this validation set")
    if not math.isfinite(start_time) or not math.isfinite(end_time):
        raise ActorValidationSampleError("--start-time and --end-time must be finite")
    if start_time < 0.0:
        raise ActorValidationSampleError("--start-time must be non-negative")
    if end_time < start_time:
        raise ActorValidationSampleError("--end-time must be >= --start-time")
    if num_frames == 1:
        return [start_time]
    step = (end_time - start_time) / float(num_frames - 1)
    return [start_time + step * index for index in range(num_frames)]


def pose_at_time(
    *,
    actor_name: str,
    waypoints: list[dict[str, Any]],
    sample_time: float,
    warnings: list[str],
) -> tuple[list[float], str, list[float]]:
    first_time = waypoints[0]["time_seconds"]
    last_time = waypoints[-1]["time_seconds"]
    if sample_time < first_time - EXACT_TIME_TOLERANCE_SECONDS or sample_time > last_time + EXACT_TIME_TOLERANCE_SECONDS:
        warnings.append(
            f"Actor {actor_name} sampled time {sample_time:.6f}s is outside trajectory range "
            f"{first_time:.6f}s..{last_time:.6f}s"
        )

    for waypoint in waypoints:
        if math.isclose(sample_time, waypoint["time_seconds"], abs_tol=EXACT_TIME_TOLERANCE_SECONDS):
            return waypoint["pose6"], "trajectory_exact_waypoint", [
                waypoint["time_seconds"],
                waypoint["time_seconds"],
            ]

    if sample_time <= first_time:
        return waypoints[0]["pose6"], "trajectory_linear_interpolation_unvalidated", [first_time, first_time]
    if sample_time >= last_time:
        return waypoints[-1]["pose6"], "trajectory_linear_interpolation_unvalidated", [last_time, last_time]

    for left, right in zip(waypoints, waypoints[1:]):
        left_time = left["time_seconds"]
        right_time = right["time_seconds"]
        if left_time <= sample_time <= right_time:
            fraction = (sample_time - left_time) / (right_time - left_time)
            return (
                interpolate_pose6(left["pose6"], right["pose6"], fraction),
                "trajectory_linear_interpolation_unvalidated",
                [left_time, right_time],
            )

    raise ActorValidationSampleError(f"Could not bracket sample time {sample_time:g}s for actor {actor_name}")


def resolve_animation_policy(args: argparse.Namespace) -> tuple[str, float | None]:
    animation_time_policy = str(args.animation_time_policy)
    loop_duration = args.animation_loop_duration_seconds
    if animation_time_policy == "same_as_actor_time":
        return animation_time_policy, None
    if animation_time_policy == "mod_clip_duration":
        if loop_duration is None:
            raise ActorValidationSampleError(
                "--animation-loop-duration-seconds is required when "
                "--animation-time-policy=mod_clip_duration"
            )
        loop_duration = float(loop_duration)
        if not math.isfinite(loop_duration) or loop_duration <= 0.0:
            raise ActorValidationSampleError("--animation-loop-duration-seconds must be finite and positive")
        return animation_time_policy, loop_duration
    raise ActorValidationSampleError(f"Unsupported animation time policy: {animation_time_policy!r}")


def animation_time_for_policy(
    actor_time_seconds: float,
    animation_time_policy: str,
    animation_loop_duration_seconds: float | None,
) -> float:
    if animation_time_policy == "same_as_actor_time":
        animation_time_seconds = actor_time_seconds
    elif animation_time_policy == "mod_clip_duration":
        if animation_loop_duration_seconds is None:
            raise ActorValidationSampleError("mod_clip_duration policy requires an animation loop duration")
        animation_time_seconds = actor_time_seconds % animation_loop_duration_seconds
    else:
        raise ActorValidationSampleError(f"Unsupported animation_time_policy: {animation_time_policy!r}")

    if not math.isfinite(animation_time_seconds) or animation_time_seconds < 0.0:
        raise ActorValidationSampleError("Computed animation_time_seconds must be finite and non-negative")
    return animation_time_seconds


def validate_assets(actor: dict[str, Any], actor_name: str) -> None:
    skin = require_object(actor.get("skin"), f"actor {actor_name}.skin")
    if skin.get("uri_status") != "resolved" or not skin.get("resolved_path"):
        raise ActorValidationSampleError(f"Actor {actor_name} skin asset is unresolved")
    animation = require_object(actor.get("animation"), f"actor {actor_name}.animation")
    if animation.get("uri_status") != "resolved" or not animation.get("resolved_path"):
        raise ActorValidationSampleError(f"Actor {actor_name} animation asset is unresolved")


def build_actor_samples(
    *,
    actor_name: str,
    actor: dict[str, Any],
    actor_cfg: dict[str, Any],
    sample_times: list[float],
    animation_time_policy: str,
    animation_loop_duration_seconds: float | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    validate_assets(actor, actor_name)
    trajectory = first_trajectory(actor, actor_name)
    waypoints = sorted_waypoints(trajectory, actor_name)
    loop_policy = require_non_empty_string(
        actor_cfg.get("loop_policy", "mod_actor_script_duration"),
        f"actor_config.{actor_name}.loop_policy",
    )
    material_label = require_non_empty_string(
        actor_cfg.get("material_label"),
        f"actor_config.{actor_name}.material_label",
    )
    actor_pose6 = require_pose6(actor.get("pose6"), f"actor {actor_name}.pose6")
    skin_scale = float(require_object(actor.get("skin"), f"actor {actor_name}.skin").get("scale"))
    skin_path = require_non_empty_string(actor["skin"].get("resolved_path"), f"actor {actor_name}.skin.resolved_path")
    animation_path = require_non_empty_string(
        actor["animation"].get("resolved_path"),
        f"actor {actor_name}.animation.resolved_path",
    )

    samples = []
    previous_pose: list[float] | None = None
    previous_time: float | None = None
    for validation_frame_id, sample_time in enumerate(sample_times):
        root_pose6, root_pose_source, neighbor_times = pose_at_time(
            actor_name=actor_name,
            waypoints=waypoints,
            sample_time=sample_time,
            warnings=warnings,
        )

        if previous_pose is not None and previous_time is not None:
            distance = math.sqrt(sum((root_pose6[index] - previous_pose[index]) ** 2 for index in range(3)))
            yaw_delta = abs(shortest_angle_delta(previous_pose[5], root_pose6[5]))
            if distance > LARGE_ROOT_JUMP_METERS:
                warnings.append(
                    f"Actor {actor_name} large root translation jump {distance:.3f}m between "
                    f"{previous_time:.6f}s and {sample_time:.6f}s"
                )
            if yaw_delta > YAW_DISCONTINUITY_RADIANS:
                warnings.append(
                    f"Actor {actor_name} yaw discontinuity {yaw_delta:.3f}rad between "
                    f"{previous_time:.6f}s and {sample_time:.6f}s"
                )
        previous_pose = root_pose6
        previous_time = sample_time

        samples.append(
            {
                "validation_frame_id": validation_frame_id,
                "actor_name": actor_name,
                "actor_time_seconds": sample_time,
                "animation_time_seconds": animation_time_for_policy(
                    sample_time,
                    animation_time_policy,
                    animation_loop_duration_seconds,
                ),
                "animation_time_policy": animation_time_policy,
                "animation_loop_duration_seconds": animation_loop_duration_seconds,
                "loop_policy": loop_policy,
                "runtime_phase_claim": False,
                "root_pose_source": root_pose_source,
                "root_pose6": root_pose6,
                "neighbor_waypoint_times": neighbor_times,
                "actor_pose6": actor_pose6,
                "skin_scale": skin_scale,
                "skin_path_resolved": skin_path,
                "animation_path_resolved": animation_path,
                "material_label": material_label,
                "trajectory_id": trajectory.get("id"),
                "trajectory_type": trajectory.get("type"),
            }
        )
    return samples


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    actor_manifest_path = resolve_path(args.actor_manifest)
    actor_config_path = resolve_path(args.actor_config)
    actor_manifest = require_object(load_json(actor_manifest_path, "actor manifest"), "actor_manifest.json")
    actor_config = require_object(load_json(actor_config_path, "actor config"), "actor_dynamic_config.json")
    animation_time_policy, animation_loop_duration_seconds = resolve_animation_policy(args)

    manifest_actors = actors_by_name(actor_manifest)
    selected_configs = enabled_actor_configs(actor_config, args.actor_name)
    warnings: list[str] = []

    disabled_ignored = [
        actor_name
        for actor_name, raw_actor_cfg in require_object(actor_config.get("actors"), "actor_dynamic_config.actors").items()
        if not require_bool(
            require_object(raw_actor_cfg, f"actor_dynamic_config.actors.{actor_name}").get("enabled"),
            f"actor_dynamic_config.actors.{actor_name}.enabled",
            default=False,
        )
    ]
    if disabled_ignored:
        warnings.append("Disabled/static actors ignored: " + ", ".join(sorted(disabled_ignored)))

    if not selected_configs:
        raise ActorValidationSampleError("No enabled actors selected for validation sampling")

    for actor_name in selected_configs:
        if actor_name not in manifest_actors:
            raise ActorValidationSampleError(f"Enabled actor {actor_name!r} missing from actor_manifest.json")

    first_actor_name = next(iter(selected_configs))
    first_actor = manifest_actors[first_actor_name]
    trajectory = first_trajectory(first_actor, first_actor_name)
    waypoints = sorted_waypoints(trajectory, first_actor_name)
    start_time = float(args.start_time)
    end_time = float(args.end_time) if args.end_time is not None else waypoints[-1]["time_seconds"]
    sample_times = sample_time_grid(start_time, end_time, int(args.num_frames))

    samples = []
    for actor_name, actor_cfg in selected_configs.items():
        samples.extend(
            build_actor_samples(
                actor_name=actor_name,
                actor=manifest_actors[actor_name],
                actor_cfg=actor_cfg,
                sample_times=sample_times,
                animation_time_policy=animation_time_policy,
                animation_loop_duration_seconds=animation_loop_duration_seconds,
                warnings=warnings,
            )
        )

    root_pose_sources = sorted({sample["root_pose_source"] for sample in samples})
    return {
        "generated_by": Path(__file__).name,
        "actor_manifest": str(actor_manifest_path),
        "actor_config": str(actor_config_path),
        "phase_strategy": "visual_validation_sampling",
        "runtime_phase_claim": False,
        "validation_only": True,
        "notes": [
            "These samples are for Blender visual validation only.",
            "They are not RT labels and do not claim Gazebo-runtime-perfect actor phase.",
            "When animation_time_policy is mod_clip_duration, animation time is looped only for visual validation and is not claimed to match Gazebo runtime phase.",
        ],
        "sampling": {
            "requested_actor_name": args.actor_name,
            "num_frames": int(args.num_frames),
            "start_time": start_time,
            "end_time": end_time,
            "time_grid": "uniform_inclusive",
            "animation_time_policy": animation_time_policy,
            "animation_loop_duration_seconds": animation_loop_duration_seconds,
        },
        "samples": samples,
        "validation_summary": {
            "sample_count": len(samples),
            "actor_count": len(selected_configs),
            "actor_names": sorted(selected_configs),
            "time_min": min(sample["actor_time_seconds"] for sample in samples),
            "time_max": max(sample["actor_time_seconds"] for sample in samples),
            "root_pose_sources": root_pose_sources,
            "warning_count": len(warnings),
            "warnings": warnings,
        },
    }


def main() -> int:
    args = parse_args()
    try:
        manifest = build_manifest(args)
        output_path = resolve_path(args.output)
        save_json(output_path, manifest)
    except ActorValidationSampleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = manifest["validation_summary"]
    print("Actor validation sample build")
    print(f"output: {resolve_path(args.output)}")
    print(f"phase_strategy: {manifest['phase_strategy']}")
    print(f"runtime_phase_claim: {manifest['runtime_phase_claim']}")
    print(f"actor_count: {summary['actor_count']}")
    print(f"sample_count: {summary['sample_count']}")
    print(f"time_min: {summary['time_min']}")
    print(f"time_max: {summary['time_max']}")
    print("root_pose_sources: " + ", ".join(summary["root_pose_sources"]))
    print(f"warning_count: {summary['warning_count']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
