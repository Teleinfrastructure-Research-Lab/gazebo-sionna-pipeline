# Project Roadmap

This document explains how the repository is organized today and how the Gazebo-side scene definition feeds the RT-side preprocessing and evaluation pipeline.

For the user-editable control layer and the still world-specific assumptions, see [`docs/configs_and_world_specific_parts.md`](./configs_and_world_specific_parts.md).

## 1. Current Validated Scope

The active, validated pipeline in this repository currently covers:

- rigid non-actor Gazebo scene content
- static scene export to Mitsuba and Sionna RT XML
- dynamic prototype motion for **`Panda`** and **`ur5_rg2`** only
- exactly **3 prototype frames**
- explicit **28 GHz** RT baseline
- single-RX and 3-frame x 3-RX sanity evaluation
- shelf-orientation correction integrated into the normal static merge path

The repository also contains an experiment-local extension,
`semantic_ablation_rigid_200f`, which reuses that validated core path and then
adds sampled-frame batching, 6 RX positions, RT-derived labels, object-aware
feature tables, and a raw occupancy baseline.

Out of scope for the active pipeline:

- Gazebo actors
- skinned or animated humans
- deformable objects
- arbitrary dynamic models beyond the configured Panda/UR5 prototype

## 2. Root-Level Project Structure

The repo root is the **Gazebo world creation side**.

| Path | Role |
| --- | --- |
| [`myworld.sdf`](../myworld.sdf) | Main Gazebo world used for general simulation |
| [`myworld_rt.sdf`](../myworld_rt.sdf) | RT-oriented world input used by manifest extraction |
| [`models/`](../models) | Gazebo model library: shell, furniture, robots, humans, parts, UAVs |
| [`plugins/`](../plugins) | Gazebo plugin source / build output |
| [`run_myworld.sh`](../run_myworld.sh) | Launch helper for `myworld.sdf` |
| [`run_myworld_rt.sh`](../run_myworld_rt.sh) | Launch helper for `myworld_rt.sdf` |
| [`scripts/generate_wall_uv_meshes.py`](../scripts/generate_wall_uv_meshes.py) | Asset-generation helper for wall UV meshes |
| [`backup world/`](../backup%20world) | Historical SDF snapshots, not part of the active RT chain |
| [`trash/`](../trash) | Non-deleted retired clutter moved out of the active tree |

### Gazebo-Side Conventions

- World structure is authored in SDF.
- Asset geometry lives under [`models/`](../models).
- The repo includes both authored models and converted/generated meshes used by the RT side.
- The world files currently include **actors**, but the active RT extraction path ignores them because the extractor only walks `<model>` and `<include>` entries.

## 3. `rt_out/` Structure

[`rt_out/`](../rt_out) is the **RT preprocessing / export / evaluation side**.

| Path | Role |
| --- | --- |
| [`rt_out/manifests/`](../rt_out/manifests) | Extracted static/dynamic manifests and derived registries |
| [`rt_out/materials/`](../rt_out/materials) | Semantic material assignment rules |
| [`rt_out/config/`](../rt_out/config) | Prototype frame config, radio site config, RT material config |
| [`rt_out/poses/`](../rt_out/poses) | Gazebo pose logs used by the dynamic prototype |
| [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes) | Static mesh conversion cache / prepared scene meshes |
| [`rt_out/static_scene/export/`](../rt_out/static_scene/export) | Standard merged static scene outputs |
| [`rt_out/dynamic_frames/`](../rt_out/dynamic_frames) | Prototype frame manifests and frame-to-visual joins |
| [`rt_out/dynamic_scene/`](../rt_out/dynamic_scene) | Per-frame dynamic mesh exports plus dynamic conversion cache |
| [`rt_out/composed_scene/`](../rt_out/composed_scene) | Standard composed static+dynamic frame outputs |
| [`rt_out/scripts/`](../rt_out/scripts) | Pipeline scripts and helper modules |
| [`rt_out/wireless/`](../rt_out/wireless) | Present but currently unused/empty in the active flow |
| [`rt_out/temp/`](../rt_out/temp) | Scratch area; not part of the main validated chain |

## 4. Boundary Between Gazebo And RT

The clean boundary is:

- **Gazebo side:** world SDFs, model SDFs, raw meshes, plugins, robot motion scripts, pose logging
- **RT side:** everything from [`00_extract_scene_manifests.py`](../rt_out/scripts/00_extract_scene_manifests.py) onward

In practical terms:

