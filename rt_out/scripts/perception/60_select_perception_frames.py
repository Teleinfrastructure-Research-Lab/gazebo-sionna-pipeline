#!/usr/bin/env python3
"""Select a small perception frame subset from a validated RT experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path(
    "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
)


class SelectionError(RuntimeError):
    """Raised when perception frame selection cannot proceed safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select experiment-local frames for the minimal perception+RT pilot.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Perception dataset config JSON path.",
    )
    parser.add_argument(
        "--source-frames",
        type=Path,
        default=None,
        help="Optional override for the source sampled_frames JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional override for selected_frames.json output path.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optional override for selected_frames_summary.json output path.",
    )
    parser.add_argument(
        "--frame-count",
        type=int,
        default=None,
        help="Optional override for the number of selected frames.",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=None,
        help="Optional override for every-nth selection stride.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise SelectionError(f"Required JSON file does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise SelectionError(f"Failed to parse JSON from {path}: {exc}") from exc


def normalize_frames(payload: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        frames = payload
    elif isinstance(payload, dict):
        if "frames" in payload:
            frames = payload["frames"]
        elif "sampled_frames" in payload:
            frames = payload["sampled_frames"]
        else:
            raise SelectionError(
                f"Unsupported frame JSON shape in {path}: expected a list, "
                "'frames', or 'sampled_frames'."
            )
    else:
        raise SelectionError(
            f"Unsupported frame JSON root type in {path}: {type(payload).__name__}"
        )

    if not isinstance(frames, list):
        raise SelectionError(f"Frame collection in {path} is not a list.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(frames):
        if not isinstance(item, dict):
            raise SelectionError(
                f"Frame record {index} in {path} is not an object/dict."
            )
        normalized.append(item)
    return normalized


def coerce_source_sample_index(record: dict[str, Any], record_index: int) -> int:
    candidate_keys = ("source_sample_index", "source_sample", "sample_index", "source_index")
    for key in candidate_keys:
        if key in record:
            value = record[key]
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise SelectionError(
                    f"Frame record {record_index} has non-integer {key}={value!r}."
                ) from exc
    raise SelectionError(
        f"Frame record {record_index} does not contain any of "
        f"{candidate_keys}."
    )


def resolve_source_frames_path(config: dict[str, Any], explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    source_experiment = config.get("source_experiment")
    if not isinstance(source_experiment, str) or not source_experiment.strip():
        raise SelectionError("Config is missing a valid 'source_experiment' string.")
    return Path(source_experiment) / "frames" / "sampled_frames.json"


def resolve_output_paths(
    config_path: Path,
    explicit_output: Path | None,
    explicit_summary_output: Path | None,
) -> tuple[Path, Path]:
    output_root = config_path.parent.parent
    output = explicit_output or (output_root / "frames" / "selected_frames.json")
    summary = explicit_summary_output or (
        output_root / "frames" / "selected_frames_summary.json"
    )
    return output, summary


def select_every_nth(
    frames: list[dict[str, Any]],
    frame_count: int,
    stride: int,
) -> list[tuple[int, dict[str, Any]]]:
    if frame_count <= 0:
        raise SelectionError(f"frame_count must be positive, got {frame_count}.")
    if stride <= 0:
        raise SelectionError(f"stride must be positive, got {stride}.")

    selected: list[tuple[int, dict[str, Any]]] = []
    for record_index in range(0, len(frames), stride):
        selected.append((record_index, frames[record_index]))
        if len(selected) == frame_count:
            break

    if len(selected) != frame_count:
        raise SelectionError(
            f"Could not select {frame_count} frames from {len(frames)} source records "
            f"using stride {stride}; selected only {len(selected)}."
        )
    return selected


def build_selected_records(
    selected_pairs: list[tuple[int, dict[str, Any]]],
    source_experiment: str,
) -> list[dict[str, Any]]:
    selected_frames: list[dict[str, Any]] = []
    seen_record_indices: set[int] = set()

    for perception_frame_id, (record_index, source_record) in enumerate(selected_pairs):
        if record_index in seen_record_indices:
            raise SelectionError(f"Duplicate source_record_index selected: {record_index}")
        seen_record_indices.add(record_index)

        source_frame_id = source_record.get("frame_id")
        if source_frame_id is None:
            source_frame_id = record_index

        selected_frames.append(
            {
                "perception_frame_id": perception_frame_id,
                "source_experiment": source_experiment,
                "source_frame_id": source_frame_id,
                "source_sample_index": coerce_source_sample_index(source_record, record_index),
                "source_record_index": record_index,
                "source_record": source_record,
            }
        )

    perception_ids = [item["perception_frame_id"] for item in selected_frames]
    if len(perception_ids) != len(set(perception_ids)):
        raise SelectionError("Duplicate perception_frame_id values were generated.")

    return selected_frames


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    config_path = args.config
    config = load_json(config_path)
    if not isinstance(config, dict):
        raise SelectionError(f"Config root must be an object/dict: {config_path}")

    experiment_name = config.get("experiment_name")
    source_experiment = config.get("source_experiment")
    strategy = config.get("selected_frames_strategy")

    if strategy != "every_nth_from_source":
        raise SelectionError(
            f"Unsupported selected_frames_strategy={strategy!r}; "
            "expected 'every_nth_from_source'."
        )
    if not isinstance(experiment_name, str) or not experiment_name.strip():
        raise SelectionError("Config is missing a valid 'experiment_name'.")
    if not isinstance(source_experiment, str) or not source_experiment.strip():
        raise SelectionError("Config is missing a valid 'source_experiment'.")

    frame_count = int(args.frame_count if args.frame_count is not None else config.get("frame_count"))
    stride = int(
        args.stride if args.stride is not None else config.get("selected_frames_stride")
    )

    source_frames_path = resolve_source_frames_path(config, args.source_frames)
    output_path, summary_output_path = resolve_output_paths(
        config_path,
        args.output,
        args.summary_output,
    )

    source_payload = load_json(source_frames_path)
    source_frames = normalize_frames(source_payload, source_frames_path)
    selected_pairs = select_every_nth(source_frames, frame_count=frame_count, stride=stride)
    selected_frames = build_selected_records(selected_pairs, source_experiment=source_experiment)

    selected_payload = {
        "experiment_name": experiment_name,
        "source_experiment": source_experiment,
        "selection_strategy": strategy,
        "selected_count": len(selected_frames),
        "selected_frames": selected_frames,
    }

    summary_payload = {
        "selected_count": len(selected_frames),
        "source_count": len(source_frames),
        "stride": stride,
        "first_selected_source_record_index": selected_frames[0]["source_record_index"],
        "last_selected_source_record_index": selected_frames[-1]["source_record_index"],
        "expected_perception_samples": config.get("expected_perception_samples"),
        "expected_rt_rows": config.get("expected_rt_rows"),
        "expected_label_rows": config.get("expected_label_rows"),
    }

    write_json(output_path, selected_payload)
    write_json(summary_output_path, summary_payload)

    print(
        f"experiment_name={experiment_name}\n"
        f"source_experiment={source_experiment}\n"
        f"source_frames_path={source_frames_path}\n"
        f"selected_count={len(selected_frames)}\n"
        f"source_count={len(source_frames)}\n"
        f"stride={stride}\n"
        f"first_source_record_index={selected_frames[0]['source_record_index']}\n"
        f"last_source_record_index={selected_frames[-1]['source_record_index']}\n"
        f"output_json={output_path}\n"
        f"summary_json={summary_output_path}"
    )


if __name__ == "__main__":
    main()
