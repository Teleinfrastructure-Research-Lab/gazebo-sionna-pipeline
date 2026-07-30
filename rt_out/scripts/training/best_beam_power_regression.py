"""Reusable, leakage-safe best-beam received-power regression support.

The source is the canonical beam-score table, not an RSRP measurement.  It
contains simulated absolute received powers in dBm for each DFT16 beam.
"""
from __future__ import annotations
import csv, json, math, os, tempfile
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np

RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
JOIN_KEYS = ('source_frame_id', 'rx_id')
TARGET_NAME = 'best_beam_received_power_dbm'
TARGET_UNIT = 'dBm'
BEAMS = 16

class RegressionInputError(RuntimeError): pass

def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8') as handle: return list(csv.DictReader(handle))

def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', newline='', encoding='utf-8', dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False) as handle:
            tmp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False) as handle:
            tmp_path = Path(handle.name)
            handle.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

def source_paths(run: Path) -> tuple[Path, Path, Path]:
    root = run / 'beam_results/canonical_4x4_dft16'
    return root / 'beam_scores.csv', root / 'beam_experiment_manifest.json', root / 'best_beam_received_power_targets.csv'

def audit_target(run: Path) -> dict[str, Any]:
    scores, manifest_path, _ = source_paths(run)
    if not scores.is_file() or not manifest_path.is_file(): raise RegressionInputError('canonical beam-score artifact or manifest is missing')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')); rows = _read_csv(scores)
    if not rows: raise RegressionInputError('beam-score table is empty')
    required = {'frame_id','timestamp','rx_id','received_powers_dbm','optimal_beam','best_power_dbm'}
    if set(rows[0]) < required: raise RegressionInputError(f'beam-score fields missing: {sorted(required-set(rows[0]))}')
    powers = [json.loads(row['received_powers_dbm']) for row in rows]
    if any(len(value) != BEAMS or not np.isfinite(np.asarray(value, float)).all() for value in powers): raise RegressionInputError('received_powers_dbm is not finite DFT16 power data')
    target = np.asarray([float(row['best_power_dbm']) for row in rows], float)
    if not np.isfinite(target).all(): raise RegressionInputError('best_power_dbm contains a non-finite value')
    repeated = {str(value): int(count) for value, count in Counter(target.tolist()).items() if count > 1}
    per_rx = {}
    for rx in sorted({row['rx_id'] for row in rows}):
        values = target[[row['rx_id'] == rx for row in rows]]; per_rx[rx] = {'min': float(values.min()), 'max': float(values.max())}
    extreme = (target < -150.0) | (target > 100.0)
    return {'passed': True, 'source_artifact': str(scores), 'source_fields': list(rows[0]), 'target_name': TARGET_NAME, 'target_meaning': 'maximum absolute simulated received power over the DFT16 codebook; not RSRP', 'target_unit': TARGET_UNIT, 'power_kind': 'absolute received power', 'beam_count': BEAMS, 'rows': len(rows), 'frame_range': [min(int(r['frame_id']) for r in rows), max(int(r['frame_id']) for r in rows)], 'rx_ids': sorted({r['rx_id'] for r in rows}), 'join_keys': list(JOIN_KEYS), 'feature_row_difference_explanation': 'beam_scores has all 2446 frames (14676 rows); published feature rows have 2436 frames (14616 rows) because the existing 10-frame/1-second horizon removes source frames 2436..2445.', 'manifest_tx_power_dbm': manifest.get('tx_power_dbm'), 'target_distribution_dbm': {'min': float(target.min()), 'max': float(target.max()), 'mean': float(target.mean()), 'std': float(target.std()), 'quantiles': {str(q): float(np.quantile(target, q)) for q in (.01,.05,.5,.95,.99)}, 'repeated_floor_or_clipping_values': repeated, 'suspicious_extreme_power_count': int(extreme.sum()), 'suspicious_extreme_rule_dbm': 'below -150 or above 100; reported only, never rejected automatically', 'per_rx_target_ranges_dbm': per_rx}}

def build_targets(run: Path) -> tuple[Path, dict[str, Any]]:
    audit = audit_target(run); scores, _, output = source_paths(run); rows = _read_csv(scores); seen = set(); targets = []
    for row in rows:
        key = (int(row['frame_id']), row['rx_id'])
        if key in seen: raise RegressionInputError(f'duplicate frame-RX row: {key}')
        seen.add(key); values = np.asarray(json.loads(row['received_powers_dbm']), dtype=float)
        if values.shape != (BEAMS,): raise RegressionInputError(f'incomplete beam group for {key}: expected {BEAMS}, got {values.size}')
        if not np.isfinite(values).all(): raise RegressionInputError(f'non-finite beam power for {key}')
        best = int(np.argmax(values)); reported = int(row['optimal_beam'])
        if best != reported or not math.isclose(float(values[best]), float(row['best_power_dbm']), rel_tol=1e-10, abs_tol=1e-8): raise RegressionInputError(f'beam-score consistency failure for {key}')
        targets.append({'source_frame_id': key[0], 'timestamp': float(row['timestamp']), 'rx_id': key[1], 'temporal_index': key[0], 'best_beam_index': best, TARGET_NAME: float(values[best]), 'target_unit': TARGET_UNIT, 'source_artifact': str(scores.relative_to(run))})
    fields = ['source_frame_id','timestamp','rx_id','temporal_index','best_beam_index',TARGET_NAME,'target_unit','source_artifact']; _write_csv(output, fields, targets)
    report = dict(audit, target_rows=len(targets), output_artifact=str(output), fields=fields); _write_json(output.with_suffix('.manifest.json'), report)
    return output, report

