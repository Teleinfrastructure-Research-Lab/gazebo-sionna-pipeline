#!/usr/bin/env python3

"""Build per-frame dynamic pose records from the prototype robot pose logs.

This stage reads the Panda and UR5 logs, finds the requested source samples, and
writes a normalized JSON description of each dynamic frame so later scripts can
attach mesh visuals and export posed geometry reproducibly.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_MANIFEST_PATH = PROJECT_ROOT / "rt_out" / "manifests" / "dynamic_manifest.json"
OUTPUT_PATH = PROJECT_ROOT / "rt_out" / "dynamic_frames" / "prototype_frames.json"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
DEFAULT_PROTOTYPE_FRAMES = PROTOTYPE_CONFIG["prototype_frames"]
MODEL_ORDER = PROTOTYPE_CONFIG["model_names"]
MODEL_CONFIG = {
    model_name: {
        "log_path": model_config["pose_log_path"],
        "expected_links": model_config["expected_link_count"],
    }
    for model_name, model_config in PROTOTYPE_CONFIG["dynamic_models"].items()
}


class DynamicFrameError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract selected dynamic frame records from validated Panda + ur5_rg2 pose logs."
    )
    parser.add_argument(
        "--frames-json",
        type=Path,
        default=None,
        help="Optional frame selection JSON with frame_id/source_sample records.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Output JSON path. Defaults to the validated prototype output path.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise DynamicFrameError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DynamicFrameError(f"Invalid JSON in {path}: {exc}") from exc


def require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DynamicFrameError(f"{label} must be a non-negative integer")
    return value


def load_selected_frames(path: Path | None) -> list[dict[str, int]]:
    # Default to the validated 3-frame prototype selection, but also allow
    # experiment-specific frame lists while preserving the same frame schema.
    if path is None:
        return [
            {
                "frame_id": int(frame["frame_id"]),
                "source_sample_index": int(frame["source_sample_index"]),
            }
            for frame in DEFAULT_PROTOTYPE_FRAMES
        ]

    raw = load_json(path.expanduser().resolve())
    if isinstance(raw, dict):
        raw_frames = raw.get("frames")
    else:
        raw_frames = raw

    if not isinstance(raw_frames, list) or not raw_frames:
        raise DynamicFrameError("Custom frames JSON must be a non-empty list or an object with frames list")

    frames: list[dict[str, int]] = []
    seen_frame_ids: set[int] = set()
    seen_source_samples: set[int] = set()
    previous_source_sample: int | None = None

    for index, item in enumerate(raw_frames):
        if not isinstance(item, dict):
            raise DynamicFrameError(f"frames[{index}] must be an object")
        frame_id = require_non_negative_int(item.get("frame_id"), f"frames[{index}].frame_id")
        source_value = item.get("source_sample_index", item.get("source_sample"))
        source_sample_index = require_non_negative_int(
            source_value,
            f"frames[{index}].source_sample",
        )
        if frame_id in seen_frame_ids:
            raise DynamicFrameError(f"Duplicate frame_id in custom frames JSON: {frame_id}")
        if source_sample_index in seen_source_samples:
            raise DynamicFrameError(
                f"Duplicate source_sample in custom frames JSON: {source_sample_index}"
            )
        if previous_source_sample is not None and source_sample_index <= previous_source_sample:
            raise DynamicFrameError("Custom source_sample values must be strictly increasing")
        seen_frame_ids.add(frame_id)
        seen_source_samples.add(source_sample_index)
        previous_source_sample = source_sample_index
        frames.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
            }
        )

    return frames


def parse_pose6(value: Any, label: str) -> list[float]:
    if isinstance(value, str):
        parts = value.split()
    elif isinstance(value, list):
        parts = value
    else:
        raise DynamicFrameError(f"{label} must be a 6-value pose string or list")

    if len(parts) != 6:
        raise DynamicFrameError(f"{label} must contain 6 values, got {len(parts)}")

    try:
        return [float(item) for item in parts]
    except (TypeError, ValueError) as exc:
        raise DynamicFrameError(f"{label} contains a non-numeric value") from exc


def pose6_to_matrix(pose: list[float]) -> list[list[float]]:
    # Convert the model pose from the manifest into a homogeneous transform so
    # it can be chained with logged link poses later.
    x, y, z, roll, pitch, yaw = pose

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y],
        [-sp, cp * sr, cp * cr, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def quaternion_to_matrix(quat_xyzw: list[float]) -> list[list[float]]:
    # Gazebo pose logs store link orientation as quaternions. Normalize them
    # before conversion so malformed or non-unit quaternions are caught early.
    x, y, z, w = quat_xyzw
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm <= 1e-12:
        raise DynamicFrameError(f"Invalid quaternion: {quat_xyzw}")

    x /= norm
    y /= norm
    z /= norm
    w /= norm

    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), 0.0],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), 0.0],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def logged_pose_to_matrix(position: list[float], orientation_xyzw: list[float]) -> list[list[float]]:
    # Turn one logged link pose into a 4x4 transform that can be chained with
    # the model pose from the extracted dynamic manifest.
    matrix = quaternion_to_matrix(orientation_xyzw)
    matrix[0][3] = position[0]
    matrix[1][3] = position[1]
    matrix[2][3] = position[2]
    return matrix


def matmul4(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4)]
        for row in range(4)
    ]


def extract_quoted_value(line: str, label: str) -> str:
    first = line.find('"')
    last = line.rfind('"')
    if first < 0 or last <= first:
        raise DynamicFrameError(f"Malformed quoted {label}: {line}")
    return line[first + 1:last]


def iter_pose_blocks(path: Path):
    # Parse the Gazebo pose log as a sequence of complete pose blocks. The later
    # frame builder relies on sample index, not timestamp, because timestamps can repeat.
    if not path.exists():
        raise DynamicFrameError(f"Missing pose log: {path}")

    in_pose = False
    stack: list[str] = []
    current_data: dict[str, str] | None = None

    sec = 0
    nsec = 0
    saw_stamp = False
    name: str | None = None
    header_data: dict[str, str] = {}
    position = {"x": 0.0, "y": 0.0, "z": 0.0}
    orientation = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0}

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue

            if line == "pose {":
                if in_pose:
                    raise DynamicFrameError(f"Nested pose block in {path}:{line_number}")
                in_pose = True
                stack = ["pose"]
                current_data = None
                sec = 0
                nsec = 0
                saw_stamp = False
                name = None
                header_data = {}
                position = {"x": 0.0, "y": 0.0, "z": 0.0}
                orientation = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0}
                continue

            if not in_pose:
                raise DynamicFrameError(f"Unexpected content outside pose block in {path}:{line_number}")

            if line.endswith("{"):
                section = line[:-1].strip()
                stack.append(section)
                if section == "stamp":
                    saw_stamp = True
                if section == "data":
                    current_data = {}
                continue

            if line == "}":
                if not stack:
                    raise DynamicFrameError(f"Unbalanced closing brace in {path}:{line_number}")
                section = stack.pop()
                if section == "data":
                    if current_data is None or "key" not in current_data or "value" not in current_data:
                        raise DynamicFrameError(f"Malformed header data block in {path}:{line_number}")
                    header_data[current_data["key"]] = current_data["value"]
                    current_data = None
                elif section == "pose":
                    if not saw_stamp:
                        raise DynamicFrameError(f"Pose block missing stamp in {path}:{line_number}")
                    if name is None:
                        raise DynamicFrameError(f"Pose block missing name in {path}:{line_number}")
                    yield {
                        "timestamp": {"sec": sec, "nsec": nsec, "seconds": sec + nsec / 1_000_000_000.0},
                        "header_data": header_data,
                        "name": name,
                        "position": [position["x"], position["y"], position["z"]],
                        "orientation_xyzw": [
                            orientation["x"],
                            orientation["y"],
                            orientation["z"],
                            orientation["w"],
                        ],
                    }
                    in_pose = False
                    stack = []
                continue

            section = stack[-1] if stack else ""

            if section == "stamp":
                if line.startswith("sec: "):
                    sec = int(line.split(": ", 1)[1])
                elif line.startswith("nsec: "):
                    nsec = int(line.split(": ", 1)[1])
                continue

            if section == "data":
                if current_data is None:
                    raise DynamicFrameError(f"Header data state error in {path}:{line_number}")
                if line.startswith("key: "):
                    current_data["key"] = extract_quoted_value(line, "key")
                elif line.startswith("value: "):
                    current_data["value"] = extract_quoted_value(line, "value")
                continue

            if section == "position" and ": " in line:
                key, raw_value = line.split(": ", 1)
                if key not in position:
                    raise DynamicFrameError(f"Unexpected position field {key!r} in {path}:{line_number}")
                position[key] = float(raw_value)
                continue

            if section == "orientation" and ": " in line:
                key, raw_value = line.split(": ", 1)
                if key not in orientation:
                    raise DynamicFrameError(f"Unexpected orientation field {key!r} in {path}:{line_number}")
                orientation[key] = float(raw_value)
                continue

            if section == "pose" and line.startswith("name: "):
                name = extract_quoted_value(line, "name")

    if in_pose:
        raise DynamicFrameError(f"Unclosed pose block in {path}")


def load_dynamic_models() -> dict[str, dict[str, Any]]:
    # Read the extracted dynamic manifest to recover the validated link order,
    # model pose, and which links actually carry visuals for Panda and UR5.
    manifest = load_json(DYNAMIC_MANIFEST_PATH)
    if not isinstance(manifest, list):
        raise DynamicFrameError("dynamic_manifest.json must contain a list")

    expected_models = set(MODEL_ORDER)
    found_models = {entry.get("model") for entry in manifest if isinstance(entry, dict)}
    unexpected = sorted(str(name) for name in found_models - expected_models)
    missing = sorted(expected_models - found_models)
    if unexpected:
        raise DynamicFrameError(f"Unexpected dynamic model(s): {', '.join(unexpected)}")
    if missing:
        raise DynamicFrameError(f"Missing dynamic model(s): {', '.join(missing)}")

    models: dict[str, dict[str, Any]] = {}
    for entry in manifest:
        model_name = entry["model"]
        model_pose = parse_pose6(entry.get("model_pose"), f"{model_name}.model_pose")
        links_raw = entry.get("links")
        if not isinstance(links_raw, list):
            raise DynamicFrameError(f"{model_name}.links must be a list")

        link_order: list[str] = []
        has_visuals: dict[str, bool] = {}
        for link_entry in links_raw:
            if not isinstance(link_entry, dict):
                raise DynamicFrameError(f"{model_name}.links contains a non-object")
            link_name = link_entry.get("link")
            visuals = link_entry.get("visuals")
            if not isinstance(link_name, str) or not link_name:
                raise DynamicFrameError(f"{model_name} has a link with missing name")
            if link_name in has_visuals:
                raise DynamicFrameError(f"{model_name} has duplicate manifest link {link_name!r}")
            if not isinstance(visuals, list):
                raise DynamicFrameError(f"{model_name}.{link_name}.visuals must be a list")
            link_order.append(link_name)
            has_visuals[link_name] = bool(visuals)

        expected_count = MODEL_CONFIG[model_name]["expected_links"]
        if len(link_order) != expected_count:
            raise DynamicFrameError(
                f"{model_name} manifest has {len(link_order)} links, expected {expected_count}"
            )

        models[model_name] = {
            "model_pose": model_pose,
            "model_matrix": pose6_to_matrix(model_pose),
            "link_order": link_order,
            "link_set": set(link_order),
            "has_visuals": has_visuals,
        }

    return models


def split_scoped_name(model_name: str, sample_index: int, source_name: str) -> str:
    if source_name.count("::") != 1:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: malformed scoped pose name {source_name!r}"
        )

    scoped_model, link_name = source_name.split("::", 1)
    if scoped_model != model_name:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: pose {source_name!r} has model {scoped_model!r}"
        )
    if not link_name:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: pose {source_name!r} has an empty link name"
        )

    return link_name


def timestamp_key(timestamp: dict[str, Any]) -> tuple[int, int]:
    return int(timestamp["sec"]), int(timestamp["nsec"])


def validate_pose_for_sample(
    model_name: str,
    sample_index: int,
    pose: dict[str, Any],
    model_info: dict[str, Any],
    current_sample: dict[str, dict[str, Any]],
    current_timestamp: tuple[int, int] | None,
) -> tuple[str, tuple[int, int]]:
    # Enforce the assumption that one logical sample contains exactly one pose
    # per expected link, all stamped with the same timestamp inside that sample.
    expected_links = model_info["link_set"]

    source_name = pose["name"]
    link_name = split_scoped_name(model_name, sample_index, source_name)

    header_data = pose["header_data"]
    if header_data.get("frame_id") != model_name:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: frame_id mismatch for {source_name!r}"
        )
    if header_data.get("child_frame_id") != source_name:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: child_frame_id mismatch for {source_name!r}"
        )

    if link_name not in expected_links:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: unexpected link {link_name!r}"
        )
    if link_name in current_sample:
        missing = sorted(expected_links - set(current_sample))
        missing_text = ", ".join(missing) if missing else "<none>"
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: duplicate link {link_name!r}; "
            f"sample was still missing: {missing_text}"
        )

    pose_timestamp = timestamp_key(pose["timestamp"])
    if current_timestamp is not None and pose_timestamp != current_timestamp:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: timestamp mismatch inside sample; "
            f"expected {current_timestamp}, got {pose_timestamp} for {source_name!r}"
        )

    quaternion_to_matrix(pose["orientation_xyzw"])
    return link_name, pose_timestamp


def finalize_completed_sample(
    model_name: str,
    sample_index: int,
    sample: dict[str, dict[str, Any]],
    model_info: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    missing = sorted(model_info["link_set"] - set(sample))
    if missing:
        raise DynamicFrameError(
            f"{model_name} sample {sample_index}: missing link(s): {', '.join(missing)}"
        )
    return dict(sample)


def read_selected_samples(
    model_name: str,
    model_info: dict[str, Any],
    selected_indices: list[int],
) -> tuple[dict[int, dict[str, dict[str, Any]]], dict[str, Any]]:
    # Walk the whole pose log sample by sample so requested source sample indices
    # can be recovered exactly, even when timestamps are duplicated.
    log_path = MODEL_CONFIG[model_name]["log_path"]
    selected = set(selected_indices)

    found: dict[int, dict[str, dict[str, Any]]] = {}
    sample: dict[str, dict[str, Any]] = {}
    sample_timestamp: tuple[int, int] | None = None
    sample_index = 0

    for pose in iter_pose_blocks(log_path):
        # Accumulate poses until one complete sample has every expected link.
        link_name, pose_timestamp = validate_pose_for_sample(
            model_name,
            sample_index,
            pose,
            model_info,
            sample,
            sample_timestamp,
        )
        if sample_timestamp is None:
            sample_timestamp = pose_timestamp
        sample[link_name] = pose

        if set(sample) != model_info["link_set"]:
            continue

        completed_sample = finalize_completed_sample(model_name, sample_index, sample, model_info)
        if sample_index in selected:
            found[sample_index] = completed_sample
        sample_index += 1
        sample = {}
        sample_timestamp = None

    if sample:
        missing = sorted(model_info["link_set"] - set(sample))
        raise DynamicFrameError(
            f"{model_name} log ended with incomplete sample {sample_index}: "
            f"{len(sample)} pose(s), missing: {', '.join(missing)}"
        )

    missing_samples = sorted(selected - set(found))
    if missing_samples:
        raise DynamicFrameError(
            f"{model_name} log missing selected sample(s): {', '.join(map(str, missing_samples))}"
        )

    summary = {
        "samples_validated": sample_index,
        "per_sample_timestamps_consistent": True,
    }
    return found, summary


def build_link_record(
    model_info: dict[str, Any],
    link_name: str,
    pose: dict[str, Any],
) -> dict[str, Any]:
    # The validated transform chain for rigid robot geometry starts from the
    # model pose in the world file and then applies the logged link pose.
    link_matrix = logged_pose_to_matrix(pose["position"], pose["orientation_xyzw"])
    to_world = matmul4(model_info["model_matrix"], link_matrix)

    return {
        "source_name": pose["name"],
        "has_visuals": model_info["has_visuals"][link_name],
        "link_pose_local_to_model": {
            "position": pose["position"],
            "orientation_xyzw": pose["orientation_xyzw"],
        },
        "to_world": to_world,
    }


def build_frames(
    frame_records: list[dict[str, int]],
    dynamic_models: dict[str, dict[str, Any]],
    selected_samples: dict[str, dict[int, dict[str, dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]], dict[str, bool]]:
    # Convert the selected source samples into compact frame records. The source
    # sample index is preserved because it is the reliable frame identity.
    frames: list[dict[str, Any]] = []
    link_counts: dict[str, dict[str, int]] = {}
    cross_robot_timestamps_matched: dict[str, bool] = {}

    for frame_record in frame_records:
        frame_id = frame_record["frame_id"]
        sample_index = frame_record["source_sample_index"]
        # Cross-check that Panda and UR5 were sampled from the same logical
        # instant before packaging them into one frame record.
        reference_timestamps = {
            model_name: selected_samples[model_name][sample_index][
                dynamic_models[model_name]["link_order"][0]
            ]["timestamp"]
            for model_name in MODEL_ORDER
        }
        first_model = MODEL_ORDER[0]
        frame_timestamp = reference_timestamps[first_model]
        timestamps_match = all(
            timestamp_key(timestamp) == timestamp_key(frame_timestamp)
            for timestamp in reference_timestamps.values()
        )
        cross_robot_timestamps_matched[str(sample_index)] = timestamps_match
        if not timestamps_match:
            raise DynamicFrameError(
                f"Timestamp mismatch at sample {sample_index}: "
                + ", ".join(
                    f"{model_name}={reference_timestamps[model_name]}"
                    for model_name in MODEL_ORDER
                )
            )

        frame_models: dict[str, Any] = {}
        frame_counts: dict[str, int] = {}
        for model_name in MODEL_ORDER:
            # Preserve the validated manifest link order so later visual export
            # stages can join logged link poses back to the correct visuals.
            model_info = dynamic_models[model_name]
            sample = selected_samples[model_name][sample_index]
            links = {
                link_name: build_link_record(model_info, link_name, sample[link_name])
                for link_name in model_info["link_order"]
            }
            frame_models[model_name] = {
                "model_to_world_pose6": model_info["model_pose"],
                "links": links,
            }
            frame_counts[model_name] = len(links)

        frames.append(
            {
                "frame_id": frame_id,
                "source_sample_index": sample_index,
                "timestamp": frame_timestamp,
                "models": frame_models,
            }
        )
        link_counts[str(sample_index)] = frame_counts

    return frames, link_counts, cross_robot_timestamps_matched


def write_output(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    warnings: list[str] = []
    # Resolve the requested frame list first so every later stage works from the
    # same ordered source sample indices.
    frame_records = load_selected_frames(args.frames_json)
    source_sample_indices = [frame["source_sample_index"] for frame in frame_records]
    output_path = args.output.expanduser().resolve()
    dynamic_models = load_dynamic_models()

    selected_samples: dict[str, dict[int, dict[str, dict[str, Any]]]] = {}
    sample_validation: dict[str, dict[str, Any]] = {}
    for model_name in MODEL_ORDER:
        # Recover the requested samples independently from each robot's pose log
        # before checking they align into shared dynamic frames.
        model_samples, model_validation = read_selected_samples(
            model_name,
            dynamic_models[model_name],
            source_sample_indices,
        )
        selected_samples[model_name] = model_samples
        sample_validation[model_name] = model_validation

    frames, link_counts, cross_robot_timestamps_matched = build_frames(
        frame_records,
        dynamic_models,
        selected_samples,
    )
    # Write one normalized JSON artifact that downstream scripts can trust
    # instead of re-parsing raw Gazebo pose logs.
    output = {
        "generated_by": Path(__file__).name,
        "source_sample_indices": source_sample_indices,
        "frames": frames,
        "validation": {
            "selected_frames_found": len(frames),
            "link_counts": link_counts,
            "samples_validated": {
                model_name: sample_validation[model_name]["samples_validated"]
                for model_name in MODEL_ORDER
            },
            "per_sample_timestamps_consistent": {
                model_name: sample_validation[model_name]["per_sample_timestamps_consistent"]
                for model_name in MODEL_ORDER
            },
            "cross_robot_timestamps_matched": cross_robot_timestamps_matched,
            "warnings": warnings,
        },
    }
    write_output(output_path, output)

    print("Dynamic prototype frame extraction")
    print(f"frames: {len(frames)}")
    print(
        f"first: frame_id={frames[0]['frame_id']}, source_sample={frames[0]['source_sample_index']}"
    )
    print(
        f"last: frame_id={frames[-1]['frame_id']}, source_sample={frames[-1]['source_sample_index']}"
    )
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DynamicFrameError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
