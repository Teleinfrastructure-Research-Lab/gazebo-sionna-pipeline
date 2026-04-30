#!/usr/bin/env python3
"""Orchestrate the frozen static-scene merge pass material by material.

This script prepares Blender jobs, groups ready static records by semantic
material class, launches the merge worker, and collates the merged outputs into
the canonical static manifest used by XML generation and RT sanity runs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_GEOMETRY = {"mesh", "box", "sphere", "cylinder"}
SUPPORTED_SCENE_MESH_EXTENSIONS = {".ply", ".obj", ".dae", ".stl", ".glb", ".gltf"}


def load_json(path: Path) -> Any:
    # This orchestrator exchanges JSON between the registry, the Blender worker,
    # and the final merged manifest, so keep JSON IO in one small helper.
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Any) -> None:
    # Persist intermediate artifacts so a failed Blender run can be inspected
    # without rerunning the full static merge step.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    out = []
    for ch in str(text):
        out.append(ch.lower() if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


def blender_candidates() -> list[Path]:
    # Search explicit environment configuration first, then PATH, then the
    # project-local Blender locations used on this machine.
    candidates: list[Path] = []

    env_path = os.environ.get("BLENDER")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    which_path = shutil.which("blender")
    if which_path:
        candidates.append(Path(which_path))

    project_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            project_root / "blender-4.5.8-linux-x64" / "blender",
            project_root.parent / "blender-4.5.8-linux-x64" / "blender",
            Path.home() / "Documents" / "blender-4.5.8-linux-x64" / "blender",
        ]
    )
    return candidates


def resolve_blender_path(requested: Path | None = None) -> Path:
    # Fail before preparing any job payloads if Blender cannot be found, because
    # the static baseline merge depends on Blender for every output mesh.
    if requested is not None:
        candidate = requested.expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

        which_path = shutil.which(str(candidate))
        if which_path:
            return Path(which_path).resolve()

        raise FileNotFoundError(
            f"Blender executable does not exist or is not executable: {candidate}"
        )

    checked: list[str] = []
    for candidate in blender_candidates():
        checked.append(str(candidate))
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "Could not find Blender executable. Set BLENDER or pass --blender. "
        f"Checked: {checked}"
    )


def parse_float_list(value: Any, *, field: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{field} must be a list with {length} elements")
    out: list[float] = []
    for idx, item in enumerate(value):
        try:
            out.append(float(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field}[{idx}] must be numeric") from exc
    return out


def parse_matrix44(value: Any, *, field: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{field} must be a 4x4 matrix")

    rows: list[list[float]] = []
    for row_idx, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError(f"{field}[{row_idx}] must contain 4 elements")
        rows.append(parse_float_list(row, field=f"{field}[{row_idx}]", length=4))
    return rows


def normalize_mesh_path(value: Any) -> str:
    if not value:
        raise ValueError("mesh entry is missing scene_mesh_path")

    mesh_path = Path(str(value)).expanduser().resolve()
    if mesh_path.suffix.lower() not in SUPPORTED_SCENE_MESH_EXTENSIONS:
        raise ValueError(f"Unsupported scene mesh extension: {mesh_path.suffix}")
    if not mesh_path.exists():
        raise ValueError(f"scene_mesh_path does not exist: {mesh_path}")
    return str(mesh_path)


def member_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": entry["id"],
        "model_name": entry["model_name"],
        "link_name": entry["link_name"],
        "visual_name": entry["visual_name"],
        "geometry_type": entry["geometry_type"],
        "material_class": entry["material_class"],
        "status": entry["status"],
        "to_world": entry["to_world"],
    }

    if entry["geometry_type"] == "mesh":
        record["scene_mesh_path"] = entry["scene_mesh_path"]
    if entry["geometry_type"] == "box":
        record["size"] = entry["size"]
    if entry["geometry_type"] == "sphere":
        record["radius"] = entry["radius"]
    if entry["geometry_type"] == "cylinder":
        record["radius"] = entry["radius"]
        record["length"] = entry["length"]
    return record


def normalize_ready_entry(raw: Any, *, index: int) -> dict[str, Any]:
    # static_registry.json may contain skipped or unresolved items. This stage
    # only accepts entries already marked ready by the validated registry builder.
    if not isinstance(raw, dict):
        raise ValueError(f"Entry #{index} must be an object")

    status = str(raw.get("status", "")).strip()
    if status != "ready":
        raise ValueError(f"Entry #{index} must have status=ready, got {status!r}")

    geometry_type = str(raw.get("geometry_type", "")).strip().lower()
    if geometry_type not in SUPPORTED_GEOMETRY:
        raise ValueError(
            f"Entry #{index} has unsupported geometry_type={geometry_type!r}"
        )

    material_class = str(raw.get("material_class", "")).strip()
    if not material_class:
        raise ValueError(f"Entry #{index} is missing material_class")

    entry_id = str(raw.get("id") or slugify(f"entry_{index}"))
    normalized: dict[str, Any] = {
        "id": entry_id,
        "model_name": str(raw.get("model_name", "")),
        "link_name": str(raw.get("link_name", "")),
        "visual_name": str(raw.get("visual_name", "")),
        "geometry_type": geometry_type,
        "material_class": material_class,
        "status": status,
        "to_world": parse_matrix44(raw.get("to_world"), field=f"entries[{index}].to_world"),
    }

    if geometry_type == "mesh":
        # Mesh entries already point at concrete converted scene meshes that the
        # Blender worker can import directly.
        normalized["scene_mesh_path"] = normalize_mesh_path(raw.get("scene_mesh_path"))
        normalized["uri"] = raw.get("uri")
        normalized["resolved_path"] = raw.get("resolved_path")
    elif geometry_type == "box":
        normalized["size"] = parse_float_list(
            raw.get("size"),
            field=f"entries[{index}].size",
            length=3,
        )
        if any(value <= 0 for value in normalized["size"]):
            raise ValueError(f"entries[{index}].size must be strictly positive")
    elif geometry_type == "sphere":
        try:
            normalized["radius"] = float(raw.get("radius"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"entries[{index}].radius must be numeric") from exc
        if normalized["radius"] <= 0:
            raise ValueError(f"entries[{index}].radius must be strictly positive")
    elif geometry_type == "cylinder":
        try:
            normalized["radius"] = float(raw.get("radius"))
            normalized["length"] = float(raw.get("length"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"entries[{index}] cylinder radius/length must be numeric"
            ) from exc
        if normalized["radius"] <= 0 or normalized["length"] <= 0:
            raise ValueError(
                f"entries[{index}] cylinder radius and length must be strictly positive"
            )

    return normalized


def load_ready_entries(registry_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    # Read the frozen static registry and retain only the geometry that is ready
    # to be merged into the canonical baseline scene.
    data = load_json(registry_path)
    if not isinstance(data, dict):
        raise ValueError("static_registry.json must contain a JSON object")

    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("static_registry.json must contain an entries list")

    root_raw = data.get("root")
    if root_raw:
        root = Path(str(root_raw)).expanduser().resolve()
    else:
        root = registry_path.resolve().parents[2]

    ready_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("status") == "ready":
            ready_entries.append(normalize_ready_entry(entry, index=index))

    if not ready_entries:
        raise ValueError("No ready static entries were found in static_registry.json")

    return data, ready_entries, root


def group_by_material(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    # Merge by semantic material class so the downstream Mitsuba and Sionna XML
    # builders can attach one material definition per merged mesh.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        grouped.setdefault(entry["material_class"], []).append(entry)

    for material_class, material_entries in grouped.items():
        material_entries.sort(key=lambda item: item["id"])
        if not material_class:
            raise ValueError("Found empty material_class during grouping")
    return dict(sorted(grouped.items()))


def build_job_payload(
    *,
    root: Path,
    registry_path: Path,
    out_dir: Path,
    merged_dir: Path,
    individual_dir: Path | None,
    export_individual: bool,
    grouped_entries: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    # Package the fully resolved inputs and outputs into a single JSON payload so
    # the Blender worker can run without importing repository state.
    return {
        "root": str(root),
        "inputs": {
            "static_registry": str(registry_path),
        },
        "output": {
            "out_dir": str(out_dir),
            "merged_dir": str(merged_dir),
            "individual_dir": str(individual_dir) if individual_dir else None,
        },
        "export_individual": export_individual,
        "material_groups": [
            {
                "material_class": material_class,
                "entries": entries,
            }
            for material_class, entries in grouped_entries.items()
        ],
    }


def run_blender_job(
    *,
    blender_path: Path,
    helper_path: Path,
    job_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    # The worker writes a structured result JSON. Treat that file as the
    # authoritative success/failure record instead of scraping stdout.
    if not blender_path.exists() and blender_path.name != "blender":
        raise FileNotFoundError(f"Blender binary does not exist: {blender_path}")
    if not helper_path.exists():
        raise FileNotFoundError(f"Blender helper script does not exist: {helper_path}")

    cmd = [
        str(blender_path),
        "--background",
        "--factory-startup",
        "--python",
        str(helper_path),
        "--",
        str(job_path),
        str(result_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if not result_path.exists():
        message = "Blender helper did not produce a result file."
        if result.stdout.strip():
            message += f"\nstdout:\n{result.stdout.strip()}"
        if result.stderr.strip():
            message += f"\nstderr:\n{result.stderr.strip()}"
        raise RuntimeError(message)

    payload = load_json(result_path)
    if not isinstance(payload, dict):
        raise RuntimeError("Blender helper result must be a JSON object")

    if result.returncode != 0 or not payload.get("ok", False):
        message = "Blender helper failed."
        if payload.get("errors"):
            message += f"\nerrors:\n{json.dumps(payload['errors'], indent=2)}"
        if result.stdout.strip():
            message += f"\nstdout:\n{result.stdout.strip()}"
        if result.stderr.strip():
            message += f"\nstderr:\n{result.stderr.strip()}"
        raise RuntimeError(message)

    return payload


def build_merged_manifest(
    *,
    root: Path,
    registry_path: Path,
    blender_path: Path,
    helper_path: Path,
    job_path: Path,
    result_path: Path,
    export_individual: bool,
    ready_entries: list[dict[str, Any]],
    grouped_entries: dict[str, list[dict[str, Any]]],
    blender_result: dict[str, Any],
) -> dict[str, Any]:
    # Convert the worker's per-material export summary into the canonical merged
    # static manifest consumed by both XML builders.
    raw_groups = blender_result.get("groups")
    if not isinstance(raw_groups, list):
        raise RuntimeError("Blender result is missing the groups list")

    raw_errors = blender_result.get("errors", [])
    if raw_errors:
        raise RuntimeError("Blender result contains hard errors")

    by_material = {}
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            raise RuntimeError("Each Blender result group must be an object")
        material_class = str(raw_group.get("material_class", "")).strip()
        merged_mesh_path = Path(str(raw_group.get("merged_mesh_path", ""))).expanduser()
        if not material_class or not merged_mesh_path.exists():
            raise RuntimeError(
                f"Invalid Blender result for material {material_class!r}: {merged_mesh_path}"
            )
        by_material[material_class] = raw_group

    merged_groups: list[dict[str, Any]] = []
    for material_class, entries in grouped_entries.items():
        # Preserve per-entry provenance so merged meshes can still be traced back
        # to the original validated registry records.
        if material_class not in by_material:
            raise RuntimeError(
                f"Blender did not return an export result for material {material_class!r}"
            )

        group_result = by_material[material_class]
        merged_groups.append(
            {
                "material_class": material_class,
                "entry_count": len(entries),
                "geometry_types": sorted({entry["geometry_type"] for entry in entries}),
                "merged_mesh_path": str(
                    Path(str(group_result["merged_mesh_path"])).expanduser().resolve()
                ),
                "vertex_count": int(group_result.get("vertex_count", 0)),
                "triangle_count": int(group_result.get("triangle_count", 0)),
                "members": [member_metadata(entry) for entry in entries],
            }
        )

    return {
        "root": str(root),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "static_registry": str(registry_path),
            "blender": str(blender_path),
            "helper_script": str(helper_path),
            "blender_job": str(job_path),
            "blender_result": str(result_path),
        },
        "summary": {
            "ready_input_entries": len(ready_entries),
            "material_groups": len(merged_groups),
            "export_individual": export_individual,
            "exported_individual_meshes": int(
                blender_result.get("summary", {}).get("exported_individual_meshes", 0)
            ),
        },
        "merged_groups": merged_groups,
        "hard_errors": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge ready static geometry by material using Blender."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="Path to static_registry.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for merged static scene data",
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=None,
        help="Path to the Blender executable. Defaults to BLENDER, PATH, then repo-local candidates.",
    )
    parser.add_argument(
        "--helper",
        type=Path,
        default=None,
        help="Path to the Blender helper script",
    )
    parser.add_argument(
        "--export-individual",
        action="store_true",
        help="Also export transformed per-entry debug meshes",
    )
    parser.add_argument(
        "--manifest-name",
        default="merged_static_manifest.json",
        help="Output manifest filename inside --out-dir",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve the static registry first. Its embedded root lets the merge stage
    # survive repo moves while still using the validated asset locations.
    if args.registry is None:
        root = Path(__file__).resolve().parents[2]
        registry_path = root / "rt_out" / "manifests" / "static_registry.json"
    else:
        registry_path = args.registry.expanduser().resolve()

    _, ready_entries, root = load_ready_entries(registry_path)

    if args.out_dir is None:
        out_dir = root / "rt_out" / "static_scene" / "export"
    else:
        out_dir = args.out_dir.expanduser().resolve()

    if args.helper is None:
        helper_path = Path(__file__).resolve().with_name("21_merge_static_scene_blender_worker.py")
    else:
        helper_path = args.helper.expanduser().resolve()

    blender_path = resolve_blender_path(args.blender)
    merged_dir = out_dir / "merged_by_material"
    debug_dir = out_dir / "debug"
    individual_dir = out_dir / "transformed_individual" if args.export_individual else None
    # Keep the manifest filename configurable, but require it to stay within the
    # chosen output directory so the export layout remains predictable.
    manifest_name = str(args.manifest_name).strip()
    if not manifest_name:
        raise ValueError("--manifest-name must be a non-empty filename")
    if Path(manifest_name).name != manifest_name:
        raise ValueError("--manifest-name must be a filename, not a path")
    manifest_path = out_dir / manifest_name
    job_path = debug_dir / "merge_job.json"
    result_path = debug_dir / "merge_result.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    merged_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    if individual_dir:
        individual_dir.mkdir(parents=True, exist_ok=True)

    # Remove any stale worker result so a previous success JSON cannot mask a
    # fresh Blender failure.
    if result_path.exists():
        result_path.unlink()

    # Group the ready entries before entering Blender so the worker can stay
    # focused on geometry import/merge instead of material bookkeeping.
    grouped_entries = group_by_material(ready_entries)
    job_payload = build_job_payload(
        root=root,
        registry_path=registry_path,
        out_dir=out_dir,
        merged_dir=merged_dir,
        individual_dir=individual_dir,
        export_individual=args.export_individual,
        grouped_entries=grouped_entries,
    )
    save_json(job_path, job_payload)

    blender_result = run_blender_job(
        blender_path=blender_path,
        helper_path=helper_path,
        job_path=job_path,
        result_path=result_path,
    )

    # Only after Blender succeeds do we mint the frozen merged static manifest
    # that later Mitsuba/Sionna stages treat as the baseline scene.
    manifest = build_merged_manifest(
        root=root,
        registry_path=registry_path,
        blender_path=blender_path,
        helper_path=helper_path,
        job_path=job_path,
        result_path=result_path,
        export_individual=args.export_individual,
        ready_entries=ready_entries,
        grouped_entries=grouped_entries,
        blender_result=blender_result,
    )
    save_json(manifest_path, manifest)

    print(f"Loaded ready entries  : {len(ready_entries)}")
    print(f"Material groups      : {len(grouped_entries)}")
    print(f"Merged manifest      : {manifest_path}")
    print(f"Merged mesh directory: {merged_dir}")
    if individual_dir:
        print(f"Debug mesh directory : {individual_dir}")


if __name__ == "__main__":
    main()