def temporal_split(rows: list[dict[str, str]], validation_fraction: float = .2) -> dict[str, Any]:
    by_frame: dict[int, set[str]] = {}
    for row in rows: by_frame.setdefault(int(row['source_frame_id']), set()).add(row['split'])
    if any(len(value) != 1 for value in by_frame.values()): raise RegressionInputError('a temporal instant appears in more than one split')
    result = {name: sorted(frame for frame, labels in by_frame.items() if name in labels) for name in ('train','excluded','test')}
    if not result['train'] or not result['test'] or max(result['train']) >= min(result['test']): raise RegressionInputError('published temporal split is not ordered train then test')
    train_frames = result['train']; validation_count = max(1, int(round(len(train_frames) * validation_fraction)))
    if validation_count >= len(train_frames): raise RegressionInputError('training partition is too small for temporal validation')
    fit_frames, validation_frames = train_frames[:-validation_count], train_frames[-validation_count:]
    partitions = {'training': fit_frames, 'validation': validation_frames, 'excluded': result['excluded'], 'test': result['test']}
    if max(fit_frames) >= min(validation_frames) or max(validation_frames) >= min(result['excluded']) or max(result['excluded']) >= min(result['test']): raise RegressionInputError('temporal partition ordering failure')
    return {'splits': {name: {'frames': len(values), 'frame_range': [min(values), max(values)] if values else None, 'rows': sum(1 for row in rows if int(row['source_frame_id']) in set(values))} for name, values in partitions.items()}, 'protocol': 'published whole-frame temporal train/excluded/test split, with the tail of published training reserved as validation; test is untouched until final evaluation'}

def load_aligned(run: Path, requested: list[str] | None = None) -> tuple[dict[str, np.ndarray], list[dict[str, Any]], dict[str, Any]]:
    _, _, target_path = source_paths(run)
    if not target_path.is_file(): raise RegressionInputError('target table missing; run --build-targets first')
    descriptor = run / 'features/classical_ml_descriptor_v2'; index_path = descriptor / 'row_index.csv'
    if not index_path.is_file(): raise RegressionInputError('published descriptor-v2 row index is missing')
    features = requested or [path.stem for path in sorted(descriptor.glob('*.npy')) if path.stem in {'G','GS','GI','GSI'}]
    if not features: raise RegressionInputError('no published canonical geometry feature representations found')
    idx = _read_csv(index_path); targets = _read_csv(target_path); target_map = {(int(row['source_frame_id']), row['rx_id']): row for row in targets}
    if len(target_map) != len(targets): raise RegressionInputError('duplicate target join keys')
    keys = [(int(row['source_frame_id']), row['rx_id']) for row in idx]
    if len(set(keys)) != len(keys): raise RegressionInputError('duplicate feature join keys')
    aligned = []
    for position, (index_row, key) in enumerate(zip(idx, keys, strict=True)):
        if key not in target_map: continue
        target_row = target_map[key]
        merged = dict(target_row); merged.update({'source_frame_id': str(key[0]), 'rx_id': key[1], 'split': index_row['split'], 'row_index': index_row['row_index']})
        if int(merged['row_index']) != position: raise RegressionInputError('array/index alignment failure: row_index is not array position')
        aligned.append(merged)
    unmatched_targets = len(targets)-len(aligned); unmatched_features = len(idx)-len(aligned)
    if unmatched_features: raise RegressionInputError(f'{unmatched_features} feature rows lack targets')
    arrays = {}
    for name in features:
        path = descriptor / f'{name}.npy'
        if not path.is_file(): raise RegressionInputError(f'representation is unavailable: {name}')
        value = np.asarray(np.load(path, mmap_mode='r', allow_pickle=False), dtype=np.float32)
        if value.ndim != 2 or value.shape[0] != len(idx) or not np.isfinite(value).all(): raise RegressionInputError(f'invalid representation: {name}')
        arrays[name] = value
    required_fields = {'source_frame_id','rx_id','split','row_index','timestamp',TARGET_NAME,'best_beam_index'}
    if any(not required_fields.issubset(row) for row in aligned): raise RegressionInputError('aligned rows lack required target/index metadata')
    report = {'source_target_rows': len(targets), 'source_feature_rows': len(idx), 'aligned_rows': len(aligned), 'unmatched_targets': unmatched_targets, 'unmatched_feature_rows': unmatched_features, 'duplicate_target_keys': 0, 'duplicate_feature_keys': 0, 'missing_values': 0, 'feature_counts': {name: int(value.shape[1]) for name,value in arrays.items()}, 'representations': list(arrays), 'join_keys': list(JOIN_KEYS), 'common_aligned_sample_set': True, 'array_index_target_identity_verified': True, 'split': temporal_split(aligned)}
    return arrays, aligned, report

def regression_metrics(y: np.ndarray, prediction: np.ndarray) -> dict[str, float | int]:
    error = np.asarray(y, float) - np.asarray(prediction, float); ss = float(np.sum((y-y.mean())**2))
    return {'mae': float(np.mean(np.abs(error))), 'rmse': float(np.sqrt(np.mean(error**2))), 'r2': float(1-np.sum(error**2)/ss) if ss else float('nan'), 'median_absolute_error': float(np.median(np.abs(error))), 'sample_count': int(len(y))}
