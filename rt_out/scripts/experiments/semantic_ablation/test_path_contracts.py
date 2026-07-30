import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "rt_out/scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "rt_out/scripts/composition"))
sys.path.insert(0, str(REPOSITORY_ROOT / "rt_out/scripts/dynamic"))
sys.path.insert(0, str(REPOSITORY_ROOT / "rt_out/scripts/features"))
sys.path.insert(0, str(REPOSITORY_ROOT / "rt_out/scripts/rt"))

import build_canonical_r1_r4_features as canonical_features  # noqa: E402
import build_segmentation_ablation_voxels as voxel_features  # noqa: E402
import compose_frame_manifests_batch as composition  # noqa: E402
import export_dynamic_meshes_batch as dynamic_batch  # noqa: E402
import build_sionna_xml_batch as xml_batch  # noqa: E402
import run_rt_multi_rx_batch as rt_batch  # noqa: E402
import semantic_ablation_run_sionna_rt_restart_safe as restart_safe  # noqa: E402


class PathContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_static_manifest(self, run_root: Path) -> Path:
        path = run_root / "geometry/static/export/merged_static_manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
        return path

    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def write_csv(self, path: Path, fieldnames: list[str], row: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)

    def make_rt_config(self, run_root: Path, num_frames: int = 1) -> Path:
        path = run_root / "config/experiment_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "experiment_name": "test",
                    "num_frames": num_frames,
                    "output_dir": ".",
                    "frequency_ghz": 28.0,
                    "tx_power_dbm": 30.0,
                    "tx": {"position": [0.0, 0.0, 2.4]},
                    "rx_list": [
                        {"id": "rx_test", "position": [1.0, 1.0, 1.0]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def make_manifest_mesh_fixture(self, run_root: Path) -> dict[str, Path | dict]:
        static_meshes = [
            run_root / f"geometry/static/export/merged_by_material/static_{i}.ply"
            for i in range(11)
        ]
        dynamic_meshes = [
            run_root / f"frames/dynamic_meshes/frame_000/raw_visual_meshes/dynamic_{i}.ply"
            for i in range(21)
        ]
        actor_mesh = run_root / (
            "frames/actor_meshes/frame_000/actor_meshes/actor_000.ply"
        )
        for path in [*static_meshes, *dynamic_meshes, actor_mesh]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("mesh\n", encoding="utf-8")

        dynamic = {
            "frame_id": 0,
            "source_sample_index": 0,
            "exported_visuals": [
                {"exported_mesh_path": str(path.relative_to(run_root))}
                for path in dynamic_meshes
            ],
        }
        actor = {
            "frame_id": 0,
            "source_sample_index": 0,
            "exported_actors": [
                {"exported_mesh_path": str(actor_mesh.relative_to(run_root))}
            ],
        }
        composed = {
            "frame_id": 0,
            "source_sample_index": 0,
            "static_count": 11,
            "dynamic_count": 21,
            "actor_count": 1,
            "total_count": 33,
            "entries": [
                {"mesh_path": str(path.relative_to(run_root))}
                for path in [*static_meshes, *dynamic_meshes, actor_mesh]
            ],
        }
        dynamic_path = run_root / (
            "frames/dynamic_meshes/frame_000/dynamic_frame_000_manifest.json"
        )
        actor_path = run_root / (
            "frames/actor_meshes/frame_000/actor_frame_000_manifest.json"
        )
        composed_path = restart_safe.composed(run_root, 0)
        self.write_json(dynamic_path, dynamic)
        self.write_json(actor_path, actor)
        self.write_json(composed_path, composed)
        return {
            "dynamic_path": dynamic_path,
            "actor_path": actor_path,
            "composed_path": composed_path,
            "dynamic": dynamic,
            "actor": actor,
            "composed": composed,
        }

    def test_batch_static_manifest_resolution_supports_default_and_explicit_paths(self):
        run_root = self.root / "run"
        default_path = self.make_static_manifest(run_root)
        self.assertEqual(composition.resolve_static_manifest(run_root), default_path.resolve())

        explicit_path = self.root / "other/static_manifest.json"
        explicit_path.parent.mkdir()
        explicit_path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(
            composition.resolve_static_manifest(run_root, explicit_path),
            explicit_path.resolve(),
        )

    def test_missing_static_manifest_fails_with_expected_path(self):
        run_root = self.root / "run"
        expected = run_root / "geometry/static/export/merged_static_manifest.json"
        with self.assertRaisesRegex(composition.BatchComposeFrameManifestError, str(expected)):
            composition.resolve_static_manifest(run_root)
        with self.assertRaisesRegex(restart_safe.Error, str(expected)):
            restart_safe.resolve_static_manifest(run_root)

    def test_restart_safe_composition_command_propagates_run_local_manifest(self):
        run_root = self.root / "run"
        manifest = self.make_static_manifest(run_root)
        command = restart_safe.compose_frame_command(run_root, 7)
        manifest_arg = command[command.index("--static-manifest") + 1]
        self.assertEqual(Path(manifest_arg), manifest.resolve())
        command_text = " ".join(command)
        self.assertNotIn("factory_panda_ur5", command_text)
        self.assertNotIn("legacy_run_20260522_133045", command_text)

    def test_batch_and_restart_safe_share_composed_manifest_path(self):
        run_root = self.root / "run"
        self.assertEqual(
            composition.composed_manifest_path(run_root, 17),
            restart_safe.composed(run_root, 17),
        )
        self.assertEqual(
            composition.composed_manifest_path(run_root, 17),
            run_root / "frames/composed_manifests/frame_017_manifest.json",
        )

    def test_batch_main_uses_run_root_for_composed_output_path(self):
        run_root = self.root / "run"
        config_path = run_root / "config/experiment_config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "experiment_name": "test",
                    "num_frames": 1,
                    "output_dir": ".",
                    "frequency_ghz": 28.0,
                    "tx": {"position": [0.0, 0.0, 2.4]},
                    "rx_list": [
                        {"id": "rx_test", "position": [1.0, 1.0, 1.0]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.make_static_manifest(run_root)
        dynamic_manifest = run_root / "frames/dynamic_meshes/frame_017/manifest.json"
        captured = {}

        def fake_run_compose(**kwargs):
            captured["output_manifest_path"] = kwargs["output_manifest_path"]
            kwargs["output_manifest_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output_manifest_path"].write_text("{}\n", encoding="utf-8")

        def fake_write_index(_path, rows):
            captured["rows"] = rows

        with (
            patch.object(
                composition,
                "load_dynamic_mesh_index",
                return_value=[
                    {
                        "frame_id": 17,
                        "source_sample_index": 17,
                        "dynamic_manifest_path": dynamic_manifest,
                    }
                ],
            ),
            patch.object(composition, "run_compose", side_effect=fake_run_compose),
            patch.object(composition, "validate_composed_manifest"),
            patch.object(composition, "write_index_csv", side_effect=fake_write_index),
            patch.object(
                sys,
                "argv",
                [
                    "compose_frame_manifests_batch.py",
                    "--config",
                    str(config_path),
                    "--no-progress",
                ],
            ),
        ):
            self.assertEqual(composition.main(), 0)

        expected = run_root / "frames/composed_manifests/frame_017_manifest.json"
        self.assertEqual(captured["output_manifest_path"], expected.resolve())
        self.assertEqual(str(captured["output_manifest_path"]).count("frames/composed_manifests"), 1)
        self.assertEqual(
            captured["rows"][0]["composed_manifest_path"],
            "frames/composed_manifests/frame_017_manifest.json",
        )

    def test_manifest_relative_mesh_paths_validate_outside_run_cwd(self):
        run_root = self.root / "run"
        fixture = self.make_manifest_mesh_fixture(run_root)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        original_cwd = Path.cwd()
        try:
            os.chdir(elsewhere)
            self.assertTrue(
                restart_safe.valid_dynamic(fixture["dynamic_path"], 0, run_root)
            )
            self.assertTrue(
                restart_safe.valid_actor(fixture["actor_path"], 0, run_root)
            )
            self.assertTrue(
                restart_safe.valid_composed(fixture["composed_path"], 0, run_root)
            )
        finally:
            os.chdir(original_cwd)

    def test_missing_manifest_relative_mesh_files_fail_validation(self):
        run_root = self.root / "run"
        fixture = self.make_manifest_mesh_fixture(run_root)
        dynamic = json.loads(json.dumps(fixture["dynamic"]))
        dynamic["exported_visuals"][0]["exported_mesh_path"] = (
            "frames/dynamic_meshes/frame_000/raw_visual_meshes/missing.ply"
        )
        self.write_json(fixture["dynamic_path"], dynamic)
        self.assertFalse(
            restart_safe.valid_dynamic(fixture["dynamic_path"], 0, run_root)
        )

        actor = json.loads(json.dumps(fixture["actor"]))
        actor["exported_actors"][0]["exported_mesh_path"] = (
            "frames/actor_meshes/frame_000/actor_meshes/missing.ply"
        )
        self.write_json(fixture["actor_path"], actor)
        self.assertFalse(
            restart_safe.valid_actor(fixture["actor_path"], 0, run_root)
        )

        composed = json.loads(json.dumps(fixture["composed"]))
        composed["entries"][0]["mesh_path"] = (
            "geometry/static/export/merged_by_material/missing.ply"
        )
        self.write_json(fixture["composed_path"], composed)
        self.assertFalse(
            restart_safe.valid_composed(fixture["composed_path"], 0, run_root)
        )

    def test_relative_output_dir_uses_owning_run_not_current_working_directory(self):
        run_root = self.root / "run"
        config_path = run_root / "config/experiment_config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "experiment_name": "test",
                    "num_frames": 1,
                    "output_dir": ".",
                    "frequency_ghz": 28.0,
                    "tx": {"position": [0.0, 0.0, 2.4]},
                    "rx_list": [
                        {"id": "rx_test", "position": [1.0, 1.0, 1.0]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        original_cwd = Path.cwd()
        try:
            os.chdir(elsewhere)
            expected = run_root.resolve()
            self.assertEqual(
                composition.load_experiment_config(config_path)["output_root"],
                expected,
            )
            self.assertEqual(
                dynamic_batch.load_experiment_config(config_path)["output_root"],
                expected,
            )
            self.assertEqual(xml_batch.load_experiment_config(config_path)["output_root"], expected)
            self.assertEqual(rt_batch.load_experiment_config(config_path)["output_root"], expected)
            self.assertEqual(
                canonical_features.resolve_output_root(config_path, "."),
                expected,
            )
            self.assertEqual(
                voxel_features.resolve_output_root(config_path, "."),
                expected,
            )
        finally:
            os.chdir(original_cwd)

    def test_dynamic_batch_main_writes_run_relative_indexes(self):
        run_root = self.root / "run"
        config_path = run_root / "config/experiment_config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "experiment_name": "test",
                    "num_frames": 1,
                    "output_dir": ".",
                    "actors": {
                        "enabled": True,
                        "actor_manifest": "provenance/manifests/actor_manifest.json",
                        "alignment_policy": "bounds_center_xy_to_root",
                        "z_alignment_policy": "bounds_min_z_to_floor",
                        "floor_z": 0.1,
                    },
                }
            ),
            encoding="utf-8",
        )
        (run_root / "provenance/manifests/actor_manifest.json").parent.mkdir(
            parents=True
        )
        (run_root / "provenance/manifests/actor_manifest.json").write_text(
            "{}\n", encoding="utf-8"
        )
        (run_root / "frames/actor_frame_samples.json").parent.mkdir(parents=True)
        (run_root / "frames/actor_frame_samples.json").write_text(
            "{}\n", encoding="utf-8"
        )
        (run_root / "frames/dynamic_visual_frames.json").write_text(
            "{}\n", encoding="utf-8"
        )
        dynamic_manifest = run_root / (
            "frames/dynamic_meshes/frame_017/dynamic_frame_017_manifest.json"
        )
        actor_manifest = run_root / (
            "frames/actor_meshes/frame_017/actor_frame_017_manifest.json"
        )
        dynamic_manifest.parent.mkdir(parents=True)
        actor_manifest.parent.mkdir(parents=True)
        dynamic_manifest.write_text("{}\n", encoding="utf-8")
        actor_manifest.write_text("{}\n", encoding="utf-8")
        captured = {}

        def capture_dynamic_index(_path, rows):
            captured["dynamic_rows"] = rows

        def capture_actor_index(_path, rows):
            captured["actor_rows"] = rows

        with (
            patch.object(dynamic_batch, "resolve_blender_or_raise", return_value=self.root / "blender"),
            patch.object(
                dynamic_batch,
                "load_frame_records",
                return_value=[{"frame_id": 17, "source_sample_index": 17}],
            ),
            patch.object(dynamic_batch, "run_export", return_value=dynamic_manifest),
            patch.object(dynamic_batch, "run_actor_export", return_value=actor_manifest),
            patch.object(dynamic_batch, "validate_actor_manifest", return_value=1),
            patch.object(dynamic_batch, "write_index_csv", side_effect=capture_dynamic_index),
            patch.object(
                dynamic_batch,
                "write_actor_index_csv",
                side_effect=capture_actor_index,
            ),
            patch.object(
                sys,
                "argv",
                [
                    "export_dynamic_meshes_batch.py",
                    "--config",
                    str(config_path),
                    "--include-actors",
                    "--no-progress",
                ],
            ),
        ):
            self.assertEqual(dynamic_batch.main(), 0)

        expected_dynamic = "frames/dynamic_meshes/frame_017/dynamic_frame_017_manifest.json"
        expected_dynamic_dir = "frames/dynamic_meshes/frame_017"
        expected_actor = "frames/actor_meshes/frame_017/actor_frame_017_manifest.json"
        expected_actor_dir = "frames/actor_meshes/frame_017"
        self.assertEqual(captured["dynamic_rows"][0]["manifest_path"], expected_dynamic)
        self.assertEqual(captured["dynamic_rows"][0]["output_dir"], expected_dynamic_dir)
        self.assertEqual(captured["actor_rows"][0]["actor_frame_manifest_path"], expected_actor)
        self.assertEqual(captured["actor_rows"][0]["output_dir"], expected_actor_dir)
        for rows in (captured["dynamic_rows"], captured["actor_rows"]):
            for row in rows:
                for value in row.values():
                    if isinstance(value, str):
                        self.assertFalse(Path(value).is_absolute())
                        self.assertNotIn(str(self.root), value)
                        self.assertNotIn(str(REPOSITORY_ROOT), value)

    def test_composition_loaders_resolve_run_relative_indexes_outside_cwd(self):
        run_root = self.root / "run"
        dynamic_manifest = run_root / "frames/dynamic_meshes/frame_017/manifest.json"
        dynamic_manifest.parent.mkdir(parents=True)
        dynamic_manifest.write_text("{}\n", encoding="utf-8")
        actor_manifest = run_root / "frames/actor_meshes/frame_017/manifest.json"
        actor_manifest.parent.mkdir(parents=True)
        actor_manifest.write_text("{}\n", encoding="utf-8")
        dynamic_index = self.root / "dynamic_mesh_index.csv"
        self.write_csv(
            dynamic_index,
            ["frame_id", "source_sample_index", "manifest_path", "output_dir"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "manifest_path": "frames/dynamic_meshes/frame_017/manifest.json",
                "output_dir": "frames/dynamic_meshes/frame_017",
            },
        )
        actor_index = self.root / "actor_mesh_index.csv"
        self.write_csv(
            actor_index,
            [
                "frame_id",
                "source_sample_index",
                "actor_frame_manifest_path",
                "output_dir",
                "actor_count",
            ],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "actor_frame_manifest_path": "frames/actor_meshes/frame_017/manifest.json",
                "output_dir": "frames/actor_meshes/frame_017",
                "actor_count": 1,
            },
        )
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        original_cwd = Path.cwd()
        try:
            os.chdir(elsewhere)
            dynamic_records = composition.load_dynamic_mesh_index(dynamic_index, run_root)
            actor_records = composition.load_actor_mesh_index(actor_index, run_root)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(dynamic_records[0]["dynamic_manifest_path"], dynamic_manifest.resolve())
        self.assertEqual(dynamic_records[0]["output_dir"], dynamic_manifest.parent.resolve())
        self.assertEqual(actor_records[17]["actor_frame_manifest_path"], actor_manifest.resolve())
        self.assertEqual(actor_records[17]["output_dir"], actor_manifest.parent.resolve())

    def test_composition_loaders_reject_missing_and_escaping_index_targets(self):
        run_root = self.root / "run"
        target_dir = run_root / "frames/dynamic_meshes/frame_017"
        target_dir.mkdir(parents=True)
        missing_index = self.root / "missing.csv"
        self.write_csv(
            missing_index,
            ["frame_id", "source_sample_index", "manifest_path", "output_dir"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "manifest_path": "frames/dynamic_meshes/frame_017/missing.json",
                "output_dir": "frames/dynamic_meshes/frame_017",
            },
        )
        with self.assertRaises(composition.BatchComposeFrameManifestError):
            composition.load_dynamic_mesh_index(missing_index, run_root)

        escaping_index = self.root / "escaping.csv"
        self.write_csv(
            escaping_index,
            ["frame_id", "source_sample_index", "manifest_path", "output_dir"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "manifest_path": "../outside.json",
                "output_dir": "frames/dynamic_meshes/frame_017",
            },
        )
        with self.assertRaisesRegex(
            composition.BatchComposeFrameManifestError,
            "escapes run root",
        ):
            composition.load_dynamic_mesh_index(escaping_index, run_root)

    def test_composition_loaders_accept_legacy_absolute_index_paths(self):
        run_root = self.root / "run"
        dynamic_manifest = self.root / "legacy/dynamic.json"
        dynamic_manifest.parent.mkdir(parents=True)
        dynamic_manifest.write_text("{}\n", encoding="utf-8")
        dynamic_output = dynamic_manifest.parent
        index = self.root / "legacy_absolute.csv"
        self.write_csv(
            index,
            ["frame_id", "source_sample_index", "manifest_path", "output_dir"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "manifest_path": str(dynamic_manifest),
                "output_dir": str(dynamic_output),
            },
        )
        records = composition.load_dynamic_mesh_index(index, run_root)
        self.assertEqual(records[0]["dynamic_manifest_path"], dynamic_manifest.resolve())
        self.assertEqual(records[0]["output_dir"], dynamic_output.resolve())

    def test_xml_builder_main_writes_run_relative_index_paths(self):
        run_root = self.root / "run"
        config_path = self.make_rt_config(run_root)
        composed_manifest = run_root / "frames/composed_manifests/frame_017_manifest.json"
        composed_manifest.parent.mkdir(parents=True)
        composed_manifest.write_text("{}\n", encoding="utf-8")
        composed_index = run_root / "frames/composed_manifests/composed_manifest_index.csv"
        self.write_csv(
            composed_index,
            ["frame_id", "source_sample_index", "composed_manifest_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": "frames/composed_manifests/frame_017_manifest.json",
            },
        )
        captured = {}

        def fake_run_xml_build(**kwargs):
            captured["xml_path"] = kwargs["xml_path"]
            kwargs["xml_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["xml_path"].write_text("<scene/>\n", encoding="utf-8")

        def capture_xml_index(_path, rows):
            captured["rows"] = rows

        with (
            patch.object(xml_batch, "run_xml_build", side_effect=fake_run_xml_build),
            patch.object(xml_batch, "write_index_csv", side_effect=capture_xml_index),
            patch.object(
                sys,
                "argv",
                [
                    "build_sionna_xml_batch.py",
                    "--config",
                    str(config_path),
                    "--no-progress",
                ],
            ),
        ):
            self.assertEqual(xml_batch.main(), 0)

        row = captured["rows"][0]
        self.assertEqual(
            row["composed_manifest_path"],
            "frames/composed_manifests/frame_017_manifest.json",
        )
        self.assertEqual(row["xml_path"], "sionna_xml/frame_017_sionna.xml")
        self.assertFalse(Path(row["composed_manifest_path"]).is_absolute())
        self.assertFalse(Path(row["xml_path"]).is_absolute())
        self.assertNotIn(str(self.root), json.dumps(row))
        self.assertNotIn(str(REPOSITORY_ROOT), json.dumps(row))

    def test_xml_and_rt_loaders_consume_relative_indexes_outside_cwd(self):
        run_root = self.root / "run"
        composed_manifest = run_root / "frames/composed_manifests/frame_017_manifest.json"
        composed_manifest.parent.mkdir(parents=True)
        composed_manifest.write_text("{}\n", encoding="utf-8")
        xml_path = run_root / "sionna_xml/frame_017_sionna.xml"
        xml_path.parent.mkdir(parents=True)
        xml_path.write_text("<scene/>\n", encoding="utf-8")
        composed_index = self.root / "composed_index.csv"
        self.write_csv(
            composed_index,
            ["frame_id", "source_sample_index", "composed_manifest_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": "frames/composed_manifests/frame_017_manifest.json",
            },
        )
        xml_index = self.root / "xml_index.csv"
        self.write_csv(
            xml_index,
            ["frame_id", "source_sample_index", "composed_manifest_path", "xml_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": "frames/composed_manifests/frame_017_manifest.json",
                "xml_path": "sionna_xml/frame_017_sionna.xml",
            },
        )
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        original_cwd = Path.cwd()
        try:
            os.chdir(elsewhere)
            composed_records = xml_batch.load_composed_manifest_index(
                composed_index, run_root
            )
            xml_records = rt_batch.load_xml_index(xml_index, run_root)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(composed_records[0]["composed_manifest_path"], composed_manifest.resolve())
        self.assertEqual(xml_records[0]["xml_path"], xml_path.resolve())

    def test_xml_and_rt_loaders_reject_missing_and_escaping_paths(self):
        run_root = self.root / "run"
        run_root.mkdir()
        missing_composed = self.root / "missing_composed.csv"
        self.write_csv(
            missing_composed,
            ["frame_id", "source_sample_index", "composed_manifest_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": "frames/composed_manifests/missing.json",
            },
        )
        with self.assertRaises(xml_batch.BatchBuildSionnaXmlError):
            xml_batch.load_composed_manifest_index(missing_composed, run_root)

        escaping_composed = self.root / "escaping_composed.csv"
        self.write_csv(
            escaping_composed,
            ["frame_id", "source_sample_index", "composed_manifest_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": "../outside.json",
            },
        )
        with self.assertRaisesRegex(xml_batch.BatchBuildSionnaXmlError, "escapes run root"):
            xml_batch.load_composed_manifest_index(escaping_composed, run_root)

        missing_xml = self.root / "missing_xml.csv"
        self.write_csv(
            missing_xml,
            ["frame_id", "source_sample_index", "xml_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "xml_path": "sionna_xml/missing.xml",
            },
        )
        with self.assertRaises(rt_batch.ExperimentRtBatchError):
            rt_batch.load_xml_index(missing_xml, run_root)

        escaping_xml = self.root / "escaping_xml.csv"
        self.write_csv(
            escaping_xml,
            ["frame_id", "source_sample_index", "xml_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "xml_path": "../outside.xml",
            },
        )
        with self.assertRaisesRegex(rt_batch.ExperimentRtBatchError, "escapes run root"):
            rt_batch.load_xml_index(escaping_xml, run_root)

    def test_xml_and_rt_loaders_accept_legacy_absolute_paths(self):
        run_root = self.root / "run"
        legacy = self.root / "legacy"
        legacy.mkdir(parents=True)
        composed_manifest = legacy / "composed.json"
        composed_manifest.write_text("{}\n", encoding="utf-8")
        xml_path = legacy / "frame.xml"
        xml_path.write_text("<scene/>\n", encoding="utf-8")
        composed_index = self.root / "legacy_composed.csv"
        self.write_csv(
            composed_index,
            ["frame_id", "source_sample_index", "composed_manifest_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": str(composed_manifest),
            },
        )
        xml_index = self.root / "legacy_xml.csv"
        self.write_csv(
            xml_index,
            ["frame_id", "source_sample_index", "xml_path"],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "xml_path": str(xml_path),
            },
        )
        self.assertEqual(
            xml_batch.load_composed_manifest_index(composed_index, run_root)[0][
                "composed_manifest_path"
            ],
            composed_manifest.resolve(),
        )
        self.assertEqual(
            rt_batch.load_xml_index(xml_index, run_root)[0]["xml_path"],
            xml_path.resolve(),
        )

    def test_restart_generated_indexes_use_run_relative_paths(self):
        run_root = self.root / "run"
        composed_rows, xml_rows = restart_safe.generated_index_rows(run_root, [17])
        self.assertEqual(
            composed_rows[0]["composed_manifest_path"],
            "frames/composed_manifests/frame_017_manifest.json",
        )
        self.assertEqual(
            xml_rows[0],
            {
                "frame_id": 17,
                "source_sample_index": 17,
                "composed_manifest_path": "frames/composed_manifests/frame_017_manifest.json",
                "xml_path": "sionna_xml/frame_017_sionna.xml",
            },
        )
        self.assertNotIn(str(self.root), json.dumps([composed_rows, xml_rows]))
        self.assertNotIn(str(REPOSITORY_ROOT), json.dumps([composed_rows, xml_rows]))


if __name__ == "__main__":
    unittest.main()
