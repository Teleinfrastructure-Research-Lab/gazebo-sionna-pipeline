#!/usr/bin/env python3

"""Join RT labels with object-centric geometry/material feature descriptors.

This experiment helper reads composed frame manifests plus labeled RT rows and
turns them into a flat supervised-learning table. The feature columns are meant
to resemble descriptors that could be derived from object masks/instances,
material tags, and compact scene geometry summaries. The RT columns remain the
supervision targets/metadata, not proactive input features by themselves.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from dynamic_prototype_config import DynamicPrototypeConfigError, load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ObjectFeatureBuildError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build per-row object-aware features joined with RT labels."
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
        raise ObjectFeatureBuildError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ObjectFeatureBuildError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ObjectFeatureBuildError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ObjectFeatureBuildError(f"{label} must be a list")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ObjectFeatureBuildError(f"{label} must be a non-empty string")
    return value.strip()


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ObjectFeatureBuildError(f"{label} must be a positive integer")
    return value


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_experiment_config(path: Path) -> dict[str, Any]:
    # Load only the experiment metadata needed for feature construction:
    # frame count, output root, dynamic models, and the material/semantic groups of interest.
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
    raw_dynamic_models = require_list(
        config.get("dynamic_models"),
        "experiment_config.dynamic_models",
    )
    dynamic_models = [
        require_non_empty_string(item, "experiment_config.dynamic_models[]")
        for item in raw_dynamic_models
    ]
    raw_materials = require_list(
        config.get("materials_of_interest"),
        "experiment_config.materials_of_interest",
    )
    materials = [
        require_non_empty_string(item, "experiment_config.materials_of_interest[]").lower()
        for item in raw_materials
    ]
    raw_semantics = require_list(
        config.get("semantic_classes_of_interest"),
        "experiment_config.semantic_classes_of_interest",
    )
    semantics = [
        require_non_empty_string(item, "experiment_config.semantic_classes_of_interest[]").lower()
        for item in raw_semantics
    ]
    return {
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "output_root": resolve_project_path(output_dir),
        "dynamic_models": dynamic_models,
        "materials_of_interest": materials,
        "semantic_classes_of_interest": semantics,
    }


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_slug(value: str) -> str:
    slug = []
    for char in value.strip().lower():
        if char.isalnum() or char == "_":
            slug.append(char)
        else:
            slug.append("_")
    text = "".join(slug).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or "value"


def load_composed_manifest_index(path: Path, *, expected_frames: int) -> dict[int, dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise ObjectFeatureBuildError(f"Missing composed manifest index CSV: {path}") from exc

    if not rows:
        raise ObjectFeatureBuildError(f"Composed manifest index CSV is empty: {path}")
    if len(rows) != expected_frames:
        raise ObjectFeatureBuildError(
            f"Expected {expected_frames} composed manifest rows, found {len(rows)} in {path}"
        )

    manifest_by_frame: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        frame_id = parse_int(row.get("frame_id"))
        source_sample_index = parse_int(row.get("source_sample_index"))
        manifest_path_text = require_non_empty_string(
            row.get("composed_manifest_path"),
            f"composed_manifest_index[{index}].composed_manifest_path",
        )
        if frame_id is None or frame_id < 0:
            raise ObjectFeatureBuildError(
                f"composed_manifest_index[{index}].frame_id must be a non-negative integer"
            )
        if source_sample_index is None or source_sample_index < 0:
            raise ObjectFeatureBuildError(
                f"composed_manifest_index[{index}].source_sample_index must be a non-negative integer"
            )
        if frame_id in manifest_by_frame:
            raise ObjectFeatureBuildError(f"Duplicate frame_id in composed manifest index: {frame_id}")
        manifest_path = resolve_project_path(manifest_path_text)
        if not manifest_path.exists():
            raise ObjectFeatureBuildError(f"Missing composed manifest: {manifest_path}")
        manifest_by_frame[frame_id] = {
            "frame_id": frame_id,
            "source_sample_index": source_sample_index,
            "manifest_path": manifest_path,
        }
    return manifest_by_frame


def load_rt_label_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise ObjectFeatureBuildError(
            f"Missing labeled RT CSV: {path}. Run "
            f"`python3 rt_out/scripts/exp_build_rt_labels.py --config "
            f"<experiment_config.json>` first."
        ) from exc

    if not rows:
        raise ObjectFeatureBuildError(f"Labeled RT CSV is empty: {path}")

    required_columns = [
        "frame_id",
        "source_sample_index",
        "rx_id",
        "tx_x",
        "tx_y",
        "tx_z",
        "rx_x",
        "rx_y",
        "rx_z",
    ]
    missing = [column for column in required_columns if column not in rows[0]]
    if missing:
        raise ObjectFeatureBuildError(
            "Labeled RT CSV is missing required columns: " + ", ".join(sorted(missing))
        )

    parsed_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        frame_id = parse_int(row.get("frame_id"))
        source_sample_index = parse_int(row.get("source_sample_index"))
        if frame_id is None or frame_id < 0:
            raise ObjectFeatureBuildError(f"rt_labels[{index}].frame_id must be a non-negative integer")
        if source_sample_index is None or source_sample_index < 0:
            raise ObjectFeatureBuildError(
                f"rt_labels[{index}].source_sample_index must be a non-negative integer"
            )
        parsed = dict(row)
        parsed.update(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "tx_x": parse_float(row.get("tx_x")) or 0.0,
                "tx_y": parse_float(row.get("tx_y")) or 0.0,
                "tx_z": parse_float(row.get("tx_z")) or 0.0,
                "rx_x": parse_float(row.get("rx_x")) or 0.0,
                "rx_y": parse_float(row.get("rx_y")) or 0.0,
                "rx_z": parse_float(row.get("rx_z")) or 0.0,
            }
        )
        parsed_rows.append(parsed)
    return parsed_rows


def extract_translation(matrix: Any) -> tuple[float, float, float] | None:
    if not isinstance(matrix, list) or len(matrix) != 4:
        return None
    rows: list[list[float]] = []
    for row in matrix:
        if not isinstance(row, list) or len(row) != 4:
            return None
        parsed_row = [parse_float(value) for value in row]
        if any(value is None for value in parsed_row):
            return None
        rows.append([float(value) for value in parsed_row if value is not None])
    return rows[0][3], rows[1][3], rows[2][3]


def centroid_from_bounds(bounds_min: Any, bounds_max: Any) -> tuple[float, float, float] | None:
    if not isinstance(bounds_min, list) or not isinstance(bounds_max, list):
        return None
    if len(bounds_min) != 3 or len(bounds_max) != 3:
        return None
    parsed_min = [parse_float(value) for value in bounds_min]
    parsed_max = [parse_float(value) for value in bounds_max]
    if any(value is None for value in parsed_min + parsed_max):
        return None
    mins = [float(value) for value in parsed_min if value is not None]
    maxs = [float(value) for value in parsed_max if value is not None]
    return tuple((mins[index] + maxs[index]) / 2.0 for index in range(3))


def volume_from_bounds(bounds_min: Any, bounds_max: Any) -> float | None:
    if not isinstance(bounds_min, list) or not isinstance(bounds_max, list):
        return None
    if len(bounds_min) != 3 or len(bounds_max) != 3:
        return None
    parsed_min = [parse_float(value) for value in bounds_min]
    parsed_max = [parse_float(value) for value in bounds_max]
    if any(value is None for value in parsed_min + parsed_max):
        return None
    mins = [float(value) for value in parsed_min if value is not None]
    maxs = [float(value) for value in parsed_max if value is not None]
    extents = [max(0.0, maxs[index] - mins[index]) for index in range(3)]
    return extents[0] * extents[1] * extents[2]


def volume_from_static_member(member: dict[str, Any]) -> float | None:
    geometry_type = str(member.get("geometry_type") or "").strip().lower()
    if geometry_type == "box":
        size = member.get("size")
        if isinstance(size, list) and len(size) == 3:
            parsed = [parse_float(value) for value in size]
            if all(value is not None for value in parsed):
                dims = [max(0.0, float(value)) for value in parsed if value is not None]
                return dims[0] * dims[1] * dims[2]
        return None
    if geometry_type == "cylinder":
        radius = parse_float(member.get("radius"))
        length = parse_float(member.get("length"))
        if radius is None or length is None:
            return None
        return math.pi * max(0.0, radius) * max(0.0, radius) * max(0.0, length)
    if geometry_type == "sphere":
        radius = parse_float(member.get("radius"))
        if radius is None:
            return None
        return (4.0 / 3.0) * math.pi * max(0.0, radius) ** 3
    return None


def infer_semantic_class(
    *,
    model_name: str,
    link_name: str,
    visual_name: str,
    object_id: str,
    material_class: str | None,
    dynamic_models: set[str],
    allowed_semantics: set[str],
) -> str | None:
    model_lower = model_name.strip().lower()
    text = " | ".join([model_name, link_name, visual_name, object_id]).lower()
    padded_text = f" {text.replace('|', ' ')} "

    semantic: str | None = None
    if model_name in dynamic_models:
        semantic = "robot_arm"
    elif model_lower == "x500" or padded_text.startswith(" x500 "):
        semantic = "drone"
    elif "picking_shelves" in text or " shelf" in padded_text or "shelf_" in text:
        semantic = "shelf"
    elif model_lower in {"desk", "desk_0", "desk_1", "coffeetable"} or "desk" in text or "table" in text:
        semantic = "desk"
    elif "factory_door" in text or " door" in padded_text or "_door" in text or "door_" in text:
        semantic = "door"
    elif "window" in text or (material_class == "glass" and "glass" in text):
        semantic = "window"
    elif "clutteringc" in text or "box" in text or "crate" in text:
        semantic = "box"
    elif "officechair" in text or "chair" in text or "sofa" in text:
        semantic = "chair"
    elif model_lower in {"naoh25v40", "cerberus_anymal_c_sensor_config_1"} or "cerberus_anymal" in text or "naoh25v40" in text:
        semantic = "robot"
    elif "trashbin" in text or " bin" in padded_text or "_bin" in text:
        semantic = "bin"
    elif model_lower == "monitorandkeyboard" or "monitor" in text or "keyboard" in text or "laptop" in text:
        semantic = "laptop"

    if semantic is None:
        return None
    if semantic not in allowed_semantics:
        return None
    return semantic


def build_frame_objects(
    manifest_path: Path,
    *,
    dynamic_models: set[str],
    dynamic_materials: dict[str, str],
    allowed_semantics: set[str],
) -> list[dict[str, Any]]:
    manifest = require_object(load_json(manifest_path), f"composed manifest {manifest_path}")
    entries = require_list(manifest.get("entries"), f"{manifest_path}.entries")
    objects: list[dict[str, Any]] = []

    for entry_index, entry_value in enumerate(entries):
        entry = require_object(entry_value, f"{manifest_path}.entries[{entry_index}]")
        static_record = entry.get("static_record")
        if isinstance(static_record, dict):
            members = require_list(
                static_record.get("members", []),
                f"{manifest_path}.entries[{entry_index}].static_record.members",
            )
            for member_index, member_value in enumerate(members):
                member = require_object(
                    member_value,
                    f"{manifest_path}.entries[{entry_index}].static_record.members[{member_index}]",
                )
                model_name = str(member.get("model_name") or "")
                link_name = str(member.get("link_name") or "")
                visual_name = str(member.get("visual_name") or "")
                object_id = str(member.get("id") or "")
                material_class = str(member.get("material_class") or "").strip().lower() or None
                centroid = extract_translation(member.get("to_world"))
                volume = volume_from_static_member(member)
                semantic = infer_semantic_class(
                    model_name=model_name,
                    link_name=link_name,
                    visual_name=visual_name,
                    object_id=object_id,
                    material_class=material_class,
                    dynamic_models=dynamic_models,
                    allowed_semantics=allowed_semantics,
                )
                objects.append(
                    {
                        "object_id": object_id,
                        "model_name": model_name,
                        "material_class": material_class,
                        "semantic_class": semantic,
                        "is_dynamic": False,
                        "dynamic_model": None,
                        "centroid": centroid,
                        "volume": volume,
                        "vertex_count": None,
                        "face_count": None,
                    }
                )
            continue

        model_name = str(entry.get("model_name") or "")
        if model_name not in dynamic_models:
            continue
        link_name = str(entry.get("link_name") or "")
        visual_name = str(entry.get("visual_name") or "")
        object_id = str(entry.get("id") or "")
        material_class = str(entry.get("material_label") or "").strip().lower() or None
        if material_class is None:
            material_class = dynamic_materials.get(model_name)
        centroid = centroid_from_bounds(entry.get("bounds_min"), entry.get("bounds_max"))
        volume = volume_from_bounds(entry.get("bounds_min"), entry.get("bounds_max"))
        semantic = infer_semantic_class(
            model_name=model_name,
            link_name=link_name,
            visual_name=visual_name,
            object_id=object_id,
            material_class=material_class,
            dynamic_models=dynamic_models,
            allowed_semantics=allowed_semantics,
        )
        objects.append(
            {
                "object_id": object_id,
                "model_name": model_name,
                "material_class": material_class,
                "semantic_class": semantic,
                "is_dynamic": True,
                "dynamic_model": model_name,
                "centroid": centroid,
                "volume": volume,
                "vertex_count": parse_float(entry.get("mesh_vertex_count")),
                "face_count": parse_float(entry.get("mesh_face_count")),
            }
        )

    if not objects:
        raise ObjectFeatureBuildError(f"No objects could be extracted from manifest: {manifest_path}")
    return objects


def distance(point_a: tuple[float, float, float], point_b: tuple[float, float, float]) -> float:
    return math.sqrt(
        (point_a[0] - point_b[0]) ** 2
        + (point_a[1] - point_b[1]) ** 2
        + (point_a[2] - point_b[2]) ** 2
    )


def point_to_segment_distance(
    point: tuple[float, float, float],
    segment_start: tuple[float, float, float],
    segment_end: tuple[float, float, float],
) -> float:
    vx = segment_end[0] - segment_start[0]
    vy = segment_end[1] - segment_start[1]
    vz = segment_end[2] - segment_start[2]
    wx = point[0] - segment_start[0]
    wy = point[1] - segment_start[1]
    wz = point[2] - segment_start[2]
    denom = vx * vx + vy * vy + vz * vz
    if denom <= 1e-12:
        return distance(point, segment_start)
    t = max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / denom))
    projection = (
        segment_start[0] + t * vx,
        segment_start[1] + t * vy,
        segment_start[2] + t * vz,
    )
    return distance(point, projection)


def safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def safe_min(values: list[float]) -> float:
    return min(values) if values else 0.0


def safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = safe_mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(max(0.0, variance))


def add_subset_features(
    destination: dict[str, Any],
    *,
    prefix: str,
    objects: list[dict[str, Any]],
    tx: tuple[float, float, float],
    rx: tuple[float, float, float],
) -> None:
    # Collapse one subset of objects into compact statistics rather than
    # carrying per-instance rows into the classifier. This is the bridge from
    # object-level scene understanding to a flat tabular learning baseline.
    centroid_objects = [
        obj for obj in objects if isinstance(obj.get("centroid"), tuple) and len(obj["centroid"]) == 3
    ]
    volumes = [float(obj["volume"]) for obj in objects if obj.get("volume") is not None]
    vertex_counts = [float(obj["vertex_count"]) for obj in objects if obj.get("vertex_count") is not None]
    face_counts = [float(obj["face_count"]) for obj in objects if obj.get("face_count") is not None]
    rx_distances = [distance(obj["centroid"], rx) for obj in centroid_objects]
    tx_distances = [distance(obj["centroid"], tx) for obj in centroid_objects]
    line_distances = [point_to_segment_distance(obj["centroid"], tx, rx) for obj in centroid_objects]
    centroid_x = [obj["centroid"][0] for obj in centroid_objects]
    centroid_y = [obj["centroid"][1] for obj in centroid_objects]
    centroid_z = [obj["centroid"][2] for obj in centroid_objects]

    destination[f"{prefix}_count"] = len(objects)
    destination[f"{prefix}_centroid_count"] = len(centroid_objects)
    destination[f"{prefix}_rx_dist_mean"] = safe_mean(rx_distances)
    destination[f"{prefix}_rx_dist_min"] = safe_min(rx_distances)
    destination[f"{prefix}_tx_dist_mean"] = safe_mean(tx_distances)
    destination[f"{prefix}_tx_dist_min"] = safe_min(tx_distances)
    destination[f"{prefix}_line_dist_mean"] = safe_mean(line_distances)
    destination[f"{prefix}_line_dist_min"] = safe_min(line_distances)
    destination[f"{prefix}_volume_sum"] = sum(volumes)
    destination[f"{prefix}_volume_mean"] = safe_mean(volumes)
    destination[f"{prefix}_vertex_sum"] = sum(vertex_counts)
    destination[f"{prefix}_face_sum"] = sum(face_counts)
    destination[f"{prefix}_centroid_x_mean"] = safe_mean(centroid_x)
    destination[f"{prefix}_centroid_y_mean"] = safe_mean(centroid_y)
    destination[f"{prefix}_centroid_z_mean"] = safe_mean(centroid_z)
    destination[f"{prefix}_centroid_x_std"] = safe_std(centroid_x)
    destination[f"{prefix}_centroid_y_std"] = safe_std(centroid_y)
    destination[f"{prefix}_centroid_z_std"] = safe_std(centroid_z)


def build_row_features(
    *,
    objects: list[dict[str, Any]],
    tx: tuple[float, float, float],
    rx: tuple[float, float, float],
    materials_of_interest: list[str],
    semantics_of_interest: list[str],
    dynamic_models: list[str],
) -> dict[str, Any]:
    # Start with pure RX/TX geometry, then add increasingly structured object,
    # material, semantic, and dynamic-model-specific aggregates.
    features: dict[str, Any] = {}
    features["geom_rx_x"] = rx[0]
    features["geom_rx_y"] = rx[1]
    features["geom_rx_z"] = rx[2]
    features["geom_tx_rx_distance"] = distance(tx, rx)

    static_objects = [obj for obj in objects if not obj["is_dynamic"]]
    dynamic_objects = [obj for obj in objects if obj["is_dynamic"]]
    add_subset_features(features, prefix="geom_all", objects=objects, tx=tx, rx=rx)
    add_subset_features(features, prefix="geom_static", objects=static_objects, tx=tx, rx=rx)
    add_subset_features(features, prefix="geom_dynamic", objects=dynamic_objects, tx=tx, rx=rx)

    for material_name in materials_of_interest:
        material_slug = safe_slug(material_name)
        subset = [obj for obj in objects if obj.get("material_class") == material_name]
        add_subset_features(features, prefix=f"mat_{material_slug}", objects=subset, tx=tx, rx=rx)
        features[f"mat_{material_slug}_dynamic_count"] = sum(1 for obj in subset if obj["is_dynamic"])
        features[f"mat_{material_slug}_static_count"] = sum(1 for obj in subset if not obj["is_dynamic"])

    for semantic_name in semantics_of_interest:
        semantic_slug = safe_slug(semantic_name)
        subset = [obj for obj in objects if obj.get("semantic_class") == semantic_name]
        add_subset_features(features, prefix=f"sem_{semantic_slug}", objects=subset, tx=tx, rx=rx)
        features[f"sem_{semantic_slug}_dynamic_count"] = sum(1 for obj in subset if obj["is_dynamic"])
        features[f"sem_{semantic_slug}_static_count"] = sum(1 for obj in subset if not obj["is_dynamic"])

    for model_name in dynamic_models:
        model_slug = safe_slug(model_name)
        subset = [obj for obj in dynamic_objects if obj.get("dynamic_model") == model_name]
        add_subset_features(features, prefix=f"obj_{model_slug}", objects=subset, tx=tx, rx=rx)

    return features


def write_feature_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ObjectFeatureBuildError("No feature rows were produced")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    config = load_experiment_config(args.config)

    try:
        # Reuse the validated dynamic prototype config so dynamic model-specific
        # assumptions like forced materials stay consistent with XML generation.
        dynamic_config = load_dynamic_prototype_config()
    except DynamicPrototypeConfigError as exc:
        raise ObjectFeatureBuildError(str(exc)) from exc

    dynamic_materials: dict[str, str] = {}
    for model_name in config["dynamic_models"]:
        model_config = dynamic_config["dynamic_models"].get(model_name)
        if model_config is None:
            raise ObjectFeatureBuildError(
                f"Dynamic model {model_name!r} is missing from dynamic prototype config"
            )
        dynamic_materials[model_name] = str(model_config["forced_material"]).strip().lower()

    output_root: Path = config["output_root"]
    composed_manifest_index_path = output_root / "frames" / "composed_manifests" / "composed_manifest_index.csv"
    # Keep the historical RT-label filename for compatibility with the existing
    # experiment wrappers even when the experiment uses 200 sampled frames.
    rt_labels_path = output_root / "rt_results" / "rt_100frames_multi_rx_labeled.csv"
    output_path = output_root / "features" / "object_features_rt_labels.csv"

    # Load the composed-scene geometry index and the already-labeled RT rows,
    # then join them by frame_id/source_sample_index.
    manifest_by_frame = load_composed_manifest_index(
        composed_manifest_index_path,
        expected_frames=config["num_frames"],
    )
    rt_rows = load_rt_label_rows(rt_labels_path)

    frame_ids_needed = sorted({int(row["frame_id"]) for row in rt_rows})
    frame_objects: dict[int, list[dict[str, Any]]] = {}
    for frame_id in frame_ids_needed:
        # Build object descriptors once per frame so multiple RX rows for the
        # same frame can reuse the same object-level geometry statistics.
        manifest_info = manifest_by_frame.get(frame_id)
        if manifest_info is None:
            raise ObjectFeatureBuildError(f"Frame {frame_id} is missing from composed manifest index")
        frame_objects[frame_id] = build_frame_objects(
            manifest_info["manifest_path"],
            dynamic_models=set(config["dynamic_models"]),
            dynamic_materials=dynamic_materials,
            allowed_semantics=set(config["semantic_classes_of_interest"]),
        )

    enriched_rows: list[dict[str, Any]] = []
    feature_columns: list[str] | None = None
    for row in rt_rows:
        # Add RX/TX-aware object features to every labeled RT row so the result
        # becomes a flat supervised-learning table.
        frame_id = int(row["frame_id"])
        manifest_info = manifest_by_frame[frame_id]
        if int(row["source_sample_index"]) != int(manifest_info["source_sample_index"]):
            raise ObjectFeatureBuildError(
                "source_sample_index mismatch between RT labels and composed manifest index "
                f"for frame_id={frame_id}"
            )

        tx = (float(row["tx_x"]), float(row["tx_y"]), float(row["tx_z"]))
        rx = (float(row["rx_x"]), float(row["rx_y"]), float(row["rx_z"]))
        features = build_row_features(
            objects=frame_objects[frame_id],
            tx=tx,
            rx=rx,
            materials_of_interest=config["materials_of_interest"],
            semantics_of_interest=config["semantic_classes_of_interest"],
            dynamic_models=config["dynamic_models"],
        )
        if feature_columns is None:
            feature_columns = sorted(features)

        enriched = dict(row)
        for key in feature_columns:
            enriched[key] = features[key]
        enriched_rows.append(enriched)

    if feature_columns is None:
        raise ObjectFeatureBuildError("No feature columns were generated")

    # Persist the joined table once so later ablation runs do not need to reopen
    # manifests or recompute object distances repeatedly.
    write_feature_rows(output_path, enriched_rows)

    print(f"experiment_name={config['experiment_name']}")
    print(f"num_frames_with_labels={len(frame_ids_needed)}")
    print(f"num_rows={len(enriched_rows)}")
    print(f"num_feature_columns={len(feature_columns)}")
    print(f"output_csv={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
