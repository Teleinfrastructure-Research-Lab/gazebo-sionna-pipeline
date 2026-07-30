#!/usr/bin/env python3
"""Build a lightweight panoptic perception dataset index linked to RT rows."""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


INDEX_VERSION = "0.1"
REQUIRED_PANOPTIC_KEYS = (
    "panoptic_labels_rgb_path",
    "semantic_decoded_path",
    "gazebo_instance_count_path",
)
OPTIONAL_PANOPTIC_KEYS = ("colored_map_path", "metadata_path")
CSV_FIELDNAMES = [
    "index_version",
    "experiment_name",
    "source_experiment",
    "selected_frame_id",
    "selected_frame_idx",
    "source_frame_id",
    "source_frame_index",
    "source_sample_index",
    "camera_id",
    "camera_width",
    "camera_height",
    "camera_fov",
    "camera_near",
    "camera_far",
    "camera_pose_x",
    "camera_pose_y",
    "camera_pose_z",
    "camera_roll",
    "camera_pitch",
    "camera_yaw",
    "panoptic_labels_rgb_path",
    "semantic_decoded_path",
    "gazebo_instance_count_path",
    "colored_map_path",
    "metadata_path",
    "has_panoptic_labels_rgb",
    "has_semantic_decoded",
    "has_gazebo_instance_count",
    "has_colored_map",
    "has_metadata",
    "labeled_pcl_path",
    "has_labeled_pcl",
    "labeled_pcl_validation_status",
    "labeled_pcl_point_count",
    "labeled_pcl_zero_label_point_count",
    "labeled_pcl_unknown_label_point_count",
    "labeled_pcl_unique_class_label_count",
    "labeled_pcl_unique_instance_id_count",
    "labeled_pcl_status",
    "labeled_pcl_notes",
    "rt_row_count",
    "rt_rx_ids",
    "rt_frame_key_used",
    "rt_rows_json",
    "label_row_count",
    "label_targets_json",
    "label_frame_key_used",
    "instance_registry_path",
    "semantic_label_map_path",
    "validation_status",
    "validation_notes",
]
RT_FRAME_KEY_CANDIDATES = [
    ("frame_id", ("source_frame_id", "source_record_index", "selected_frame_id")),
    ("source_sample_index", ("source_sample_index",)),
]
LABEL_FRAME_KEY_CANDIDATES = [
    ("frame_id", ("source_frame_id", "source_record_index", "selected_frame_id")),
    ("frame_id_t", ("source_frame_id", "source_record_index", "selected_frame_id")),
    ("source_sample_index", ("source_sample_index",)),
    ("source_sample_index_t", ("source_sample_index",)),
]
RT_COMPACT_COLUMNS = (
    "frame_id",
    "source_sample_index",
    "rx_id",
    "tx_id",
    "tx_name",
    "num_paths",
    "tau_min",
    "tau_max",
    "delay_spread",
    "path_gain_sum",
    "path_gain_db",
    "rx_power_dbm",
    "sanity_ok",
    "error_message",
    "xml_path",
)
LABEL_TARGET_COLUMNS = (
    "frame_id",
    "frame_id_t",
    "frame_id_next",
    "source_sample_index",
    "source_sample_index_t",
    "source_sample_index_next",
    "rx_id",
    "delta_num_paths",
    "delta_delay_spread",
    "delta_rx_power_db",
    "y_path_change",
    "y_path_drop",
    "y_rx_power_drop_0p5db",
    "y_rx_power_drop_1db",
    "y_rx_power_drop_2db",
    "y_delay_spread_increase",
    "y_adaptation_trigger_1db",
    "y_adaptation_trigger_2db",
)


class IndexBuildError(RuntimeError):
    """Raised when index building cannot proceed safely."""


@dataclass
class LinkedRows:
    rows: list[dict[str, Any]]
    key_used: str | None


@dataclass
class SourceExperimentHandle:
    experiment_path: Path
    project_root: Path
    local_root: Path | None
    archive_path: Path | None
    archive_prefix: str | None

    @classmethod
    def from_path(cls, experiment_path: Path, project_root: Path) -> "SourceExperimentHandle":
        local_root = experiment_path if experiment_path.is_dir() else None
        archive_path: Path | None = None
        archive_prefix: str | None = None

        archive_candidates = [
            experiment_path.parent / "semantic_ablation.zip",
            experiment_path.parent / f"{experiment_path.name}.zip",
        ]
        if local_root is None:
            for archive_candidate in archive_candidates:
                if not archive_candidate.is_file():
                    continue
                prefix = f"{experiment_path.name}/"
                try:
                    with zipfile.ZipFile(archive_candidate) as zf:
                        if any(name.startswith(prefix) for name in zf.namelist()):
                            archive_path = archive_candidate
                            archive_prefix = prefix
                            break
                except zipfile.BadZipFile as exc:
                    raise IndexBuildError(
                        f"Source experiment archive is not a valid ZIP: {archive_candidate}"
                    ) from exc

        return cls(
            experiment_path=experiment_path,
            project_root=project_root,
            local_root=local_root,
            archive_path=archive_path,
            archive_prefix=archive_prefix,
        )

    @property
    def mode(self) -> str:
        if self.local_root is not None:
            return "directory"
        if self.archive_path is not None:
            return "zip"
        return "missing"

    def require_available(self) -> None:
        if self.mode == "missing":
            raise IndexBuildError(
                "Source experiment is unavailable as both a directory and known ZIP archive: "
                f"{self.experiment_path}"
            )

    def _archive_member(self, relative_path: str) -> str:
        if self.archive_prefix is None:
            raise IndexBuildError("Archive prefix is not configured.")
        return f"{self.archive_prefix}{relative_path}"

    def exists(self, relative_path: str) -> bool:
        if self.local_root is not None:
            return (self.local_root / relative_path).is_file()
        if self.archive_path is None:
            return False
        member = self._archive_member(relative_path)
        with zipfile.ZipFile(self.archive_path) as zf:
            try:
                zf.getinfo(member)
                return True
            except KeyError:
                return False

    def read_text(self, relative_path: str) -> str:
        if self.local_root is not None:
            path = self.local_root / relative_path
            if not path.is_file():
                raise IndexBuildError(f"Missing source experiment file: {path}")
            return path.read_text(encoding="utf-8")
        if self.archive_path is None:
            raise IndexBuildError(
                f"Missing source experiment file and no archive fallback is available: {relative_path}"
            )
        member = self._archive_member(relative_path)
        try:
            with zipfile.ZipFile(self.archive_path) as zf:
                with zf.open(member, "r") as handle:
                    return handle.read().decode("utf-8")
        except KeyError as exc:
            raise IndexBuildError(
                f"Missing source experiment archive member: {member} in {self.archive_path}"
            ) from exc

    def list_csv_members(self) -> list[str]:
        if self.local_root is not None:
            return [
                str(path.relative_to(self.local_root))
                for path in sorted(self.local_root.rglob("*.csv"))
            ]
        if self.archive_path is None or self.archive_prefix is None:
            return []
        with zipfile.ZipFile(self.archive_path) as zf:
            return sorted(
                name[len(self.archive_prefix):]
                for name in zf.namelist()
                if name.startswith(self.archive_prefix) and name.lower().endswith(".csv")
            )

    def relpath_for_output(self, relative_path: str) -> str:
        if self.local_root is not None:
            return project_rel(self.local_root / relative_path, self.project_root)
        if self.archive_path is not None:
            return f"{project_rel(self.archive_path, self.project_root)}::{self._archive_member(relative_path)}"
        return relative_path


