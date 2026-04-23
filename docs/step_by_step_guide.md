# Step-by-Step Operational Guide

This is the practical runbook for the **current validated pipeline**.

Use this guide when you want to run the repo end to end without guessing:

- what to run
- in what order
- what each step reads and writes
- when a step can be skipped
- what to rerun after a change

Before starting, check [`docs/requirements_and_inputs.md`](./requirements_and_inputs.md) so you know which inputs must already exist and which ones the pipeline can regenerate.
If you are adapting the repo to a different world or prototype, also check [`docs/configs_and_world_specific_parts.md`](./configs_and_world_specific_parts.md).

For detailed per-script notes, see [`docs/script_reference.md`](./script_reference.md).

## 1. Before You Run Anything

### Where to run from

Run all commands from the repository root:

```bash
cd /path/to/my_world
```

### What you need

- **Gazebo Sim** with the `gz` CLI available
- **Blender** available on `PATH`, or set with `BLENDER`
- **Sionna RT + Mitsuba** in the project’s current RT environment
  - the repo currently expects the `collabpaper` environment
  - `35` and `36` try to find it automatically, but setting `COLLABPAPER_PYTHON` is safer

### Recommended environment setup

```bash
conda activate collabpaper
export COLLABPAPER_PYTHON="${COLLABPAPER_PYTHON:-$HOME/miniconda3/envs/collabpaper/bin/python}"
export BLENDER="${BLENDER:-blender}"
```

### Important notes before starting

- The RT extractor reads [`myworld_rt.sdf`](../myworld_rt.sdf), not [`myworld.sdf`](../myworld.sdf).
- The shelf orientation correction is already integrated into the normal static merge path.
- Older notes may still mention `_fixed` artifacts, but current reruns should normally use the unsuffixed outputs.
- The current static side assumes the needed converted static meshes already exist under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes). If you add new static assets in formats such as `DAE`, `GLB`, or `STL`, you may need to refresh those converted meshes with the Blender helpers before the static merge is fully ready.

## 2. Scene / World Editing Side

### What defines the Gazebo scene

- [`myworld.sdf`](../myworld.sdf): main Gazebo world
- [`myworld_rt.sdf`](../myworld_rt.sdf): RT extraction world
- [`models/`](../models): model SDFs, meshes, textures, and assets

### When to edit `myworld_rt.sdf`

Edit [`myworld_rt.sdf`](../myworld_rt.sdf) when the RT pipeline should see a changed:

- model placement
- included model list
- static geometry layout
- dynamic model presence
- world-side pose of RT-relevant objects

If you change only [`myworld.sdf`](../myworld.sdf), the RT pipeline will **not** see that change unless you also carry it into [`myworld_rt.sdf`](../myworld_rt.sdf).

### When to edit `models/`

Edit files under [`models/`](../models) when you change:

- model geometry
- model-local SDF structure
- visual URIs
- meshes or textures

These changes flow downstream into:

- manifest extraction
- URI resolution
- static merge inputs
- dynamic visual resolution

## 3. Static RT Preprocessing

Run the static stages in this order.

### Step 00 - Extract scene manifests

- **Run**

```bash
python3 rt_out/scripts/00_extract_scene_manifests.py
```

