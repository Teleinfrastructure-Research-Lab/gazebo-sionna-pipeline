"""Focused tests for legacy experiment path plumbing; no workers are invoked."""

from __future__ import annotations

import json
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SCRIPTS_ROOT.parents[1]
for path in (SCRIPTS_ROOT, SCRIPTS_ROOT / "dynamic_rigid", SCRIPTS_ROOT / "static_scene", SCRIPTS_ROOT / "features"):
    sys.path.insert(0, str(path))

import build_object_features as object_features  # noqa: E402
import build_raw_occupancy_features as raw_features  # noqa: E402
import build_scene_geometry_registry as geometry_registry  # noqa: E402
import build_static_scene_registry as static_registry  # noqa: E402
import dynamic_prototype_config as prototype_config  # noqa: E402
import sample_experiment_frames as sampler  # noqa: E402
import run_three_frame_multi_rx_rt_sanity as multi_rx  # noqa: E402
import run_three_frame_rt_sanity as single_rx  # noqa: E402
from experiment_paths import (  # noqa: E402
    ExperimentPathError,
    PROJECT_ROOT,
    RT_OUT_ROOT,
    resolve_config_output_root,
)
from three_frame_paths import (  # noqa: E402
    actor_frame_manifest_path,
    dynamic_manifest_path,
    require_path_within_root,
    resolve_three_frame_paths,
)


class LegacyPathContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_index(self, path: Path, manifest_path: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["frame_id", "source_sample_index", "composed_manifest_path"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "frame_id": 0,
                    "source_sample_index": 0,
                    "composed_manifest_path": manifest_path,
                }
            )

    def test_config_owned_output_root_contract(self) -> None:
        run = self.root / "run"
        config = run / "config/experiment_config.json"
        config.parent.mkdir(parents=True)
        self.assertEqual(resolve_config_output_root(config, "."), run.resolve())
        absolute = self.root / "absolute-output"
        self.assertEqual(resolve_config_output_root(config, absolute), absolute.resolve())
        self.assertEqual(
            resolve_config_output_root(config, "nested/output"),
            (run / "nested/output").resolve(),
        )
        external_config = self.root / "elsewhere/config.json"
        self.assertEqual(
            resolve_config_output_root(external_config, "generated"),
            (external_config.parent / "generated").resolve(),
        )
        with self.assertRaises(ExperimentPathError):
            resolve_config_output_root(config, "")
        with self.assertRaises(ExperimentPathError):
            resolve_config_output_root(config, "../escape")
        with self.assertRaises(ExperimentPathError):
            resolve_config_output_root(PROJECT_ROOT / "experiment_config.json", ".")
        with self.assertRaises(ExperimentPathError):
            resolve_config_output_root(config, PROJECT_ROOT)
        with self.assertRaises(ExperimentPathError):
            resolve_config_output_root(config, RT_OUT_ROOT)

    def test_dynamic_prototype_pose_logs_resolve_from_config_owner(self) -> None:
        run = self.root / "run"
        config = run / "config/dynamic_prototype_config.json"
        panda = run / "inputs/poses/panda_pose.log"
        ur5 = run / "inputs/poses/ur5_pose.log"
        panda.parent.mkdir(parents=True)
        panda.write_text("panda\n", encoding="utf-8")
        ur5.write_text("ur5\n", encoding="utf-8")
        self.write_json(
            config,
            {
                "prototype_frames": [{"frame_id": 0, "source_sample_index": 0}],
                "dynamic_models": {
                    "Panda": {
                        "pose_log": "inputs/poses/panda_pose.log",
                        "expected_link_count": 2,
                        "non_renderable_links": [],
                        "forced_material": "metal",
                    },
                    "ur5_rg2": {
                        "pose_log": "inputs/poses/ur5_pose.log",
                        "expected_link_count": 2,
                        "non_renderable_links": [],
                        "forced_material": "metal",
                    },
                },
            },
        )
        loaded = prototype_config.load_dynamic_prototype_config(config)
        self.assertEqual(loaded["dynamic_models"]["Panda"]["pose_log_path"], panda.resolve())
        self.assertEqual(loaded["dynamic_models"]["ur5_rg2"]["pose_log_path"], ur5.resolve())

    def test_dynamic_prototype_pose_log_resolution_is_safe_and_config_owned(self) -> None:
        external = self.root / "external/dynamic_prototype_config.json"
        self.assertEqual(
            prototype_config.resolve_config_owned_pose_log_path("inputs/panda.log", external),
            (external.parent / "inputs/panda.log").resolve(),
        )
        absolute = self.root / "absolute/ur5.log"
        self.assertEqual(
            prototype_config.resolve_config_owned_pose_log_path(str(absolute), external),
            absolute.resolve(),
        )
        with self.assertRaises(prototype_config.DynamicPrototypeConfigError):
            prototype_config.resolve_config_owned_pose_log_path("../escape.log", external)

    @unittest.skipUnless(
        os.environ.get("POSE_ARCHIVE_INTEGRATION_TESTS") == "1",
        "set POSE_ARCHIVE_INTEGRATION_TESTS=1 to validate extracted pose archives",
    )
    def test_archive_pose_bindings_exist_without_changing_2446_inputs(self) -> None:
        factory = REPOSITORY_ROOT / "rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045"
        runs = [
            factory,
            REPOSITORY_ROOT / "rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_rigid_200f",
            REPOSITORY_ROOT / "rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_actor_200f",
        ]
        for run in runs:
            loaded = prototype_config.load_dynamic_prototype_config(
                run / "config/dynamic_prototype_config.json"
            )
            self.assertEqual(
                loaded["dynamic_models"]["Panda"]["pose_log_path"],
                run / "inputs/poses/panda_pose.log",
            )
            self.assertEqual(
                loaded["dynamic_models"]["ur5_rg2"]["pose_log_path"],
                run / "inputs/poses/ur5_pose.log",
            )
            self.assertTrue(loaded["dynamic_models"]["Panda"]["pose_log_path"].is_file())
            self.assertTrue(loaded["dynamic_models"]["ur5_rg2"]["pose_log_path"].is_file())

        run2446 = REPOSITORY_ROOT / "rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015"
        loaded2446 = prototype_config.load_dynamic_prototype_config(
            run2446 / "config/dynamic_prototype_config.json"
        )
        self.assertEqual(
            loaded2446["dynamic_models"]["Panda"]["pose_log_path"],
            run2446 / "inputs/poses/panda_pose.log",
        )
        self.assertEqual(
            loaded2446["dynamic_models"]["ur5_rg2"]["pose_log_path"],
            run2446 / "inputs/poses/ur5_pose.log",
        )

    def test_feature_configs_use_shared_config_owned_resolver(self) -> None:
        config = self.root / "run/config/experiment_config.json"
        self.write_json(
            config,
            {
                "experiment_name": "test",
                "num_frames": 2,
                "output_dir": ".",
                "dynamic_models": ["panda"],
                "materials_of_interest": ["metal"],
                "semantic_classes_of_interest": ["robot"],
            },
        )
        self.assertEqual(object_features.load_experiment_config(config)["output_root"], self.root / "run")
        self.assertEqual(raw_features.load_experiment_config(config)["output_root"], self.root / "run")

    def test_sampler_explicit_manifest_is_used_and_recorded(self) -> None:
        run = self.root / "run"
        config = run / "config/experiment_config.json"
        manifest = self.root / "inputs/dynamic_manifest.json"
        self.write_json(
            config,
            {
                "experiment_name": "test",
                "num_frames": 2,
                "dynamic_models": ["panda"],
                "output_dir": ".",
            },
        )
        self.write_json(manifest, [{"model": "panda", "links": [{"link": "base"}]}])
        prototype = {
            "config_path": self.root / "prototype.json",
            "dynamic_models": {"panda": {"expected_link_count": 1, "pose_log_path": self.root / "pose.log"}},
        }
        with (
            patch.object(sampler, "DYNAMIC_MANIFEST_PATH", self.root / "missing-factory.json"),
            patch.object(sampler, "load_dynamic_prototype_config", return_value=prototype),
            patch.object(sampler, "count_valid_samples", return_value=2),
            patch.object(sys, "argv", ["sample_experiment_frames.py", "--config", str(config), "--dynamic-manifest", str(manifest)]),
        ):
            self.assertEqual(sampler.main(), 0)
        output = json.loads((run / "frames/sampled_frames.json").read_text())
        self.assertEqual(output["dynamic_manifest_path"], str(manifest.resolve()))

    def test_geometry_registry_honors_explicit_paths(self) -> None:
        static = self.root / "input/static.json"
        dynamic = self.root / "input/dynamic.json"
        models = self.root / "models"
        output = self.root / "output/geometry.json"
        self.write_json(static, [])
        self.write_json(dynamic, [])
        models.mkdir()
        self.assertEqual(
            geometry_registry.main([
                "--static-manifest", str(static), "--dynamic-manifest", str(dynamic),
                "--models-root", str(models), "--output", str(output),
            ]),
            0,
        )
        self.assertTrue(output.is_file())

    def test_static_registry_honors_explicit_paths(self) -> None:
        registry = self.root / "input/geometry.json"
        materials = self.root / "input/materials.json"
        output = self.root / "output/static.json"
        self.write_json(registry, [])
        self.write_json(materials, {"default_material": "composite", "model_rules": []})
        self.assertEqual(
            static_registry.main([
                "--geometry-registry", str(registry), "--material-map", str(materials),
                "--output", str(output), "--project-root", str(self.root),
            ]),
            0,
        )
        self.assertTrue(output.is_file())

    def test_feature_index_paths_are_resolved_from_run_output_root(self) -> None:
        run = self.root / "run"
        manifest = run / "frames/composed_manifests/frame_000_manifest.json"
        self.write_json(manifest, {"entries": []})
        index = run / "frames/composed_manifests/composed_manifest_index.csv"
        relative = "frames/composed_manifests/frame_000_manifest.json"
        self.write_index(index, relative)
        self.assertEqual(
            object_features.load_composed_manifest_index(
                index, output_root=run, expected_frames=1
            )[0]["manifest_path"],
            manifest.resolve(),
        )
        self.assertEqual(
            raw_features.load_composed_manifest_index(
                index, output_root=run, expected_frames=1
            )[0]["manifest_path"],
            manifest.resolve(),
        )

    def test_feature_indexes_reject_escaping_run_relative_path(self) -> None:
        run = self.root / "run"
        index = run / "frames/composed_manifests/composed_manifest_index.csv"
        self.write_index(index, "../outside.json")
        with self.assertRaises(object_features.ObjectFeatureBuildError):
            object_features.load_composed_manifest_index(index, output_root=run, expected_frames=1)
        with self.assertRaises(raw_features.RawOccupancyFeatureError):
            raw_features.load_composed_manifest_index(index, output_root=run, expected_frames=1)

    def test_feature_indexes_accept_legacy_absolute_manifest_paths(self) -> None:
        run = self.root / "run"
        manifest = self.root / "legacy/frame_000_manifest.json"
        self.write_json(manifest, {"entries": []})
        index = run / "frames/composed_manifests/composed_manifest_index.csv"
        self.write_index(index, str(manifest))
        self.assertEqual(
            object_features.load_composed_manifest_index(
                index, output_root=run, expected_frames=1
            )[0]["manifest_path"],
            manifest.resolve(),
        )
        self.assertEqual(
            raw_features.load_composed_manifest_index(
                index, output_root=run, expected_frames=1
            )[0]["manifest_path"],
            manifest.resolve(),
        )

    def test_single_and_multi_rx_share_run_local_generated_paths(self) -> None:
        run = self.root / "run"
        run.mkdir()
        plan, legacy = resolve_three_frame_paths(run)
        self.assertFalse(legacy)
        expected_dynamic = run / "dynamic_scene/frame_017/dynamic_frame_017_manifest.json"
        expected_actor = run / "dynamic_scene/frame_017/actor_frame_017_manifest.json"
        self.assertEqual(dynamic_manifest_path(plan.dynamic_root, 17), expected_dynamic)
        self.assertEqual(actor_frame_manifest_path(plan.dynamic_root, 17), expected_actor)
        self.assertEqual(
            plan.dynamic_prototype_config,
            run / "config/dynamic_prototype_config.json",
        )
        self.assertEqual(plan.rt_runtime_config, run / "config/rt_material_mapping.json")
        for module in (single_rx, multi_rx):
            self.assertIs(module.planned_dynamic_manifest_path, dynamic_manifest_path)
            self.assertIs(module.planned_actor_frame_manifest_path, actor_frame_manifest_path)
        self.assertNotIn("factory_panda_ur5", str(expected_dynamic))

    def test_multi_rx_worker_commands_are_run_local(self) -> None:
        run = self.root / "run"
        dynamic_root = run / "dynamic_scene"
        composed_root = run / "composed_scene"
        dynamic_manifest = dynamic_manifest_path(dynamic_root, 0)
        actor_manifest = actor_frame_manifest_path(dynamic_root, 0)
        commands: list[list[str]] = []

        def capture(command, **_kwargs):
            commands.append(command)
            if "--output-manifest" in command:
                output = Path(command[command.index("--output-manifest") + 1])
                self.write_json(
                    output,
                    {
                        "frame_id": 0,
                        "source_sample_index": 0,
                        "entries": [],
                        "total_count": 0,
                        "dynamic_count": 0,
                        "actor_count": 0,
                    },
                )
            if "--output-xml" in command:
                output = Path(command[command.index("--output-xml") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("<scene/>\n", encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch.object(multi_rx, "run_command", side_effect=capture),
            patch.object(multi_rx, "validate_actor_frame_manifest", return_value=1),
            patch.object(multi_rx, "EXPECTED_DYNAMIC_COUNT", 0),
            patch.object(multi_rx, "DYNAMIC_PROTOTYPE_CONFIG_PATH", run / "config/dynamic_prototype_config.json"),
            patch.object(multi_rx, "RT_RUNTIME_CONFIG_PATH", run / "config/rt_material_mapping.json"),
        ):
            multi_rx.export_actor_frame(
                0, 0,
                actor_samples_path=run / "dynamic_frames/actor_frame_samples.json",
                actor_manifest_path=run / "manifests/actor_manifest.json",
                actor_alignment_policy="bounds_center_xy_to_root",
                actor_z_alignment_policy="bounds_min_z_to_floor",
                actor_floor_z=0.1,
                dynamic_output_root=dynamic_root,
            )
            multi_rx.compose_and_emit_frame(
                0,
                source_sample_index=0,
                static_manifest_path=run / "static_scene/export/merged_static_manifest.json",
                composed_root=composed_root,
                dynamic_manifest=dynamic_manifest,
            )
        command_text = "\n".join(" ".join(map(str, command)) for command in commands)
        self.assertIn(str(dynamic_root), command_text)
        self.assertIn(str(dynamic_manifest), command_text)
        self.assertIn(str(composed_root / "frame_000/composed_frame_000_manifest.json"), command_text)
        self.assertIn(str(composed_root / "frame_000/frame_000_sionna.xml"), command_text)
        self.assertIn(str(run / "config/dynamic_prototype_config.json"), command_text)
        self.assertIn(str(run / "config/rt_material_mapping.json"), command_text)
        self.assertNotIn("factory_panda_ur5/legacy_run_20260522_133045", command_text)

    def test_generated_paths_cannot_escape_explicit_run_root(self) -> None:
        run = self.root / "run"
        run.mkdir()
        with self.assertRaises(ExperimentPathError):
            require_path_within_root(run / "../escape", run, "output")

    def test_single_rx_worker_commands_are_run_local(self) -> None:
        run = self.root / "run"
        dynamic_root = run / "dynamic_scene"
        composed_root = run / "composed_scene"
        commands: list[list[str]] = []

        def capture(command, **_kwargs):
            commands.append(command)
            return type("Result", (), {"returncode": 0, "stdout": "paths_found: 1\nscene_objects: 1\nradio_materials: 1\n", "stderr": ""})()

        with (
            patch.object(single_rx, "DYNAMIC_PROTOTYPE_CONFIG_PATH", run / "config/dynamic_prototype_config.json"),
            patch.object(single_rx, "RT_RUNTIME_CONFIG_PATH", run / "config/rt_material_mapping.json"),
            patch.object(single_rx, "EXPECTED_DYNAMIC_COUNT", 1),
            patch.object(single_rx, "run_command", side_effect=capture),
            patch.object(single_rx, "validate_dynamic_manifest"),
            patch.object(single_rx, "validate_actor_frame_manifest", return_value=1),
            patch.object(single_rx, "validate_composed_manifest", return_value=(3, 1)),
            patch.object(single_rx, "validate_xml"),
            patch.object(single_rx, "extract_tau_stats", return_value=(1, 0.1, 0.2, None)),
        ):
            single_rx.run_frame(
                0, 0, {}, Path(sys.executable),
                static_manifest_path=run / "static_scene/export/merged_static_manifest.json",
                composed_root=composed_root,
                dynamic_output_root=dynamic_root,
                output_suffix="",
                include_actors=True,
                actor_samples_path=run / "dynamic_frames/actor_frame_samples.json",
                actor_manifest_path=run / "manifests/actor_manifest.json",
                actor_alignment_policy="bounds_center_xy_to_root",
                actor_z_alignment_policy="bounds_min_z_to_floor",
                actor_floor_z=0.1,
            )
        command_text = "\n".join(" ".join(map(str, command)) for command in commands)
        self.assertIn(str(dynamic_root), command_text)
        self.assertIn(str(dynamic_root / "frame_000/dynamic_frame_000_manifest.json"), command_text)
        self.assertIn(str(composed_root / "frame_000/composed_frame_000_manifest.json"), command_text)
        self.assertIn(str(composed_root / "frame_000/frame_000_sionna.xml"), command_text)
        self.assertIn(str(run / "config/dynamic_prototype_config.json"), command_text)
        self.assertIn(str(run / "config/rt_material_mapping.json"), command_text)
        self.assertNotIn("factory_panda_ur5/legacy_run_20260522_133045", command_text)

    def test_harnesses_select_run_local_runtime_configs_before_loading(self) -> None:
        run = self.root / "run"
        dynamic_config = run / "config/dynamic_prototype_config.json"
        runtime_config = run / "config/rt_material_mapping.json"
        self.write_json(dynamic_config, {})
        self.write_json(runtime_config, {})

        for module, script_name in (
            (single_rx, "run_three_frame_rt_sanity.py"),
            (multi_rx, "run_three_frame_multi_rx_rt_sanity.py"),
        ):
            captured: list[tuple[Path | None, Path | None]] = []

            def stop_after_capture(dynamic_path, runtime_path):
                captured.append((dynamic_path, runtime_path))
                raise RuntimeError("intentional test stop")

            with (
                patch.object(module, "configure_runtime", side_effect=stop_after_capture),
                patch.object(sys, "argv", [script_name, "--experiment-root", str(run)]),
            ):
                self.assertEqual(module.main(), 1)
            self.assertEqual(captured, [(dynamic_config.resolve(), runtime_config.resolve())])


if __name__ == "__main__":
    unittest.main()