1. Gazebo defines the world and model graph.
2. The extractor reads [`myworld_rt.sdf`](../myworld_rt.sdf) and model SDFs under [`models/`](../models).
3. The RT pipeline turns that scene into manifests, merged geometry, composed frame scenes, and Sionna sanity outputs.

## 5. High-Level Active Flow

### A. Scene Authoring / Simulation Side

1. Author or update the scene in [`myworld.sdf`](../myworld.sdf) and [`myworld_rt.sdf`](../myworld_rt.sdf)
2. Keep model assets under [`models/`](../models)
3. Launch Gazebo with [`run_myworld.sh`](../run_myworld.sh) or [`run_myworld_rt.sh`](../run_myworld_rt.sh)

### B. Static RT Preprocessing

1. [`00_extract_scene_manifests.py`](../rt_out/scripts/00_extract_scene_manifests.py)  
   Reads [`myworld_rt.sdf`](../myworld_rt.sdf) and model SDFs, then writes:
   - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
   - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)

2. [`01_validate_scene_manifests.py`](../rt_out/scripts/01_validate_scene_manifests.py)  
   Validates both manifests and writes:
   - [`rt_out/manifests/manifest_validation_report.json`](../rt_out/manifests/manifest_validation_report.json)

3. [`02_build_scene_geometry_registry.py`](../rt_out/scripts/02_build_scene_geometry_registry.py)  
   Flattens visual geometry into:
   - [`rt_out/manifests/geometry_registry.json`](../rt_out/manifests/geometry_registry.json)

4. [`03_build_static_scene_registry.py`](../rt_out/scripts/03_build_static_scene_registry.py)  
   Filters the geometry registry down to static renderable entries, assigns semantic materials, computes `to_world`, and writes:
   - [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json)

5. [`20_merge_static_scene_by_material.py`](../rt_out/scripts/20_merge_static_scene_by_material.py)  
   Uses Blender through [`21_merge_static_scene_blender_worker.py`](../rt_out/scripts/21_merge_static_scene_blender_worker.py) to merge static geometry by material and writes:
   - merged PLYs under [`rt_out/static_scene/export/merged_by_material/`](../rt_out/static_scene/export/merged_by_material)
   - merged manifest under [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)

6. [`22_build_static_mitsuba_xml.py`](../rt_out/scripts/22_build_static_mitsuba_xml.py)  
   Writes a Mitsuba visual/debug scene:
   - [`rt_out/static_scene/export/static_scene_mitsuba.xml`](../rt_out/static_scene/export/static_scene_mitsuba.xml)

7. [`23_build_static_sionna_xml.py`](../rt_out/scripts/23_build_static_sionna_xml.py)  
   Writes a Sionna RT scene:
   - [`rt_out/static_scene/export/static_scene_sionna.xml`](../rt_out/static_scene/export/static_scene_sionna.xml)

8. [`24_run_sionna_rt_sanity.py`](../rt_out/scripts/24_run_sionna_rt_sanity.py)  
   Loads the Sionna XML, sets the carrier frequency explicitly from config, adds a TX/RX pair, and checks that path computation works.

### C. Dynamic Prototype Preprocessing

