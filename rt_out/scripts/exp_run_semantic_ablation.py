#!/usr/bin/env python3

"""Evaluate lightweight classical baselines on the experiment feature table.

The script keeps the learning side intentionally simple: grouped frame-level
cross-validation, RX filtering, raw/compact/wide feature subsets, and a small
set of classical models. The targets come from RT-derived labels such as
adaptation-trigger or path-change events; this script does not implement full
beamforming or resource allocation.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SemanticAblationError(RuntimeError):
    pass


WIDE_FEATURE_SET_ORDER = [
    "majority_baseline",
    "geometry_only",
    "geometry_material",
    "geometry_semantic",
    "full_object_aware",
]


COMPACT_FEATURE_SET_ORDER = [
    "majority_baseline",
    "compact_geometry",
    "compact_geometry_material",
    "compact_geometry_semantic",
    "compact_full_object_aware",
]


RAW_FEATURE_SET_ORDER = [
    "majority_baseline",
    "raw_occupancy",
]


COMPACT_FEATURE_COLUMNS = {
    "compact_geometry": [
        "geom_rx_x",
        "geom_rx_y",
        "geom_rx_z",
        "geom_tx_rx_distance",
        "geom_all_line_dist_min",
        "geom_dynamic_line_dist_min",
        "geom_dynamic_rx_dist_min",
        "geom_dynamic_count",
        "geom_dynamic_centroid_count",
    ],
    "compact_geometry_material": [
        "geom_rx_x",
        "geom_rx_y",
        "geom_rx_z",
        "geom_tx_rx_distance",
        "geom_all_line_dist_min",
        "geom_dynamic_line_dist_min",
        "geom_dynamic_rx_dist_min",
        "geom_dynamic_count",
        "geom_dynamic_centroid_count",
        "mat_metal_line_dist_min",
        "mat_metal_rx_dist_min",
        "mat_metal_count",
        "mat_metal_dynamic_count",
        "mat_glass_line_dist_min",
        "mat_glass_rx_dist_min",
        "mat_wood_line_dist_min",
        "mat_wood_rx_dist_min",
        "mat_plastic_line_dist_min",
        "mat_plastic_rx_dist_min",
        "mat_textile_line_dist_min",
        "mat_cardboard_line_dist_min",
    ],
    "compact_geometry_semantic": [
        "geom_rx_x",
        "geom_rx_y",
        "geom_rx_z",
        "geom_tx_rx_distance",
        "geom_all_line_dist_min",
        "geom_dynamic_line_dist_min",
        "geom_dynamic_rx_dist_min",
        "geom_dynamic_count",
        "geom_dynamic_centroid_count",
        "sem_robot_arm_line_dist_min",
        "sem_robot_arm_rx_dist_min",
        "sem_robot_arm_count",
        "sem_robot_arm_dynamic_count",
        "sem_shelf_line_dist_min",
        "sem_window_line_dist_min",
        "sem_desk_line_dist_min",
        "sem_door_line_dist_min",
        "sem_robot_line_dist_min",
        "sem_drone_line_dist_min",
        "sem_laptop_line_dist_min",
    ],
    "compact_full_object_aware": [
        "geom_rx_x",
        "geom_rx_y",
        "geom_rx_z",
        "geom_tx_rx_distance",
        "geom_all_line_dist_min",
        "geom_dynamic_line_dist_min",
        "geom_dynamic_rx_dist_min",
        "geom_dynamic_count",
        "geom_dynamic_centroid_count",
        "mat_metal_line_dist_min",
        "mat_metal_rx_dist_min",
        "mat_metal_count",
        "mat_metal_dynamic_count",
        "mat_glass_line_dist_min",
        "mat_glass_rx_dist_min",
        "mat_wood_line_dist_min",
        "mat_wood_rx_dist_min",
        "mat_plastic_line_dist_min",
        "mat_plastic_rx_dist_min",
        "mat_textile_line_dist_min",
        "mat_cardboard_line_dist_min",
        "sem_robot_arm_line_dist_min",
        "sem_robot_arm_rx_dist_min",
        "sem_robot_arm_count",
        "sem_robot_arm_dynamic_count",
        "sem_shelf_line_dist_min",
        "sem_window_line_dist_min",
        "sem_desk_line_dist_min",
        "sem_door_line_dist_min",
        "sem_robot_line_dist_min",
        "sem_drone_line_dist_min",
        "sem_laptop_line_dist_min",
        "obj_panda_line_dist_min",
        "obj_panda_rx_dist_min",
        "obj_panda_centroid_x_mean",
        "obj_panda_centroid_y_mean",
        "obj_panda_centroid_z_mean",
        "obj_ur5_rg2_line_dist_min",
        "obj_ur5_rg2_rx_dist_min",
        "obj_ur5_rg2_centroid_x_mean",
        "obj_ur5_rg2_centroid_y_mean",
        "obj_ur5_rg2_centroid_z_mean",
    ],
}


RESULT_COLUMNS = [
    "target",
    "rx_filter",
    "feature_set",
    "num_rows",
    "positive_ratio",
    "model",
    "accuracy_mean",
    "accuracy_std",
    "balanced_accuracy_mean",
    "balanced_accuracy_std",
    "precision_mean",
    "precision_std",
    "recall_mean",
    "recall_std",
    "f1_mean",
    "f1_std",
]


MODEL_CHOICES = ["logistic", "rf", "svm", "mlp"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run lightweight semantic/material ablation baselines with grouped frame splits."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to experiment_config.json",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Binary target column from the selected feature table",
    )
    parser.add_argument(
        "--rx-filter",
        default=None,
        help="Optional comma-separated RX ID filter, e.g. rx_panda_base,rx_ur5_base",
    )
    parser.add_argument(
        "--feature-mode",
        choices=["wide", "compact", "raw"],
        default="wide",
        help="Feature subset mode. Default: wide",
    )
    parser.add_argument(
        "--models",
        default="logistic",
        help="Comma-separated model list. Supported: logistic,rf,svm,mlp. Default: logistic",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise SemanticAblationError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SemanticAblationError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SemanticAblationError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticAblationError(f"{label} must be a non-empty string")
    return value.strip()


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_experiment_config(path: Path) -> dict[str, Any]:
    # Only the experiment name and output root are needed here because the
    # learning script consumes the already-built feature table.
    config = require_object(load_json(path), "experiment_config.json")
    experiment_name = require_non_empty_string(
        config.get("experiment_name"),
        "experiment_config.experiment_name",
    )
    output_dir = require_non_empty_string(
        config.get("output_dir"),
        "experiment_config.output_dir",
    )
    return {
        "experiment_name": experiment_name,
        "output_root": resolve_project_path(output_dir),
    }


def parse_rx_filter(value: str | None) -> list[str] | None:
    if value is None:
        return None
    selected = [item.strip() for item in value.split(",") if item.strip()]
    if not selected:
        raise SemanticAblationError("--rx-filter must contain at least one RX ID")
    return selected


def parse_models(value: str) -> list[str]:
    selected: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if not item:
            continue
        if item not in MODEL_CHOICES:
            raise SemanticAblationError(
                f"Unsupported model {item!r}. Supported models: {', '.join(MODEL_CHOICES)}"
            )
        if item not in selected:
            selected.append(item)
    if not selected:
        raise SemanticAblationError("--models must contain at least one supported model")
    return selected


def safe_slug(value: str) -> str:
    slug = []
    for char in value.strip().lower():
        if char.isalnum() or char == "_":
            slug.append(char)
        else:
            slug.append("_")
    text = "".join(slug).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or "value"


def output_suffix_for_rx_filter(rx_filter: list[str] | None) -> str:
    if not rx_filter:
        return "all_rx"
    if set(rx_filter) == {"rx_panda_base", "rx_ur5_base"} and len(rx_filter) == 2:
        return "panda_ur5"
    compact = []
    for rx_id in rx_filter:
        text = rx_id
        if text.startswith("rx_"):
            text = text[3:]
        if text.endswith("_base"):
            text = text[: -len("_base")]
        compact.append(safe_slug(text))
    return "_".join(compact)


def output_suffix_for_models(models: list[str]) -> str:
    if models == ["logistic"]:
        return ""
    return "_models_" + "_".join(models)


def load_feature_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise SemanticAblationError(
            "Missing feature CSV: "
            f"{path}. Run `python3 rt_out/scripts/exp_build_object_features.py "
            f"--config <experiment_config.json>` first for wide/compact mode, or "
            f"`python3 rt_out/scripts/exp_build_raw_occupancy_features.py "
            f"--config <experiment_config.json>` first for raw mode."
        ) from exc

    if not rows:
        raise SemanticAblationError(f"Object feature CSV is empty: {path}")
    return rows


def parse_binary_label(value: Any, label: str) -> int:
    if value is None:
        raise SemanticAblationError(f"{label} must be present")
    text = str(value).strip()
    if text in {"0", "0.0"}:
        return 0
    if text in {"1", "1.0"}:
        return 1
    raise SemanticAblationError(f"{label} must be binary 0/1, got {value!r}")


def parse_float_cell(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SemanticAblationError(f"{label} must be numeric, got {value!r}") from exc


def parse_int_cell(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SemanticAblationError(f"{label} must be an integer, got {value!r}") from exc


def filter_rows(rows: list[dict[str, str]], rx_filter: list[str] | None) -> list[dict[str, str]]:
    # RX filtering is optional so the same feature table can support the main
    # Panda+UR5 result and the broader all-RX diagnostic run.
    if rx_filter is None:
        return list(rows)
    selected = set(rx_filter)
    filtered = [row for row in rows if row.get("rx_id") in selected]
    if not filtered:
        raise SemanticAblationError(
            "No rows remain after applying --rx-filter: " + ",".join(rx_filter)
        )
    return filtered


def wide_feature_columns_from_header(header: list[str]) -> dict[str, list[str]]:
    # Wide mode is intentionally diagnostic: include all discovered feature
    # columns by prefix so we can inspect how broader feature families behave.
    geometry = sorted(column for column in header if column.startswith("geom_"))
    material = sorted(column for column in header if column.startswith("mat_"))
    semantic = sorted(column for column in header if column.startswith("sem_"))
    object_aware = sorted(column for column in header if column.startswith("obj_"))
    if not geometry:
        raise SemanticAblationError("No geometry feature columns were found")
    return {
        "majority_baseline": [],
        "geometry_only": geometry,
        "geometry_material": geometry + material,
        "geometry_semantic": geometry + semantic,
        "full_object_aware": geometry + material + semantic + object_aware,
    }


def compact_feature_columns_from_header(
    header: list[str],
) -> tuple[dict[str, list[str]], list[str]]:
    # Compact mode is paper-facing: request a smaller, defensible subset of
    # features that maps more directly to object masks/instances.
    header_set = set(header)
    feature_sets: dict[str, list[str]] = {"majority_baseline": []}
    missing_columns: list[str] = []
    for feature_set_name, requested_columns in COMPACT_FEATURE_COLUMNS.items():
        usable_columns = [column for column in requested_columns if column in header_set]
        feature_sets[feature_set_name] = usable_columns
        missing_columns.extend(column for column in requested_columns if column not in header_set)
    return feature_sets, sorted(set(missing_columns))


def raw_feature_columns_from_header(header: list[str]) -> dict[str, list[str]]:
    # Raw mode uses only unsegmented occupancy-style descriptors, with no
    # semantic/material/object-identity feature columns.
    raw_columns = sorted(column for column in header if column.startswith("raw_"))
    if not raw_columns:
        raise SemanticAblationError("No raw occupancy feature columns were found")
    return {
        "majority_baseline": [],
        "raw_occupancy": raw_columns,
    }


def resolve_feature_sets(
    header: list[str],
    *,
    feature_mode: str,
) -> tuple[list[str], dict[str, list[str]], list[str]]:
    if feature_mode == "wide":
        return WIDE_FEATURE_SET_ORDER, wide_feature_columns_from_header(header), []
    if feature_mode == "compact":
        feature_sets, missing_columns = compact_feature_columns_from_header(header)
        return COMPACT_FEATURE_SET_ORDER, feature_sets, missing_columns
    if feature_mode == "raw":
        return RAW_FEATURE_SET_ORDER, raw_feature_columns_from_header(header), []
    raise SemanticAblationError(f"Unsupported feature mode: {feature_mode}")


def validate_feature_sets(
    feature_sets: dict[str, list[str]],
    *,
    feature_set_order: list[str],
    feature_mode: str,
) -> None:
    for feature_set_name in feature_set_order:
        if feature_set_name == "majority_baseline":
            continue
        usable_columns = feature_sets.get(feature_set_name, [])
        if not usable_columns:
            raise SemanticAblationError(
                f"Feature set {feature_set_name!r} has zero usable columns in {feature_mode} mode"
            )


def load_optional_sklearn() -> dict[str, Any]:
    try:
        ensemble = importlib.import_module("sklearn.ensemble")
        neural_network = importlib.import_module("sklearn.neural_network")
        pipeline = importlib.import_module("sklearn.pipeline")
        preprocessing = importlib.import_module("sklearn.preprocessing")
        svm = importlib.import_module("sklearn.svm")
    except ImportError as exc:
        raise SemanticAblationError(
            "scikit-learn is required for models rf, svm, or mlp in this environment"
        ) from exc

    return {
        "RandomForestClassifier": ensemble.RandomForestClassifier,
        "MLPClassifier": neural_network.MLPClassifier,
        "Pipeline": pipeline.Pipeline,
        "StandardScaler": preprocessing.StandardScaler,
        "SVC": svm.SVC,
    }


def build_group_kfold_splits(groups: np.ndarray, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    unique_groups, counts = np.unique(groups, return_counts=True)
    if len(unique_groups) < 2:
        raise SemanticAblationError("Need at least two unique frame_id groups for grouped evaluation")
    n_splits = max(2, min(n_splits, len(unique_groups)))

    order = sorted(
        zip(unique_groups.tolist(), counts.tolist()),
        key=lambda item: (-item[1], item[0]),
    )
    fold_groups: list[set[int]] = [set() for _ in range(n_splits)]
    fold_sizes = [0] * n_splits
    for group_id, count in order:
        target_fold = min(range(n_splits), key=lambda index: (fold_sizes[index], index))
        fold_groups[target_fold].add(int(group_id))
        fold_sizes[target_fold] += int(count)

    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for group_set in fold_groups:
        test_mask = np.isin(groups, list(group_set))
        test_index = np.nonzero(test_mask)[0]
        train_index = np.nonzero(~test_mask)[0]
        if len(test_index) == 0 or len(train_index) == 0:
            continue
        splits.append((train_index, test_index))
    if len(splits) < 2:
        raise SemanticAblationError("Could not build at least two non-empty grouped folds")
    return splits


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-clipped))


class BalancedLogisticRegression:
    def __init__(self, *, reg_strength: float = 0.1, max_iter: int = 100, tol: float = 1e-6) -> None:
        self.reg_strength = reg_strength
        self.max_iter = max_iter
        self.tol = tol
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.weights_: np.ndarray | None = None
        self.constant_probability_: float | None = None

    def fit(self, features: np.ndarray, labels: np.ndarray) -> "BalancedLogisticRegression":
        num_rows, num_features = features.shape
        positives = int(np.sum(labels == 1))
        negatives = int(np.sum(labels == 0))
        if positives == 0 or negatives == 0:
            self.constant_probability_ = float(np.mean(labels))
            self.mean_ = np.zeros(num_features, dtype=float)
            self.scale_ = np.ones(num_features, dtype=float)
            self.weights_ = np.zeros(num_features + 1, dtype=float)
            return self

        self.mean_ = np.mean(features, axis=0)
        self.scale_ = np.std(features, axis=0)
        self.scale_[self.scale_ < 1e-9] = 1.0
        scaled = (features - self.mean_) / self.scale_
        design = np.concatenate([np.ones((num_rows, 1), dtype=float), scaled], axis=1)

        sample_weights = np.where(
            labels == 1,
            float(num_rows) / (2.0 * positives),
            float(num_rows) / (2.0 * negatives),
        )

        weights = np.zeros(design.shape[1], dtype=float)
        regularizer = np.eye(design.shape[1], dtype=float)
        regularizer[0, 0] = 0.0

        def loss_gradient_hessian(current: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
            probs = sigmoid(design @ current)
            eps = 1e-12
            loss_terms = -labels * np.log(probs + eps) - (1.0 - labels) * np.log(1.0 - probs + eps)
            loss = float(np.mean(sample_weights * loss_terms))
            loss += 0.5 * self.reg_strength * float(np.sum(current[1:] ** 2))

            residual = (probs - labels) * sample_weights
            gradient = (design.T @ residual) / num_rows
            gradient[1:] += self.reg_strength * current[1:]

            curvature = sample_weights * probs * (1.0 - probs)
            hessian = (design.T * curvature) @ design / num_rows
            hessian[1:, 1:] += self.reg_strength * np.eye(design.shape[1] - 1)
            return loss, gradient, hessian

        previous_loss: float | None = None
        for _ in range(self.max_iter):
            loss, gradient, hessian = loss_gradient_hessian(weights)
            hessian = hessian + 1e-8 * regularizer
            try:
                direction = np.linalg.solve(hessian, gradient)
            except np.linalg.LinAlgError:
                direction = np.linalg.pinv(hessian) @ gradient

            step_size = 1.0
            candidate = weights - step_size * direction
            candidate_loss, _, _ = loss_gradient_hessian(candidate)
            while candidate_loss > loss and step_size > 1e-6:
                step_size *= 0.5
                candidate = weights - step_size * direction
                candidate_loss, _, _ = loss_gradient_hessian(candidate)

            if candidate_loss > loss:
                candidate = weights - 0.05 * gradient
                candidate_loss, _, _ = loss_gradient_hessian(candidate)

            if np.max(np.abs(candidate - weights)) < self.tol:
                weights = candidate
                break
            if previous_loss is not None and abs(previous_loss - candidate_loss) < self.tol:
                weights = candidate
                break
            previous_loss = candidate_loss
            weights = candidate

        self.weights_ = weights
        self.constant_probability_ = None
        return self

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        if self.constant_probability_ is not None:
            return np.full(features.shape[0], self.constant_probability_, dtype=float)
        if self.mean_ is None or self.scale_ is None or self.weights_ is None:
            raise SemanticAblationError("BalancedLogisticRegression has not been fitted yet")
        scaled = (features - self.mean_) / self.scale_
        design = np.concatenate([np.ones((features.shape[0], 1), dtype=float), scaled], axis=1)
        return sigmoid(design @ self.weights_)


def balanced_sample_weights(labels: np.ndarray) -> np.ndarray:
    num_rows = int(labels.shape[0])
    positives = int(np.sum(labels == 1))
    negatives = int(np.sum(labels == 0))
    if positives == 0 or negatives == 0:
        return np.ones(num_rows, dtype=float)
    return np.where(
        labels == 1,
        float(num_rows) / (2.0 * positives),
        float(num_rows) / (2.0 * negatives),
    )


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    if y_true.shape != y_pred.shape:
        raise SemanticAblationError("Prediction shape mismatch")
    total = int(y_true.shape[0])
    true_positive = int(np.sum((y_true == 1) & (y_pred == 1)))
    true_negative = int(np.sum((y_true == 0) & (y_pred == 0)))
    false_positive = int(np.sum((y_true == 0) & (y_pred == 1)))
    false_negative = int(np.sum((y_true == 1) & (y_pred == 0)))

    accuracy = (true_positive + true_negative) / total if total else 0.0
    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
    specificity = true_negative / (true_negative + false_positive) if (true_negative + false_positive) else 0.0
    balanced_accuracy = 0.5 * (recall + specificity)
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def aggregate_metric_rows(metric_rows: list[dict[str, float]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for metric_name in ["accuracy", "balanced_accuracy", "precision", "recall", "f1"]:
        values = [row[metric_name] for row in metric_rows]
        mean_value = float(sum(values) / len(values)) if values else 0.0
        std_value = (
            float(math.sqrt(sum((value - mean_value) ** 2 for value in values) / len(values)))
            if values
            else 0.0
        )
        result[f"{metric_name}_mean"] = mean_value
        result[f"{metric_name}_std"] = std_value
    return result


def evaluate_majority_baseline(
    *,
    labels: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
) -> dict[str, float]:
    # Keep a no-feature baseline in every result file so the object-aware models
    # can be compared against the simplest possible grouped predictor.
    metric_rows: list[dict[str, float]] = []
    for train_index, test_index in splits:
        train_labels = labels[train_index]
        majority_label = 1 if float(np.mean(train_labels)) >= 0.5 else 0
        predictions = np.full(test_index.shape[0], majority_label, dtype=int)
        metric_rows.append(compute_metrics(labels[test_index], predictions))
    return aggregate_metric_rows(metric_rows)


def build_feature_matrix(
    *,
    rows: list[dict[str, str]],
    feature_columns: list[str],
) -> np.ndarray:
    return np.asarray(
        [
            [parse_float_cell(row.get(column), column) for column in feature_columns]
            for row in rows
        ],
        dtype=float,
    )


def evaluate_selected_model(
    *,
    model_name: str,
    feature_matrix: np.ndarray,
    labels: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
    sklearn_api: dict[str, Any] | None,
) -> dict[str, float]:
    # Evaluate one classical model across the grouped frame splits while keeping
    # frame_id groups intact across train/test boundaries.
    metric_rows: list[dict[str, float]] = []
    mlp_warned_unweighted = False

    for split_index, (train_index, test_index) in enumerate(splits):
        train_x = feature_matrix[train_index]
        test_x = feature_matrix[test_index]
        train_y = labels[train_index]
        test_y = labels[test_index]
        seed = 1000 + split_index

        if model_name == "logistic":
            model = BalancedLogisticRegression().fit(train_x, train_y)
            probabilities = model.predict_proba(test_x)
            predictions = (probabilities >= 0.5).astype(int)
        elif model_name == "rf":
            if sklearn_api is None:
                raise SemanticAblationError("Model rf requires scikit-learn")
            classifier = sklearn_api["RandomForestClassifier"](
                n_estimators=300,
                max_depth=None,
                min_samples_leaf=3,
                class_weight="balanced_subsample",
                random_state=seed,
            )
            classifier.fit(train_x, train_y)
            predictions = classifier.predict(test_x).astype(int)
        elif model_name == "svm":
            if sklearn_api is None:
                raise SemanticAblationError("Model svm requires scikit-learn")
            classifier = sklearn_api["Pipeline"](
                [
                    ("scaler", sklearn_api["StandardScaler"]()),
                    (
                        "svc",
                        sklearn_api["SVC"](
                            kernel="rbf",
                            class_weight="balanced",
                            C=1.0,
                            gamma="scale",
                        ),
                    ),
                ]
            )
            classifier.fit(train_x, train_y)
            predictions = classifier.predict(test_x).astype(int)
        elif model_name == "mlp":
            if sklearn_api is None:
                raise SemanticAblationError("Model mlp requires scikit-learn")
            classifier = sklearn_api["Pipeline"](
                [
                    ("scaler", sklearn_api["StandardScaler"]()),
                    (
                        "mlp",
                        sklearn_api["MLPClassifier"](
                            hidden_layer_sizes=(16,),
                            activation="relu",
                            alpha=1e-3,
                            max_iter=1000,
                            early_stopping=True,
                            random_state=seed,
                        ),
                    ),
                ]
            )
            sample_weights = balanced_sample_weights(train_y)
            try:
                classifier.fit(train_x, train_y, mlp__sample_weight=sample_weights)
            except TypeError:
                if not mlp_warned_unweighted:
                    print(
                        "warning: sklearn MLPClassifier sample_weight is not supported "
                        "in this environment; running unweighted MLP as diagnostic only"
                    )
                    mlp_warned_unweighted = True
                classifier.fit(train_x, train_y)
            except ValueError as exc:
                if "sample_weight" not in str(exc):
                    raise
                if not mlp_warned_unweighted:
                    print(
                        "warning: sklearn MLPClassifier sample_weight is not supported "
                        "in this environment; running unweighted MLP as diagnostic only"
                    )
                    mlp_warned_unweighted = True
                classifier.fit(train_x, train_y)
            predictions = classifier.predict(test_x).astype(int)
        else:
            raise SemanticAblationError(f"Unsupported model: {model_name}")

        metric_rows.append(compute_metrics(test_y, predictions))

    return aggregate_metric_rows(metric_rows)


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    config = load_experiment_config(args.config)
    rx_filter = parse_rx_filter(args.rx_filter)
    selected_models = parse_models(args.models)
    sklearn_api: dict[str, Any] | None = None
    if any(model_name in {"rf", "svm", "mlp"} for model_name in selected_models):
        sklearn_api = load_optional_sklearn()

    # Wide and compact modes reuse the object-aware feature table, while the raw
    # mode reads the class-agnostic vertex-occupancy baseline table.
    if args.feature_mode == "raw":
        features_path = config["output_root"] / "features" / "raw_occupancy_features_rt_labels.csv"
    else:
        features_path = config["output_root"] / "features" / "object_features_rt_labels.csv"
    # Load the prebuilt feature table. This script intentionally fails clearly if
    # the feature builder has not been run yet.
    rows = load_feature_rows(features_path)
    header = list(rows[0].keys())
    if args.target not in header:
        raise SemanticAblationError(
            f"Target column {args.target!r} is missing from {features_path}"
        )

    filtered_rows = filter_rows(rows, rx_filter)
    filtered_rows.sort(key=lambda row: (parse_int_cell(row.get("frame_id"), "frame_id"), row.get("rx_id", "")))
    positive_labels = [parse_binary_label(row.get(args.target), args.target) for row in filtered_rows]
    positive_count = int(sum(positive_labels))
    negative_count = int(len(filtered_rows) - positive_count)
    positive_ratio = float(sum(positive_labels) / len(positive_labels))
    unique_groups = sorted(
        {parse_int_cell(row.get("frame_id"), "frame_id") for row in filtered_rows}
    )
    if len(set(positive_labels)) < 2:
        raise SemanticAblationError(
            f"Target {args.target!r} is constant after filtering and cannot support ablation evaluation"
        )

    groups = np.asarray(
        [parse_int_cell(row.get("frame_id"), "frame_id") for row in filtered_rows],
        dtype=int,
    )
    # GroupKFold-style splitting by frame_id keeps all RX rows from the same
    # frame together, preventing leakage across train/test folds.
    splits = build_group_kfold_splits(groups, n_splits=5)
    feature_set_order, feature_sets, missing_compact_columns = resolve_feature_sets(
        header,
        feature_mode=args.feature_mode,
    )
    validate_feature_sets(
        feature_sets,
        feature_set_order=feature_set_order,
        feature_mode=args.feature_mode,
    )
    labels = np.asarray(positive_labels, dtype=int)

    print(f"experiment_name={config['experiment_name']}")
    print(f"target={args.target}")
    print(f"rx_filter={','.join(rx_filter) if rx_filter else 'all_rx'}")
    print(f"feature_mode={args.feature_mode}")
    print(f"models={','.join(selected_models)}")
    print(f"num_rows={len(filtered_rows)}")
    print(f"num_positive={positive_count}")
    print(f"num_negative={negative_count}")
    print(f"positive_ratio={positive_ratio:.6f}")
    print(f"num_groups={len(unique_groups)}")
    print(f"num_folds={len(splits)}")
    if args.feature_mode == "compact" and missing_compact_columns:
        print(
            "warning: missing compact feature columns: "
            + ", ".join(missing_compact_columns)
        )

    result_rows: list[dict[str, Any]] = []

    for feature_set_name in feature_set_order:
        # Evaluate each requested feature set independently so the resulting CSV
        # can serve directly as an ablation table.
        feature_columns = feature_sets[feature_set_name]
        print(f"{feature_set_name}_num_features={len(feature_columns)}")
        if feature_set_name == "majority_baseline":
            metrics = evaluate_majority_baseline(
                labels=labels,
                splits=splits,
            )
            result_row: dict[str, Any] = {
                "target": args.target,
                "rx_filter": ",".join(rx_filter) if rx_filter else "all_rx",
                "feature_set": feature_set_name,
                "num_rows": len(filtered_rows),
                "positive_ratio": positive_ratio,
                "model": "majority",
            }
            result_row.update(metrics)
            result_rows.append(result_row)
            print(
                f"{feature_set_name}: "
                f"num_features={len(feature_columns)}, "
                f"model=majority, "
                f"accuracy={metrics['accuracy_mean']:.4f} +/- {metrics['accuracy_std']:.4f}, "
                f"balanced_accuracy={metrics['balanced_accuracy_mean']:.4f} +/- {metrics['balanced_accuracy_std']:.4f}, "
                f"precision={metrics['precision_mean']:.4f} +/- {metrics['precision_std']:.4f}, "
                f"recall={metrics['recall_mean']:.4f} +/- {metrics['recall_std']:.4f}, "
                f"f1={metrics['f1_mean']:.4f} +/- {metrics['f1_std']:.4f}"
            )
            continue

        feature_matrix = build_feature_matrix(
            rows=filtered_rows,
            feature_columns=feature_columns,
        )
        for model_name in selected_models:
            metrics = evaluate_selected_model(
                model_name=model_name,
                feature_matrix=feature_matrix,
                labels=labels,
                splits=splits,
                sklearn_api=sklearn_api,
            )
            result_row = {
                "target": args.target,
                "rx_filter": ",".join(rx_filter) if rx_filter else "all_rx",
                "feature_set": feature_set_name,
                "num_rows": len(filtered_rows),
                "positive_ratio": positive_ratio,
                "model": model_name,
            }
            result_row.update(metrics)
            result_rows.append(result_row)
            print(
                f"{feature_set_name}: "
                f"num_features={len(feature_columns)}, "
                f"model={model_name}, "
                f"accuracy={metrics['accuracy_mean']:.4f} +/- {metrics['accuracy_std']:.4f}, "
                f"balanced_accuracy={metrics['balanced_accuracy_mean']:.4f} +/- {metrics['balanced_accuracy_std']:.4f}, "
                f"precision={metrics['precision_mean']:.4f} +/- {metrics['precision_std']:.4f}, "
                f"recall={metrics['recall_mean']:.4f} +/- {metrics['recall_std']:.4f}, "
                f"f1={metrics['f1_mean']:.4f} +/- {metrics['f1_std']:.4f}"
            )

    output_suffix = output_suffix_for_rx_filter(rx_filter)
    output_name = f"semantic_ablation_results_{safe_slug(args.target)}_{output_suffix}.csv"
    if args.feature_mode == "compact":
        output_name = f"semantic_ablation_results_compact_{safe_slug(args.target)}_{output_suffix}.csv"
    elif args.feature_mode == "raw":
        output_name = f"semantic_ablation_results_raw_{safe_slug(args.target)}_{output_suffix}.csv"
    model_suffix = output_suffix_for_models(selected_models)
    if model_suffix:
        if args.feature_mode == "compact":
            output_name = (
                f"semantic_ablation_results_compact_{safe_slug(args.target)}_"
                f"{output_suffix}{model_suffix}.csv"
            )
        elif args.feature_mode == "raw":
            output_name = (
                f"semantic_ablation_results_raw_{safe_slug(args.target)}_"
                f"{output_suffix}{model_suffix}.csv"
            )
        else:
            output_name = (
                f"semantic_ablation_results_{safe_slug(args.target)}_"
                f"{output_suffix}{model_suffix}.csv"
            )
    output_path = config["output_root"] / "results" / output_name
    write_results(output_path, result_rows)
    print(f"output_csv={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
