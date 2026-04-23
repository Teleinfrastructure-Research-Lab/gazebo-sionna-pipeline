#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = PROJECT_ROOT / "rt_out" / "manifests"
STATIC_MANIFEST_PATH = MANIFESTS_DIR / "static_manifest.json"
DYNAMIC_MANIFEST_PATH = MANIFESTS_DIR / "dynamic_manifest.json"
REGISTRY_PATH = MANIFESTS_DIR / "geometry_registry.json"
MODELS_ROOT = PROJECT_ROOT / "models"

ALLOWED_GEOMETRY_TYPES = ("mesh", "box", "cylinder", "sphere")


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc


def _parse_float_sequence(value: Any, expected_length: int, field_name: str) -> list[float]:
    if isinstance(value, str):
        parts = value.split()
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError(
            f"{field_name} must contain exactly {expected_length} numeric values, "
            f"got {type(value).__name__}"
        )

    if len(parts) != expected_length:
        raise ValueError(
            f"{field_name} must contain exactly {expected_length} numeric values, got {len(parts)}"
        )

    numbers: list[float] = []
    for item in parts:
        try:
            numbers.append(float(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} must contain exactly {expected_length} numeric values"
            ) from exc

    return numbers


def parse_pose(value: Any) -> list[float]:
    return _parse_float_sequence(value, 6, "pose")


def parse_vec3(value: Any, field_name: str) -> list[float]:
    return _parse_float_sequence(value, 3, field_name)


