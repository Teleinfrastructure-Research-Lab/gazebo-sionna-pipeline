"""Small, side-effect-free helpers for release-facing experiment integrity.

This module deliberately does not know how to train models or build datasets.
It only provides immutable-manifest writes, stable source fingerprints, and
strict inventory collection for experiment aggregators.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


CANONICAL_MANIFEST_SCHEMA_VERSION = "release_experiment_manifest_v2"
INVOCATION_MANIFEST_SCHEMA_VERSION = "release_invocation_manifest_v1"
VALIDATION_SCOPES = ("single_job", "model_family", "combined_release")
INVOCATION_STATUSES = ("started", "completed", "failed")
SUCCESSFUL_RUN_EXECUTION_STATUSES = ("generated", "resumed")


class ManifestConflictError(RuntimeError):
    """Raised when an existing immutable manifest differs from a new invocation."""


class InventoryValidationError(RuntimeError):
    """Raised when a fail-closed inventory contains rejected or missing jobs."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(json.dumps(report, sort_keys=True))


def atomic_json(path: Path, value: Any) -> None:
    """Write JSON atomically without replacing an unrelated destination midway."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def stable_source_hash(path: Path) -> str:
    """Hash exact source bytes so the fingerprint is interpreter-independent."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(paths: Iterable[Path], *, project_root: Path | None = None) -> dict[str, str]:
    """Return deterministic repository-relative execution-source fingerprints."""
    root = (project_root or Path.cwd()).resolve()
    result: dict[str, str] = {}
    for path in sorted({Path(item).resolve() for item in paths}, key=str):
        try:
            name = str(path.relative_to(root))
        except ValueError:
            name = str(path)
        result[name] = stable_source_hash(path)
    return result


def canonical_manifest_payload(
    *,
    experiment_identity: dict[str, Any],
    expected_jobs: Iterable[Iterable[Any]],
    input_hashes: dict[str, str],
    scientific_configuration: dict[str, Any],
    implementation_version: str,
    seed: int,
) -> dict[str, Any]:
    """Build the immutable experiment inventory, independent of one invocation."""
    return {
        "schema_version": CANONICAL_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "canonical_experiment",
        "experiment_identity": experiment_identity,
        "expected_jobs": [list(job) for job in sorted((tuple(job) for job in expected_jobs))],
        "input_hashes": dict(sorted(input_hashes.items())),
        "scientific_configuration": scientific_configuration,
        "implementation_version": implementation_version,
        "seed": seed,
    }


def write_canonical_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Create or validate the canonical inventory; invocations never replace it."""
    validate_existing_manifest(path, payload)
    if not path.exists():
        atomic_json(path, payload)


def validate_existing_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Check an existing canonical manifest without writing any destination."""
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestConflictError(f"Existing manifest is unreadable: {path}") from exc
        if existing != payload:
            raise ManifestConflictError(
                f"Canonical experiment manifest conflict: {path}; refusing metadata loss"
            )


def invocation_manifest_payload(
    *,
    invocation_id: str,
    requested_jobs: Iterable[Iterable[Any]],
    normalized_cli_args: dict[str, Any],
    execution_source_hashes: dict[str, str],
    dependency_versions: dict[str, str],
    command_mode: str,
    canonical_manifest_sha256: str,
    input_hashes: dict[str, str],
    timestamp_utc: str | None = None,
    status: str = "completed",
    completed_jobs: Iterable[Iterable[Any]] = (),
    resumed_jobs: Iterable[Iterable[Any]] = (),
    failed_jobs: Iterable[Iterable[Any]] = (),
) -> dict[str, Any]:
    """Build one append-only invocation record for a subset of canonical jobs."""
    if not invocation_id or "/" in invocation_id or "\\" in invocation_id:
        raise ValueError("invocation_id must be a non-empty path-safe identifier")
    if status not in INVOCATION_STATUSES:
        raise ValueError(f"unsupported invocation status: {status}")
    normalize = lambda jobs: [list(job) for job in sorted({tuple(job) for job in jobs})]
    return {
        "schema_version": INVOCATION_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "invocation",
        "invocation_id": invocation_id,
        "timestamp_utc": timestamp_utc or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "command_mode": command_mode,
        "normalized_cli_args": normalized_cli_args,
        "requested_jobs": normalize(requested_jobs),
        "completed_jobs": normalize(completed_jobs),
        "resumed_jobs": normalize(resumed_jobs),
        "failed_jobs": normalize(failed_jobs),
        "execution_source_hashes": dict(sorted(execution_source_hashes.items())),
        "dependency_versions": dict(sorted(dependency_versions.items())),
        "canonical_manifest_sha256": canonical_manifest_sha256,
        "input_hashes": dict(sorted(input_hashes.items())),
    }


