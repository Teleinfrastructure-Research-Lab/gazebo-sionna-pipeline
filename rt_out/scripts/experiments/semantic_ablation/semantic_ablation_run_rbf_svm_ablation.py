#!/usr/bin/env python3
"""Leakage-safe exact RBF-SVM temporal ablations on descriptor-v2 features."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from release_hardening import (
    InventoryValidationError,
    ManifestConflictError,
    atomic_json as atomic_release_json,
    atomic_promote_files,
    canonical_manifest_payload,
    collect_run_inventory,
    installed_versions,
    invocation_manifest_payload,
    new_invocation_id,
    source_hashes,
    validate_run_invocation_binding,
    validate_existing_manifest,
    write_canonical_manifest,
    write_invocation_manifest,
)

RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
TASKS = ('beam_reselection_1db_1s', 'y_path_change', 'y_adaptation_trigger_1db')
VIEWS = ('CTX', 'G', 'GS', 'GI', 'GSI')
MODEL = 'rbf_svm'
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
VERSION = 'classical_ml_rbf_svm_v1'
N_ROWS = 14616
SPLITS = {'train': 10170, 'excluded': 120, 'test': 4326}
SEED = 42
GAP = 10
GRID = ({'C': 0.01, 'gamma': 'scale'}, {'C': 0.1, 'gamma': 'scale'}, {'C': 1.0, 'gamma': 'scale'}, {'C': 10.0, 'gamma': 'scale'})
PREDICTION_FIELDS = ['row_index', 'source_frame_id', 'rx_id', 'split', 'y_true', 'score', 'y_pred_default', 'y_pred_selected']
OOF_FIELDS = ['row_index', 'source_frame_id', 'rx_id', 'fold', 'y_true', 'score']


class Error(RuntimeError):
    pass


def require_sklearn() -> None:
    global SVC, VarianceThreshold, average_precision_score, balanced_accuracy_score
    global confusion_matrix, f1_score, precision_recall_curve, precision_score
    global recall_score, roc_auc_score, Pipeline, StandardScaler, ConvergenceWarning
    try:
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.feature_selection import VarianceThreshold
        from sklearn.metrics import (average_precision_score, balanced_accuracy_score,
                                     confusion_matrix, f1_score, precision_recall_curve,
                                     precision_score, recall_score, roc_auc_score)
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVC
    except ImportError as exc:
        raise Error('scikit-learn is required to run RBF-SVM experiments') from exc


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def config_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def execution_source_hashes() -> dict[str, str]:
    return source_hashes(
        (Path(__file__).resolve(), Path(__file__).with_name('release_hardening.py')),
        project_root=REPOSITORY_ROOT,
    )


def normalize_cli_args(value: Any) -> Any:
    if isinstance(value, Path):
        if value.is_absolute():
            try:
                return str(value.resolve().relative_to(REPOSITORY_ROOT))
            except ValueError:
                return '<external-path>'
        return str(value)
    if isinstance(value, dict):
        return {str(key): normalize_cli_args(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_cli_args(item) for item in value]
    return value


def scientific_configuration() -> dict[str, Any]:
    return {
        'tasks': list(TASKS), 'views': list(VIEWS), 'models': [MODEL],
        'rows': N_ROWS, 'splits': SPLITS, 'temporal_gap': GAP,
        'excluded_rows_never_used': True, 'family': MODEL,
    }


def canonical_manifest_for(data: Data) -> dict[str, Any]:
    return canonical_manifest_payload(
        experiment_identity={'experiment_name': data.exp.parent.name, 'run_id': data.exp.name, 'model_family': MODEL},
        expected_jobs=[(task, view, MODEL) for task in TASKS for view in VIEWS], input_hashes=data.input_hashes,
        scientific_configuration=scientific_configuration(), implementation_version=VERSION, seed=SEED,
    )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


def atomic_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def canonical() -> list[tuple[str, str]]:
    return [(str(frame), rx) for frame in range(2436) for rx in RX]


class Data:
    """Published descriptor-v2 inputs, verified before any model fitting."""

    def __init__(self, root: Path, experiment_root: Path | None = None):
        self.root = root.resolve()
        self.exp = (experiment_root or (self.root / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015')).resolve()
        self.desc = self.exp / 'features/classical_ml_descriptor_v2'
        self.targets_path = self.exp / 'beam_results/canonical_4x4_dft16/supervised_targets_horizon10.csv'
        required = {view: self.desc / f'{view}.npy' for view in ('G', 'GS', 'GI', 'GSI')}
        required.update({
            'link_context': self.desc / 'link_context.npy',
            'current_beam_onehot': self.desc / 'current_beam_onehot.npy',
            'row_index': self.desc / 'row_index.csv',
            'schema': self.desc / 'descriptor_schema.json',
            'validation': self.desc / 'validation_summary.json',
            'targets': self.targets_path,
        })
        if any(not path.is_file() for path in required.values()):
            raise Error('missing published descriptor-v2 input artifact')
        self.paths = required
        self.schema = json.loads(required['schema'].read_text())
        self.validation = json.loads(required['validation'].read_text())
        if self.validation.get('passed') is not True or self.validation.get('published') is not True or self.validation.get('rows') != N_ROWS:
            raise Error('descriptor validation summary is not a published PASS')
        expected_dimensions = {'G': 65, 'GS': 1430, 'GI': 715, 'GSI': 2080}
        if {name: int(self.schema['views'][name]['dimension']) for name in expected_dimensions} != expected_dimensions:
            raise Error('descriptor schema dimensions invalid')
        for key in ('G', 'GS', 'GI', 'GSI', 'link_context', 'current_beam_onehot', 'row_index', 'schema'):
            expected_hash = self.validation.get('output_hashes', {}).get(key)
            if expected_hash is None or sha(required[key]) != expected_hash:
                raise Error(f'descriptor output hash mismatch: {key}')
        if self.validation.get('input_hashes', {}).get('supervised_targets') != sha(required['targets']):
            raise Error('supervised target hash mismatch against descriptor validation manifest')
        names = ('G', 'GS', 'GI', 'GSI', 'link_context', 'current_beam_onehot')
        self.arrays = {name: np.load(required[name], mmap_mode='r', allow_pickle=False) for name in names}
        for view, dimension in expected_dimensions.items():
            array = self.arrays[view]
            if array.shape != (N_ROWS, dimension) or not np.isfinite(array).all():
                raise Error(f'descriptor array contract failure: {view}')
        context, beam = self.arrays['link_context'], self.arrays['current_beam_onehot']
        if context.shape != (N_ROWS, 16) or beam.shape != (N_ROWS, 16) or not np.isfinite(context).all() or not np.array_equal(beam.sum(1), np.ones(N_ROWS, dtype=np.float32)) or not np.isin(beam, (0, 1)).all():
            raise Error('context array contract failure')
        self.rows = read_csv(required['row_index'])
        targets = read_csv(required['targets'])
        if len(self.rows) != N_ROWS or len(targets) != N_ROWS:
            raise Error('row-index/target row count failure')
        if [(row.get('source_frame_id'), row.get('rx_id')) for row in self.rows] != canonical() or [(row.get('source_frame_id'), row.get('rx_id')) for row in targets] != canonical():
            raise Error('non-canonical row ordering')
        if Counter(row['split'] for row in self.rows) != SPLITS or any(row['split'] != target['split'] for row, target in zip(self.rows, targets, strict=True)):
            raise Error('split join mismatch')
        for index, row in enumerate(self.rows):
            if int(row['row_index']) != index or int(row['source_frame_id']) != index // 6 or row['rx_id'] != RX[index % 6]:
                raise Error('row index is not frame-major/RX-minor')
        self.source = np.asarray([int(row['source_frame_id']) for row in self.rows], dtype=np.int32)
        self.rx = np.asarray([row['rx_id'] for row in self.rows])
        self.split = np.asarray([row['split'] for row in self.rows])
        self.y = {task: np.asarray([int(row[task]) for row in targets], dtype=np.int8) for task in TASKS}
        frame_sets = {split: set(self.source[self.split == split].tolist()) for split in SPLITS}
        if any(frame_sets[left] & frame_sets[right] for left, right in (('train', 'excluded'), ('train', 'test'), ('excluded', 'test'))):
            raise Error('source frame appears in more than one split')
        if any(not np.isin(labels, (0, 1)).all() for labels in self.y.values()):
            raise Error('non-binary target labels')
        if np.any((self.split == 'train') & (self.source > 1694)) or np.any((self.split == 'excluded') & ((self.source < 1695) | (self.source > 1714))) or np.any((self.split == 'test') & (self.source < 1715)):
            raise Error('chronological split frame contract failure')
        self.input_hashes = {key: sha(path) for key, path in required.items()}

    def features(self, task: str, view: str) -> np.ndarray:
        context = np.asarray(self.arrays['link_context'], dtype=np.float32)
        if task == 'beam_reselection_1db_1s':
            context = np.concatenate((context, np.asarray(self.arrays['current_beam_onehot'], dtype=np.float32)), axis=1)
        if view == 'CTX':
            return context
        return np.concatenate((np.asarray(self.arrays[view], dtype=np.float32), context), axis=1)


def folds(data: Data, task: str) -> tuple[list[dict[str, Any]], list[tuple[np.ndarray, np.ndarray]]]:
    frame_ids = np.arange(1695, dtype=np.int32)
    # Equivalent to TimeSeriesSplit(n_splits=3, gap=10) on the 1695 train frames.
    test_size = len(frame_ids) // 4
    pairs = [
        (np.arange(len(frame_ids) - (3 - number) * test_size - GAP),
         np.arange(len(frame_ids) - (3 - number) * test_size, len(frame_ids) - (2 - number) * test_size))
        for number in range(3)
    ]
    metadata, mapped = [], []
    for fold, (train_index, validation_index) in enumerate(pairs):
        train_frames, validation_frames = frame_ids[train_index], frame_ids[validation_index]
        if set(train_frames) & set(validation_frames) or int(validation_frames.min()) - int(train_frames.max()) - 1 < GAP:
            raise Error('temporal CV frame overlap/gap violation')
        train_rows = np.flatnonzero(np.isin(data.source, train_frames) & (data.split == 'train'))
        validation_rows = np.flatnonzero(np.isin(data.source, validation_frames) & (data.split == 'train'))
        if len(train_rows) != len(train_frames) * 6 or len(validation_rows) != len(validation_frames) * 6 or not np.any(data.y[task][validation_rows] == 1):
            raise Error(f'fold {fold} has invalid rows or no validation positives')
        metadata.append({
            'fold': fold,
            'train_frame_range': [int(train_frames.min()), int(train_frames.max())],
            'validation_frame_range': [int(validation_frames.min()), int(validation_frames.max())],
            'gap_source_frames': int(validation_frames.min() - train_frames.max() - 1),
            'train_frames': len(train_frames), 'validation_frames': len(validation_frames),
            'train_rows': len(train_rows), 'validation_rows': len(validation_rows),
            'train_positive': int(data.y[task][train_rows].sum()),
            'validation_positive': int(data.y[task][validation_rows].sum()),
        })
        mapped.append((train_rows, validation_rows))
    return metadata, mapped


def feature_construction(task: str, view: str) -> dict[str, Any]:
    context = ['link_context']
    if task == 'beam_reselection_1db_1s':
        context.append('current_beam_onehot')
    return {'view': view, 'descriptor': None if view == 'CTX' else view, 'context': context}


def pipeline(params: dict[str, Any]) -> Pipeline:
    estimator = SVC(kernel='rbf', C=params['C'], gamma=params['gamma'], class_weight='balanced', probability=False, cache_size=2048, shrinking=True, tol=1e-3, max_iter=-1, random_state=SEED)
    return Pipeline([('variance', VarianceThreshold()), ('scale', StandardScaler()), ('model', estimator)])


def fit_model(fitted: Pipeline, features: np.ndarray, labels: np.ndarray) -> tuple[dict[str, Any], np.ndarray | None]:
    started = time.monotonic()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', ConvergenceWarning)
        fitted.fit(features, labels)
    estimator = fitted.named_steps['model']
    scores = np.asarray(fitted.decision_function(features), dtype=np.float64)
    warning_messages = [str(item.message) for item in caught]
    convergence_warning = any(issubclass(item.category, ConvergenceWarning) for item in caught)
    fit_status = int(estimator.fit_status_)
    finite_scores = bool(np.isfinite(scores).all())
    details = {
        'runtime_seconds': time.monotonic() - started,
        'n_iter': int(np.max(np.asarray(estimator.n_iter_))),
        'fit_status': fit_status,
        'support_vector_count': int(np.asarray(estimator.support_).size),
        'support_vectors_per_class': [int(value) for value in np.asarray(estimator.n_support_)],
        'warnings': warning_messages,
        'convergence_warning': convergence_warning,
        'scores_finite': finite_scores,
        'converged': bool(fit_status == 0 and not convergence_warning and finite_scores),
    }
    return details, scores if finite_scores else None


def choose_threshold(labels: np.ndarray, scores: np.ndarray) -> tuple[float, dict[str, float]]:
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-15)
    best = np.flatnonzero(np.isclose(f1, f1.max()))
    index = best[np.argmax(recall[best])]
    ties = best[np.isclose(recall[best], recall[index])]
    index = ties[np.argmin(thresholds[ties])]
    return float(thresholds[index]), {'oof_f1': float(f1[index]), 'oof_precision': float(precision[index]), 'oof_recall': float(recall[index])}


def metrics(labels: np.ndarray, scores: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    matrix = confusion_matrix(labels, prediction, labels=(0, 1))
    single_class = len(np.unique(labels)) != 2
    prevalence = float(labels.mean())
    ap = None if single_class else float(average_precision_score(labels, scores))
    return {
        'rows': int(len(labels)), 'positive_count': int(labels.sum()), 'positive_prevalence': prevalence,
        'average_precision': ap,
        'average_precision_lift': None if single_class else ap - prevalence,
        'average_precision_ratio': None if single_class or prevalence == 0 else ap / prevalence,
        'f1': float(f1_score(labels, prediction, zero_division=0)),
        'precision': float(precision_score(labels, prediction, zero_division=0)),
        'recall': float(recall_score(labels, prediction, zero_division=0)),
        'balanced_accuracy': None if single_class else float(balanced_accuracy_score(labels, prediction)),
        'roc_auc': None if single_class else float(roc_auc_score(labels, scores)),
        'single_class_y_true': single_class, 'confusion_matrix': matrix.tolist(),
    }


def baselines(data: Data, task: str, test_rows: np.ndarray) -> dict[str, Any]:
    train_rows = np.flatnonzero(data.split == 'train')
    train_labels, test_labels = data.y[task][train_rows], data.y[task][test_rows]
    zeros = np.zeros(len(test_rows), dtype=np.int8)
    global_label = int(train_labels.mean() >= 0.5)
    per_rx = {rx: int(train_labels[data.rx[train_rows] == rx].mean() >= 0.5) for rx in RX}
    rx_prediction = np.asarray([per_rx[rx] for rx in data.rx[test_rows]], dtype=np.int8)
    return {
        'always_negative': metrics(test_labels, zeros, zeros),
        'global_train_majority': {'train_label': global_label, 'metrics': metrics(test_labels, np.full(len(test_rows), global_label), np.full(len(test_rows), global_label))},
        'train_only_per_rx_majority': {'train_labels': per_rx, 'metrics': metrics(test_labels, rx_prediction, rx_prediction)},
    }


def paths_for(out: Path, task: str, view: str) -> dict[str, Path]:
    return {
        'run': out / 'runs' / task / view / f'{MODEL}.json',
        'prediction': out / 'predictions' / task / view / f'{MODEL}.csv',
        'oof': out / 'oof_predictions' / task / view / f'{MODEL}.csv',
    }


def identity(data: Data, task: str, view: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[np.ndarray, np.ndarray]]]:
    fold_meta, fold_rows = folds(data, task)
    payload = {
        'script_version': VERSION,
        'script_sha256': sha(Path(__file__).resolve()),
        'execution_source_hashes': execution_source_hashes(),
        'input_artifact_hashes': data.input_hashes,
        'task': task, 'view': view, 'model': MODEL,
        'feature_construction': feature_construction(task, view),
        'feature_dimension': int(data.features(task, view).shape[1]),
        'cv_folds': fold_meta,
        'preprocessing': ['VarianceThreshold', 'StandardScaler', 'SVC(kernel=rbf)'],
        'svc_configuration': {'kernel': 'rbf', 'class_weight': 'balanced', 'probability': False, 'cache_size': 2048, 'shrinking': True, 'tol': 1e-3, 'max_iter': -1, 'random_state': SEED},
        'hyperparameter_grid': list(GRID),
        'selection_metric': 'average_precision',
        'threshold_selection_policy': 'maximize OOF F1; ties higher recall then lower threshold',
        'random_seed': SEED,
    }
    return payload, fold_meta, fold_rows


def validate_completed(
    data: Data,
    out: Path,
    task: str,
    view: str,
    *,
    check_invocation_binding: bool = True,
) -> dict[str, Any]:
    artifact = paths_for(out, task, view)
    if any(not path.is_file() for path in artifact.values()):
        raise Error('incomplete run artifacts')
    run = json.loads(artifact['run'].read_text())
    payload, _, fold_rows = identity(data, task, view)
    if run.get('run_schema_version') != VERSION or run.get('configuration') != payload or run.get('configuration_sha256') != config_hash(payload):
        raise Error('configuration-mismatched run')
    if run.get('prediction_sha256') != sha(artifact['prediction']) or run.get('oof_prediction_sha256') != sha(artifact['oof']):
        raise Error('run artifact hash mismatch')
    if check_invocation_binding:
        try:
            validate_run_invocation_binding(
                out,
                run,
                (task, view, MODEL),
                expected_execution_source_hashes=execution_source_hashes(),
                expected_dependency_versions=installed_versions(('numpy', 'scikit-learn')),
            )
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
    selected = [entry for entry in run.get('config_grid', []) if entry.get('params') == run.get('selected_hyperparameters')]
    if len(selected) != 1 or selected[0].get('converged') is not True or run.get('selected_configuration_converged') is not True or run.get('final_fit', {}).get('converged') is not True:
        raise Error('selected configuration/final fit is not converged')
    if any(not bool(entry.get('scores_finite')) for entry in selected[0].get('fold_fits', [])) or not bool(run['final_fit'].get('scores_finite')):
        raise Error('selected configuration has non-finite scores')
    prediction = read_csv(artifact['prediction'])
    expected_test = np.flatnonzero(data.split == 'test')
    if len(prediction) != 4326 or [(int(row['row_index']), row['rx_id'], row['split']) for row in prediction] != [(int(index), str(data.rx[index]), 'test') for index in expected_test]:
        raise Error('prediction CSV is not canonical 4326-row test output')
    if any(int(row['source_frame_id']) != int(data.source[int(row['row_index'])]) or int(row['y_true']) != int(data.y[task][int(row['row_index'])]) or not math.isfinite(float(row['score'])) for row in prediction):
        raise Error('prediction label/identifier/score mismatch')
    oof = read_csv(artifact['oof'])
    fold_by_row = {int(index): fold for fold, (_, validation) in enumerate(fold_rows) for index in validation}
    if [int(row['row_index']) for row in oof] != sorted(fold_by_row) or len(oof) != len(fold_by_row):
        raise Error('OOF CSV row ordering/count failure')
    for row in oof:
        index = int(row['row_index'])
        if index not in fold_by_row or int(row['fold']) != fold_by_row[index] or row['rx_id'] != data.rx[index] or int(row['y_true']) != int(data.y[task][index]) or data.split[index] != 'train' or not math.isfinite(float(row['score'])):
            raise Error('OOF CSV includes non-validation, excluded, or invalid rows')
    if run.get('threshold_selection_source') != 'train_only_oof_predictions' or int(run.get('oof_rows', -1)) != len(oof) or int(run.get('test_rows', -1)) != 4326:
        raise Error('threshold source or result row-count contract failed')
    return run


def aggregate_results(data: Data, out: Path, *, require_complete: bool = False) -> dict[str, Any]:
    expected = {(task, view) for task in TASKS for view in VIEWS}
    manifest_path = out / 'experiment_manifest.json'
    if not manifest_path.is_file():
        raise Error(f'canonical experiment manifest is missing: {manifest_path}')
    validate_existing_manifest(manifest_path, canonical_manifest_for(data))
    paths = sorted((out / 'runs').glob('*/*/*.json')) if (out / 'runs').is_dir() else []
    try:
        report, accepted = collect_run_inventory(
            paths,
            expected=expected,
            identity_fields=('task', 'view'),
            validator=lambda identity, payload, path: validate_completed(data, out, *identity),
            fail_closed=require_complete,
            scope='model_family',
        )
    except InventoryValidationError as exc:
        invalid = {**exc.report, 'aggregation_complete': False, 'release_ready': False, 'status': 'INCOMPLETE'}
        atomic_release_json(out / 'aggregation_validation.json', invalid)
        raise Error(f"release aggregation failed closed: {exc}") from exc
    report['aggregation_complete'] = bool(report['passed'])
    report['release_ready'] = bool(report['passed'])
    report['status'] = 'PASS' if report['aggregation_complete'] else 'INCOMPLETE'
    if not report['passed']:
        atomic_release_json(out / 'aggregation_validation.json', report)
        return report
    valid = list(accepted.values())
    summaries, per_rx, selected = [], [], {}
    for run in valid:
        key = f"{run['task']}/{run['view']}/{MODEL}"
        selected[key] = {'hyperparameters': run['selected_hyperparameters'], 'threshold': run['selected_threshold'], 'mean_validation_average_precision': run['selected_mean_validation_average_precision'], 'warnings': run['warnings']}
        summaries.append({
            'task': run['task'], 'view': run['view'], 'model': MODEL,
            'feature_dimension': run['feature_dimension'],
            'mean_validation_average_precision': run['selected_mean_validation_average_precision'],
            'selected_threshold': run['selected_threshold'],
            'selected_converged': run['selected_configuration_converged'],
            **{f'test_{name}': value for name, value in run['test_selected_threshold'].items() if name != 'confusion_matrix'},
        })
        per_rx.extend(run['per_rx_metrics'])
    if not summaries or not per_rx:
        report['aggregation_complete'] = False
        report['release_ready'] = False
        report['status'] = 'INCOMPLETE'
        atomic_release_json(out / 'aggregation_validation.json', report)
        return report
    with tempfile.TemporaryDirectory(prefix='rbf_aggregate_', dir=out.parent) as temporary:
        stage = Path(temporary)
        atomic_csv(stage / 'run_summary.csv', list(summaries[0]), summaries)
        atomic_csv(stage / 'per_rx_metrics.csv', list(per_rx[0]), per_rx)
        atomic_json(stage / 'selected_hyperparameters.json', selected)
        report['aggregate_file_hashes'] = {
            name: sha(stage / name)
            for name in ('run_summary.csv', 'per_rx_metrics.csv', 'selected_hyperparameters.json')
        }
        atomic_release_json(stage / 'aggregation_validation.json', report)
        atomic_promote_files({
            stage / name: out / name
            for name in ('run_summary.csv', 'per_rx_metrics.csv', 'selected_hyperparameters.json', 'aggregation_validation.json')
        })
    return report


def run_one(
    data: Data,
    task: str,
    view: str,
    out: Path,
    job_number: int,
    total_jobs: int,
    invocation_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    features = data.features(task, view)
    train_rows = np.flatnonzero(data.split == 'train')
    test_rows = np.flatnonzero(data.split == 'test')
    payload, fold_meta, fold_rows = identity(data, task, view)
    results = []
    for configuration_number, params in enumerate(GRID, start=1):
        configuration_started = time.monotonic()
        scores = np.full(N_ROWS, np.nan, dtype=np.float64)
        fold_ids = np.full(N_ROWS, -1, dtype=np.int8)
        fold_fits, fold_ap = [], []
        for fold_number, (fold_train, fold_validation) in enumerate(fold_rows, start=1):
            print(f'[rbf-svm] job={job_number}/{total_jobs} task={task} view={view} status=created config={configuration_number}/{len(GRID)} fold={fold_number}/3 elapsed_seconds={time.monotonic() - started:.3f}', flush=True)
            fitted = pipeline(params)
            details, validation_scores = fit_model(fitted, features[fold_train], data.y[task][fold_train])
            # Scores must be evaluated on the validation fold, not the fold-training data.
            if details['converged']:
                validation_scores = np.asarray(fitted.decision_function(features[fold_validation]), dtype=np.float64)
                details['scores_finite'] = bool(np.isfinite(validation_scores).all())
                details['converged'] = bool(details['converged'] and details['scores_finite'])
            if validation_scores is not None and details['scores_finite']:
                scores[fold_validation], fold_ids[fold_validation] = validation_scores, fold_number - 1
                fold_ap.append(float(average_precision_score(data.y[task][fold_validation], validation_scores)))
            else:
                fold_ap.append(None)
            fold_fits.append(details)
        converged = bool(all(item['converged'] for item in fold_fits))
        results.append({
            'params': dict(params), 'converged': converged, 'fold_fits': fold_fits,
            'fold_average_precision': fold_ap,
            'mean_validation_average_precision': float(np.mean(fold_ap)) if converged else None,
            'configuration_runtime_seconds': time.monotonic() - configuration_started,
            'oof_scores': scores, 'fold_ids': fold_ids,
        })
    valid = [result for result in results if result['converged']]
    if not valid:
        raise Error('all RBF-SVM configurations failed fit-status, warning, or finite-score validation')
    best = max(valid, key=lambda result: result['mean_validation_average_precision'])
    oof_rows = np.flatnonzero(np.isfinite(best['oof_scores']))
    threshold, threshold_info = choose_threshold(data.y[task][oof_rows], best['oof_scores'][oof_rows])
    final = pipeline(best['params'])
    final_fit, _ = fit_model(final, features[train_rows], data.y[task][train_rows])
    if not final_fit['converged']:
        raise Error('selected RBF-SVM configuration failed final fit validation')
    test_scores = np.asarray(final.decision_function(features[test_rows]), dtype=np.float64)
    final_fit['scores_finite'] = bool(np.isfinite(test_scores).all())
    final_fit['converged'] = bool(final_fit['converged'] and final_fit['scores_finite'])
    if not final_fit['converged']:
        raise Error('selected RBF-SVM configuration produced non-finite test scores')
    default_prediction = (test_scores >= 0.0).astype(np.int8)
    selected_prediction = (test_scores >= threshold).astype(np.int8)
    test_labels, per_rx = data.y[task][test_rows], []
    for rx in RX:
        mask = data.rx[test_rows] == rx
        for threshold_type, prediction in (('default', default_prediction), ('selected', selected_prediction)):
            per_rx.append({'task': task, 'view': view, 'model': MODEL, 'threshold_type': threshold_type, 'rx_id': rx, **metrics(test_labels[mask], test_scores[mask], prediction[mask])})
    prediction_rows = [
        {'row_index': int(index), 'source_frame_id': int(data.source[index]), 'rx_id': str(data.rx[index]), 'split': 'test', 'y_true': int(data.y[task][index]), 'score': float(score), 'y_pred_default': int(default), 'y_pred_selected': int(selected)}
        for index, score, default, selected in zip(test_rows, test_scores, default_prediction, selected_prediction, strict=True)
    ]
    oof_csv = [
        {'row_index': int(index), 'source_frame_id': int(data.source[index]), 'rx_id': str(data.rx[index]), 'fold': int(best['fold_ids'][index]), 'y_true': int(data.y[task][index]), 'score': float(best['oof_scores'][index])}
        for index in oof_rows
    ]
    artifact = paths_for(out, task, view)
    atomic_csv(artifact['prediction'], PREDICTION_FIELDS, prediction_rows)
    atomic_csv(artifact['oof'], OOF_FIELDS, oof_csv)
    warnings_out = []
    if best['params']['C'] in (GRID[0]['C'], GRID[-1]['C']):
        warnings_out.append('selected_C_is_grid_boundary')
        print(f'[rbf-svm] warning task={task} view={view} selected_C={best["params"]["C"]} is a grid boundary', flush=True)
    run = {
        'run_schema_version': VERSION, 'configuration': payload, 'configuration_sha256': config_hash(payload),
        'task': task, 'view': view, 'model': MODEL, 'feature_dimension': int(features.shape[1]), 'random_seed': SEED,
        'cv_folds': fold_meta,
        'config_grid': [{key: value for key, value in result.items() if key not in ('oof_scores', 'fold_ids')} for result in results],
        'selected_hyperparameters': best['params'], 'selected_mean_validation_average_precision': best['mean_validation_average_precision'],
        'selected_threshold': threshold, 'threshold_selection': threshold_info, 'threshold_selection_source': 'train_only_oof_predictions',
        'default_threshold': 0.0, 'oof_rows': int(len(oof_rows)), 'test_rows': int(len(test_rows)),
        'test_default_threshold': metrics(test_labels, test_scores, default_prediction),
        'test_selected_threshold': metrics(test_labels, test_scores, selected_prediction),
        'baselines': baselines(data, task, test_rows), 'per_rx_metrics': per_rx, 'warnings': warnings_out,
        'selected_configuration_converged': best['converged'], 'final_fit': final_fit,
        'runtime_seconds': time.monotonic() - started,
        'prediction_sha256': sha(artifact['prediction']), 'oof_prediction_sha256': sha(artifact['oof']),
    }
    run.update(invocation_metadata or {})
    atomic_json(artifact['run'], run)
    return run


def input_validation(data: Data) -> dict[str, Any]:
    return {
        'passed': True, 'rows': N_ROWS, 'split_rows': dict(Counter(data.split)),
        'descriptor_dimensions': {view: int(data.arrays[view].shape[1]) for view in ('G', 'GS', 'GI', 'GSI')},
        'feature_dimensions': {task: {view: int(data.features(task, view).shape[1]) for view in VIEWS} for task in TASKS},
        'temporal_cv_folds': {task: folds(data, task)[0] for task in TASKS}, 'input_hashes': data.input_hashes,
    }


def validate_results(
    data: Data,
    out: Path,
    expected_jobs: list[tuple[str, str]] | None = None,
    *,
    scope: str = 'model_family',
) -> dict[str, Any]:
    if scope == 'single_job':
        if not expected_jobs or len(expected_jobs) != 1:
            raise Error('single_job validation requires exactly one task/view identity')
        expected = {tuple(expected_jobs[0])}
        manifest_path = out / 'experiment_manifest.json'
        if not manifest_path.is_file():
            raise Error(f'single_job validation requires a canonical experiment manifest: {manifest_path}')
        try:
            validate_existing_manifest(manifest_path, canonical_manifest_for(data))
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
        paths = [paths_for(out, *expected_jobs[0])['run']]
    elif scope == 'model_family':
        manifest_path = out / 'experiment_manifest.json'
        if not manifest_path.is_file():
            raise Error(f'model_family validation requires a canonical experiment manifest: {manifest_path}')
        try:
            validate_existing_manifest(manifest_path, canonical_manifest_for(data))
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
        expected = {(task, view) for task in TASKS for view in VIEWS}
        paths = sorted((out / 'runs').glob('*/*/*.json')) if (out / 'runs').is_dir() else []
    else:
        raise Error('combined_release validation is provided by --validate-combined')
    report, accepted = collect_run_inventory(
        paths,
        expected=expected,
        identity_fields=('task', 'view'),
        validator=lambda identity, payload, path: validate_completed(data, out, *identity),
        fail_closed=True,
        scope=scope,
    )
    return {'passed': True, 'output_root': str(out), **report, 'run_identities': sorted(f'{run["task"]}/{run["view"]}/{MODEL}' for run in accepted.values())}


def write_validation_summary(data: Data, out: Path, expected_jobs: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    summary = input_validation(data)
    try:
        summary['result_validation'] = validate_results(data, out, expected_jobs)
    except (Error, InventoryValidationError) as exc:
        summary['result_validation'] = {'passed': False, 'error': str(exc)}
        if isinstance(exc, InventoryValidationError):
            summary['result_validation']['report'] = exc.report
    atomic_json(out / 'validation_summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--experiment-root', type=Path, help='Run root containing features/, beam_results/, and results/.')
    parser.add_argument('--task', choices=TASKS)
    parser.add_argument('--view', choices=VIEWS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--run-all', action='store_true')
    mode.add_argument('--validate-results', action='store_true')
    parser.add_argument('--force', action='store_true', help='Replace artifacts only for one explicit task/view job.')
    parser.add_argument('--validation-scope', choices=('single_job', 'model_family', 'combined_release'), default='model_family')
    args = parser.parse_args()
    data = Data(args.root, args.experiment_root)
    out = data.exp / 'results/classical_ml_rbf_svm_v1'
    explicit = args.task is not None or args.view is not None
    if explicit and not (args.task and args.view):
        raise Error('--task and --view must be supplied together')
    if args.smoke:
        if not (args.task and args.view):
            raise Error('--smoke requires explicit --task and --view')
        jobs: list[tuple[str, str]] | None = [(args.task, args.view)]
    elif args.run_all:
        if explicit:
            raise Error('--run-all does not accept --task/--view')
        jobs = [(task, view) for task in TASKS for view in VIEWS]
    else:
        jobs = [(args.task, args.view)] if explicit else None
    if args.force and (jobs is None or len(jobs) != 1):
        raise Error('--force is allowed only for one explicit --task --view job')
    if args.validate_results:
        if args.validation_scope == 'combined_release':
            raise Error('use --validate-combined for combined_release validation')
        result = validate_results(data, out, jobs, scope=args.validation_scope)
        print(json.dumps(result, sort_keys=True))
        return
    require_sklearn()
    validation = input_validation(data)
    canonical = canonical_manifest_payload(
        experiment_identity={'experiment_name': data.exp.parent.name, 'run_id': data.exp.name, 'model_family': MODEL},
        expected_jobs=[(task, view, MODEL) for task in TASKS for view in VIEWS],
        input_hashes=data.input_hashes,
        scientific_configuration=scientific_configuration(),
        implementation_version=VERSION,
        seed=SEED,
    )
    try:
        manifest_path = out / 'experiment_manifest.json'
        write_canonical_manifest(manifest_path, canonical)
        invocation_id = new_invocation_id()
        invocation_kwargs = {
            'invocation_id': invocation_id,
            'requested_jobs': [(task, view, MODEL) for task, view in (jobs or [])],
            'normalized_cli_args': normalize_cli_args(vars(args)),
            'execution_source_hashes': execution_source_hashes(),
            'dependency_versions': installed_versions(('numpy', 'scikit-learn')),
            'command_mode': 'smoke' if args.smoke else 'run_all',
            'canonical_manifest_sha256': sha(manifest_path),
            'input_hashes': data.input_hashes,
        }
        write_invocation_manifest(
            out / 'invocations',
            invocation_manifest_payload(
                **invocation_kwargs,
                status='started',
            ),
        )
    except Exception as exc:
        raise Error(str(exc)) from exc
    invocation_timestamp = json.loads(
        (out / 'invocations' / f'{invocation_id}.started.json').read_text()
    )['timestamp_utc']
    atomic_json(out / 'temporal_cv_folds.json', validation['temporal_cv_folds'])
    assert jobs is not None
    completed_jobs: list[tuple[str, str, str]] = []
    resumed_jobs: list[tuple[str, str, str]] = []
    for number, (task, view) in enumerate(jobs, start=1):
        job = (task, view, MODEL)
        try:
            validate_completed(data, out, task, view)
            completed_jobs.append(job)
            resumed_jobs.append(job)
            print(f'[rbf-svm] job={number}/{len(jobs)} task={task} view={view} status=resumed elapsed_seconds=0.000', flush=True)
        except Error as exc:
            try:
                artifact = paths_for(out, task, view)
                if any(path.exists() for path in artifact.values()):
                    if not args.force:
                        raise Error(f'invalid existing run for {task}/{view}: {exc}; refuse to overwrite without --force') from exc
                    for path in artifact.values():
                        if path.exists():
                            path.unlink()
                metadata = {
                    'invocation_id': invocation_id,
                    'invocation_manifest': f'invocations/{invocation_id}.json',
                    'execution_source_hashes': invocation_kwargs['execution_source_hashes'],
                    'dependency_versions': invocation_kwargs['dependency_versions'],
                    'created_at_utc': invocation_timestamp,
                    'job_identity': list(job),
                    'execution_status': 'generated',
                }
                run_one(data, task, view, out, number, len(jobs), metadata)
                validate_completed(data, out, task, view, check_invocation_binding=False)
                completed_jobs.append(job)
            except Exception:
                failed = invocation_manifest_payload(
                    **invocation_kwargs,
                    timestamp_utc=invocation_timestamp,
                    status='failed',
                    completed_jobs=completed_jobs,
                    resumed_jobs=resumed_jobs,
                    failed_jobs=[job],
                )
                write_invocation_manifest(out / 'invocations', failed)
                raise
        write_validation_summary(data, out, jobs)
    write_invocation_manifest(
        out / 'invocations',
        invocation_manifest_payload(
            **invocation_kwargs,
            timestamp_utc=invocation_timestamp,
            status='completed',
            completed_jobs=completed_jobs,
            resumed_jobs=resumed_jobs,
        ),
    )
    aggregation = aggregate_results(data, out, require_complete=False)
    aggregation_complete = bool(aggregation.get('aggregation_complete', aggregation.get('passed')))
    print(json.dumps({
        'result': 'PASS' if aggregation_complete else 'INCOMPLETE',
        'job_execution_passed': True,
        'aggregation_complete': aggregation_complete,
        'release_ready': aggregation_complete,
        'output_root': str(out), 'aggregation_report': aggregation,
        'runs': len(jobs), 'smoke': args.smoke,
    }, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (Error, InventoryValidationError) as exc:
        raise SystemExit(f'ERROR: {exc}')
