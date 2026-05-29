# Cleanup Inventory Dry-Run

This report is inventory only. No files were deleted, moved, archived, staged,
or committed by this helper.

## 1. Git Status

`git status --short summary: modified=13, deleted=467, untracked=37`

## 2. Current Main Pipeline Proposal

A. Frame/config/world preparation:

- `rt_out/scripts/perception/60_select_perception_frames.py`
- `rt_out/scripts/perception/61_build_perception_instance_registry.py`
- `rt_out/scripts/perception/62_build_labeled_gazebo_world.py`
- `rt_out/scripts/perception/63_capture_panoptic_topics.py`
- `rt_out/scripts/perception/64_validate_panoptic_capture.py`

B. Synchronized stable-instance label + RGB/PCL capture:

- `rt_out/scripts/perception/70_capture_synchronized_stable_instance_rgb_pcl_topics.py`
- `rt_out/scripts/perception/71_validate_synchronized_stable_instance_rgb_pcl_capture.py`

C. Final labeled RGB point clouds:

- `rt_out/scripts/perception/72_build_labeled_colorized_pointclouds.py`
- `rt_out/scripts/perception/73_validate_labeled_colorized_pointclouds.py`

D. Dataset index:

- `rt_out/scripts/perception/65_build_panoptic_dataset_index.py`

E. Existing validated wireless source:

- `rt_out/experiments/semantic_ablation.zip` fallback source for RT and label CSVs

## 3. Script Inventory

Full source/helper inventory is written to:

- `rt_out/experiments/perception_rt_small_v0/cleanup_inventory/cleanup_inventory_scripts.csv`

| Path | Classification | Type | Size Bytes | Reason |
| --- | --- | --- | --- | --- |
| rt_out/scripts/perception/60_select_perception_frames.py | main_candidate | python | 10075 | Selects the 20 source frames that anchor the perception pilot. |
| rt_out/scripts/perception/61_build_perception_instance_registry.py | main_candidate | python | 22986 | Builds the stable object/semantic registry used by the active panoptic pilot. |
| rt_out/scripts/perception/62_build_labeled_gazebo_world.py | main_candidate | python | 56019 | Generates the active panoptic Gazebo world and fixed camera rig used by capture workflows. |
| rt_out/scripts/perception/63_capture_panoptic_topics.py | main_candidate | python | 17013 | Captures the active semantic panoptic outputs that remain part of the indexed perception pilot. |
| rt_out/scripts/perception/64_validate_panoptic_capture.py | main_candidate | python | 28101 | Validates the active panoptic capture outputs that the indexed pilot still depends on. |
| rt_out/scripts/perception/65_build_panoptic_dataset_index.py | main_candidate | python | 51978 | Builds the central linkage index that ties selected frames, panoptic samples, RT rows, wireless labels, and final labeled point clouds together. |
| rt_out/scripts/perception/70_capture_synchronized_stable_instance_rgb_pcl_topics.py | main_candidate | python | 16409 | Captures synchronized stable-instance labels, RGB, and direct PCL groups for the final labeled export path. |
| rt_out/scripts/perception/71_validate_synchronized_stable_instance_rgb_pcl_capture.py | main_candidate | python | 25675 | Validates the synchronized stable-instance label plus RGB/PCL capture path. |
| rt_out/scripts/perception/72_build_labeled_colorized_pointclouds.py | main_candidate | python | 26343 | Builds the final strict labeled RGB point clouds with fields x y z red green blue class_label instance_id. |
| rt_out/scripts/perception/73_validate_labeled_colorized_pointclouds.py | main_candidate | python | 21073 | Validates the final fully labeled RGB point clouds used as the current main dataset product. |
| rt_out/scripts/perception/90_cleanup_inventory_dry_run.py | diagnostic_keep | python | 38341 | Inventory-only dry-run helper for cleanup planning; not a generation step in the data pipeline. |
| rt_out/scripts/perception/91_run_gazebo_capture_helper.py | diagnostic_keep | python | 16872 | Optional launcher helper for running the panoptic or stable-instance Gazebo worlds; useful for operations but not part of the numbered generation path. |
| rt_out/scripts/perception/92_preview_panoptic_capture.py | diagnostic_keep | python | 10595 | Qualitative preview builder for panoptic captures; useful reference output, not core synchronized PCL path. |
| rt_out/scripts/perception/93_extract_camera_rig_from_gazebo_pose.py | diagnostic_keep | python | 6899 | Optional camera-tuning extractor kept for rig iteration and debugging. |
| rt_out/scripts/perception/README.md | docs_or_other | markdown | 4498 | Perception workflow documentation rather than a pipeline executable. |
| rt_out/scripts/perception/cpp/build_capture_segmentation_topics.sh | cpp_helper | shell | 1107 | Gazebo capture helper source, build script, or built helper binary. |
| rt_out/scripts/perception/cpp/build_capture_synchronized_stable_instance_rgb_pcl_topics.sh | cpp_helper | shell | 1155 | Gazebo capture helper source, build script, or built helper binary. |
| rt_out/scripts/perception/cpp/capture_segmentation_topics.cpp | cpp_helper | cpp_source | 16450 | Gazebo capture helper source, build script, or built helper binary. |
| rt_out/scripts/perception/cpp/capture_synchronized_stable_instance_rgb_pcl_topics | cpp_helper | cpp_binary | 191136 | Gazebo capture helper source, build script, or built helper binary. |
| rt_out/scripts/perception/cpp/capture_synchronized_stable_instance_rgb_pcl_topics.cpp | cpp_helper | cpp_source | 46006 | Gazebo capture helper source, build script, or built helper binary. |