- **Reads**
  - [`myworld_rt.sdf`](../myworld_rt.sdf)
  - model SDFs under [`models/`](../models)
  - [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Writes**
  - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
- **Why**
  - splits the Gazebo RT world into static and dynamic manifest inputs for the rest of the pipeline
- **Rerun this when**
  - [`myworld_rt.sdf`](../myworld_rt.sdf) changed
  - model SDF structure changed
  - dynamic prototype model membership changed
- **Skip if**
  - those inputs are unchanged and the manifest files are already current

### Step 01 - Validate the manifests

- **Run**

```bash
python3 rt_out/scripts/01_validate_scene_manifests.py
```

- **Reads**
  - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
  - [`models/`](../models)
- **Writes**
  - [`rt_out/manifests/manifest_validation_report.json`](../rt_out/manifests/manifest_validation_report.json)
- **Why**
  - catches structural issues, pose-format issues, bad URIs, and wrong dynamic model membership early
- **Rerun this when**
  - you rerun `00`
  - you hand-edit either manifest
- **Skip if**
  - manifests are unchanged and you already have a passing validation report for them

### Step 02 - Build the geometry registry

- **Run**

```bash
python3 rt_out/scripts/02_build_scene_geometry_registry.py
```

- **Reads**
  - [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
- **Writes**
  - [`rt_out/manifests/geometry_registry.json`](../rt_out/manifests/geometry_registry.json)
- **Why**
  - flattens all manifest visuals into normalized geometry records
- **Rerun this when**
  - `00` changed either manifest
- **Skip if**
  - manifests are unchanged and the registry is already current

### Step 03 - Build the static scene registry

- **Run**

```bash
python3 rt_out/scripts/03_build_static_scene_registry.py
```

- **Reads**
  - [`rt_out/manifests/geometry_registry.json`](../rt_out/manifests/geometry_registry.json)
  - [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)
- **Writes**
  - [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json)
- **Why**
  - filters to static entries
  - assigns semantic material classes
  - computes `to_world`
  - prepares the static merge input
- **Rerun this when**
  - `02` changed
  - [`material_map.json`](../rt_out/materials/material_map.json) changed
- **Skip if**
  - geometry registry and semantic material rules are unchanged

### Step 20 - Merge the static scene by material

- **Run**

```bash
python3 rt_out/scripts/20_merge_static_scene_by_material.py
```

- **Reads**
  - [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json)
  - Blender
- **Writes**
  - merged PLYs under [`rt_out/static_scene/export/merged_by_material/`](../rt_out/static_scene/export/merged_by_material)
  - debug job/result JSON under [`rt_out/static_scene/export/debug/`](../rt_out/static_scene/export/debug)
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
- **Why**
  - bakes the static scene into merged per-material meshes for Mitsuba/Sionna
- **Rerun this when**
  - `03` changed
  - static mesh conversion cache changed
  - Blender-side asset fixes changed
- **Skip if**
  - static registry and converted static meshes are unchanged

### Step 22 - Build the static Mitsuba XML

- **Run**

```bash
python3 rt_out/scripts/22_build_static_mitsuba_xml.py
```

- **Reads**
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
- **Writes**
  - [`rt_out/static_scene/export/static_scene_mitsuba.xml`](../rt_out/static_scene/export/static_scene_mitsuba.xml)
- **Why**
  - creates a visual/debug XML for scene inspection
- **Rerun this when**
  - `20` changed the merged static manifest
- **Skip if**
  - you are only doing RT and do not need the Mitsuba debug scene right now

### Step 23 - Build the static Sionna XML

- **Run**

```bash
python3 rt_out/scripts/23_build_static_sionna_xml.py
```

- **Reads**
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- **Writes**
  - [`rt_out/static_scene/export/static_scene_sionna.xml`](../rt_out/static_scene/export/static_scene_sionna.xml)
- **Why**
  - creates the radio-material XML used by Sionna RT
- **Rerun this when**
  - `20` changed
  - RT frequency/material config changed
- **Skip if**
  - merged static manifest and RT material config are unchanged

### Step 24 - Run the static Sionna sanity check

- **Run**

```bash
python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
```

- **Reads**
  - [`rt_out/static_scene/export/static_scene_sionna.xml`](../rt_out/static_scene/export/static_scene_sionna.xml)
  - current RT runtime config from [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- **Writes**
  - no files; prints diagnostics
- **Why**
  - confirms the static Sionna scene loads, TX/RX can be added, and path computation succeeds
- **Rerun this when**
  - `23` changed
  - you changed RT frequency or radio-material config
- **Skip if**
  - you already have a successful sanity run for the exact same static XML and runtime config

## 4. Dynamic Prototype Preparation

### When pose logs are needed

You need fresh pose logs when:

- the Panda / UR5 motion sequence changed
- you want a new dynamic prototype recording
- the existing logs are missing or intentionally being replaced

If the current logs are still the ones you want, you can skip log generation and go straight to `30` and `31`.

### How pose logs are generated

Typical pattern:

Terminal A:

```bash
./run_myworld_rt.sh
```

Terminal B:

```bash
bash rt_out/scripts/run_all.sh
```

What those helpers do:

- [`run_all.sh`](../rt_out/scripts/run_all.sh) starts the Panda and UR5 pose loggers and launches both robot motion scripts
- [`run_panda.sh`](../rt_out/scripts/run_panda.sh) drives the Panda motion sequence
- [`run_ur5.sh`](../rt_out/scripts/run_ur5.sh) drives the UR5/RG2 motion sequence

Use `run_panda.sh` or `run_ur5.sh` directly only when you intentionally want a one-robot motion run or are debugging a single sequence.

### Step 30 - Build prototype dynamic frames

- **Run**

```bash
python3 rt_out/scripts/30_build_prototype_dynamic_frames.py
```

- **Reads**
  - [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
  - [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
  - [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **Writes**
  - [`rt_out/dynamic_frames/prototype_frames.json`](../rt_out/dynamic_frames/prototype_frames.json)
- **Why**
  - reconstructs the trusted 3-frame motion manifest from the raw pose logs
- **Rerun this when**
  - either pose log changed
  - the dynamic prototype frame config changed
  - dynamic manifest link structure changed
- **Skip if**
  - logs, dynamic manifest, and frame config are unchanged

### Step 31 - Build dynamic visual frames

- **Run**

```bash
python3 rt_out/scripts/31_build_prototype_dynamic_visual_frames.py
```

- **Reads**
  - [`rt_out/dynamic_frames/prototype_frames.json`](../rt_out/dynamic_frames/prototype_frames.json)
  - [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json)
  - dynamic mesh assets under [`models/`](../models)
- **Writes**
  - [`rt_out/dynamic_frames/dynamic_visual_frames.json`](../rt_out/dynamic_frames/dynamic_visual_frames.json)
- **Why**
  - joins the trusted link transforms with the renderable visual metadata for Panda and UR5
- **Rerun this when**
  - `30` changed
  - dynamic manifest visuals changed
  - dynamic robot assets/URIs changed
- **Skip if**
  - motion frames and dynamic visual metadata are unchanged

## 5. End-to-End Prototype Sanity

### Step 35 - Run the 3-frame prototype sanity flow

- **Run**

```bash
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
```

- **Reads**
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - [`rt_out/dynamic_frames/dynamic_visual_frames.json`](../rt_out/dynamic_frames/dynamic_visual_frames.json)
  - current RT material/runtime config
- **Writes**
  - frame-specific dynamic mesh exports under [`rt_out/dynamic_scene/frame_000/`](../rt_out/dynamic_scene/frame_000), [`frame_001/`](../rt_out/dynamic_scene/frame_001), [`frame_002/`](../rt_out/dynamic_scene/frame_002)
  - composed frame manifests / XMLs under [`rt_out/composed_scene/`](../rt_out/composed_scene)
  - [`rt_out/composed_scene/three_frame_rt_summary.csv`](../rt_out/composed_scene/three_frame_rt_summary.csv)
- **Why**
  - this is the easiest end-to-end sanity runner for the current 3-frame prototype
- **What it does internally**
  - exports dynamic frame meshes (`32`)
  - composes static + dynamic per frame (`33`)
  - builds frame Sionna XML (`34`)
  - runs RT sanity and tau stats
- **Rerun this when**
  - static merged manifest changed
  - dynamic visual frames changed
  - RT material/frequency config changed
- **Skip if**
  - you already have a current `three_frame_rt_summary.csv` for the exact same static manifest, dynamic frames, and RT config

## 6. Multi-RX Evaluation

### Radio-site config

Approved TX/RX positions live in:

- [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)

### Step 36 - Run the 3-frame x 3-RX sanity flow

- **Run**

```bash
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

- **Reads**
  - [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)
  - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
  - existing dynamic exports under [`rt_out/dynamic_scene/`](../rt_out/dynamic_scene)
  - current RT material/runtime config
- **Writes**
  - refreshed composed frame manifests / XMLs under [`rt_out/composed_scene/`](../rt_out/composed_scene)
  - [`rt_out/composed_scene/three_frame_three_rx_rt_summary.csv`](../rt_out/composed_scene/three_frame_three_rx_rt_summary.csv)
- **Why**
  - validates whether the frame-dependent RT effect is still visible across multiple RX locations
- **Important expectation**
  - `36` does **not** run `32`
  - easiest path: run `35` first, then run `36`
- **Rerun this when**
  - TX/RX positions changed
  - static merged manifest changed
  - RT material/frequency config changed
  - dynamic per-frame exports were refreshed
- **Skip if**
  - the radio-site config and all scene inputs are unchanged and the CSV is already current

### How to interpret the CSV at a high level

Look at:

- `num_paths`
- `tau_min`
- `tau_max`
- whether frame `1` differs from frames `0` and `2`
- whether one RX is clearly more motion-sensitive than the others

This CSV is a **sanity / validation** artifact, not a final paper-ready evaluation by itself.

## 7. Visual Inspection

### Static-only scene vs full frame scene

- The static-only branch under [`rt_out/static_scene/export/`](../rt_out/static_scene/export) contains merged static geometry only.
- `Panda` and `ur5_rg2` are **not** part of that static merge, so they will not appear there.

### Why raw/cache robot meshes can look wrong in Blender

If you import raw or cached robot source meshes directly, they can look:

- stacked
- overlapped
- centered incorrectly
- generally “wrong”

That is expected, because those meshes are usually still in local mesh coordinates, not final world placement.

### What to import for inspection

For static-only inspection:

- import the merged static PLYs under [`rt_out/static_scene/export/merged_by_material/`](../rt_out/static_scene/export/merged_by_material)

For per-frame inspection:

- use the composed frame manifest as the inventory:
  - [`rt_out/composed_scene/frame_000/composed_frame_000_manifest.json`](../rt_out/composed_scene/frame_000/composed_frame_000_manifest.json)
  - [`rt_out/composed_scene/frame_001/composed_frame_001_manifest.json`](../rt_out/composed_scene/frame_001/composed_frame_001_manifest.json)
  - [`rt_out/composed_scene/frame_002/composed_frame_002_manifest.json`](../rt_out/composed_scene/frame_002/composed_frame_002_manifest.json)
- then import the mesh paths referenced there:
  - merged static PLYs
  - baked dynamic meshes under [`rt_out/dynamic_scene/frame_000/raw_visual_meshes/`](../rt_out/dynamic_scene/frame_000/raw_visual_meshes), [`frame_001/raw_visual_meshes/`](../rt_out/dynamic_scene/frame_001/raw_visual_meshes), [`frame_002/raw_visual_meshes/`](../rt_out/dynamic_scene/frame_002/raw_visual_meshes)

## 8. What Should I Rerun If I Changed X?

### If I changed the world geometry

Rerun:

```bash
python3 rt_out/scripts/00_extract_scene_manifests.py
python3 rt_out/scripts/01_validate_scene_manifests.py
python3 rt_out/scripts/02_build_scene_geometry_registry.py
python3 rt_out/scripts/03_build_static_scene_registry.py
python3 rt_out/scripts/20_merge_static_scene_by_material.py
python3 rt_out/scripts/22_build_static_mitsuba_xml.py
python3 rt_out/scripts/23_build_static_sionna_xml.py
python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

If the change also touched dynamic robot SDF structure or visuals, rerun `30` and `31` before `35`.

### If I changed only semantic material mapping (`material_map.json`)

Rerun:

```bash
python3 rt_out/scripts/03_build_static_scene_registry.py
python3 rt_out/scripts/20_merge_static_scene_by_material.py
python3 rt_out/scripts/22_build_static_mitsuba_xml.py
python3 rt_out/scripts/23_build_static_sionna_xml.py
python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

### If I changed only dynamic logs

Rerun:

```bash
python3 rt_out/scripts/30_build_prototype_dynamic_frames.py
python3 rt_out/scripts/31_build_prototype_dynamic_visual_frames.py
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

### If I changed only TX/RX positions

Rerun:

```bash
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

If you want a one-off single-RX check instead, rerun `24` directly with `--tx` / `--rx`.

### If I changed only the frequency / RT material config

Rerun:

```bash
python3 rt_out/scripts/23_build_static_sionna_xml.py
python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

If you changed only the runtime frequency/material model and not semantic material assignment, you do **not** need to rerun `00` through `20`.

## 9. Current Validated Quickstart

If you already have the current Panda/UR5 logs:

```bash
python3 rt_out/scripts/00_extract_scene_manifests.py
python3 rt_out/scripts/01_validate_scene_manifests.py
python3 rt_out/scripts/02_build_scene_geometry_registry.py
python3 rt_out/scripts/03_build_static_scene_registry.py
python3 rt_out/scripts/20_merge_static_scene_by_material.py
python3 rt_out/scripts/22_build_static_mitsuba_xml.py
python3 rt_out/scripts/23_build_static_sionna_xml.py
python3 rt_out/scripts/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
python3 rt_out/scripts/30_build_prototype_dynamic_frames.py
python3 rt_out/scripts/31_build_prototype_dynamic_visual_frames.py
python3 rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py
```

If you need fresh logs first:

```bash
./run_myworld_rt.sh
bash rt_out/scripts/run_all.sh
```

## 10. Current Limitations

- Actors are present in the world files, but they are **not** integrated into the active RT pipeline.
- Dynamic support is still prototype-scoped to the configured Panda/UR5 workflow.
- The pipeline is validated for the current rigid non-actor workflow, but it is **not yet** a fully general Gazebo scene pipeline.
- The static side still relies on prepared converted meshes under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes) for some asset formats.
