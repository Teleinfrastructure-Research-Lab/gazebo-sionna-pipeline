#!/usr/bin/env python3
"""Validate native panoptic segmentation capture outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
PRIMARY_MODE = "panoptic"
REQUIRED_CAPTURE_SUBDIRS = ("labels_maps_rgb", "semantic_decoded", "gazebo_instance_count", "colored_maps", "metadata")
DECODED_MASK_SUFFIXES = (".pgm", ".png")
DEFAULT_ZERO_THRESHOLD = 0.01
DEFAULT_EXPECTED_MESSAGES_PER_CAMERA = 3
REQUIRED_SEMANTIC_LABELS = tuple(range(1, 11))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate native panoptic segmentation capture outputs."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument(
        "--zero-threshold",
        type=float,
        default=DEFAULT_ZERO_THRESHOLD,
        help="Maximum allowed zero-label ratio per semantic-decoded mask. Label 0 is invalid/unlabeled.",
    )
    parser.add_argument(
        "--expected-messages-per-camera",
        type=int,
        default=DEFAULT_EXPECTED_MESSAGES_PER_CAMERA,
        help="Expected decoded panoptic message count per camera.",
    )
    parser.add_argument(
        "--write-diagnostics",
        action="store_true",
        help="Also write supplementary histogram and invalid-pixel CSV diagnostics.",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        fail(f"Missing {label}: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        fail(f"Failed to parse {label} JSON at {path}: {exc}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def project_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_camera_ids(config: dict[str, Any]) -> list[str]:
    camera_ids = config.get("camera_ids")
    if not isinstance(camera_ids, list) or not camera_ids or not all(isinstance(item, str) and item.strip() for item in camera_ids):
        fail("Config field 'camera_ids' must be a non-empty list of camera IDs.")
    return camera_ids


def load_expected_camera_count(config: dict[str, Any], camera_ids: list[str]) -> int:
    expected = config.get("expected_camera_count")
    if expected is None:
        return len(camera_ids)
    if not isinstance(expected, int) or expected <= 0:
        fail("Config field 'expected_camera_count' must be a positive integer when present.")
    return expected


def load_semantic_label_map(path: Path) -> dict[int, str]:
    payload = load_json(path, "semantic label map")
    if not isinstance(payload, dict):
        fail(f"Semantic label map at {path} must be a JSON object.")
    try:
        semantic_map = {int(key): str(value) for key, value in payload.items()}
    except (TypeError, ValueError) as exc:
        fail(f"Semantic label map at {path} contains non-integer IDs: {exc}")
    if sorted(semantic_map) != list(REQUIRED_SEMANTIC_LABELS):
        fail(
            f"Semantic label map at {path} must contain exactly labels {list(REQUIRED_SEMANTIC_LABELS)}. "
            f"Found: {sorted(semantic_map)}"
        )
    return semantic_map


def try_import_pillow():
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    return Image


def next_pgm_token(data: bytes, index: int) -> tuple[str, int]:
    size = len(data)
    while index < size:
        value = data[index]
        if value == 35:
            while index < size and data[index] not in (10, 13):
                index += 1
            continue
        if chr(value).isspace():
            index += 1
            continue
        break
    start = index
    while index < size and not chr(data[index]).isspace() and data[index] != 35:
        index += 1
    if start == index:
        raise ValueError("Unexpected end of PGM header.")
    return data[start:index].decode("ascii"), index


def read_pgm_mask(path: Path) -> tuple[int, int, list[int]]:
    data = path.read_bytes()
    magic, index = next_pgm_token(data, 0)
    width_token, index = next_pgm_token(data, index)
    height_token, index = next_pgm_token(data, index)
    maxval_token, index = next_pgm_token(data, index)
    width = int(width_token)
    height = int(height_token)
    max_value = int(maxval_token)
    pixel_count = width * height

    if magic == "P2":
        pixels: list[int] = []
        while len(pixels) < pixel_count:
            token, index = next_pgm_token(data, index)
            pixels.append(int(token))
        return width, height, pixels

    if magic != "P5":
        raise ValueError(f"Unsupported PGM magic {magic!r} in {path}.")
    if index >= len(data) or not chr(data[index]).isspace():
        raise ValueError(f"PGM header in {path} is missing the binary data separator.")
    if data[index] == 13 and index + 1 < len(data) and data[index + 1] == 10:
        payload_start = index + 2
    else:
        payload_start = index + 1

    if max_value <= 255:
        payload = data[payload_start:payload_start + pixel_count]
        if len(payload) != pixel_count:
            raise ValueError(f"Expected {pixel_count} bytes in {path}, found {len(payload)}.")
        return width, height, list(payload)

    expected_bytes = pixel_count * 2
    payload = data[payload_start:payload_start + expected_bytes]
    if len(payload) != expected_bytes:
        raise ValueError(f"Expected {expected_bytes} bytes in {path}, found {len(payload)}.")
    pixels = [(payload[offset] << 8) | payload[offset + 1] for offset in range(0, expected_bytes, 2)]
    return width, height, pixels


def read_mask_pixels(path: Path, pillow_image: Any) -> tuple[int, int, list[int]]:
    if path.suffix.lower() == ".pgm":
        return read_pgm_mask(path)
    if pillow_image is None:
        raise ValueError(f"Unsupported decoded mask format {path.suffix!r} for {path}; install Pillow or use .pgm masks.")
    image = pillow_image.open(path)
    try:
        width, height = image.size
        if image.mode in {"I;16", "I;16B", "I;16L", "I"}:
            return width, height, [int(value) for value in image.getdata()]
        grayscale = image.convert("L")
        return width, height, list(grayscale.tobytes())
    finally:
        image.close()


def count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return len([path for path in directory.iterdir() if path.is_file()])


def numeric_stem(path: Path) -> str:
    digits = "".join(character for character in path.stem if character.isdigit())
    if digits:
        return f"{int(digits):06d}"
    return path.stem


def list_mask_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in DECODED_MASK_SUFFIXES)


def build_mask_lookup(paths: list[Path]) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    for path in paths:
        lookup[numeric_stem(path)] = path
    return lookup


def count_message_files(directory: Path, suffixes: tuple[str, ...]) -> int:
    if not directory.is_dir():
        return 0
    return len(
        {
            numeric_stem(path)
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        }
    )


def build_histogram_rows(
    camera_id: str,
    semantic_path: Path,
    width: int,
    height: int,
    histogram: Counter[int],
    semantic_map: dict[int, str],
) -> list[dict[str, Any]]:
    total_pixels = width * height
    rows: list[dict[str, Any]] = []
    for label, pixel_count in sorted(histogram.items()):
        is_zero = label == 0
        is_allowed = label in semantic_map
        rows.append(
            {
                "mode": PRIMARY_MODE,
                "camera_id": camera_id,
                "mask_path": project_rel(semantic_path),
                "width": width,
                "height": height,
                "label": label,
                "pixel_count": pixel_count,
                "pixel_ratio": f"{(pixel_count / total_pixels) if total_pixels else 0.0:.8f}",
                "is_zero_label": str(is_zero).lower(),
                "is_allowed_label": str(is_allowed).lower(),
                "is_invalid_label": str(not is_allowed).lower(),
                "label_name": semantic_map.get(label, "unlabeled" if is_zero else ""),
                "semantic_name": semantic_map.get(label, ""),
            }
        )
    return rows


def build_invalid_rows(
    camera_id: str,
    semantic_path: Path,
    width: int,
    height: int,
    histogram: Counter[int],
    semantic_map: dict[int, str],
) -> list[dict[str, Any]]:
    total_pixels = width * height
    rows: list[dict[str, Any]] = []
    for label, pixel_count in sorted(histogram.items()):
        if label in semantic_map:
            continue
        rows.append(
            {
                "mode": PRIMARY_MODE,
                "camera_id": camera_id,
                "mask_path": project_rel(semantic_path),
                "width": width,
                "height": height,
                "invalid_label": label,
                "pixel_count": pixel_count,
                "pixel_ratio": f"{(pixel_count / total_pixels) if total_pixels else 0.0:.8f}",
                "reason": "zero_label_unlabeled" if label == 0 else "label_not_in_allowed_set",
            }
        )
    return rows


def validate_paired_masks(
    camera_id: str,
    message_index: str,
    semantic_path: Path,
    count_path: Path,
    semantic_map: dict[int, str],
    zero_threshold: float,
    pillow_image: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    semantic_width, semantic_height, semantic_pixels = read_mask_pixels(semantic_path, pillow_image)
    count_width, count_height, count_pixels = read_mask_pixels(count_path, pillow_image)
    if semantic_width != count_width or semantic_height != count_height:
        raise ValueError(
            f"semantic/count shape mismatch for {camera_id}/{message_index}: "
            f"semantic={semantic_width}x{semantic_height}, gazebo_instance_count={count_width}x{count_height}"
        )

    semantic_histogram = Counter(int(value) for value in semantic_pixels)
    zero_label_pixel_count = int(semantic_histogram.get(0, 0))
    total_pixels = semantic_width * semantic_height
    zero_label_ratio = (zero_label_pixel_count / total_pixels) if total_pixels else 0.0
    unexpected_labels = sorted(label for label in semantic_histogram if label not in semantic_map and label != 0)
    invalid_nonzero_pixel_count = sum(semantic_histogram[label] for label in unexpected_labels)
    unique_gazebo_instance_count_values = sorted({int(value) for value in count_pixels})

    mask_summary = {
        "message_index": message_index,
        "semantic_path": project_rel(semantic_path),
        "gazebo_instance_count_path": project_rel(count_path),
        "width": semantic_width,
        "height": semantic_height,
        "pixel_count": total_pixels,
        "unique_semantic_label_count": len(semantic_histogram),
        "min_semantic_label": min(semantic_histogram) if semantic_histogram else None,
        "max_semantic_label": max(semantic_histogram) if semantic_histogram else None,
        "zero_label_pixel_count": zero_label_pixel_count,
        "zero_label_ratio": zero_label_ratio,
        "zero_label_ratio_exceeds_threshold": zero_label_ratio > zero_threshold,
        "unexpected_semantic_labels": unexpected_labels,
        "invalid_nonzero_pixel_count": invalid_nonzero_pixel_count,
        "unique_gazebo_instance_count_count": len(unique_gazebo_instance_count_values),
        "unique_gazebo_instance_count_values": unique_gazebo_instance_count_values,
        "passed": zero_label_ratio <= zero_threshold and not unexpected_labels,
    }
    histogram_rows = build_histogram_rows(camera_id, semantic_path, semantic_width, semantic_height, semantic_histogram, semantic_map)
    invalid_rows = build_invalid_rows(camera_id, semantic_path, semantic_width, semantic_height, semantic_histogram, semantic_map)
    return mask_summary, histogram_rows, invalid_rows


def main() -> None:
    args = parse_args()
    if args.zero_threshold < 0.0:
        fail("--zero-threshold must be non-negative.")
    if args.expected_messages_per_camera <= 0:
        fail("--expected-messages-per-camera must be positive.")

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")

    experiment_root = config_path.resolve().parents[1]
    semantic_map_path = experiment_root / "configs" / "semantic_label_map.json"
    native_root = experiment_root / "perception_raw" / "native" / PRIMARY_MODE
    validation_root = experiment_root / "validation"
    summary_path = validation_root / "native_segmentation_validation_summary.json"
    histograms_path = validation_root / "native_segmentation_label_histograms.csv"
    invalid_pixels_path = validation_root / "native_segmentation_invalid_pixels.csv"

    camera_ids = load_camera_ids(config)
    expected_camera_count = load_expected_camera_count(config, camera_ids)
    semantic_map = load_semantic_label_map(semantic_map_path)
    pillow_image = try_import_pillow()

    expected_mask_count = expected_camera_count * args.expected_messages_per_camera
    failures: list[str] = []
    histogram_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []

    if expected_camera_count != len(camera_ids):
        failures.append(
            f"Config mismatch: expected_camera_count={expected_camera_count} but camera_ids has {len(camera_ids)} entries."
        )

    discovered_camera_ids = sorted(path.name for path in native_root.iterdir() if path.is_dir()) if native_root.is_dir() else []
    missing_camera_ids = sorted(set(camera_ids) - set(discovered_camera_ids))
    extra_camera_ids = sorted(set(discovered_camera_ids) - set(camera_ids))
    if not native_root.is_dir():
        failures.append(f"Missing panoptic native root directory: {project_rel(native_root)}.")
    if len(discovered_camera_ids) != expected_camera_count:
        failures.append(f"Expected {expected_camera_count} panoptic camera directories, found {len(discovered_camera_ids)}.")
    if missing_camera_ids:
        failures.append(f"Missing expected panoptic camera directories: {', '.join(missing_camera_ids)}.")
    if extra_camera_ids:
        failures.append(f"Found unexpected panoptic camera directories: {', '.join(extra_camera_ids)}.")

    camera_summaries: list[dict[str, Any]] = []
    total_zero_label_pixels = 0
    total_pixels = 0
    total_invalid_nonzero_pixels = 0
    actual_semantic_decoded_count = 0
    actual_gazebo_instance_count_count = 0
    masks_over_zero_threshold = 0
    overall_unique_gazebo_instance_count_values: set[int] = set()

    for camera_id in camera_ids:
        camera_root = native_root / camera_id
        subdir_paths = {name: camera_root / name for name in REQUIRED_CAPTURE_SUBDIRS}
        missing_subdirs = [name for name, path in subdir_paths.items() if not path.is_dir()]
        empty_subdirs = [name for name, path in subdir_paths.items() if path.is_dir() and count_files(path) == 0]
        file_counts = {name: count_files(path) for name, path in subdir_paths.items()}

        semantic_mask_lookup = build_mask_lookup(list_mask_files(subdir_paths["semantic_decoded"]))
        count_mask_lookup = build_mask_lookup(list_mask_files(subdir_paths["gazebo_instance_count"]))
        actual_semantic_decoded_count += len(semantic_mask_lookup)
        actual_gazebo_instance_count_count += len(count_mask_lookup)

        missing_semantic_indices = sorted(set(count_mask_lookup) - set(semantic_mask_lookup))
        missing_count_indices = sorted(set(semantic_mask_lookup) - set(count_mask_lookup))
        paired_indices = sorted(set(semantic_mask_lookup) & set(count_mask_lookup))

        if not camera_root.is_dir():
            failures.append(f"{camera_id}: missing panoptic camera directory {project_rel(camera_root)}.")
        if missing_subdirs:
            failures.append(f"{camera_id}: missing required panoptic subdirectories: {', '.join(missing_subdirs)}.")
        if empty_subdirs:
            failures.append(f"{camera_id}: empty required panoptic subdirectories: {', '.join(empty_subdirs)}.")
        if len(semantic_mask_lookup) != args.expected_messages_per_camera:
            failures.append(
                f"{camera_id}: expected {args.expected_messages_per_camera} semantic decoded masks, found {len(semantic_mask_lookup)}."
            )
        if len(count_mask_lookup) != args.expected_messages_per_camera:
            failures.append(
                f"{camera_id}: expected {args.expected_messages_per_camera} gazebo instance count masks, found {len(count_mask_lookup)}."
            )
        if missing_semantic_indices:
            failures.append(
                f"{camera_id}: missing semantic decoded masks for indices {', '.join(missing_semantic_indices)}."
            )
        if missing_count_indices:
            failures.append(
                f"{camera_id}: missing gazebo instance count masks for indices {', '.join(missing_count_indices)}."
            )

        camera_zero_label_pixels = 0
        camera_total_pixels = 0
        camera_invalid_nonzero_pixels = 0
        camera_unexpected_semantic_labels: set[int] = set()
        camera_unique_gazebo_instance_count_values: set[int] = set()
        camera_masks_over_zero_threshold = 0
        mask_summaries: list[dict[str, Any]] = []

        for message_index in paired_indices:
            semantic_path = semantic_mask_lookup[message_index]
            count_path = count_mask_lookup[message_index]
            try:
                mask_summary, mask_histogram_rows, mask_invalid_rows = validate_paired_masks(
                    camera_id,
                    message_index,
                    semantic_path,
                    count_path,
                    semantic_map,
                    args.zero_threshold,
                    pillow_image,
                )
            except Exception as exc:
                failures.append(f"{camera_id}/{message_index}: failed to validate panoptic masks: {exc}")
                continue

            histogram_rows.extend(mask_histogram_rows)
            invalid_rows.extend(mask_invalid_rows)
            mask_summaries.append(mask_summary)
            camera_zero_label_pixels += int(mask_summary["zero_label_pixel_count"])
            camera_total_pixels += int(mask_summary["pixel_count"])
            camera_invalid_nonzero_pixels += int(mask_summary["invalid_nonzero_pixel_count"])
            camera_unexpected_semantic_labels.update(int(value) for value in mask_summary["unexpected_semantic_labels"])
            camera_unique_gazebo_instance_count_values.update(
                int(value) for value in mask_summary["unique_gazebo_instance_count_values"]
            )
            if mask_summary["zero_label_ratio_exceeds_threshold"]:
                camera_masks_over_zero_threshold += 1
                failures.append(
                    f"{camera_id}/{message_index}: semantic zero-label ratio "
                    f"{mask_summary['zero_label_ratio']:.6f} exceeds threshold {args.zero_threshold:.6f}."
                )
            if mask_summary["unexpected_semantic_labels"]:
                failures.append(
                    f"{camera_id}/{message_index}: semantic_decoded contains invalid labels "
                    f"{mask_summary['unexpected_semantic_labels']}."
                )

        total_zero_label_pixels += camera_zero_label_pixels
        total_pixels += camera_total_pixels
        total_invalid_nonzero_pixels += camera_invalid_nonzero_pixels
        masks_over_zero_threshold += camera_masks_over_zero_threshold
        overall_unique_gazebo_instance_count_values.update(camera_unique_gazebo_instance_count_values)
        camera_zero_ratio = (camera_zero_label_pixels / camera_total_pixels) if camera_total_pixels else 0.0

        camera_summaries.append(
            {
                "camera_id": camera_id,
                "root": project_rel(camera_root),
                "present": camera_root.is_dir(),
                "missing_subdirs": missing_subdirs,
                "empty_subdirs": empty_subdirs,
                "file_counts": file_counts,
                "semantic_decoded_count": len(semantic_mask_lookup),
                "gazebo_instance_count_count": len(count_mask_lookup),
                "paired_message_index_count": len(paired_indices),
                "missing_semantic_decoded_indices": missing_semantic_indices,
                "missing_gazebo_instance_count_indices": missing_count_indices,
                "zero_label_pixel_count": camera_zero_label_pixels,
                "total_pixel_count": camera_total_pixels,
                "zero_label_ratio": camera_zero_ratio,
                "zero_label_ratio_exceeds_threshold": camera_zero_ratio > args.zero_threshold,
                "mask_count_over_zero_threshold": camera_masks_over_zero_threshold,
                "invalid_nonzero_pixel_count": camera_invalid_nonzero_pixels,
                "unexpected_semantic_labels": sorted(camera_unexpected_semantic_labels),
                "unique_gazebo_instance_count_count": len(camera_unique_gazebo_instance_count_values),
                "unique_gazebo_instance_count_values": sorted(camera_unique_gazebo_instance_count_values),
                "masks": mask_summaries,
                "passed": (
                    camera_root.is_dir()
                    and not missing_subdirs
                    and not empty_subdirs
                    and len(semantic_mask_lookup) == args.expected_messages_per_camera
                    and len(count_mask_lookup) == args.expected_messages_per_camera
                    and not missing_semantic_indices
                    and not missing_count_indices
                    and camera_invalid_nonzero_pixels == 0
                    and camera_masks_over_zero_threshold == 0
                ),
            }
        )

    if actual_semantic_decoded_count != expected_mask_count:
        failures.append(
            f"Expected {expected_mask_count} semantic decoded panoptic masks, found {actual_semantic_decoded_count}."
        )
    if actual_gazebo_instance_count_count != expected_mask_count:
        failures.append(
            f"Expected {expected_mask_count} gazebo instance count masks, found {actual_gazebo_instance_count_count}."
        )

    summary = {
        "experiment_name": str(config.get("experiment_name", "perception_rt_small_v0")),
        "config_path": project_rel(config_path),
        "semantic_label_map_path": project_rel(semantic_map_path),
        "native_root": project_rel(native_root),
        "primary_mode": PRIMARY_MODE,
        "zero_label_threshold": args.zero_threshold,
        "expected_camera_count": expected_camera_count,
        "expected_messages_per_camera": args.expected_messages_per_camera,
        "expected_semantic_decoded_count": expected_mask_count,
        "expected_gazebo_instance_count_count": expected_mask_count,
        "outputs": {
            "summary_json": project_rel(summary_path),
            "label_histograms_csv": project_rel(histograms_path) if args.write_diagnostics else None,
            "invalid_pixels_csv": project_rel(invalid_pixels_path) if args.write_diagnostics else None,
            "supplementary_diagnostics_written": args.write_diagnostics,
        },
        "overall_passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "panoptic": {
            "root": project_rel(native_root),
            "camera_dir_count": len(discovered_camera_ids),
            "expected_camera_count": expected_camera_count,
            "camera_count_matches_expected": len(discovered_camera_ids) == expected_camera_count,
            "configured_camera_ids": camera_ids,
            "discovered_camera_ids": discovered_camera_ids,
            "missing_camera_ids": missing_camera_ids,
            "extra_camera_ids": extra_camera_ids,
            "actual_semantic_decoded_count": actual_semantic_decoded_count,
            "actual_gazebo_instance_count_count": actual_gazebo_instance_count_count,
            "decoded_count_matches_expected": (
                actual_semantic_decoded_count == expected_mask_count
                and actual_gazebo_instance_count_count == expected_mask_count
            ),
            "allowed_semantic_labels": list(REQUIRED_SEMANTIC_LABELS),
            "zero_label_pixel_count": total_zero_label_pixels,
            "total_pixel_count": total_pixels,
            "zero_label_ratio": (total_zero_label_pixels / total_pixels) if total_pixels else 0.0,
            "invalid_nonzero_pixel_count": total_invalid_nonzero_pixels,
            "masks_over_zero_threshold": masks_over_zero_threshold,
            "unique_gazebo_instance_count_count": len(overall_unique_gazebo_instance_count_values),
            "unique_gazebo_instance_count_values": sorted(overall_unique_gazebo_instance_count_values),
            "camera_summaries": camera_summaries,
        },
    }

    write_json(summary_path, summary)
    if args.write_diagnostics:
        write_csv(
            histograms_path,
            [
                "mode",
                "camera_id",
                "mask_path",
                "width",
                "height",
                "label",
                "pixel_count",
                "pixel_ratio",
                "is_zero_label",
                "is_allowed_label",
                "is_invalid_label",
                "label_name",
                "semantic_name",
            ],
            histogram_rows,
        )
        write_csv(
            invalid_pixels_path,
            [
                "mode",
                "camera_id",
                "mask_path",
                "width",
                "height",
                "invalid_label",
                "pixel_count",
                "pixel_ratio",
                "reason",
            ],
            invalid_rows,
        )

    print(f"experiment_name={summary['experiment_name']}")
    print(f"primary_mode={PRIMARY_MODE}")
    print(f"overall_passed={str(summary['overall_passed']).lower()}")
    print(f"failure_count={summary['failure_count']}")
    print(f"summary_json={project_rel(summary_path)}")
    if args.write_diagnostics:
        print(f"label_histograms_csv={project_rel(histograms_path)}")
        print(f"invalid_pixels_csv={project_rel(invalid_pixels_path)}")

    if failures:
        fail(
            f"Native panoptic segmentation validation found {len(failures)} issue(s). "
            f"See {project_rel(summary_path)} for details."
        )


if __name__ == "__main__":
    main()
