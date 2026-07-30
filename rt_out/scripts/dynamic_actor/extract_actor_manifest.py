#!/usr/bin/env python3
"""Extract Gazebo actor metadata into a dedicated RT actor manifest.

This stage is intentionally separate from the validated rigid Panda/UR5
pipeline. It reads world-level <actor> elements, resolves their skin and
animation assets, captures script/trajectory metadata, and writes a manifest
that later actor-only export stages can consume.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORLD_PATH = PROJECT_ROOT / "myworld_rt.sdf"
DEFAULT_MODELS_ROOT = PROJECT_ROOT / "models"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "manifests" / "actor_manifest.json"
ZERO_POSE = "0 0 0 0 0 0"


class ActorManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedUri:
    uri: str
    resolved_path: str | None
    status: str
    candidates: list[str]
    warning: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract world-level Gazebo <actor> entries into actor_manifest.json."
    )
    parser.add_argument(
        "--world",
        type=Path,
        default=DEFAULT_WORLD_PATH,
        help="World SDF containing top-level <actor> entries.",
    )
    parser.add_argument(
        "--models-root",
        type=Path,
        default=DEFAULT_MODELS_ROOT,
        help="Root directory used to resolve model:// actor assets.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output actor manifest JSON path.",
    )
    return parser.parse_args()


def pose_text_to_list(text: str, label: str) -> list[float]:
    parts = text.strip().split()
    if len(parts) != 6:
        raise ActorManifestError(f"{label} must contain 6 pose values, got {text!r}")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        raise ActorManifestError(f"{label} contains non-numeric pose values: {text!r}") from exc


def parse_optional_float(text: str | None, default: float, label: str) -> float:
    if text is None or not text.strip():
        return default
    try:
        return float(text.strip())
    except ValueError as exc:
        raise ActorManifestError(f"{label} must be numeric, got {text!r}") from exc


def parse_bool_text(text: str | None, default: bool = False) -> bool:
    if text is None:
        return default
    return text.strip().lower() == "true"


def as_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_model_uri(uri: str, *, models_root: Path, world_parent: Path) -> ResolvedUri:
    uri = uri.strip()
    if not uri:
        return ResolvedUri(uri=uri, resolved_path=None, status="missing", candidates=[])

    if uri.startswith("model://"):
        relative = uri[len("model://") :]
        model_name, separator, suffix = relative.partition("/")
        if not model_name or not separator or not suffix:
            return ResolvedUri(
                uri=uri,
                resolved_path=None,
                status="malformed",
                candidates=[],
                warning=f"Malformed model URI: {uri}",
            )

        direct = models_root / model_name / suffix
        candidates: list[Path] = []
        if direct.exists():
            candidates.append(direct)

        for model_dir in models_root.rglob(model_name):
            if not model_dir.is_dir():
                continue
            candidate = model_dir / suffix
            if candidate.exists() and candidate not in candidates:
                candidates.append(candidate)

        resolved_candidates = sorted(path.resolve() for path in candidates)
        candidate_strings = [str(path) for path in resolved_candidates]
        if not resolved_candidates:
            return ResolvedUri(uri=uri, resolved_path=None, status="missing", candidates=[])
        if len(resolved_candidates) > 1:
            return ResolvedUri(
                uri=uri,
                resolved_path=str(resolved_candidates[0]),
                status="ambiguous",
                candidates=candidate_strings,
                warning=f"Ambiguous URI {uri}; selected {resolved_candidates[0]}",
            )
        return ResolvedUri(
            uri=uri,
            resolved_path=str(resolved_candidates[0]),
            status="resolved",
            candidates=candidate_strings,
        )

    path = Path(uri).expanduser()
    if not path.is_absolute():
        path = world_parent / path
    if path.exists():
        resolved = str(path.resolve())
        return ResolvedUri(uri=uri, resolved_path=resolved, status="resolved", candidates=[resolved])
    return ResolvedUri(uri=uri, resolved_path=None, status="missing", candidates=[str(path)])


def parse_waypoint(
    waypoint_elem: ET.Element,
    *,
    actor_name: str,
    trajectory_index: int,
    waypoint_index: int,
) -> dict[str, Any]:
    time_text = waypoint_elem.findtext("time")
    pose_text = waypoint_elem.findtext("pose")
    label = f"actor {actor_name} trajectory[{trajectory_index}] waypoint[{waypoint_index}]"
    if time_text is None or pose_text is None:
        raise ActorManifestError(f"{label} must contain both <time> and <pose>")
    return {
        "time_seconds": parse_optional_float(time_text, 0.0, f"{label}.time"),
        "pose": pose_text.strip(),
        "pose6": pose_text_to_list(pose_text, f"{label}.pose"),
    }


def parse_trajectory(
    trajectory_elem: ET.Element,
    *,
    actor_name: str,
    trajectory_index: int,
) -> dict[str, Any]:
    waypoints = [
        parse_waypoint(
            waypoint,
            actor_name=actor_name,
            trajectory_index=trajectory_index,
            waypoint_index=index,
        )
        for index, waypoint in enumerate(trajectory_elem.findall("waypoint"))
    ]
    times = [waypoint["time_seconds"] for waypoint in waypoints]
    duration = times[-1] - times[0] if len(times) >= 2 else 0.0
    return {
        "id": trajectory_elem.get("id"),
        "type": trajectory_elem.get("type"),
        "tension": parse_optional_float(
            trajectory_elem.get("tension"),
            0.0,
            f"actor {actor_name} trajectory[{trajectory_index}].tension",
        ),
        "waypoint_count": len(waypoints),
        "duration_seconds": duration,
        "waypoints_time_sorted": times == sorted(times),
        "waypoints": waypoints,
    }


def parse_script(actor_elem: ET.Element, actor_name: str) -> dict[str, Any]:
    script_elem = actor_elem.find("script")
    if script_elem is None:
        return {
            "present": False,
            "loop": False,
            "delay_start": 0.0,
            "auto_start": False,
            "trajectory_count": 0,
            "trajectories": [],
        }

    trajectories = [
        parse_trajectory(trajectory, actor_name=actor_name, trajectory_index=index)
        for index, trajectory in enumerate(script_elem.findall("trajectory"))
    ]
    return {
        "present": True,
        "loop": parse_bool_text(script_elem.findtext("loop"), default=False),
        "delay_start": parse_optional_float(
            script_elem.findtext("delay_start"),
            0.0,
            f"actor {actor_name} script.delay_start",
        ),
        "auto_start": parse_bool_text(script_elem.findtext("auto_start"), default=False),
        "trajectory_count": len(trajectories),
        "trajectories": trajectories,
    }


def parse_animation(
    anim_elem: ET.Element,
    *,
    actor_name: str,
    animation_index: int,
    models_root: Path,
    world_parent: Path,
) -> dict[str, Any]:
    uri = (anim_elem.findtext("filename") or "").strip()
    resolved = resolve_model_uri(uri, models_root=models_root, world_parent=world_parent)
    return {
        "name": anim_elem.get("name"),
        "filename": uri,
        "uri": uri,
        "resolved_path": resolved.resolved_path,
        "uri_status": resolved.status,
        "uri_candidates": resolved.candidates,
        "interpolate_x": parse_bool_text(anim_elem.findtext("interpolate_x"), default=False),
        "index": animation_index,
    }


def parse_actor(actor_elem: ET.Element, *, models_root: Path, world_parent: Path) -> dict[str, Any]:
    actor_name = actor_elem.get("name")
    if not actor_name or not actor_name.strip():
        raise ActorManifestError("Encountered world-level <actor> without a non-empty name")
    actor_name = actor_name.strip()

    pose_text = actor_elem.findtext("pose", default=ZERO_POSE).strip()

    skin_elem = actor_elem.find("skin")
    skin_uri = (skin_elem.findtext("filename") if skin_elem is not None else "") or ""
    skin_uri = skin_uri.strip()
    skin_resolved = resolve_model_uri(skin_uri, models_root=models_root, world_parent=world_parent)
    skin_scale = parse_optional_float(
        skin_elem.findtext("scale") if skin_elem is not None else None,
        1.0,
        f"actor {actor_name} skin.scale",
    )

    animations = [
        parse_animation(
            animation,
            actor_name=actor_name,
            animation_index=index,
            models_root=models_root,
            world_parent=world_parent,
        )
        for index, animation in enumerate(actor_elem.findall("animation"))
    ]
    primary_animation = animations[0] if animations else None
    script = parse_script(actor_elem, actor_name)
    has_trajectory = any(item["waypoint_count"] > 0 for item in script["trajectories"])

    validation_warnings = []
    for resolved in [skin_resolved]:
        if resolved.warning:
            validation_warnings.append(resolved.warning)
    for animation in animations:
        if animation["uri_status"] == "ambiguous":
            validation_warnings.append(
                f"Ambiguous URI {animation['uri']}; selected {animation['resolved_path']}"
            )
        if animation["uri_status"] in {"missing", "malformed"}:
            validation_warnings.append(
                f"Animation URI {animation['uri']!r} for actor {actor_name} is {animation['uri_status']}"
            )
    if skin_resolved.status in {"missing", "malformed"}:
        validation_warnings.append(f"Skin URI {skin_uri!r} for actor {actor_name} is {skin_resolved.status}")
    for trajectory in script["trajectories"]:
        if not trajectory["waypoints_time_sorted"]:
            validation_warnings.append(
                f"Actor {actor_name} trajectory {trajectory['id']!r} waypoint times are not sorted"
            )

    return {
        "actor_name": actor_name,
        "pose": pose_text,
        "pose6": pose_text_to_list(pose_text, f"actor {actor_name}.pose"),
        "skin": {
            "filename": skin_uri,
            "uri": skin_uri,
            "resolved_path": skin_resolved.resolved_path,
            "uri_status": skin_resolved.status,
            "uri_candidates": skin_resolved.candidates,
            "scale": skin_scale,
        },
        "animation": primary_animation,
        "animations": animations,
        "script": script,
        "validation": {
            "has_skin": skin_elem is not None,
            "has_animation": bool(animations),
            "has_trajectory": has_trajectory,
            "is_static_no_trajectory": not has_trajectory,
            "warnings": validation_warnings,
        },
    }


def count_uri_statuses(actors: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"resolved": 0, "missing": 0, "ambiguous": 0, "malformed": 0}
    for actor in actors:
        statuses = [actor["skin"]["uri_status"]]
        statuses.extend(animation["uri_status"] for animation in actor["animations"])
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
    return counts


def build_manifest(world_path: Path, models_root: Path) -> dict[str, Any]:
    try:
        root = ET.parse(world_path).getroot()
    except FileNotFoundError as exc:
        raise ActorManifestError(f"World file does not exist: {world_path}") from exc
    except ET.ParseError as exc:
        raise ActorManifestError(f"Invalid world SDF/XML in {world_path}: {exc}") from exc

    world = root.find("world")
    if world is None:
        raise ActorManifestError(f"{world_path} does not contain a <world> element")

    actor_elems = world.findall("actor")
    actors = [
        parse_actor(actor_elem, models_root=models_root, world_parent=world_path.parent)
        for actor_elem in actor_elems
    ]

    names = [actor["actor_name"] for actor in actors]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ActorManifestError(f"Duplicate actor names in world: {duplicate_names}")

    uri_counts = count_uri_statuses(actors)
    warnings = [
        warning
        for actor in actors
        for warning in actor["validation"].get("warnings", [])
    ]

    return {
        "generated_by": Path(__file__).name,
        "world_path": str(world_path.resolve()),
        "models_root": str(models_root.resolve()),
        "actors": actors,
        "validation_summary": {
            "actor_count": len(actors),
            "resolved_uri_count": uri_counts.get("resolved", 0),
            "missing_uri_count": uri_counts.get("missing", 0) + uri_counts.get("malformed", 0),
            "ambiguous_uri_count": uri_counts.get("ambiguous", 0),
            "trajectory_actor_count": sum(1 for actor in actors if actor["validation"]["has_trajectory"]),
            "static_no_trajectory_actor_count": sum(
                1 for actor in actors if actor["validation"]["is_static_no_trajectory"]
            ),
            "warning_count": len(warnings),
            "warnings": warnings,
        },
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    world_path = args.world.expanduser()
    if not world_path.is_absolute():
        world_path = PROJECT_ROOT / world_path
    world_path = world_path.resolve()

    models_root = args.models_root.expanduser()
    if not models_root.is_absolute():
        models_root = PROJECT_ROOT / models_root
    models_root = models_root.resolve()

    output_path = args.output.expanduser()
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path = output_path.resolve()

    try:
        manifest = build_manifest(world_path, models_root)
        write_json(output_path, manifest)
    except ActorManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = manifest["validation_summary"]
    print("Actor manifest extraction")
    print(f"world: {world_path}")
    print(f"models_root: {models_root}")
    print(f"output: {output_path}")
    print(f"actor_count: {summary['actor_count']}")
    print(f"resolved_uri_count: {summary['resolved_uri_count']}")
    print(f"missing_uri_count: {summary['missing_uri_count']}")
    print(f"ambiguous_uri_count: {summary['ambiguous_uri_count']}")
    print(f"trajectory_actor_count: {summary['trajectory_actor_count']}")
    print(f"static_no_trajectory_actor_count: {summary['static_no_trajectory_actor_count']}")
    print(f"warning_count: {summary['warning_count']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
