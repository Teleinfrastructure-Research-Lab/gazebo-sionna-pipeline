# Script Reference

Compact reference for the reorganized `rt_out/scripts/` tree. For architecture
and contracts, see [Pipeline Overview](pipeline_overview.md) and
[Developer Guide](developer_guide.md).

## Static Scene

| Path | Purpose | Main inputs | Main outputs | Important flags |
| --- | --- | --- | --- | --- |
| `rt_out/scripts/static_scene/00_extract_scene_manifests.py` | Extract static and rigid-dynamic model manifests from `myworld_rt.sdf`. | `myworld_rt.sdf`, `models/`, `dynamic_prototype_config.json` | `rt_out/manifests/static_manifest.json`, `rt_out/manifests/dynamic_manifest.json` | none |
| `rt_out/scripts/static_scene/01_validate_scene_manifests.py` | Validate manifest schema, mesh paths, geometry types, and expected dynamic models. | static/dynamic manifests | `rt_out/manifests/manifest_validation_report.json` | none |
| `rt_out/scripts/static_scene/02_build_scene_geometry_registry.py` | Flatten visual geometry into a registry. | static/dynamic manifests | `rt_out/manifests/geometry_registry.json` | none |
| `rt_out/scripts/static_scene/03_build_static_scene_registry.py` | Build renderable static registry with semantic materials and transforms. | geometry registry, `material_map.json` | `rt_out/manifests/static_registry.json` | none |
| `rt_out/scripts/static_scene/10_convert_dae_to_ply_blender.py` | Blender DAE-to-PLY utility. | DAE mesh | PLY mesh | Blender `--python ... -- input output` |
| `rt_out/scripts/static_scene/11_convert_mesh_to_ply_blender.py` | Blender generic mesh-to-PLY utility. | mesh file | PLY mesh | Blender `--python ... -- input output` |
| `rt_out/scripts/static_scene/20_merge_static_scene_by_material.py` | Orchestrate static mesh merge by semantic material. | static registry, converted meshes | merged PLYs, `merged_static_manifest.json` | `--blender` |
| `rt_out/scripts/static_scene/21_merge_static_scene_blender_worker.py` | Blender worker used by `20`. | worker JSON payload | merged material PLYs, worker summary | internal worker |
| `rt_out/scripts/static_scene/22_build_static_mitsuba_xml.py` | Emit visual/debug Mitsuba XML for the static scene. | merged static manifest | `static_scene_mitsuba.xml` | path overrides |
| `rt_out/scripts/static_scene/23_build_static_sionna_xml.py` | Emit static Sionna XML with radio materials. | merged static manifest, RT material mapping | `static_scene_sionna.xml` | path overrides |
| `rt_out/scripts/static_scene/24_run_sionna_rt_sanity.py` | Load one XML scene and run a single TX/RX Sionna sanity solve. | Sionna XML, RT environment | console summary | `--xml`, `--tx`, `--rx`, `--frequency-hz`, `--use-fallback-variant` |

## Dynamic Rigid

| Path | Purpose | Main inputs | Main outputs | Important flags |
| --- | --- | --- | --- | --- |
| `rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py` | Sample configured Panda/UR5 source poses into prototype frames. | pose logs, dynamic manifest, dynamic config | `rt_out/dynamic_frames/prototype_frames.json` | path overrides |
| `rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py` | Join sampled rigid link poses to renderable visuals. | prototype frames, dynamic manifest | `rt_out/dynamic_frames/dynamic_visual_frames.json` | path overrides |
| `rt_out/scripts/dynamic_rigid/32_export_dynamic_frame_meshes.py` | Export posed rigid robot meshes for one frame. | dynamic visual frames | `rt_out/dynamic_scene/frame_XXX/dynamic_frame_XXX_manifest.json`, PLYs | `--frame-id`, `--blender` |
| `rt_out/scripts/dynamic_rigid/33_compose_prototype_frame_scene.py` | Compose static, rigid dynamic, and optional actor manifests into one frame manifest. | merged static manifest, dynamic frame manifest, optional actor frame manifest | `rt_out/composed_scene/frame_XXX/composed_frame_XXX_manifest.json` | `--frame-id`, `--actor-frame-manifest` |
| `rt_out/scripts/dynamic_rigid/34_build_prototype_frame_sionna_xml.py` | Emit frame-specific Sionna XML from a composed manifest. | composed frame manifest, RT material mapping | `rt_out/composed_scene/frame_XXX/frame_XXX_sionna.xml` | `--frame-id`, path overrides |
| `rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py` | End-to-end three-frame single-RX sanity harness. | static baseline, dynamic frames, RT env, optional actor inputs | three composed frame branches, summary CSV | `--include-actors`, `--summary-csv`, `--sionna-python`, actor flags |
| `rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py` | Three-frame, three-RX sanity harness. | existing rigid frame exports, radio sites, RT env, optional actor inputs | 9-row summary CSV | `--include-actors`, `--output-csv`, `--sionna-python`, actor flags |