def _parse_number(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


@lru_cache(maxsize=None)
def _build_model_index(models_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    seen_paths: set[Path] = set()

    for marker_name in ("model.config", "model.sdf"):
        for marker in models_root.rglob(marker_name):
            model_dir = marker.parent.resolve()
            if model_dir in seen_paths:
                continue
            seen_paths.add(model_dir)
            index.setdefault(model_dir.name, []).append(model_dir)

    for paths in index.values():
        paths.sort(key=lambda path: (len(path.parts), str(path)))

    return index


def resolve_uri(uri: Any, project_root: Path, models_root: Path) -> Path:
    if not isinstance(uri, str) or not uri.strip():
        raise ValueError("mesh uri must be a non-empty string")

    cleaned_uri = uri.strip()

    if cleaned_uri.startswith("model://"):
        relative_uri = cleaned_uri[len("model://") :]
        path_parts = Path(relative_uri).parts
        if len(path_parts) < 2:
            raise ValueError(f"model:// URI must include model name and relative path: {cleaned_uri}")

        model_name = path_parts[0]
        relative_path = Path(*path_parts[1:])
        model_dirs = _build_model_index(models_root).get(model_name)
        if not model_dirs:
            raise ValueError(f"could not resolve model '{model_name}' under {models_root}")

        return (model_dirs[0] / relative_path).resolve()

    if cleaned_uri.startswith("file://"):
        raw_path = cleaned_uri[len("file://") :]
    elif "://" in cleaned_uri:
        raise ValueError(f"unsupported URI scheme in {cleaned_uri}")
    else:
        raw_path = cleaned_uri

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate

    return candidate.resolve()


def _warning(
    source_manifest: str,
    model_name: str,
    link_name: str,
    visual_label: str,
    message: str,
) -> str:
    return (
        f"[{source_manifest}] model={model_name!r}, link={link_name!r}, "
        f"visual={visual_label!r}: {message}"
    )


def _info(source_manifest: str, model_name: str, link_name: str, message: str) -> str:
    return f"[{source_manifest}] model={model_name!r}, link={link_name!r}: {message}"


def _empty_result() -> dict[str, Any]:
    return {
        "entries": [],
        "warnings": [],
        "info": [],
        "geometry_counts": {name: 0 for name in ALLOWED_GEOMETRY_TYPES},
        "skipped_visuals": 0,
        "links_without_visuals": 0,
    }


def flatten_manifest(
    manifest_data: Any,
    source_manifest: str,
    static_flag: bool,
    project_root: Path,
    models_root: Path,
) -> dict[str, Any]:
    result = _empty_result()

    if not isinstance(manifest_data, list):
        result["warnings"].append(f"[{source_manifest}] manifest root is not a list; skipping")
        return result

    for model_index, model in enumerate(manifest_data):
        if not isinstance(model, dict):
            result["warnings"].append(
                f"[{source_manifest}] model index {model_index}: model entry is not an object; skipping"
            )
            continue

        raw_model_name = model.get("model")
        model_name = raw_model_name if isinstance(raw_model_name, str) and raw_model_name else "<missing model>"

        raw_links = model.get("links")
        if not isinstance(raw_links, list):
            result["warnings"].append(
                f"[{source_manifest}] model={model_name!r}: links is missing or not a list; skipping model"
            )
            continue

        try:
            model_pose = parse_pose(model.get("model_pose"))
            model_pose_error: str | None = None
        except ValueError as exc:
            model_pose = None
            model_pose_error = str(exc)

        for link_index, link in enumerate(raw_links):
            if not isinstance(link, dict):
                result["warnings"].append(
                    f"[{source_manifest}] model={model_name!r}, link index {link_index}: "
                    "link entry is not an object; skipping link"
                )
                continue

            raw_link_name = link.get("link")
            link_name = raw_link_name if isinstance(raw_link_name, str) and raw_link_name else "<missing link>"

            visuals = link.get("visuals")
            if not isinstance(visuals, list):
                result["warnings"].append(
                    f"[{source_manifest}] model={model_name!r}, link={link_name!r}: "
                    "visuals is missing or not a list; skipping link"
                )
                continue

            if not visuals:
                result["links_without_visuals"] += 1
                result["info"].append(
                    _info(source_manifest, model_name, link_name, "link has no visuals")
                )
                continue

            try:
                link_pose = parse_pose(link.get("link_pose"))
                link_pose_error: str | None = None
            except ValueError as exc:
                link_pose = None
                link_pose_error = str(exc)

            for visual_index, visual in enumerate(visuals):
                if not isinstance(visual, dict):
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(
                            source_manifest,
                            model_name,
                            link_name,
                            f"index {visual_index}",
                            "visual entry is not an object",
                        )
                    )
                    continue

                visual_name_value = visual.get("visual_name")
                visual_label = (
                    visual_name_value
                    if isinstance(visual_name_value, str) and visual_name_value
                    else f"index {visual_index}"
                )

                if not isinstance(raw_model_name, str) or not raw_model_name:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(source_manifest, model_name, link_name, visual_label, "missing model name")
                    )
                    continue

                if model_pose_error is not None:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(
                            source_manifest,
                            model_name,
                            link_name,
                            visual_label,
                            f"invalid model_pose: {model_pose_error}",
                        )
                    )
                    continue

                if not isinstance(raw_link_name, str) or not raw_link_name:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(source_manifest, model_name, link_name, visual_label, "missing link name")
                    )
                    continue

                if link_pose_error is not None:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(
                            source_manifest,
                            model_name,
                            link_name,
                            visual_label,
                            f"invalid link_pose: {link_pose_error}",
                        )
                    )
                    continue

                if not isinstance(visual_name_value, str) or not visual_name_value:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(source_manifest, model_name, link_name, visual_label, "missing visual_name")
                    )
                    continue

                geometry_type = visual.get("geometry_type")
                if not isinstance(geometry_type, str) or not geometry_type:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(source_manifest, model_name, link_name, visual_label, "missing geometry_type")
                    )
                    continue

                if geometry_type not in ALLOWED_GEOMETRY_TYPES:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(
                            source_manifest,
                            model_name,
                            link_name,
                            visual_name_value,
                            f"unsupported geometry_type {geometry_type!r}",
                        )
                    )
                    continue

                try:
                    visual_pose = parse_pose(visual.get("visual_pose"))
                except ValueError as exc:
                    result["skipped_visuals"] += 1
                    result["warnings"].append(
                        _warning(
                            source_manifest,
                            model_name,
                            link_name,
                            visual_name_value,
                            f"invalid visual_pose: {exc}",
                        )
                    )
                    continue

                record: dict[str, Any] = {
                    "model_name": raw_model_name,
                    "link_name": raw_link_name,
                    "visual_name": visual_name_value,
                    "geometry_type": geometry_type,
                    "static": static_flag,
                    "source_manifest": source_manifest,
                    "model_pose": model_pose,
                    "link_pose": link_pose,
                    "visual_pose": visual_pose,
                }

                if geometry_type == "mesh":
                    if "uri" not in visual:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(source_manifest, model_name, link_name, visual_name_value, "mesh is missing uri")
                        )
                        continue

                    uri = visual.get("uri")
                    try:
                        resolved_path = resolve_uri(uri, project_root, models_root)
                    except ValueError as exc:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                f"could not resolve uri {uri!r}: {exc}",
                            )
                        )
                        continue

                    if not resolved_path.exists():
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                f"resolved mesh path does not exist: {resolved_path}",
                            )
                        )
                        continue

                    if "scale" in visual:
                        scale_value = visual.get("scale")
                    else:
                        scale_value = "1 1 1"
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                "scale missing; defaulting to [1.0, 1.0, 1.0]",
                            )
                        )

                    try:
                        scale = parse_vec3(scale_value, "scale")
                    except ValueError as exc:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                f"invalid scale: {exc}",
                            )
                        )
                        continue

                    record.update(
                        {
                            "uri": uri,
                            "resolved_path": str(resolved_path),
                            "scale": scale,
                        }
                    )

                elif geometry_type == "box":
                    if "size" not in visual:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(source_manifest, model_name, link_name, visual_name_value, "box is missing size")
                        )
                        continue

                    try:
                        size = parse_vec3(visual.get("size"), "size")
                    except ValueError as exc:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                f"invalid size: {exc}",
                            )
                        )
                        continue

                    record["size"] = size

                elif geometry_type == "cylinder":
                    if "radius" not in visual or "length" not in visual:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                "cylinder is missing radius or length",
                            )
                        )
                        continue

                    try:
                        record["radius"] = _parse_number(visual.get("radius"), "radius")
                        record["length"] = _parse_number(visual.get("length"), "length")
                    except ValueError as exc:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                f"invalid cylinder data: {exc}",
                            )
                        )
                        continue

                elif geometry_type == "sphere":
                    if "radius" not in visual:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                "sphere is missing radius",
                            )
                        )
                        continue

                    try:
                        record["radius"] = _parse_number(visual.get("radius"), "radius")
                    except ValueError as exc:
                        result["skipped_visuals"] += 1
                        result["warnings"].append(
                            _warning(
                                source_manifest,
                                model_name,
                                link_name,
                                visual_name_value,
                                f"invalid sphere data: {exc}",
                            )
                        )
                        continue

                result["entries"].append(record)
                result["geometry_counts"][geometry_type] += 1

    return result


