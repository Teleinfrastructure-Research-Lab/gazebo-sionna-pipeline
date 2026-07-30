# `perception_rt_small_v0` perception pilot

## 1. Purpose

This is a separate Gazebo-native perception branch that links selected camera
captures to an existing RT experiment. It builds panoptic labels, synchronized
RGB/depth/point topics, labeled colorized PCLs, and a central index. It is not
part of the mandatory Sionna RT scene-generation sequence.

## 2. Status

`Saved partial experiment`. The scripts remain in the repository, but the
validated run is stored at
`rt_out/experiments/perception_rt_small_v0/run_20260522_133045.zip`; the live
directory is not a complete unpacked current input tree. The recorded coverage
is 24/160 final frame-camera PCL rows.

## 3. Differences from the main pipeline

The branch starts from a selected subset of a source experiment, creates
Gazebo-native labeled worlds, captures topics from a live Gazebo process, and
reconstructs RGB PCLs. It does not generate the RT scene or replace the GT
scene PCL branch.

## 4. Experiment and run layout

After unpacking the archive into a temporary or dedicated run directory:

```text
<perception-run>/config/
├── perception_dataset_config.json
├── camera_rig.json
└── semantic_label_map.json
<perception-run>/frames/
<perception-run>/perception_sdf/
<perception-run>/perception_raw/native/
<perception-run>/reconstruction/labeled_colorized_pcl_sync/
<perception-run>/dataset_index/
```

The archived config selects 20 source frames, eight cameras, and 160 expected
frame-camera samples. Its source experiment path references an archived actor
200-frame run; resolve that path before capture.

## 5. Required configuration and environment

Gazebo Sim/`gz`, `myworld_rt.sdf`, `models/`, Python 3, a C++17 compiler,
`pkg-config`, `gz-transport`, `gz-msgs`, and optionally OpenCV4. The generated
world uses semantic panoptic labels in channel 2 and Gazebo runtime instance
counts in channels 1 and 0. Stable dataset instance IDs come from the
experiment-local registry, not directly from the Gazebo count.

## 6. Environment setup

```bash
REPO_ROOT="$(pwd)"
PERCEPTION_ROOT="$REPO_ROOT/rt_out/experiments/perception_rt_small_v0/run_20260522_133045"
source rt_out/scripts/ops/setup_gazebo_env.sh
test -f "$PERCEPTION_ROOT/config/perception_dataset_config.json"
```

If the archive is the only source, unpack it into
`rt_out/experiments/perception_rt_small_v0/` and confirm the paths in the
config before running any stage. Do not overwrite an existing run.

## 7. Complete end-to-end command sequence

Select frames and build the stable registry/worlds:

```bash
python3 rt_out/scripts/perception/capture/select_perception_frames.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/capture/build_perception_instance_registry.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/capture/build_labeled_gazebo_world.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json" \
  --build-stable-instance-panoptic-world
```

Build the C++ topic helpers when they are not already present:

```bash
bash rt_out/scripts/perception/capture/cpp/build_capture_segmentation_topics.sh
bash rt_out/scripts/perception/capture/cpp/build_capture_synchronized_stable_instance_rgb_pcl_topics.sh
```

Start the generated labeled Gazebo world separately, then capture and validate:

```bash
python3 rt_out/scripts/perception/capture/capture_panoptic_topics.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/capture/validate_panoptic_capture.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/capture/capture_synchronized_stable_instance_rgb_pcl.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/capture/validate_synchronized_stable_instance_rgb_pcl.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/reconstruction/build_labeled_colorized_point_cloud.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
python3 rt_out/scripts/perception/reconstruction/validate_labeled_colorized_point_cloud.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json" \
  --expected-cloud-count 24 --min-points-per-cloud 1000
python3 rt_out/scripts/perception/reconstruction/build_panoptic_dataset_index.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json"
```

The orchestrator prints the same ten stages and supports a non-executing dry
run:

```bash
python3 rt_out/scripts/perception/run_perception_pipeline.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json" \
  --expected-cloud-count 24 --dry-run
```

## 8. Smoke/debug sequence

Use `--dry-run`, `--help`, and validators on existing captures. `--force` is
available on selected world/capture/reconstruction/index stages; use it only
in a disposable copy of the run. `preview_panoptic_capture.py` is diagnostic.

## 9. Full-run sequence

The configured pilot expects 20 frames × 8 cameras = 160 rows, but the
recorded dataset has only 24 final PCL rows. A command that runs all ten stages
does not change that evidence: validators may report partial overall coverage.

## 10. Restart/resume sequence

Capture scripts can reuse or force-overwrite stage outputs according to their
flags; validators are read-only. If a live capture is interrupted, preserve the
capture index and validate it before resuming. Rebuild generated worlds only in
the same run when the config hash and source scene are unchanged.

## 11. Expected inputs and outputs

- selected frames: 20;
- fixed cameras: 8;
- expected frame-camera rows: 160;
- recorded final labeled PCL rows: 24;
- final public PLY fields: `x y z red green blue class_label instance_id`;
- index links: source frame, camera, panoptic artifacts, RT rows, labels, and
  final PCL status.

## 12. Validation commands

```bash
python3 rt_out/scripts/perception/run_perception_pipeline.py \
  --config "$PERCEPTION_ROOT/config/perception_dataset_config.json" \
  --expected-cloud-count 24 --dry-run
python3 rt_out/scripts/perception/capture/validate_panoptic_capture.py --help
python3 rt_out/scripts/perception/capture/validate_synchronized_stable_instance_rgb_pcl.py --help
python3 rt_out/scripts/perception/reconstruction/validate_labeled_colorized_point_cloud.py --help
```

Confirm semantic labels, stable-instance mapping, synchronization deltas,
point counts, no zero/unknown public labels, and the expected partial coverage.

## 13. Output directory tree

```text
<perception-run>/
├── config/
├── frames/{selected_frames.json,instance_registry.json}
├── perception_sdf/
├── perception_raw/native/{panoptic,sync_stable_instance_rgb_pcl}/
├── reconstruction/labeled_colorized_pcl_sync/
└── dataset_index/
```

## 14. Known limitations

- The current live run is archived, not a complete unpacked source tree.
- Perception coverage is 24/160, not complete 160/160 coverage.
- RGB perception PCLs and GT scene PCLs have different schemas and must not be
  compared as interchangeable products.
- The C++ helpers are capture dependencies, not independent RT stages.

## 15. Links

- [Complete pipeline sequence](../pipeline_execution_order.md)
- [Configuration](../configuration.md)
- [Troubleshooting](../troubleshooting.md)
- [Script reference](../script_reference.md)
