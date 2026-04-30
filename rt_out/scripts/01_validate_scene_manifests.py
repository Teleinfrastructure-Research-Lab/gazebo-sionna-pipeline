#!/usr/bin/env python3

"""Validate the extracted scene manifests before downstream geometry work.

The checks here are intentionally strict because every later export stage trusts
these JSON files. This script catches missing fields, bad paths, and mismatched
static/dynamic assumptions early and writes a machine-readable validation report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = PROJECT_ROOT / "rt_out" / "manifests"
STATIC_MANIFEST_PATH = MANIFESTS_DIR / "static_manifest.json"
DYNAMIC_MANIFEST_PATH = MANIFESTS_DIR / "dynamic_manifest.json"
REPORT_PATH = MANIFESTS_DIR / "manifest_validation_report.json"
MODELS_ROOT = PROJECT_ROOT / "models"

REQUIRED_MODEL_KEYS = ("model", "model_pose", "static", "links")
REQUIRED_LINK_KEYS = ("link", "link_pose", "visuals")
REQUIRED_VISUAL_KEYS = ("visual_name", "visual_pose", "geometry_type")
ALLOWED_GEOMETRY_TYPES = ("mesh", "box", "cylinder", "sphere")
PROTOTYPE_CONFIG = load_dynamic_prototype_config()
ALLOWED_DYNAMIC_MODELS = set(PROTOTYPE_CONFIG["model_names"])


def add_issue(bucket: list[dict[str, str]], manifest: str, location: str, message: str) -> None:
    # Store every finding in the same structure so the console and JSON report
    # can present validation errors, warnings, and info entries uniformly.
    bucket.append(
        {
            "manifest": manifest,
            "location": location,
            "message": message,
        }
    )


def load_json(path: Path) -> tuple[Any | None, str | None]:
    # Return an error string instead of raising immediately so the caller can
    # report both static and dynamic manifest load failures in one validation run.
    if not path.exists():
        return None, f"Missing file: {path}"

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), None
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON in {path}: {exc}"
    except OSError as exc:
        return None, f"Could not read {path}: {exc}"


def parse_numeric_sequence(value: Any, expected_length: int) -> tuple[list[float] | None, str | None]:
    # Manifest fields sometimes arrive as Gazebo-style whitespace strings and
    # sometimes as JSON lists, so normalize both forms before validation.
    if isinstance(value, str):
        parts = value.split()
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return None, f"Expected {expected_length} numeric values, got {type(value).__name__}"

    if len(parts) != expected_length:
        return None, f"Expected {expected_length} numeric values, got {len(parts)}"

    numbers: list[float] = []
    for item in parts:
        try:
            numbers.append(float(item))
        except (TypeError, ValueError):
            return None, f"Expected {expected_length} numeric values, got non-numeric token {item!r}"

    return numbers, None


def check_pose_string(value: Any, field_name: str) -> str | None:
    _, error = parse_numeric_sequence(value, 6)
    if error is None:
        return None
    return f"{field_name} must contain exactly 6 numeric values: {error}"


def parse_positive_number(value: Any, field_name: str) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{field_name} must be a positive number"

    if number <= 0:
        return f"{field_name} must be a positive number"

    return None


def build_model_index(models_root: Path) -> dict[str, list[Path]]:
    # Build a lookup for model:// URIs by scanning every model directory once.
    # If multiple directories share a model name, keep all candidates so URI
    # resolution can warn about the ambiguity explicitly.
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


def resolve_path_candidates(raw_path: str, manifest_dir: Path, project_root: Path) -> Path:
    # Support both manifest-relative and project-root-relative mesh paths. The
    # extracted manifests can preserve either form depending on the source asset.
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate

    manifest_relative = (manifest_dir / candidate).resolve()
    if manifest_relative.exists():
        return manifest_relative

    project_relative = (project_root / candidate).resolve()
    if project_relative.exists():
        return project_relative

    return manifest_relative


def resolve_uri(
    uri: Any,
    manifest_dir: Path,
    project_root: Path,
    models_root: Path,
    model_index: dict[str, list[Path]],
) -> tuple[Path | None, str | None, str | None]:
    # Mesh visuals are the main case where manifests reference external assets.
    # Resolve the URI and return optional warning text if the lookup was ambiguous.
    if not isinstance(uri, str) or not uri.strip():
        return None, "Mesh uri must be a non-empty string", None

    cleaned_uri = uri.strip()
    warning: str | None = None

    if cleaned_uri.startswith("model://"):
        relative_uri = cleaned_uri[len("model://") :]
        path_parts = Path(relative_uri).parts
        if len(path_parts) < 2:
            return None, f"model:// URI must include model name and relative path: {cleaned_uri}", None

        model_name = path_parts[0]
        relative_path = Path(*path_parts[1:])
        model_dirs = model_index.get(model_name, [])

        if not model_dirs:
            return None, f"Could not resolve model '{model_name}' under {models_root}", None

        if len(model_dirs) > 1:
            warning = (
                f"Multiple model directories match '{model_name}'. "
                f"Using {model_dirs[0]}"
            )

        return model_dirs[0] / relative_path, None, warning

    if cleaned_uri.startswith("file://"):
        return resolve_path_candidates(
            cleaned_uri[len("file://") :],
            manifest_dir=manifest_dir,
            project_root=project_root,
        ), None, None

    if "://" in cleaned_uri:
        return None, f"Unsupported URI scheme in {cleaned_uri}", None

    return resolve_path_candidates(
        cleaned_uri,
        manifest_dir=manifest_dir,
        project_root=project_root,
    ), None, None


def validate_visual_by_geometry_type(
    visual: dict[str, Any],
    manifest_name: str,
    location: str,
    manifest_dir: Path,
    project_root: Path,
    models_root: Path,
    model_index: dict[str, list[Path]],
    geometry_counts: dict[str, int],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    # Downstream exporters assume every supported geometry type already carries
    # the fields needed to either import a mesh or create a primitive.
    geometry_type = visual.get("geometry_type")
    if not isinstance(geometry_type, str):
        add_issue(errors, manifest_name, f"{location}.geometry_type", "geometry_type must be a string")
        return

    if geometry_type in geometry_counts:
        geometry_counts[geometry_type] += 1

    if geometry_type not in ALLOWED_GEOMETRY_TYPES:
        add_issue(
            warnings,
            manifest_name,
            f"{location}.geometry_type",
            f"Unsupported geometry_type '{geometry_type}'",
        )
        return

    if geometry_type == "mesh":
        # Mesh visuals must resolve all the way to a real file because Blender
        # later imports the asset directly from this path.
        if "uri" not in visual:
            add_issue(errors, manifest_name, f"{location}.uri", "mesh visual is missing uri")
            return

        resolved_path, error, warning = resolve_uri(
            visual.get("uri"),
            manifest_dir=manifest_dir,
            project_root=project_root,
            models_root=models_root,
            model_index=model_index,
        )
        if error is not None:
            add_issue(errors, manifest_name, f"{location}.uri", error)
        elif resolved_path is not None and not resolved_path.exists():
            add_issue(
                errors,
                manifest_name,
                f"{location}.uri",
                f"Resolved mesh path does not exist: {resolved_path}",
            )

        if warning is not None:
            add_issue(warnings, manifest_name, f"{location}.uri", warning)

        if "scale" not in visual:
            add_issue(
                warnings,
                manifest_name,
                f"{location}.scale",
                "scale is missing; assuming default '1 1 1'",
            )
        else:
            _, scale_error = parse_numeric_sequence(visual.get("scale"), 3)
            if scale_error is not None:
                add_issue(
                    warnings,
                    manifest_name,
                    f"{location}.scale",
                    f"scale should contain 3 numeric values: {scale_error}",
                )
        return

    if geometry_type == "box":
        # Primitive boxes stay procedural until the static or dynamic export
        # stages, so only their dimensions need to be validated here.
        if "size" not in visual:
            add_issue(errors, manifest_name, f"{location}.size", "box visual is missing size")
            return

        size_values, size_error = parse_numeric_sequence(visual.get("size"), 3)
        if size_error is not None:
            add_issue(errors, manifest_name, f"{location}.size", f"size is invalid: {size_error}")
            return

        if any(number <= 0 for number in size_values):
            add_issue(errors, manifest_name, f"{location}.size", "size values must all be positive")
        return

    if geometry_type == "cylinder":
        # Cylinders and spheres are likewise emitted procedurally later, so the
        # manifest only needs to prove their numeric parameters are sensible.
        radius_error = parse_positive_number(visual.get("radius"), "radius")
        length_error = parse_positive_number(visual.get("length"), "length")

        if radius_error is not None:
            add_issue(errors, manifest_name, f"{location}.radius", radius_error)
        if length_error is not None:
            add_issue(errors, manifest_name, f"{location}.length", length_error)
        return

    if geometry_type == "sphere":
        radius_error = parse_positive_number(visual.get("radius"), "radius")
        if radius_error is not None:
            add_issue(errors, manifest_name, f"{location}.radius", radius_error)


def validate_visual(
    visual: Any,
    manifest_name: str,
    location: str,
    manifest_dir: Path,
    project_root: Path,
    models_root: Path,
    model_index: dict[str, list[Path]],
    geometry_counts: dict[str, int],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    # Validate the shape of the visual record first, then delegate the
    # geometry-specific rules to the helper above.
    if not isinstance(visual, dict):
        add_issue(errors, manifest_name, location, "visual entry must be an object")
        return

    for key in REQUIRED_VISUAL_KEYS:
        if key not in visual:
            add_issue(errors, manifest_name, f"{location}.{key}", f"Missing required visual field '{key}'")

    if "visual_name" in visual and not isinstance(visual.get("visual_name"), str):
        add_issue(errors, manifest_name, f"{location}.visual_name", "visual_name must be a string")

    if "visual_pose" in visual:
        pose_error = check_pose_string(visual.get("visual_pose"), "visual_pose")
        if pose_error is not None:
            add_issue(errors, manifest_name, f"{location}.visual_pose", pose_error)

    if "geometry_type" in visual:
        validate_visual_by_geometry_type(
            visual=visual,
            manifest_name=manifest_name,
            location=location,
            manifest_dir=manifest_dir,
            project_root=project_root,
            models_root=models_root,
            model_index=model_index,
            geometry_counts=geometry_counts,
            errors=errors,
            warnings=warnings,
        )


def validate_link(
    link: Any,
    manifest_name: str,
    location: str,
    manifest_dir: Path,
    project_root: Path,
    models_root: Path,
    model_index: dict[str, list[Path]],
    counters: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    info: list[dict[str, str]],
) -> None:
    # Count every visited link so the final report can confirm that the manifest
    # still describes the expected amount of scene structure.
    counters["links"] += 1

    if not isinstance(link, dict):
        add_issue(errors, manifest_name, location, "link entry must be an object")
        return

    for key in REQUIRED_LINK_KEYS:
        if key not in link:
            add_issue(errors, manifest_name, f"{location}.{key}", f"Missing required link field '{key}'")

    if "link" in link and not isinstance(link.get("link"), str):
        add_issue(errors, manifest_name, f"{location}.link", "link must be a string")

    if "link_pose" in link:
        pose_error = check_pose_string(link.get("link_pose"), "link_pose")
        if pose_error is not None:
            add_issue(errors, manifest_name, f"{location}.link_pose", pose_error)

    visuals = link.get("visuals")
    if visuals is None:
        return

    if not isinstance(visuals, list):
        add_issue(errors, manifest_name, f"{location}.visuals", "visuals must be a list")
        return

    # Some helper links intentionally have no renderable geometry. Keep that as
    # info instead of treating it as a hard failure.
    if not visuals:
        add_issue(info, manifest_name, f"{location}.visuals", "Link has no visuals")
        return

    for visual_index, visual in enumerate(visuals):
        counters["visuals"] += 1
        validate_visual(
            visual=visual,
            manifest_name=manifest_name,
            location=f"{location}.visuals[{visual_index}]",
            manifest_dir=manifest_dir,
            project_root=project_root,
            models_root=models_root,
            model_index=model_index,
            geometry_counts=counters["geometry_counts"],
            errors=errors,
            warnings=warnings,
        )


def validate_manifest(
    manifest_name: str,
    manifest_data: Any,
    expected_static: bool,
    counters: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    info: list[dict[str, str]],
    manifest_dir: Path,
    project_root: Path,
    models_root: Path,
    model_index: dict[str, list[Path]],
) -> set[str]:
    # Walk each manifest exactly the way downstream stages consume it:
    # model -> link -> visual, while also enforcing the static/dynamic split.
    seen_models: set[str] = set()

    if not isinstance(manifest_data, list):
        add_issue(errors, manifest_name, "root", "Manifest root must be a list")
        return seen_models

    for entry_index, entry in enumerate(manifest_data):
        location = f"entries[{entry_index}]"
        if not isinstance(entry, dict):
            add_issue(errors, manifest_name, location, "Model entry must be an object")
            continue

        for key in REQUIRED_MODEL_KEYS:
            if key not in entry:
                add_issue(errors, manifest_name, f"{location}.{key}", f"Missing required model field '{key}'")

        model_name = entry.get("model")
        if isinstance(model_name, str):
            if model_name in seen_models:
                add_issue(errors, manifest_name, f"{location}.model", f"Duplicate model '{model_name}'")
            else:
                seen_models.add(model_name)
        elif "model" in entry:
            add_issue(errors, manifest_name, f"{location}.model", "model must be a string")

        if "model_pose" in entry:
            pose_error = check_pose_string(entry.get("model_pose"), "model_pose")
            if pose_error is not None:
                add_issue(errors, manifest_name, f"{location}.model_pose", pose_error)

        static_value = entry.get("static")
        if "static" in entry:
            # The validated pipeline expects every entry in a given manifest to
            # agree with that manifest's static/dynamic role.
            if not isinstance(static_value, bool):
                add_issue(errors, manifest_name, f"{location}.static", "static must be a boolean")
            elif static_value is not expected_static:
                add_issue(
                    errors,
                    manifest_name,
                    f"{location}.static",
                    f"Expected static={expected_static}, got {static_value}",
                )

        links = entry.get("links")
        if links is None:
            continue

        if not isinstance(links, list):
            add_issue(errors, manifest_name, f"{location}.links", "links must be a list")
            continue

        for link_index, link in enumerate(links):
            validate_link(
                link=link,
                manifest_name=manifest_name,
                location=f"{location}.links[{link_index}]",
                manifest_dir=manifest_dir,
                project_root=project_root,
                models_root=models_root,
                model_index=model_index,
                counters=counters,
                errors=errors,
                warnings=warnings,
                info=info,
            )

    return seen_models


def create_summary(
    static_manifest_models: int,
    dynamic_manifest_models: int,
    counters: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    info: list[dict[str, str]],
) -> dict[str, Any]:
    # Keep the summary numeric and compact so the JSON report doubles as a quick
    # regression target between validation runs.
    return {
        "static_manifest_models": static_manifest_models,
        "dynamic_manifest_models": dynamic_manifest_models,
        "total_links": counters["links"],
        "total_visuals": counters["visuals"],
        "geometry_counts": counters["geometry_counts"],
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(info),
    }


def write_report(report_path: Path, report_data: dict[str, Any]) -> None:
    # Always rewrite the full report so the JSON artifact matches the latest
    # console output and can be archived with experiment results.
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report_data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def print_issue_group(title: str, issues: list[dict[str, str]]) -> None:
    # Mirror the JSON issue structure in the console so locations are easy to
    # trace back into the written validation report.
    print(f"{title} ({len(issues)}):")
    if not issues:
        print("  - none")
        return

    for issue in issues:
        print(f"  - [{issue['manifest']}] {issue['location']}: {issue['message']}")


def main() -> int:
    # Accumulate findings across both manifests so one run gives a complete
    # picture before any geometry conversion or XML generation happens.
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    info: list[dict[str, str]] = []

    static_data, static_load_error = load_json(STATIC_MANIFEST_PATH)
    dynamic_data, dynamic_load_error = load_json(DYNAMIC_MANIFEST_PATH)

    # Parsing must succeed before structural checks can compare the frozen static
    # baseline against the validated Panda/UR5 dynamic branch.
    if static_load_error is not None:
        add_issue(errors, "static_manifest", str(STATIC_MANIFEST_PATH), static_load_error)
    if dynamic_load_error is not None:
        add_issue(errors, "dynamic_manifest", str(DYNAMIC_MANIFEST_PATH), dynamic_load_error)

    if errors:
        # Even early load failures get written to the standard report path so
        # later debugging does not depend on captured terminal output.
        summary = {
            "static_manifest_models": 0,
            "dynamic_manifest_models": 0,
            "total_links": 0,
            "total_visuals": 0,
            "geometry_counts": {name: 0 for name in ALLOWED_GEOMETRY_TYPES},
            "error_count": len(errors),
            "warning_count": 0,
            "info_count": 0,
        }
        report = {
            "summary": summary,
            "errors": errors,
            "warnings": warnings,
            "info": info,
        }
        write_report(REPORT_PATH, report)
        print("Manifest validation failed before structural checks.")
        print_issue_group("Errors", errors)
        print(f"Report written to: {REPORT_PATH}")
        return 2

    counters = {
        "links": 0,
        "visuals": 0,
        "geometry_counts": {name: 0 for name in ALLOWED_GEOMETRY_TYPES},
    }
    # Build the model:// lookup only after both manifests were parsed cleanly.
    model_index = build_model_index(MODELS_ROOT)

    static_models = validate_manifest(
        manifest_name="static_manifest",
        manifest_data=static_data,
        expected_static=True,
        counters=counters,
        errors=errors,
        warnings=warnings,
        info=info,
        manifest_dir=STATIC_MANIFEST_PATH.parent,
        project_root=PROJECT_ROOT,
        models_root=MODELS_ROOT,
        model_index=model_index,
    )

    dynamic_models = validate_manifest(
        manifest_name="dynamic_manifest",
        manifest_data=dynamic_data,
        expected_static=False,
        counters=counters,
        errors=errors,
        warnings=warnings,
        info=info,
        manifest_dir=DYNAMIC_MANIFEST_PATH.parent,
        project_root=PROJECT_ROOT,
        models_root=MODELS_ROOT,
        model_index=model_index,
    )

    if "factory_shell" not in static_models:
        # The static baseline is expected to contain the full shell geometry.
        # Missing it would invalidate every later RT export.
        add_issue(
            errors,
            "static_manifest",
            "root",
            "static_manifest must contain model 'factory_shell'",
        )

    unexpected_dynamic_models = sorted(dynamic_models - ALLOWED_DYNAMIC_MODELS)
    missing_dynamic_models = sorted(ALLOWED_DYNAMIC_MODELS - dynamic_models)

    # The current validated rigid dynamic path is intentionally narrow: Panda
    # and ur5_rg2 only. Actor experiments are tracked separately in spike scripts.
    if unexpected_dynamic_models:
        add_issue(
            errors,
            "dynamic_manifest",
            "root",
            f"dynamic_manifest contains unexpected models: {', '.join(unexpected_dynamic_models)}",
        )

    if missing_dynamic_models:
        add_issue(
            errors,
            "dynamic_manifest",
            "root",
            f"dynamic_manifest is missing expected models: {', '.join(missing_dynamic_models)}",
        )

    static_count = len(static_data) if isinstance(static_data, list) else 0
    dynamic_count = len(dynamic_data) if isinstance(dynamic_data, list) else 0
    summary = create_summary(
        static_manifest_models=static_count,
        dynamic_manifest_models=dynamic_count,
        counters=counters,
        errors=errors,
        warnings=warnings,
        info=info,
    )

    report = {
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }
    # Persist the machine-readable report before printing the human-readable
    # summary so the artifact exists even if stdout is truncated.
    write_report(REPORT_PATH, report)

    print("Manifest validation summary")
    print("===========================")
    print(f"Static manifest models:  {summary['static_manifest_models']}")
    print(f"Dynamic manifest models: {summary['dynamic_manifest_models']}")
    print(f"Total links:             {summary['total_links']}")
    print(f"Total visuals:           {summary['total_visuals']}")
    print("Geometry counts:")
    for geometry_name in ALLOWED_GEOMETRY_TYPES:
        print(f"  - {geometry_name}: {summary['geometry_counts'][geometry_name]}")
    print_issue_group("Errors", errors)
    print_issue_group("Warnings", warnings)
    print_issue_group("Info", info)
    print(f"Report written to: {REPORT_PATH}")

    if errors:
        print(f"Validation FAILED with {len(errors)} error(s).")
        return 1

    print(f"Validation PASSED with {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
