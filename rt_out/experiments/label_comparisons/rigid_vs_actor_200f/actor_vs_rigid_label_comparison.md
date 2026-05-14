# Actor vs Rigid RT Label Comparison

## Inputs

- Baseline labels: `/home/telilab4090/Documents/Gazebo World/my_world/rt_out/experiments/semantic_ablation_rigid_200f/rt_results/rt_200frames_multi_rx_labeled.csv`
- Actor labels: `/home/telilab4090/Documents/Gazebo World/my_world/rt_out/experiments/semantic_ablation_actor_200f/rt_results/rt_200frames_multi_rx_labeled.csv`
- Join keys: `frame_id, source_sample_index, rx_id`

## Validation Summary

- Baseline row count: `1194`
- Actor row count: `1194`
- Expected row count: `1194`
- Matching joined rows: `1194`
- Missing baseline rows in actor: `0`
- Missing actor rows in baseline: `0`
- Duplicate join violations: `0`

## Overall Label Comparison

| Label | Baseline+ | Actor+ | Delta+ | Changed | Changed Ratio | New + | Lost + |
| --- | --- | --- | --- | --- | --- | --- | --- |
| y_path_change | 213 | 314 | 101 | 107 | 0.0896 | 104 | 3 |
| y_path_drop | 102 | 150 | 48 | 52 | 0.0436 | 50 | 2 |
| y_rx_power_drop_0p5db | 25 | 27 | 2 | 2 | 0.0017 | 2 | 0 |
| y_rx_power_drop_1db | 23 | 25 | 2 | 2 | 0.0017 | 2 | 0 |
| y_rx_power_drop_2db | 15 | 17 | 2 | 2 | 0.0017 | 2 | 0 |
| y_delay_spread_increase | 25 | 29 | 4 | 4 | 0.0034 | 4 | 0 |
| y_adaptation_trigger_1db | 46 | 52 | 6 | 6 | 0.0050 | 6 | 0 |
| y_adaptation_trigger_2db | 38 | 44 | 6 | 6 | 0.0050 | 6 | 0 |

## Per-RX Label Comparison

