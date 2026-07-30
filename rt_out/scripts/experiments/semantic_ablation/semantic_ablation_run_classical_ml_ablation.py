#!/usr/bin/env python3
"""Leakage-safe temporal classical-ML ablations on v2 fixed-length descriptors."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, json, math, os, tempfile, time, warnings
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
MODELS = ('logistic_regression', 'random_forest', 'linear_svm', 'rbf_svm', 'xgboost')
V4_MODELS = ('logistic_regression', 'random_forest', 'linear_svm')
RBF_VERSION = 'classical_ml_rbf_svm_v1'
XGBOOST_VERSION = 'classical_ml_xgboost_v1'
N_ROWS = 14616
SPLITS = {'train': 10170, 'excluded': 120, 'test': 4326}
SEED = 42
GAP = 10
VERSION = 'classical_ml_ablation_v4'
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PREDICTION_FIELDS = ['row_index', 'source_frame_id', 'rx_id', 'split', 'y_true', 'score', 'y_pred_default', 'y_pred_selected']
OOF_FIELDS = ['row_index', 'source_frame_id', 'rx_id', 'fold', 'y_true', 'score']

class Error(RuntimeError):
    pass

def require_sklearn() -> None:
    global RandomForestClassifier, VarianceThreshold, LogisticRegression, average_precision_score, balanced_accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, TimeSeriesSplit, Pipeline, StandardScaler, LinearSVC, ConvergenceWarning
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_selection import VarianceThreshold
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import average_precision_score, balanced_accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import LinearSVC
        from sklearn.exceptions import ConvergenceWarning
    except ImportError as exc:
        raise Error('scikit-learn is required to run model experiments; validation-only does not require it') from exc


def require_xgboost() -> None:
    global XGBClassifier
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise Error('xgboost is required for --model xgboost; install it in the selected environment with: python -m pip install xgboost') from exc


_RBF_REFERENCE = None


def rbf_reference():
    """Load the frozen, validated RBF runner so its behavior and identity are exact."""
    global _RBF_REFERENCE
    if _RBF_REFERENCE is None:
        path = Path(__file__).with_name('semantic_ablation_run_rbf_svm_ablation.py')
        if not path.is_file():
            raise Error('validated RBF-SVM reference runner is missing')
        spec = importlib.util.spec_from_file_location('validated_rbf_svm_reference', path)
        if spec is None or spec.loader is None:
            raise Error('cannot load validated RBF-SVM reference runner')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RBF_REFERENCE = module
    return _RBF_REFERENCE

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda : f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)

def atomic_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as h:
        return list(csv.DictReader(h))

def canonical():
    return [(str(f), rx) for f in range(2436) for rx in RX]


def config_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def execution_source_hashes(model_name: str | None = None) -> dict[str, str]:
    sources = [Path(__file__).resolve(), Path(__file__).with_name('release_hardening.py')]
    if model_name == 'rbf_svm':
        sources = [Path(__file__).with_name('semantic_ablation_run_rbf_svm_ablation.py'), Path(__file__).with_name('release_hardening.py')]
    return source_hashes(
        sources,
        project_root=REPOSITORY_ROOT,
    )


def model_family(model_name: str) -> str:
    return 'classical_ml_ablation_v4' if model_name in V4_MODELS else model_name


def family_models(family: str) -> tuple[str, ...]:
    if family == 'classical_ml_ablation_v4':
        return V4_MODELS
    if family in ('rbf_svm', 'xgboost'):
        return (family,)
    raise Error(f'unsupported model family: {family}')


def family_jobs(family: str) -> list[tuple[str, str, str]]:
    return [(task, view, model) for model in family_models(family) for task in TASKS for view in VIEWS]


def scientific_configuration(family: str) -> dict[str, Any]:
    return {
        'tasks': list(TASKS), 'views': list(VIEWS), 'models': list(family_models(family)),
        'rows': N_ROWS, 'splits': SPLITS, 'temporal_gap': GAP,
        'excluded_rows_never_used': True, 'family': family,
    }


def canonical_manifest_for(data: Data, family: str) -> dict[str, Any]:
    version = (
        VERSION
        if family == 'classical_ml_ablation_v4'
        else RBF_VERSION
        if family == 'rbf_svm'
        else XGBOOST_VERSION
    )
    return canonical_manifest_payload(
        experiment_identity={'experiment_name': data.exp.parent.name, 'run_id': data.exp.name, 'model_family': family},
        expected_jobs=family_jobs(family), input_hashes=data.input_hashes,
        scientific_configuration=scientific_configuration(family), implementation_version=version, seed=SEED,
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


def dependency_versions_for(family: str) -> dict[str, str]:
    packages = ['numpy', 'scikit-learn']
    if family == 'xgboost':
        packages.append('xgboost')
    return installed_versions(packages)

class Data:

    def __init__(self, root: Path, experiment_root: Path | None = None):
        self.root = root.resolve()
        self.exp = (experiment_root or (self.root / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015')).resolve()
        self.desc = self.exp / 'features/classical_ml_descriptor_v2'
        self.targets_path = self.exp / 'beam_results/canonical_4x4_dft16/supervised_targets_horizon10.csv'
        required = {v: self.desc / f'{v}.npy' for v in ('G', 'GS', 'GI', 'GSI')}
        required.update({'link_context': self.desc / 'link_context.npy', 'current_beam_onehot': self.desc / 'current_beam_onehot.npy', 'row_index': self.desc / 'row_index.csv', 'schema': self.desc / 'descriptor_schema.json', 'validation': self.desc / 'validation_summary.json', 'targets': self.targets_path})
        if any((not p.is_file() for p in required.values())):
            raise Error('missing published descriptor-v2 input artifact')
        self.paths = required
        self.schema = json.loads(required['schema'].read_text())
        self.validation = json.loads(required['validation'].read_text())
        if self.validation.get('passed') is not True or self.validation.get('published') is not True or self.validation.get('rows') != N_ROWS:
            raise Error('descriptor validation summary is not a published PASS')
        expected = {'G': 65, 'GS': 1430, 'GI': 715, 'GSI': 2080}
        if {k: int(self.schema['views'][k]['dimension']) for k in expected} != expected:
            raise Error('descriptor schema dimensions invalid')
        for key in ('G', 'GS', 'GI', 'GSI', 'link_context', 'current_beam_onehot', 'row_index', 'schema'):
            expected_hash = self.validation.get('output_hashes', {}).get(key)
            if expected_hash is None or sha(required[key]) != expected_hash:
                raise Error(f'descriptor output hash mismatch: {key}')
        if self.validation.get('input_hashes', {}).get('supervised_targets') != sha(required['targets']):
            raise Error('supervised target hash mismatch against descriptor validation manifest')
        self.arrays = {v: np.load(required[v], mmap_mode='r', allow_pickle=False) for v in ('G', 'GS', 'GI', 'GSI', 'link_context', 'current_beam_onehot')}
        if any((a.shape != (N_ROWS, expected[v]) or not np.isfinite(a).all() for (v, a) in self.arrays.items() if v in expected)):
            raise Error('descriptor array shape/non-finite failure')
        if self.arrays['link_context'].shape != (N_ROWS, 16) or self.arrays['current_beam_onehot'].shape != (N_ROWS, 16) or (not np.isfinite(self.arrays['link_context']).all()) or (not np.array_equal(self.arrays['current_beam_onehot'].sum(1), np.ones(N_ROWS, dtype=np.float32))) or (not np.isin(self.arrays['current_beam_onehot'], (0, 1)).all()):
            raise Error('context array contract failure')
        self.rows = read_csv(required['row_index'])
        self.targets = read_csv(required['targets'])
        if len(self.rows) != N_ROWS or len(self.targets) != N_ROWS or [(r.get('source_frame_id'), r.get('rx_id')) for r in self.rows] != canonical() or ([(r.get('source_frame_id'), r.get('rx_id')) for r in self.targets] != canonical()):
            raise Error('non-canonical row ordering')
        if Counter((r['split'] for r in self.rows)) != SPLITS or any((r['split'] != t['split'] for (r, t) in zip(self.rows, self.targets, strict=True))):
            raise Error('split join mismatch')
        for (i, r) in enumerate(self.rows):
            if int(r['row_index']) != i or int(r['source_frame_id']) != i // 6 or r['rx_id'] != RX[i % 6]:
                raise Error('row index is not frame-major/RX-minor')
        self.source = np.asarray([int(r['source_frame_id']) for r in self.rows], np.int32)
        self.rx = np.asarray([r['rx_id'] for r in self.rows])
        self.split = np.asarray([r['split'] for r in self.rows])
        self.y = {task: np.asarray([int(r[task]) for r in self.targets], np.int8) for task in TASKS}
        frame_sets = {split: set(self.source[self.split == split].tolist()) for split in SPLITS}
        if any((frame_sets[a] & frame_sets[b] for (a, b) in (('train', 'excluded'), ('train', 'test'), ('excluded', 'test')))):
            raise Error('source frame appears in more than one chronological split')
        if any((not np.isin(y, (0, 1)).all() for y in self.y.values())):
            raise Error('non-binary task label')
        if np.any((self.split == 'train') & (self.source > 1694)) or np.any((self.split == 'excluded') & ((self.source < 1695) | (self.source > 1714))) or np.any((self.split == 'test') & (self.source < 1715)):
            raise Error('chronological split frame contract failure')
        self.input_hashes = {k: sha(p) for (k, p) in required.items()}

    def features(self, task: str, view: str) -> np.ndarray:
        context = np.asarray(self.arrays['link_context'], np.float32)
        if task == 'beam_reselection_1db_1s':
            context = np.concatenate((context, np.asarray(self.arrays['current_beam_onehot'], np.float32)), axis=1)
        if view == 'CTX':
            return context
        return np.concatenate((np.asarray(self.arrays[view], np.float32), context), axis=1)

def folds(data: Data, task: str) -> tuple[list[dict[str, Any]], list[tuple[np.ndarray, np.ndarray]]]:
    frame_ids = np.arange(1695, dtype=np.int32)
    meta = []
    mapped = []
    try:
        from sklearn.model_selection import TimeSeriesSplit
        pairs = list(TimeSeriesSplit(n_splits=3, gap=GAP).split(frame_ids))
    except ImportError:
        test_size = len(frame_ids) // 4
        pairs = [(np.arange(len(frame_ids) - (3 - n) * test_size - GAP), np.arange(len(frame_ids) - (3 - n) * test_size, len(frame_ids) - (2 - n) * test_size)) for n in range(3)]
    for (n, (tr, val)) in enumerate(pairs):
        (tr_frames, va_frames) = (frame_ids[tr], frame_ids[val])
        if set(tr_frames) & set(va_frames) or int(va_frames.min()) - int(tr_frames.max()) - 1 < GAP:
            raise Error('temporal CV frame overlap/gap violation')
        tr_rows = np.flatnonzero(np.isin(data.source, tr_frames) & (data.split == 'train'))
        va_rows = np.flatnonzero(np.isin(data.source, va_frames) & (data.split == 'train'))
        if len(tr_rows) != len(tr_frames) * 6 or len(va_rows) != len(va_frames) * 6 or np.any(data.y[task][va_rows] == 1) == False:
            raise Error(f'fold {n} has invalid rows or no validation positives')
        meta.append({'fold': n, 'train_frame_range': [int(tr_frames.min()), int(tr_frames.max())], 'validation_frame_range': [int(va_frames.min()), int(va_frames.max())], 'gap_source_frames': int(va_frames.min() - tr_frames.max() - 1), 'train_frames': len(tr_frames), 'validation_frames': len(va_frames), 'train_rows': len(tr_rows), 'validation_rows': len(va_rows), 'train_positive': int(data.y[task][tr_rows].sum()), 'validation_positive': int(data.y[task][va_rows].sum())})
        mapped.append((tr_rows, va_rows))
    return (meta, mapped)

def pipeline(model: str, params: dict[str, Any]) -> Pipeline:
    if model == 'logistic_regression':
        est = LogisticRegression(C=params['C'], penalty='l2', class_weight='balanced', max_iter=10000, solver='liblinear', random_state=SEED)
        steps = [('variance', VarianceThreshold()), ('scale', StandardScaler()), ('model', est)]
    elif model == 'linear_svm':
        est = LinearSVC(C=params['C'], penalty='l2', loss='squared_hinge', dual=False, class_weight='balanced', max_iter=100000, random_state=SEED)
        steps = [('variance', VarianceThreshold()), ('scale', StandardScaler()), ('model', est)]
    elif model == 'random_forest':
        est = RandomForestClassifier(n_estimators=params['n_estimators'], max_depth=params['max_depth'], min_samples_leaf=params['min_samples_leaf'], max_features=params['max_features'], class_weight='balanced_subsample', random_state=SEED, n_jobs=-1)
        steps = [('variance', VarianceThreshold()), ('model', est)]
    else:
        raise Error('unsupported model')
    return Pipeline(steps)

def grid(model: str) -> list[dict[str, Any]]:
    if model == 'logistic_regression':
        return [{'C': x} for x in (0.001, 0.01, 0.1, 1.0, 10.0, 100.0)]
    if model == 'linear_svm':
        return [{'C': x} for x in (1e-05, 0.0001, 0.001, 0.01, 0.1)]
    return [{'n_estimators': 300, 'max_depth': depth, 'min_samples_leaf': leaf, 'max_features': 'sqrt'} for depth in (12, 24, None) for leaf in (1, 5, 10)]

def score(model: Pipeline, x: np.ndarray) -> np.ndarray:
    est = model.named_steps['model']
    return model.predict_proba(x)[:, 1] if hasattr(est, 'predict_proba') else model.decision_function(x)


def fit_with_convergence(model_name: str, fitted: Pipeline, x: np.ndarray, y: np.ndarray) -> tuple[bool, int | None, list[str]]:
    """Fit one fold and make every LinearSVC convergence warning observable."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', ConvergenceWarning)
        fitted.fit(x, y)
    warning_messages = [str(item.message) for item in caught]
    convergence_warning = any(issubclass(item.category, ConvergenceWarning) for item in caught)
    n_iter = None
    if model_name == 'linear_svm':
        raw = fitted.named_steps['model'].n_iter_
        n_iter = int(np.max(np.asarray(raw)))
    return (not convergence_warning, n_iter, warning_messages)

