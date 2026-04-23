# Gazebo World -> Mitsuba / Sionna RT Pipeline

This repository has two connected halves:

- the **Gazebo scene side** at the repo root, where the world, models, meshes, and simulation helpers live
- the **RT export / evaluation side** under [`rt_out/`](./rt_out), where the scene is turned into manifests, merged geometry, Mitsuba/Sionna XML, and prototype RT sanity outputs

The current validated scope is intentionally narrow:

- rigid non-actor Gazebo scenes only
- static scene export
- dynamic prototype for **`Panda`** and **`ur5_rg2`** only
- exactly **3 prototype frames** from recorded pose logs
- explicit **28 GHz** RT baseline
- current multi-RX sanity validation with the shelf correction integrated into the main merge path

Actors exist in the world files, but they are **not** part of the active RT pipeline. The extraction scripts only process `<model>` and `<include>` content.

## Where To Start

- Project roadmap: [`docs/project_roadmap.md`](./docs/project_roadmap.md)
- Requirements and inputs: [`docs/requirements_and_inputs.md`](./docs/requirements_and_inputs.md)
- Configs and world-specific parts: [`docs/configs_and_world_specific_parts.md`](./docs/configs_and_world_specific_parts.md)
- Step-by-step runbook: [`docs/step_by_step_guide.md`](./docs/step_by_step_guide.md)
- Script reference: [`docs/script_reference.md`](./docs/script_reference.md)
- Misc/tooling/history notes: [`docs/misc_and_legacy.md`](./docs/misc_and_legacy.md)

## Repo Layout At A Glance

- [`myworld.sdf`](./myworld.sdf): main Gazebo world
- [`myworld_rt.sdf`](./myworld_rt.sdf): RT-oriented world input used by manifest extraction
- [`models/`](./models): Gazebo model library and scene assets
- [`plugins/`](./plugins): Gazebo plugin source / build artifacts
- [`rt_out/`](./rt_out): manifests, configs, static export, dynamic frame processing, XML generation, and RT outputs

## Current Active RT Flow

Static side:

1. [`00_extract_scene_manifests.py`](./rt_out/scripts/00_extract_scene_manifests.py)
2. [`01_validate_scene_manifests.py`](./rt_out/scripts/01_validate_scene_manifests.py)
3. [`02_build_scene_geometry_registry.py`](./rt_out/scripts/02_build_scene_geometry_registry.py)
4. [`03_build_static_scene_registry.py`](./rt_out/scripts/03_build_static_scene_registry.py)
5. [`20_merge_static_scene_by_material.py`](./rt_out/scripts/20_merge_static_scene_by_material.py)
6. [`22_build_static_mitsuba_xml.py`](./rt_out/scripts/22_build_static_mitsuba_xml.py)
7. [`23_build_static_sionna_xml.py`](./rt_out/scripts/23_build_static_sionna_xml.py)
8. [`24_run_sionna_rt_sanity.py`](./rt_out/scripts/24_run_sionna_rt_sanity.py)

Dynamic prototype side:

1. pose logs from Gazebo under [`rt_out/poses/`](./rt_out/poses)
2. [`30_build_prototype_dynamic_frames.py`](./rt_out/scripts/30_build_prototype_dynamic_frames.py)
3. [`31_build_prototype_dynamic_visual_frames.py`](./rt_out/scripts/31_build_prototype_dynamic_visual_frames.py)
4. [`32_export_dynamic_frame_meshes.py`](./rt_out/scripts/32_export_dynamic_frame_meshes.py)
5. [`33_compose_prototype_frame_scene.py`](./rt_out/scripts/33_compose_prototype_frame_scene.py)
6. [`34_build_prototype_frame_sionna_xml.py`](./rt_out/scripts/34_build_prototype_frame_sionna_xml.py)
7. [`35_run_prototype_three_frame_rt_sanity.py`](./rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py)
8. [`36_run_three_frame_three_rx_rt_sanity.py`](./rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py)

## Output Branch Note

The active scripts currently default to the unsuffixed outputs:

- [`rt_out/static_scene/export/`](./rt_out/static_scene/export)
- [`rt_out/composed_scene/`](./rt_out/composed_scene)

Earlier notes or older validation outputs may still refer to `_fixed` artifacts from the shelf-fix stage. That correction is now integrated into the normal merge path, so current reruns should normally use the unsuffixed outputs.

## Quick Gazebo Launch

Launch the regular world:

```bash
./run_myworld.sh
```

Launch the RT extraction world:

```bash
./run_myworld_rt.sh
```

## Current Validated Quickstart

Minimal working path for the current validated pipeline.

If you need fresh Panda/UR5 pose logs, start the RT world in one terminal and run the logger/motion helper in another:

```bash
./run_myworld_rt.sh
bash rt_out/scripts/run_all.sh
```

Then run the RT pipeline:

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

`35` and `36` call the frame composition / frame XML stages internally, so you do not need to run `32` / `33` / `34` separately for the standard sanity path.

The RT sanity steps expect the Sionna/Mitsuba environment used by the project today, typically through `COLLABPAPER_PYTHON` or the standard `collabpaper` conda environment.

## Blender Inspection Note

For quick visual checks in Blender:

- importing the **static** scene alone will **not** show `Panda` or `ur5_rg2`, because those robots are handled by the dynamic prototype path
- importing raw/source/cache robot meshes directly can make them look stacked, overlapped, or misplaced, because those files are usually still in model-local mesh coordinates
- for visually checking robot placement, use:
  - the composed frame outputs under [`rt_out/composed_scene/frame_000/`](./rt_out/composed_scene/frame_000), [`frame_001/`](./rt_out/composed_scene/frame_001), [`frame_002/`](./rt_out/composed_scene/frame_002)
  - or the baked dynamic meshes under [`rt_out/dynamic_scene/frame_000/raw_visual_meshes/`](./rt_out/dynamic_scene/frame_000/raw_visual_meshes), [`frame_001/raw_visual_meshes/`](./rt_out/dynamic_scene/frame_001/raw_visual_meshes), [`frame_002/raw_visual_meshes/`](./rt_out/dynamic_scene/frame_002/raw_visual_meshes)

## Current Config Files

- [`rt_out/config/dynamic_prototype_config.json`](./rt_out/config/dynamic_prototype_config.json): dynamic model names, pose logs, expected link counts, prototype frame indices, forced dynamic materials
- [`rt_out/config/rt_material_mapping.json`](./rt_out/config/rt_material_mapping.json): 28 GHz RT baseline and radio-material mapping
- [`rt_out/config/prototype_radio_sites.json`](./rt_out/config/prototype_radio_sites.json): approved TX/RX positions for the 3-frame x 3-RX sanity evaluation
