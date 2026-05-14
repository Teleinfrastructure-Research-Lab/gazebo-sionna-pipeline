# Pipeline Overview

This document explains the repository layout and the main RT pipeline branches.
It is the single central place that describes the script folder structure.

## Validated Scope

The current validated pipeline covers:

- static scene extraction and Sionna/Mitsuba XML export
- rigid Panda/UR5 dynamic frame processing
- three prototype frames
- optional actor export/composition for those same three frames
- 28 GHz Sionna sanity runs
- rigid `semantic_ablation_rigid_200f` experiment wrappers
- actor-aware `semantic_ablation_actor_200f` experiment wrappers with RT, labels, features, and ablations

The pipeline does not claim fully general Gazebo model support, arbitrary actor
support, or Gazebo-runtime-perfect actor animation phase reconstruction.

## Repository Structure

```text
myworld_rt.sdf                 RT-oriented Gazebo world input
models/                        Gazebo model and mesh assets
rt_out/config/                 pipeline and radio/material configs
rt_out/materials/              semantic material mapping rules
rt_out/manifests/              extracted and derived scene manifests
rt_out/static_scene/           converted and merged static outputs
rt_out/dynamic_frames/         sampled rigid and actor frame metadata
rt_out/dynamic_scene/          per-frame rigid and actor mesh exports
rt_out/composed_scene/         static + dynamic frame manifests and XMLs
rt_out/experiments/            experiment-local outputs and configs
rt_out/scripts/                pipeline scripts and helper modules
docs/                          user and developer documentation
```

## Script Folder Structure

```text
rt_out/scripts/
  static_scene/      static extraction, registries, merge, XML, base RT sanity
  dynamic_rigid/     Panda/UR5 rigid frame building, export, composition, 35/36
  dynamic_actor/     optional actor manifest, samples, and posed mesh export
  validation/        actor diagnostics and Blender inspection builders
  experiments/       rigid and actor-aware semantic ablation batch wrappers
  ops/               Gazebo operational helpers for Panda/UR5 pose logs
  dynamic_prototype_config.py
  rt_material_config.py
```

The root helper modules remain at `rt_out/scripts/` so moved scripts can import
shared config loaders by inserting `rt_out/scripts` into `sys.path`.

## Static Branch

The static branch reads `myworld_rt.sdf`, resolves model assets, builds static
geometry registries, merges renderable geometry by semantic material, and emits
static XML.

Main stages:

- `00_extract_scene_manifests.py`
- `01_validate_scene_manifests.py`
- `02_build_scene_geometry_registry.py`
- `03_build_static_scene_registry.py`
- `20_merge_static_scene_by_material.py`
- `23_build_static_sionna_xml.py`
- `24_run_sionna_rt_sanity.py`

The merged static manifest is treated as a frozen baseline for frame composition
and experiments.

## Rigid Panda/UR5 Dynamic Branch

The rigid dynamic branch is link-pose based. It reads pose logs, samples the
configured prototype frames, joins link poses to renderable visuals, exports
posed robot meshes, composes static + dynamic frame manifests, emits frame XML,
and runs sanity checks.

Main stages:

- `30_build_prototype_dynamic_frames.py`
- `31_build_prototype_dynamic_visual_frames.py`
- `32_export_dynamic_frame_meshes.py`
- `33_compose_prototype_frame_scene.py`
- `34_build_prototype_frame_sionna_xml.py`
- `35_run_prototype_three_frame_rt_sanity.py`
- `36_run_three_frame_three_rx_rt_sanity.py`

`35` exports rigid meshes for the three frames. `36` expects those rigid frame
exports to exist and evaluates the same composed branch across the approved RX
sites.

## Optional Actor Branch

Gazebo actors are handled separately from Panda/UR5 because they are skinned
animated meshes rather than rigid links with pose logs. The actor branch:

- extracts world-level actor metadata
- builds actor frame samples for the three prototype frames
- exports baked actor PLYs through Blender
- passes actor frame manifests into the normal composition/XML path

Actor-aware runs are opt-in:

```bash
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

Current validation status: actor-free `35`, actor-aware `35`, and actor-aware
`36` pass.

## Semantic Ablation Experiment Branches

The repository now has two 200-frame experiment branches:

- `semantic_ablation_rigid_200f`: static scene + Panda/UR5 only.
- `semantic_ablation_actor_200f`: static scene + Panda/UR5 + moving human actor.

Both branches reuse the frozen static baseline, the same TX/RX setup, and the
same RT/material configuration. The actor-aware branch acts as a stress test for
object-aware side information under human motion rather than a new radio stack.

## What Is Validated

Validated now:

- current static scene assets and material mapping
- three-frame Panda/UR5 rigid prototype
- actor-aware composition for the optional three-frame prototype
- Sionna path-count and delay-stat sanity outputs for `35`/`36`
- rigid `semantic_ablation_rigid_200f` experiment through RT, labels, features, and ablations
- actor-aware `semantic_ablation_actor_200f` experiment through RT, labels, object-aware features, raw occupancy features, and ablations

Not validated now:

- arbitrary robot models without config and pose-log work
- arbitrary actor trajectories or actor timing policies
- Gazebo-runtime-perfect actor phase reconstruction for the 200-frame actor branch
- full proactive beamforming/resource allocation beyond the current RT-derived supervision setup
- generated-output commit hygiene for large meshes, CSVs, `.blend` files, or feature tables