def choose_threshold(y: np.ndarray, s: np.ndarray) -> tuple[float, dict[str, float]]:
    from sklearn.metrics import precision_recall_curve
    (p, r, t) = precision_recall_curve(y, s)
    f = 2 * p[:-1] * r[:-1] / np.maximum(p[:-1] + r[:-1], 1e-15)
    best = np.flatnonzero(np.isclose(f, f.max()))
    idx = best[np.argmax(r[best])]
    tied = best[np.isclose(r[best], r[idx])]
    idx = tied[np.argmin(t[tied])]
    return (float(t[idx]), {'oof_f1': float(f[idx]), 'oof_precision': float(p[idx]), 'oof_recall': float(r[idx])})

def metrics(y: np.ndarray, s: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    cm = confusion_matrix(y, pred, labels=(0, 1))
    single_class = len(np.unique(y)) != 2
    prevalence = float(y.mean())
    ap = None if single_class else float(average_precision_score(y, s))
    balanced = None if single_class else float(balanced_accuracy_score(y, pred))
    roc = None if single_class else float(roc_auc_score(y, s))
    return {
        'rows': int(len(y)),
        'positive_count': int(y.sum()),
        'positive_prevalence': prevalence,
        'average_precision': ap,
        'average_precision_lift': None if single_class else ap - prevalence,
        'average_precision_ratio': None if single_class or prevalence == 0 else ap / prevalence,
        'f1': float(f1_score(y, pred, zero_division=0)),
        'precision': float(precision_score(y, pred, zero_division=0)),
        'recall': float(recall_score(y, pred, zero_division=0)),
        'balanced_accuracy': balanced,
        'roc_auc': roc,
        'single_class_y_true': single_class,
        'confusion_matrix': cm.tolist(),
    }

def baselines(data: Data, task: str, test: np.ndarray) -> dict[str, Any]:
    train = np.flatnonzero(data.split == 'train')
    (ytr, yte) = (data.y[task][train], data.y[task][test])
    zero = np.zeros(len(test), np.int8)
    global_label = int(ytr.mean() >= 0.5)
    per = {rx: int(ytr[data.rx[train] == rx].mean() >= 0.5) for rx in RX}
    rx_pred = np.asarray([per[x] for x in data.rx[test]], np.int8)
    return {'always_negative': metrics(yte, zero, zero), 'global_train_majority': {'train_label': global_label, 'metrics': metrics(yte, np.full(len(test), global_label), np.full(len(test), global_label))}, 'train_only_per_rx_majority': {'train_labels': per, 'metrics': metrics(yte, rx_pred, rx_pred)}}

def feature_construction(task: str, view: str) -> dict[str, Any]:
    context = ['link_context']
    if task == 'beam_reselection_1db_1s':
        context.append('current_beam_onehot')
    return {'view': view, 'descriptor': None if view == 'CTX' else view, 'context': context}


def preprocessing(model: str) -> list[str]:
    return ['VarianceThreshold', 'StandardScaler', model] if model != 'random_forest' else ['VarianceThreshold', model]


def run_paths(out: Path, task: str, view: str, model: str) -> dict[str, Path]:
    return {
        'run': out / 'runs' / task / view / f'{model}.json',
        'prediction': out / 'predictions' / task / view / f'{model}.csv',
        'oof': out / 'oof_predictions' / task / view / f'{model}.csv',
    }


def xgboost_grid() -> list[dict[str, Any]]:
    return [
        {'n_estimators': n_estimators, 'max_depth': max_depth, 'learning_rate': learning_rate}
        for n_estimators in (300, 600)
        for max_depth in (3, 6)
        for learning_rate in (0.03, 0.1)
    ]


def xgboost_pipeline(params: dict[str, Any], scale_pos_weight: float) -> Pipeline:
    estimator = XGBClassifier(
        objective='binary:logistic', eval_metric='logloss', tree_method='hist',
        subsample=0.8, colsample_bytree=0.8, min_child_weight=1, gamma=0,
        reg_alpha=0, reg_lambda=1, random_state=SEED, n_jobs=-1, verbosity=0,
        scale_pos_weight=scale_pos_weight, **params,
    )
    return Pipeline([('variance', VarianceThreshold()), ('model', estimator)])


def xgboost_identity(data: Data, task: str, view: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[np.ndarray, np.ndarray]]]:
    fold_meta, fold_rows = folds(data, task)
    payload = {
        'script_version': XGBOOST_VERSION,
        'script_sha256': sha(Path(__file__).resolve()),
        'execution_source_hashes': execution_source_hashes('xgboost'),
        'input_artifact_hashes': data.input_hashes,
        'task': task, 'view': view, 'model': 'xgboost',
        'feature_construction': feature_construction(task, view),
        'feature_dimension': int(data.features(task, view).shape[1]),
        'cv_folds': fold_meta,
        'preprocessing': ['VarianceThreshold', 'XGBClassifier'],
        'xgboost_base_configuration': {
            'objective': 'binary:logistic', 'eval_metric': 'logloss', 'tree_method': 'hist',
            'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 1,
            'gamma': 0, 'reg_alpha': 0, 'reg_lambda': 1, 'random_state': SEED,
            'n_jobs': -1, 'verbosity': 0,
        },
        'hyperparameter_grid': xgboost_grid(),
        'scale_pos_weight_policy': 'fold training negatives / fold training positives; final train negatives / final train positives',
        'threshold_selection_policy': 'maximize OOF F1; ties higher recall then lower threshold',
        'random_seed': SEED,
    }
    return payload, fold_meta, fold_rows


