#!/usr/bin/env python3

"""Build raw occupancy-style geometry features from unsegmented frame meshes.

This script creates a class-agnostic baseline feature table for wireless
prediction experiments. It reuses the composed per-frame manifests, samples mesh
vertices in world space, and derives TX/RX-to-geometry features without using
semantic labels, material labels, model names, or object identities as model
inputs. The result approximates a raw 3D / occupancy / LiDAR-style baseline.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_VERTICES_PER_FRAME = 20_000
SUBSAMPLE_SEED = 42
OBJECT_AWARE_PREFIXES = ("geom_", "mat_", "sem_", "obj_", "raw_")
RAW_FEATURE_COLUMNS = [
    "raw_tx_rx_distance",
    "raw_vertex_count_near_link_0p25m",
    "raw_vertex_count_near_link_0p50m",
    "raw_vertex_count_near_link_1p00m",
    "raw_min_vertex_dist_to_link",
    "raw_mean_vertex_dist_to_link_k20",
    "raw_mean_vertex_dist_to_link_k50",
    "raw_vertex_count_near_rx_0p50m",
    "raw_vertex_count_near_tx_0p50m",
    "raw_link_corridor_occupancy_ratio_0p50m",
]

PLY_SCALAR_DTYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


class RawOccupancyFeatureError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build raw occupancy-style features from per-frame composed meshes."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to experiment_config.json",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RawOccupancyFeatureError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RawOccupancyFeatureError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RawOccupancyFeatureError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RawOccupancyFeatureError(f"{label} must be a non-empty string")
    return value.strip()


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RawOccupancyFeatureError(f"{label} must be a positive integer")
    return value


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def parse_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise RawOccupancyFeatureError(f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RawOccupancyFeatureError(f"{label} must be an integer") from exc


def parse_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise RawOccupancyFeatureError(f"{label} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RawOccupancyFeatureError(f"{label} must be numeric") from exc


def load_experiment_config(path: Path) -> dict[str, Any]:
    # Only the experiment metadata needed by this baseline is loaded here:
    # experiment name, frame count, and the output root containing manifests/features.
    config = require_object(load_json(path), "experiment_config.json")
    experiment_name = require_non_empty_string(
        config.get("experiment_name"),
        "experiment_config.experiment_name",
    )
    num_frames = require_positive_int(
        config.get("num_frames"),
        "experiment_config.num_frames",
    )
    output_dir = require_non_empty_string(
        config.get("output_dir"),
        "experiment_config.output_dir",
    )
    return {
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "output_root": resolve_project_path(output_dir),
        "config_path": path.resolve(),
    }


def load_object_feature_rows(path: Path, *, config_path: Path) -> list[dict[str, str]]:
    # Reuse the already labeled RT table as the row template so this raw baseline
    # preserves frame/RX rows and supervision targets exactly.
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise RawOccupancyFeatureError(
            "Missing object feature CSV: "
            f"{path}. Run `python3 rt_out/scripts/exp_build_object_features.py "
            f"--config {config_path}` first."
        ) from exc

    if not rows:
        raise RawOccupancyFeatureError(f"Object feature CSV is empty: {path}")
    return rows


def load_composed_manifest_index(path: Path, *, expected_frames: int) -> dict[int, dict[str, Any]]:
    # Read the composed-manifest index and reduce it to frame/sample/manifest
    # records so per-frame geometry can be cached once and reused across RX rows.
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise RawOccupancyFeatureError(f"Missing composed manifest index CSV: {path}") from exc

    if len(rows) != expected_frames:
        raise RawOccupancyFeatureError(
            f"Expected {expected_frames} composed manifest rows, found {len(rows)} in {path}"
        )

    manifest_by_frame: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        frame_id = parse_int(row.get("frame_id"), f"composed_manifest_index[{index}].frame_id")
        source_sample_index = parse_int(
            row.get("source_sample_index"),
            f"composed_manifest_index[{index}].source_sample_index",
        )
        manifest_path_text = require_non_empty_string(
            row.get("composed_manifest_path"),
            f"composed_manifest_index[{index}].composed_manifest_path",
        )
        if frame_id in manifest_by_frame:
            raise RawOccupancyFeatureError(f"Duplicate frame_id in composed manifest index: {frame_id}")
        manifest_path = resolve_project_path(manifest_path_text)
        if not manifest_path.exists():
            raise RawOccupancyFeatureError(f"Missing composed manifest: {manifest_path}")
        manifest_by_frame[frame_id] = {
            "frame_id": frame_id,
            "source_sample_index": source_sample_index,
            "manifest_path": manifest_path,
        }
    return manifest_by_frame


def preserved_columns_from_header(header: list[str]) -> list[str]:
    # Drop the existing object-aware feature columns and keep metadata, RT
    # metrics, labels, and coordinate fields intact.
    return [column for column in header if not column.startswith(OBJECT_AWARE_PREFIXES)]


def parse_optional_matrix44(value: Any, label: str) -> np.ndarray | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise RawOccupancyFeatureError(f"{label} must be a 4x4 matrix when present")
    rows: list[list[float]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 4:
            raise RawOccupancyFeatureError(f"{label}[{row_index}] must contain 4 numeric values")
        rows.append([parse_float(item, f"{label}[{row_index}][]") for item in row])
    return np.asarray(rows, dtype=np.float64)


def apply_transform(vertices: np.ndarray, transform: np.ndarray) -> np.ndarray:
    ones = np.ones((vertices.shape[0], 1), dtype=np.float64)
    homogeneous = np.concatenate([vertices, ones], axis=1)
    transformed = homogeneous @ transform.T
    return transformed[:, :3]


def read_ply_vertices(path: Path) -> np.ndarray:
    with path.open("rb") as handle:
        first_line = handle.readline().decode("ascii", errors="strict").strip()
        if first_line != "ply":
            raise RawOccupancyFeatureError(f"PLY file missing 'ply' header: {path}")

        format_name: str | None = None
        vertex_count: int | None = None
        vertex_properties: list[tuple[str, str]] = []
        current_element: str | None = None

        while True:
            raw_line = handle.readline()
            if not raw_line:
                raise RawOccupancyFeatureError(f"PLY header ended unexpectedly: {path}")
            line = raw_line.decode("ascii", errors="strict").strip()
            if line == "end_header":
                break
            if not line or line.startswith("comment"):
                continue
            parts = line.split()
            if parts[0] == "format":
                format_name = parts[1]
            elif parts[0] == "element":
                current_element = parts[1]
                if current_element == "vertex":
                    vertex_count = parse_int(parts[2], f"{path}.vertex_count")
            elif parts[0] == "property" and current_element == "vertex":
                if parts[1] == "list":
                    raise RawOccupancyFeatureError(
                        f"Vertex list properties are not supported in PLY file: {path}"
                    )
                property_type = parts[1]
                property_name = parts[2]
                if property_type not in PLY_SCALAR_DTYPES:
                    raise RawOccupancyFeatureError(
                        f"Unsupported PLY vertex property type {property_type!r} in {path}"
                    )
                vertex_properties.append((property_name, property_type))

        if format_name is None or vertex_count is None or not vertex_properties:
            raise RawOccupancyFeatureError(f"Incomplete PLY header in {path}")

        property_names = [name for name, _ in vertex_properties]
        if not {"x", "y", "z"}.issubset(property_names):
            raise RawOccupancyFeatureError(f"PLY file is missing x/y/z vertex properties: {path}")

        if format_name == "ascii":
            rows: list[list[float]] = []
            for vertex_index in range(vertex_count):
                raw_line = handle.readline()
                if not raw_line:
                    raise RawOccupancyFeatureError(
                        f"PLY file ended before reading {vertex_count} vertices: {path}"
                    )
                parts = raw_line.decode("ascii", errors="strict").strip().split()
                if len(parts) < len(vertex_properties):
                    raise RawOccupancyFeatureError(
                        f"ASCII PLY vertex line {vertex_index} is too short in {path}"
                    )
                value_by_name = {
                    property_names[prop_index]: float(parts[prop_index])
                    for prop_index in range(len(vertex_properties))
                }
                rows.append([value_by_name["x"], value_by_name["y"], value_by_name["z"]])
            return np.asarray(rows, dtype=np.float64)

        if format_name not in {"binary_little_endian", "binary_big_endian"}:
            raise RawOccupancyFeatureError(f"Unsupported PLY format {format_name!r} in {path}")

        endian = "<" if format_name == "binary_little_endian" else ">"
        dtype = np.dtype(
            [(name, endian + PLY_SCALAR_DTYPES[property_type]) for name, property_type in vertex_properties]
        )
        data = np.fromfile(handle, dtype=dtype, count=vertex_count)
        if data.shape[0] != vertex_count:
            raise RawOccupancyFeatureError(f"PLY file ended early while reading vertices: {path}")
        return np.column_stack([data["x"], data["y"], data["z"]]).astype(np.float64, copy=False)


def read_obj_vertices(path: Path) -> np.ndarray:
    vertices: list[list[float]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
    if not vertices:
        raise RawOccupancyFeatureError(f"OBJ file contains no vertices: {path}")
    return np.asarray(vertices, dtype=np.float64)


def load_mesh_vertices(path: Path, mesh_cache: dict[Path, np.ndarray]) -> np.ndarray:
    # Cache source mesh vertices by path so static meshes shared across many
    # frames are only parsed once.
    if path in mesh_cache:
        return mesh_cache[path]

    suffix = path.suffix.lower()
    if suffix == ".ply":
        vertices = read_ply_vertices(path)
    elif suffix == ".obj":
        vertices = read_obj_vertices(path)
    else:
        raise RawOccupancyFeatureError(
            f"Unsupported mesh format for raw occupancy baseline: {path}"
        )

    if vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.shape[0] == 0:
        raise RawOccupancyFeatureError(f"Mesh did not yield a valid vertex array: {path}")

    mesh_cache[path] = vertices
    return vertices


def collect_world_vertices_for_frame(
    manifest_path: Path,
    *,
    mesh_cache: dict[Path, np.ndarray],
    frame_id: int,
) -> np.ndarray:
    # Read every mesh referenced by the composed manifest and combine all world-
    # space vertices into one unsegmented geometry sample set for this frame.
    manifest = require_object(load_json(manifest_path), f"composed manifest {manifest_path}")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RawOccupancyFeatureError(f"{manifest_path} must contain a non-empty entries list")

    world_vertex_parts: list[np.ndarray] = []
    for entry_index, entry_value in enumerate(entries):
        entry = require_object(entry_value, f"{manifest_path}.entries[{entry_index}]")
        mesh_path_text = require_non_empty_string(
            entry.get("mesh_path"),
            f"{manifest_path}.entries[{entry_index}].mesh_path",
        )
        mesh_path = resolve_project_path(mesh_path_text)
        if not mesh_path.exists():
            raise RawOccupancyFeatureError(f"Referenced mesh does not exist: {mesh_path}")

        vertices = load_mesh_vertices(mesh_path, mesh_cache).astype(np.float64, copy=True)
        transform = parse_optional_matrix44(
            entry.get("transform"),
            f"{manifest_path}.entries[{entry_index}].transform",
        )
        baked_world_geometry = entry.get("baked_world_geometry") is True

        # Current composed manifests typically point at already world-baked meshes.
        # If an explicit transform is present, apply it. Otherwise require that
        # the mesh is declared world-baked so raw geometry stays correctly placed.
        if transform is not None:
            vertices = apply_transform(vertices, transform)
        elif not baked_world_geometry:
            raise RawOccupancyFeatureError(
                f"Entry {entry.get('id')!r} in frame {frame_id} is not world-baked and has no transform"
            )

        world_vertex_parts.append(vertices)

    if not world_vertex_parts:
        raise RawOccupancyFeatureError(f"No mesh vertices collected for frame {frame_id}")

    all_vertices = np.concatenate(world_vertex_parts, axis=0)
    if all_vertices.shape[0] > MAX_VERTICES_PER_FRAME:
        rng = np.random.default_rng(SUBSAMPLE_SEED + int(frame_id))
        selected = rng.choice(all_vertices.shape[0], size=MAX_VERTICES_PER_FRAME, replace=False)
        all_vertices = all_vertices[np.sort(selected)]
    return all_vertices


def point_distances(points: np.ndarray, point: np.ndarray) -> np.ndarray:
    deltas = points - point[None, :]
    return np.linalg.norm(deltas, axis=1)


def segment_distances(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    # Compute distances to the finite TX-RX segment, not the infinite line, so
    # the resulting occupancy features match corridor-style wireless geometry.
    segment = end - start
    denom = float(np.dot(segment, segment))
    if denom <= 1e-12:
        return point_distances(points, start)
    offsets = points - start[None, :]
    t = np.clip((offsets @ segment) / denom, 0.0, 1.0)
    projection = start[None, :] + t[:, None] * segment[None, :]
    return np.linalg.norm(points - projection, axis=1)


def mean_smallest(values: np.ndarray, k: int) -> float:
    if values.size == 0:
        return 0.0
    count = min(k, int(values.size))
    if count <= 0:
        return 0.0
    smallest = np.partition(values, count - 1)[:count]
    return float(np.mean(smallest))


def build_raw_features(
    *,
    vertices: np.ndarray,
    tx: np.ndarray,
    rx: np.ndarray,
) -> dict[str, float]:
    if vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.shape[0] == 0:
        raise RawOccupancyFeatureError("Raw occupancy feature computation received no vertices")

    # Treat the sampled world-space vertices as an unsegmented occupancy cloud
    # and measure how densely that cloud lies around the finite TX-RX segment.
    link_distances = segment_distances(vertices, tx, rx)
    rx_distances = point_distances(vertices, rx)
    tx_distances = point_distances(vertices, tx)
    total_vertices = float(vertices.shape[0])

    return {
        "raw_tx_rx_distance": float(np.linalg.norm(tx - rx)),
        "raw_vertex_count_near_link_0p25m": int(np.count_nonzero(link_distances <= 0.25)),
        "raw_vertex_count_near_link_0p50m": int(np.count_nonzero(link_distances <= 0.50)),
        "raw_vertex_count_near_link_1p00m": int(np.count_nonzero(link_distances <= 1.00)),
        "raw_min_vertex_dist_to_link": float(np.min(link_distances)),
        "raw_mean_vertex_dist_to_link_k20": mean_smallest(link_distances, 20),
        "raw_mean_vertex_dist_to_link_k50": mean_smallest(link_distances, 50),
        "raw_vertex_count_near_rx_0p50m": int(np.count_nonzero(rx_distances <= 0.50)),
        "raw_vertex_count_near_tx_0p50m": int(np.count_nonzero(tx_distances <= 0.50)),
        "raw_link_corridor_occupancy_ratio_0p50m": float(
            np.count_nonzero(link_distances <= 0.50) / total_vertices
        ),
    }


def write_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    if not rows:
        raise RawOccupancyFeatureError("No raw occupancy rows were produced")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise RawOccupancyFeatureError(f"Config file does not exist: {config_path}")

    experiment = load_experiment_config(config_path)
    output_root = experiment["output_root"]
    features_dir = output_root / "features"
    source_feature_path = features_dir / "object_features_rt_labels.csv"
    manifest_index_path = output_root / "frames" / "composed_manifests" / "composed_manifest_index.csv"
    output_path = features_dir / "raw_occupancy_features_rt_labels.csv"

    source_rows = load_object_feature_rows(source_feature_path, config_path=config_path)
    manifest_by_frame = load_composed_manifest_index(
        manifest_index_path,
        expected_frames=experiment["num_frames"],
    )

    header = list(source_rows[0].keys())
    preserved_columns = preserved_columns_from_header(header)
    for required in ["frame_id", "source_sample_index", "rx_id", "tx_x", "tx_y", "tx_z", "rx_x", "rx_y", "rx_z"]:
        if required not in header:
            raise RawOccupancyFeatureError(
                f"Source feature CSV is missing required column {required!r}: {source_feature_path}"
            )

    unique_frame_ids = sorted({parse_int(row.get("frame_id"), "frame_id") for row in source_rows})
    mesh_cache: dict[Path, np.ndarray] = {}
    frame_vertex_cache: dict[int, np.ndarray] = {}

    for frame_index, frame_id in enumerate(unique_frame_ids, start=1):
        manifest_info = manifest_by_frame.get(frame_id)
        if manifest_info is None:
            raise RawOccupancyFeatureError(f"Frame {frame_id} is missing from composed manifest index")
        print(f"[raw occupancy] loading frame {frame_index}/{len(unique_frame_ids)} frame_id={frame_id}")
        frame_vertex_cache[frame_id] = collect_world_vertices_for_frame(
            manifest_info["manifest_path"],
            mesh_cache=mesh_cache,
            frame_id=frame_id,
        )

    output_rows: list[dict[str, Any]] = []
    total_rows = len(source_rows)
    for row_index, source_row in enumerate(source_rows, start=1):
        frame_id = parse_int(source_row.get("frame_id"), f"row[{row_index}].frame_id")
        source_sample_index = parse_int(
            source_row.get("source_sample_index"),
            f"row[{row_index}].source_sample_index",
        )
        manifest_info = manifest_by_frame.get(frame_id)
        if manifest_info is None:
            raise RawOccupancyFeatureError(f"Frame {frame_id} is missing from composed manifest index")
        if source_sample_index != int(manifest_info["source_sample_index"]):
            raise RawOccupancyFeatureError(
                "source_sample_index mismatch between source feature CSV and composed manifest index "
                f"for frame_id={frame_id}"
            )

        if row_index == 1 or row_index == total_rows or row_index % 50 == 0:
            print(f"[raw occupancy] processing row {row_index}/{total_rows}")

        tx = np.asarray(
            [
                parse_float(source_row.get("tx_x"), f"row[{row_index}].tx_x"),
                parse_float(source_row.get("tx_y"), f"row[{row_index}].tx_y"),
                parse_float(source_row.get("tx_z"), f"row[{row_index}].tx_z"),
            ],
            dtype=np.float64,
        )
        rx = np.asarray(
            [
                parse_float(source_row.get("rx_x"), f"row[{row_index}].rx_x"),
                parse_float(source_row.get("rx_y"), f"row[{row_index}].rx_y"),
                parse_float(source_row.get("rx_z"), f"row[{row_index}].rx_z"),
            ],
            dtype=np.float64,
        )
        # Reuse the cached frame-level vertex cloud for each RX row so the raw
        # baseline stays cheap even when many receivers share the same frame.
        raw_features = build_raw_features(
            vertices=frame_vertex_cache[frame_id],
            tx=tx,
            rx=rx,
        )

        output_row: dict[str, Any] = {column: source_row.get(column, "") for column in preserved_columns}
        output_row.update(raw_features)
        output_rows.append(output_row)

    fieldnames = preserved_columns + RAW_FEATURE_COLUMNS
    write_rows(output_path, output_rows, fieldnames)

    print(f"experiment_name={experiment['experiment_name']}")
    print(f"num_frames={experiment['num_frames']}")
    print(f"row_count={len(output_rows)}")
    print(f"output_csv={output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RawOccupancyFeatureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
