# Configs And World-Specific Parts

This document explains the **user-editable / non-generalized layer** of the current project.

Use it when you want to answer questions like:

- what files behave like configuration
- which parts are true config files versus config-like project files
- what is still specific to the current world or prototype
- what you must edit to adapt the project to a different Gazebo scene

This page is intentionally direct. It documents the repository as it exists now, not a future fully generalized version.

## 1. Overview

The project already has a useful split between:

- **true config files**  
  explicit JSON/rule files that control prototype frames, RT materials, TX/RX sites, and semantic material assignment

- **config-like project files**  
  world SDFs, model SDFs, helper modules, and script defaults that still encode important assumptions

The current validated flow is best thought of as:

- a reusable static export path for this repo’s current world structure
- plus a **prototype-scoped dynamic path** for `Panda` and `ur5_rg2`

## 2. True Config Files

These are the clearest user-editable control points.

### `rt_out/config/dynamic_prototype_config.json`

- **Path:** [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
- **What it controls:**
  - prototype frame IDs and source sample indices
  - dynamic model names
  - pose log paths
  - expected link counts
  - non-renderable links
  - forced dynamic materials
- **Current project-specific values:**
  - models: `Panda`, `ur5_rg2`
  - frames: `0`, `1`, `2`
  - sample indices: `0`, `25570`, `51140`
  - non-renderable links: `panda_link8`, `tool0`
  - forced material: `metal`
- **When to change it:**
  - using different dynamic models
  - changing the prototype frame set
  - pointing at different pose logs
  - changing which links are motion-only
- **Downstream stages:**
  - `00`, `01`, `30`, `31`, `32`, `34`, `35`, `36`
- **What breaks if inconsistent:**
  - dynamic models may be misclassified
  - frame parsing may fail on missing logs or wrong link counts
  - dynamic XML emission may reject unexpected model names

### `rt_out/config/prototype_radio_sites.json`

- **Path:** [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)
- **What it controls:**
  - multi-RX sanity transmitter position
  - approved receiver positions for the current three-frame comparison
- **Current project-specific values:**
  - TX ID: `tx_ap`
  - RX IDs:
    - `rx_panda_base`
    - `rx_ur5_base`
    - `rx_cerberus_base`
- **When to change it:**
  - evaluating different TX/RX placements
  - adapting the RT comparison to a different scene layout
- **Downstream stages:**
  - `36_run_three_frame_three_rx_rt_sanity.py`
- **What breaks if inconsistent:**
  - `36` currently expects `tx_ap` plus the three RX IDs above
  - changing the names without updating the runner will fail validation

### `rt_out/config/rt_material_mapping.json`

- **Path:** [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)
- **What it controls:**
  - global RT carrier frequency
  - semantic material-class -> radio-material mapping
  - custom `human_skin` properties
- **Current project-specific values:**
  - carrier frequency: `28e9`
  - custom `human_skin` parameters tied to that mmWave baseline
- **When to change it:**
  - changing the RT frequency
  - changing the material regime
  - adding a new semantic class that needs a radio-material mapping
- **Downstream stages:**
  - `23`, `24`, `34`, `35`, `36`
- **What breaks if inconsistent:**
  - XML generation fails if a used material class is not mapped
  - RT sanity can run with the wrong frequency/material regime

### `rt_out/experiments/<experiment_name>/configs/experiment_config.json`

- **Path pattern:** `rt_out/experiments/*/configs/experiment_config.json`
- **What it controls:**
  - experiment name and output root
  - number of sampled frames
  - dynamic model list
  - TX position
  - RX list
  - material and semantic groups of interest
  - optional `tx_power_dbm`
- **Current example:**
  - [`rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json`](../rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json)
- **When to change it:**
  - creating a new experiment branch
  - changing experiment-local TX/RX placements
  - changing frame count or output root
- **Downstream stages:**
  - `exp_sample_frames.py`
  - experiment-local batch wrappers
  - RT label / feature builders
  - semantic ablation evaluation
- **What breaks if inconsistent:**
  - experiment wrappers point at the wrong tree
  - RT rows no longer match the intended RX set
  - downstream row-count assumptions fail

### `rt_out/materials/material_map.json`

- **Path:** [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)
- **What it controls:**
  - semantic material assignment on the **static** side
  - skip rules such as `material="__skip__"`
- **Current project-specific values:**
  - naming rules tuned to this factory/lab scene
  - assignments such as:
    - `Picking_Shelves -> metal`
    - `person_standing -> human_skin`
    - wall/ceiling/floor naming matches
    - furniture/lab-object naming rules
- **When to change it:**
  - adapting to a world with different model/link/visual names
  - changing semantic material assumptions
  - changing which visuals should be skipped
- **Downstream stages:**
  - `03`, then everything downstream of the static registry
- **What breaks if inconsistent:**
  - semantic materials become wrong
  - wrong radio materials propagate into RT
  - skipped/not-skipped geometry changes the static scene unexpectedly

## 3. Config-Like Project Files

These are not simple JSON configs, but they still behave like configuration because they define the scene or centralize assumptions.

### `myworld_rt.sdf`

- **Path:** [`myworld_rt.sdf`](../myworld_rt.sdf)
- **Category:** config-like world-definition file
- **What it controls:**
  - the RT-facing Gazebo scene
  - which models/includes exist in the extraction world
  - world layout and model placement
  - presence of the dynamic prototype models
- **When to change it:**
  - changing the RT scene geometry/layout
  - adding/removing models
  - adapting the pipeline to a different Gazebo world
- **Downstream stages:**
  - `00`, and therefore everything else
- **What breaks if inconsistent:**
  - manifests no longer reflect the intended world
  - RT scenes represent the wrong geometry

### `myworld.sdf`

- **Path:** [`myworld.sdf`](../myworld.sdf)
- **Category:** config-like world-definition file
- **What it controls:**
  - the main Gazebo simulation world
- **Important note:**
  - the RT pipeline does **not** read this directly; it reads `myworld_rt.sdf`
- **When to change it:**
  - editing the simulation world
- **What can go wrong:**
  - if `myworld.sdf` and `myworld_rt.sdf` diverge, the simulation and RT pipelines stop matching

### `models/`

- **Path:** [`models/`](../models)
- **Category:** config-like asset library / world-specific input layer
- **What it controls:**
  - model SDF structure
  - mesh URIs
  - visual hierarchy
  - nested model structure
- **When to change it:**
  - editing actual scene assets
  - replacing or adding models
  - adapting the repo to a different world
- **Downstream stages:**
  - `00`, `01`, static URI resolution, dynamic visual resolution
- **What breaks if inconsistent:**
  - URI resolution fails
  - manifests become stale
  - converted-mesh expectations stop matching the assets

### `rt_out/scripts/dynamic_prototype_config.py`

- **Path:** [`rt_out/scripts/dynamic_prototype_config.py`](../rt_out/scripts/dynamic_prototype_config.py)
- **Category:** config-loader helper
- **Why it is config-like:**
  - it validates and expands `dynamic_prototype_config.json`
  - it derives secondary assumptions such as:
    - source-sample lookup by frame ID
    - expected total renderable visual count
- **When to change it:**
  - rarely; only if the prototype-config schema itself changes

### `rt_out/scripts/rt_material_config.py`

- **Path:** [`rt_out/scripts/rt_material_config.py`](../rt_out/scripts/rt_material_config.py)
- **Category:** config-loader helper
- **Why it is config-like:**
  - it validates and materializes the RT material config
  - it centralizes the carrier-frequency source of truth
- **When to change it:**
  - rarely; mainly if the RT material-config schema changes

### `run_myworld_rt.sh`

- **Path:** [`run_myworld_rt.sh`](../run_myworld_rt.sh)
- **Category:** config-like operational launcher
- **Why it is config-like:**
  - it hardwires the RT launch to `myworld_rt.sdf`
  - it defines the effective Gazebo resource roots at launch time
- **When to change it:**
  - if the RT world file name changes
  - if resource layout changes significantly

## 4. Script-Level Defaults That Behave Like Config

These are not config files, but they still encode important assumptions.

### World / manifest defaults

- [`00_extract_scene_manifests.py`](../rt_out/scripts/00_extract_scene_manifests.py)
  - always reads [`myworld_rt.sdf`](../myworld_rt.sdf)
  - classifies dynamic models using `dynamic_prototype_config.json`

- [`33_compose_prototype_frame_scene.py`](../rt_out/scripts/33_compose_prototype_frame_scene.py)
  - defaults to:
    - [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
    - [`rt_out/dynamic_scene/frame_XXX/dynamic_frame_XXX_manifest.json`](../rt_out/dynamic_scene/frame_000/dynamic_frame_000_manifest.json)
    - [`rt_out/composed_scene/frame_XXX/composed_frame_XXX_manifest.json`](../rt_out/composed_scene/frame_000/composed_frame_000_manifest.json)

- [`34_build_prototype_frame_sionna_xml.py`](../rt_out/scripts/34_build_prototype_frame_sionna_xml.py)
  - defaults to composed manifests and XMLs under [`rt_out/composed_scene/`](../rt_out/composed_scene)

- [`35_run_prototype_three_frame_rt_sanity.py`](../rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py)
  - defaults to the current standard output branch:
    - static manifest from [`rt_out/static_scene/export/`](../rt_out/static_scene/export)
    - composed outputs under [`rt_out/composed_scene/`](../rt_out/composed_scene)

- [`36_run_three_frame_three_rx_rt_sanity.py`](../rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py)
  - defaults to:
    - static manifest from [`rt_out/static_scene/export/merged_static_manifest.json`](../rt_out/static_scene/export/merged_static_manifest.json)
    - composed outputs under [`rt_out/composed_scene/`](../rt_out/composed_scene)
    - radio sites from [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)

### RT sanity fallback positions

- [`24_run_sionna_rt_sanity.py`](../rt_out/scripts/24_run_sionna_rt_sanity.py)
  - still contains default fallback TX/RX positions for the single-scene sanity run:
    - TX: `(-0.3, -3.8, 1.3)`
    - RX: `(2.5, -3.1, 1.3)`
  - these are effectively config-like defaults even though they live in code

- [`rt_out/scripts/exp_run_rt_multi_rx_batch.py`](../rt_out/scripts/exp_run_rt_multi_rx_batch.py)
  - keeps the historical output filename `rt_100frames_multi_rx.csv` even for
    `semantic_ablation_rigid_200f`
  - this is a compatibility naming wart rather than a scientific assumption,
    but it matters for downstream scripts and docs

### Environment-discovery assumptions

- [`20_merge_static_scene_by_material.py`](../rt_out/scripts/20_merge_static_scene_by_material.py)
- [`32_export_dynamic_frame_meshes.py`](../rt_out/scripts/32_export_dynamic_frame_meshes.py)
  - both contain Blender discovery logic

- [`35_run_prototype_three_frame_rt_sanity.py`](../rt_out/scripts/35_run_prototype_three_frame_rt_sanity.py)
- [`36_run_three_frame_three_rx_rt_sanity.py`](../rt_out/scripts/36_run_three_frame_three_rx_rt_sanity.py)
  - both contain `COLLABPAPER_PYTHON` discovery logic

## 5. Current Non-Generalized Assumptions

These are the important world-specific or prototype-specific assumptions still present in the repo.

### Dynamic prototype membership is still project-specific

- only `Panda` and `ur5_rg2` are treated as dynamic
- everything else is outside the validated dynamic path

### Prototype frames are still fixed and manually chosen

- current sample indices:
  - `0`
  - `25570`
  - `51140`

### Multi-RX evaluation still expects named approved sites

- `36` currently requires:
  - `tx_ap`
  - `rx_panda_base`
  - `rx_ur5_base`
  - `rx_cerberus_base`

The numeric positions are in config, but the expected site IDs are still coded into the runner.

### Static semantic material assignment is scene-name driven

- `material_map.json` relies heavily on current model/link/visual naming
- a different world with different naming will need new rules

### Static converted-mesh layout is still project-specific

- `03` expects converted static meshes under:
  - [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes)
- this is useful for the current repo, but it is not yet a generalized “convert everything automatically” stage

### Asset-local correction hooks are still hardcoded

The static merge Blender worker still contains asset-specific local corrections for:

- a reflective table mesh
- the `Picking_Shelves` mesh

Those hooks live in:

- [`21_merge_static_scene_blender_worker.py`](../rt_out/scripts/21_merge_static_scene_blender_worker.py)

They are intentional and useful, but they are clearly **world-specific fixes**, not general geometry logic.

### The RT extraction world is explicitly tied to `myworld_rt.sdf`

- the extractor does not currently take a generalized world-path config
- it uses the repo’s RT world file by default

### Actors are present but still out of scope

- the world SDFs contain actors
- the active RT path ignores them

## 6. If I Want To Adapt This To A Different World, What Do I Change?

This is the practical section.

### To adapt to a new static world, change:

- [`myworld_rt.sdf`](../myworld_rt.sdf)
- probably [`myworld.sdf`](../myworld.sdf) too, if you want simulation and RT to stay aligned
- model SDFs / assets under [`models/`](../models)
- semantic material rules in [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)
- converted static meshes under [`rt_out/static_scene/converted_meshes/`](../rt_out/static_scene/converted_meshes) if the asset set changes

### To adapt to different dynamic models, change:

- [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)
  - model names
  - pose log paths
  - expected link counts
  - non-renderable links
  - forced material defaults
- ensure [`myworld_rt.sdf`](../myworld_rt.sdf) actually contains those models
- ensure the pose logs match those model names

You may also need code changes if:

- the new dynamic models do not follow the current logged-pose assumptions
- the new models need a different multi-RX evaluation naming scheme

### To adapt to a different prototype frame selection, change:

- [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)

Then rerun:

- `30`
- `31`
- `35`
- `36`

### To adapt TX/RX placements, change:

- [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)

If you only change the numeric positions but keep the existing IDs, `36` should keep working.

If you want different **site names**, `36` currently also needs a code update because it expects the current IDs explicitly.

### To adapt to a different frequency/material regime, change:

- [`rt_out/config/rt_material_mapping.json`](../rt_out/config/rt_material_mapping.json)

Then rerun:

- `23`
- `24`
- `34`
- `35`
- `36`

### To adapt semantic material assumptions, change:

- [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)

Then rerun:

- `03`
- `20`
- `22`
- `23`
- `24`
- and any composed/dynamic RT stages that depend on the rebuilt static manifest

### To adapt pose-log generation to a different motion run, change:

- the Gazebo motion/logging helpers:
  - [`rt_out/scripts/run_all.sh`](../rt_out/scripts/run_all.sh)
  - [`rt_out/scripts/run_panda.sh`](../rt_out/scripts/run_panda.sh)
  - [`rt_out/scripts/run_ur5.sh`](../rt_out/scripts/run_ur5.sh)
- or provide different pose logs and update [`dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)

## 7. User-Defined World-Specific Inputs

These files are not “one universal answer” files. They are exactly where a user customizes the repo to their own world.

- [`myworld_rt.sdf`](../myworld_rt.sdf)  
  Your RT-facing world definition.

- [`myworld.sdf`](../myworld.sdf)  
  Your main Gazebo simulation world.

- [`models/`](../models)  
  Your model library and mesh/SDF structure.

- [`rt_out/materials/material_map.json`](../rt_out/materials/material_map.json)  
  Your semantic interpretation of the scene.

- [`rt_out/config/dynamic_prototype_config.json`](../rt_out/config/dynamic_prototype_config.json)  
  Your choice of dynamic models, logs, and prototype frames.

- [`rt_out/config/prototype_radio_sites.json`](../rt_out/config/prototype_radio_sites.json)  
  Your chosen TX/RX evaluation sites.

- pose logs under [`rt_out/poses/`](../rt_out/poses)  
  Your recorded motion run.

## 8. What Is Generalized Enough, What Is Still Project-Specific, And What Is Not Supported?

### Currently generalized enough

- static manifest extraction from the RT world
- static geometry registry / static registry flow
- static merge of supported geometry types
- Mitsuba/Sionna XML emission from merged manifests
- explicit RT material/frequency configuration
- frame-based prototype composition flow

### Currently still project-specific

- dynamic model membership (`Panda`, `ur5_rg2`)
- prototype frame selection (`0`, `25570`, `51140`)
- semantic material naming rules for this world
- approved TX/RX site IDs and placements
- asset-local orientation corrections in the static merge worker
- dependence on prepared converted static meshes

### Currently not supported

- actor integration in the RT path
- generalized arbitrary dynamic-scene configuration
- truly scene-agnostic semantic material assignment
- fully automatic static mesh conversion for every new asset in one end-to-end stage
- a fully generalized multi-site RT evaluation schema with arbitrary TX/RX naming