## 4. Experiment Output Inventory

Full path inventory is written to:

- `rt_out/experiments/perception_rt_small_v0/cleanup_inventory/cleanup_inventory_paths.csv`

Directory snapshots (up to the configured child limit per directory):

- `rt_out/experiments/perception_rt_small_v0/configs`: 5 direct children
  - `rt_out/experiments/perception_rt_small_v0/configs/camera_rig.json`
  - `rt_out/experiments/perception_rt_small_v0/configs/camera_rig_8cam_seeded.json`
  - `rt_out/experiments/perception_rt_small_v0/configs/camera_rig_before_8cam_expansion.json`
  - `rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json`
  - `rt_out/experiments/perception_rt_small_v0/configs/semantic_label_map.json`
- `rt_out/experiments/perception_rt_small_v0/frames`: 4 direct children
  - `rt_out/experiments/perception_rt_small_v0/frames/instance_registry.json`
  - `rt_out/experiments/perception_rt_small_v0/frames/instance_registry_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/frames/selected_frames.json`
  - `rt_out/experiments/perception_rt_small_v0/frames/selected_frames_summary.json`
- `rt_out/experiments/perception_rt_small_v0/perception_sdf`: 8 direct children
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/camera_tuning_world_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_camera_tuning_world.sdf`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_panoptic_world.sdf`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_stable_instance_panoptic_world.sdf`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_stable_instance_panoptic_world_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_world_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/instance_label_map.json`
  - `rt_out/experiments/perception_rt_small_v0/perception_sdf/stable_instance_label_map.json`
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic`: 8 direct children
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_sw`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_wall_east`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_wall_north`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_wall_south`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_wall_west`
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl`: 8 direct children
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_ne`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_nw`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_se`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_sw`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_east`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_north`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_south`
  - `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_west`
- `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync`: 5 direct children
  - `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/frame_000`
  - `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/frame_001`
  - `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/frame_002`
  - `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/labeled_colorized_pcl_index.csv`
  - `rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync/labeled_colorized_pcl_summary.json`
- `rt_out/experiments/perception_rt_small_v0/validation`: 9 direct children
  - `rt_out/experiments/perception_rt_small_v0/validation/instance_registry_review.csv`
  - `rt_out/experiments/perception_rt_small_v0/validation/labeled_colorized_pcl_invalid_rows.csv`
  - `rt_out/experiments/perception_rt_small_v0/validation/labeled_colorized_pcl_validation_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/validation/native_segmentation_invalid_pixels.csv`
  - `rt_out/experiments/perception_rt_small_v0/validation/native_segmentation_label_histograms.csv`
  - `rt_out/experiments/perception_rt_small_v0/validation/native_segmentation_validation_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks`
  - `rt_out/experiments/perception_rt_small_v0/validation/sync_stable_instance_rgb_pcl_capture_validation_summary.json`
  - `rt_out/experiments/perception_rt_small_v0/validation/sync_stable_instance_rgb_pcl_invalid_rows.csv`
