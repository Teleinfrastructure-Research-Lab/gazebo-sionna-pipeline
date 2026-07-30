# Three-frame actor-aware prototype

## 1. Purpose

This is the small actor-aware test used to check actor manifest extraction,
Blender baking, composition, XML generation, and a small Sionna RT solve. It is
not the 2,446-frame experiment and it does not reproduce the full actor phase.

## 2. Status

`Validated small test`. The current scripts support this test, but their
default paths still point at the old saved run unless explicit paths are
supplied.

## 3. Difference from the main pipeline

It uses exactly three prototype frame IDs and can run through a small test
script. Actor-free and actor-aware script modes are alternatives. Actor export applies
`bounds_center_xy_to_root`, `bounds_min_z_to_floor`, and `floor_z=0.1` when
`--include-actors` is selected.

## 4. Experiment and run layout

Use a unique run root and keep generated files under:

```text
<run>/config/
<run>/manifests/actor_manifest.json
<run>/frames/actor_frame_samples.json
<run>/frames/actor_meshes/frame_000/
<run>/frames/composed_manifests/
<run>/sionna_xml/
<run>/rt_results/
```

Do not use the old shared `rt_out/dynamic_scene/` or
`rt_out/composed_scene/` locations for a new run.

## 5. Required configuration files

- `myworld_rt.sdf` and `models/`;
- resolved `dynamic_prototype_config.json`;
- resolved `actor_dynamic_config.json`;
- resolved `rt_material_mapping.json`;
- merged static manifest;
- a three-frame `sampled_frames.json`/dynamic manifest and pose logs.

## 6. Environment setup

```bash
REPO_ROOT="$(pwd)"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/actor_aware_3frame/run_$(date +%Y%m%d_%H%M%S)"
BLENDER="<path-to-blender>"
SIONNA_PYTHON="<path-to-sionna-python>"
export PIPELINE_RUN_DIR="$RUN_ROOT" BLENDER SIONNA_PYTHON
source rt_out/scripts/ops/setup_gazebo_env.sh
mkdir -p "$RUN_ROOT"/{config,manifests,frames,sionna_xml,rt_results,reports}
```

## 7. Complete end-to-end command sequence

Extract actor metadata:

```bash
python3 rt_out/scripts/dynamic_actor/extract_actor_manifest.py \
  --world "$REPO_ROOT/myworld_rt.sdf" \
  --models-root "$REPO_ROOT/models" \
  --output "$RUN_ROOT/manifests/actor_manifest.json"
```

Build actor samples for the selected three frames:

```bash
python3 rt_out/scripts/dynamic_actor/build_actor_frame_samples.py \
  --actor-manifest "$RUN_ROOT/manifests/actor_manifest.json" \
  --actor-config "$RUN_ROOT/config/actor_dynamic_config.json" \
  --dynamic-prototype-config "$RUN_ROOT/config/dynamic_prototype_config.json" \
  --rt-material-config "$RUN_ROOT/config/rt_material_mapping.json" \
  --output "$RUN_ROOT/frames/actor_frame_samples.json"
```

For one frame, manually export, compose, and emit XML:

```bash
python3 rt_out/scripts/dynamic_actor/export_actor_frame_meshes.py \
  --frame-id 0 \
  --actor-samples "$RUN_ROOT/frames/actor_frame_samples.json" \
  --actor-manifest "$RUN_ROOT/manifests/actor_manifest.json" \
  --output-root "$RUN_ROOT/frames/actor_meshes" \
  --blender "$BLENDER" \
  --alignment-policy bounds_center_xy_to_root \
  --z-alignment-policy bounds_min_z_to_floor \
  --floor-z 0.1
python3 rt_out/scripts/dynamic_rigid/compose_frame_scene.py \
  --frame-id 0 \
  --static-manifest "$RUN_ROOT/static_scene/export/merged_static_manifest.json" \
  --dynamic-manifest "$RUN_ROOT/frames/dynamic_meshes/frame_000/dynamic_frame_000_manifest.json" \
  --actor-frame-manifest "$RUN_ROOT/frames/actor_meshes/frame_000/actor_frame_000_manifest.json" \
  --output-manifest "$RUN_ROOT/frames/composed_manifests/frame_000_manifest.json"
python3 rt_out/scripts/dynamic_rigid/build_frame_sionna_xml.py \
  --frame-id 0 \
  --rt-material-config "$RUN_ROOT/config/rt_material_mapping.json" \
  --input-manifest "$RUN_ROOT/frames/composed_manifests/frame_000_manifest.json" \
  --output-xml "$RUN_ROOT/sionna_xml/frame_000_sionna.xml"
```

