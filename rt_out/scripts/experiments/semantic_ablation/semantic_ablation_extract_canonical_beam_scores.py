#!/usr/bin/env python3
"""Restart-safe 4x4 DFT16 beam-score extraction from existing canonical XMLs."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, json, math, os, sys, time
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np
HERE = Path(__file__).resolve().parent
SCRIPT_ROOT = HERE.parents[1]
ROOT = Path('rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015').resolve()
N = 2446
PROBE_SCRIPT = SCRIPT_ROOT / 'evaluation' / 'probe_beam_selection_feasibility.py'
spec = importlib.util.spec_from_file_location('beam_probe', PROBE_SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
RX = probe.RX
FIELDS = ('frame_id', 'timestamp', 'rx_id', 'valid_path_count', 'channel_gains', 'received_powers_dbm', 'optimal_beam', 'top3_beams', 'best_power_dbm', 'second_best_power_dbm', 'beam_margin_db')
VERSION = 'canonical_4x4_dft16_beam_scores_v2'

class Error(RuntimeError):
    pass

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception as e:
        raise Error(f'invalid JSON {p}: {e}') from e

def atomic_json(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + '.tmp')
    t.write_text(json.dumps(x, indent=2, sort_keys=True) + '\n')
    os.replace(t, p)

def atomic_csv(p: Path, rows: list[dict[str, Any]]) -> None:
    t = p.with_suffix(p.suffix + '.tmp')
    with t.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(t, p)

def atomic_npy(p: Path, a: np.ndarray) -> None:
    t = p.with_suffix(p.suffix + '.tmp')
    with t.open('wb') as h:
        np.save(h, a)
    os.replace(t, p)

def metadata() -> dict[int, float]:
    x = read(ROOT / 'frames/sampled_frames.json').get('frames', [])
    visual = read(ROOT / 'frames/dynamic_visual_frames.json').get('frames', [])
    if [r.get('frame_id') for r in x] != list(range(N)) or [r.get('frame_id') for r in visual] != list(range(N)):
        raise Error('sampled/visual frames are not exactly 0..2445')
    result = {}
    for (r, v) in zip(x, visual, strict=True):
        f = r['frame_id']
        ts = v.get('timestamp', {}).get('seconds')
        source = v.get('source_sample_index')
        if r.get('source_sample', f) != f or source != f or (not isinstance(ts, (int, float))) or (not math.isfinite(float(ts))):
            raise Error(f'frame {f}: invalid canonical metadata')
        result[f] = float(ts)
    return result

def settings() -> dict[str, Any]:
    cfg = read(ROOT / 'config/experiment_config.json')
    if cfg.get('num_frames') != N or cfg.get('frequency_ghz') != 28 or cfg.get('tx', {}).get('position') != [0.0, 0.0, 2.4] or ([r.get('id') for r in cfg.get('rx_list', [])] != list(RX)):
        raise Error('non-canonical beam configuration')
    (w, labels) = probe.dft_codebook()
    if w.shape != (16, 16) or not np.allclose(np.linalg.norm(w, axis=1), 1.0, atol=1e-12):
        raise Error('invalid DFT16 codebook')
    codebook_sha = hashlib.sha256(np.ascontiguousarray(w.view(np.float64)).tobytes()).hexdigest()
    d = {'version': VERSION, 'script_sha256': sha(Path(__file__).resolve()), 'probe_script_sha256': sha(PROBE_SCRIPT), 'frequency_hz': probe.FREQUENCY_HZ, 'tx_position': cfg['tx']['position'], 'tx_orientation_rad': list(probe.TX_ORIENTATION_RAD), 'rx_order': list(RX), 'rx_positions': [r['position'] for r in cfg['rx_list']], 'tx_array': {'rows': 4, 'cols': 4, 'plane': 'y-z', 'element_order': 'column-first', 'spacing_wavelength': 0.5, 'pattern': 'iso', 'polarization': 'V'}, 'rx_array': {'elements': 1, 'pattern': 'iso', 'polarization': 'V'}, 'codebook': {'type': 'unit_norm_2d_dft16', 'phase_convention': 'exp_positive_j_2pi_r_dot_k', 'labels': labels, 'complex_weights_sha256': codebook_sha}, 'solver_settings': probe.SOLVER, 'tx_power_dbm': float(cfg.get('tx_power_dbm', 30.0))}
    d['configuration_sha256'] = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return d

def shard_path(f: int) -> Path:
    return ROOT / 'beam_results/staging' / f'frame_{f:04d}_beam_scores.json'

def path_data(paths: Any) -> tuple[np.ndarray, np.ndarray, dict[str, list[int]]]:
    """Use actual runtime dimensions; only path and TX-element axes are fixed."""
    a = paths.a
    if not isinstance(a, (tuple, list)) or len(a) != 2:
        raise Error('Paths.a is not real/imag pair')
    c = probe.array(a[0]).astype(np.float64) + 1j * probe.array(a[1]).astype(np.float64)
    v = probe.array(paths.valid).astype(bool)
    if c.ndim < 3 or c.shape[0] != 6 or c.shape[-2] != 16:
        raise Error(f'unexpected synthetic-array coefficient shape {c.shape}')
    p = c.shape[-1]
    if v.ndim < 2 or v.shape[0] != 6 or v.shape[-1] != p:
        raise Error(f'unexpected valid tensor shape {v.shape}')
    if any((x != 1 for x in c.shape[1:-2])) or any((x != 1 for x in v.shape[1:-1])):
        raise Error(f'unexpected non-singleton configured tensor axes: coefficients={c.shape}, valid={v.shape}')
    coeff = c.reshape(6, 16, p)
    valid = v.reshape(6, p)
    if not (np.isfinite(coeff.real).all() and np.isfinite(coeff.imag).all()):
        raise Error('non-finite path coefficients')
    return (coeff, valid, {'coefficient_real_imag': list(c.shape), 'valid_mask': list(v.shape), 'per_rx_coefficients': list(coeff.shape), 'per_rx_valid_mask': list(valid.shape)})

def solve_frame(f: int, cfg: dict[str, Any], timestamp: float) -> dict[str, Any]:
    import mitsuba as mi
    from sionna.rt import PlanarArray, Receiver, Transmitter, PathSolver, load_scene
    xml = ROOT / f'sionna_xml/frame_{f:03d}_sionna.xml'
    if not xml.is_file() or xml.stat().st_size == 0:
        raise Error(f'missing XML {xml}')
    try:
        scene = load_scene(str(xml), merge_shapes=False)
    except TypeError:
        scene = load_scene(str(xml))
    scene.frequency = probe.FREQUENCY_HZ
    scene.tx_array = PlanarArray(num_rows=4, num_cols=4, vertical_spacing=0.5, horizontal_spacing=0.5, pattern='iso', polarization='V')
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, pattern='iso', polarization='V')
    tx = Transmitter(name='beam_batch_tx', position=mi.Point3f(*cfg['tx_position']))
    scene.add(tx)
    tx.orientation = mi.Point3f(*probe.TX_ORIENTATION_RAD)
    for (rx_id, pos) in zip(RX, cfg['rx_positions'], strict=True):
        scene.add(Receiver(name=rx_id, position=mi.Point3f(*pos)))
    paths = PathSolver()(scene=scene, **probe.SOLVER)
    (coeff, valid, runtime_shapes) = path_data(paths)
    (weights, _) = probe.dft_codebook()
    rows = []
    for (i, rx_id) in enumerate(RX):
        mask = valid[i]
        if not mask.any():
            raise Error(f'frame {f} {rx_id}: empty valid paths')
        h = np.sum(coeff[i][:, mask], axis=1)
        if h.shape != (16,):
            raise Error(f'frame {f} {rx_id}: channel shape {h.shape}, expected (16,)')
        g = np.abs(np.conjugate(weights) @ h) ** 2
        if not np.isfinite(g).all():
            raise Error(f'frame {f} {rx_id}: non-finite beam gain')
        order = np.argsort(-g, kind='stable')
        dbm = cfg['tx_power_dbm'] + 10 * np.log10(g + 1e-30)
        rows.append({'frame_id': f, 'timestamp': timestamp, 'rx_id': rx_id, 'valid_path_count': int(mask.sum()), 'channel_gains': [float(x) for x in g], 'received_powers_dbm': [float(x) for x in dbm], 'optimal_beam': int(order[0]), 'top3_beams': [int(x) for x in order[:3]], 'best_power_dbm': float(dbm[order[0]]), 'second_best_power_dbm': float(dbm[order[1]]), 'beam_margin_db': float(dbm[order[0]] - dbm[order[1]])})
    return {'version': VERSION, 'configuration_sha256': cfg['configuration_sha256'], 'frame_id': f, 'timestamp': timestamp, 'xml_path': str(xml), 'xml_sha256': sha(xml), 'runtime_tensor_shapes': runtime_shapes, 'rows': rows}

def valid_shard(p: Path, f: int, cfg: dict[str, Any], timestamp: float) -> dict[str, Any] | None:
    try:
        d = read(p)
        rows = d['rows']
        xml = ROOT / f'sionna_xml/frame_{f:03d}_sionna.xml'
        if d.get('version') != VERSION or d.get('configuration_sha256') != cfg['configuration_sha256'] or d.get('frame_id') != f or (float(d.get('timestamp')) != timestamp) or (d.get('xml_path') != str(xml)) or (d.get('xml_sha256') != sha(xml)) or (len(rows) != 6) or ([r.get('rx_id') for r in rows] != list(RX)):
            return None
        shapes = d.get('runtime_tensor_shapes', {})
        if shapes.get('per_rx_coefficients', [])[:2] != [6, 16] or shapes.get('per_rx_valid_mask', [])[:1] != [6]:
            return None
        for r in rows:
            g = np.asarray(r['channel_gains'], float)
            power = np.asarray(r['received_powers_dbm'], float)
            top = r['top3_beams']
            if r.get('frame_id') != f or not np.isclose(float(r.get('timestamp')), timestamp, atol=0.0, rtol=0.0) or g.shape != (16,) or (power.shape != (16,)) or (not np.isfinite(g).all()) or np.any(g < 0) or (not np.isfinite(power).all()) or (int(r['valid_path_count']) < 1):
                return None
            order = np.argsort(-g, kind='stable')
            expected_power = cfg['tx_power_dbm'] + 10 * np.log10(g + 1e-30)
            if len(top) != 3 or len(set(map(int, top))) != 3 or int(r['optimal_beam']) != int(order[0]) or (list(map(int, top)) != list(map(int, order[:3]))) or (not np.allclose(power, expected_power, atol=1e-08, rtol=1e-10)) or (not np.isclose(float(r['best_power_dbm']), power[order[0]], atol=1e-08)) or (not np.isclose(float(r['second_best_power_dbm']), power[order[1]], atol=1e-08)) or (not np.isclose(float(r['beam_margin_db']), power[order[0]] - power[order[1]], atol=1e-08)):
                return None
        return d
    except Exception:
        return None

def publish(cfg: dict[str, Any], meta: dict[int, float]) -> dict[str, Any]:
    final = ROOT / 'beam_results/canonical_4x4_dft16'
    tmp = final.with_name(final.name + '.tmp')
    if final.exists():
        raise Error('refusing to overwrite completed final beam output')
    if tmp.exists():
        raise Error('final temporary publication directory already exists')
    shards = []
    for f in range(N):
        x = valid_shard(shard_path(f), f, cfg, meta[f])
        if x is None:
            raise Error(f'cannot publish: invalid/missing shard {f}')
        shards.extend(x['rows'])
    powers = np.asarray([[r['received_powers_dbm'] for r in shards[i * 6:(i + 1) * 6]] for i in range(N)], np.float64)
    if powers.shape != (N, 6, 16):
        raise Error('final beam tensor shape mismatch')
    tmp.mkdir(parents=True)
    flat = []
    for r in shards:
        flat.append({**r, 'channel_gains': json.dumps(r['channel_gains']), 'received_powers_dbm': json.dumps(r['received_powers_dbm']), 'top3_beams': json.dumps(r['top3_beams'])})
    atomic_csv(tmp / 'beam_scores.csv', flat)
    atomic_npy(tmp / 'beam_powers.npy', powers)
    optimal = np.asarray([[r['optimal_beam'] for r in shards[i * 6:(i + 1) * 6]] for i in range(N)], int)
    margins = np.asarray([[r['beam_margin_db'] for r in shards[i * 6:(i + 1) * 6]] for i in range(N)], float)
    summary = {'passed': True, 'frames': N, 'rows': N * 6, 'beam_powers_shape': list(powers.shape), 'rx_order': list(RX), 'configuration_sha256': cfg['configuration_sha256'], 'optimal_beam_counts_global': {str(k): int(v) for (k, v) in Counter(optimal.ravel()).items()}, 'optimal_beam_counts_per_rx': {RX[i]: {str(k): int(v) for (k, v) in Counter(optimal[:, i]).items()} for i in range(6)}, 'beam_margin_db': {'min': float(margins.min()), 'mean': float(margins.mean()), 'max': float(margins.max())}, 'beam_changes_between_consecutive_frames': {RX[i]: int(np.count_nonzero(optimal[1:, i] != optimal[:-1, i])) for i in range(6)}}
    manifest = {**cfg, 'frames': N, 'rows': N * 6, 'beam_scores_sha256': sha(tmp / 'beam_scores.csv'), 'beam_powers_sha256': sha(tmp / 'beam_powers.npy')}
    atomic_json(tmp / 'beam_experiment_manifest.json', manifest)
    atomic_json(tmp / 'validation_summary.json', summary)
    os.replace(tmp, final)
    return summary

def validate_final(cfg: dict[str, Any]) -> dict[str, Any]:
    final = ROOT / 'beam_results/canonical_4x4_dft16'
    manifest = read(final / 'beam_experiment_manifest.json')
    summary = read(final / 'validation_summary.json')
    if manifest.get('configuration_sha256') != cfg['configuration_sha256'] or manifest.get('frames') != N or manifest.get('rows') != N * 6 or (manifest.get('beam_scores_sha256') != sha(final / 'beam_scores.csv')) or (manifest.get('beam_powers_sha256') != sha(final / 'beam_powers.npy')):
        raise Error('final manifest/hash validation failed')
    with (final / 'beam_scores.csv').open(newline='') as h:
        rows = list(csv.DictReader(h))
    powers = np.load(final / 'beam_powers.npy', mmap_mode='r')
    if len(rows) != N * 6 or tuple(powers.shape) != (N, 6, 16) or (not np.isfinite(powers).all()) or (summary.get('passed') is not True):
        raise Error('final CSV/NPY validation failed')
    if [(int(r['frame_id']), r['rx_id']) for r in rows] != [(f, rx) for f in range(N) for rx in RX]:
        raise Error('final CSV ordering invalid')
    return summary

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--start-frame', type=int, default=0)
    ap.add_argument('--end-frame', type=int, default=N - 1)
    ap.add_argument('--validate-only', action='store_true')
    a = ap.parse_args()
    if not 0 <= a.start_frame <= a.end_frame < N:
        raise Error('invalid inclusive frame range')
    cfg = settings()
    meta = metadata()
    valid = created = 0
    started = time.monotonic()
    total = a.end_frame - a.start_frame + 1
    for f in range(a.start_frame, a.end_frame + 1):
        old = valid_shard(shard_path(f), f, cfg, meta[f])
        if old is not None:
            valid += 1
            print(f'[beam] frame={f} status=resumed completed={f - a.start_frame + 1}/{total} elapsed_seconds={time.monotonic() - started:.3f}', flush=True)
            continue
        if shard_path(f).exists():
            raise Error(f'invalid or configuration-mismatched shard {shard_path(f)}')
        if a.validate_only:
            raise Error(f'missing shard {shard_path(f)}')
        result = solve_frame(f, cfg, meta[f])
        probe.atomic_json(shard_path(f), result)
        if valid_shard(shard_path(f), f, cfg, meta[f]) is None:
            raise Error(f'newly written shard invalid frame {f}')
        created += 1
        print(f'[beam] frame={f} status=created completed={f - a.start_frame + 1}/{total} elapsed_seconds={time.monotonic() - started:.3f}', flush=True)
    if a.start_frame == 0 and a.end_frame == N - 1:
        if a.validate_only:
            summary = validate_final(cfg)
        else:
            summary = publish(cfg, meta)
        print(json.dumps({'passed': True, 'validated_shards': valid, 'created_shards': created, 'final_validation': summary}, sort_keys=True))
        return
    print(json.dumps({'passed': True, 'range': [a.start_frame, a.end_frame], 'valid_shards': valid, 'created_shards': created, 'final_publication': 'not attempted for bounded range'}, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except Error as e:
        print(f'ERROR: {e}', file=sys.stderr)
        raise SystemExit(1)