def write_invocation_manifest(directory: Path, payload: dict[str, Any]) -> Path:
    """Append an invocation record without modifying prior invocation records."""
    invocation_id = payload.get("invocation_id")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("invocation manifest requires invocation_id")
    status = payload.get("status", "completed")
    suffix = "" if status == "completed" else f".{status}"
    path = directory / f"{invocation_id}{suffix}.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestConflictError(f"Existing invocation manifest is unreadable: {path}") from exc
        if existing != payload:
            raise ManifestConflictError(f"Invocation manifest conflict: {path}")
        return path
    atomic_json(path, payload)
    return path


def validate_run_invocation_binding(
    run_root: Path,
    run: dict[str, Any],
    expected_job: Iterable[Any],
    *,
    expected_execution_source_hashes: dict[str, str],
    expected_dependency_versions: dict[str, str],
    allow_legacy: bool = False,
) -> dict[str, Any] | None:
    """Validate the provenance binding for a newly generated run.

    Missing binding is accepted only when the caller explicitly opts into the
    legacy policy. The returned legacy report is never a release PASS.
    """
    if "invocation_id" not in run:
        if allow_legacy:
            return {
                "status": "missing",
                "release_validation_passed": False,
                "reason": "run invocation binding is missing",
            }
        raise ManifestConflictError("run invocation binding is missing")
    job = list(expected_job)
    invocation_id = run.get("invocation_id")
    manifest_name = run.get("invocation_manifest")
    required = (
        "execution_source_hashes",
        "dependency_versions",
        "created_at_utc",
        "job_identity",
        "execution_status",
    )
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ManifestConflictError("run invocation_id is missing or invalid")
    if not isinstance(manifest_name, str) or not manifest_name:
        raise ManifestConflictError("run invocation_manifest is missing")
    if any(value in manifest_name for value in ("\\", "..")) or Path(manifest_name).is_absolute():
        raise ManifestConflictError("run invocation_manifest must be a safe relative path")
    if any(field not in run for field in required):
        raise ManifestConflictError("run invocation binding is incomplete")
    if run.get("execution_status") not in SUCCESSFUL_RUN_EXECUTION_STATUSES:
        raise ManifestConflictError("run execution_status is not a successful generated/resumed value")
    if run.get("job_identity") != job:
        raise ManifestConflictError("run job identity does not match its output path")
    manifest_path = (run_root / manifest_name).resolve()
    try:
        manifest_path.relative_to(run_root.resolve())
    except ValueError as exc:
        raise ManifestConflictError("run invocation_manifest escapes the result root") from exc
    if not manifest_path.is_file():
        raise ManifestConflictError(f"referenced invocation manifest is missing: {manifest_name}")
    try:
        invocation = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestConflictError("referenced invocation manifest is unreadable") from exc
    if invocation.get("invocation_id") != invocation_id or invocation.get("status") != "completed":
        raise ManifestConflictError("run does not reference a successful completed invocation")
    run_timestamp = run.get("created_at_utc")
    invocation_timestamp = invocation.get("timestamp_utc")
    if (
        not isinstance(run_timestamp, str)
        or not run_timestamp
        or not isinstance(invocation_timestamp, str)
        or not invocation_timestamp
    ):
        raise ManifestConflictError("run and invocation timestamps must be non-empty strings")
    if run_timestamp != invocation_timestamp:
        raise ManifestConflictError("run created_at_utc differs from invocation timestamp_utc")
    resumed_jobs = invocation.get("resumed_jobs")
    if not isinstance(resumed_jobs, list):
        raise ManifestConflictError("invocation resumed_jobs must be a list")
    if run.get("execution_status") == "resumed" and job not in resumed_jobs:
        raise ManifestConflictError("resumed run is not listed in invocation resumed_jobs")
    if run.get("execution_status") == "generated" and job in resumed_jobs:
        raise ManifestConflictError("generated run incorrectly claims a resumed invocation")
    canonical_path = run_root / "experiment_manifest.json"
    if not canonical_path.is_file():
        raise ManifestConflictError("current canonical experiment manifest is missing")
    canonical_hash = stable_source_hash(canonical_path)
    if invocation.get("canonical_manifest_sha256") != canonical_hash:
        raise ManifestConflictError("invocation canonical manifest hash differs from the current manifest")
    try:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestConflictError("current canonical experiment manifest is unreadable") from exc
    if invocation.get("input_hashes") != canonical.get("input_hashes"):
        raise ManifestConflictError("invocation input hashes differ from the current experiment inputs")
    if job not in invocation.get("requested_jobs", []) or job not in invocation.get("completed_jobs", []):
        raise ManifestConflictError("completed invocation does not contain the run identity")
    if invocation.get("execution_source_hashes") != run.get("execution_source_hashes"):
        raise ManifestConflictError("run and invocation source fingerprints differ")
    if invocation.get("dependency_versions") != run.get("dependency_versions"):
        raise ManifestConflictError("run and invocation dependency versions differ")
    if invocation.get("execution_source_hashes") != expected_execution_source_hashes:
        raise ManifestConflictError("invocation source fingerprints differ from the current checkout")
    if invocation.get("dependency_versions") != expected_dependency_versions:
        raise ManifestConflictError("invocation dependency versions differ from the current environment")


