# Gazebo To Sionna RT Pipeline

This repository converts a Gazebo lab world into Mitsuba/Sionna RT scene inputs
for wireless ray-tracing experiments. It extracts static and dynamic scene
manifests, prepares mesh geometry, emits static and frame-specific Sionna XML,
and runs small regression flows for a Panda/UR5 prototype scene.

## Environment Setup

The repository currently assumes you already have a Python environment with
Sionna RT and Mitsuba installed. Set `SIONNA_PYTHON` to that interpreter, for
example:

```bash
export SIONNA_PYTHON="$HOME/miniconda3/envs/your_env_name/bin/python"
export BLENDER=blender
```

A fully reproducible `environment.yml` or `requirements.txt` is not yet
provided, so environment setup is still manual.

The current validated scope is intentionally narrow:

- Static Gazebo scene export to Mitsuba and Sionna RT XML.
- Rigid dynamic prototype motion for `Panda` and `ur5_rg2`.
- Three validated prototype frames.
- Optional actor-aware export/composition for those same three frames.
- A 28 GHz Sionna RT baseline with single-RX and three-RX sanity runners.
- A validated `semantic_ablation_rigid_200f` experiment branch for rigid Panda/UR5 only.
- A validated `semantic_ablation_actor_200f` experiment branch with static scene + Panda/UR5 + a moving human actor, including RT, labels, object-aware features, raw occupancy features, and ablations.

## Quickstart: Actor-Free Prototype

Run from the repository root:

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

## Quickstart: Optional Actor-Aware Prototype

Actor support is validated only for the optional three-frame prototype branch.
`35` and `36` remain actor-free unless `--include-actors` is passed.

```bash
python3 rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py
python3 rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

Current validation status: actor-free `35`, actor-aware `35`, and actor-aware
`36` pass. Delay statistics are populated for rows that have paths; zero-path
rows remain valid completed RT solves.

## 200-Frame Experiment Branches

- `semantic_ablation_rigid_200f`: rigid baseline branch for static scene + Panda/UR5 only.
- `semantic_ablation_actor_200f`: actor-aware branch for static scene + Panda/UR5 + moving human actor. This branch has been validated through mesh export, composition, XML, RT, labels, object-aware features, raw occupancy features, and ablations.

## Documentation

- [Getting Started](docs/getting_started.md): prerequisites, required inputs, setup, and basic validation.
- [Pipeline Overview](docs/pipeline_overview.md): architecture, script folders, branches, and validated scope.
- [Configuration](docs/configuration.md): user-editable config files and when to change them.
- [Script Reference](docs/script_reference.md): compact reference for every script group.
- [Developer Guide](docs/developer_guide.md): manifest contracts, extension guidance, design decisions, and testing expectations.
- [Actor-Aware 3-Frame Pipeline](docs/actor_aware_3frame_pipeline.md): actor-specific commands, alignment policies, validation tools, and limitations.
- [Semantic Ablation 200f Pipeline](docs/semantic_ablation_200f_pipeline.md): rigid-only experiment workflow and outputs.
- [Actor-Aware Semantic Ablation 200f Pipeline](docs/semantic_ablation_actor_200f_pipeline.md): actor-aware 200-frame workflow, debug commands, expected counts, label changes, and ablation snapshot.
- [Troubleshooting](docs/troubleshooting.md): common environment, mesh, actor, RT, and stale-path issues.

