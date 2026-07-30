import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import release_hardening
from release_hardening import (
    atomic_json,
    atomic_promote_files,
    canonical_manifest_payload,
    InventoryValidationError,
    ManifestConflictError,
    collect_run_inventory,
    invocation_manifest_payload,
    stable_source_hash,
    validate_existing_manifest,
    write_canonical_manifest,
    write_invocation_manifest,
    validate_run_invocation_binding,
)
import semantic_ablation_run_classical_ml_ablation as classical
import semantic_ablation_run_rbf_svm_ablation as rbf


class ReleaseHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.expected = {("task", "view", "model")}

    def tearDown(self):
        self.temp.cleanup()

    def binding_kwargs(self):
        return {
            "expected_execution_source_hashes": {"runner.py": "source"},
            "expected_dependency_versions": {"numpy": "1"},
        }

    def write(self, name="run.json", payload=None):
        path = self.root / name
        path.write_text(json.dumps(payload or {"task": "task", "view": "view", "model": "model"}))
        return path

    def validate(self, identity, payload, path):
        if payload.get("hash") != "good":
            raise ValueError("hash mismatch")
        return payload

    def test_missing_run_fails_closed(self):
        with self.assertRaises(InventoryValidationError) as caught:
            collect_run_inventory([], expected=self.expected, identity_fields=("task", "view", "model"), validator=self.validate, fail_closed=True)
        self.assertEqual(caught.exception.report["missing_identities"], ["task/view/model"])

    def test_corrupt_run_is_rejected(self):
        path = self.root / "corrupt.json"
        path.write_text("{")
        report, accepted = collect_run_inventory([path], expected=self.expected, identity_fields=("task", "view", "model"), validator=self.validate, fail_closed=False)
        self.assertFalse(report["passed"])
        self.assertFalse(accepted)
        self.assertIn("JSONDecodeError", report["rejected_runs"][0]["reason"])

    def test_unexpected_inventory_exception_is_reported_separately(self):
        path = self.write(payload={"task": "task", "view": "view", "model": "model", "hash": "good"})
        def unexpected(identity, payload, source):
            raise AttributeError("validator bug")
        report, accepted = collect_run_inventory(
            [path], expected=self.expected, identity_fields=("task", "view", "model"),
            validator=unexpected, fail_closed=False,
        )
        self.assertFalse(report["passed"])
        self.assertFalse(accepted)
        self.assertEqual(report["internal_validation_errors"][0]["reason"], "AttributeError: validator bug")

    def test_atomic_json_uses_unique_same_filesystem_temporaries(self):
        destination = self.root / "atomic.json"
        with patch.object(release_hardening.os, "replace", wraps=release_hardening.os.replace) as replace:
            atomic_json(destination, {"value": 1})
            atomic_json(destination, {"value": 2})
        temporary_paths = [Path(call.args[0]) for call in replace.call_args_list]
        self.assertEqual(len(temporary_paths), 2)
        self.assertEqual(len(set(temporary_paths)), 2)
        self.assertTrue(all(path.parent == destination.parent for path in temporary_paths))
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_duplicate_identity_is_rejected(self):
        first = self.write("a.json", {"task": "task", "view": "view", "model": "model", "hash": "good"})
        second = self.write("b.json", {"task": "task", "view": "view", "model": "model", "hash": "good"})
        report, accepted = collect_run_inventory([first, second], expected=self.expected, identity_fields=("task", "view", "model"), validator=self.validate, fail_closed=False)
        self.assertFalse(report["passed"])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(report["rejected_runs"][0]["reason"], "duplicate identity")

    def test_hash_mismatch_is_rejected(self):
        path = self.write(payload={"task": "task", "view": "view", "model": "model", "hash": "bad"})
        report, accepted = collect_run_inventory([path], expected=self.expected, identity_fields=("task", "view", "model"), validator=self.validate, fail_closed=False)
        self.assertFalse(report["passed"])
        self.assertFalse(accepted)
        self.assertIn("hash mismatch", report["rejected_runs"][0]["reason"])

    def canonical(self, input_hashes=None, scientific=None, expected=None):
        return canonical_manifest_payload(
            experiment_identity={"experiment": "model"},
            expected_jobs=expected or [("task", "view", "model"), ("task2", "view", "model")],
            input_hashes=input_hashes or {"input": "hash"},
            scientific_configuration=scientific or {"split": "fixed"},
            implementation_version="v1",
            seed=42,
        )

    def test_sequential_invocations_preserve_canonical_inventory(self):
        path = self.root / "manifest.json"
        payload = self.canonical()
        write_canonical_manifest(path, payload)
        common = dict(
            requested_jobs=[("task", "view", "model")],
            normalized_cli_args={"task": "task"},
            execution_source_hashes={"script.py": "source"},
            dependency_versions={"numpy": "1"},
            command_mode="single",
            canonical_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            input_hashes={"input": "hash"},
            timestamp_utc="2026-01-01T00:00:00+00:00",
        )
        first = write_invocation_manifest(self.root / "invocations", invocation_manifest_payload(invocation_id="one", **common))
        second_payload = invocation_manifest_payload(**{**common, "invocation_id": "two", "requested_jobs": [("task2", "view", "model")]})
        second = write_invocation_manifest(self.root / "invocations", second_payload)
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(path.read_text())["expected_jobs"], [list(job) for job in payload["expected_jobs"]])
        self.assertEqual(len(list((self.root / "invocations").glob("*.json"))), 2)

    def test_invocation_cli_paths_are_portable(self):
        value = classical.normalize_cli_args({"inside": classical.REPOSITORY_ROOT / "rt_out", "outside": Path("/tmp/private-run")})
        serialized = json.dumps(value)
        self.assertNotIn(str(classical.REPOSITORY_ROOT), serialized)
        self.assertNotIn("/tmp/private-run", serialized)
        self.assertEqual(value["outside"], "<external-path>")

    def test_resuming_same_invocation_is_idempotent(self):
        payload = invocation_manifest_payload(
            invocation_id="same",
            requested_jobs=[("task", "view", "model")],
            normalized_cli_args={}, execution_source_hashes={}, dependency_versions={},
            command_mode="single", canonical_manifest_sha256="manifest", input_hashes={},
            timestamp_utc="2026-01-01T00:00:00+00:00",
        )
        write_invocation_manifest(self.root / "invocations", payload)
        write_invocation_manifest(self.root / "invocations", payload)
        with self.assertRaises(ManifestConflictError):
            write_invocation_manifest(self.root / "invocations", {**payload, "requested_jobs": []})

    def test_invocation_lifecycle_and_exact_run_binding(self):
        job = ("task", "view", "model")
        manifest_path = self.root / "experiment_manifest.json"
        write_canonical_manifest(manifest_path, self.canonical(expected=[job]))
        common = {
            "requested_jobs": [job],
            "normalized_cli_args": {"force": True},
            "execution_source_hashes": {"runner.py": "source"},
            "dependency_versions": {"numpy": "1"},
            "command_mode": "single",
            "canonical_manifest_sha256": stable_source_hash(manifest_path),
            "input_hashes": {"input": "hash"},
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
        }
        invocation_id = "forced-replacement"
        started = invocation_manifest_payload(
            invocation_id=invocation_id, **common, status="started"
        )
        write_invocation_manifest(self.root / "invocations", started)
        completed = invocation_manifest_payload(
            invocation_id=invocation_id,
            **common,
            status="completed",
            completed_jobs=[job],
        )
        completed_path = write_invocation_manifest(self.root / "invocations", completed)
        run = {
            "invocation_id": invocation_id,
            "invocation_manifest": str(completed_path.relative_to(self.root)),
            "execution_source_hashes": common["execution_source_hashes"],
            "dependency_versions": common["dependency_versions"],
            "created_at_utc": common["timestamp_utc"],
            "job_identity": list(job),
            "execution_status": "generated",
        }
        validate_run_invocation_binding(self.root, run, job, **self.binding_kwargs())
        timestamp_tampered = {**run, "created_at_utc": "2026-01-01T00:00:01+00:00"}
        with self.assertRaises(ManifestConflictError):
            validate_run_invocation_binding(self.root, timestamp_tampered, job, **self.binding_kwargs())
        resumed_status_tampered = {**run, "execution_status": "resumed"}
        with self.assertRaises(ManifestConflictError):
            validate_run_invocation_binding(self.root, resumed_status_tampered, job, **self.binding_kwargs())
        resumed_jobs_tampered = {**completed, "resumed_jobs": [list(job)]}
        completed_path.write_text(json.dumps(resumed_jobs_tampered, sort_keys=True) + "\n")
        with self.assertRaises(ManifestConflictError):
            validate_run_invocation_binding(self.root, run, job, **self.binding_kwargs())
        resumed = invocation_manifest_payload(
            invocation_id="resumed-job",
            **common,
            status="completed",
            completed_jobs=[job],
            resumed_jobs=[job],
        )
        self.assertEqual(resumed["resumed_jobs"], [list(job)])
        failed = invocation_manifest_payload(
            invocation_id="failed-job", **common, status="failed", failed_jobs=[job]
        )
        self.assertEqual(failed["status"], "failed")
        for mutation in (
            {**run, "invocation_manifest": "invocations/missing.json"},
            {**run, "invocation_id": "wrong"},
            {**run, "job_identity": ["other", "view", "model"]},
        ):
            with self.assertRaises(ManifestConflictError):
                validate_run_invocation_binding(self.root, mutation, job, **self.binding_kwargs())

    def test_release_validation_rejects_stripped_hardened_run_binding(self):
        job = ("task", "view", "model")
        canonical = self.canonical(expected=[job], input_hashes={"input": "hash"})
        manifest_path = self.root / "experiment_manifest.json"
        write_canonical_manifest(manifest_path, canonical)
        invocation_id = "hardened"
        invocation = invocation_manifest_payload(
            invocation_id=invocation_id,
            requested_jobs=[job],
            normalized_cli_args={},
            execution_source_hashes={"runner.py": "source"},
            dependency_versions={"numpy": "1"},
            command_mode="single",
            canonical_manifest_sha256=stable_source_hash(manifest_path),
            input_hashes={"input": "hash"},
            timestamp_utc="2026-01-01T00:00:00+00:00",
            status="completed",
            completed_jobs=[job],
        )
        invocation_path = write_invocation_manifest(self.root / "invocations", invocation)
        run = {
            "invocation_id": invocation_id,
            "invocation_manifest": str(invocation_path.relative_to(self.root)),
            "execution_source_hashes": {"runner.py": "source"},
            "dependency_versions": {"numpy": "1"},
            "created_at_utc": invocation["timestamp_utc"],
            "job_identity": list(job),
            "execution_status": "generated",
        }
        validate_run_invocation_binding(self.root, run, job, **self.binding_kwargs())
        stripped = dict(run)
        for field in (
            "invocation_id", "invocation_manifest", "execution_source_hashes",
            "dependency_versions", "created_at_utc", "job_identity", "execution_status",
        ):
            stripped.pop(field)
        with self.assertRaises(ManifestConflictError):
            validate_run_invocation_binding(
                self.root, stripped, job, **self.binding_kwargs(), allow_legacy=False
            )

    def test_invocation_fingerprints_must_match_current_environment(self):
        job = ("task", "view", "model")
        manifest_path = self.root / "experiment_manifest.json"
        write_canonical_manifest(manifest_path, self.canonical(expected=[job]))
        invocation = invocation_manifest_payload(
            invocation_id="fingerprints",
            requested_jobs=[job],
            normalized_cli_args={},
            execution_source_hashes={"runner.py": "source"},
            dependency_versions={"numpy": "1"},
            command_mode="single",
            canonical_manifest_sha256=stable_source_hash(manifest_path),
            input_hashes={"input": "hash"},
            timestamp_utc="2026-01-01T00:00:00+00:00",
            status="completed",
            completed_jobs=[job],
        )
        path = write_invocation_manifest(self.root / "invocations", invocation)
        run = {
            "invocation_id": "fingerprints",
            "invocation_manifest": str(path.relative_to(self.root)),
            "execution_source_hashes": {"runner.py": "source"},
            "dependency_versions": {"numpy": "1"},
            "created_at_utc": invocation["timestamp_utc"],
            "job_identity": list(job),
            "execution_status": "generated",
        }
        validate_run_invocation_binding(self.root, run, job, **self.binding_kwargs())
        for field, changed in (
            ("execution_source_hashes", {"runner.py": "tampered-source"}),
            ("dependency_versions", {"numpy": "tampered-version"}),
        ):
            tampered_invocation = {**invocation, field: changed}
            path.write_text(json.dumps(tampered_invocation, sort_keys=True) + "\n")
            tampered_run = {**run, field: changed}
            with self.assertRaises(ManifestConflictError):
                validate_run_invocation_binding(self.root, tampered_run, job, **self.binding_kwargs())

    def test_explicit_dynamic_configuration_reaches_explicit_input_validation(self):
        explicit_config = self.root / "explicit_dynamic_prototype_config.json"
        explicit_config.write_text(
            json.dumps(
                {
                    "prototype_frames": [{"frame_id": 0, "source_sample_index": 0}],
                    "dynamic_models": {
                        "test_model": {
                            "pose_log": "missing_pose.csv",
                            "expected_link_count": 1,
                            "non_renderable_links": [],
                            "forced_material": "test_material",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        explicit_input = self.root / "explicit_dynamic_frames.json"
        script = classical.REPOSITORY_ROOT / "rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--experiment-root",
                str(self.root),
                "--dynamic-prototype-config",
                str(explicit_config),
                "--dynamic-frames",
                str(explicit_input),
            ],
            cwd=classical.REPOSITORY_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(explicit_input), result.stdout + result.stderr)

    def test_incompatible_input_and_scientific_configuration_conflict(self):
        path = self.root / "manifest.json"
        write_canonical_manifest(path, self.canonical())
        with self.assertRaises(ManifestConflictError):
            write_canonical_manifest(path, self.canonical(input_hashes={"input": "changed"}))
        with self.assertRaises(ManifestConflictError):
            write_canonical_manifest(path, self.canonical(scientific={"split": "changed"}))

    def test_single_job_scope_ignores_other_valid_jobs(self):
        first = self.write("one.json", {"task": "task", "view": "view", "model": "model", "hash": "good"})
        other = self.write("other.json", {"task": "other", "view": "view", "model": "model", "hash": "good"})
        report, accepted = collect_run_inventory(
            [first, other], expected={("task", "view", "model")},
            identity_fields=("task", "view", "model"), validator=self.validate,
            fail_closed=True, scope="single_job",
        )
        self.assertTrue(report["passed"])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(report["ignored_runs"][0]["identity"], "other/view/model")

    def test_transactional_promotion_restores_all_files_on_failure(self):
        destination_a, destination_b = self.root / "a.json", self.root / "b.json"
        destination_a.write_text("old-a")
        destination_b.write_text("old-b")
        blocked_parent = self.root / "blocked"
        blocked_parent.write_text("not a directory")
        staged_a, staged_b = self.root / "stage-a", self.root / "stage-b"
        staged_a.write_text("new-a")
        staged_b.write_text("new-b")
        original = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (destination_a, destination_b)}
        with self.assertRaises(OSError):
            atomic_promote_files({staged_a: destination_a, staged_b: blocked_parent / "b.json"})
        self.assertEqual(original, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (destination_a, destination_b)})

    def make_combined_sources(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        data = FakeData()
        for model in classical.V4_MODELS + ("rbf_svm", "xgboost"):
            source_name = "classical_ml_ablation_v4" if model in classical.V4_MODELS else f"classical_ml_{model}_v1"
            source = data.exp / "results" / source_name
            family = "classical_ml_ablation_v4" if model in classical.V4_MODELS else model
            write_canonical_manifest(source / "experiment_manifest.json", classical.canonical_manifest_for(data, family))
            for task in classical.TASKS:
                for view in classical.VIEWS:
                    run_path = source / "runs" / task / view / f"{model}.json"
                    run_path.parent.mkdir(parents=True, exist_ok=True)
                    run_path.write_text(json.dumps({
                        "task": task, "view": view, "model": model, "feature_dimension": 1,
                        "selected_mean_validation_average_precision": 0.5, "selected_threshold": 0.5,
                        "selected_configuration_converged": True, "test_selected_threshold": {"accuracy": 1.0},
                        "per_rx_metrics": [], "selected_hyperparameters": {}, "warnings": [],
                    }))
                    prediction = source / "predictions" / task / view / f"{model}.csv"
                    oof = source / "oof_predictions" / task / view / f"{model}.csv"
                    prediction.parent.mkdir(parents=True, exist_ok=True)
                    oof.parent.mkdir(parents=True, exist_ok=True)
                    prediction.write_text("prediction")
                    oof.write_text("oof")
        def fake_validate(_data, _out, task, view, model):
            return {
                "task": task, "view": view, "model": model, "feature_dimension": 1,
                "selected_mean_validation_average_precision": 0.5, "selected_threshold": 0.5,
                "selected_configuration_converged": True, "test_selected_threshold": {"accuracy": 1.0},
                "per_rx_metrics": [], "selected_hyperparameters": {}, "warnings": [],
            }
        return data, fake_validate

    def test_combined_manifest_conflict_has_no_partial_writes(self):
        data, fake_validate = self.make_combined_sources()
        combined = data.exp / "results/classical_ml_combined_v1"
        combined.mkdir(parents=True)
        old = {}
        for name in ("combined_manifest.json", "run_summary.csv", "per_rx_metrics.csv", "selected_hyperparameters.json", "validation_summary.json"):
            path = combined / name
            path.write_text(f"old-{name}")
            old[path] = path.read_text()

        with patch.object(classical, "validate_completed", side_effect=fake_validate):
            with self.assertRaises(ManifestConflictError):
                classical.aggregate_combined(data)
        self.assertEqual(old, {path: path.read_text() for path in old})

    def test_validate_combined_requires_existing_aggregate_outputs(self):
        data, fake_validate = self.make_combined_sources()
        with patch.object(classical, "validate_completed", side_effect=fake_validate):
            report = classical.aggregate_combined(data, validate_only=True)
        self.assertFalse(report["release_ready"])
        self.assertFalse(report["aggregation_complete"])
        self.assertIn("combined_manifest.json", [Path(value).name for value in report["missing_outputs"]])

    def test_incomplete_family_marks_stale_summary_invalid(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        data = FakeData()
        out = data.exp / "results/classical_ml_ablation_v4"
        out.mkdir(parents=True)
        write_canonical_manifest(out / "experiment_manifest.json", classical.canonical_manifest_payload(
            experiment_identity={"experiment_name": data.exp.parent.name, "run_id": data.exp.name, "model_family": "classical_ml_ablation_v4"},
            expected_jobs=classical.family_jobs("classical_ml_ablation_v4"), input_hashes=data.input_hashes,
            scientific_configuration=classical.scientific_configuration("classical_ml_ablation_v4"), implementation_version=classical.VERSION, seed=classical.SEED,
        ))
        stale = out / "run_summary.csv"
        stale.write_text("old-summary")
        report = classical.aggregate_results(data, out)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertFalse(report["aggregation_complete"])
        self.assertFalse(report["release_ready"])
        validation = json.loads((out / "aggregation_validation.json").read_text())
        self.assertEqual(validation["status"], "INCOMPLETE")
        self.assertFalse(validation["release_ready"])
        self.assertEqual(stale.read_text(), "old-summary")

    def test_model_family_manifest_tampering_cannot_shrink_or_change_contract(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        mutations = ("removed_job", "unsupported_job", "seed", "input_hash", "family", "scientific")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = FakeData()
                out = data.exp / "results/classical_ml_ablation_v4"
                out.mkdir(parents=True, exist_ok=True)
                payload = classical.canonical_manifest_for(data, "classical_ml_ablation_v4")
                if mutation == "removed_job":
                    payload["expected_jobs"].pop()
                elif mutation == "unsupported_job":
                    payload["expected_jobs"].append(["bad", "view", "model"])
                elif mutation == "seed":
                    payload["seed"] += 1
                elif mutation == "input_hash":
                    payload["input_hashes"]["input"] = "changed"
                elif mutation == "family":
                    payload["experiment_identity"]["model_family"] = "wrong_family"
                else:
                    payload["scientific_configuration"]["temporal_gap"] = 999
                (out / "experiment_manifest.json").write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
                with self.assertRaises(classical.Error):
                    classical.validate_results(data, out, scope="model_family")

    def test_rbf_manifest_contract_uses_rbf_implementation_version(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        manifest = classical.canonical_manifest_for(FakeData(), "rbf_svm")
        self.assertEqual(manifest["implementation_version"], classical.RBF_VERSION)

    def test_single_job_validation_requires_current_canonical_manifest(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        out = FakeData.exp / "results/classical_ml_ablation_v4"
        with self.assertRaises(classical.Error):
            classical.validate_results(FakeData(), out, [("task", "view", "logistic_regression")], scope="single_job")

    def test_combined_sources_reject_cross_family_root(self):
        data, fake_validate = self.make_combined_sources()
        wrong_root = data.exp / "results/classical_ml_ablation_v4"
        correct_root = data.exp / "results/classical_ml_xgboost_v1"
        task, view = classical.TASKS[0], classical.VIEWS[0]
        correct_run = correct_root / "runs" / task / view / "xgboost.json"
        wrong_run = wrong_root / "runs" / task / view / "xgboost.json"
        wrong_run.parent.mkdir(parents=True, exist_ok=True)
        wrong_run.write_text(correct_run.read_text())
        correct_run.unlink()
        with patch.object(classical, "validate_completed", side_effect=fake_validate):
            report = classical.validate_combined_sources(data)
        self.assertFalse(report["passed"])
        self.assertIn("wrong model-family root", report["error"])

    def test_family_aggregation_promotion_is_transactional(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        data = FakeData()
        out = data.exp / "results/classical_ml_ablation_v4"
        out.mkdir(parents=True)
        write_canonical_manifest(out / "experiment_manifest.json", classical.canonical_manifest_for(data, "classical_ml_ablation_v4"))
        old = {}
        for name in ("run_summary.csv", "per_rx_metrics.csv", "selected_hyperparameters.json", "aggregation_validation.json"):
            path = out / name
            path.write_text(f"old-{name}")
            old[path] = path.read_text()
        run = {
            "task": "task", "view": "view", "model": "logistic_regression",
            "selected_hyperparameters": {}, "selected_threshold": 0.5,
            "selected_mean_validation_average_precision": 0.5,
            "warnings": [], "feature_dimension": 1,
            "selected_configuration_converged": True,
            "test_selected_threshold": {"accuracy": 1.0},
            "per_rx_metrics": [{"rx_id": "rx", "accuracy": 1.0}],
        }
        inventory = {"passed": True, "expected_runs": 45, "validated_runs": 45}
        with patch.object(classical, "collect_run_inventory", return_value=(inventory, {("task", "view", "logistic_regression"): run})):
            with patch.object(classical, "atomic_promote_files", side_effect=OSError("promotion failed")):
                with self.assertRaises(OSError):
                    classical.aggregate_results(data, out)
        self.assertEqual(old, {path: path.read_text() for path in old})

    def test_rbf_family_aggregation_promotion_is_transactional(self):
        class FakeData:
            exp = self.root / "experiment"
            input_hashes = {"input": "hash"}

        data = FakeData()
        out = data.exp / "results/classical_ml_rbf_svm_v1"
        out.mkdir(parents=True)
        write_canonical_manifest(out / "experiment_manifest.json", classical.canonical_manifest_for(data, "rbf_svm"))
        old = {}
        for name in ("run_summary.csv", "per_rx_metrics.csv", "selected_hyperparameters.json", "aggregation_validation.json"):
            path = out / name
            path.write_text(f"old-{name}")
            old[path] = path.read_text()
        run = {
            "task": "task", "view": "view", "model": "rbf_svm",
            "selected_hyperparameters": {}, "selected_threshold": 0.5,
            "selected_mean_validation_average_precision": 0.5,
            "warnings": [], "feature_dimension": 1,
            "selected_configuration_converged": True,
            "test_selected_threshold": {"accuracy": 1.0},
            "per_rx_metrics": [{"rx_id": "rx", "accuracy": 1.0}],
        }
        inventory = {"passed": True, "expected_runs": 15, "validated_runs": 15}
        with patch.object(rbf, "collect_run_inventory", return_value=(inventory, {("task", "view"): run})):
            with patch.object(rbf, "atomic_promote_files", side_effect=OSError("promotion failed")):
                with self.assertRaises(OSError):
                    rbf.aggregate_results(data, out)
        self.assertEqual(old, {path: path.read_text() for path in old})

    def test_rbf_incremental_summary_records_incomplete_validation(self):
        out = self.root / "rbf-output"
        out.mkdir()
        failure = InventoryValidationError({"passed": False, "missing_identities": ["task/view"]})
        with patch.object(rbf, "input_validation", return_value={"passed": True}):
            with patch.object(rbf, "validate_results", side_effect=failure):
                summary = rbf.write_validation_summary(None, out, [])
        self.assertFalse(summary["result_validation"]["passed"])
        self.assertEqual(json.loads((out / "validation_summary.json").read_text())["result_validation"]["report"], failure.report)


if __name__ == "__main__":
    unittest.main()
