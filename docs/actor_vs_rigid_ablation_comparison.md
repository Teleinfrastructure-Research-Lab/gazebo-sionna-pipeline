# Actor-aware vs rigid ablation comparison

Best rows are selected by `f1_mean` within each task and feature mode. Actor values are from the uploaded actor-aware result CSVs. Rigid values are the previously validated rigid baseline values.

| task                    | feature_mode   | rigid_best_feature_set    | rigid_best_model   |   rigid_f1 | actor_best_feature_set    | actor_best_model   |   actor_f1 |   delta_f1_actor_minus_rigid |   rigid_bal_acc |   actor_bal_acc |   delta_bal_acc_actor_minus_rigid |   rigid_pos_ratio |   actor_pos_ratio |   num_rows |
|:------------------------|:---------------|:--------------------------|:-------------------|-----------:|:--------------------------|:-------------------|-----------:|-----------------------------:|----------------:|----------------:|----------------------------------:|------------------:|------------------:|-----------:|
| Adaptation trigger 1 dB | compact        | compact_full_object_aware | rf                 |      0.393 | compact_full_object_aware | rf                 |      0.411 |                        0.018 |           0.648 |           0.658 |                             0.010 |             0.108 |             0.111 |        398 |
| Adaptation trigger 1 dB | raw            | raw_occupancy             | svm                |      0.261 | raw_occupancy             | svm                |      0.272 |                        0.011 |           0.606 |           0.611 |                             0.005 |             0.108 |             0.111 |        398 |
| Path change             | compact        | compact_full_object_aware | svm                |      0.509 | compact_full_object_aware | rf                 |      0.582 |                        0.073 |           0.625 |           0.659 |                             0.034 |             0.308 |             0.400 |        597 |
| Path change             | raw            | raw_occupancy             | svm                |      0.510 | raw_occupancy             | logistic           |      0.527 |                        0.017 |           0.628 |           0.568 |                            -0.060 |             0.308 |             0.400 |        597 |


## Short interpretation

- Actor-aware compact object features improve over the rigid compact baseline on both tasks.

- Actor-aware raw occupancy also improves slightly on the adaptation task but only modestly on path-change.

- The largest gain is for actor-aware compact path-change prediction.

- In the actor-aware branch, compact object-aware features outperform raw occupancy on both tasks.
