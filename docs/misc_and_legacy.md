# Misc And Legacy Notes

This file covers scripts and folders that are part of the project, but are not part of the current main RT pipeline chain.

## 1. Gazebo Operational And Data-Generation Helpers

### `run_myworld.sh`

- **Path:** [`run_myworld.sh`](../run_myworld.sh)
- **Status:** misc
- **Purpose:** launches Gazebo on [`myworld.sdf`](../myworld.sdf)
- **Notes:** sets `GZ_SIM_RESOURCE_PATH` to the repo’s model folders before running `gz sim`

### `run_myworld_rt.sh`

- **Path:** [`run_myworld_rt.sh`](../run_myworld_rt.sh)
- **Status:** misc
- **Purpose:** launches Gazebo on [`myworld_rt.sdf`](../myworld_rt.sdf)
- **Notes:** useful when the RT extraction world needs to be the live Gazebo world

### `rt_out/scripts/run_all.sh`

- **Path:** [`rt_out/scripts/run_all.sh`](../rt_out/scripts/run_all.sh)
- **Status:** helper
- **Purpose:** operational helper that records Panda and UR5 pose logs while running both robot motion scripts
- **Produces:**
  - [`rt_out/poses/panda/panda_pose.log`](../rt_out/poses/panda/panda_pose.log)
  - [`rt_out/poses/ur5/ur5_pose.log`](../rt_out/poses/ur5/ur5_pose.log)
- **Why it matters:** this is the current data-generation entry point for the dynamic prototype logs

### `rt_out/scripts/run_panda.sh`

- **Path:** [`rt_out/scripts/run_panda.sh`](../rt_out/scripts/run_panda.sh)
- **Status:** helper
- **Purpose:** sends a scripted Panda joint-command sequence over Gazebo topics
- **Why it matters:** this operational helper drives the Panda motion that is later captured in `panda_pose.log`

### `rt_out/scripts/run_ur5.sh`

- **Path:** [`rt_out/scripts/run_ur5.sh`](../rt_out/scripts/run_ur5.sh)
- **Status:** helper
- **Purpose:** sends a scripted UR5/RG2 joint-command sequence over Gazebo topics
- **Why it matters:** this operational helper drives the UR5 motion that is later captured in `ur5_pose.log`

## 2. Experimental / Debug RT Script

### `rt_out/scripts/sionna_test.py`

- **Path:** [`rt_out/scripts/sionna_test.py`](../rt_out/scripts/sionna_test.py)
- **Status:** misc
- **Purpose:** ad hoc multi-RX static RT experiment script
- **Reads:** [`rt_out/static_scene/export/static_scene_sionna.xml`](../rt_out/static_scene/export/static_scene_sionna.xml)
- **Writes:** [`rt_out/static_scene/export/static_multi_rx_sanity.csv`](../rt_out/static_scene/export/static_multi_rx_sanity.csv)
- **Why it is not part of the active flow:**
  - it hardcodes its own RX list
  - it is not used by `35` or `36`
  - it is better treated as exploratory tooling than as a pipeline stage

## 3. World / Asset Authoring Helpers

### `scripts/generate_wall_uv_meshes.py`

- **Path:** [`scripts/generate_wall_uv_meshes.py`](../scripts/generate_wall_uv_meshes.py)
- **Status:** misc
- **Purpose:** generates UV-aware wall OBJ meshes so plaster textures continue across split wall segments
- **Outputs:** wall meshes and a placeholder material file
- **Why it matters:** this script belongs to the Gazebo world authoring side, not the RT export chain

### `plugins/preload_joint_pose.cc`

- **Path:** [`plugins/preload_joint_pose.cc`](../plugins/preload_joint_pose.cc)
- **Status:** misc
- **Purpose:** Gazebo plugin source for preloading joint positions on model configure
- **Built artifact:** [`plugins/libpreload_joint_pose.so`](../plugins/libpreload_joint_pose.so)
- **Why it is not in the RT chain:** it affects Gazebo simulation initialization, not RT preprocessing

## 4. Historical / Non-Active Content

### `backup world/`

- **Path:** [`backup world/`](../backup%20world)
- **Status:** historical
- **Purpose:** saved world variants and backups
- **Use with care:** these are helpful references, but they are not the current extraction target