def build_registry(
    static_manifest: Any,
    dynamic_manifest: Any,
    project_root: Path,
    models_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    static_result = flatten_manifest(
        static_manifest,
        "static_manifest",
        True,
        project_root,
        models_root,
    )
    dynamic_result = flatten_manifest(
        dynamic_manifest,
        "dynamic_manifest",
        False,
        project_root,
        models_root,
    )

    registry = static_result["entries"] + dynamic_result["entries"]
    geometry_counts = {
        geometry_type: (
            static_result["geometry_counts"][geometry_type]
            + dynamic_result["geometry_counts"][geometry_type]
        )
        for geometry_type in ALLOWED_GEOMETRY_TYPES
    }

    summary = {
        "total_entries": len(registry),
        "static_entries": len(static_result["entries"]),
        "dynamic_entries": len(dynamic_result["entries"]),
        "geometry_counts": geometry_counts,
        "skipped_visuals": static_result["skipped_visuals"] + dynamic_result["skipped_visuals"],
        "links_without_visuals": (
            static_result["links_without_visuals"] + dynamic_result["links_without_visuals"]
        ),
        "warnings": static_result["warnings"] + dynamic_result["warnings"],
        "info": static_result["info"] + dynamic_result["info"],
    }

    return registry, summary


def write_registry(path: Path, registry: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    try:
        static_manifest = load_json(STATIC_MANIFEST_PATH)
        dynamic_manifest = load_json(DYNAMIC_MANIFEST_PATH)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    registry, summary = build_registry(
        static_manifest,
        dynamic_manifest,
        PROJECT_ROOT,
        MODELS_ROOT,
    )
    write_registry(REGISTRY_PATH, registry)

    print("Geometry registry summary")
    print("=========================")
    print(f"Total registry entries: {summary['total_entries']}")
    print(f"Static entries: {summary['static_entries']}")
    print(f"Dynamic entries: {summary['dynamic_entries']}")
    print("Geometry counts:")
    for geometry_type in ALLOWED_GEOMETRY_TYPES:
        print(f"  - {geometry_type}: {summary['geometry_counts'][geometry_type]}")
    print(f"Skipped visuals: {summary['skipped_visuals']}")
    print(f"Links without visuals: {summary['links_without_visuals']}")
    print(f"Warnings: {len(summary['warnings'])}")
    print(f"Saved to: {REGISTRY_PATH}")

    if summary["info"]:
        print("Info:")
        for message in summary["info"]:
            print(f"  - {message}")

    if summary["warnings"]:
        print("Warning details:")
        for message in summary["warnings"]:
            print(f"  - {message}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
