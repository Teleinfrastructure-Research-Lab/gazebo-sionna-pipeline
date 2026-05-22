# Troubleshooting

Common issues across the current Gazebo-to-Sionna RT project.

## Sionna Or Mitsuba Import Fails

Symptoms:

- `Could not import Sionna RT`
- Mitsuba variant errors
- `PathSolver` import errors

Checks:

```bash
echo "$SIONNA_PYTHON"
$SIONNA_PYTHON -c "import sionna.rt, mitsuba as mi; print(mi.variant())"
```

Use the same Sionna/Mitsuba-capable interpreter for the static sanity run, the
prototype RT harnesses, and the experiment wrappers. If an older wrapper still
refers to `COLLABPAPER_PYTHON`, point it at the same interpreter.

## Gazebo Resource Paths Look Wrong

If Gazebo cannot find models, textures, or nested resources, load the shared
setup first:

```bash
source rt_out/scripts/ops/setup_gazebo_env.sh
```

For launches that should use the intended GPU environment, prefer:

```bash
bash rt_out/scripts/ops/run_gazebo_gpu.sh <world.sdf>
```

## Gazebo Uses CPU Rendering Or The Wrong GPU

`glxinfo` can still show Mesa or `llvmpipe` if Gazebo was launched without the
intended PRIME offload or GPU environment.

Checks:

```bash
watch -n 1 nvidia-smi
```

Run the world through `run_gazebo_gpu.sh` while watching `nvidia-smi`. The
helper sets the intended rendering variables for this project.

## Blender Not Found

Symptoms:

- static merge fails before launching a Blender worker
- rigid mesh export cannot find Blender
- actor export fails before writing meshes

Set:

```bash
export BLENDER=blender
```

Or use a full path:

```bash
export BLENDER=/path/to/blender
```

## Missing Converted Static Meshes

Symptoms:

- `20_merge_static_scene_by_material.py` reports missing source meshes
- static registry entries cannot be imported by Blender

Checks:

```bash
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 rt_out/scripts/static_scene/02_build_scene_geometry_registry.py
python3 rt_out/scripts/static_scene/03_build_static_scene_registry.py
```

If a model asset changed, rebuild the relevant static path before rerunning the
merge or XML stages.

## Missing Pose Logs

Symptoms:

- `30_build_prototype_dynamic_frames.py` cannot find Panda or UR5 logs
- sampled source indices are out of range

Generate fresh logs by launching the RT world and running:

```bash
bash rt_out/scripts/ops/run_all.sh
```

Then confirm the paths in `rt_out/config/dynamic_prototype_config.json`.

## Actor Alignment Looks Wrong

Actor drift usually means the baked mesh bounds do not visually align with the
sampled root pose.

Useful checks:

```bash
python3 rt_out/scripts/validation/53_diagnose_actor_validation_alignment.py
python3 rt_out/scripts/validation/55_diagnose_actor_floor_alignment.py
python3 rt_out/scripts/validation/56_build_composed_frame_blender_scene.py \
  --composed-manifest rt_out/composed_scene/frame_000/composed_frame_000_manifest.json
```

The current actor export uses approximate offline placement for RT export. It
should not be described as exact Gazebo runtime animation-phase matching.

## Actor-Aware 200-Frame Experiment Has Too Few RT Rows

The actor-aware 200-frame branch supports debug runs with fewer frames.

Checks:

- `18` rows means `3` frames x `6` RX
- `120` rows means `20` frames x `6` RX
- the full branch expects `1200` RT rows before building full labels and
  features

Do not build final labels or features from a debug-only RT CSV unless that is
the branch you actually want.

## Perception Topics Show No Data

For the active perception pilot, the capture topics are panoptic:

```bash
gz topic -l | grep /perception/native/panoptic
```

No captured messages usually means one of these:

- the Gazebo world is not running
- the panoptic world is still loading and not publishing yet
- the wrong world was launched
- the wrong capture mode was requested

The active perception path is panoptic-only. Missing semantic-only or
instance-only perception worlds is expected in the current checkout.

## C++ Topic-Capture Helper Does Not Build

If the perception topic-capture helper fails to compile, confirm a C++
frontend is available:

```bash
g++ --version
clang++ --version
bash rt_out/scripts/perception/cpp/build_capture_segmentation_topics.sh
```

Install `g++` or `clang++` if neither exists.

## Panoptic Validation Fails

Useful checks:

```bash
python3 rt_out/scripts/perception/66_validate_native_segmentation_capture.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --zero-threshold 0.01
```

If the zero-label ratio is high:

- inspect
  `rt_out/experiments/perception_rt_small_v0/validation/native_segmentation_validation_summary.json`
- inspect the generated previews under
  `rt_out/experiments/perception_rt_small_v0/validation/previews/`

Label `0` is treated as invalid or unlabeled, but tiny ratios below the
configured threshold are allowed.

## Current Perception Assumptions

The active perception pilot uses:

- panoptic topic capture
- semantic labels from channel `2`
- Gazebo instance count from `rgb[1] * 256 + rgb[0]`

`gazebo_instance_count` is not the stable dataset instance ID. Stable object
metadata remains in
`rt_out/experiments/perception_rt_small_v0/frames/instance_registry.json`.
