#!/usr/bin/env python3

"""Build experiment-local actor frame samples compatible with export_actor_frame_meshes.py.

This stage consumes an experiment config plus a sampled-frame list and emits a
42-compatible `actor_frame_samples.json` file rooted under the experiment's own
output directory. It only prepares per-frame actor timing/pose metadata; it
does not export meshes and does not invoke Blender.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXACT_TIME_TOLERANCE_SECONDS = 1e-9


class ExperimentActorFrameSampleError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build experiment-local actor frame samples for export_actor_frame_meshes.py."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to experiment_config.json",
    )
    parser.add_argument(
        "--frames-json",
        type=Path,
        default=None,
        help="Optional sampled-frame JSON. Defaults to <output_root>/frames/sampled_frames.json",
    )
    parser.add_argument(
        "--dynamic-frames",
        type=Path,
        default=None,
        help=(
            "Optional dynamic-frames JSON. Defaults to <output_root>/frames/dynamic_frames.json "
            "when actor_time_policy=timestamp_mod_trajectory_duration"
        ),
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional debug limit on the number of selected frame records.",
    )
    parser.add_argument(
        "--frame-ids",
        default=None,
        help="Optional comma-separated list of frame_ids to select.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output JSON path. Defaults to <output_root>/frames/actor_frame_samples.json",
    )
    return parser.parse_args()


def load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ExperimentActorFrameSampleError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentActorFrameSampleError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentActorFrameSampleError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExperimentActorFrameSampleError(f"{label} must be a list")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentActorFrameSampleError(f"{label} must be a non-empty string")
    return value.strip()


def require_bool(value: Any, label: str, *, default: bool | None = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise ExperimentActorFrameSampleError(f"{label} must be a boolean")
    return value


def require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ExperimentActorFrameSampleError(f"{label} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentActorFrameSampleError(f"{label} must be a non-negative integer") from exc
    if parsed < 0:
        raise ExperimentActorFrameSampleError(f"{label} must be a non-negative integer")
    return parsed


def require_positive_int(value: Any, label: str) -> int:
    parsed = require_non_negative_int(value, label)
    if parsed <= 0:
        raise ExperimentActorFrameSampleError(f"{label} must be a positive integer")
    return parsed


def require_non_negative_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ExperimentActorFrameSampleError(f"{label} must be a non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentActorFrameSampleError(f"{label} must be a non-negative number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ExperimentActorFrameSampleError(f"{label} must be finite and non-negative")
    return number


def require_pose6(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 6:
        raise ExperimentActorFrameSampleError(f"{label} must contain 6 values")
    try:
        pose = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ExperimentActorFrameSampleError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in pose):
        raise ExperimentActorFrameSampleError(f"{label} contains non-finite values")
    return pose


def resolve_project_path(path_value: Path | str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def parse_frame_ids(text: str | None) -> set[int] | None:
    if text is None:
        return None
    items = [item.strip() for item in text.split(",")]
    if not items or any(not item for item in items):
        raise ExperimentActorFrameSampleError("--frame-ids must be a comma-separated list like 0,1,2")
    frame_ids: set[int] = set()
    for index, item in enumerate(items):
        frame_id = require_non_negative_int(item, f"--frame-ids[{index}]")
        if frame_id in frame_ids:
            raise ExperimentActorFrameSampleError(f"--frame-ids contains duplicate frame_id={frame_id}")
        frame_ids.add(frame_id)
    return frame_ids


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def shortest_angle_delta(start: float, end: float) -> float:
    return normalize_angle(end - start)


def interpolate_pose6(start_pose: list[float], end_pose: list[float], fraction: float) -> list[float]:
    pose = [
        start_pose[index] + fraction * (end_pose[index] - start_pose[index])
        for index in range(5)
    ]
    pose.append(normalize_angle(start_pose[5] + fraction * shortest_angle_delta(start_pose[5], end_pose[5])))
    return pose


def animation_time_for_policy(
    actor_time_seconds: float,
    animation_time_policy: str,
    animation_loop_duration_seconds: float | None,
) -> float:
    if animation_time_policy == "mod_clip_duration":
        if animation_loop_duration_seconds is None:
            raise ExperimentActorFrameSampleError(
                "mod_clip_duration requires animation_loop_duration_seconds"
            )
        animation_time_seconds = actor_time_seconds % animation_loop_duration_seconds
    else:
        raise ExperimentActorFrameSampleError(
            f"Unsupported animation_time_policy: {animation_time_policy!r}"
        )
    if not math.isfinite(animation_time_seconds) or animation_time_seconds < 0.0:
        raise ExperimentActorFrameSampleError("Computed animation_time_seconds must be finite and non-negative")
    return animation_time_seconds


def actors_by_name(actor_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    actors = actor_manifest.get("actors")
    if not isinstance(actors, list):
        raise ExperimentActorFrameSampleError("actor_manifest.json must contain an actors list")
    result: dict[str, dict[str, Any]] = {}
    for index, raw_actor in enumerate(actors):
        actor = require_object(raw_actor, f"actor_manifest.actors[{index}]")
        actor_name = require_non_empty_string(
            actor.get("actor_name"),
            f"actor_manifest.actors[{index}].actor_name",
        )
        if actor_name in result:
            raise ExperimentActorFrameSampleError(f"Duplicate actor in actor manifest: {actor_name}")
        result[actor_name] = actor
    return result


def require_resolved_asset(path_value: Any, label: str) -> str:
    path = Path(require_non_empty_string(path_value, label))
    if not path.exists():
        raise ExperimentActorFrameSampleError(f"{label} does not exist: {path}")
    return str(path.resolve())


def validate_actor_assets(actor: dict[str, Any], actor_name: str) -> None:
    skin = require_object(actor.get("skin"), f"actor {actor_name}.skin")
    if skin.get("uri_status") != "resolved":
        raise ExperimentActorFrameSampleError(f"Actor {actor_name} skin asset is unresolved")
    animation = require_object(actor.get("animation"), f"actor {actor_name}.animation")
    if animation.get("uri_status") != "resolved":
        raise ExperimentActorFrameSampleError(f"Actor {actor_name} animation asset is unresolved")


def first_trajectory(actor: dict[str, Any], actor_name: str) -> dict[str, Any]:
    script = require_object(actor.get("script"), f"actor {actor_name}.script")
    trajectories = script.get("trajectories")
    if not isinstance(trajectories, list):
        raise ExperimentActorFrameSampleError(f"actor {actor_name}.script.trajectories must be a list")
    for index, raw_trajectory in enumerate(trajectories):
        trajectory = require_object(raw_trajectory, f"actor {actor_name}.trajectory[{index}]")
        waypoints = trajectory.get("waypoints")
        if isinstance(waypoints, list) and waypoints:
            return trajectory
    raise ExperimentActorFrameSampleError(f"Actor {actor_name} has no trajectory")


def sorted_waypoints(trajectory: dict[str, Any], actor_name: str) -> list[dict[str, Any]]:
    raw_waypoints = trajectory.get("waypoints")
    if not isinstance(raw_waypoints, list) or not raw_waypoints:
        raise ExperimentActorFrameSampleError(f"Actor {actor_name} trajectory must contain waypoints")
    waypoints: list[dict[str, Any]] = []
    for index, raw_waypoint in enumerate(raw_waypoints):
        waypoint = require_object(raw_waypoint, f"actor {actor_name}.waypoints[{index}]")
        time_seconds = require_non_negative_float(
            waypoint.get("time_seconds"),
            f"actor {actor_name}.waypoints[{index}].time_seconds",
        )
        pose6 = require_pose6(
            waypoint.get("pose6"),
            f"actor {actor_name}.waypoints[{index}].pose6",
        )
        waypoints.append(
            {
                "time_seconds": time_seconds,
                "pose6": pose6,
            }
        )
    waypoints.sort(key=lambda item: item["time_seconds"])
    return waypoints


def pose_at_time(
    *,
    actor_name: str,
    waypoints: list[dict[str, Any]],
    sample_time: float,
    warnings: list[str],
) -> tuple[list[float], str]:
    first_time = waypoints[0]["time_seconds"]
    last_time = waypoints[-1]["time_seconds"]
    if sample_time < first_time - EXACT_TIME_TOLERANCE_SECONDS or sample_time > last_time + EXACT_TIME_TOLERANCE_SECONDS:
        warnings.append(
            f"Actor {actor_name} sampled time {sample_time:.6f}s is outside trajectory range "
            f"{first_time:.6f}s..{last_time:.6f}s"
        )

    for waypoint in waypoints:
        if math.isclose(sample_time, waypoint["time_seconds"], abs_tol=EXACT_TIME_TOLERANCE_SECONDS):
            return waypoint["pose6"], "trajectory_exact_waypoint"

    if sample_time <= first_time:
        return waypoints[0]["pose6"], "trajectory_linear_interpolation_unvalidated"
    if sample_time >= last_time:
        return waypoints[-1]["pose6"], "trajectory_linear_interpolation_unvalidated"

    for left, right in zip(waypoints, waypoints[1:]):
        left_time = left["time_seconds"]
        right_time = right["time_seconds"]
        if left_time <= sample_time <= right_time:
            fraction = (sample_time - left_time) / (right_time - left_time)
            return (
                interpolate_pose6(left["pose6"], right["pose6"], fraction),
                "trajectory_linear_interpolation_unvalidated",
            )

    raise ExperimentActorFrameSampleError(
        f"Could not bracket sample time {sample_time:g}s for actor {actor_name}"
    )


def actor_times_for_selected_frames(frame_count: int, trajectory_duration_seconds: float) -> list[float]:
    if frame_count <= 0:
        return []
    if frame_count == 1:
        return [0.0]
    step = trajectory_duration_seconds / float(frame_count - 1)
    return [step * index for index in range(frame_count)]


def actor_times_from_dynamic_frame_timestamps(
    selected_records: list[dict[str, int]],
    *,
    dynamic_frames_path: Path,
    trajectory_duration_seconds: float,
) -> list[float]:
    data = load_json(dynamic_frames_path, "dynamic frames")
    raw_frames = data.get("frames") if isinstance(data, dict) else data
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ExperimentActorFrameSampleError(
            "dynamic frames JSON must be a non-empty list or object with frames list"
        )

    dynamic_frame_map: dict[int, tuple[int, float]] = {}
    for index, raw_frame in enumerate(raw_frames):
        frame = require_object(raw_frame, f"dynamic_frames[{index}]")
        frame_id = require_non_negative_int(frame.get("frame_id"), f"dynamic_frames[{index}].frame_id")
        source_sample_index = require_non_negative_int(
            frame.get("source_sample_index"),
            f"dynamic_frames[{index}].source_sample_index",
        )
        timestamp = require_object(frame.get("timestamp"), f"dynamic_frames[{index}].timestamp")
        sec = require_non_negative_int(timestamp.get("sec"), f"dynamic_frames[{index}].timestamp.sec")
        nsec = require_non_negative_int(timestamp.get("nsec"), f"dynamic_frames[{index}].timestamp.nsec")
        if nsec >= 1_000_000_000:
            raise ExperimentActorFrameSampleError(
                f"dynamic_frames[{index}].timestamp.nsec must be < 1e9"
            )
        timestamp_seconds = require_non_negative_float(
            timestamp.get("seconds"),
            f"dynamic_frames[{index}].timestamp.seconds",
        )
        exact_timestamp_seconds = sec + nsec / 1_000_000_000.0
        if not math.isclose(
            timestamp_seconds,
            exact_timestamp_seconds,
            abs_tol=EXACT_TIME_TOLERANCE_SECONDS,
        ):
            raise ExperimentActorFrameSampleError(
                f"dynamic_frames[{index}] timestamp.seconds does not match sec/nsec"
            )
        if frame_id in dynamic_frame_map:
            raise ExperimentActorFrameSampleError(
                f"Duplicate frame_id in dynamic frames JSON: {frame_id}"
            )
        dynamic_frame_map[frame_id] = (source_sample_index, timestamp_seconds)

    actor_times: list[float] = []
    for record in selected_records:
        frame_id = record["frame_id"]
        dynamic_record = dynamic_frame_map.get(frame_id)
        if dynamic_record is None:
            raise ExperimentActorFrameSampleError(
                f"Missing frame_id={frame_id} in dynamic frames JSON {dynamic_frames_path}"
            )
        dynamic_source_sample_index, timestamp_seconds = dynamic_record
        if dynamic_source_sample_index != record["source_sample_index"]:
            raise ExperimentActorFrameSampleError(
                f"Frame mismatch for frame_id={frame_id}: sampled_frames source_sample_index="
                f"{record['source_sample_index']} but dynamic_frames source_sample_index="
                f"{dynamic_source_sample_index}"
            )
        actor_time_seconds = timestamp_seconds % trajectory_duration_seconds
        if math.isclose(
            actor_time_seconds,
            0.0,
            abs_tol=EXACT_TIME_TOLERANCE_SECONDS,
        ):
            actor_time_seconds = 0.0
        actor_times.append(actor_time_seconds)

    if len(actor_times) != len(selected_records):
        raise ExperimentActorFrameSampleError(
            f"Expected {len(selected_records)} actor timestamps, got {len(actor_times)}"
        )
    return actor_times


def load_experiment_config(path: Path) -> dict[str, Any]:
    config = require_object(load_json(path, "experiment config"), "experiment_config.json")
    experiment_name = require_non_empty_string(
        config.get("experiment_name"),
        "experiment_config.experiment_name",
    )
    output_dir = require_non_empty_string(
        config.get("output_dir"),
        "experiment_config.output_dir",
    )
    output_root = resolve_project_path(output_dir)

    actors = require_object(config.get("actors"), "experiment_config.actors")
    enabled = require_bool(actors.get("enabled"), "experiment_config.actors.enabled", default=False)
    actor_manifest_path = resolve_project_path(
        require_non_empty_string(
            actors.get("actor_manifest"),
            "experiment_config.actors.actor_manifest",
        )
    )
    actor_name = require_non_empty_string(
        actors.get("actor_name"),
        "experiment_config.actors.actor_name",
    )
    material_label = require_non_empty_string(
        actors.get("material_label"),
        "experiment_config.actors.material_label",
    )
    actor_time_policy = require_non_empty_string(
        actors.get("actor_time_policy"),
        "experiment_config.actors.actor_time_policy",
    )
    if actor_time_policy not in {
        "uniform_over_actor_trajectory",
        "timestamp_mod_trajectory_duration",
    }:
        raise ExperimentActorFrameSampleError(
            f"Unsupported actor_time_policy: {actor_time_policy!r}"
        )
    trajectory_duration_seconds = require_non_negative_float(
        actors.get("trajectory_duration_seconds"),
        "experiment_config.actors.trajectory_duration_seconds",
    )
    animation_time_policy = require_non_empty_string(
        actors.get("animation_time_policy"),
        "experiment_config.actors.animation_time_policy",
    )
    if animation_time_policy != "mod_clip_duration":
        raise ExperimentActorFrameSampleError(
            f"Unsupported animation_time_policy: {animation_time_policy!r}"
        )
    animation_loop_duration_seconds = require_non_negative_float(
        actors.get("animation_loop_duration_seconds"),
        "experiment_config.actors.animation_loop_duration_seconds",
    )
    if animation_loop_duration_seconds <= 0.0:
        raise ExperimentActorFrameSampleError(
            "experiment_config.actors.animation_loop_duration_seconds must be positive"
        )
    runtime_phase_claim = require_bool(
        actors.get("runtime_phase_claim"),
        "experiment_config.actors.runtime_phase_claim",
        default=False,
    )

    return {
        "config_path": path.resolve(),
        "experiment_name": experiment_name,
        "output_root": output_root,
        "actors": {
            "enabled": enabled,
            "actor_manifest_path": actor_manifest_path,
            "actor_name": actor_name,
            "material_label": material_label,
            "actor_time_policy": actor_time_policy,
            "trajectory_duration_seconds": trajectory_duration_seconds,
            "animation_time_policy": animation_time_policy,
            "animation_loop_duration_seconds": animation_loop_duration_seconds,
            "alignment_policy": actors.get("alignment_policy"),
            "z_alignment_policy": actors.get("z_alignment_policy"),
            "floor_z": actors.get("floor_z"),
            "runtime_phase_claim": runtime_phase_claim,
        },
    }


def default_frames_json(output_root: Path) -> Path:
    return output_root / "frames" / "sampled_frames.json"


def default_output_json(output_root: Path) -> Path:
    return output_root / "frames" / "actor_frame_samples.json"


def default_dynamic_frames_json(output_root: Path) -> Path:
    return output_root / "frames" / "dynamic_frames.json"


def load_frame_records(path: Path) -> list[dict[str, int]]:
    data = load_json(path, "sampled frames")
    raw_frames = data.get("frames") if isinstance(data, dict) else data
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ExperimentActorFrameSampleError("frames JSON must be a non-empty list or object with frames list")

    records: list[dict[str, int]] = []
    seen_frame_ids: set[int] = set()
    for index, raw_frame in enumerate(raw_frames):
        frame = require_object(raw_frame, f"frames[{index}]")
        frame_id = require_non_negative_int(frame.get("frame_id"), f"frames[{index}].frame_id")
        source_value = frame.get("source_sample_index", frame.get("source_sample"))
        source_sample_index = require_non_negative_int(
            source_value,
            f"frames[{index}].source_sample_index",
        )
        if frame_id in seen_frame_ids:
            raise ExperimentActorFrameSampleError(f"Duplicate frame_id in frames JSON: {frame_id}")
        seen_frame_ids.add(frame_id)
        records.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
            }
        )
    return records


def select_frame_records(
    records: list[dict[str, int]],
    *,
    max_frames: int | None,
    frame_ids: set[int] | None,
) -> list[dict[str, int]]:
    if max_frames is not None and frame_ids is not None:
        raise ExperimentActorFrameSampleError("Pass only one of --max-frames or --frame-ids, not both")
    if max_frames is not None:
        if max_frames <= 0:
            raise ExperimentActorFrameSampleError("--max-frames must be a positive integer")
        return records[:max_frames]
    if frame_ids is not None:
        selected = [record for record in records if record["frame_id"] in frame_ids]
        missing = sorted(frame_ids - {record["frame_id"] for record in selected})
        if missing:
            raise ExperimentActorFrameSampleError(
                "Requested frame_ids are missing from frames JSON: " + ", ".join(str(item) for item in missing)
            )
        return selected
    return list(records)


def empty_manifest(
    *,
    experiment: dict[str, Any],
    frames_json_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    return {
        "generated_by": Path(__file__).name,
        "experiment_name": experiment["experiment_name"],
        "config_path": str(experiment["config_path"]),
        "actor_manifest": relpath(experiment["actors"]["actor_manifest_path"]),
        "frames_json": str(frames_json_path),
        "selected_frame_count": 0,
        "actor_time_policy": experiment["actors"]["actor_time_policy"],
        "trajectory_duration_seconds": experiment["actors"]["trajectory_duration_seconds"],
        "animation_time_policy": experiment["actors"]["animation_time_policy"],
        "animation_loop_duration_seconds": experiment["actors"]["animation_loop_duration_seconds"],
        "runtime_phase_claim": experiment["actors"]["runtime_phase_claim"],
        "output_path": str(output_path),
        "enabled": False,
        "frames": [],
        "validation_summary": {
            "enabled": False,
            "enabled_actor_count": 0,
            "frame_count": 0,
            "actor_sample_count": 0,
            "first_frame_id": None,
            "last_frame_id": None,
            "first_source_sample_index": None,
            "last_source_sample_index": None,
            "first_actor_time_seconds": None,
            "last_actor_time_seconds": None,
            "material_labels_used": [],
            "root_pose_sources": [],
            "warning_count": 0,
            "warnings": [],
        },
    }


def build_actor_sample(
    *,
    actor_name: str,
    actor: dict[str, Any],
    material_label: str,
    source_record: dict[str, int],
    actor_time_seconds: float,
    animation_time_policy: str,
    animation_loop_duration_seconds: float,
    runtime_phase_claim: bool,
    waypoints: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    root_pose6, root_pose_source = pose_at_time(
        actor_name=actor_name,
        waypoints=waypoints,
        sample_time=actor_time_seconds,
        warnings=warnings,
    )

    skin = require_object(actor.get("skin"), f"actor {actor_name}.skin")
    animation = require_object(actor.get("animation"), f"actor {actor_name}.animation")
    trajectory = first_trajectory(actor, actor_name)

    return {
        "actor_name": actor_name,
        "frame_id": source_record["frame_id"],
        "source_sample_index": source_record["source_sample_index"],
        "actor_time_seconds": actor_time_seconds,
        "animation_time_seconds": animation_time_for_policy(
            actor_time_seconds,
            animation_time_policy,
            animation_loop_duration_seconds,
        ),
        "animation_time_policy": animation_time_policy,
        "loop_policy": "mod_actor_script_duration",
        "runtime_phase_claim": runtime_phase_claim,
        "root_pose_source": root_pose_source,
        "root_pose6": root_pose6,
        "material_label": material_label,
        "skin_uri": skin.get("uri"),
        "skin_path_resolved": require_resolved_asset(
            skin.get("resolved_path"),
            f"actor {actor_name}.skin.resolved_path",
        ),
        "skin_scale": float(skin.get("scale")),
        "animation_name": animation.get("name"),
        "animation_uri": animation.get("uri"),
        "animation_path_resolved": require_resolved_asset(
            animation.get("resolved_path"),
            f"actor {actor_name}.animation.resolved_path",
        ),
        "animation_interpolate_x": animation.get("interpolate_x"),
        "trajectory_id": trajectory.get("id"),
        "trajectory_type": trajectory.get("type"),
    }


def build_manifest(
    *,
    experiment: dict[str, Any],
    frames_json_path: Path,
    dynamic_frames_path: Path | None,
    selected_records: list[dict[str, int]],
    output_path: Path,
) -> dict[str, Any]:
    warnings: list[str] = []
    actor_options = experiment["actors"]
    if actor_options["enabled"] is False:
        return empty_manifest(
            experiment=experiment,
            frames_json_path=frames_json_path,
            output_path=output_path,
        )

    actor_manifest = require_object(
        load_json(actor_options["actor_manifest_path"], "actor manifest"),
        "actor_manifest.json",
    )
    actor_map = actors_by_name(actor_manifest)
    actor_name = actor_options["actor_name"]
    if actor_name not in actor_map:
        raise ExperimentActorFrameSampleError(
            f"Configured actor {actor_name!r} is missing from actor_manifest.json"
        )
    actor = actor_map[actor_name]
    validate_actor_assets(actor, actor_name)

    trajectory = first_trajectory(actor, actor_name)
    waypoints = sorted_waypoints(trajectory, actor_name)
    actual_duration_seconds = waypoints[-1]["time_seconds"]
    configured_duration_seconds = actor_options["trajectory_duration_seconds"]
    if not math.isclose(
        actual_duration_seconds,
        configured_duration_seconds,
        abs_tol=1e-6,
    ):
        warnings.append(
            "Configured trajectory_duration_seconds differs from actor manifest "
            f"duration ({configured_duration_seconds:.6f}s vs {actual_duration_seconds:.6f}s)"
        )

    if actor_options["actor_time_policy"] == "uniform_over_actor_trajectory":
        actor_times = actor_times_for_selected_frames(
            len(selected_records),
            configured_duration_seconds,
        )
    elif actor_options["actor_time_policy"] == "timestamp_mod_trajectory_duration":
        if dynamic_frames_path is None:
            raise ExperimentActorFrameSampleError(
                "timestamp_mod_trajectory_duration requires dynamic_frames.json"
            )
        actor_times = actor_times_from_dynamic_frame_timestamps(
            selected_records,
            dynamic_frames_path=dynamic_frames_path,
            trajectory_duration_seconds=configured_duration_seconds,
        )
    else:
        raise ExperimentActorFrameSampleError(
            f"Unsupported actor_time_policy: {actor_options['actor_time_policy']!r}"
        )
    frames: list[dict[str, Any]] = []
    actor_sample_count = 0

    for source_record, actor_time_seconds in zip(selected_records, actor_times):
        sample = build_actor_sample(
            actor_name=actor_name,
            actor=actor,
            material_label=actor_options["material_label"],
            source_record=source_record,
            actor_time_seconds=actor_time_seconds,
            animation_time_policy=actor_options["animation_time_policy"],
            animation_loop_duration_seconds=actor_options["animation_loop_duration_seconds"],
            runtime_phase_claim=actor_options["runtime_phase_claim"],
            waypoints=waypoints,
            warnings=warnings,
        )
        frames.append(
            {
                "frame_id": source_record["frame_id"],
                "source_sample_index": source_record["source_sample_index"],
                "runtime_phase_claim": actor_options["runtime_phase_claim"],
                "actors": [sample],
            }
        )
        actor_sample_count += 1

    root_pose_sources = sorted({sample["root_pose_source"] for frame in frames for sample in frame["actors"]})
    material_labels_used = sorted({sample["material_label"] for frame in frames for sample in frame["actors"]})
    first_frame = frames[0] if frames else None
    last_frame = frames[-1] if frames else None
    first_actor_time_seconds = frames[0]["actors"][0]["actor_time_seconds"] if frames else None
    last_actor_time_seconds = frames[-1]["actors"][0]["actor_time_seconds"] if frames else None

    return {
        "generated_by": Path(__file__).name,
        "experiment_name": experiment["experiment_name"],
        "config_path": str(experiment["config_path"]),
        "actor_manifest": relpath(actor_options["actor_manifest_path"]),
        "frames_json": str(frames_json_path),
        "selected_frame_count": len(selected_records),
        "actor_time_policy": actor_options["actor_time_policy"],
        "trajectory_duration_seconds": actor_options["trajectory_duration_seconds"],
        "animation_time_policy": actor_options["animation_time_policy"],
        "animation_loop_duration_seconds": actor_options["animation_loop_duration_seconds"],
        "runtime_phase_claim": actor_options["runtime_phase_claim"],
        "output_path": str(output_path),
        "enabled": True,
        "frames": frames,
        "validation_summary": {
            "enabled": True,
            "enabled_actor_count": 1,
            "frame_count": len(frames),
            "actor_sample_count": actor_sample_count,
            "first_frame_id": first_frame["frame_id"] if first_frame is not None else None,
            "last_frame_id": last_frame["frame_id"] if last_frame is not None else None,
            "first_source_sample_index": (
                first_frame["source_sample_index"] if first_frame is not None else None
            ),
            "last_source_sample_index": (
                last_frame["source_sample_index"] if last_frame is not None else None
            ),
            "first_actor_time_seconds": first_actor_time_seconds,
            "last_actor_time_seconds": last_actor_time_seconds,
            "material_labels_used": material_labels_used,
            "root_pose_sources": root_pose_sources,
            "warning_count": len(warnings),
            "warnings": warnings,
        },
    }


def main() -> int:
    args = parse_args()
    try:
        config_path = resolve_project_path(args.config)
        experiment = load_experiment_config(config_path)
        frames_json_path = (
            resolve_project_path(args.frames_json)
            if args.frames_json is not None
            else default_frames_json(experiment["output_root"])
        )
        dynamic_frames_path = (
            resolve_project_path(args.dynamic_frames)
            if args.dynamic_frames is not None
            else default_dynamic_frames_json(experiment["output_root"])
        )
        output_path = (
            resolve_project_path(args.output)
            if args.output is not None
            else default_output_json(experiment["output_root"])
        )
        frame_ids = parse_frame_ids(args.frame_ids)
        all_records = load_frame_records(frames_json_path)
        selected_records = select_frame_records(
            all_records,
            max_frames=args.max_frames,
            frame_ids=frame_ids,
        )
        manifest = build_manifest(
            experiment=experiment,
            frames_json_path=frames_json_path,
            dynamic_frames_path=dynamic_frames_path,
            selected_records=selected_records,
            output_path=output_path,
        )
        save_json(output_path, manifest)
    except ExperimentActorFrameSampleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = manifest["validation_summary"]
    print(f"experiment_name: {manifest['experiment_name']}")
    print(f"config_path: {manifest['config_path']}")
    print(f"frames_json: {manifest['frames_json']}")
    print(f"output_path: {manifest['output_path']}")
    print(f"enabled: {summary['enabled']}")
    print(f"selected_frame_count: {manifest['selected_frame_count']}")
    print(f"actor_sample_count: {summary['actor_sample_count']}")
    print(f"first_frame_id: {summary['first_frame_id']}")
    print(f"last_frame_id: {summary['last_frame_id']}")
    print(f"first_source_sample_index: {summary['first_source_sample_index']}")
    print(f"last_source_sample_index: {summary['last_source_sample_index']}")
    print(f"first_actor_time_seconds: {summary['first_actor_time_seconds']}")
    print(f"last_actor_time_seconds: {summary['last_actor_time_seconds']}")
    print("root_pose_sources: " + ", ".join(summary["root_pose_sources"]))
    print(f"warning_count: {summary['warning_count']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
