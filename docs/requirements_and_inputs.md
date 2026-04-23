# Requirements And Inputs

This document explains what you need **before** running the current validated pipeline.

Use it together with:

- [`README.md`](../README.md) for the project overview
- [`docs/step_by_step_guide.md`](./step_by_step_guide.md) for the run order
- [`docs/script_reference.md`](./script_reference.md) for per-script details

This page is intentionally practical. It answers:

- what software must be installed
- what environments must exist
- what files the repo must already contain
- what data the pipeline can generate
- what data you still need to provide manually

## Current Validated Scope

The active validated path in this repo is:

- rigid **non-actor** Gazebo scenes
- static scene export to Mitsuba/Sionna
- dynamic prototype for **`Panda`** and **`ur5_rg2`** only
- exactly **3 prototype frames**
- explicit **28 GHz** RT baseline
- three-frame sanity and three-frame x three-RX sanity evaluation

Actors are present in some world files but are **not** part of the active RT extraction flow.

## 1. Software Requirements

### Core tools

| Requirement | Why it is needed | Used by |
|---|---|---|
| `python3` | Runs the manifest, registry, merge-driver, XML, and orchestration scripts | `00-36` |
| Blender | Imports source meshes and exports transformed/merged `PLY` meshes | `20`, `21`, `32`, helpers `10`, `11` |
| Gazebo Sim / `gz` CLI | Launches the RT world and records Panda/UR5 pose logs | `run_myworld_rt.sh`, `run_all.sh`, `run_panda.sh`, `run_ur5.sh` |
| Sionna RT + Mitsuba | Loads the emitted XML scenes and computes RT paths | `24`, `35`, `36` |
| Bash | Runs the motion/logging helpers and world launch scripts | `run_myworld.sh`, `run_myworld_rt.sh`, `run_all.sh`, `run_panda.sh`, `run_ur5.sh` |

### Python / environment expectations

There are really **two Python contexts** in the current project:

1. **General preprocessing scripts**  
   These are usually run with plain `python3` from your normal shell.

2. **RT evaluation scripts**  
   These require the Sionna/Mitsuba environment used by this repo, currently the `collabpaper` environment.

The current runners look for that RT interpreter automatically, but setting it explicitly is safer:

```bash
export COLLABPAPER_PYTHON="${COLLABPAPER_PYTHON:-$HOME/miniconda3/envs/collabpaper/bin/python}"
```

### Blender discovery

The Blender-using scripts try these in order:

1. `BLENDER`
2. `blender` on `PATH`
3. a few repo/home fallback locations

The most reliable setup is:

```bash
export BLENDER="${BLENDER:-blender}"
```

### Gazebo assumptions

To generate fresh pose logs, you need:

- a working `gz` CLI
- the RT world launch path
- access to the repo’s `models/` tree through the resource path setup already handled by [`run_myworld_rt.sh`](../run_myworld_rt.sh)

### Suggested shell setup

Run from the repo root:

```bash
cd /path/to/my_world
export BLENDER="${BLENDER:-blender}"
export COLLABPAPER_PYTHON="${COLLABPAPER_PYTHON:-$HOME/miniconda3/envs/collabpaper/bin/python}"
```

## 2. Repository-Side Required Files

These files are expected to exist in the repository for the active flow to work.

### World and model inputs

- [`myworld_rt.sdf`](../myworld_rt.sdf)  
  Main RT extraction world. `00_extract_scene_manifests.py` reads this.

- [`myworld.sdf`](../myworld.sdf)  
  Main Gazebo world. Useful for simulation authoring, but the RT pipeline itself reads `myworld_rt.sdf`.

- [`models/`](../models)  
  Gazebo model library, including:
  - static furniture/assets
  - the standing person model
  - `Panda`
  - `ur5_rg2`
  - any other world models present in `myworld_rt.sdf`

### Active config inputs

- [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)  
  Static semantic material rules used by `03`.

- [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)  
  RT material mapping and current **28 GHz** carrier frequency source of truth.

- [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)  
  Dynamic prototype configuration:
  - `Panda` / `ur5_rg2`
  - pose log paths
  - expected link counts
  - prototype frame/sample mapping
  - forced dynamic material defaults

- [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)  
  Current approved TX/RX positions for the multi-RX sanity run.

### Runtime helper scripts expected by the workflow

- [`run_myworld_rt.sh`](../run_myworld_rt.sh)
- [`rt_out/scripts/run_all.sh`](../rt_out/scripts/run_all.sh)
- [`rt_out/scripts/run_panda.sh`](../rt_out/scripts/run_panda.sh)
- [`rt_out/scripts/run_ur5.sh`](../rt_out/scripts/run_ur5.sh)