def new_invocation_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:12]


def installed_versions(packages: Iterable[str]) -> dict[str, str]:
    """Return versions without importing heavyweight runtime packages."""
    result = {}
    for package in sorted(set(packages)):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "<missing>"
    return result


def assess_compatibility(
    provenance: dict[str, Any] | None,
    *,
    expected_source_hashes: dict[str, str],
    expected_input_hashes: dict[str, str],
) -> dict[str, Any]:
    """Assess provenance using exact-byte source fingerprints only.

    A source mismatch is deliberately ``unknown``. This helper does not claim
    comment-only or metadata-only semantic compatibility.
    """
    if provenance is None:
        return {"status": "missing", "release_validation_passed": False, "reason": "provenance manifest is missing"}
    if provenance.get("schema_version") not in ("best_beam_provenance_v1", "best_beam_provenance_v2"):
        return {"status": "unknown", "release_validation_passed": False, "reason": "unknown provenance schema"}
    source_match = provenance.get("execution_source_hashes") == expected_source_hashes
    input_match = provenance.get("input_hashes") == expected_input_hashes
    if not input_match:
        return {"status": "behavior_affecting", "release_validation_passed": False, "reason": "input artifact hashes differ"}
    if not source_match:
        return {"status": "unknown", "release_validation_passed": False, "reason": "execution source hashes differ"}
    return {"status": "exact_match", "release_validation_passed": True, "reason": "source and input hashes match"}