## Dynamic Actor

| Path | Purpose | Main inputs | Main outputs | Important flags |
| --- | --- | --- | --- | --- |
| `rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py` | Extract Gazebo actor metadata and resolve actor mesh URIs. | `myworld_rt.sdf`, `models/` | `rt_out/manifests/actor_manifest.json` | `--world`, `--models-root`, `--output` |
| `rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py` | Build actor samples for the three prototype frames. | actor manifest, actor config, dynamic config, RT material mapping | `rt_out/dynamic_frames/actor_frame_samples.json` | `--actor-manifest`, `--actor-config`, `--output` |
| `rt_out/scripts/dynamic_actor/42_export_actor_frame_meshes.py` | Export baked posed actor meshes for one frame. | actor samples, actor manifest | actor PLYs, actor frame manifest, metadata | `--frame-id`, `--alignment-policy`, `--z-alignment-policy`, `--floor-z`, `--blender` |
| `rt_out/scripts/dynamic_actor/actor_blender_export_frame_meshes.py` | Blender worker launched by `42` and validation export. | worker JSON payload | actor PLYs, summary JSON | internal worker |

## Validation

| Path | Purpose | Main inputs | Main outputs | Important flags |
| --- | --- | --- | --- | --- |
| `rt_out/scripts/validation/50_build_actor_validation_samples.py` | Build larger actor validation sample sets. | actor manifest/config | validation sample JSON | path overrides |
| `rt_out/scripts/validation/51_export_actor_validation_meshes.py` | Export validation actor mesh batches. | validation samples, actor manifest | validation PLYs, summaries | `--blender`, `--alignment-policy`, `--z-alignment-policy`, `--floor-z` |
| `rt_out/scripts/validation/52_build_actor_blender_validation_scene.py` | Build actor-only Blender validation scenes with room geometry. | actor validation meshes, static geometry | `.blend`, inventory JSON | `--blender` |
| `rt_out/scripts/validation/53_diagnose_actor_validation_alignment.py` | Diagnose horizontal actor/path drift. | actor validation metadata | console diagnostics | path overrides |
| `rt_out/scripts/validation/54_build_actor_prototype_mesh_index.py` | Adapt three-frame actor manifests for Blender inspection. | actor frame manifests | actor prototype mesh index | path overrides |
| `rt_out/scripts/validation/55_diagnose_actor_floor_alignment.py` | Diagnose actor/floor vertical alignment. | actor metadata, static floor context | console diagnostics | path overrides |
| `rt_out/scripts/validation/56_build_composed_frame_blender_scene.py` | Import a composed frame into Blender for inspection. | composed frame manifest | `.blend`, inventory JSON | `--composed-manifest`, `--output-root`, `--blender` |
| `rt_out/scripts/validation/57_build_experiment_timeline_blender_scene.py` | Build a multi-frame Blender timeline scene for an experiment branch. | experiment config, composed manifest index | `.blend`, inventory JSON, timeline payload | `--config`, `--max-frames`, `--frame-step`, `--frame-ids`, `--blender` |

## Experiments

