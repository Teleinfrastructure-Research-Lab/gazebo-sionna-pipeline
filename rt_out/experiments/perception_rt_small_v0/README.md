# perception_rt_small_v0

This experiment is the current Gazebo-native panoptic perception pilot for the
Gazebo-to-Sionna RT project. It is an additional branch built on top of the
validated RT pipelines, especially `semantic_ablation_actor_200f`.

## Purpose

- select a small set of source frames from the actor-aware 200-frame branch
- capture Gazebo-native panoptic segmentation from a fixed 8-camera rig
- prepare perception artifacts that can later be aligned with RT rows and
  wireless labels

## Active Configs

- `configs/perception_dataset_config.json`
- `configs/semantic_label_map.json`
- `configs/camera_rig.json`
- `configs/camera_rig_8cam_seeded.json`
- `configs/camera_rig_before_8cam_expansion.json`

## Active Frame Metadata

- `frames/selected_frames.json`
- `frames/selected_frames_summary.json`
- `frames/instance_registry.json`
- `frames/instance_registry_summary.json`

## Active Generated Outputs

- primary world:
  `perception_sdf/gazebo_native_panoptic_world.sdf`
- world summary:
  `perception_sdf/gazebo_native_world_summary.json`
- Gazebo label/debug mapping:
  `perception_sdf/instance_label_map.json`
- active raw output:
  `perception_raw/native/panoptic/`
- validation summary:
  `validation/native_segmentation_validation_summary.json`
- validation histograms:
  `validation/native_segmentation_label_histograms.csv`
- validation invalid-pixel report:
  `validation/native_segmentation_invalid_pixels.csv`
- previews:
  `validation/previews/`

## Panoptic Encoding

- semantic label = channel `2`
- Gazebo instance count = `rgb[1] * 256 + rgb[0]`
- `gazebo_instance_count` is not the stable dataset `instance_id`
- stable object metadata remains in `frames/instance_registry.json`

The active semantic taxonomy is:

- `1 floor`
- `2 ceiling`
- `3 wall`
- `4 door`
- `5 window`
- `6 table`
- `7 chair`
- `8 robot`
- `9 human`
- `10 misc_object`

## Current Validation Status

Current validated snapshot from
`validation/native_segmentation_validation_summary.json`:

- `primary_mode = panoptic`
- `overall_passed = true`
- `expected_camera_count = 8`
- `expected_semantic_decoded_count = 24`
- `expected_gazebo_instance_count_count = 24`

## Usually Not Committed

This branch includes large generated artifacts that are usually better kept out
of Git unless intentionally curated:

- raw panoptic masks and images under `perception_raw/native/panoptic/`
- preview images under `validation/previews/`
- generated SDFs if you treat them as reproducible build outputs
- logs and temporary capture artifacts

## Notes

- The active checkout is panoptic-only.
- No semantic-only or instance-only perception world is part of the current
  active workflow.
- Historical replay-SDF and split semantic/instance perception paths were
  removed from the active checkout.
- For the active 60-67 workflow, use `rt_out/scripts/perception/README.md`.
