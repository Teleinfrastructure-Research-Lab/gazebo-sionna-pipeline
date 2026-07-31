"""Shared run-local locations for the legacy three-frame RT harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from experiment_paths import PROJECT_ROOT, ExperimentPathError, run_output


FACTORY_EXPERIMENT_ROOT = (
    PROJECT_ROOT
    / "rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045"
)


@dataclass(frozen=True)
class ThreeFramePaths:
    experiment_root: Path
    dynamic_root: Path
    composed_root: Path
    static_manifest: Path
    actor_samples: Path
    actor_manifest: Path
    radio_sites: Path
    dynamic_prototype_config: Path
    rt_runtime_config: Path


def resolve_cli_path(value: str | Path) -> Path:
    """Resolve explicit repository-relative paths independently of cwd."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def resolve_three_frame_paths(
    experiment_root: str | Path | None,
) -> tuple[ThreeFramePaths, bool]:
    """Return run-local paths and whether a legacy default was selected."""

    legacy_default = experiment_root is None
    root = FACTORY_EXPERIMENT_ROOT if legacy_default else resolve_cli_path(experiment_root)
    if root.exists() and not root.is_dir():
        raise ExperimentPathError(f"Experiment root is not a directory: {root}")
    if not root.is_dir():
        raise ExperimentPathError(f"Experiment root does not exist: {root}")
    return (
        ThreeFramePaths(
            experiment_root=root,
            dynamic_root=run_output(root, "dynamic_scene"),
            composed_root=run_output(root, "composed_scene"),
            static_manifest=run_output(
                root, "static_scene", "export", "merged_static_manifest.json"
            ),
            actor_samples=run_output(root, "dynamic_frames", "actor_frame_samples.json"),
            actor_manifest=run_output(root, "manifests", "actor_manifest.json"),
            radio_sites=run_output(root, "config", "prototype_radio_sites.json"),
            dynamic_prototype_config=run_output(
                root, "config", "dynamic_prototype_config.json"
            ),
            rt_runtime_config=run_output(root, "config", "rt_material_mapping.json"),
        ),
        legacy_default,
    )


def require_path_within_root(path: Path, root: Path, label: str) -> Path:
    """Reject generated-output locations outside an explicit run root."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ExperimentPathError(
            f"{label} escapes experiment root {root}: {resolved}"
        ) from exc
    return resolved


def dynamic_manifest_path(dynamic_root: Path, frame_id: int) -> Path:
    return run_output(
        dynamic_root,
        f"frame_{frame_id:03d}",
        f"dynamic_frame_{frame_id:03d}_manifest.json",
    )


def actor_frame_manifest_path(dynamic_root: Path, frame_id: int) -> Path:
    return run_output(
        dynamic_root,
        f"frame_{frame_id:03d}",
        f"actor_frame_{frame_id:03d}_manifest.json",
    )