1. Generate Gazebo pose logs under:
   - [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
   - [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)

2. [`30_build_prototype_dynamic_frames.py`](../rt_out/scripts/30_build_prototype_dynamic_frames.py)  
   Parses the pose logs into a strict 3-frame canonical motion manifest:
   - [`rt_out/dynamic_frames/prototype_frames.json`](../rt_out/dynamic_frames/prototype_frames.json)

3. [`31_build_prototype_dynamic_visual_frames.py`](../rt_out/scripts/31_build_prototype_dynamic_visual_frames.py)  
   Joins those frames with visual-bearing dynamic geometry from the dynamic manifest:
   - [`rt_out/dynamic_frames/dynamic_visual_frames.json`](../rt_out/dynamic_frames/dynamic_visual_frames.json)

4. [`32_export_dynamic_frame_meshes.py`](../rt_out/scripts/32_export_dynamic_frame_meshes.py)  
   Exports transformed dynamic-only mesh geometry for one frame at a time:
   - [`rt_out/dynamic_scene/frame_000/`](../rt_out/dynamic_scene/frame_000)
   - [`rt_out/dynamic_scene/frame_001/`](../rt_out/dynamic_scene/frame_001)
   - [`rt_out/dynamic_scene/frame_002/`](../rt_out/dynamic_scene/frame_002)

### D. Static + Dynamic Composition

1. [`33_compose_prototype_frame_scene.py`](../rt_out/scripts/33_compose_prototype_frame_scene.py)  
   Combines the frozen static manifest and one dynamic frame manifest into a flat composed manifest per frame.

2. [`34_build_prototype_frame_sionna_xml.py`](../rt_out/scripts/34_build_prototype_frame_sionna_xml.py)  
   Emits frame-specific Sionna XML from the composed manifest, forcing:
   - `Panda -> metal`
   - `ur5_rg2 -> metal`

### E. Evaluation

1. [`35_run_prototype_three_frame_rt_sanity.py`](../rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py)  
   Runs the 3-frame single-RX sanity flow and writes:
   - [`rt_out/composed_scene/three_frame_rt_summary.csv`](../rt_out/composed_scene/three_frame_rt_summary.csv)

2. [`36_run_three_frame_three_rx_rt_sanity.py`](../rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py)  
   Runs the 3-frame x 3-RX evaluation and writes:
   - [`rt_out/composed_scene/three_frame_three_rx_rt_summary.csv`](../rt_out/composed_scene/three_frame_three_rx_rt_summary.csv)

## 6. Current Active Branches And Outputs

The active scripts currently default to the unsuffixed branch as the main output path.

### Main branch

- static export: [`rt_out/static_scene/export/`](../rt_out/static_scene/export)
- composed frames: [`rt_out/composed_scene/`](../rt_out/composed_scene)
- single-RX summary: [`rt_out/composed_scene/three_frame_rt_summary.csv`](../rt_out/composed_scene/three_frame_rt_summary.csv)
- multi-RX summary: [`rt_out/composed_scene/three_frame_three_rx_rt_summary.csv`](../rt_out/composed_scene/three_frame_three_rx_rt_summary.csv)

Important detail: the shelf-orientation correction is implemented in the merge worker code itself, so corrected geometry is part of the normal merge path now. Earlier notes or historical comparisons may still mention `_fixed` artifacts from that transition stage.

### Experiment-local branch

- root: [`rt_out/experiments/semantic_ablation_rigid_200f/`](../rt_out/experiments/semantic_ablation_rigid_200f)
- guide: [`docs/semantic_ablation_200f_pipeline.md`](./semantic_ablation_200f_pipeline.md)
- primary outputs:
  - sampled-frame lists
  - experiment-local dynamic mesh indexes
  - experiment-local Sionna XML indexes
  - multi-RX RT CSVs
  - label tables
  - object-aware and raw occupancy feature tables

These experiment outputs are generated working artifacts and should normally
remain ignored rather than being committed.

## 7. Important Current Constraints

- The dynamic prototype is config-driven, but still limited to the two configured robot models.
- Static actor geometry is not extracted because actors are not handled by the manifest extractor.
- The static merge step assumes that required converted static meshes already exist under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes) for raw assets that are not directly usable as `PLY` or `OBJ`.
- The dynamic mesh export step handles conversion on demand through Blender and caches the converted source meshes under [`rt_out/dynamic_scene/converted_mesh_cache/`](../rt_out/dynamic_scene/converted_mesh_cache).

## 8. Minimal End-to-End Working Flow

Assuming the Panda/UR5 pose logs already exist:

```bash
python3 rt_out/scripts/00_extract_scene_manifests.py
python3 rt_out/scripts/01_validate_scene_manifests.py
python3 rt_out/scripts/02_build_scene_geometry_registry.py
python3 rt_out/scripts/03_build_static_scene_registry.py
python3 rt_out/scripts/20_merge_static_scene_by_material.py
python3 rt_out/scripts/23_build_static_sionna_xml.py
python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
python3 rt_out/scripts/30_build_prototype_dynamic_frames.py
python3 rt_out/scripts/31_build_prototype_dynamic_visual_frames.py
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

If you need fresh pose logs first, run [`run_myworld_rt.sh`](../run_myworld_rt.sh) and then [`rt_out/scripts/run_all.sh`](../rt_out/scripts/run_all.sh).

The RT sanity steps expect the current Sionna/Mitsuba runtime, typically through `COLLABPAPER_PYTHON` or the standard `collabpaper` conda environment.

## 9. Recommended Reading Order

If you are new to the repo:

1. Read [`README.md`](../README.md)
2. Read this roadmap
3. Read [`docs/script_reference.md`](./script_reference.md)
4. Open [`myworld_rt.sdf`](../myworld_rt.sdf), [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json), and [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
5. Follow the active script chain from `00` through `36`