These wrappers now support both the rigid `semantic_ablation_rigid_200f` branch
and the actor-aware `semantic_ablation_actor_200f` branch when the relevant
flags/config are used.

| Path | Purpose | Main inputs | Main outputs | Important flags |
| --- | --- | --- | --- | --- |
| `rt_out/scripts/experiments/exp_sample_frames.py` | Sample source-frame indices for an experiment. | experiment config, pose logs | sampled-frame JSON | `--config` |
| `rt_out/scripts/experiments/exp_build_actor_frame_samples.py` | Build experiment-local actor frame samples for arbitrary sampled-frame lists. | experiment config, sampled-frame JSON, actor manifest | `frames/actor_frame_samples.json` | `--config`, `--frames-json`, `--max-frames`, `--frame-ids`, `--output` |
| `rt_out/scripts/experiments/exp_export_dynamic_meshes_batch.py` | Batch-run rigid mesh export and, optionally, actor mesh export. | sampled frames, dynamic visual frames, optional actor samples | rigid manifests/PLYs, optional `actor_mesh_index.csv` | `--config`, `--include-actors`, `--max-frames`, `--blender` |
| `rt_out/scripts/experiments/exp_compose_frame_manifests_batch.py` | Batch-compose static + rigid dynamic manifests, optionally with actor frame manifests. | sampled frames, static/dynamic manifests, optional actor mesh index | composed frame manifests | `--config`, `--include-actors`, `--max-frames` |
| `rt_out/scripts/experiments/exp_build_sionna_xml_batch.py` | Batch-build Sionna XMLs from composed manifests. | composed manifests | frame XMLs | `--config`, `--max-frames` |
| `rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py` | Batch-run multi-RX RT solves. | frame XMLs, radio config | RT CSVs | `--config`, `--max-frames`, `--max-rows`, `--continue-on-error`, `--sionna-python` |
| `rt_out/scripts/experiments/exp_build_rt_labels.py` | Build supervised labels from RT CSVs. | RT CSV | label CSV | `--config` |
| `rt_out/scripts/experiments/exp_build_object_features.py` | Build object-aware feature tables, including actor entries when composed manifests contain `source == "actor"`. | composed manifests, labels | feature CSV | `--config`, feature mode options |
| `rt_out/scripts/experiments/exp_build_raw_occupancy_features.py` | Build raw occupancy baseline features from composed mesh geometry. | composed manifests, labels | raw occupancy CSV | `--config` |
| `rt_out/scripts/experiments/exp_run_semantic_ablation.py` | Run classical model ablation. | feature CSVs, labels | result tables | `--config`, `--target`, `--feature-mode`, `--rx-filter`, `--models` |

## Ops

| Path | Purpose | Main inputs | Main outputs | Important flags |
| --- | --- | --- | --- | --- |
| `rt_out/scripts/ops/run_all.sh` | Record Panda and UR5 pose logs while both motion scripts run. | running Gazebo world | pose logs under `rt_out/poses/` | shell env/Gazebo |
| `rt_out/scripts/ops/run_panda.sh` | Drive Panda motion sequence. | running Gazebo world | robot motion | none |
| `rt_out/scripts/ops/run_ur5.sh` | Drive UR5/RG2 motion sequence. | running Gazebo world | robot motion | none |

## Legacy

| Path | Purpose | Notes |
| --- | --- | --- |
| `rt_out/scripts/legacy/sionna_test.py` | Ad hoc Sionna sandbox. | Not part of active validation. |
| `rt_out/scripts/legacy/actor_spike_export_actor_walking.py` | Historical actor export spike. | Superseded by `dynamic_actor/40`-`42`. |
| `rt_out/scripts/legacy/actor_spike_blender_sample_actor.py` | Historical Blender actor sampling helper. | Superseded by current actor worker. |

## Helper Modules

| Path | Purpose |
| --- | --- |
| `rt_out/scripts/dynamic_prototype_config.py` | Loads and validates rigid dynamic prototype config. |
| `rt_out/scripts/rt_material_config.py` | Loads RT material/runtime config and emits radio material XML. |