def xgboost_fit(model: Pipeline, x: np.ndarray, y: np.ndarray) -> tuple[dict[str, Any], np.ndarray | None]:
    started = time.monotonic()
    caught: list[Any] = []
    error = None
    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter('always')
            model.fit(x, y)
            caught = list(caught_warnings)
    except Exception as exc:  # Configuration rejection is deliberate and recorded.
        error = f'{type(exc).__name__}: {exc}'
    runtime = time.monotonic() - started
    warning_messages = [str(item.message) for item in caught]
    if error is not None:
        return ({'runtime_seconds': runtime, 'warnings': warning_messages, 'error': error, 'scores_finite': False, 'fitted_tree_count': None, 'valid': False}, None)
    estimator = model.named_steps['model']
    try:
        tree_count = len(estimator.get_booster().get_dump())
        scores = np.asarray(model.predict_proba(x)[:, 1], dtype=np.float64)
        finite = bool(np.isfinite(scores).all())
    except Exception as exc:
        return ({'runtime_seconds': runtime, 'warnings': warning_messages, 'error': f'{type(exc).__name__}: {exc}', 'scores_finite': False, 'fitted_tree_count': None, 'valid': False}, None)
    return ({'runtime_seconds': runtime, 'warnings': warning_messages, 'error': None, 'scores_finite': finite, 'fitted_tree_count': int(tree_count), 'valid': bool(finite and tree_count > 0)}, scores if finite else None)


def run_xgboost_one(
    data: Data,
    task: str,
    view: str,
    out: Path,
    job_number: int,
    total_jobs: int,
    invocation_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_xgboost()
    started = time.monotonic()
    x = data.features(task, view)
    train, test = np.flatnonzero(data.split == 'train'), np.flatnonzero(data.split == 'test')
    payload, fold_meta, folds_ = xgboost_identity(data, task, view)
    results = []
    for config_number, params in enumerate(xgboost_grid(), start=1):
        configuration_started = time.monotonic()
        scores, fold_ids, fold_fits, fold_ap = np.full(N_ROWS, np.nan), np.full(N_ROWS, -1, np.int8), [], []
        for fold_number, (tr, va) in enumerate(folds_, start=1):
            labels = data.y[task][tr]
            positive, negative = int(labels.sum()), int(len(labels) - labels.sum())
            if positive == 0:
                raise Error(f'xgboost fold {fold_number} has no training positives')
            scale_pos_weight = negative / positive
            print(f'[ablation] job={job_number}/{total_jobs} task={task} view={view} model=xgboost status=created config={config_number}/8 fold={fold_number}/3 elapsed_seconds={time.monotonic()-started:.3f}', flush=True)
            fitted = xgboost_pipeline(params, scale_pos_weight)
            details, _ = xgboost_fit(fitted, x[tr], labels)
            details.update({'scale_pos_weight': scale_pos_weight, 'training_positive_count': positive, 'training_negative_count': negative})
            if details['valid']:
                try:
                    values = np.asarray(fitted.predict_proba(x[va])[:, 1], dtype=np.float64)
                    details['scores_finite'] = bool(np.isfinite(values).all())
                    details['valid'] = bool(details['valid'] and details['scores_finite'])
                except Exception as exc:
                    details.update({'valid': False, 'scores_finite': False, 'error': f'{type(exc).__name__}: {exc}'})
                    values = None
            else:
                values = None
            if values is None or not details['valid']:
                fold_ap.append(None)
            else:
                scores[va], fold_ids[va] = values, fold_number - 1
                fold_ap.append(float(average_precision_score(data.y[task][va], values)))
            fold_fits.append(details)
        valid = bool(all(item['valid'] for item in fold_fits))
        results.append({'params': params, 'valid': valid, 'fold_fits': fold_fits, 'fold_average_precision': fold_ap, 'mean_validation_average_precision': float(np.mean(fold_ap)) if valid else None, 'configuration_runtime_seconds': time.monotonic()-configuration_started, 'oof_scores': scores, 'fold_ids': fold_ids})
    viable = [result for result in results if result['valid']]
    if not viable:
        raise Error('all xgboost configurations failed fitting, finite-score, tree-count, or result-contract validation')
    best = max(viable, key=lambda result: result['mean_validation_average_precision'])
    oof_rows = np.flatnonzero(np.isfinite(best['oof_scores']))
    threshold, threshold_info = choose_threshold(data.y[task][oof_rows], best['oof_scores'][oof_rows])
    final_labels = data.y[task][train]
    final_positive, final_negative = int(final_labels.sum()), int(len(final_labels) - final_labels.sum())
    final = xgboost_pipeline(best['params'], final_negative / final_positive)
    final_fit, _ = xgboost_fit(final, x[train], final_labels)
    final_fit.update({'scale_pos_weight': final_negative / final_positive, 'training_positive_count': final_positive, 'training_negative_count': final_negative})
    if not final_fit['valid']:
        raise Error('selected xgboost configuration failed final fit validation')
    test_scores = np.asarray(final.predict_proba(x[test])[:, 1], dtype=np.float64)
    final_fit['scores_finite'] = bool(np.isfinite(test_scores).all())
    final_fit['valid'] = bool(final_fit['valid'] and final_fit['scores_finite'])
    if not final_fit['valid']:
        raise Error('selected xgboost configuration produced non-finite test scores')
    default, selected = (test_scores >= 0.5).astype(np.int8), (test_scores >= threshold).astype(np.int8)
    ytest, per_rx = data.y[task][test], []
    for rx in RX:
        mask = data.rx[test] == rx
        for name, prediction in (('default', default), ('selected', selected)):
            per_rx.append({'task': task, 'view': view, 'model': 'xgboost', 'threshold_type': name, 'rx_id': rx, **metrics(ytest[mask], test_scores[mask], prediction[mask])})
    prediction_rows = [{'row_index': int(i), 'source_frame_id': int(data.source[i]), 'rx_id': str(data.rx[i]), 'split': 'test', 'y_true': int(data.y[task][i]), 'score': float(score), 'y_pred_default': int(pred), 'y_pred_selected': int(chosen)} for i, score, pred, chosen in zip(test, test_scores, default, selected, strict=True)]
    oof_rows_csv = [{'row_index': int(i), 'source_frame_id': int(data.source[i]), 'rx_id': str(data.rx[i]), 'fold': int(best['fold_ids'][i]), 'y_true': int(data.y[task][i]), 'score': float(best['oof_scores'][i])} for i in oof_rows]
    paths = run_paths(out, task, view, 'xgboost')
    atomic_csv(paths['prediction'], PREDICTION_FIELDS, prediction_rows)
    atomic_csv(paths['oof'], OOF_FIELDS, oof_rows_csv)
    run = {'run_schema_version': XGBOOST_VERSION, 'configuration': payload, 'configuration_sha256': config_hash(payload), 'task': task, 'view': view, 'model': 'xgboost', 'feature_dimension': int(x.shape[1]), 'random_seed': SEED, 'cv_folds': fold_meta, 'config_grid': [{key: value for key, value in result.items() if key not in ('oof_scores', 'fold_ids')} for result in results], 'selected_hyperparameters': best['params'], 'selected_mean_validation_average_precision': best['mean_validation_average_precision'], 'selected_threshold': threshold, 'threshold_selection': threshold_info, 'threshold_selection_source': 'train_only_oof_predictions', 'default_threshold': 0.5, 'oof_rows': int(len(oof_rows)), 'test_rows': int(len(test)), 'test_default_threshold': metrics(ytest, test_scores, default), 'test_selected_threshold': metrics(ytest, test_scores, selected), 'baselines': baselines(data, task, test), 'per_rx_metrics': per_rx, 'warnings': [], 'selected_configuration_converged': best['valid'], 'final_fit': final_fit, 'runtime_seconds': time.monotonic()-started, 'prediction_sha256': sha(paths['prediction']), 'oof_prediction_sha256': sha(paths['oof'])}
    run.update(invocation_metadata or {})
    atomic_json(paths['run'], run)
    return run


def identity(data: Data, task: str, view: str, model: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[np.ndarray, np.ndarray]]]:
    fold_meta, fold_rows = folds(data, task)
    payload = {
        'script_version': VERSION,
        'execution_source_hashes': execution_source_hashes(model),
        'input_artifact_hashes': data.input_hashes,
        'task': task,
        'view': view,
        'model': model,
        'feature_construction': feature_construction(task, view),
        'feature_dimension': int(data.features(task, view).shape[1]),
        'cv_folds': fold_meta,
        'preprocessing': preprocessing(model),
        'hyperparameter_grid': grid(model),
        'threshold_selection_policy': 'maximize OOF F1; ties higher recall then lower threshold',
        'random_seed': SEED,
    }
    return payload, fold_meta, fold_rows