def parse_args() -> argparse.Namespace:
    default_config = Path("rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/perception_dataset_config.json")
    parser = argparse.ArgumentParser(
        description="Build a lightweight dataset index linking panoptic perception samples to RT outputs."
    )
    parser.add_argument("--config", type=Path, required=True, help="Perception dataset config JSON path.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional override for output directory. Defaults to <experiment_root>/dataset_index.",
    )
    parser.add_argument(
        "--source-experiment",
        type=Path,
        default=None,
        help="Optional override for the source RT experiment directory.",
    )
    parser.add_argument("--rt-csv", type=Path, default=None, help="Optional explicit RT CSV path.")
    parser.add_argument("--labels-csv", type=Path, default=None, help="Optional explicit labels CSV path.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs.")
    parser.add_argument("--strict", action="store_true", help="Treat missing expected files or RT links as errors.")
    parser.add_argument("--pretty-json", action="store_true", help="Write indented JSON outputs.")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional debug limit applied after candidate frame-camera rows are built.",
    )
    parser.set_defaults(config=default_config)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def resolve_project_root(config_path: Path) -> Path:
    config_resolved = config_path.resolve()
    for ancestor in [config_resolved.parent, *config_resolved.parents]:
        if (ancestor / "rt_out").is_dir():
            return ancestor
    cwd = Path.cwd().resolve()
    for ancestor in [cwd, *cwd.parents]:
        if (ancestor / "rt_out").is_dir():
            return ancestor
    raise IndexBuildError(f"Could not resolve project root from config path: {config_path}")


def load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise IndexBuildError(f"Missing {label}: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise IndexBuildError(f"Failed to parse {label} JSON at {path}: {exc}") from exc


def load_optional_json(path: Path, label: str) -> Any | None:
    if not path.is_file():
        return None
    return load_json(path, label)


def write_json(path: Path, payload: Any, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if pretty:
            json.dump(payload, handle, indent=2, sort_keys=False)
        else:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=False)
        handle.write("\n")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def project_rel(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root))
    except ValueError:
        return str(path)


def normalize_scalar(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    return value


def json_cell(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=False)


def ensure_output_paths(paths: Iterable[Path], force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise IndexBuildError(
            f"Output file(s) already exist. Use --force to overwrite: {joined}"
        )


def get_first_present(record: dict[str, Any], candidate_keys: Iterable[str]) -> Any:
    for key in candidate_keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def normalize_frame_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.12g}"
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        return text
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.12g}"


