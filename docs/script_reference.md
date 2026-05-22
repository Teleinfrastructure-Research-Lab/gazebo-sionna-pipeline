# Script Reference

Compact reference for the current `rt_out/scripts/` tree. Use
[Pipeline Overview](pipeline_overview.md) for branch context and
[Developer Guide](developer_guide.md) for internal contracts.

## Static Scene

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/static_scene/00_extract_scene_manifests.py` | extract static and dynamic manifests from `myworld_rt.sdf` |
| `rt_out/scripts/static_scene/01_validate_scene_manifests.py` | validate extracted manifests and asset paths |
| `rt_out/scripts/static_scene/02_build_scene_geometry_registry.py` | flatten scene visuals into a geometry registry |
| `rt_out/scripts/static_scene/03_build_static_scene_registry.py` | build the renderable static registry with semantic materials |
| `rt_out/scripts/static_scene/10_convert_dae_to_ply_blender.py` | Blender DAE-to-PLY conversion helper |
| `rt_out/scripts/static_scene/11_convert_mesh_to_ply_blender.py` | Blender generic mesh-to-PLY conversion helper |
| `rt_out/scripts/static_scene/20_merge_static_scene_by_material.py` | merge static geometry by semantic material |
| `rt_out/scripts/static_scene/21_merge_static_scene_blender_worker.py` | Blender worker used by `20` |
| `rt_out/scripts/static_scene/22_build_static_mitsuba_xml.py` | build optional Mitsuba/debug XML |
| `rt_out/scripts/static_scene/23_build_static_sionna_xml.py` | build the static Sionna XML |
| `rt_out/scripts/static_scene/24_run_sionna_rt_sanity.py` | run a static RT sanity solve |

## Dynamic Rigid

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py` | sample Panda/UR5 source poses into rigid frames |
| `rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py` | join rigid link poses to renderable visuals |
| `rt_out/scripts/dynamic_rigid/32_export_dynamic_frame_meshes.py` | export posed rigid meshes for one frame |
| `rt_out/scripts/dynamic_rigid/33_compose_prototype_frame_scene.py` | compose static + rigid + optional actor manifests |
| `rt_out/scripts/dynamic_rigid/34_build_prototype_frame_sionna_xml.py` | build frame-specific Sionna XML |
| `rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py` | end-to-end three-frame single-RX RT sanity harness |
| `rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py` | three-frame, three-RX RT sanity harness |

## Dynamic Actor

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py` | extract Gazebo actor metadata and mesh references |
| `rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py` | build actor frame samples |
| `rt_out/scripts/dynamic_actor/42_export_actor_frame_meshes.py` | export posed actor meshes for one frame |
| `rt_out/scripts/dynamic_actor/actor_blender_export_frame_meshes.py` | Blender worker for actor export |

## Experiments And Feature Building

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/experiments/exp_sample_frames.py` | sample experiment frame sets |
| `rt_out/scripts/experiments/exp_export_dynamic_meshes_batch.py` | batch rigid mesh export for experiment frames |
| `rt_out/scripts/experiments/exp_build_actor_frame_samples.py` | batch actor frame sampling for experiment branches |
| `rt_out/scripts/experiments/exp_compose_frame_manifests_batch.py` | batch composition of static, rigid, and optional actor manifests |
| `rt_out/scripts/experiments/exp_build_sionna_xml_batch.py` | batch Sionna XML generation |
| `rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py` | batch multi-RX RT solves |
| `rt_out/scripts/experiments/exp_build_rt_labels.py` | build wireless transition labels from RT outputs |
| `rt_out/scripts/experiments/exp_build_object_features.py` | build compact object-aware features |
| `rt_out/scripts/experiments/exp_build_raw_occupancy_features.py` | build raw occupancy feature baselines |
| `rt_out/scripts/experiments/exp_compare_rt_labels.py` | compare or inspect generated RT label sets |
| `rt_out/scripts/experiments/exp_run_semantic_ablation.py` | run classical ablations on the generated features |

## Validation And Inspection

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/validation/50_build_actor_validation_samples.py` | build larger actor validation sample sets |
| `rt_out/scripts/validation/51_export_actor_validation_meshes.py` | export validation actor meshes |
| `rt_out/scripts/validation/52_build_actor_blender_validation_scene.py` | build actor-only Blender validation scenes |
| `rt_out/scripts/validation/53_diagnose_actor_validation_alignment.py` | diagnose actor XY alignment |
| `rt_out/scripts/validation/54_build_actor_prototype_mesh_index.py` | build actor mesh indexes for inspection |
| `rt_out/scripts/validation/55_diagnose_actor_floor_alignment.py` | diagnose actor Z/floor alignment |
| `rt_out/scripts/validation/56_build_composed_frame_blender_scene.py` | build Blender scenes for composed-frame inspection |
| `rt_out/scripts/validation/57_build_experiment_timeline_blender_scene.py` | build timeline inspection scenes for experiment branches |

## Ops Helpers

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/ops/setup_gazebo_env.sh` | export Gazebo resource and GPU-related environment variables |
| `rt_out/scripts/ops/run_gazebo_gpu.sh` | launch Gazebo with the intended GPU environment |
| `rt_out/scripts/ops/run_panda.sh` | capture Panda pose logs |
| `rt_out/scripts/ops/run_ur5.sh` | capture UR5 pose logs |
| `rt_out/scripts/ops/run_all.sh` | capture both Panda and UR5 pose logs |

## Perception Pilot

Active perception scripts for `perception_rt_small_v0`:

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/perception/60_select_perception_frames.py` | select the 20 source frames for the perception pilot |
| `rt_out/scripts/perception/61_build_perception_instance_registry.py` | build the stable object and semantic registry |
| `rt_out/scripts/perception/62_build_labeled_gazebo_world.py` | build the panoptic Gazebo world and optional panoptic helper worlds |
| `rt_out/scripts/perception/63_run_gazebo_native_capture.py` | optional helper for launching Gazebo-native capture runs |
| `rt_out/scripts/perception/64_capture_segmentation_topics.py` | capture panoptic Gazebo Transport segmentation topics |
| `rt_out/scripts/perception/65_preview_native_segmentation_capture.py` | build preview images from panoptic capture outputs |
| `rt_out/scripts/perception/66_validate_native_segmentation_capture.py` | validate the panoptic capture outputs |
| `rt_out/scripts/perception/67_extract_camera_rig_from_gazebo_pose.py` | extract tuned camera poses from Gazebo pose logs |
| `rt_out/scripts/perception/cpp/capture_segmentation_topics.cpp` | C++ helper for topic capture |
| `rt_out/scripts/perception/cpp/build_capture_segmentation_topics.sh` | build helper for the C++ capture utility |

For detailed perception commands and current dataset assumptions, use
`rt_out/scripts/perception/README.md`.
