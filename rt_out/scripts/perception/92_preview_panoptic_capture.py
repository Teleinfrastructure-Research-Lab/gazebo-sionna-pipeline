#!/usr/bin/env python3
"""Build quick validation previews from Gazebo-native panoptic capture."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
PRIMARY_MODE = "panoptic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build quick preview assets from native Gazebo panoptic capture."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing preview outputs.")
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


def remove_existing_output(path: Path, force: bool) -> None:
    if not path.exists():
        return
    if not force:
        fail(f"Preview output already exists at {path}. Re-run with --force to overwrite.")
    shutil.rmtree(path)


def load_camera_ids(config: dict[str, Any]) -> list[str]:
    camera_ids = config.get("camera_ids")
    if not isinstance(camera_ids, list) or not all(isinstance(item, str) and item.strip() for item in camera_ids):
        fail("Config field 'camera_ids' must be a non-empty list of strings.")
    return camera_ids


def first_available_file(directory: Path, patterns: list[str]) -> Path | None:
    if not directory.is_dir():
        return None
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(directory.glob(pattern))
    files = sorted(path for path in candidates if path.is_file())
    return files[0] if files else None


def try_import_pillow():
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    return Image


def try_import_cv2():
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    return cv2


def copy_preview_file(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return project_rel(destination)


def build_montage_with_pillow(
    image_module: Any,
    semantic_decoded: Path,
    gazebo_instance_count: Path,
    colored_map: Path,
    destination: Path,
) -> str:
    images = [image_module.open(path).convert("RGB") for path in (semantic_decoded, gazebo_instance_count, colored_map)]
    try:
        widths = [image.width for image in images]
        heights = [image.height for image in images]
        montage = image_module.new("RGB", (sum(widths), max(heights)), color=(24, 24, 24))
        offset = 0
        for image in images:
            montage.paste(image, (offset, 0))
            offset += image.width
        destination.parent.mkdir(parents=True, exist_ok=True)
        montage.save(destination)
    finally:
        for image in images:
            image.close()
    return project_rel(destination)


def build_montage_with_cv2(
    cv2: Any,
    semantic_decoded: Path,
    gazebo_instance_count: Path,
    colored_map: Path,
    destination: Path,
) -> str:
    arrays = []
    for path in (semantic_decoded, gazebo_instance_count, colored_map):
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            fail(f"OpenCV could not read preview source image: {path}")
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        arrays.append(image)
    height = max(array.shape[0] for array in arrays)
    padded = []
    for array in arrays:
        if array.shape[0] != height:
            pad_rows = height - array.shape[0]
            array = cv2.copyMakeBorder(array, 0, pad_rows, 0, 0, cv2.BORDER_CONSTANT, value=(24, 24, 24))
        padded.append(array)
    montage = cv2.hconcat(padded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), montage):
        fail(f"OpenCV failed to write montage image: {destination}")
    return project_rel(destination)


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")

    experiment_root = config_path.resolve().parents[1]
    panoptic_root = experiment_root / "perception_raw" / "native" / PRIMARY_MODE
    preview_root = experiment_root / "validation" / "previews"
    summary_path = preview_root / "preview_summary.json"

    if not panoptic_root.is_dir():
        fail(f"Missing native panoptic capture root: {panoptic_root}")

    remove_existing_output(preview_root, args.force)
    preview_root.mkdir(parents=True, exist_ok=True)

    camera_ids = load_camera_ids(config)
    pillow_image = try_import_pillow()
    cv2 = try_import_cv2()
    montage_backend = "none"
    if pillow_image is not None:
        montage_backend = "pillow"
    elif cv2 is not None:
        montage_backend = "opencv"

    cameras_summary: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_copied_files = 0
    montage_count = 0

    for camera_id in camera_ids:
        panoptic_camera_root = panoptic_root / camera_id
        preview_camera_root = preview_root / camera_id
        preview_camera_root.mkdir(parents=True, exist_ok=True)

        semantic_decoded = first_available_file(panoptic_camera_root / "semantic_decoded", ["*.pgm", "*.png"])
        gazebo_instance_count = first_available_file(panoptic_camera_root / "gazebo_instance_count", ["*.pgm", "*.png"])
        colored_map = first_available_file(panoptic_camera_root / "colored_maps", ["*.ppm", "*.png"])

        camera_entry: dict[str, Any] = {
            "camera_id": camera_id,
            "semantic_decoded_preview": None,
            "gazebo_instance_count_preview": None,
            "colored_map_preview": None,
            "montage_preview": None,
            "warnings": [],
        }

        if semantic_decoded is None:
            message = f"No panoptic semantic-decoded mask found for {camera_id}."
            camera_entry["warnings"].append(message)
            warnings.append(message)
        else:
            destination = preview_camera_root / f"{camera_id}_semantic_decoded{semantic_decoded.suffix}"
            camera_entry["semantic_decoded_preview"] = copy_preview_file(semantic_decoded, destination)
            total_copied_files += 1

        if gazebo_instance_count is None:
            message = f"No panoptic Gazebo instance-count mask found for {camera_id}."
            camera_entry["warnings"].append(message)
            warnings.append(message)
        else:
            destination = preview_camera_root / f"{camera_id}_gazebo_instance_count{gazebo_instance_count.suffix}"
            camera_entry["gazebo_instance_count_preview"] = copy_preview_file(gazebo_instance_count, destination)
            total_copied_files += 1

        if colored_map is None:
            message = f"No panoptic colored map found for {camera_id}."
            camera_entry["warnings"].append(message)
            warnings.append(message)
        else:
            destination = preview_camera_root / f"{camera_id}_colored_map{colored_map.suffix}"
            camera_entry["colored_map_preview"] = copy_preview_file(colored_map, destination)
            total_copied_files += 1

        if semantic_decoded and gazebo_instance_count and colored_map:
            montage_path = preview_camera_root / f"{camera_id}_preview_montage.png"
            if montage_backend == "pillow":
                camera_entry["montage_preview"] = build_montage_with_pillow(
                    pillow_image,
                    semantic_decoded,
                    gazebo_instance_count,
                    colored_map,
                    montage_path,
                )
                montage_count += 1
            elif montage_backend == "opencv":
                camera_entry["montage_preview"] = build_montage_with_cv2(
                    cv2,
                    semantic_decoded,
                    gazebo_instance_count,
                    colored_map,
                    montage_path,
                )
                montage_count += 1
            else:
                message = (
                    f"No Pillow/OpenCV available for montage generation; copied representative files only for {camera_id}."
                )
                camera_entry["warnings"].append(message)
                warnings.append(message)

        cameras_summary.append(camera_entry)

    summary = {
        "experiment_name": config.get("experiment_name", "perception_rt_small_v0"),
        "primary_mode": PRIMARY_MODE,
        "preview_root": project_rel(preview_root),
        "panoptic_input_root": project_rel(panoptic_root),
        "camera_count": len(camera_ids),
        "copied_preview_file_count": total_copied_files,
        "montage_backend": montage_backend,
        "montage_count": montage_count,
        "cameras": cameras_summary,
        "warnings": warnings,
    }
    write_json(summary_path, summary)

    print(f"experiment_name={summary['experiment_name']}")
    print(f"primary_mode={summary['primary_mode']}")
    print(f"preview_root={summary['preview_root']}")
    print(f"camera_count={summary['camera_count']}")
    print(f"copied_preview_file_count={summary['copied_preview_file_count']}")
    print(f"montage_backend={summary['montage_backend']}")
    print(f"montage_count={summary['montage_count']}")
    print(f"warning_count={len(warnings)}")


if __name__ == "__main__":
    main()
