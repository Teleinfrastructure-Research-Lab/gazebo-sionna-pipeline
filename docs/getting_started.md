# Getting Started

This guide is the practical entry point for running the current validated
pipeline. For architecture and extension details, see
[Pipeline Overview](pipeline_overview.md) and [Developer Guide](developer_guide.md).

## Prerequisites

Run commands from the repository root. The pipeline expects:

- Python 3 for manifest, registry, orchestration, and batch scripts.
- `numpy` for transform and manifest checks.
- Blender for static mesh merge, dynamic mesh export, and actor mesh export.
- A Sionna RT + Mitsuba environment for `24`, `35`, and `36`.
- Gazebo only when recording fresh Panda/UR5 pose logs.

Recommended shell setup:

```bash
export SIONNA_PYTHON="$HOME/miniconda3/envs/your_env_name/bin/python"
export BLENDER=blender
```

Use `export BLENDER=/path/to/blender` for a custom Blender install. The scripts
also try to discover these tools automatically, but explicit paths make failures
easier to understand.

Environment setup is currently manual. The repository expects a Python
interpreter with Sionna RT and Mitsuba already installed. Prefer
`SIONNA_PYTHON` for that interpreter. A fully reproducible
`environment.yml` or `requirements.txt` is not yet provided.

## Tested Environment

These versions are known to work in the current development setup. They are
tested examples, not strict requirements:

- Blender 4.5.8 LTS
- Sionna RT in a Python environment of your choice
- Mitsuba variant ending in `_ad_mono_polarized`
- Gazebo Sim with the `gz` CLI available for pose-log generation

## Required Inputs

Before running the actor-free prototype, make sure these exist:

- `myworld_rt.sdf`
- `models/`
- `rt_out/config/dynamic_prototype_config.json`
- `rt_out/config/prototype_radio_sites.json`
- `rt_out/config/rt_material_mapping.json`
- `rt_out/materials/material_map.json`
- static source meshes and converted static mesh cache expected by the manifests
- Panda and UR5 pose logs under `rt_out/poses/` before running `30`

For the optional actor-aware branch, also keep:

- `rt_out/config/actor_dynamic_config.json`
- world-level Gazebo `<actor>` entries in `myworld_rt.sdf`
- actor model assets under `models/`

Generated actor manifest and actor frame sample JSON can be rebuilt with `40`
and `41`; they do not need to be hand-authored.

## Actor-Free Run

This is the normal three-frame Panda/UR5 prototype flow:

```bash
python3 rt_out/scripts/static_scene/00_extract_scene_manifests.py
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 rt_out/scripts/static_scene/02_build_scene_geometry_registry.py
python3 rt_out/scripts/static_scene/03_build_static_scene_registry.py
python3 rt_out/scripts/static_scene/20_merge_static_scene_by_material.py
python3 rt_out/scripts/static_scene/23_build_static_sionna_xml.py
python3 rt_out/scripts/static_scene/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
python3 rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py
python3 rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py
```

The quickstart skips `22_build_static_mitsuba_xml.py` because it emits optional
visual/debug Mitsuba XML, while `23_build_static_sionna_xml.py` emits the Sionna
scene used by RT sanity. Run `22` as an optional inspection step after `20`:

```bash
python3 rt_out/scripts/static_scene/22_build_static_mitsuba_xml.py
```

Outputs land mainly under:

- `rt_out/manifests/`
- `rt_out/static_scene/export/`
- `rt_out/dynamic_frames/`
- `rt_out/dynamic_scene/frame_XXX/`
- `rt_out/composed_scene/frame_XXX/`

## Actor-Aware Run

The actor-aware branch is optional and validated only for the three prototype
frames. It reuses the static and rigid dynamic products, then adds actor mesh
exports during `35` and `36`.

```bash
python3 rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py
python3 rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

Use the detailed actor guide when changing actor timing, alignment, materials,
or validation scenes: [Actor-Aware 3-Frame Pipeline](actor_aware_3frame_pipeline.md).

## Run The Actor-Aware 200-Frame Experiment

The actor-aware 200-frame branch lives under
`rt_out/experiments/semantic_ablation_actor_200f/`. Its high-level order is:

1. sample frames
2. build rigid frame metadata
3. build actor frame samples
4. export rigid and actor meshes
5. compose actor-aware manifests
6. build Sionna XML
7. run RT
8. build labels and features
9. run ablations

Use the dedicated guide instead of expanding the three-frame commands by hand:
[Actor-Aware Semantic Ablation 200f Pipeline](semantic_ablation_actor_200f_pipeline.md).

## Pose-Log Generation

Pose logs are required before running `30` if the robot motion data has changed.
Start the RT world, then run:

```bash
bash rt_out/scripts/ops/run_all.sh
```

`run_all.sh` records both pose topics while running:

- `rt_out/scripts/ops/run_panda.sh`
- `rt_out/scripts/ops/run_ur5.sh`

The resulting logs are consumed through `dynamic_prototype_config.json`.

## Basic Validation Checks

Useful quick checks:

```bash
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 -m py_compile rt_out/scripts/**/*.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

If your shell does not expand `**`, use:

```bash
find rt_out/scripts -name '*.py' -print0 | xargs -0 python3 -m py_compile
```

For failures, see [Troubleshooting](troubleshooting.md).