def validate_completed(
    data: Data,
    out: Path,
    task: str,
    view: str,
    model: str,
    *,
    check_invocation_binding: bool = True,
) -> dict[str, Any]:
    if model == 'rbf_svm':
        reference = rbf_reference()
        reference.require_sklearn()
        try:
            return reference.validate_completed(
                data, out, task, view, check_invocation_binding=check_invocation_binding
            )
        except reference.Error as exc:
            raise Error(str(exc)) from exc
    if model == 'xgboost':
        return validate_xgboost_completed(
            data, out, task, view, check_invocation_binding=check_invocation_binding
        )
    paths = run_paths(out, task, view, model)
    if any(not path.is_file() for path in paths.values()):
        raise Error('incomplete run artifacts')
    run = json.loads(paths['run'].read_text())
    payload, fold_meta, fold_rows = identity(data, task, view, model)
    if run.get('run_schema_version') != VERSION or run.get('configuration') != payload or run.get('configuration_sha256') != config_hash(payload):
        raise Error('configuration-mismatched run')
    if run.get('prediction_sha256') != sha(paths['prediction']) or run.get('oof_prediction_sha256') != sha(paths['oof']):
        raise Error('run artifact hash mismatch')
    if check_invocation_binding:
        try:
            validate_run_invocation_binding(
                out,
                run,
                (task, view, model),
                expected_execution_source_hashes=execution_source_hashes(model),
                expected_dependency_versions=dependency_versions_for(model_family(model)),
            )
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
    prediction = read_csv(paths['prediction'])
    expected_test = np.flatnonzero(data.split == 'test')
    if len(prediction) != 4326 or [(int(r['row_index']), r['rx_id'], r['split']) for r in prediction] != [(int(i), str(data.rx[i]), 'test') for i in expected_test]:
        raise Error('prediction CSV is not canonical 4326-row test output')
    if any(int(r['source_frame_id']) != int(data.source[int(r['row_index'])]) or int(r['y_true']) != int(data.y[task][int(r['row_index'])]) for r in prediction):
        raise Error('prediction label/identifier mismatch')
    oof = read_csv(paths['oof'])
    fold_by_row = {}
    for fold, (_, validation_rows) in enumerate(fold_rows):
        fold_by_row.update({int(i): fold for i in validation_rows})
    if (
        [int(r['row_index']) for r in oof] != sorted(fold_by_row)
        or len(oof) != len(fold_by_row)
        or any(
            int(r['row_index']) not in fold_by_row
            or int(r['fold']) != fold_by_row[int(r['row_index'])]
            or r['rx_id'] != data.rx[int(r['row_index'])]
            or int(r['y_true']) != int(data.y[task][int(r['row_index'])])
            or data.split[int(r['row_index'])] != 'train'
            for r in oof
        )
    ):
        raise Error('OOF CSV includes non-validation, excluded, or invalid rows')
    if run.get('threshold_selection_source') != 'train_only_oof_predictions' or int(run.get('oof_rows', -1)) != len(oof) or int(run.get('test_rows', -1)) != 4326:
        raise Error('threshold source or result row-count contract failed')
    if model == 'linear_svm':
        selected = [item for item in run.get('config_grid', []) if item.get('params') == run.get('selected_hyperparameters')]
        if len(selected) != 1 or selected[0].get('converged') is not True or run.get('selected_configuration_converged') is not True or run.get('final_fit_converged') is not True:
            raise Error('completed LinearSVC run selected a non-converged configuration')
    if run.get('deterministic_rerun_equal') is False:
        raise Error('deterministic logistic smoke check failed')
    return run


