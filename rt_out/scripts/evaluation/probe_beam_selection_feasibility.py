#!/usr/bin/env python3
"""One-scene, one-receiver deterministic 4x4 transmit-beam feasibility probe.

This is isolated from the canonical RT CSV/staging artifacts. It deliberately
solves one existing XML twice so the public Sionna Paths tensors and deterministic
beam post-processing can be checked before any batch beam experiment is scoped.
"""
from __future__ import annotations
import argparse, json, math, os, sys
from pathlib import Path
from typing import Any
import numpy as np
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
SOLVER = {'max_depth': 2, 'max_num_paths_per_src': 10000, 'samples_per_src': 20000, 'synthetic_array': True, 'los': True, 'specular_reflection': True, 'diffuse_reflection': False, 'refraction': False, 'seed': 42}
FREQUENCY_HZ = 28000000000.0
TX_ORIENTATION_RAD = (0.0, 0.0, 0.0)
PHASE_RELATIVE_ERROR_TOLERANCE = 0.0001
DETERMINISM_ATOL = 1e-07
DETERMINISM_RTOL = 1e-06

class Error(RuntimeError):
    pass

def read(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception as e:
        raise Error(f'invalid JSON {p}: {e}') from e

def atomic_json(p: Path, value: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + '.tmp')
    t.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(t, p)

def array(value: Any) -> np.ndarray:
    if hasattr(value, 'numpy'):
        value = value.numpy()
    return np.asarray(value)

def shape(value: Any) -> list[int]:
    return list(array(value).shape)

def finite_complex(a: np.ndarray) -> bool:
    return bool(np.isfinite(a.real).all() and np.isfinite(a.imag).all())

def config(root: Path, rx_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    c = read(root / 'config/experiment_config.json')
    if c.get('num_frames') != 2446 or c.get('frequency_ghz') != 28 or c.get('tx', {}).get('position') != [0.0, 0.0, 2.4]:
        raise Error('non-canonical experiment configuration')
    if [x.get('id') for x in c.get('rx_list', [])] != list(RX):
        raise Error('canonical RX order mismatch')
    rx = next((x for x in c['rx_list'] if x['id'] == rx_id), None)
    if rx is None:
        raise Error('unknown canonical RX')
    return (c, rx)

def dft_codebook() -> tuple[np.ndarray, list[dict[str, int]]]:
    """16 unit-norm 2-D DFT beams, rows vertical (z), columns horizontal (y)."""
    w = []
    labels = []
    for vr in range(4):
        for hc in range(4):
            grid = np.fromfunction(lambda r, c: np.exp(2j * np.pi * (vr * r / 4 + hc * c / 4)), (4, 4), dtype=float)
            w.append(grid.reshape(-1, order='F') / 4)
            labels.append({'vertical_dft_index': vr, 'horizontal_dft_index': hc})
    return (np.asarray(w, np.complex128), labels)

def extract(paths: Any) -> dict[str, Any]:
    """Extract exact public Paths tensors without assuming their Python types."""
    required = ('a', 'tau', 'phi_t', 'theta_t', 'valid')
    if any((not hasattr(paths, n) for n in required)):
        raise Error('Sionna Paths API lacks a required public attribute')
    raw_a = paths.a
    if not isinstance(raw_a, (tuple, list)) or len(raw_a) != 2:
        raise Error('Paths.a is not the documented real/imaginary coefficient pair')
    a = array(raw_a[0]).astype(np.float64) + 1j * array(raw_a[1]).astype(np.float64)
    tau = array(paths.tau).astype(np.float64)
    phi = array(paths.phi_t).astype(np.float64)
    theta = array(paths.theta_t).astype(np.float64)
    valid = array(paths.valid).astype(bool)
    if a.ndim < 2 or a.shape[-1] < 1:
        raise Error(f'unexpected coefficient tensor shape {a.shape}')
    p = a.shape[-1]
    if any((x.shape[-1] != p for x in (tau, phi, theta, valid))):
        raise Error('path tensor path axes disagree')
    tx_ant = a.shape[-2]
    if tx_ant != 16:
        raise Error(f'synthetic 4x4 TX expected 16 element coefficients, got axis size {tx_ant}')
    coeff = a.reshape((-1, tx_ant, p))[0]
    v = valid.reshape((-1, p))[0]
    t = tau.reshape((-1, p))[0]
    az = phi.reshape((-1, p))[0]
    el = theta.reshape((-1, p))[0]
    if not v.any():
        raise Error('empty valid path mask')
    if not (finite_complex(coeff[:, v]) and np.isfinite(t[v]).all() and np.isfinite(az[v]).all() and np.isfinite(el[v]).all()):
        raise Error('non-finite valid path tensor values')
    return {'coeff': coeff, 'valid': v, 'tau': t, 'phi_t': az, 'theta_t': el, 'shapes': {'a_real': shape(raw_a[0]), 'a_imag': shape(raw_a[1]), 'tau': shape(paths.tau), 'phi_t': shape(paths.phi_t), 'theta_t': shape(paths.theta_t), 'valid': shape(paths.valid)}, 'path_slots': int(p), 'valid_path_count': int(v.sum()), 'tx_element_count': int(tx_ant)}

def angle_response(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Sionna PlanarArray local y-z geometry in wavelengths, column-first order."""
    (rows, cols) = np.meshgrid(np.arange(4), np.arange(4), indexing='ij')
    y = (cols.reshape(-1, order='F') - 1.5) * 0.5
    z = (1.5 - rows.reshape(-1, order='F')) * 0.5
    ky = np.sin(theta) * np.sin(phi)
    kz = np.cos(theta)
    return np.exp(2j * np.pi * (y[:, None] * ky[None, :] + z[:, None] * kz[None, :]))

def phase_consistency(coeff: np.ndarray, response: np.ndarray) -> dict[str, Any]:
    """Validate Sionna synthetic-array element phases up to one scalar/path."""
    candidates = {'exp_positive_j_2pi_r_dot_k': response, 'exp_negative_j_2pi_r_dot_k': np.conjugate(response)}
    tested = {}
    for (convention, theory) in candidates.items():
        relative = []
        phase = []
        for p in range(coeff.shape[1]):
            c = coeff[:, p]
            r = theory[:, p]
            scalar = np.vdot(r, c) / np.vdot(r, r)
            predicted = scalar * r
            relative.append(float(np.linalg.norm(c - predicted) / max(np.linalg.norm(c), 1e-30)))
            keep = np.abs(predicted) > 1e-20
            phase.extend(np.abs(np.angle(c[keep] / predicted[keep])).tolist())
        tested[convention] = {'relative_profile_error_max': float(max(relative)) if relative else math.inf, 'relative_profile_error_mean': float(np.mean(relative)) if relative else math.inf, 'phase_error_rad_max': float(max(phase)) if phase else math.inf, 'phase_error_rad_mean': float(np.mean(phase)) if phase else math.inf}
    selected = min(tested, key=lambda k: tested[k]['relative_profile_error_max'])
    stats = tested[selected]
    if stats['relative_profile_error_max'] > PHASE_RELATIVE_ERROR_TOLERANCE:
        raise Error(f"synthetic-array element order/conjugation validation failed: {stats['relative_profile_error_max']:.3g} > {PHASE_RELATIVE_ERROR_TOLERANCE}")
    return {'element_order': 'Sionna documented column-first, top-left to bottom-right, local y-z plane', 'selected_phase_convention': selected, 'tested_phase_conventions': tested, 'tolerance_relative_profile_error': PHASE_RELATIVE_ERROR_TOLERANCE, 'valid_path_count': int(coeff.shape[1]), 'passed': True}

def solve(xml: Path, tx_pos: list[float], rx_pos: list[float], tx_power_dbm: float) -> dict[str, Any]:
    import sionna
    import mitsuba as mi
    from sionna.rt import PlanarArray, Receiver, Transmitter, PathSolver, load_scene
    try:
        scene = load_scene(str(xml), merge_shapes=False)
    except TypeError:
        scene = load_scene(str(xml))
    scene.frequency = FREQUENCY_HZ
    scene.tx_array = PlanarArray(num_rows=4, num_cols=4, vertical_spacing=0.5, horizontal_spacing=0.5, pattern='iso', polarization='V')
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, pattern='iso', polarization='V')
    tx = Transmitter(name='beam_probe_tx', position=mi.Point3f(*tx_pos))
    rx = Receiver(name='beam_probe_rx', position=mi.Point3f(*rx_pos))
    scene.add(tx)
    scene.add(rx)
    tx.orientation = mi.Point3f(*TX_ORIENTATION_RAD)
    paths = PathSolver()(scene=scene, **SOLVER)
    d = extract(paths)
    (weights, labels) = dft_codebook()
    valid = d['valid']
    channel = np.sum(d['coeff'][:, valid], axis=1)
    voltage = np.conjugate(weights) @ channel
    powers = np.abs(voltage) ** 2
    if not np.isfinite(powers).all() or not np.isfinite(channel.real).all() or (not np.isfinite(channel.imag).all()):
        raise Error('non-finite beam power')
    order = np.argsort(-powers, kind='stable')
    (best, second) = (int(order[0]), int(order[1]))
    tx_mw = 10 ** (tx_power_dbm / 10.0)
    rows = []
    for i in range(16):
        rows.append({'beam_index': i, **labels[i], 'weight_norm': float(np.linalg.norm(weights[i])), 'channel_gain_linear': float(powers[i]), 'received_power_mw': float(powers[i] * tx_mw), 'received_power_dbm': float(tx_power_dbm + 10 * np.log10(powers[i] + 1e-30))})
    steering = angle_response(d['phi_t'][valid], d['theta_t'][valid])
    phase_validation = phase_consistency(d['coeff'][:, valid], steering)
    return {'sionna_version': getattr(sionna, '__version__', 'unknown'), 'path_tensors': {'attributes': ['a', 'tau', 'phi_t', 'theta_t', 'valid'], 'shapes': d['shapes'], 'valid_path_mask': 'valid flattened at the path axis using the first RX/RX-element/TX slice; only true entries contribute', 'path_slots': d['path_slots'], 'valid_path_count': d['valid_path_count'], 'delay_seconds_min': float(d['tau'][valid].min()), 'delay_seconds_max': float(d['tau'][valid].max())}, 'array_response': {'geometry': 'Sionna PlanarArray local y-z plane; column-first 4x4 positions; half-wavelength spacing', 'shape': list(steering.shape), 'uses': 'departure phi_t/theta_t valid paths only', 'phase_validation': phase_validation, 'synthetic_array_postprocess_reusable': True, 'reusability_note': 'Set true only after phase-profile validation. This 4x4 synthetic-array solve exposes a 16-element coefficient axis; canonical 1x1 CSV rows do not retain raw coefficients/angles.'}, 'beam_codebook': {'type': 'deterministic_2d_dft', 'shape': [16, 16], 'num_beams': 16, 'normalization': 'each beam has unit L2 norm', 'beam_index_order': 'vertical DFT index major, horizontal DFT index minor'}, 'per_beam_received_power': {'coherent_path_summation': 'sum valid complex a[element,path] before w^H h; no extra delay phase because the complex carrier coefficients already carry path phase', 'units': 'mW and dBm using canonical transmit power', 'tx_power_dbm': tx_power_dbm, 'beams': rows}, 'selection': {'optimal_beam': rows[best], 'top3': [rows[int(i)] for i in order[:3]], 'best_channel_gain_linear': float(powers[best]), 'second_best_channel_gain_linear': float(powers[second]), 'beam_margin_db': float(10 * np.log10((powers[best] + 1e-30) / (powers[second] + 1e-30)))}, '_determinism': {'channel_real': channel.real.tolist(), 'channel_imag': channel.imag.tolist(), 'powers': powers.tolist()}}

def public(core: dict[str, Any]) -> dict[str, Any]:
    d = dict(core)
    d.pop('_determinism', None)
    return d

def determinism(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    a = np.asarray(first['_determinism']['channel_real']) + 1j * np.asarray(first['_determinism']['channel_imag'])
    b = np.asarray(second['_determinism']['channel_real']) + 1j * np.asarray(second['_determinism']['channel_imag'])
    p = np.asarray(first['_determinism']['powers'])
    q = np.asarray(second['_determinism']['powers'])
    channel_diff = float(np.max(np.abs(a - b))) if len(a) else 0.0
    power_diff = float(np.max(np.abs(p - q))) if len(p) else 0.0
    passed = bool(np.allclose(a, b, atol=DETERMINISM_ATOL, rtol=DETERMINISM_RTOL) and np.allclose(p, q, atol=DETERMINISM_ATOL, rtol=DETERMINISM_RTOL) and (first['path_tensors'] == second['path_tensors']))
    return {'passed': passed, 'atol': DETERMINISM_ATOL, 'rtol': DETERMINISM_RTOL, 'max_absolute_channel_coefficient_difference': channel_diff, 'max_absolute_beam_power_difference': power_diff, 'comparison': 'valid-path channel vector, beam powers, and path tensor metadata'}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--frame-id', type=int, default=0)
    ap.add_argument('--rx-id', default='rx_panda_base', choices=RX)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--validate-only', action='store_true')
    a = ap.parse_args()
    root = Path('rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015').resolve()
    probe = root / 'beam_results/probe'
    out = a.output.resolve() if a.output else probe / f'beam_probe_frame_{a.frame_id:03d}_{a.rx_id}.json'
    try:
        out.relative_to(probe.resolve())
    except ValueError:
        raise Error('output must remain under beam_results/probe')
    if a.frame_id < 0 or a.frame_id >= 2446:
        raise Error('frame-id must be 0..2445')
    if a.validate_only:
        payload = read(out)
        if payload.get('passed') is not True or payload.get('frame_id') != a.frame_id or payload.get('rx_id') != a.rx_id or (len(payload.get('probe', {}).get('per_beam_received_power', {}).get('beams', [])) != 16):
            raise Error('invalid probe output')
        print(json.dumps({'passed': True, 'validate_only': True, 'output': str(out)}, sort_keys=True))
        return
    if out.exists():
        raise Error(f'refusing to overwrite existing probe output: {out}')
    (c, rx) = config(root, a.rx_id)
    xml = root / f'sionna_xml/frame_{a.frame_id:03d}_sionna.xml'
    if not xml.is_file() or xml.stat().st_size == 0:
        raise Error(f'missing existing XML: {xml}')
    tx_power_dbm = float(c.get('tx_power_dbm', 30.0))
    first = solve(xml, c['tx']['position'], rx['position'], tx_power_dbm)
    second = solve(xml, c['tx']['position'], rx['position'], tx_power_dbm)
    repeat = determinism(first, second)
    if not repeat['passed']:
        raise Error('two identical seeded probes exceeded deterministic allclose tolerances')
    payload = {'passed': True, 'frame_id': a.frame_id, 'rx_id': a.rx_id, 'xml_path': str(xml), 'frequency_hz': FREQUENCY_HZ, 'tx_power_dbm': tx_power_dbm, 'tx_position': c['tx']['position'], 'tx_orientation_rad': {'name': 'fixed_world_orientation_alpha_beta_gamma', 'value': list(TX_ORIENTATION_RAD)}, 'rx_position': rx['position'], 'solver_settings': SOLVER, 'determinism': repeat, 'probe': public(first)}
    atomic_json(out, payload)
    print(json.dumps({'passed': True, 'output': str(out), 'optimal_beam': payload['probe']['selection']['optimal_beam']['beam_index'], 'beam_margin_db': payload['probe']['selection']['beam_margin_db']}, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except Error as e:
        print(f'ERROR: {e}', file=sys.stderr)
        raise SystemExit(1)
