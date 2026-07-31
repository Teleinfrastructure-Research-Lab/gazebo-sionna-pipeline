#!/usr/bin/env python3
"""Shared experiment-run path handling.

Generated artifacts must live below one explicit run directory.  Pipeline
stages may pass ``--experiment-root`` or set ``PIPELINE_RUN_DIR``; silently
falling back to ``rt_out`` is intentionally not supported.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RT_OUT_ROOT = PROJECT_ROOT / "rt_out"
EXPERIMENTS_ROOT = RT_OUT_ROOT / "experiments"


class ExperimentPathError(RuntimeError):
    """Raised when a generated-output root is missing or unsafe."""


def add_experiment_root_argument(
    parser: argparse.ArgumentParser,
    *,
    required: bool = True,
) -> None:
    """Add the one canonical generated-output argument to a CLI parser."""

    parser.add_argument(
        "--experiment-root",
        type=Path,
        required=required,
        default=None,
        help=(
            "Single run directory for generated outputs. Relative paths are "
            "resolved from the repository root; PIPELINE_RUN_DIR is accepted "
            "when this option is omitted."
        ),
    )


def _resolve_candidate(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def resolve_config_output_root(config_path: str | Path, output_dir: str | Path) -> Path:
    """Resolve an experiment output directory from its owning configuration.

    A configuration in ``<run>/config/`` owns paths relative to ``<run>``;
    configurations elsewhere own paths relative to their parent directory.
    This deliberately does not use the process working directory.
    """

    if not isinstance(output_dir, (str, Path)) or not str(output_dir).strip():
        raise ExperimentPathError("experiment_config.output_dir must be a non-empty path")
    config = Path(config_path).expanduser().resolve()
    configured = Path(output_dir).expanduser()
    owner_root = config.parent.parent if config.parent.name == "config" else config.parent
    if configured.is_absolute():
        resolved = configured.resolve()
    else:
        resolved = (owner_root / configured).resolve()
        try:
            resolved.relative_to(owner_root)
        except ValueError as exc:
            raise ExperimentPathError(
                f"experiment_config.output_dir escapes its owner root {owner_root}: {resolved}"
            ) from exc
    if resolved in {PROJECT_ROOT, RT_OUT_ROOT}:
        raise ExperimentPathError(
            f"experiment_config.output_dir resolves to unsafe repository-wide root: {resolved}"
        )
    return resolved


def resolve_run_index_path(
    value: str | Path,
    output_root: str | Path,
    *,
    label: str = "index path",
) -> Path:
    """Resolve an absolute, run-relative, or explicit historical repo path.

    Modern indexes are relative to ``output_root``. Historical repository paths
    are recognized only by their unambiguous ``rt_out/`` prefix. Relative paths
    containing traversal are rejected rather than interpreted from cwd.
    """

    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ExperimentPathError(f"{label} must be a non-empty path")
    root = Path(output_root).expanduser().resolve()
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if ".." in raw.parts:
        raise ExperimentPathError(f"{label} must not contain '..': {value}")
    if raw.parts[:1] == ("rt_out",):
        return (PROJECT_ROOT / raw).resolve()
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ExperimentPathError(
            f"{label} escapes experiment output root {root}: {resolved}"
        ) from exc
    return resolved


def resolve_experiment_root(
    value: str | Path | None = None,
    *,
    create: bool = True,
    require_existing: bool = False,
) -> Path:
    """Resolve and optionally create a safe run directory.

    A run directory may be inside ``rt_out/experiments`` or a caller-provided
    temporary directory used by tests.  The ``rt_out`` root itself and the
    historical ``current_experiment`` convention are rejected.
    """

    raw_value: str | Path | None = value
    if raw_value is None:
        raw_value = os.environ.get("PIPELINE_RUN_DIR")
    if raw_value is None or not str(raw_value).strip():
        raise ExperimentPathError(
            "No experiment run directory was provided. Pass --experiment-root "
            "or set PIPELINE_RUN_DIR; generated files will not be written to rt_out."
        )

    root = _resolve_candidate(raw_value)
    if root == RT_OUT_ROOT or root == PROJECT_ROOT:
        raise ExperimentPathError(f"Refusing unsafe experiment root: {root}")
    if root.name == "current_experiment" or "current_experiment" in root.parts:
        raise ExperimentPathError(
            f"Refusing non-versioned current_experiment path: {root}"
        )
    if require_existing and not root.is_dir():
        raise ExperimentPathError(f"Experiment root does not exist: {root}")
    if root.exists() and not root.is_dir():
        raise ExperimentPathError(f"Experiment root is not a directory: {root}")
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def announce_experiment_root(root: Path, *, stage: str | None = None) -> None:
    """Print the resolved run root before a stage performs work."""

    label = f"[{stage}] " if stage else ""
    print(f"{label}experiment_root={root.resolve()}")


def run_output(root: Path, *parts: str) -> Path:
    """Return a path below ``root`` and reject traversal outside the run."""

    candidate = (root.joinpath(*parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ExperimentPathError(
            f"Generated path escapes experiment root {root}: {candidate}"
        ) from exc
    return candidate


def experiment_logs_root(
    experiment_root: str | Path | None = None,
    *,
    create: bool = False,
) -> Path:
    """Return the run-local log directory, creating it only when requested."""

    root = resolve_experiment_root(
        experiment_root,
        create=False,
        require_existing=True,
    )
    logs = run_output(root, "logs")
    if create:
        logs.mkdir(parents=True, exist_ok=True)
    return logs


def experiment_log_path(
    experiment_root: str | Path | None,
    name: str,
    *,
    timestamp: bool = False,
    create: bool = True,
) -> Path:
    """Allocate a non-overwriting path below ``<run>/logs``.

    ``name`` may contain functional subdirectories such as ``rt/solver.log``.
    When ``timestamp`` is true, the consistent local-time suffix
    ``_YYYYMMDD_HHMMSS`` is inserted before the extension.  A numeric suffix is
    added if the resulting path already exists.
    """

    root = resolve_experiment_root(
        experiment_root,
        create=False,
        require_existing=True,
    )
    relative_name = Path(name)
    if relative_name.is_absolute() or not str(relative_name).strip():
        raise ExperimentPathError(f"Log name must be a relative non-empty path: {name!r}")

    logs = experiment_logs_root(root, create=create)
    candidate = run_output(logs, *relative_name.parts)
    if timestamp:
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        candidate = candidate.with_name(f"{candidate.stem}_{stamp}{candidate.suffix}")

    index = 1
    unique = candidate
    unique.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            # Reserve the name atomically so concurrent stages cannot select
            # the same log path before either process opens it for writing.
            with unique.open("x", encoding="utf-8"):
                pass
            return unique
        except FileExistsError:
            unique = candidate.with_name(
                f"{candidate.stem}_{index:02d}{candidate.suffix}"
            )
            index += 1


def new_run_dir(experiment_name: str, *, now: datetime | None = None) -> Path:
    """Create a unique timestamped run directory for an entry-point wrapper."""

    safe_name = "_".join(part for part in experiment_name.strip().split() if part)
    if not safe_name or safe_name in {".", ".."}:
        raise ExperimentPathError("Experiment name must be non-empty")
    timestamp = (now or datetime.now(timezone.utc)).astimezone().strftime(
        "run_%Y%m%d_%H%M%S"
    )
    root = EXPERIMENTS_ROOT / safe_name / timestamp
    suffix = 1
    while root.exists():
        root = EXPERIMENTS_ROOT / safe_name / f"{timestamp}_{suffix:02d}"
        suffix += 1
    root.mkdir(parents=True)
    return root


def resolved_config_record(path: Path, root: Path) -> dict[str, Any]:
    """Return small provenance metadata for a resolved config copied to a run."""

    return {
        "source_path": str(path.resolve()),
        "experiment_root": str(root.resolve()),
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Allocate a run-local pipeline log path.")
    parser.add_argument("--experiment-root", required=True, type=Path)
    parser.add_argument("--log-name", required=True)
    parser.add_argument("--timestamp", action="store_true")
    args = parser.parse_args()
    print(
        experiment_log_path(
            args.experiment_root,
            args.log_name,
            timestamp=args.timestamp,
            create=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