def validate_xgboost_completed(
    data: Data,
    out: Path,
    task: str,
    view: str,
    *,
    check_invocation_binding: bool = True,
) -> dict[str, Any]:
    paths = run_paths(out, task, view, 'xgboost')
    if any(not path.is_file() for path in paths.values()):
        raise Error('incomplete xgboost run artifacts')
    run = json.loads(paths['run'].read_text())
    payload, _, fold_rows = xgboost_identity(data, task, view)
    if run.get('run_schema_version') != XGBOOST_VERSION or run.get('configuration') != payload or run.get('configuration_sha256') != config_hash(payload):
        raise Error('configuration-mismatched xgboost run')
    if run.get('prediction_sha256') != sha(paths['prediction']) or run.get('oof_prediction_sha256') != sha(paths['oof']):
        raise Error('xgboost run artifact hash mismatch')
    if check_invocation_binding:
        try:
            validate_run_invocation_binding(
                out,
                run,
                (task, view, 'xgboost'),
                expected_execution_source_hashes=execution_source_hashes('xgboost'),
                expected_dependency_versions=dependency_versions_for('xgboost'),
            )
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
    selected = [entry for entry in run.get('config_grid', []) if entry.get('params') == run.get('selected_hyperparameters')]
    if len(selected) != 1 or selected[0].get('valid') is not True or run.get('selected_configuration_converged') is not True or run.get('final_fit', {}).get('valid') is not True:
        raise Error('selected xgboost configuration/final fit is invalid')
    prediction = read_csv(paths['prediction'])
    expected_test = np.flatnonzero(data.split == 'test')
    if len(prediction) != 4326 or [(int(row['row_index']), row['rx_id'], row['split']) for row in prediction] != [(int(index), str(data.rx[index]), 'test') for index in expected_test]:
        raise Error('xgboost prediction CSV is not canonical 4326-row test output')
    if any(not math.isfinite(float(row['score'])) or int(row['source_frame_id']) != int(data.source[int(row['row_index'])]) or int(row['y_true']) != int(data.y[task][int(row['row_index'])]) for row in prediction):
        raise Error('xgboost prediction identifier/label/score mismatch')
    oof = read_csv(paths['oof'])
    fold_by_row = {int(index): fold for fold, (_, validation) in enumerate(fold_rows) for index in validation}
    if [int(row['row_index']) for row in oof] != sorted(fold_by_row) or len(oof) != len(fold_by_row):
        raise Error('xgboost OOF CSV row ordering/count failure')
    if any(int(row['row_index']) not in fold_by_row or int(row['fold']) != fold_by_row[int(row['row_index'])] or row['rx_id'] != data.rx[int(row['row_index'])] or int(row['y_true']) != int(data.y[task][int(row['row_index'])]) or data.split[int(row['row_index'])] != 'train' or not math.isfinite(float(row['score'])) for row in oof):
        raise Error('xgboost OOF CSV includes non-validation, excluded, or invalid rows')
    if run.get('threshold_selection_source') != 'train_only_oof_predictions' or int(run.get('oof_rows', -1)) != len(oof) or int(run.get('test_rows', -1)) != 4326:
        raise Error('xgboost threshold/result row contract failed')
    return run