These matter because they are the current operational path for generating the pose logs used by the dynamic prototype.

## 3. Required Data Inputs

This is the most important section. It separates:

- inputs the repo should already contain
- data you can regenerate
- data you may need to provide manually

### A. Static source geometry

#### Required before `00-03`

- the world and model SDF files
- source meshes referenced by those models under [`models/`](../models)

These are part of the Gazebo side of the repo.

#### Required before `20`

- prepared static scene meshes under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes)

This is an important current limitation:

- the active static merge path expects those converted meshes to already exist when a mesh is not directly usable as `PLY` or `OBJ`
- `03_build_static_scene_registry.py` marks such entries as `missing_converted_mesh` if the expected converted file is absent
- `20_merge_static_scene_by_material.py` expects `scene_mesh_path` to exist for every `ready` mesh entry

So, for the current repo:

- some static assets are effectively **pre-prepared inputs**
- they are not yet rebuilt by one single automatic “convert all static meshes” stage

Manual fallback if needed:

- use [`10_convert_dae_to_ply_blender.py`](../rt_out/scripts/10_convert_dae_to_ply_blender.py)
- use [`11_convert_mesh_to_ply_blender.py`](../rt_out/scripts/11_convert_mesh_to_ply_blender.py)

### B. Dynamic pose logs

#### Required before `30`

