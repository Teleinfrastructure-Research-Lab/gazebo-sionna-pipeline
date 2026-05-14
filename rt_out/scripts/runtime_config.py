#!/usr/bin/env python3
"""Shared runtime/path discovery helpers for RT and Blender wrappers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "rt_out" / "scripts"
STATIC_SCENE_SCRIPTS = SCRIPTS_ROOT / "static_scene"
DYNAMIC_RIGID_SCRIPTS = SCRIPTS_ROOT / "dynamic_rigid"
DYNAMIC_ACTOR_SCRIPTS = SCRIPTS_ROOT / "dynamic_actor"
EXPERIMENT_SCRIPTS = SCRIPTS_ROOT / "experiments"
VALIDATION_SCRIPTS = SCRIPTS_ROOT / "validation"

SCRIPT_24_RUN_SIONNA_RT_SANITY = STATIC_SCENE_SCRIPTS / "24_run_sionna_rt_sanity.py"
SCRIPT_32_EXPORT_DYNAMIC_FRAME_MESHES = DYNAMIC_RIGID_SCRIPTS / "32_export_dynamic_frame_meshes.py"
SCRIPT_33_COMPOSE_FRAME_SCENE = DYNAMIC_RIGID_SCRIPTS / "33_compose_prototype_frame_scene.py"
SCRIPT_34_BUILD_FRAME_SIONNA_XML = DYNAMIC_RIGID_SCRIPTS / "34_build_prototype_frame_sionna_xml.py"
SCRIPT_42_EXPORT_ACTOR_FRAME_MESHES = DYNAMIC_ACTOR_SCRIPTS / "42_export_actor_frame_meshes.py"
SCRIPT_ACTOR_BLENDER_EXPORT_FRAME_MESHES = (
    DYNAMIC_ACTOR_SCRIPTS / "actor_blender_export_frame_meshes.py"
)

DEFAULT_SIONNA_ENV_NAMES = ("sionna", "sionna-rt", "collabpaper")
MPLCONFIGDIR_DEFAULT = Path("/tmp/matplotlib-sionna")
DRJIT_CACHE_DIR_DEFAULT = Path("/tmp/drjit-sionna")


class RuntimeConfigError(RuntimeError):
    """Raised when a required runtime dependency cannot be discovered."""


def _path_variants(value: str | Path) -> Iterable[Path]:
    text = str(value).strip()
    if not text:
        return []

    path = Path(text).expanduser()
    variants: list[Path] = []
    if path.is_absolute():
        variants.append(path)
    else:
        variants.append(path)
        variants.append((PROJECT_ROOT / path).expanduser())
    return variants


def _executable_candidates(value: str | Path) -> list[Path]:
    text = str(value).strip()
    if not text:
        return []

    candidates: list[Path] = []
    which_path = shutil.which(text)
    if which_path:
        candidates.append(Path(which_path))
    for candidate in _path_variants(text):
        candidates.append(candidate)
    return candidates


def _existing_file_candidates(candidates: Iterable[Path]) -> list[Path]:
    existing: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        try:
            if resolved.exists() and resolved.is_file():
                resolved = resolved.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    existing.append(resolved)
        except OSError:
            continue
    return existing


def _python_supports_sionna(python_path: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import sionna.rt"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _current_python_supports_sionna() -> bool:
    try:
        import sionna.rt  # noqa: F401
    except Exception:
        return False
    return True


def _legacy_conda_python_candidates() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []
    for base in (home / "miniconda3", home / "anaconda3"):
        for env_name in DEFAULT_SIONNA_ENV_NAMES:
            candidates.append(base / "envs" / env_name / "bin" / "python")
    return candidates


def find_sionna_python(explicit: str | Path | None = None) -> Path:
    """Locate a Python interpreter that can import ``sionna.rt``.

    Search order:
    1. explicit argument
    2. ``SIONNA_PYTHON``
    3. ``COLLABPAPER_PYTHON`` (legacy compatibility)
    4. current interpreter, if it already imports ``sionna.rt``
    5. common conda env names under ``~/miniconda3`` and ``~/anaconda3``
    """

    checked: list[str] = []

    for label, value in (
        ("explicit", explicit),
        ("SIONNA_PYTHON", os.environ.get("SIONNA_PYTHON")),
        ("COLLABPAPER_PYTHON", os.environ.get("COLLABPAPER_PYTHON")),
    ):
        if value is None:
            continue
        candidates = _existing_file_candidates(_executable_candidates(value))
        checked.extend(f"{label}:{candidate}" for candidate in candidates)
        for candidate in candidates:
            if _python_supports_sionna(candidate):
                return candidate

    current_python = Path(sys.executable).resolve()
    checked.append(f"current:{current_python}")
    if _current_python_supports_sionna():
        return current_python

    for candidate in _existing_file_candidates(_legacy_conda_python_candidates()):
        checked.append(f"candidate:{candidate}")
        if _python_supports_sionna(candidate):
            return candidate

    raise RuntimeConfigError(
        "Could not find a Python interpreter with sionna.rt. "
        "Set SIONNA_PYTHON or the legacy COLLABPAPER_PYTHON, or run the wrapper "
        f"with a Sionna-capable interpreter. Checked: {checked}"
    )


def _blender_fallback_candidates() -> list[Path]:
    roots = [
        PROJECT_ROOT,
        PROJECT_ROOT.parent,
        Path.cwd(),
        Path.cwd().parent,
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home() / "Applications",
    ]
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "tools" / "blender" / "blender")
        if root.exists():
            for directory in sorted(root.glob("blender*")):
                candidates.append(directory / "blender")
    return candidates


def find_blender(explicit: str | Path | None = None) -> Path:
    """Locate a Blender executable for geometry export / scene inspection."""

    checked: list[str] = []
    ordered_values = [explicit]
    blender_env = os.environ.get("BLENDER")
    if blender_env:
        ordered_values.append(blender_env)
    ordered_values.append("blender")

    for value in ordered_values:
        if value is None:
            continue
        for candidate in _existing_file_candidates(_executable_candidates(value)):
            checked.append(str(candidate))
            return candidate

    for candidate in _existing_file_candidates(_blender_fallback_candidates()):
        checked.append(str(candidate))
        return candidate

    raise RuntimeConfigError(
        "Could not find Blender executable. Set BLENDER, pass --blender, or "
        f"install Blender in a standard location. Checked: {checked}"
    )


def runtime_env() -> dict[str, str]:
    """Return an environment with stable per-run cache/config directories."""

    env = os.environ.copy()
    MPLCONFIGDIR_DEFAULT.mkdir(parents=True, exist_ok=True)
    DRJIT_CACHE_DIR_DEFAULT.mkdir(parents=True, exist_ok=True)
    env["MPLCONFIGDIR"] = str(MPLCONFIGDIR_DEFAULT)
    env["DRJIT_CACHE_DIR"] = str(DRJIT_CACHE_DIR_DEFAULT)
    return env