def atomic_promote_files(staged: dict[Path, Path]) -> None:
    """Promote a group of files with rollback if any replacement fails."""
    backups: dict[Path, Path] = {}
    replaced: list[Path] = []
    created_directories: list[Path] = []
    try:
        for temporary, destination in staged.items():
            missing: list[Path] = []
            parent = destination.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            created_directories.extend(missing)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = destination.with_name(destination.name + f".backup-{uuid.uuid4().hex}")
                os.replace(destination, backup)
                backups[destination] = backup
            os.replace(temporary, destination)
            replaced.append(destination)
    except Exception:
        for destination in reversed(replaced):
            if destination.exists():
                destination.unlink()
            backup = backups.get(destination)
            if backup and backup.exists():
                os.replace(backup, destination)
        for destination, backup in backups.items():
            if backup.exists() and not destination.exists():
                os.replace(backup, destination)
        for temporary in staged:
            if temporary.exists():
                temporary.unlink()
        for directory in sorted(created_directories, key=lambda value: len(value.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    finally:
        for backup in backups.values():
            if backup.exists():
                backup.unlink()


def required_identity(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    """Extract a non-empty identity tuple from a run payload."""
    values = tuple(payload.get(field) for field in fields)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"run payload has incomplete identity fields {fields!r}")
    return values


def collect_run_inventory(
    paths: Iterable[Path],
    *,
    expected: set[tuple[str, ...]],
    identity_fields: tuple[str, ...],
    validator: Callable[[tuple[str, ...], dict[str, Any], Path], Any],
    fail_closed: bool,
    scope: str = "model_family",
) -> tuple[dict[str, Any], dict[tuple[str, ...], Any]]:
    """Collect run payloads and report every missing/rejected identity.

    ``fail_closed=False`` is reserved for incremental development reports. Such
    reports are explicitly ``passed: false`` until the complete expected set is
    present and validated. Release aggregation must use ``True``.
    """
    if scope not in VALIDATION_SCOPES:
        raise ValueError(f"unsupported validation scope: {scope}")
    accepted: dict[tuple[str, ...], Any] = {}
    seen: set[tuple[str, ...]] = set()
    rejected: list[dict[str, str]] = []
    ignored: list[dict[str, str]] = []
    internal_errors: list[dict[str, str]] = []
    for path in sorted({Path(item) for item in paths}, key=str):
        identity_text = "<unreadable>"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("run payload must be a JSON object")
            identity = required_identity(payload, identity_fields)
            identity_text = "/".join(identity)
            if identity not in expected:
                if scope == "single_job":
                    ignored.append({"path": str(path), "identity": identity_text, "reason": "outside single_job scope"})
                    continue
                rejected.append({"path": str(path), "identity": identity_text, "reason": "unexpected identity"})
                continue
            if identity in seen:
                rejected.append({"path": str(path), "identity": identity_text, "reason": "duplicate identity"})
                continue
            seen.add(identity)
            accepted[identity] = validator(identity, payload, path)
        except Exception as exc:  # Every malformed/hash-mismatched run is reported, never skipped.
            rejected.append({"path": str(path), "identity": identity_text, "reason": f"{type(exc).__name__}: {exc}"})
            if isinstance(exc, (AttributeError, AssertionError, ImportError, NameError)):
                internal_errors.append({"path": str(path), "identity": identity_text, "reason": f"{type(exc).__name__}: {exc}"})

    missing = sorted("/".join(identity) for identity in expected - set(accepted))
    report = {
        "passed": not rejected and not missing and len(accepted) == len(expected),
        "expected_runs": len(expected),
        "validated_runs": len(accepted),
        "rejected_runs": rejected,
        "missing_identities": missing,
        "identity_fields": list(identity_fields),
        "validation_scope": scope,
        "ignored_runs": ignored,
        "internal_validation_errors": internal_errors,
        "job_execution_passed": not rejected,
        "aggregation_complete": not rejected and not missing and len(accepted) == len(expected),
        "release_ready": not rejected and not missing and len(accepted) == len(expected),
    }
    if fail_closed and not report["passed"]:
        raise InventoryValidationError(report)
    return report, accepted