- `rt_out/experiments/perception_rt_small_v0/dataset_index`: 3 direct children
  - `rt_out/experiments/perception_rt_small_v0/dataset_index/panoptic_dataset_index.csv`
  - `rt_out/experiments/perception_rt_small_v0/dataset_index/panoptic_dataset_index.json`
  - `rt_out/experiments/perception_rt_small_v0/dataset_index/panoptic_dataset_index_summary.json`
- `rt_out/experiments/perception_rt_small_v0/cleanup_inventory`: 0 direct children

## 5. Cleanup Candidates (Dry-Run Only)

- No conservative cleanup candidates were identified.

## 6. Review Required

- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/rgbd_capture_index.csv`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/rgbd_capture_summary.json`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/rgbd_pointcloud_capture_index.csv`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/rgbd_pointcloud_capture_summary.json`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_rgb_pcl_capture_index.csv`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_rgb_pcl_capture_summary.json`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_ne`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_ne/depth_validity_mask_000000.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_ne/depth_validity_mask_000001.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_ne/depth_validity_mask_000002.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_nw`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_nw/depth_validity_mask_000000.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_nw/depth_validity_mask_000001.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_corner_nw/depth_validity_mask_000002.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_wall_north`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_wall_north/depth_validity_mask_000000.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_wall_north/depth_validity_mask_000001.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.
- `rt_out/experiments/perception_rt_small_v0/validation/rgbd_validity_masks/cam_wall_north/depth_validity_mask_000002.png`: `unknown_review_required` / `review_required`. Path was not matched confidently to the current conservative inventory rules.

## 7. Size Summary

Total experiment size: `209976276` bytes

Largest directories:

| Path | Size Bytes | Recursive File Count |
| --- | --- | --- |
| . | 209976276 | 433 |
| rt_out/experiments/perception_rt_small_v0/perception_raw | 184634318 | 370 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native | 184634318 | 370 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl | 109903018 | 168 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic | 66387564 | 120 |
| rt_out/experiments/perception_rt_small_v0/reconstruction | 21560663 | 26 |
| rt_out/experiments/perception_rt_small_v0/reconstruction/labeled_colorized_pcl_sync | 21560663 | 26 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_sw | 13759425 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_nw | 13757373 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_ne | 13753150 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_corner_se | 13751379 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_north | 13744545 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_east | 13717629 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_west | 13714248 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/sync_stable_instance_rgb_pcl/cam_wall_south | 13705269 | 21 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_wall_north | 8298459 | 15 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_wall_south | 8298459 | 15 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne | 8298441 | 15 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw | 8298441 | 15 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se | 8298441 | 15 |

Largest files:

| Path | Size Bytes |
| --- | --- |
| rt_out/experiments/perception_rt_small_v0/dataset_index/panoptic_dataset_index.json | 1493863 |
| rt_out/experiments/perception_rt_small_v0/dataset_index/panoptic_dataset_index.csv | 976074 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne/colored_maps/000000.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne/colored_maps/000001.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne/colored_maps/000002.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne/labels_maps_rgb/000000.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne/labels_maps_rgb/000001.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_ne/labels_maps_rgb/000002.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw/colored_maps/000000.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw/colored_maps/000001.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw/colored_maps/000002.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw/labels_maps_rgb/000000.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw/labels_maps_rgb/000001.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_nw/labels_maps_rgb/000002.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se/colored_maps/000000.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se/colored_maps/000001.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se/colored_maps/000002.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se/labels_maps_rgb/000000.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se/labels_maps_rgb/000001.ppm | 921615 |
| rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/cam_corner_se/labels_maps_rgb/000002.ppm | 921615 |

## 8. Risk Notes

- Do not delete anything referenced by panoptic_dataset_index.csv unless the dataset index is rebuilt or patched afterward.
- Do not delete perception_raw/native/sync_stable_instance_rgb_pcl or reconstruction/labeled_colorized_pcl_sync because these are the current main corrected outputs.
- Treat optional helpers like 91_run_gazebo_capture_helper.py, 92_preview_panoptic_capture.py, and 93_extract_camera_rig_from_gazebo_pose.py as non-core utilities rather than active generation steps.
- Treat native_segmentation_label_histograms.csv, native_segmentation_invalid_pixels.csv, and preview assets as supplementary diagnostics rather than required active outputs.
- Do not delete source configs, selected frames, semantic label map, instance registry, generated world SDF, or the RT source archive.
- Do not delete outputs just because they are partial. Some partial outputs are deliberately linked in the index as 24/160 coverage.
- This helper is dry-run only and does not remove or archive any files.