def normalize_csv_rows(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if key is None:
                continue
            normalized[key] = value.strip() if isinstance(value, str) else value
        rows.append(normalized)
    return rows


def load_optional_csv_rows(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        return normalize_csv_rows(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IndexBuildError(f"Failed to read {label} at {path}: {exc}") from exc


def discover_csv_path(
    explicit_path: Path | None,
    source_handle: SourceExperimentHandle,
    exact_candidates: Iterable[str],
    discovery_tokens: Iterable[str],
) -> tuple[str | None, str | None]:
    if explicit_path is not None:
        return str(explicit_path), "explicit"

    for candidate in exact_candidates:
        if source_handle.exists(candidate):
            return candidate, source_handle.mode

    csv_members = source_handle.list_csv_members()
    lowered_tokens = [token.lower() for token in discovery_tokens]
    for member in csv_members:
        lowered = member.lower()
        if all(token in lowered for token in lowered_tokens):
            return member, source_handle.mode
    return None, None


def load_csv_records(
    source_handle: SourceExperimentHandle,
    csv_path_arg: str,
    origin: str,
) -> tuple[list[dict[str, Any]], str]:
    if origin == "explicit":
        path = Path(csv_path_arg)
        if not path.is_file():
            raise IndexBuildError(f"Missing explicit CSV path: {path}")
        return normalize_csv_rows(path.read_text(encoding="utf-8")), str(path)
    return normalize_csv_rows(source_handle.read_text(csv_path_arg)), source_handle.relpath_for_output(csv_path_arg)


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def resolve_path_text(path_value: Any, project_root: Path) -> Path | None:
    if path_value in (None, ""):
        return None
    candidate = Path(str(path_value))
    return candidate if candidate.is_absolute() else project_root / candidate


def normalize_output_path(path_value: Any, project_root: Path) -> str | None:
    resolved = resolve_path_text(path_value, project_root)
    if resolved is None:
        return None
    return project_rel(resolved, project_root)


def normalize_selected_frames(payload: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise IndexBuildError(f"Selected frames JSON must be an object: {path}")
    frames = payload.get("selected_frames")
    if not isinstance(frames, list):
        raise IndexBuildError(f"Selected frames JSON is missing 'selected_frames': {path}")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(frames):
        if not isinstance(item, dict):
            raise IndexBuildError(f"Selected frame record {index} is not an object.")
        normalized.append(item)
    return normalized


def load_camera_map(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise IndexBuildError("camera_rig.json must be a JSON object.")
    cameras = payload.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        raise IndexBuildError("camera_rig.json must contain a non-empty 'cameras' list.")
    camera_map: dict[str, dict[str, Any]] = {}
    for index, camera in enumerate(cameras):
        if not isinstance(camera, dict):
            raise IndexBuildError(f"Camera record {index} is not an object.")
        camera_id = camera.get("camera_id")
        if not isinstance(camera_id, str) or not camera_id.strip():
            raise IndexBuildError(f"Camera record {index} is missing a valid camera_id.")
        camera_map[camera_id] = camera
    return camera_map


def extract_camera_fields(camera: dict[str, Any]) -> dict[str, Any]:
    pose = camera.get("pose_xyz_rpy")
    pose_values = list(pose) if isinstance(pose, list) else []
    while len(pose_values) < 6:
        pose_values.append(None)
    return {
        "camera_width": camera.get("width"),
        "camera_height": camera.get("height"),
        "camera_fov": camera.get("horizontal_fov", camera.get("fov")),
        "camera_near": camera.get("near_clip", camera.get("near")),
        "camera_far": camera.get("far_clip", camera.get("far")),
        "camera_pose_x": pose_values[0],
        "camera_pose_y": pose_values[1],
        "camera_pose_z": pose_values[2],
        "camera_roll": pose_values[3],
        "camera_pitch": pose_values[4],
        "camera_yaw": pose_values[5],
    }


def build_panoptic_lookup(panoptic_root: Path) -> dict[str, dict[str, dict[str, str]]]:
    category_map = {
        "labels_maps_rgb": "panoptic_labels_rgb_path",
        "semantic_decoded": "semantic_decoded_path",
        "gazebo_instance_count": "gazebo_instance_count_path",
        "colored_maps": "colored_map_path",
        "metadata": "metadata_path",
    }
    lookup: dict[str, dict[str, dict[str, str]]] = {}
    if not panoptic_root.is_dir():
        return lookup

    for camera_dir in sorted(path for path in panoptic_root.iterdir() if path.is_dir()):
        camera_lookup: dict[str, dict[str, str]] = {}
        for subdir in sorted(path for path in camera_dir.iterdir() if path.is_dir()):
            row_key = category_map.get(subdir.name)
            if row_key is None:
                continue
            for file_path in sorted(path for path in subdir.iterdir() if path.is_file()):
                stem = normalize_frame_key(file_path.stem)
                if stem is None:
                    continue
                camera_lookup.setdefault(stem, {})[row_key] = str(file_path)
        lookup[camera_dir.name] = camera_lookup
    return lookup


def build_labeled_pcl_lookup(
    labeled_rows: list[dict[str, Any]],
    project_root: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in labeled_rows:
        camera_id = str(row.get("camera_id") or "").strip()
        selected_frame_id = normalize_frame_key(row.get("selected_frame_id"))
        if not camera_id or selected_frame_id is None:
            continue
        output_path = normalize_output_path(row.get("output_labeled_pcl_path"), project_root)
        resolved_output_path = resolve_path_text(row.get("output_labeled_pcl_path"), project_root)
        lookup[(camera_id, selected_frame_id)] = {
            "camera_id": camera_id,
            "selected_frame_id": selected_frame_id,
            "pcl_path": output_path,
            "pcl_exists": resolved_output_path.is_file() if resolved_output_path is not None else False,
            "point_count": parse_int(row.get("point_count")),
            "zero_label_point_count": parse_int(row.get("zero_label_point_count")),
            "unknown_label_point_count": parse_int(row.get("unknown_label_point_count")),
            "unique_class_label_count": parse_int(row.get("unique_class_label_count")),
            "unique_instance_id_count": parse_int(row.get("unique_instance_id_count")),
            "status": row.get("status") or None,
            "notes": row.get("notes") or None,
        }
    return lookup


def build_labeled_pcl_invalid_lookup(
    invalid_rows: list[dict[str, Any]],
    project_root: Path,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in invalid_rows:
        camera_id = str(row.get("camera_id") or "").strip()
        selected_frame_id = normalize_frame_key(row.get("selected_frame_id"))
        if not camera_id or selected_frame_id is None:
            continue
        lookup.setdefault((camera_id, selected_frame_id), []).append(
            {
                "issue": row.get("issue") or None,
                "output_labeled_pcl_path": normalize_output_path(
                    row.get("output_labeled_pcl_path"),
                    project_root,
                ),
                "point_count": parse_int(row.get("point_count")),
            }
        )
    return lookup


def find_matching_rows(selected_record: dict[str, Any], rows: list[dict[str, Any]], candidates: list[tuple[str, tuple[str, ...]]]) -> LinkedRows:
    for row_key, selected_keys in candidates:
        expected_value = get_first_present(selected_record, selected_keys)
        normalized_value = normalize_frame_key(expected_value)
        if normalized_value is None:
            continue
        matched = [
            row for row in rows
            if normalize_frame_key(row.get(row_key)) == normalized_value
        ]
        if matched:
            return LinkedRows(rows=matched, key_used=row_key)
    return LinkedRows(rows=[], key_used=None)


def compact_row(row: dict[str, Any], allowed_columns: Iterable[str], project_root: Path) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for column in allowed_columns:
        if column not in row or row[column] in (None, ""):
            continue
        value: Any = row[column]
        if column.endswith("_path") and isinstance(value, str):
            candidate_path = Path(value)
            if candidate_path.is_absolute():
                value = project_rel(candidate_path, project_root)
        compact[column] = normalize_scalar(value)
    return compact


def dedupe_rx_ids(rows: list[dict[str, Any]]) -> list[str]:
    rx_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        rx_id = row.get("rx_id")
        if rx_id in (None, ""):
            continue
        rx_text = str(rx_id)
        if rx_text not in seen:
            seen.add(rx_text)
            rx_ids.append(rx_text)
    return rx_ids


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def build_row(
    *,
    experiment_name: str,
    source_experiment: str,
    selected_frame_idx: int,
    selected_record: dict[str, Any],
    camera_id: str,
    camera: dict[str, Any],
    panoptic_lookup: dict[str, dict[str, dict[str, str]]],
    labeled_pcl_lookup: dict[tuple[str, str], dict[str, Any]],
    labeled_pcl_invalid_lookup: dict[tuple[str, str], list[dict[str, Any]]],
    rt_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]] | None,
    project_root: Path,
    instance_registry_path: Path,
    semantic_label_map_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    selected_frame_id = get_first_present(
        selected_record,
        ("selected_frame_id", "perception_frame_id", "frame_id"),
    )
    if selected_frame_id is None:
        selected_frame_id = selected_frame_idx
    source_frame_id = get_first_present(selected_record, ("source_frame_id", "frame_id"))
    source_frame_index = get_first_present(selected_record, ("source_frame_index", "source_record_index", "source_record_idx"))
    source_sample_index = get_first_present(selected_record, ("source_sample_index", "sample_index"))

    panoptic_key = normalize_frame_key(selected_frame_id)
    file_bundle = panoptic_lookup.get(camera_id, {}).get(panoptic_key or "", {})
    resolved_files = {
        "panoptic_labels_rgb_path": project_rel(Path(file_bundle["panoptic_labels_rgb_path"]), project_root)
        if "panoptic_labels_rgb_path" in file_bundle else None,
        "semantic_decoded_path": project_rel(Path(file_bundle["semantic_decoded_path"]), project_root)
        if "semantic_decoded_path" in file_bundle else None,
        "gazebo_instance_count_path": project_rel(Path(file_bundle["gazebo_instance_count_path"]), project_root)
        if "gazebo_instance_count_path" in file_bundle else None,
        "colored_map_path": project_rel(Path(file_bundle["colored_map_path"]), project_root)
        if "colored_map_path" in file_bundle else None,
        "metadata_path": project_rel(Path(file_bundle["metadata_path"]), project_root)
        if "metadata_path" in file_bundle else None,
    }

    labeled_pcl_entry = (
        labeled_pcl_lookup.get((camera_id, panoptic_key))
        if panoptic_key is not None
        else None
    )
    invalid_labeled_pcl_rows = (
        labeled_pcl_invalid_lookup.get((camera_id, panoptic_key), [])
        if panoptic_key is not None
        else []
    )

    labeled_pcl_path = None if labeled_pcl_entry is None else labeled_pcl_entry.get("pcl_path")
    has_labeled_pcl = bool(labeled_pcl_path)

    rt_link = find_matching_rows(selected_record, rt_rows, RT_FRAME_KEY_CANDIDATES)
    label_link = find_matching_rows(selected_record, label_rows or [], LABEL_FRAME_KEY_CANDIDATES)

    compact_rt_rows = [compact_row(row, RT_COMPACT_COLUMNS, project_root) for row in rt_link.rows]
    compact_label_rows = [compact_row(row, LABEL_TARGET_COLUMNS, project_root) for row in label_link.rows]
    rt_rx_ids = dedupe_rx_ids(rt_link.rows)

    warnings: list[str] = []
    errors: list[str] = []
    for key in REQUIRED_PANOPTIC_KEYS:
        if not resolved_files[key]:
            errors.append(f"missing required panoptic file: {key}")
    for key in OPTIONAL_PANOPTIC_KEYS:
        if not resolved_files[key]:
            warnings.append(f"missing optional panoptic file: {key}")
    if not rt_link.rows:
        errors.append("no RT rows linked")
    if not label_link.rows:
        warnings.append("no transition label rows linked")
    if panoptic_key is None:
        errors.append("selected frame record does not expose a usable frame key")

    labeled_pcl_errors: list[str] = []
    labeled_pcl_status = None if labeled_pcl_entry is None else labeled_pcl_entry.get("status")
    labeled_pcl_point_count = None if labeled_pcl_entry is None else labeled_pcl_entry.get("point_count")
    labeled_pcl_zero_label_point_count = (
        None if labeled_pcl_entry is None else labeled_pcl_entry.get("zero_label_point_count")
    )
    labeled_pcl_unknown_label_point_count = (
        None if labeled_pcl_entry is None else labeled_pcl_entry.get("unknown_label_point_count")
    )
    if labeled_pcl_entry is None:
        labeled_pcl_validation_status = "missing"
    else:
        if not labeled_pcl_path:
            labeled_pcl_errors.append("labeled PCL index row is missing output_labeled_pcl_path")
        elif not labeled_pcl_entry["pcl_exists"]:
            labeled_pcl_errors.append(f"labeled PCL file is missing: {labeled_pcl_path}")
        if labeled_pcl_status != "ok":
            labeled_pcl_errors.append(
                f"labeled PCL index row reports non-ok status {labeled_pcl_status!r}"
            )
        if labeled_pcl_point_count is None or labeled_pcl_point_count <= 0:
            labeled_pcl_errors.append("labeled PCL point_count is missing or zero")
        if labeled_pcl_zero_label_point_count is None:
            labeled_pcl_errors.append("labeled PCL zero_label_point_count is missing")
        elif labeled_pcl_zero_label_point_count > 0:
            labeled_pcl_errors.append(
                f"labeled PCL zero_label_point_count is {labeled_pcl_zero_label_point_count}"
            )
        if labeled_pcl_unknown_label_point_count is None:
            labeled_pcl_errors.append("labeled PCL unknown_label_point_count is missing")
        elif labeled_pcl_unknown_label_point_count > 0:
            labeled_pcl_errors.append(
                "labeled PCL unknown_label_point_count is "
                f"{labeled_pcl_unknown_label_point_count}"
            )
        for invalid_row in invalid_labeled_pcl_rows:
            issue = invalid_row.get("issue") or "unknown labeled PCL validation failure"
            labeled_pcl_errors.append(
                f"labeled PCL validator reported failure for frame {panoptic_key}: {issue}"
            )
        labeled_pcl_validation_status = "error" if labeled_pcl_errors else "ok"

    if labeled_pcl_validation_status == "error":
        errors.extend(f"labeled_pcl: {message}" for message in labeled_pcl_errors)

    validation_status = "ok"
    if errors:
        validation_status = "error"
    elif warnings:
        validation_status = "warning"

    row = {
        "index_version": INDEX_VERSION,
        "experiment_name": experiment_name,
        "source_experiment": source_experiment,
        "selected_frame_id": selected_frame_id,
        "selected_frame_idx": selected_frame_idx,
        "source_frame_id": source_frame_id,
        "source_frame_index": source_frame_index,
        "source_sample_index": source_sample_index,
        "camera_id": camera_id,
        **extract_camera_fields(camera),
        **resolved_files,
        "has_panoptic_labels_rgb": bool_string(bool(resolved_files["panoptic_labels_rgb_path"])),
        "has_semantic_decoded": bool_string(bool(resolved_files["semantic_decoded_path"])),
        "has_gazebo_instance_count": bool_string(bool(resolved_files["gazebo_instance_count_path"])),
        "has_colored_map": bool_string(bool(resolved_files["colored_map_path"])),
        "has_metadata": bool_string(bool(resolved_files["metadata_path"])),
        "labeled_pcl_path": labeled_pcl_path,
        "has_labeled_pcl": bool_string(has_labeled_pcl),
        "labeled_pcl_validation_status": labeled_pcl_validation_status,
        "labeled_pcl_point_count": labeled_pcl_point_count,
        "labeled_pcl_zero_label_point_count": labeled_pcl_zero_label_point_count,
        "labeled_pcl_unknown_label_point_count": labeled_pcl_unknown_label_point_count,
        "labeled_pcl_unique_class_label_count": None
        if labeled_pcl_entry is None
        else labeled_pcl_entry.get("unique_class_label_count"),
        "labeled_pcl_unique_instance_id_count": None
        if labeled_pcl_entry is None
        else labeled_pcl_entry.get("unique_instance_id_count"),
        "labeled_pcl_status": labeled_pcl_status,
        "labeled_pcl_notes": None if labeled_pcl_entry is None else labeled_pcl_entry.get("notes"),
        "rt_row_count": len(rt_link.rows),
        "rt_rx_ids": ",".join(rt_rx_ids),
        "rt_frame_key_used": rt_link.key_used,
        "rt_rows_json": json_cell(compact_rt_rows),
        "label_row_count": len(label_link.rows),
        "label_targets_json": json_cell(compact_label_rows),
        "label_frame_key_used": label_link.key_used,
        "instance_registry_path": project_rel(instance_registry_path, project_root),
        "semantic_label_map_path": project_rel(semantic_label_map_path, project_root),
        "validation_status": validation_status,
        "validation_notes": "; ".join([*errors, *warnings]),
    }

    json_record = {
        "index_version": INDEX_VERSION,
        "experiment_name": experiment_name,
        "source_experiment": source_experiment,
        "selected_frame": {
            "selected_frame_id": selected_frame_id,
            "selected_frame_idx": selected_frame_idx,
            "source_frame_id": source_frame_id,
            "source_frame_index": source_frame_index,
            "source_sample_index": source_sample_index,
            "source_record": selected_record.get("source_record"),
        },
        "camera": {
            "camera_id": camera_id,
            **extract_camera_fields(camera),
        },
        "panoptic_files": {
            **resolved_files,
            "has_panoptic_labels_rgb": bool(resolved_files["panoptic_labels_rgb_path"]),
            "has_semantic_decoded": bool(resolved_files["semantic_decoded_path"]),
            "has_gazebo_instance_count": bool(resolved_files["gazebo_instance_count_path"]),
            "has_colored_map": bool(resolved_files["colored_map_path"]),
            "has_metadata": bool(resolved_files["metadata_path"]),
        },
        "labeled_pointcloud": {
            "pcl_path": labeled_pcl_path,
            "has_pcl": has_labeled_pcl,
            "validation_status": labeled_pcl_validation_status,
            "point_count": labeled_pcl_point_count,
            "zero_label_point_count": labeled_pcl_zero_label_point_count,
            "unknown_label_point_count": labeled_pcl_unknown_label_point_count,
            "unique_class_label_count": None
            if labeled_pcl_entry is None
            else labeled_pcl_entry.get("unique_class_label_count"),
            "unique_instance_id_count": None
            if labeled_pcl_entry is None
            else labeled_pcl_entry.get("unique_instance_id_count"),
            "status": labeled_pcl_status,
            "notes": None if labeled_pcl_entry is None else labeled_pcl_entry.get("notes"),
            "errors": labeled_pcl_errors,
        },
        "rt_link": {
            "row_count": len(rt_link.rows),
            "rx_ids": rt_rx_ids,
            "frame_key_used": rt_link.key_used,
            "rows": compact_rt_rows,
        },
        "label_link": {
            "row_count": len(label_link.rows),
            "frame_key_used": label_link.key_used,
            "rows": compact_label_rows,
        },
        "instance_registry_path": project_rel(instance_registry_path, project_root),
        "semantic_label_map_path": project_rel(semantic_label_map_path, project_root),
        "validation": {
            "status": validation_status,
            "errors": errors,
            "warnings": warnings,
        },
    }
    return row, json_record, errors, warnings


def build_summary(
    *,
    config: dict[str, Any],
    experiment_name: str,
    source_experiment: str,
    selected_frames: list[dict[str, Any]],
    camera_ids: list[str],
    csv_rows: list[dict[str, Any]],
    input_notes: list[str],
    sync_stable_validation_summary_path: str | None,
    sync_stable_validation_overall_passed: bool | None,
    labeled_pcl_index_path: str | None,
    labeled_pcl_summary_path: str | None,
    labeled_pcl_validation_summary_path: str | None,
    labeled_pcl_validation_overall_passed: bool | None,
    labeled_pcl_artifacts_present: bool,
    labeled_pcl_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    rows_with_all_panoptic_files = sum(
        1
        for row in csv_rows
        if row["has_panoptic_labels_rgb"] == "true"
        and row["has_semantic_decoded"] == "true"
        and row["has_gazebo_instance_count"] == "true"
    )
    rows_with_rt_links = sum(1 for row in csv_rows if int(row["rt_row_count"]) > 0)
    rows_with_label_links = sum(1 for row in csv_rows if int(row["label_row_count"]) > 0)
    rows_with_labeled_pcl = sum(1 for row in csv_rows if row["has_labeled_pcl"] == "true")
    rows_with_labeled_pcl_ok = sum(
        1 for row in csv_rows if row.get("labeled_pcl_validation_status") == "ok"
    )
    rows_with_labeled_pcl_error = sum(
        1 for row in csv_rows if row.get("labeled_pcl_validation_status") == "error"
    )
    missing_file_count = sum(
        1
        for row in csv_rows
        for key in (
            "has_panoptic_labels_rgb",
            "has_semantic_decoded",
            "has_gazebo_instance_count",
            "has_colored_map",
            "has_metadata",
        )
        if row[key] != "true"
    )
    missing_rt_link_count = sum(1 for row in csv_rows if int(row["rt_row_count"]) == 0)
    missing_label_link_count = sum(1 for row in csv_rows if int(row["label_row_count"]) == 0)
    missing_labeled_pcl_count = len(csv_rows) - rows_with_labeled_pcl
    warning_count = sum(1 for row in csv_rows if row["validation_status"] == "warning")
    error_count = sum(1 for row in csv_rows if row["validation_status"] == "error")
    expected_frame_count = int(config.get("frame_count", len(selected_frames)))
    expected_camera_count = int(config.get("expected_camera_count", len(camera_ids)))
    expected_sample_count = int(config.get("expected_perception_samples", expected_frame_count * expected_camera_count))
    labeled_pcl_point_counts = [
        value
        for value in (parse_int(row.get("labeled_pcl_point_count")) for row in csv_rows)
        if value is not None
    ]
    labeled_pcl_zero_counts = [
        value
        for value in (parse_int(row.get("labeled_pcl_zero_label_point_count")) for row in csv_rows)
        if value is not None
    ]
    labeled_pcl_unknown_counts = [
        value
        for value in (parse_int(row.get("labeled_pcl_unknown_label_point_count")) for row in csv_rows)
        if value is not None
    ]
    labeled_pcl_coverage_ok = (
        not labeled_pcl_artifacts_present
        or (
            rows_with_labeled_pcl == expected_sample_count
            and rows_with_labeled_pcl_error == 0
            and labeled_pcl_validation_overall_passed is not False
        )
    )
    overall_passed = (
        len(csv_rows) == expected_sample_count
        and len(selected_frames) == expected_frame_count
        and len(camera_ids) == expected_camera_count
        and rows_with_all_panoptic_files == len(csv_rows)
        and missing_rt_link_count == 0
        and labeled_pcl_coverage_ok
    )
    return {
        "index_version": INDEX_VERSION,
        "experiment_name": experiment_name,
        "source_experiment": source_experiment,
        "rows": len(csv_rows),
        "expected_frame_count": expected_frame_count,
        "actual_frame_count": len(selected_frames),
        "expected_camera_count": expected_camera_count,
        "actual_camera_count": len(camera_ids),
        "expected_sample_count": expected_sample_count,
        "actual_index_rows": len(csv_rows),
        "sync_stable_instance_validation_summary_path": sync_stable_validation_summary_path,
        "sync_stable_instance_validation_overall_passed": sync_stable_validation_overall_passed,
        "labeled_pcl_index_path": labeled_pcl_index_path,
        "labeled_pcl_summary_path": labeled_pcl_summary_path,
        "labeled_pcl_validation_summary_path": labeled_pcl_validation_summary_path,
        "labeled_pcl_validation_overall_passed": labeled_pcl_validation_overall_passed,
        "expected_labeled_pcl_sample_count": expected_sample_count,
        "rows_with_labeled_pcl": rows_with_labeled_pcl,
        "rows_with_labeled_pcl_ok": rows_with_labeled_pcl_ok,
        "rows_with_labeled_pcl_error": rows_with_labeled_pcl_error,
        "missing_labeled_pcl_count": missing_labeled_pcl_count,
        "total_labeled_pcl_points": sum(labeled_pcl_point_counts) if labeled_pcl_point_counts else 0,
        "labeled_pcl_zero_label_point_count": sum(labeled_pcl_zero_counts) if labeled_pcl_zero_counts else 0,
        "labeled_pcl_unknown_label_point_count": sum(labeled_pcl_unknown_counts) if labeled_pcl_unknown_counts else 0,
        "labeled_pcl_unique_class_labels_observed": []
        if not isinstance(labeled_pcl_summary, dict)
        else list(labeled_pcl_summary.get("unique_class_labels_observed") or []),
        "labeled_pcl_unique_instance_ids_observed": []
        if not isinstance(labeled_pcl_summary, dict)
        else list(labeled_pcl_summary.get("unique_instance_ids_observed") or []),
        "rows_with_all_panoptic_files": rows_with_all_panoptic_files,
        "rows_with_rt_links": rows_with_rt_links,
        "rows_with_label_links": rows_with_label_links,
        "missing_file_count": missing_file_count,
        "missing_rt_link_count": missing_rt_link_count,
        "missing_label_link_count": missing_label_link_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "overall_passed": overall_passed,
        "notes": input_notes,
    }


def main() -> None:
    args = parse_args()
    try:
        config_path = args.config.resolve()
        project_root = resolve_project_root(config_path)
        config = load_json(config_path, "perception config")
        if not isinstance(config, dict):
            raise IndexBuildError(f"Perception config must be a JSON object: {config_path}")

        experiment_root = config_path.parent.parent
        print(f"experiment_root={experiment_root.resolve()}")
        output_dir = (args.output_dir.resolve() if args.output_dir is not None else experiment_root / "dataset_index")
        summary_path = output_dir / "panoptic_dataset_index_summary.json"
        json_path = output_dir / "panoptic_dataset_index.json"
        csv_path = output_dir / "panoptic_dataset_index.csv"
        ensure_output_paths([summary_path, json_path, csv_path], args.force)

        experiment_name = str(config.get("experiment_name") or experiment_root.name)
        source_experiment_value = args.source_experiment or config.get("source_experiment")
        if not isinstance(source_experiment_value, (str, Path)):
            raise IndexBuildError("Config is missing a valid 'source_experiment'.")
        source_experiment_rel = str(source_experiment_value)
        source_experiment_path = Path(source_experiment_rel)
        if not source_experiment_path.is_absolute():
            source_experiment_path = project_root / source_experiment_path
        source_handle = SourceExperimentHandle.from_path(source_experiment_path, project_root)
        source_handle.require_available()

        camera_rig_path = experiment_root / "config" / "camera_rig.json"
        semantic_label_map_path = experiment_root / "config" / "semantic_label_map.json"
        selected_frames_path = experiment_root / "frames" / "selected_frames.json"
        instance_registry_path = experiment_root / "frames" / "instance_registry.json"
        panoptic_root = experiment_root / "perception_raw" / "native" / "panoptic"
        sync_stable_validation_summary_path = (
            experiment_root / "validation" / "sync_stable_instance_rgb_pcl_capture_validation_summary.json"
        )
        labeled_pcl_index_path = experiment_root / "reconstruction" / "labeled_colorized_pcl_sync" / "labeled_colorized_pcl_index.csv"
        labeled_pcl_summary_path = experiment_root / "reconstruction" / "labeled_colorized_pcl_sync" / "labeled_colorized_pcl_summary.json"
        labeled_pcl_validation_summary_path = experiment_root / "validation" / "labeled_colorized_pcl_validation_summary.json"
        labeled_pcl_invalid_rows_path = experiment_root / "validation" / "labeled_colorized_pcl_invalid_rows.csv"

        camera_map = load_camera_map(load_json(camera_rig_path, "camera rig"))
        semantic_label_map = load_json(semantic_label_map_path, "semantic label map")
        if not isinstance(semantic_label_map, dict):
            raise IndexBuildError(f"Semantic label map must be a JSON object: {semantic_label_map_path}")
        selected_frames = normalize_selected_frames(load_json(selected_frames_path, "selected frames"), selected_frames_path)
        _instance_registry = load_json(instance_registry_path, "instance registry")

        configured_camera_ids = config.get("camera_ids")
        if isinstance(configured_camera_ids, list) and configured_camera_ids:
            camera_ids = [str(camera_id) for camera_id in configured_camera_ids]
        else:
            camera_ids = list(camera_map)

        rt_csv_candidate, rt_origin = discover_csv_path(
            args.rt_csv,
            source_handle,
            exact_candidates=("rt_results/rt_200frames_multi_rx.csv",),
            discovery_tokens=("rt_200frames_multi_rx",),
        )
        if rt_csv_candidate is None or rt_origin is None:
            raise IndexBuildError("Could not discover the actor-aware RT CSV.")

        labels_csv_candidate, labels_origin = discover_csv_path(
            args.labels_csv,
            source_handle,
            exact_candidates=(
                "labels/rt_transition_labels.csv",
                "rt_results/rt_200frames_multi_rx_labeled.csv",
            ),
            discovery_tokens=("labeled", "rt"),
        )
        if labels_csv_candidate is None or labels_origin is None:
            raise IndexBuildError("Could not discover a transition-label CSV.")

        rt_rows, rt_csv_resolved = load_csv_records(source_handle, rt_csv_candidate, rt_origin)
        label_rows, labels_csv_resolved = load_csv_records(source_handle, labels_csv_candidate, labels_origin)
        sync_stable_validation_summary = load_optional_json(
            sync_stable_validation_summary_path,
            "synchronized stable-instance RGB/PCL validation summary",
        )
        labeled_pcl_rows = load_optional_csv_rows(
            labeled_pcl_index_path,
            "final labeled colorized PCL index",
        )
        labeled_pcl_summary = load_optional_json(
            labeled_pcl_summary_path,
            "final labeled colorized PCL summary",
        )
        labeled_pcl_validation_summary = load_optional_json(
            labeled_pcl_validation_summary_path,
            "final labeled colorized PCL validation summary",
        )
        labeled_pcl_invalid_rows = load_optional_csv_rows(
            labeled_pcl_invalid_rows_path,
            "final labeled colorized PCL invalid rows",
        )

        panoptic_lookup = build_panoptic_lookup(panoptic_root)
        labeled_pcl_lookup = build_labeled_pcl_lookup(
            labeled_pcl_rows,
            project_root,
        )
        labeled_pcl_invalid_lookup = build_labeled_pcl_invalid_lookup(
            labeled_pcl_invalid_rows,
            project_root,
        )
        labeled_pcl_artifacts_present = any(
            [
                bool(labeled_pcl_rows),
                labeled_pcl_summary is not None,
                labeled_pcl_validation_summary is not None,
                bool(labeled_pcl_invalid_rows),
            ]
        )
        sync_stable_validation_overall_passed = (
            sync_stable_validation_summary.get("overall_passed")
            if isinstance(sync_stable_validation_summary, dict)
            else None
        )
        labeled_pcl_validation_overall_passed = (
            labeled_pcl_validation_summary.get("overall_passed")
            if isinstance(labeled_pcl_validation_summary, dict)
            else None
        )
        input_notes = [
            f"source_experiment_mode={source_handle.mode}",
            f"rt_csv={rt_csv_resolved}",
            f"labels_csv={labels_csv_resolved}",
            f"sync_stable_instance_validation_summary={project_rel(sync_stable_validation_summary_path, project_root) if sync_stable_validation_summary_path.is_file() else 'missing'}",
            f"labeled_pcl_index={project_rel(labeled_pcl_index_path, project_root) if labeled_pcl_index_path.is_file() else 'missing'}",
            f"labeled_pcl_summary={project_rel(labeled_pcl_summary_path, project_root) if labeled_pcl_summary_path.is_file() else 'missing'}",
            f"labeled_pcl_validation_summary={project_rel(labeled_pcl_validation_summary_path, project_root) if labeled_pcl_validation_summary_path.is_file() else 'missing'}",
            "semantic labels decode from panoptic rgb[2]",
            "gazebo_instance_count decode is rgb[1] * 256 + rgb[0]",
            "gazebo_instance_count is not the stable dataset instance ID",
        ]

        csv_rows: list[dict[str, Any]] = []
        json_rows: list[dict[str, Any]] = []
        total_errors = 0

        for selected_frame_idx, selected_record in enumerate(selected_frames):
            for camera_id in camera_ids:
                camera = camera_map.get(camera_id)
                if camera is None:
                    raise IndexBuildError(f"camera_rig.json does not define configured camera_id={camera_id!r}")
                csv_row, json_row, errors, _warnings = build_row(
                    experiment_name=experiment_name,
                    source_experiment=source_experiment_rel,
                    selected_frame_idx=selected_frame_idx,
                    selected_record=selected_record,
                    camera_id=camera_id,
                    camera=camera,
                    panoptic_lookup=panoptic_lookup,
                    labeled_pcl_lookup=labeled_pcl_lookup,
                    labeled_pcl_invalid_lookup=labeled_pcl_invalid_lookup,
                    rt_rows=rt_rows,
                    label_rows=label_rows,
                    project_root=project_root,
                    instance_registry_path=instance_registry_path,
                    semantic_label_map_path=semantic_label_map_path,
                )
                csv_rows.append(csv_row)
                json_rows.append(json_row)
                total_errors += len(errors)

        if args.max_rows is not None:
            csv_rows = csv_rows[:args.max_rows]
            json_rows = json_rows[:args.max_rows]

        summary = build_summary(
            config=config,
            experiment_name=experiment_name,
            source_experiment=source_experiment_rel,
            selected_frames=selected_frames,
            camera_ids=camera_ids,
            csv_rows=csv_rows,
            input_notes=input_notes,
            sync_stable_validation_summary_path=project_rel(sync_stable_validation_summary_path, project_root)
            if sync_stable_validation_summary_path.is_file()
            else None,
            sync_stable_validation_overall_passed=sync_stable_validation_overall_passed,
            labeled_pcl_index_path=project_rel(labeled_pcl_index_path, project_root)
            if labeled_pcl_index_path.is_file()
            else None,
            labeled_pcl_summary_path=project_rel(labeled_pcl_summary_path, project_root)
            if labeled_pcl_summary_path.is_file()
            else None,
            labeled_pcl_validation_summary_path=project_rel(labeled_pcl_validation_summary_path, project_root)
            if labeled_pcl_validation_summary_path.is_file()
            else None,
            labeled_pcl_validation_overall_passed=labeled_pcl_validation_overall_passed,
            labeled_pcl_artifacts_present=labeled_pcl_artifacts_present,
            labeled_pcl_summary=labeled_pcl_summary if isinstance(labeled_pcl_summary, dict) else None,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(csv_path, CSV_FIELDNAMES, csv_rows)
        write_json(json_path, json_rows, pretty=args.pretty_json)
        write_json(summary_path, summary, pretty=args.pretty_json)

        print(
            "Built panoptic dataset index:",
            f"rows={summary['actual_index_rows']}",
            f"cameras={summary['actual_camera_count']}",
            f"rows_with_rt_links={summary['rows_with_rt_links']}",
            f"rows_with_label_links={summary['rows_with_label_links']}",
            f"rows_with_labeled_pcl={summary['rows_with_labeled_pcl']}",
            f"rows_with_all_panoptic_files={summary['rows_with_all_panoptic_files']}",
            f"overall_passed={summary['overall_passed']}",
        )

        if args.strict and total_errors:
            raise IndexBuildError(
                f"Strict mode failed because {total_errors} row-level error(s) were found."
            )
    except IndexBuildError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
