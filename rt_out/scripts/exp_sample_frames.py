#!/usr/bin/env python3

"""Sample uniformly spaced source-frame indices for an experiment branch.

Rather than hardcoding the prototype's three samples, this helper inspects the
available Panda and UR5 pose logs, finds the common valid sample range, and
builds a monotonic frame list for larger experiments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_MANIFEST_PATH = PROJECT_ROOT / "rt_out" / "manifests" / "dynamic_manifest.json"


class ExperimentFrameSamplingError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ExperimentFrameSamplingError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentFrameSamplingError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentFrameSamplingError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentFrameSamplingError(f"{label} must be a non-empty string")
    return value.strip()


def require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExperimentFrameSamplingError(f"{label} must be a non-negative integer")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Uniformly sample source frame indices for a semantic ablation experiment."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to experiment_config.json",
    )
    return parser.parse_args()


def load_experiment_config(config_path: Path) -> dict[str, Any]:
    # Only the subset of experiment settings relevant to frame sampling is
    # loaded here: experiment name, frame count, dynamic models, and output root.
    data = require_object(load_json(config_path), "experiment_config.json")

    experiment_name = require_non_empty_string(
        data.get("experiment_name"), "experiment_config.experiment_name"
    )
    num_frames = require_non_negative_int(data.get("num_frames"), "experiment_config.num_frames")
    if num_frames < 2:
        raise ExperimentFrameSamplingError("experiment_config.num_frames must be >= 2")

    raw_models = data.get("dynamic_models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ExperimentFrameSamplingError("experiment_config.dynamic_models must be a non-empty list")
    dynamic_models = [
        require_non_empty_string(item, f"experiment_config.dynamic_models[{index}]")
        for index, item in enumerate(raw_models)
    ]
    if len(set(dynamic_models)) != len(dynamic_models):
        raise ExperimentFrameSamplingError("experiment_config.dynamic_models contains duplicates")

    output_dir = require_non_empty_string(data.get("output_dir"), "experiment_config.output_dir")
    output_root = Path(output_dir).expanduser()
    if not output_root.is_absolute():
        output_root = (PROJECT_ROOT / output_root).resolve()
    else:
        output_root = output_root.resolve()

    return {
        "config_path": config_path.resolve(),
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "dynamic_models": dynamic_models,
        "output_dir": output_dir,
        "output_root": output_root,
    }


def extract_quoted_value(line: str, label: str) -> str:
    first = line.find('"')
    last = line.rfind('"')
    if first < 0 or last <= first:
        raise ExperimentFrameSamplingError(f"Malformed quoted {label}: {line}")
    return line[first + 1:last]


def iter_pose_blocks(path: Path):
    # Reuse the same pose-block parsing logic as the validated rigid prototype so
    # source sample indices mean exactly the same thing here as they do in script 30.
    if not path.exists():
        raise ExperimentFrameSamplingError(f"Missing pose log: {path}")

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
                    raise ExperimentFrameSamplingError(
                        f"Nested pose block in {path}:{line_number}"
                    )
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
                raise ExperimentFrameSamplingError(
                    f"Unexpected content outside pose block in {path}:{line_number}"
                )

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
                    raise ExperimentFrameSamplingError(
                        f"Unbalanced closing brace in {path}:{line_number}"
                    )
                section = stack.pop()
                if section == "data":
                    if current_data is None or "key" not in current_data or "value" not in current_data:
                        raise ExperimentFrameSamplingError(
                            f"Malformed header data block in {path}:{line_number}"
                        )
                    header_data[current_data["key"]] = current_data["value"]
                    current_data = None
                elif section == "pose":
                    if not saw_stamp:
                        raise ExperimentFrameSamplingError(
                            f"Pose block missing stamp in {path}:{line_number}"
                        )
                    if name is None:
                        raise ExperimentFrameSamplingError(
                            f"Pose block missing name in {path}:{line_number}"
                        )
                    yield {
                        "timestamp": {"sec": sec, "nsec": nsec},
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
                    raise ExperimentFrameSamplingError(
                        f"Header data state error in {path}:{line_number}"
                    )
                if line.startswith("key: "):
                    current_data["key"] = extract_quoted_value(line, "key")
                elif line.startswith("value: "):
                    current_data["value"] = extract_quoted_value(line, "value")
                continue

            if section == "position" and ": " in line:
                key, raw_value = line.split(": ", 1)
                if key not in position:
                    raise ExperimentFrameSamplingError(
                        f"Unexpected position field {key!r} in {path}:{line_number}"
                    )
                position[key] = float(raw_value)
                continue

            if section == "orientation" and ": " in line:
                key, raw_value = line.split(": ", 1)
                if key not in orientation:
                    raise ExperimentFrameSamplingError(
                        f"Unexpected orientation field {key!r} in {path}:{line_number}"
                    )
                orientation[key] = float(raw_value)
                continue

            if section == "pose" and line.startswith("name: "):
                name = extract_quoted_value(line, "name")

    if in_pose:
        raise ExperimentFrameSamplingError(f"Unclosed pose block in {path}")


def load_dynamic_manifest_models(prototype_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # Read the validated dynamic manifest to confirm the requested experiment
    # models are still the supported rigid Panda/UR5 entries.
    manifest = load_json(DYNAMIC_MANIFEST_PATH)
    if not isinstance(manifest, list):
        raise ExperimentFrameSamplingError("dynamic_manifest.json must contain a list")

    models_from_manifest: dict[str, dict[str, Any]] = {}
    for entry in manifest:
        if not isinstance(entry, dict):
            raise ExperimentFrameSamplingError("dynamic_manifest.json entries must be objects")
        model_name = require_non_empty_string(entry.get("model"), "dynamic_manifest model name")
        if model_name in models_from_manifest:
            raise ExperimentFrameSamplingError(f"Duplicate dynamic manifest model: {model_name}")

        links_raw = entry.get("links")
        if not isinstance(links_raw, list):
            raise ExperimentFrameSamplingError(f"{model_name}.links must be a list")

        link_order: list[str] = []
        for link_entry in links_raw:
            if not isinstance(link_entry, dict):
                raise ExperimentFrameSamplingError(f"{model_name}.links contains a non-object")
            link_name = require_non_empty_string(
                link_entry.get("link"), f"{model_name}.links[].link"
            )
            if link_name in link_order:
                raise ExperimentFrameSamplingError(
                    f"{model_name} has duplicate manifest link {link_name!r}"
                )
            link_order.append(link_name)

        expected_count = prototype_config["dynamic_models"][model_name]["expected_link_count"]
        if len(link_order) != expected_count:
            raise ExperimentFrameSamplingError(
                f"{model_name} manifest has {len(link_order)} links, expected {expected_count}"
            )

        models_from_manifest[model_name] = {
            "link_order": link_order,
            "link_set": set(link_order),
        }

    return models_from_manifest


def split_scoped_name(model_name: str, sample_index: int, source_name: str) -> str:
    if source_name.count("::") != 1:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: malformed scoped pose name {source_name!r}"
        )

    scoped_model, link_name = source_name.split("::", 1)
    if scoped_model != model_name:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: pose {source_name!r} has model {scoped_model!r}"
        )
    if not link_name:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: pose {source_name!r} has an empty link name"
        )
    return link_name


def validate_pose_for_sample(
    model_name: str,
    sample_index: int,
    pose: dict[str, Any],
    model_info: dict[str, Any],
    current_sample: dict[str, dict[str, Any]],
) -> str:
    source_name = pose["name"]
    link_name = split_scoped_name(model_name, sample_index, source_name)

    header_data = pose["header_data"]
    if header_data.get("frame_id") != model_name:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: frame_id mismatch for {source_name!r}"
        )
    if header_data.get("child_frame_id") != source_name:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: child_frame_id mismatch for {source_name!r}"
        )

    if link_name not in model_info["link_set"]:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: unexpected link {link_name!r}"
        )
    if link_name in current_sample:
        raise ExperimentFrameSamplingError(
            f"{model_name} sample {sample_index}: duplicate link {link_name!r}"
        )
    return link_name


def count_valid_samples(model_name: str, model_info: dict[str, Any], log_path: Path) -> int:
    # Count logical samples by requiring one pose per expected link, rather than
    # trusting timestamps, because Gazebo pose logs can repeat timestamps.
    sample: dict[str, dict[str, Any]] = {}
    sample_index = 0

    for pose in iter_pose_blocks(log_path):
        link_name = validate_pose_for_sample(model_name, sample_index, pose, model_info, sample)
        sample[link_name] = pose

        if set(sample) != model_info["link_set"]:
            continue

        sample_index += 1
        sample = {}

    if sample:
        missing = sorted(model_info["link_set"] - set(sample))
        raise ExperimentFrameSamplingError(
            f"{model_name} log ended with incomplete sample {sample_index}: "
            f"{len(sample)} pose(s), missing: {', '.join(missing)}"
        )

    if sample_index == 0:
        raise ExperimentFrameSamplingError(f"{model_name} pose log contains zero complete samples")
    return sample_index


def round_divide_half_up(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 >= denominator:
        return quotient + 1
    return quotient


def build_uniform_samples(num_frames: int, common_last_sample: int) -> list[dict[str, int]]:
    # Spread the experiment frames uniformly over the full common sample range
    # while pinning the first sample to 0 and the last to the common maximum.
    available_samples = common_last_sample + 1
    if num_frames > available_samples:
        raise ExperimentFrameSamplingError(
            f"num_frames={num_frames} exceeds available common samples={available_samples}"
        )

    frames: list[dict[str, int]] = []
    for frame_id in range(num_frames):
        source_sample = round_divide_half_up(
            frame_id * common_last_sample,
            num_frames - 1,
        )
        frames.append({"frame_id": frame_id, "source_sample": source_sample})
    return frames


def validate_sampled_frames(frames: list[dict[str, int]], num_frames: int, common_last_sample: int) -> None:
    if len(frames) != num_frames:
        raise ExperimentFrameSamplingError(
            f"sampled_frames.json must contain exactly {num_frames} entries, got {len(frames)}"
        )

    frame_ids = [frame["frame_id"] for frame in frames]
    if frame_ids != list(range(num_frames)):
        raise ExperimentFrameSamplingError("frame_id values must run from 0 to num_frames-1")

    source_samples = [frame["source_sample"] for frame in frames]
    if source_samples[0] != 0:
        raise ExperimentFrameSamplingError("First source_sample must be 0")
    if source_samples[-1] != common_last_sample:
        raise ExperimentFrameSamplingError(
            f"Last source_sample must be {common_last_sample}, got {source_samples[-1]}"
        )
    if len(set(source_samples)) != len(source_samples):
        raise ExperimentFrameSamplingError("Sampled source_sample values must not contain duplicates")
    if source_samples != sorted(source_samples):
        raise ExperimentFrameSamplingError("source_sample values must be monotonically increasing")
    if any(sample < 0 or sample > common_last_sample for sample in source_samples):
        raise ExperimentFrameSamplingError("Sampled source_sample values must stay within range")


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    # Load the experiment request, then recover the common available sample
    # range from the validated Panda and UR5 pose logs.
    experiment = load_experiment_config(Path(args.config).expanduser().resolve())
    prototype_config = load_dynamic_prototype_config()
    manifest_models = load_dynamic_manifest_models(prototype_config)

    per_model_sample_counts: dict[str, int] = {}
    for model_name in experiment["dynamic_models"]:
        if model_name not in prototype_config["dynamic_models"]:
            raise ExperimentFrameSamplingError(
                f"Experiment model {model_name!r} is missing from dynamic_prototype_config.json"
            )
        if model_name not in manifest_models:
            raise ExperimentFrameSamplingError(
                f"Experiment model {model_name!r} is missing from dynamic_manifest.json"
            )

        log_path = prototype_config["dynamic_models"][model_name]["pose_log_path"]
        per_model_sample_counts[model_name] = count_valid_samples(
            model_name,
            manifest_models[model_name],
            log_path,
        )

    common_sample_count = min(per_model_sample_counts.values())
    common_last_sample = common_sample_count - 1
    frames = build_uniform_samples(experiment["num_frames"], common_last_sample)
    validate_sampled_frames(frames, experiment["num_frames"], common_last_sample)

    # Write the selected source sample indices as a stable frame list that every
    # later experiment stage can reuse without re-reading the pose logs.
    output_path = experiment["output_root"] / "frames" / "sampled_frames.json"
    payload = {
        "generated_by": Path(__file__).name,
        "config_path": str(experiment["config_path"]),
        "experiment_name": experiment["experiment_name"],
        "dynamic_models": experiment["dynamic_models"],
        "per_model_sample_counts": per_model_sample_counts,
        "common_sample_range": {
            "first_source_sample": 0,
            "last_source_sample": common_last_sample,
            "sample_count": common_sample_count,
        },
        "frames": frames,
    }
    write_output(output_path, payload)

    saved = require_object(load_json(output_path), "sampled_frames.json")
    saved_frames = saved.get("frames")
    if not isinstance(saved_frames, list):
        raise ExperimentFrameSamplingError("sampled_frames.json must contain a frames list")
    validate_sampled_frames(saved_frames, experiment["num_frames"], common_last_sample)

    print(f"num_frames: {experiment['num_frames']}")
    print("first sample: 0")
    print(f"last sample: {common_last_sample}")
    print(f"output path: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExperimentFrameSamplingError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