def aggregate_results(data: Data, out: Path, *, require_complete: bool = False) -> dict[str, Any]:
    family = 'xgboost' if 'xgboost' in out.name else 'classical_ml_ablation_v4'
    expected = set(tuple(job) for job in family_jobs(family))
    manifest_path = out / 'experiment_manifest.json'
    if not manifest_path.is_file():
        raise Error(f'canonical experiment manifest is missing: {manifest_path}')
    validate_existing_manifest(manifest_path, canonical_manifest_for(data, family))
    paths = sorted((out / 'runs').glob('*/*/*.json')) if (out / 'runs').is_dir() else []
    try:
        report, accepted = collect_run_inventory(
            paths,
            expected=expected,
            identity_fields=('task', 'view', 'model'),
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
        selected[f"{run['task']}/{run['view']}/{run['model']}"] = {
            'hyperparameters': run['selected_hyperparameters'],
            'threshold': run['selected_threshold'],
            'mean_validation_average_precision': run['selected_mean_validation_average_precision'],
            'warnings': run['warnings'],
        }
        summaries.append({
            'task': run['task'], 'view': run['view'], 'model': run['model'],
            'feature_dimension': run['feature_dimension'],
            'mean_validation_average_precision': run['selected_mean_validation_average_precision'],
            'selected_threshold': run['selected_threshold'],
            'selected_converged': run['selected_configuration_converged'],
            **{f'test_{k}': v for k, v in run['test_selected_threshold'].items() if k != 'confusion_matrix'},
        })
        per_rx.extend(run['per_rx_metrics'])
    if not summaries or not per_rx:
        report['aggregation_complete'] = False
        report['release_ready'] = False
        report['status'] = 'INCOMPLETE'
        atomic_release_json(out / 'aggregation_validation.json', report)
        return report
    with tempfile.TemporaryDirectory(prefix='family_aggregate_', dir=out.parent) as temporary:
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
    model_name: str,
    out: Path,
    smoke: bool,
    job_number: int,
    total_jobs: int,
    invocation_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if model_name == 'rbf_svm':
        reference = rbf_reference()
        reference.require_sklearn()
        return reference.run_one(data, task, view, out, job_number, total_jobs, invocation_metadata)
    if model_name == 'xgboost':
        return run_xgboost_one(data, task, view, out, job_number, total_jobs, invocation_metadata)
    started = time.monotonic()
    x = data.features(task, view)
    train, test = np.flatnonzero(data.split == 'train'), np.flatnonzero(data.split == 'test')
    payload, fold_meta, folds_ = identity(data, task, view, model_name)
    results = []
    for config_number, params in enumerate(grid(model_name), start=1):
        configuration_started = time.monotonic()
        scores, fold_ids, per = np.full(N_ROWS, np.nan), np.full(N_ROWS, -1, np.int8), []
        fold_converged, fold_n_iter, fold_runtime_seconds, configuration_warnings = [], [], [], []
        for fold_number, (tr, va) in enumerate(folds_, start=1):
            fold_started = time.monotonic()
            print(f'[ablation] job={job_number}/{total_jobs} task={task} view={view} model={model_name} status=created config={config_number}/{len(grid(model_name))} fold={fold_number}/3 elapsed_seconds={time.monotonic()-started:.3f}', flush=True)
            fitted = pipeline(model_name, params)
            converged, n_iter, warnings_seen = fit_with_convergence(model_name, fitted, x[tr], data.y[task][tr])
            fold_converged.append(converged)
            fold_n_iter.append(n_iter)
            fold_runtime_seconds.append(time.monotonic() - fold_started)
            configuration_warnings.extend(warnings_seen)
            if not converged:
                print(f'[ablation] warning task={task} view={view} model={model_name} config={config_number}/{len(grid(model_name))} fold={fold_number}/3 convergence_warning n_iter={n_iter}', flush=True)
            values = score(fitted, x[va])
            scores[va], fold_ids[va] = values, fold_number - 1
            per.append(float(average_precision_score(data.y[task][va], values)))
        converged = all(fold_converged)
        results.append({'params': params, 'converged': converged, 'fold_converged': fold_converged, 'fold_n_iter': fold_n_iter, 'fold_runtime_seconds': fold_runtime_seconds, 'configuration_runtime_seconds': time.monotonic() - configuration_started, 'warnings': configuration_warnings, 'mean_validation_average_precision': float(np.mean(per)) if converged else None, 'fold_average_precision': per, 'oof_scores': scores, 'fold_ids': fold_ids})
    valid_results = [value for value in results if value['converged']]
    if not valid_results:
        raise Error(f'all {model_name} hyperparameter configurations failed convergence validation')
    best = max(valid_results, key=lambda value: value['mean_validation_average_precision'])
    oof_rows = np.flatnonzero(np.isfinite(best['oof_scores']))
    threshold, threshold_info = choose_threshold(data.y[task][oof_rows], best['oof_scores'][oof_rows])
    final = pipeline(model_name, best['params'])
    final_converged, final_n_iter, final_warnings = fit_with_convergence(model_name, final, x[train], data.y[task][train])
    if not final_converged:
        raise Error(f'selected {model_name} configuration failed convergence on the complete train split')
    test_score = score(final, x[test])
    default_threshold = 0.5 if model_name != 'linear_svm' else 0.0
    default_pred, selected_pred = (test_score >= default_threshold).astype(np.int8), (test_score >= threshold).astype(np.int8)
    deterministic = None
    if smoke and model_name == 'logistic_regression':
        repeat = pipeline(model_name, best['params'])
        repeat_converged, _, _ = fit_with_convergence(model_name, repeat, x[train], data.y[task][train])
        if not repeat_converged:
            raise Error('deterministic logistic smoke refit failed convergence validation')
        deterministic = bool(np.array_equal(test_score, score(repeat, x[test])))
    warnings = []
    if model_name in ('logistic_regression', 'linear_svm') and best['params']['C'] in (grid(model_name)[0]['C'], grid(model_name)[-1]['C']):
        warnings.append('selected_C_is_grid_boundary')
        print(f'[ablation] warning task={task} view={view} model={model_name} selected_C={best["params"]["C"]} is a grid boundary', flush=True)
    ytest, per_rx = data.y[task][test], []
    for rx in RX:
        pick = data.rx[test] == rx
        for name, pred in (('default', default_pred), ('selected', selected_pred)):
            per_rx.append({'task': task, 'view': view, 'model': model_name, 'threshold_type': name, 'rx_id': rx, **metrics(ytest[pick], test_score[pick], pred[pick])})
    prediction_rows = [{'row_index': int(i), 'source_frame_id': int(data.source[i]), 'rx_id': str(data.rx[i]), 'split': 'test', 'y_true': int(data.y[task][i]), 'score': float(value), 'y_pred_default': int(default), 'y_pred_selected': int(selected)} for i, value, default, selected in zip(test, test_score, default_pred, selected_pred, strict=True)]
    oof_rows_csv = [{'row_index': int(i), 'source_frame_id': int(data.source[i]), 'rx_id': str(data.rx[i]), 'fold': int(best['fold_ids'][i]), 'y_true': int(data.y[task][i]), 'score': float(best['oof_scores'][i])} for i in oof_rows]
    paths = run_paths(out, task, view, model_name)
    atomic_csv(paths['prediction'], PREDICTION_FIELDS, prediction_rows)
    atomic_csv(paths['oof'], OOF_FIELDS, oof_rows_csv)
    run = {
        'run_schema_version': VERSION, 'configuration': payload, 'configuration_sha256': config_hash(payload),
        'task': task, 'view': view, 'model': model_name, 'feature_dimension': int(x.shape[1]),
        'random_seed': SEED, 'cv_folds': fold_meta,
        'config_grid': [{'params': value['params'], 'converged': value['converged'], 'fold_converged': value['fold_converged'], 'fold_n_iter': value['fold_n_iter'], 'fold_runtime_seconds': value['fold_runtime_seconds'], 'configuration_runtime_seconds': value['configuration_runtime_seconds'], 'warnings': value['warnings'], 'mean_validation_average_precision': value['mean_validation_average_precision'], 'fold_average_precision': value['fold_average_precision']} for value in results],
        'selected_hyperparameters': best['params'], 'selected_mean_validation_average_precision': best['mean_validation_average_precision'],
        'selected_threshold': threshold, 'threshold_selection': threshold_info, 'threshold_selection_source': 'train_only_oof_predictions',
        'default_threshold': default_threshold, 'oof_rows': int(len(oof_rows)), 'test_rows': int(len(test)),
        'test_default_threshold': metrics(ytest, test_score, default_pred), 'test_selected_threshold': metrics(ytest, test_score, selected_pred),
        'baselines': baselines(data, task, test), 'per_rx_metrics': per_rx, 'warnings': warnings,
        'selected_configuration_converged': best['converged'], 'final_fit_converged': final_converged,
        'final_fit_n_iter': final_n_iter, 'final_fit_warnings': final_warnings, 'runtime_seconds': time.monotonic() - started,
        'deterministic_rerun_equal': deterministic, 'prediction_sha256': sha(paths['prediction']), 'oof_prediction_sha256': sha(paths['oof']),
    }
    run.update(invocation_metadata or {})
    atomic_json(paths['run'], run)
    return run

def validate_only(data: Data) -> dict[str, Any]:
    folds_out = {task: folds(data, task)[0] for task in TASKS}
    return {'passed': True, 'rows': N_ROWS, 'split_rows': dict(Counter(data.split)), 'descriptor_dimensions': {v: int(data.arrays[v].shape[1]) for v in ('G', 'GS', 'GI', 'GSI')}, 'feature_dimensions': {task: {view: int(data.features(task, view).shape[1]) for view in VIEWS} for task in TASKS}, 'temporal_cv_folds': folds_out, 'input_hashes': data.input_hashes}


def validate_results(
    data: Data,
    out: Path,
    expected_jobs: list[tuple[str, str, str]] | None = None,
    *,
    scope: str = 'model_family',
) -> dict[str, Any]:
    if scope == 'single_job':
        if not expected_jobs or len(expected_jobs) != 1:
            raise Error('single_job validation requires exactly one task/view/model identity')
        expected = {tuple(expected_jobs[0])}
        job = expected_jobs[0]
        manifest_path = out / 'experiment_manifest.json'
        if not manifest_path.is_file():
            raise Error(f'single_job validation requires a canonical experiment manifest: {manifest_path}')
        try:
            validate_existing_manifest(manifest_path, canonical_manifest_for(data, model_family(job[2])))
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
        paths = [run_paths(out, *job)['run']]
    elif scope == 'model_family':
        manifest_path = out / 'experiment_manifest.json'
        if not manifest_path.is_file():
            raise Error(f'model_family validation requires a canonical experiment manifest: {manifest_path}')
        family = 'xgboost' if 'xgboost' in out.name else 'classical_ml_ablation_v4'
        try:
            validate_existing_manifest(manifest_path, canonical_manifest_for(data, family))
        except ManifestConflictError as exc:
            raise Error(str(exc)) from exc
        expected = {tuple(job) for job in family_jobs(family)}
        paths = sorted((out / 'runs').glob('*/*/*.json')) if (out / 'runs').is_dir() else []
    else:
        raise Error('combined_release validation is provided by --validate-combined')
    report, accepted = collect_run_inventory(
        paths,
        expected=expected,
        identity_fields=('task', 'view', 'model'),
        validator=lambda identity, payload, path: validate_completed(data, out, *identity),
        fail_closed=True,
        scope=scope,
    )
    return {'passed': True, 'output_root': str(out), **report, 'run_identities': sorted('/'.join(identity) for identity in accepted)}


def output_root(data: Data, model: str, smoke: bool = False) -> Path:
    if model in V4_MODELS:
        return data.exp / ('results/classical_ml_ablation_v4_smoke' if smoke else 'results/classical_ml_ablation_v4')
    if model == 'rbf_svm':
        return data.exp / ('results/classical_ml_rbf_svm_v1_parity_smoke' if smoke else 'results/classical_ml_rbf_svm_v1')
    if model == 'xgboost':
        return data.exp / ('results/classical_ml_xgboost_v1_smoke' if smoke else 'results/classical_ml_xgboost_v1')
    raise Error(f'unsupported model: {model}')


def validate_combined_sources(data: Data) -> dict[str, Any]:
    sources = {
        'classical_ml_ablation_v4': data.exp / 'results/classical_ml_ablation_v4',
        'classical_ml_rbf_svm_v1': data.exp / 'results/classical_ml_rbf_svm_v1',
        'classical_ml_xgboost_v1': data.exp / 'results/classical_ml_xgboost_v1',
    }
    source_contracts = {
        'classical_ml_ablation_v4': ('classical_ml_ablation_v4', set(V4_MODELS)),
        'classical_ml_rbf_svm_v1': ('rbf_svm', {'rbf_svm'}),
        'classical_ml_xgboost_v1': ('xgboost', {'xgboost'}),
    }
    expected = {(task, view, model) for task in TASKS for view in VIEWS for model in MODELS}
    found, summaries, per_rx, selected, references = set(), [], [], {}, []
    try:
        for source_name, source_root in sources.items():
            family, allowed_models = source_contracts[source_name]
            manifest_path = source_root / 'experiment_manifest.json'
            if not manifest_path.is_file():
                raise Error(f'combined source canonical manifest is missing: {manifest_path}')
            validate_existing_manifest(manifest_path, canonical_manifest_for(data, family))
            for path in sorted((source_root / 'runs').glob('*/*/*.json')) if (source_root / 'runs').is_dir() else []:
                run = json.loads(path.read_text())
                identity_ = (run.get('task'), run.get('view'), run.get('model'))
                if identity_ not in expected or identity_ in found:
                    raise Error(f'invalid or duplicate combined source run: {path}')
                if identity_[2] not in allowed_models:
                    raise Error(f'combined source run is in the wrong model-family root: {path}')
                validate_completed(data, source_root, *identity_)
                prediction = source_root / 'predictions' / identity_[0] / identity_[1] / f'{identity_[2]}.csv'
                oof = source_root / 'oof_predictions' / identity_[0] / identity_[1] / f'{identity_[2]}.csv'
                found.add(identity_)
                references.append({'identity': '/'.join(identity_), 'source_root': str(source_root.relative_to(data.exp)), 'run_json': str(path.relative_to(data.exp)), 'run_sha256': sha(path), 'prediction_csv': str(prediction.relative_to(data.exp)), 'prediction_sha256': sha(prediction), 'oof_prediction_csv': str(oof.relative_to(data.exp)), 'oof_prediction_sha256': sha(oof)})
                summaries.append({'task': identity_[0], 'view': identity_[1], 'model': identity_[2], 'feature_dimension': run['feature_dimension'], 'mean_validation_average_precision': run['selected_mean_validation_average_precision'], 'selected_threshold': run['selected_threshold'], 'selected_converged': run['selected_configuration_converged'], **{f'test_{key}': value for key, value in run['test_selected_threshold'].items() if key != 'confusion_matrix'}})
                per_rx.extend(run['per_rx_metrics'])
                selected['/'.join(identity_)] = {'hyperparameters': run['selected_hyperparameters'], 'threshold': run['selected_threshold'], 'mean_validation_average_precision': run['selected_mean_validation_average_precision'], 'source_run_sha256': sha(path)}
        missing = sorted('/'.join(item) for item in expected - found)
        if missing:
            raise Error(f'combined aggregation requires all {len(expected)} validated runs; missing {len(missing)}: {missing[:5]}')
    except (Error, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {'status': 'INCOMPLETE', 'passed': False, 'job_execution_passed': False, 'aggregation_complete': False, 'release_ready': False, 'validated_runs': len(found), 'expected_runs': len(expected), 'error': str(exc)}
    return {
        'status': 'PASS', 'passed': True, 'job_execution_passed': True,
        'aggregation_complete': True, 'release_ready': True,
        'validated_runs': len(found), 'expected_runs': len(expected),
        'expected_jobs': sorted(expected), 'summaries': summaries, 'per_rx': per_rx,
        'selected': selected, 'references': references,
    }


def combined_manifest_for(data: Data, source_info: dict[str, Any]) -> dict[str, Any]:
    expected = {tuple(job) for job in source_info['expected_jobs']}
    return canonical_manifest_payload(
        experiment_identity={
            'experiment_name': data.exp.name,
            'model_family': 'classical_ml_combined_v1',
            'version': 'classical_ml_combined_v1',
            'expected_runs': len(expected),
            'source_artifacts': source_info['references'],
        },
        expected_jobs=sorted(expected),
        input_hashes=data.input_hashes,
        scientific_configuration={'tasks': list(TASKS), 'views': list(VIEWS), 'models': list(MODELS), 'expected_runs': len(expected)},
        implementation_version='classical_ml_combined_v1',
        seed=SEED,
    )


def build_combined_aggregate(data: Data) -> dict[str, Any]:
    out = data.exp / 'results/classical_ml_combined_v1'
    source_info = validate_combined_sources(data)
    if not source_info['passed']:
        invalid = {key: value for key, value in source_info.items() if key not in {'summaries', 'per_rx', 'selected', 'references', 'expected_jobs'}}
        atomic_release_json(out / 'validation_summary.json', invalid)
        return invalid
    manifest = combined_manifest_for(data, source_info)
    validate_existing_manifest(out / 'combined_manifest.json', manifest)
    output_hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix='combined_aggregate_', dir=data.exp) as temporary:
        stage = Path(temporary)
        summaries, per_rx, selected = source_info['summaries'], source_info['per_rx'], source_info['selected']
        atomic_csv(stage / 'run_summary.csv', list(summaries[0]), summaries)
        atomic_csv(stage / 'per_rx_metrics.csv', list(per_rx[0]), per_rx)
        atomic_json(stage / 'selected_hyperparameters.json', selected)
        atomic_json(stage / 'combined_manifest.json', manifest)
        output_hashes = {name: sha(stage / name) for name in ('run_summary.csv', 'per_rx_metrics.csv', 'selected_hyperparameters.json', 'combined_manifest.json')}
        atomic_json(stage / 'validation_summary.json', {
            'status': 'PASS', 'job_execution_passed': True, 'aggregation_complete': True, 'release_ready': True,
            'validated_runs': source_info['validated_runs'], 'expected_runs': source_info['expected_runs'],
            'source_artifact_hashes_verified': True, 'output_hashes': output_hashes,
        })
        atomic_promote_files({stage / name: out / name for name in (*output_hashes, 'validation_summary.json')})
    return {**manifest, 'status': 'PASS', 'job_execution_passed': True, 'aggregation_complete': True, 'release_ready': True, 'output_hashes': output_hashes}


def _csv_rows_for_validation(fields: list[str], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{field: '' if row.get(field) is None else str(row.get(field)) for field in fields} for row in rows]


def validate_existing_combined_aggregate(data: Data) -> dict[str, Any]:
    source_info = validate_combined_sources(data)
    if not source_info['passed']:
        return source_info
    out = data.exp / 'results/classical_ml_combined_v1'
    required = [out / name for name in ('combined_manifest.json', 'run_summary.csv', 'per_rx_metrics.csv', 'selected_hyperparameters.json', 'validation_summary.json')]
    missing = [str(path.relative_to(data.exp)) for path in required if not path.is_file()]
    if missing:
        return {'status': 'INCOMPLETE', 'passed': False, 'job_execution_passed': True, 'aggregation_complete': False, 'release_ready': False, 'validated_runs': source_info['validated_runs'], 'expected_runs': source_info['expected_runs'], 'missing_outputs': missing}
    try:
        manifest = json.loads((out / 'combined_manifest.json').read_text())
        expected_manifest = combined_manifest_for(data, source_info)
        if manifest != expected_manifest:
            raise Error('combined manifest does not match current source inventory/configuration')
        summary = json.loads((out / 'validation_summary.json').read_text())
        expected_hash_names = {'run_summary.csv', 'per_rx_metrics.csv', 'selected_hyperparameters.json', 'combined_manifest.json'}
        if set(summary.get('output_hashes', {})) != expected_hash_names:
            raise Error('combined validation summary has incomplete output hashes')
        for name in expected_hash_names:
            if sha(out / name) != summary['output_hashes'][name]:
                raise Error(f'combined output hash mismatch: {name}')
        summaries = source_info['summaries']
        if read_csv(out / 'run_summary.csv') != _csv_rows_for_validation(list(summaries[0]), summaries):
            raise Error('combined run summary does not match source runs')
        per_rx = source_info['per_rx']
        if read_csv(out / 'per_rx_metrics.csv') != _csv_rows_for_validation(list(per_rx[0]), per_rx):
            raise Error('combined per-RX metrics do not match source runs')
        if json.loads((out / 'selected_hyperparameters.json').read_text()) != source_info['selected']:
            raise Error('combined selected hyperparameters do not match source runs')
        if summary.get('status') != 'PASS' or summary.get('validated_runs') != source_info['expected_runs'] or summary.get('expected_runs') != source_info['expected_runs'] or summary.get('source_artifact_hashes_verified') is not True:
            raise Error('combined validation summary is not a complete PASS')
    except (Error, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {'status': 'INCOMPLETE', 'passed': False, 'job_execution_passed': True, 'aggregation_complete': False, 'release_ready': False, 'validated_runs': source_info['validated_runs'], 'expected_runs': source_info['expected_runs'], 'error': str(exc)}
    return {'status': 'PASS', 'passed': True, 'job_execution_passed': True, 'aggregation_complete': True, 'release_ready': True, 'validated_runs': source_info['validated_runs'], 'expected_runs': source_info['expected_runs'], 'source_artifact_hashes_verified': True, 'output_directory': str(out)}


def aggregate_combined(data: Data, validate_only: bool = False) -> dict[str, Any]:
    if validate_only:
        return validate_existing_combined_aggregate(data)
    return build_combined_aggregate(data)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path.cwd())
    ap.add_argument('--experiment-root', type=Path, help='Run root containing features/, beam_results/, and results/.')
    ap.add_argument('--task', choices=TASKS)
    ap.add_argument('--view', choices=VIEWS)
    ap.add_argument('--model', choices=MODELS)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--run-all', action='store_true')
    mode.add_argument('--validate-only', action='store_true')
    mode.add_argument('--aggregate-combined', action='store_true')
    mode.add_argument('--validate-combined', action='store_true')
    ap.add_argument('--validate-results', action='store_true')
    ap.add_argument('--validation-scope', choices=('single_job', 'model_family', 'combined_release'), default='model_family')
    ap.add_argument('--force', action='store_true', help='Replace artifacts only for one explicit task/view/model job.')
    a = ap.parse_args()
    data = Data(a.root, a.experiment_root)
    if a.aggregate_combined:
        print(json.dumps(aggregate_combined(data), sort_keys=True))
        return
    if a.validate_combined:
        print(json.dumps(aggregate_combined(data, validate_only=True), sort_keys=True))
        return
    if a.validate_only:
        print(json.dumps(validate_only(data), sort_keys=True))
        return
    if a.smoke:
        if any(value is not None for value in (a.task, a.view, a.model)) and not all(value is not None for value in (a.task, a.view, a.model)):
            raise Error('--smoke accepts either no task/view/model or all three')
        if a.model in ('rbf_svm', 'xgboost') and not (a.task and a.view):
            raise Error('--smoke for rbf_svm or xgboost requires explicit --task and --view')
        jobs = [(a.task or 'y_path_change', a.view or 'G', a.model or 'logistic_regression')]
        out = output_root(data, jobs[0][2], smoke=True)
    elif a.run_all:
        selected_models = (a.model,) if a.model else V4_MODELS
        jobs = [(t, v, m) for m in selected_models for t in TASKS for v in VIEWS]
        out = output_root(data, selected_models[0]) if len(selected_models) == 1 else None
    else:
        if not (a.task and a.view and a.model):
            if a.validate_results:
                jobs = None
                out = output_root(data, a.model or 'logistic_regression')
            else:
                raise Error('provide --task --view --model, --smoke, --run-all, --validate-only, or --validate-results')
        else:
            jobs = [(a.task, a.view, a.model)]
            out = output_root(data, a.model)
    if a.force and (a.run_all or jobs is None or len(jobs) != 1):
        raise Error('--force is allowed only for one explicit --task --view --model job')
    if a.validate_results:
        if out is None:
            raise Error('--validate-results requires one --model when used with --run-all')
        if a.validation_scope == 'combined_release':
            raise Error('use --validate-combined for combined_release validation')
        print(json.dumps(validate_results(data, out, jobs, scope=a.validation_scope), sort_keys=True))
        return
    require_sklearn()
    if any(model == 'xgboost' for _, _, model in jobs):
        require_xgboost()
    validation = validate_only(data)
    roots = {model: output_root(data, model, smoke=a.smoke) for _, _, model in jobs}
    processed_roots: set[Path] = set()
    invocation_contexts: dict[Path, dict[str, Any]] = {}
    for model, root in roots.items():
        if root in processed_roots:
            continue
        processed_roots.add(root)
        jobs_for_root = [job for job in jobs if roots[job[2]] == root]
        root_family = model_family(model)
        version = VERSION if model in V4_MODELS else RBF_VERSION if model == 'rbf_svm' else XGBOOST_VERSION
        manifest = root / 'experiment_manifest.json'
        fold_file = root / 'temporal_cv_folds.json'
        canonical = canonical_manifest_payload(
            experiment_identity={'experiment_name': data.exp.parent.name, 'run_id': data.exp.name, 'model_family': root_family},
            expected_jobs=family_jobs(root_family),
            input_hashes=data.input_hashes,
            scientific_configuration=scientific_configuration(root_family),
            implementation_version=version,
            seed=SEED,
        )
        try:
            write_canonical_manifest(manifest, canonical)
            invocation_id = new_invocation_id()
            invocation = invocation_manifest_payload(
                invocation_id=invocation_id,
                requested_jobs=jobs_for_root,
                normalized_cli_args=normalize_cli_args(vars(a)),
                execution_source_hashes=execution_source_hashes(model),
                dependency_versions=dependency_versions_for(root_family),
                command_mode='smoke' if a.smoke else 'run_all' if a.run_all else 'single',
                canonical_manifest_sha256=sha(manifest),
                input_hashes=data.input_hashes,
                status='started',
            )
            write_invocation_manifest(root / 'invocations', invocation)
            invocation_contexts[root] = {
                'invocation_id': invocation_id,
                'requested_jobs': jobs_for_root,
                'normalized_cli_args': normalize_cli_args(vars(a)),
                'execution_source_hashes': execution_source_hashes(model),
                'dependency_versions': dependency_versions_for(root_family),
                'command_mode': 'smoke' if a.smoke else 'run_all' if a.run_all else 'single',
                'canonical_manifest_sha256': sha(manifest),
                'input_hashes': data.input_hashes,
                'timestamp_utc': invocation['timestamp_utc'],
                'completed_jobs': [],
                'resumed_jobs': [],
                'failed_jobs': [],
            }
        except Exception as exc:
            raise Error(str(exc)) from exc
        if model != 'rbf_svm' or a.smoke or not fold_file.exists():
            atomic_json(fold_file, validation['temporal_cv_folds'])
    for number, (task, view, model) in enumerate(jobs, start=1):
        out = roots[model]
        context = invocation_contexts[out]
        job = (task, view, model)
        try:
            validate_completed(data, out, task, view, model)
            context['completed_jobs'].append(job)
            context['resumed_jobs'].append(job)
            print(f'[ablation] job={number}/{len(jobs)} task={task} view={view} model={model} status=resumed elapsed_seconds=0.000', flush=True)
        except Error as exc:
            try:
                paths = run_paths(out, task, view, model)
                if paths['run'].exists() or paths['prediction'].exists() or paths['oof'].exists():
                    if not a.force:
                        raise Error(f'invalid existing run for {task}/{view}/{model}: {exc}; refuse to overwrite without --force') from exc
                    for path in paths.values():
                        if path.exists():
                            path.unlink()
                metadata = {
                    'invocation_id': context['invocation_id'],
                    'invocation_manifest': f"invocations/{context['invocation_id']}.json",
                    'execution_source_hashes': context['execution_source_hashes'],
                    'dependency_versions': context['dependency_versions'],
                    'created_at_utc': context['timestamp_utc'],
                    'job_identity': list(job),
                    'execution_status': 'generated',
                }
                run_one(data, task, view, model, out, a.smoke, number, len(jobs), metadata)
                validate_completed(data, out, task, view, model, check_invocation_binding=False)
                context['completed_jobs'].append(job)
            except Exception:
                context['failed_jobs'].append(job)
                failed = invocation_manifest_payload(
                    invocation_id=context['invocation_id'],
                    requested_jobs=context['requested_jobs'],
                    normalized_cli_args=context['normalized_cli_args'],
                    execution_source_hashes=context['execution_source_hashes'],
                    dependency_versions=context['dependency_versions'],
                    command_mode=context['command_mode'],
                    canonical_manifest_sha256=context['canonical_manifest_sha256'],
                    input_hashes=context['input_hashes'],
                    timestamp_utc=context['timestamp_utc'],
                    status='failed',
                    completed_jobs=context['completed_jobs'],
                    resumed_jobs=context['resumed_jobs'],
                    failed_jobs=context['failed_jobs'],
                )
                write_invocation_manifest(out / 'invocations', failed)
                raise
    for root, context in invocation_contexts.items():
        completed = invocation_manifest_payload(
            invocation_id=context['invocation_id'],
            requested_jobs=context['requested_jobs'],
            normalized_cli_args=context['normalized_cli_args'],
            execution_source_hashes=context['execution_source_hashes'],
            dependency_versions=context['dependency_versions'],
            command_mode=context['command_mode'],
            canonical_manifest_sha256=context['canonical_manifest_sha256'],
            input_hashes=context['input_hashes'],
            timestamp_utc=context['timestamp_utc'],
            status='completed',
            completed_jobs=context['completed_jobs'],
            resumed_jobs=context['resumed_jobs'],
            failed_jobs=(),
        )
        write_invocation_manifest(root / 'invocations', completed)
    aggregation_reports = {}
    aggregated_roots: set[Path] = set()
    for model, root in roots.items():
        if root in aggregated_roots:
            continue
        aggregated_roots.add(root)
        if model == 'rbf_svm':
            report = rbf_reference().aggregate_results(data, root, require_complete=False)
        else:
            report = aggregate_results(data, root, require_complete=False)
        aggregation_reports[str(root)] = report
    aggregation_complete = all(bool(report.get('aggregation_complete', report.get('passed'))) for report in aggregation_reports.values())
    print(json.dumps({
        'result': 'PASS' if aggregation_complete else 'INCOMPLETE',
        'job_execution_passed': True,
        'aggregation_complete': aggregation_complete,
        'release_ready': aggregation_complete,
        'output_roots': {model: str(root) for model, root in roots.items()},
        'aggregation_reports': aggregation_reports,
        'runs': len(jobs), 'smoke': a.smoke,
    }, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except (Error, InventoryValidationError) as e:
        raise SystemExit(f'ERROR: {e}')
