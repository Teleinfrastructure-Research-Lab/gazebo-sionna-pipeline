#!/usr/bin/env python3
"""Build final fully labeled RGB point clouds from synchronized stable-instance capture."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
INDEX_FIELDS = [
    "selected_frame_id",
    "camera_id",
    "source_sync_metadata_path",
    "source_rgb_path",
    "source_pcl_path",
    "source_compact_instance_label_path",
    "output_labeled_pcl_path",
    "point_count",
    "zero_label_point_count",
    "unknown_label_point_count",
    "unique_class_label_count",
    "unique_instance_id_count",
    "status",
    "notes",
]
EXPECTED_INPUT_FIELDS = ["x", "y", "z", "red", "green", "blue", "pixel_u", "pixel_v"]
FINAL_PROPERTY_LINES = [
    "property float x",
    "property float y",
    "property float z",
    "property uchar red",
    "property uchar green",
    "property uchar blue",
    "property ushort class_label",
    "property int instance_id",
]


class BuildError(RuntimeError):
    """Raised when strict labeled point-cloud export cannot proceed safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build final fully labeled RGB point clouds from synchronized stable-instance capture."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Perception dataset config JSON.")
    parser.add_argument(
        "--sync-root",
        type=Path,
        default=None,
        help="Root directory containing synchronized stable-instance RGB/PCL capture outputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for final labeled colorized point clouds.",
    )
    parser.add_argument(
        "--frame-filter",
        type=str,
        default=None,
        help="Optional comma-separated selected_frame_id filter, e.g. 0,1,2.",
    )
    parser.add_argument(
        "--camera-filter",
        type=str,
        default=None,
        help="Optional comma-separated camera_id filter.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite output directory.")
    parser.add_argument("--pretty-json", action="store_true", help="Pretty-print JSON outputs.")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise BuildError(f"Missing {label}: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise BuildError(f"Failed to parse {label} JSON at {path}: {exc}") from exc


def write_json(path: Path, payload: Any, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if pretty:
            json.dump(payload, handle, indent=2, sort_keys=False)
        else:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=False)
        handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def ensure_output_dir(path: Path, force: bool) -> None:
    if path.exists():
        if not force:
            raise BuildError(f"Output directory already exists. Re-run with --force: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def parse_filter(raw_value: str | None) -> set[str] | None:
    if raw_value is None:
        return None
    values = {item.strip() for item in raw_value.split(",") if item.strip()}
    return values or None


def parse_int(value: Any, label: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BuildError(f"Could not parse integer for {label}: {value!r}") from exc


def frame_dir_name(selected_frame_id: int) -> str:
    return f"frame_{selected_frame_id:03d}"


def load_camera_ids(config_path: Path) -> tuple[dict[str, Any], list[str], Path, Path, Path]:
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        raise BuildError(f"Perception dataset config at {config_path} must be a JSON object.")
    camera_ids = config.get("camera_ids")
    if not isinstance(camera_ids, list) or not all(isinstance(item, str) and item.strip() for item in camera_ids):
        raise BuildError("Config field 'camera_ids' must be a non-empty list of camera IDs.")
    experiment_root = config_path.resolve().parents[1]
    default_sync_root = experiment_root / "perception_raw" / "native" / "sync_stable_instance_rgb_pcl"
    default_output_dir = experiment_root / "reconstruction" / "labeled_colorized_pcl_sync"
    stable_map_path = experiment_root / "perception_sdf" / "stable_instance_label_map.json"
    return config, list(camera_ids), experiment_root, default_sync_root, stable_map_path


def build_stable_label_lookup(stable_map_path: Path, registry_path: Path) -> tuple[dict[int, dict[str, Any]], dict[int, tuple[int, str]]]:
    payload = load_json(stable_map_path, "stable instance label map")
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise BuildError(f"Stable instance label map at {stable_map_path} must contain an 'entries' list.")
    lookup: dict[int, dict[str, Any]] = {}
    semantic_by_instance: dict[int, tuple[int, str]] = {}
    for entry in payload["entries"]:
        if not isinstance(entry, dict):
            raise BuildError(f"Stable map entry is not an object: {entry!r}")
        compact_label = parse_int(entry.get("compact_instance_label"), "compact_instance_label")
        stable_instance_id = parse_int(entry.get("stable_instance_id"), "stable_instance_id")
        semantic_id = parse_int(entry.get("semantic_id"), "semantic_id")
        semantic_name = str(entry.get("semantic_name", "")).strip()
        if compact_label <= 0:
            raise BuildError(f"Compact label must be positive in {stable_map_path}: {compact_label}")
        if stable_instance_id <= 0:
            raise BuildError(f"Stable instance id must be positive in {stable_map_path}: {stable_instance_id}")
        if not (1 <= semantic_id <= 10):
            raise BuildError(f"semantic_id must stay in 1..10 in {stable_map_path}: {semantic_id}")
        lookup[compact_label] = {
            "stable_instance_id": stable_instance_id,
            "semantic_id": semantic_id,
            "semantic_name": semantic_name,
            "instance_name": str(entry.get("instance_name", "")),
            "source": str(entry.get("source", "")),
        }
        semantic_by_instance[stable_instance_id] = (semantic_id, semantic_name)

    registry_payload = load_json(registry_path, "instance registry")
    if isinstance(registry_payload, dict) and isinstance(registry_payload.get("instances"), list):
        for instance in registry_payload["instances"]:
            if not isinstance(instance, dict):
                continue
            instance_id = parse_int(instance.get("instance_id"), "instance_id")
            semantic_id = parse_int(instance.get("semantic_id"), "semantic_id")
            semantic_name = str(instance.get("semantic_name", "")).strip()
            recovered = semantic_by_instance.get(instance_id)
            if recovered is None:
                continue
            if recovered != (semantic_id, semantic_name):
                raise BuildError(
                    "Stable instance label map disagrees with instance registry for "
                    f"instance_id={instance_id}: map={recovered}, registry={(semantic_id, semantic_name)}"
                )
    return lookup, semantic_by_instance


def _read_token(handle) -> bytes:
    token = bytearray()
    while True:
        char = handle.read(1)
        if not char:
            break
        if char == b"#":
            handle.readline()
            continue
        if char.isspace():
            if token:
                break
            continue
        token.extend(char)
    return bytes(token)


def read_pnm(path: Path) -> tuple[str, int, int, int, bytes]:
    if not path.is_file():
        raise BuildError(f"Missing image/mask file: {path}")
    with path.open("rb") as handle:
        magic = _read_token(handle)
        if magic not in {b"P5", b"P6"}:
            raise BuildError(f"Unsupported PNM format at {path}: {magic!r}")
        width = int(_read_token(handle))
        height = int(_read_token(handle))
        max_value = int(_read_token(handle))
        payload = handle.read()
    return magic.decode("ascii"), width, height, max_value, payload


def load_rgb_pixels(path: Path, expected_width: int, expected_height: int) -> list[tuple[int, int, int]]:
    magic, width, height, max_value, payload = read_pnm(path)
    if magic != "P6":
        raise BuildError(f"RGB file must be P6 PPM at {path}, got {magic}")
    if max_value != 255:
        raise BuildError(f"RGB PPM max value must be 255 at {path}, got {max_value}")
    if width != expected_width or height != expected_height:
        raise BuildError(
            f"RGB dimensions at {path} do not match metadata: {width}x{height} vs {expected_width}x{expected_height}"
        )
    expected_bytes = width * height * 3
    if len(payload) != expected_bytes:
        raise BuildError(f"RGB payload size mismatch at {path}: expected {expected_bytes}, got {len(payload)}")
    return [(payload[index], payload[index + 1], payload[index + 2]) for index in range(0, len(payload), 3)]


def load_compact_mask(path: Path, expected_width: int, expected_height: int) -> bytes:
    magic, width, height, max_value, payload = read_pnm(path)
    if magic != "P5":
        raise BuildError(f"Compact instance label mask must be P5 PGM at {path}, got {magic}")
    if max_value > 255:
        raise BuildError(f"Compact instance label mask max value must be <=255 at {path}, got {max_value}")
    if width != expected_width or height != expected_height:
        raise BuildError(
            "Compact instance label mask dimensions at "
            f"{path} do not match metadata: {width}x{height} vs {expected_width}x{expected_height}"
        )
    expected_bytes = width * height
    if len(payload) != expected_bytes:
        raise BuildError(
            f"Compact instance label mask size mismatch at {path}: expected {expected_bytes}, got {len(payload)}"
        )
    return payload


def parse_ascii_ply(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.is_file():
        raise BuildError(f"Missing synchronized PLY file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        first = handle.readline().strip()
        if first != "ply":
            raise BuildError(f"PLY at {path} must start with 'ply'")
        fmt = handle.readline().strip()
        if fmt != "format ascii 1.0":
            raise BuildError(f"Only ASCII PLY is supported at {path}; got {fmt!r}")

        vertex_count: int | None = None
        properties: list[str] = []
        in_vertex_element = False
        while True:
            line = handle.readline()
            if not line:
                raise BuildError(f"Incomplete PLY header at {path}")
            stripped = line.strip()
            if stripped == "end_header":
                break
            if stripped.startswith("element "):
                parts = stripped.split()
                in_vertex_element = len(parts) >= 3 and parts[1] == "vertex"
                if in_vertex_element:
                    vertex_count = parse_int(parts[2], "element vertex count")
                continue
            if stripped.startswith("property ") and in_vertex_element:
                parts = stripped.split()
                if len(parts) < 3:
                    raise BuildError(f"Malformed property line at {path}: {stripped}")
                properties.append(parts[-1])

        if vertex_count is None:
            raise BuildError(f"PLY at {path} is missing an element vertex declaration")
        missing = [name for name in EXPECTED_INPUT_FIELDS if name not in properties]
        if missing:
            raise BuildError(f"PLY at {path} is missing required fields: {missing}")

        rows: list[list[str]] = []
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) != len(properties):
                raise BuildError(
                    f"PLY row at {path} has {len(parts)} columns but header declared {len(properties)} properties"
                )
            rows.append(parts)
    if len(rows) != vertex_count:
        raise BuildError(f"PLY at {path} declared {vertex_count} vertices but contained {len(rows)} rows")
    return properties, rows


def output_path_for(output_root: Path, selected_frame_id: int, camera_id: str) -> Path:
    return output_root / frame_dir_name(selected_frame_id) / f"{camera_id}_labeled_colorized.ply"


def metadata_source_path(metadata_row: dict[str, Any], key: str, fallback: Path | None = None) -> Path:
    value = metadata_row.get(key)
    if isinstance(value, str) and value.strip():
        return resolve_path(Path(value))
    if fallback is not None:
        return fallback
    raise BuildError(f"Metadata is missing required path field '{key}'")


def write_final_ply(path: Path, points: list[tuple[float, float, float, int, int, int, int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write(f"element vertex {len(points)}\n")
        for line in FINAL_PROPERTY_LINES:
            handle.write(f"{line}\n")
        handle.write("end_header\n")
        for x, y, z, red, green, blue, class_label, instance_id in points:
            handle.write(
                f"{x:.6f} {y:.6f} {z:.6f} {red:d} {green:d} {blue:d} {class_label:d} {instance_id:d}\n"
            )


def collect_metadata_rows(sync_root: Path, camera_ids: list[str]) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    for camera_id in camera_ids:
        metadata_dir = sync_root / camera_id / "metadata"
        if not metadata_dir.is_dir():
            continue
        for metadata_path in sorted(metadata_dir.glob("sync_*.json")):
            rows.append((camera_id, metadata_path))
    return rows


def process_cloud(
    camera_id: str,
    metadata_path: Path,
    stable_lookup: dict[int, dict[str, Any]],
    output_root: Path,
) -> tuple[dict[str, Any], set[int], set[int], int, int]:
    metadata = load_json(metadata_path, f"metadata {metadata_path}")
    if not isinstance(metadata, dict):
        raise BuildError(f"Metadata at {metadata_path} must be a JSON object.")

    selected_frame_id = parse_int(metadata.get("group_index"), "group_index")
    width = parse_int(metadata.get("width"), "width")
    height = parse_int(metadata.get("height"), "height")
    if width <= 0 or height <= 0:
        raise BuildError(f"Metadata at {metadata_path} has invalid width/height: {width}x{height}")
    if metadata.get("has_pixel_coordinates") is not True:
        raise BuildError(f"Metadata at {metadata_path} must have has_pixel_coordinates=true")
    if metadata.get("label_mode") != "compact_stable_instance":
        raise BuildError(f"Metadata at {metadata_path} must have label_mode=compact_stable_instance")

    source_rgb_path = metadata_source_path(metadata, "rgb_path")
    source_pcl_path = metadata_source_path(metadata, "pcl_path")
    source_compact_path = metadata_source_path(metadata, "compact_instance_label_path")
    rgb_pixels = load_rgb_pixels(source_rgb_path, width, height)
    compact_mask = load_compact_mask(source_compact_path, width, height)
    properties, rows = parse_ascii_ply(source_pcl_path)

    property_index = {name: properties.index(name) for name in EXPECTED_INPUT_FIELDS}
    final_points: list[tuple[float, float, float, int, int, int, int, int]] = []
    zero_label_point_count = 0
    unknown_label_point_count = 0
    unique_class_labels: set[int] = set()
    unique_instance_ids: set[int] = set()

    for parts in rows:
        try:
            x = float(parts[property_index["x"]])
            y = float(parts[property_index["y"]])
            z = float(parts[property_index["z"]])
            pixel_u = int(parts[property_index["pixel_u"]])
            pixel_v = int(parts[property_index["pixel_v"]])
        except ValueError as exc:
            raise BuildError(f"PLY row in {source_pcl_path} has non-numeric xyz/pixel fields") from exc
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise BuildError(f"PLY row in {source_pcl_path} contains non-finite xyz values")
        if not (0 <= pixel_u < width and 0 <= pixel_v < height):
            raise BuildError(
                f"PLY row in {source_pcl_path} has out-of-bounds pixel coordinates ({pixel_u}, {pixel_v})"
            )
        pixel_index = pixel_v * width + pixel_u
        compact_label = compact_mask[pixel_index]
        if compact_label == 0:
            zero_label_point_count += 1
            continue
        label_entry = stable_lookup.get(int(compact_label))
        if label_entry is None:
            unknown_label_point_count += 1
            continue
        class_label = parse_int(label_entry["semantic_id"], "semantic_id")
        instance_id = parse_int(label_entry["stable_instance_id"], "stable_instance_id")
        if not (1 <= class_label <= 10):
            raise BuildError(
                f"Stable map semantic_id for compact label {compact_label} must be in 1..10, got {class_label}"
            )
        if instance_id <= 0:
            raise BuildError(
                f"Stable map stable_instance_id for compact label {compact_label} must be positive, got {instance_id}"
            )
        red, green, blue = rgb_pixels[pixel_index]
        final_points.append((x, y, z, red, green, blue, class_label, instance_id))
        unique_class_labels.add(class_label)
        unique_instance_ids.add(instance_id)

    if zero_label_point_count > 0 or unknown_label_point_count > 0:
        raise BuildError(
            f"Strict label export failed: zero_label_point_count={zero_label_point_count}, "
            f"unknown_label_point_count={unknown_label_point_count}"
        )
    if not final_points:
        raise BuildError("Strict label export produced zero final points")

    output_path = output_path_for(output_root, selected_frame_id, camera_id)
    write_final_ply(output_path, final_points)
    row = {
        "selected_frame_id": str(selected_frame_id),
        "camera_id": camera_id,
        "source_sync_metadata_path": project_rel(metadata_path),
        "source_rgb_path": project_rel(source_rgb_path),
        "source_pcl_path": project_rel(source_pcl_path),
        "source_compact_instance_label_path": project_rel(source_compact_path),
        "output_labeled_pcl_path": project_rel(output_path),
        "point_count": str(len(final_points)),
        "zero_label_point_count": "0",
        "unknown_label_point_count": "0",
        "unique_class_label_count": str(len(unique_class_labels)),
        "unique_instance_id_count": str(len(unique_instance_ids)),
        "status": "ok",
        "notes": "",
    }
    return row, unique_class_labels, unique_instance_ids, 0, 0


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    if not config_path.is_file():
        fail(f"Missing perception dataset config: {config_path}")

    _, camera_ids, experiment_root, default_sync_root, stable_map_path = load_camera_ids(config_path)
    registry_path = experiment_root / "frames" / "instance_registry.json"
    sync_root = resolve_path(args.sync_root) if args.sync_root is not None else default_sync_root
    output_root = resolve_path(args.output_dir) if args.output_dir is not None else (experiment_root / "reconstruction" / "labeled_colorized_pcl_sync")
    frame_filter = parse_filter(args.frame_filter)
    camera_filter = parse_filter(args.camera_filter)

    if not sync_root.is_dir():
        fail(f"Missing synchronized stable-instance capture root: {sync_root}")
    stable_lookup, _ = build_stable_label_lookup(stable_map_path, registry_path)
    ensure_output_dir(output_root, args.force)

    metadata_rows = collect_metadata_rows(sync_root, camera_ids)
    if camera_filter is not None:
        metadata_rows = [item for item in metadata_rows if item[0] in camera_filter]

    rows: list[dict[str, Any]] = []
    processed_cloud_count = 0
    valid_cloud_count = 0
    failed_cloud_count = 0
    total_points_written = 0
    zero_label_point_count = 0
    unknown_label_point_count = 0
    unique_class_labels_observed: set[int] = set()
    unique_instance_ids_observed: set[int] = set()
    errors: list[str] = []

    for camera_id, metadata_path in metadata_rows:
        try:
            metadata = load_json(metadata_path, f"metadata {metadata_path}")
            if not isinstance(metadata, dict):
                raise BuildError(f"Metadata at {metadata_path} must be a JSON object.")
            selected_frame_id = parse_int(metadata.get("group_index"), "group_index")
        except BuildError as exc:
            processed_cloud_count += 1
            failed_cloud_count += 1
            message = f"{project_rel(metadata_path)}: {exc}"
            errors.append(message)
            rows.append(
                {
                    "selected_frame_id": "",
                    "camera_id": camera_id,
                    "source_sync_metadata_path": project_rel(metadata_path),
                    "source_rgb_path": "",
                    "source_pcl_path": "",
                    "source_compact_instance_label_path": "",
                    "output_labeled_pcl_path": "",
                    "point_count": "0",
                    "zero_label_point_count": "0",
                    "unknown_label_point_count": "0",
                    "unique_class_label_count": "0",
                    "unique_instance_id_count": "0",
                    "status": "error",
                    "notes": str(exc),
                }
            )
            continue

        if frame_filter is not None and str(selected_frame_id) not in frame_filter:
            continue

        processed_cloud_count += 1
        try:
            row, class_labels, instance_ids, zero_count, unknown_count = process_cloud(
                camera_id,
                metadata_path,
                stable_lookup,
                output_root,
            )
            valid_cloud_count += 1
            total_points_written += parse_int(row["point_count"], "point_count")
            zero_label_point_count += zero_count
            unknown_label_point_count += unknown_count
            unique_class_labels_observed.update(class_labels)
            unique_instance_ids_observed.update(instance_ids)
            rows.append(row)
        except BuildError as exc:
            failed_cloud_count += 1
            message = f"{project_rel(metadata_path)}: {exc}"
            errors.append(message)
            rows.append(
                {
                    "selected_frame_id": str(selected_frame_id),
                    "camera_id": camera_id,
                    "source_sync_metadata_path": project_rel(metadata_path),
                    "source_rgb_path": "",
                    "source_pcl_path": "",
                    "source_compact_instance_label_path": "",
                    "output_labeled_pcl_path": "",
                    "point_count": "0",
                    "zero_label_point_count": "0",
                    "unknown_label_point_count": "0",
                    "unique_class_label_count": "0",
                    "unique_instance_id_count": "0",
                    "status": "error",
                    "notes": str(exc),
                }
            )

    rows.sort(key=lambda row: (parse_int(row["selected_frame_id"] or -1, "selected_frame_id"), row["camera_id"]))
    index_path = output_root / "labeled_colorized_pcl_index.csv"
    summary_path = output_root / "labeled_colorized_pcl_summary.json"
    write_csv(index_path, rows)
    summary = {
        "experiment_name": "perception_rt_small_v0",
        "sync_root": project_rel(sync_root),
        "output_dir": project_rel(output_root),
        "stable_instance_label_map": project_rel(stable_map_path),
        "processed_cloud_count": processed_cloud_count,
        "valid_cloud_count": valid_cloud_count,
        "failed_cloud_count": failed_cloud_count,
        "total_points_written": total_points_written,
        "zero_label_point_count": zero_label_point_count,
        "unknown_label_point_count": unknown_label_point_count,
        "unique_class_labels_observed": sorted(unique_class_labels_observed),
        "unique_instance_ids_observed": sorted(unique_instance_ids_observed),
        "overall_passed": failed_cloud_count == 0 and valid_cloud_count > 0,
        "errors": errors,
    }
    write_json(summary_path, summary, args.pretty_json)

    print(f"processed_cloud_count={processed_cloud_count}")
    print(f"valid_cloud_count={valid_cloud_count}")
    print(f"failed_cloud_count={failed_cloud_count}")
    print(f"total_points_written={total_points_written}")
    print(f"zero_label_point_count={zero_label_point_count}")
    print(f"unknown_label_point_count={unknown_label_point_count}")
    print(f"overall_passed={summary['overall_passed']}")


if __name__ == "__main__":
    main()