The current scripts that run several prototype steps are the preferred entry
points when their default/static paths have been made explicit:

```bash
python3 rt_out/scripts/dynamic_rigid/run_three_frame_rt_sanity.py \
  --static-manifest "$RUN_ROOT/static_scene/export/merged_static_manifest.json" \
  --composed-root "$RUN_ROOT" \
  --include-actors --actor-samples "$RUN_ROOT/frames/actor_frame_samples.json" \
  --actor-manifest "$RUN_ROOT/manifests/actor_manifest.json" \
  --sionna-python "$SIONNA_PYTHON"
python3 rt_out/scripts/dynamic_rigid/run_three_frame_multi_rx_rt_sanity.py \
  --static-manifest "$RUN_ROOT/static_scene/export/merged_static_manifest.json" \
  --composed-root "$RUN_ROOT" \
  --include-actors --actor-samples "$RUN_ROOT/frames/actor_frame_samples.json" \
  --actor-manifest "$RUN_ROOT/manifests/actor_manifest.json" \
  --sionna-python "$SIONNA_PYTHON"
```

The two scripts are alternatives, not consecutive required stages.

## 8. Smoke/debug sequence

Use one explicit frame and `--help`/manifest validation first. These scripts
form the small-test path; do not launch full 2,446-frame generation from this
guide.

## 9. Full-run sequence

There is no full-run command for this three-frame prototype. The complete
workload is three frames; use the manual sequence or small-test script above.

## 10. Restart/resume sequence

The script validates existing frame manifests and XML/RT chunks where
available. An invalid existing output is an error, not a reason to append new
rows. Use a new run root after changing actor alignment or material policy.

## 11. Expected inputs and outputs

Expected counts are three sampled frames, 21 rigid visual meshes per frame,
one actor mesh per frame, 33 composed entries per actor-aware frame, and the
RX count selected by the chosen sanity harness.

## 12. Validation commands

```bash
python3 rt_out/scripts/validation/build_actor_prototype_mesh_index.py \
  --actor-frame-manifests "$RUN_ROOT/frames/actor_meshes/frame_000/actor_frame_000_manifest.json" \
  --output "$RUN_ROOT/reports/actor_mesh_index.json"
python3 rt_out/scripts/validation/diagnose_actor_validation_alignment.py --help
python3 rt_out/scripts/validation/diagnose_actor_floor_alignment.py --help
python3 -m json.tool "$RUN_ROOT/frames/actor_frame_samples.json" >/dev/null
```

Inspect actor material, shape counts, transforms, mesh existence, and the
alignment metadata. The export is an RT-oriented baked approximation.

## 13. Output directory tree

```text
<run>/
├── config/
├── manifests/actor_manifest.json
├── frames/actor_frame_samples.json
├── frames/actor_meshes/frame_000/{actor_meshes,actor_metadata,manifest}.json
├── frames/composed_manifests/
├── sionna_xml/
├── rt_results/
└── reports/
```

## 14. Known limitations

- Default legacy paths remain in several prototype helpers.
- Actor runtime animation phase is not claimed.
- The prototype is not a substitute for the current 2,446-frame guide.

## 15. Links

- [Complete pipeline sequence](../pipeline_execution_order.md)
- [Configuration](../configuration.md)
- [Script reference](../script_reference.md)
