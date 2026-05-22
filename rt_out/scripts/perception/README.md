# Perception Scripts

`perception_rt_small_v0` is the current Gazebo-native perception pilot for this
repository. The active checkout is panoptic-only.

Important current assumptions:

- no semantic-only perception world is part of the active checkout
- no instance-only perception world is part of the active checkout
- no legacy folder is present in the current checkout
- historical replay-SDF and split semantic/instance perception designs were
  removed from the active checkout

## Active Script Flow

The active numbered scripts are:

- `60_select_perception_frames.py`
- `61_build_perception_instance_registry.py`
- `62_build_labeled_gazebo_world.py`
- `63_run_gazebo_native_capture.py`
- `64_capture_segmentation_topics.py`
- `65_preview_native_segmentation_capture.py`
- `66_validate_native_segmentation_capture.py`
- `67_extract_camera_rig_from_gazebo_pose.py`

## Current Data Design

- primary world:
  `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_panoptic_world.sdf`
- primary capture mode: `panoptic`
- current source frames: `20`
- fixed cameras: `8`
- expected perception samples: `160`
- stable object metadata:
  `rt_out/experiments/perception_rt_small_v0/frames/instance_registry.json`

Optional helper worlds still exist when requested:

- `gazebo_native_camera_tuning_world.sdf`
- `gazebo_native_camera_debug_world.sdf`

Those helper worlds also use panoptic sensors.

## Panoptic Decoding

Capture uses Gazebo Transport topics because Gazebo `<save>` did not emit files
reliably on this setup.

For the active panoptic labels map:

- `semantic_id = rgb[2]`
- `gazebo_instance_count = rgb[1] * 256 + rgb[0]`

`gazebo_instance_count` is not the stable dataset `instance_id`.

The compact semantic taxonomy is:

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

Label `0` is treated as invalid or unlabeled during validation.

## Workflow

1. Select the source frames:

```bash
python3 rt_out/scripts/perception/60_select_perception_frames.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json
```

2. Build the stable instance registry:

```bash
python3 rt_out/scripts/perception/61_build_perception_instance_registry.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json
```

3. Build the panoptic Gazebo world:

```bash
python3 rt_out/scripts/perception/62_build_labeled_gazebo_world.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --force
```

4. Optional camera tuning world:

```bash
python3 rt_out/scripts/perception/62_build_labeled_gazebo_world.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --camera-tuning-world \
  --force
```

Launch the tuning world:

```bash
bash rt_out/scripts/ops/run_gazebo_gpu.sh \
  rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_camera_tuning_world.sdf
```

Export tuned camera poses:

```bash
timeout 3 gz topic -e -t /world/small_factory_room/pose/info > /tmp/camera_pose_dump.txt
python3 rt_out/scripts/perception/67_extract_camera_rig_from_gazebo_pose.py \
  --pose-log /tmp/camera_pose_dump.txt \
  --output-json /tmp/camera_rig_tuned.json
```

5. Launch the primary panoptic world:

```bash
bash rt_out/scripts/ops/run_gazebo_gpu.sh \
  rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_panoptic_world.sdf
```

6. Capture the panoptic topics:

```bash
python3 rt_out/scripts/perception/64_capture_segmentation_topics.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --mode panoptic \
  --max-messages-per-topic 3 \
  --timeout-seconds 30 \
  --force
```

The topic-capture index and summary describe only the most recent capture run.

7. Generate previews:

```bash
python3 rt_out/scripts/perception/65_preview_native_segmentation_capture.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --force
```

8. Validate the capture:

```bash
python3 rt_out/scripts/perception/66_validate_native_segmentation_capture.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --zero-threshold 0.01
```

## Active Raw Outputs

The active raw panoptic tree is:

`rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/`

Each camera folder contains:

- `labels_maps_rgb/`
- `semantic_decoded/`
- `gazebo_instance_count/`
- `colored_maps/`
- `metadata/`

## Notes

- `63_run_gazebo_native_capture.py` is an optional launch helper. The active
  dataset is produced by `64_capture_segmentation_topics.py`.
- The current camera rig uses eight fixed viewpoints:
  `cam_corner_nw`, `cam_corner_ne`, `cam_corner_sw`, `cam_corner_se`,
  `cam_wall_north`, `cam_wall_south`, `cam_wall_east`, `cam_wall_west`.