| RX | Label | Baseline+ | Actor+ | New + | Lost + | Changed |
| --- | --- | --- | --- | --- | --- | --- |
| rx_cerberus_base | y_path_change | 4 | 22 | 18 | 0 | 18 |
| rx_human_chest | y_path_change | 17 | 21 | 4 | 0 | 4 |
| rx_nao_chest | y_path_change | 43 | 72 | 30 | 1 | 31 |
| rx_panda_base | y_path_change | 75 | 89 | 15 | 1 | 16 |
| rx_ur5_base | y_path_change | 66 | 78 | 12 | 0 | 12 |
| rx_x500_body | y_path_change | 8 | 32 | 25 | 1 | 26 |
| rx_cerberus_base | y_path_drop | 2 | 11 | 9 | 0 | 9 |
| rx_human_chest | y_path_drop | 7 | 9 | 2 | 0 | 2 |
| rx_nao_chest | y_path_drop | 21 | 35 | 15 | 1 | 16 |
| rx_panda_base | y_path_drop | 38 | 44 | 6 | 0 | 6 |
| rx_ur5_base | y_path_drop | 30 | 35 | 5 | 0 | 5 |
| rx_x500_body | y_path_drop | 4 | 16 | 13 | 1 | 14 |
| rx_cerberus_base | y_rx_power_drop_0p5db | 0 | 1 | 1 | 0 | 1 |
| rx_human_chest | y_rx_power_drop_0p5db | 1 | 1 | 0 | 0 | 0 |
| rx_nao_chest | y_rx_power_drop_0p5db | 0 | 1 | 1 | 0 | 1 |
| rx_panda_base | y_rx_power_drop_0p5db | 5 | 5 | 0 | 0 | 0 |
| rx_ur5_base | y_rx_power_drop_0p5db | 19 | 19 | 0 | 0 | 0 |
| rx_x500_body | y_rx_power_drop_0p5db | 0 | 0 | 0 | 0 | 0 |
| rx_cerberus_base | y_rx_power_drop_1db | 0 | 1 | 1 | 0 | 1 |
| rx_human_chest | y_rx_power_drop_1db | 0 | 0 | 0 | 0 | 0 |
| rx_nao_chest | y_rx_power_drop_1db | 0 | 1 | 1 | 0 | 1 |
| rx_panda_base | y_rx_power_drop_1db | 5 | 5 | 0 | 0 | 0 |
| rx_ur5_base | y_rx_power_drop_1db | 18 | 18 | 0 | 0 | 0 |
| rx_x500_body | y_rx_power_drop_1db | 0 | 0 | 0 | 0 | 0 |
| rx_cerberus_base | y_rx_power_drop_2db | 0 | 1 | 1 | 0 | 1 |
| rx_human_chest | y_rx_power_drop_2db | 0 | 0 | 0 | 0 | 0 |
| rx_nao_chest | y_rx_power_drop_2db | 0 | 1 | 1 | 0 | 1 |
| rx_panda_base | y_rx_power_drop_2db | 4 | 4 | 0 | 0 | 0 |
| rx_ur5_base | y_rx_power_drop_2db | 11 | 11 | 0 | 0 | 0 |
| rx_x500_body | y_rx_power_drop_2db | 0 | 0 | 0 | 0 | 0 |
| rx_cerberus_base | y_delay_spread_increase | 2 | 4 | 2 | 0 | 2 |
| rx_human_chest | y_delay_spread_increase | 0 | 0 | 0 | 0 | 0 |
| rx_nao_chest | y_delay_spread_increase | 1 | 2 | 1 | 0 | 1 |
| rx_panda_base | y_delay_spread_increase | 9 | 10 | 1 | 0 | 1 |
| rx_ur5_base | y_delay_spread_increase | 13 | 13 | 0 | 0 | 0 |
| rx_x500_body | y_delay_spread_increase | 0 | 0 | 0 | 0 | 0 |
| rx_cerberus_base | y_adaptation_trigger_1db | 2 | 5 | 3 | 0 | 3 |
| rx_human_chest | y_adaptation_trigger_1db | 0 | 0 | 0 | 0 | 0 |
| rx_nao_chest | y_adaptation_trigger_1db | 1 | 3 | 2 | 0 | 2 |
| rx_panda_base | y_adaptation_trigger_1db | 12 | 13 | 1 | 0 | 1 |
| rx_ur5_base | y_adaptation_trigger_1db | 31 | 31 | 0 | 0 | 0 |
| rx_x500_body | y_adaptation_trigger_1db | 0 | 0 | 0 | 0 | 0 |
| rx_cerberus_base | y_adaptation_trigger_2db | 2 | 5 | 3 | 0 | 3 |
| rx_human_chest | y_adaptation_trigger_2db | 0 | 0 | 0 | 0 | 0 |
| rx_nao_chest | y_adaptation_trigger_2db | 1 | 3 | 2 | 0 | 2 |
| rx_panda_base | y_adaptation_trigger_2db | 11 | 12 | 1 | 0 | 1 |
| rx_ur5_base | y_adaptation_trigger_2db | 24 | 24 | 0 | 0 | 0 |
| rx_x500_body | y_adaptation_trigger_2db | 0 | 0 | 0 | 0 | 0 |

## Most Changed Labels

| Label | Rows Changed |
| --- | --- |
| y_path_change | 107 |
| y_path_drop | 52 |
| y_adaptation_trigger_1db | 6 |
| y_adaptation_trigger_2db | 6 |
| y_delay_spread_increase | 4 |

## Most Affected RXs

| RX | Total Changed Labels |
| --- | --- |
| rx_nao_chest | 55 |
| rx_x500_body | 40 |
| rx_cerberus_base | 38 |
| rx_panda_base | 25 |
| rx_ur5_base | 17 |
| rx_human_chest | 6 |

## Interpretation

- Labels with higher positive counts in the actor-aware branch: `y_path_change, y_path_drop, y_rx_power_drop_0p5db, y_rx_power_drop_1db, y_rx_power_drop_2db, y_delay_spread_increase, y_adaptation_trigger_1db, y_adaptation_trigger_2db`.
- Labels with lower positive counts in the actor-aware branch: `none`.
- Adaptation-trigger labels changed as follows: `y_adaptation_trigger_1db=6 changed rows, y_adaptation_trigger_2db=6 changed rows`.
- Path-related labels changed as follows: `y_path_change=107 changed rows, y_path_drop=52 changed rows`.
- RXs with the largest total number of label flips: `rx_nao_chest=55, rx_x500_body=40, rx_cerberus_base=38`.

## Caveat

Actor timing is offline sampled and not Gazebo-runtime-perfect phase.
