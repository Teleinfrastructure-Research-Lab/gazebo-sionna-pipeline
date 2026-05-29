# Pipeline Overview

This repository is a Gazebo-to-Sionna RT project with several validated
branches built around the same scene assets. The core workflow is RT-focused:
extract scene geometry and materials from Gazebo inputs, generate Sionna-ready
scene descriptions, run ray tracing, and build labels and features for wireless
prediction experiments. The panoptic perception branch is an additional pilot,
not a replacement for the validated RT branches.

## Static RT Pipeline

High-level flow:

```text
Gazebo/SDF world
  -> manifests and geometry registry
  -> merged static scene assets
  -> Mitsuba / Sionna XML
  -> RT outputs and validation summaries
```

The static branch is the stable foundation used by the dynamic and experiment
pipelines. It turns `myworld_rt.sdf` plus `models/` assets into a frozen static
baseline that later branches reuse.

## Rigid Dynamic Pipeline

High-level flow:

```text
Panda / UR5 pose logs
  -> sampled rigid frames
  -> per-frame rigid mesh placement
  -> composed manifests and frame XML
  -> RT rows
  -> labels and features
```

This branch treats robot dynamics as rigid-link transforms from logged poses.
It is the basis for the rigid prototype and the
`semantic_ablation_rigid_200f` experiment branch.

## Actor-Aware Pipeline

Gazebo actors are handled separately from rigid robot dynamics because actors
use animated skinned meshes rather than rigid links with direct pose logs.

High-level flow:

```text
Gazebo actor metadata
  -> actor frame sampling
  -> approximate baked actor mesh export
  -> composition with static + rigid scene
  -> frame XML
  -> RT rows, labels, and features
```

The current actor export path uses approximate mesh sampling and placement for
RT purposes. It should not be claimed to perfectly match Gazebo runtime
animation phase.

## Semantic / Object-Aware Feature Experiments

The two validated 200-frame experiment branches build on the static, rigid, and
actor-aware scene pipelines:

- `semantic_ablation_rigid_200f`
- `semantic_ablation_actor_200f`

These branches produce:

- RT rows
- transition labels
- compact object-aware features
- raw occupancy features
- classical prediction/ablation outputs

For the current actor-aware pilot, compact object-aware features outperform raw
occupancy on the tracked tasks:

- adaptation trigger F1: `0.411` vs `0.272`
- path change F1: `0.582` vs `0.527`

The actor-aware compact path-change score also exceeds the rigid compact
baseline in the current branch: `0.582` vs `0.509`.

## Panoptic Perception Pilot

`perception_rt_small_v0` is the current Gazebo-native perception pilot that now
extends beyond panoptic capture to a strict final labeled RGB point-cloud
export. It does not replace the existing RT branches; it links perception
artifacts back to the validated actor-aware wireless source. In the current
checkout that actor-aware source may be read from
`rt_out/experiments/semantic_ablation.zip` rather than from an unpacked
`semantic_ablation_actor_200f/` directory.

Current design:

- primary world:
  `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_panoptic_world.sdf`
- stable-instance sibling world:
  `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_stable_instance_panoptic_world.sdf`
- selected source frames: `20`
- fixed cameras: `8`
- expected perception samples: `160`
- primary capture mode: `panoptic`
- semantic label decoding: `rgb[2]`
- Gazebo instance count decoding: `rgb[1] * 256 + rgb[0]`
- stable object identity remains separate in
  `rt_out/experiments/perception_rt_small_v0/frames/instance_registry.json`
- final main product:
  `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/`
- final public PLY fields:
  `x y z red green blue class_label instance_id`

Current validated interpretation:

- RT links are complete: `160/160`
- wireless transition-label links are `152/160`
- perception/PCL products currently exist for `24/160` frame-camera rows
- those `24` rows correspond to selected frames `0`, `1`, and `2` across `8`
  cameras
- missing `136/160` perception/PCL rows are expected in the current pilot
- therefore the dataset index may still report `overall_passed = false` even
  though all available perception/PCL validations pass

Current main perception pipeline:

1. select frames
2. build instance registry
3. build semantic and stable-instance Gazebo worlds
4. capture semantic panoptic segmentation
5. validate panoptic capture
6. capture synchronized stable-instance labels + RGB + PCL
7. validate synchronized stable-instance capture
8. build final labeled RGB PCLs
9. validate final labeled RGB PCLs
10. build the central panoptic dataset index linking perception artifacts to RT
    rows and wireless labels



## Repository Structure

```text
models/                                            Gazebo models, robots, actors, and meshes
rt_out/scripts/                                    main pipeline scripts
rt_out/scripts/static_scene/                       static extraction, merge, XML, RT sanity
rt_out/scripts/dynamic_rigid/                      rigid frame generation and RT sanity
rt_out/scripts/dynamic_actor/                      actor sampling and actor mesh export
rt_out/scripts/experiments/                        batch experiment wrappers, labels, features
rt_out/scripts/validation/                         actor and scene diagnostics
rt_out/scripts/ops/                                Gazebo environment and pose-log helpers
rt_out/scripts/perception/                         panoptic perception pilot scripts
rt_out/experiments/semantic_ablation_rigid_200f/   validated rigid 200-frame experiment
rt_out/experiments/semantic_ablation_actor_200f/   validated actor-aware 200-frame experiment
rt_out/experiments/semantic_ablation.zip           fallback archive for actor-aware RT/label source data
rt_out/experiments/perception_rt_small_v0/         panoptic perception pilot
```

## Current Validated Branches

- Static scene export and RT validation
- Rigid Panda/UR5 prototype branch
- Actor-aware prototype branch
- `semantic_ablation_rigid_200f`
- `semantic_ablation_actor_200f`
- `perception_rt_small_v0` as a pilot extension