- [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
- [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)

These are required inputs for the dynamic prototype.

They can come from either:

1. the repo already containing the logs you want to use, or
2. you generating fresh ones by running Gazebo + the motion/logging helpers

Current generation path:

```bash
./run_myworld_rt.sh
bash rt_out/scripts/run_all.sh
```

`run_all.sh` records:

- `/model/Panda/pose` -> `rt_out/poses/panda/panda_pose.log`
- `/model/ur5_rg2/pose` -> `rt_out/poses/ur5/ur5_pose.log`

### C. Generated intermediate data

These are not hand-authored inputs, but later steps depend on them:

| File | Produced by | Needed by |
|---|---|---|
| [`rt_out/manifests/static_manifest.json`](../rt_out/manifests/static_manifest.json) | `00` | `01`, `02` |
| [`rt_out/manifests/dynamic_manifest.json`](../rt_out/manifests/dynamic_manifest.json) | `00` | `01`, `02`, `30`, `31` |
| [`rt_out/manifests/geometry_registry.json`](../rt_out/manifests/geometry_registry.json) | `02` | `03` |
| [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json) | `03` | `20` |
| [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json) | `20` | `22`, `23`, `33`, `35`, `36` |
| [`rt_out/dynamic_frames/prototype_frames.json`](../rt_out/dynamic_frames/prototype_frames.json) | `30` | `31` |
| [`rt_out/dynamic_frames/dynamic_visual_frames.json`](../rt_out/dynamic_frames/dynamic_visual_frames.json) | `31` | `32`, `35` |
| [`rt_out/dynamic_scene/frame_XXX/dynamic_frame_XXX_manifest.json`](../rt_out/dynamic_scene/frame_000/dynamic_frame_000_manifest.json) | `32` or `35` | `33`, `36` |
| [`rt_out/composed_scene/frame_XXX/composed_frame_XXX_manifest.json`](../rt_out/composed_scene/frame_000/composed_frame_000_manifest.json) | `33`, `35`, `36` | `34`, RT runs |
| [`rt_out/composed_scene/frame_XXX/frame_XXX_sionna.xml`](../rt_out/composed_scene/frame_000/frame_000_sionna.xml) | `34`, `35`, `36` | `24`, RT runs |

## 4. What Do I Need To Provide?

### To run only the static branch, you need:

- the repo with:
  - [`myworld_rt.sdf`](../myworld_rt.sdf)
  - [`models/`](../models)
  - [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)
  - [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- Python 3
- Blender
- prepared static converted meshes under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes)

If you also want to run static RT sanity, you additionally need:

- the `collabpaper` Sionna/Mitsuba environment, or `COLLABPAPER_PYTHON`

### To run the dynamic prototype, you additionally need:

- [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- `Panda` and `ur5_rg2` model definitions under [`models/`](../models)
- both pose logs:
  - [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
  - [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)

Those logs can either:

- already exist in the repo, or
- be generated by you with Gazebo + the motion/logging helpers

### To run the full current validated flow, you need:

- everything from the static branch checklist
- everything from the dynamic prototype checklist
- [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json) for the 3-frame x 3-RX run
- the `collabpaper` RT environment for `24`, `35`, and `36`

## 5. What Can The Pipeline Generate For Me?

This section is the flip side of the checklists above.

- **Generated by `00`**
  - static manifest
  - dynamic manifest

- **Generated by `01`**
  - manifest validation report

- **Generated by `02`**
  - geometry registry

- **Generated by `03`**
  - static scene registry

- **Generated by `20`**
  - merged static per-material meshes
  - merged static manifest
  - merge debug records

- **Generated by `22`**
  - static Mitsuba XML

- **Generated by `23`**
  - static Sionna XML

- **Generated by `30`**
  - trusted 3-frame dynamic motion manifest

- **Generated by `31`**
  - dynamic visual frame join artifact

- **Generated by `32`**
  - per-frame dynamic transformed meshes
  - per-frame dynamic export manifest

- **Generated by `35`**
  - dynamic exports for frames `0`, `1`, `2`
  - composed frame manifests for frames `0`, `1`, `2`
  - frame Sionna XMLs for frames `0`, `1`, `2`
  - [`rt_out/composed_scene/three_frame_rt_summary.csv`](../rt_out/composed_scene/three_frame_rt_summary.csv)

- **Generated by `36`**
  - refreshed composed manifests / frame XMLs as needed
  - [`rt_out/composed_scene/three_frame_three_rx_rt_summary.csv`](../rt_out/composed_scene/three_frame_three_rx_rt_summary.csv)

### What the pipeline does **not** currently generate for you automatically

- all static converted meshes from raw source assets in one end-to-end stage
- new pose logs unless you actually run the Gazebo world and logging helpers
- a general arbitrary-scene dynamic configuration

## 6. One-Shot Execution Readiness

If you want to run the **whole validated pipeline at once**, this is what must already be in place:

### Required source files

- [`myworld_rt.sdf`](../myworld_rt.sdf)
- [`models/`](../models)
- active configs:
  - [`material_map.json`](../rt_out/materials/material_map.json)
  - [`rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
  - [`dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
  - [`prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)

### Required environments

- `python3`
- Blender
- Gazebo Sim / `gz`
- `collabpaper` RT Python or `COLLABPAPER_PYTHON`

### Required data

- static converted meshes under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes)
- either:
  - existing Panda/UR5 pose logs, or
  - the ability to generate them with Gazebo + the motion scripts

### Honest current status

A fresh user can run **most** of the pipeline from the repo, but the current repo is **not yet fully one-click from-scratch reproducible**.

The two main reasons are:

1. the static side currently assumes prepared converted meshes already exist for some assets
2. the dynamic prototype assumes Panda/UR5 pose logs already exist, or that you will generate them before running `30`

So the repo is currently best described as:

- **re-runnable once the expected inputs are present**
- **not yet a full “clone and run everything from zero with no prep” pipeline**

## 7. Missing-Input Detection Checklist

Before a full run, check these quickly.

### Environment checks

```bash
command -v python3
command -v gz
command -v blender
test -x "${COLLABPAPER_PYTHON:-$HOME/miniconda3/envs/collabpaper/bin/python}"
```

### Core repo inputs

```bash
test -f myworld_rt.sdf
test -f rt_out/materials/material_map.json
test -f rt_out/config/rt_material_mapping.json
test -f rt_out/config/dynamic_prototype_config.json
test -f rt_out/config/prototype_radio_sites.json
```

### Static converted meshes

```bash
find rt_out/static_scene/converted_meshes -type f | head
```

If that directory is empty, the current static merge path is probably not ready yet.

### Pose logs

```bash
test -f rt_out/poses/panda/panda_pose.log
test -f rt_out/poses/ur5/ur5_pose.log
```

If those are missing, generate them before running `30` or `35`.

### Optional early validation after `00`

After manifest extraction, the fastest useful sanity check is:

```bash
python3 rt_out/scripts/01_validate_scene_manifests.py
python3 rt_out/scripts/02_build_scene_geometry_registry.py
python3 rt_out/scripts/03_build_static_scene_registry.py
```

Then inspect [`rt_out/manifests/static_registry.json`](../rt_out/manifests/static_registry.json) for mesh entries marked:

- `missing_converted_mesh`
- `missing_source_path`
- `unsupported_mesh_extension`

Those statuses tell you the static merge inputs are not fully ready yet.

## 8. Recommended Next Improvement

The simplest future improvement would be a small **preflight checker** that verifies:

- environment tools exist
- required config files exist
- pose logs exist
- converted static meshes exist
- no `03` entries are blocked by `missing_converted_mesh`

That would make “can I run this now?” much easier to answer automatically.
