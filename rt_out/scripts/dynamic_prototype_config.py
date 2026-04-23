from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "rt_out" / "config" / "dynamic_prototype_config.json"


class DynamicPrototypeConfigError(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise DynamicPrototypeConfigError(f"Missing dynamic prototype config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DynamicPrototypeConfigError(f"Invalid dynamic prototype config JSON: {exc}") from exc


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DynamicPrototypeConfigError(f"{label} must be an object")
    return value


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DynamicPrototypeConfigError(f"{label} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DynamicPrototypeConfigError(f"{label} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DynamicPrototypeConfigError(f"{label} must be a non-negative integer")
    return value


def _resolve_project_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def load_dynamic_prototype_config(
    config_path: Path | None = None,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    path = (config_path or DEFAULT_CONFIG_PATH).expanduser().resolve()
    data = _require_object(_load_json(path), "dynamic_prototype_config.json")

    raw_frames = data.get("prototype_frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise DynamicPrototypeConfigError("prototype_frames must be a non-empty list")

    frames: list[dict[str, int]] = []
    seen_frame_ids: set[int] = set()
    seen_source_indices: set[int] = set()
    for index, raw_frame in enumerate(raw_frames):
        frame = _require_object(raw_frame, f"prototype_frames[{index}]")
        frame_id = _require_non_negative_int(
            frame.get("frame_id"),
            f"prototype_frames[{index}].frame_id",
        )
        source_sample_index = _require_non_negative_int(
            frame.get("source_sample_index"),
            f"prototype_frames[{index}].source_sample_index",
        )
        if frame_id in seen_frame_ids:
            raise DynamicPrototypeConfigError(f"Duplicate prototype frame_id: {frame_id}")
        if source_sample_index in seen_source_indices:
            raise DynamicPrototypeConfigError(
                f"Duplicate prototype source_sample_index: {source_sample_index}"
            )
        seen_frame_ids.add(frame_id)
        seen_source_indices.add(source_sample_index)
        frames.append({"frame_id": frame_id, "source_sample_index": source_sample_index})

    raw_models = data.get("dynamic_models")
    if not isinstance(raw_models, dict) or not raw_models:
        raise DynamicPrototypeConfigError("dynamic_models must be a non-empty object")

    models: dict[str, dict[str, Any]] = {}
    for model_name, raw_model in raw_models.items():
        model_name = _require_non_empty_string(model_name, "dynamic model name")
        model = _require_object(raw_model, f"dynamic_models.{model_name}")
        pose_log = _require_non_empty_string(
            model.get("pose_log"),
            f"dynamic_models.{model_name}.pose_log",
        )
        expected_link_count = _require_positive_int(
            model.get("expected_link_count"),
            f"dynamic_models.{model_name}.expected_link_count",
        )
        raw_non_renderable = model.get("non_renderable_links", [])
        if not isinstance(raw_non_renderable, list):
            raise DynamicPrototypeConfigError(
                f"dynamic_models.{model_name}.non_renderable_links must be a list"
            )
        non_renderable_links = [
            _require_non_empty_string(item, f"dynamic_models.{model_name}.non_renderable_links")
            for item in raw_non_renderable
        ]
        if len(set(non_renderable_links)) != len(non_renderable_links):
            raise DynamicPrototypeConfigError(
                f"dynamic_models.{model_name}.non_renderable_links contains duplicates"
            )
        if len(non_renderable_links) >= expected_link_count:
            raise DynamicPrototypeConfigError(
                f"dynamic_models.{model_name} has no renderable links left after non-renderable list"
            )

        forced_material = _require_non_empty_string(
            model.get("forced_material"),
            f"dynamic_models.{model_name}.forced_material",
        )
        expected_renderable_count = expected_link_count - len(non_renderable_links)
        models[model_name] = {
            "pose_log": pose_log,
            "pose_log_path": _resolve_project_path(pose_log, project_root),
            "expected_link_count": expected_link_count,
            "expected_renderable_link_count": expected_renderable_count,
            "expected_renderable_visual_count": expected_renderable_count,
            "non_renderable_links": non_renderable_links,
            "forced_material": forced_material,
        }

    return {
        "config_path": path,
        "prototype_frames": frames,
        "frame_ids": [frame["frame_id"] for frame in frames],
        "source_sample_indices": [frame["source_sample_index"] for frame in frames],
        "source_sample_by_frame": {
            frame["frame_id"]: frame["source_sample_index"] for frame in frames
        },
        "dynamic_models": models,
        "model_names": list(models),
        "expected_renderable_visual_count_total": sum(
            model["expected_renderable_visual_count"] for model in models.values()
        ),
    }
