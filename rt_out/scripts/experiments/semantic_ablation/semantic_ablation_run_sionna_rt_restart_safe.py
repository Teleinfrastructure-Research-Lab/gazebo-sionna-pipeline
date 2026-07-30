#!/usr/bin/env python3
"""Restart-safe composed-scene, Sionna XML, and multi-RX RT batch runner."""
from __future__ import annotations
import argparse, csv, json, math, os, subprocess, sys, time
from pathlib import Path
from typing import Any
SCRIPTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / 'composition'))
from runtime_config import PROJECT_ROOT, find_sionna_python, runtime_env
from compose_frame_manifests_batch import composed_manifest_path
from rt.run_rt_multi_rx_batch import load_experiment_config, TAU_STATS_SCRIPT
N = 2446
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
TX = (0.0, 0.0, 2.4)
RX_POS = ((0.582, 0.888, 1.195), (0.497, -0.841, 0.995), (4.074, -1.779, 0.81), (-0.1337, 2.748, 0.7), (-1.4605, -0.8406, 1.6421), (-3.9279, 3.2024, 1.3944))
FIELDS = ['frame_id', 'source_sample_index', 'timestamp', 'rx_id', 'xml_path', 'tx_power_dbm', 'tx_x', 'tx_y', 'tx_z', 'rx_x', 'rx_y', 'rx_z', 'frequency_hz', 'num_paths', 'tau_min', 'tau_max', 'delay_spread', 'path_gain_sum', 'path_gain_db', 'rx_power_dbm', 'gain_method', 'gain_error', 'a_shape', 'tau_cir_shape', 'valid_shape', 'tau_shape', 'gain_debug', 'sanity_ok', 'error_message']
SOLVER_SETTINGS = {'max_depth': 2, 'max_num_paths_per_src': 10000, 'samples_per_src': 20000, 'synthetic_array': True, 'los': True, 'specular_reflection': True, 'diffuse_reflection': False, 'refraction': False, 'seed': 42}
STATIC_MANIFEST_RELATIVE_PATH = Path('geometry/static/export/merged_static_manifest.json')

class Error(RuntimeError):
    pass

def resolve_static_manifest(run_root: Path) -> Path:
    path = (run_root / STATIC_MANIFEST_RELATIVE_PATH).resolve()
    if not path.is_file():
        raise Error(f'missing static manifest; expected path: {path}')
    return path

def read(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        raise Error(f'invalid JSON {path}: {e}') from e

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(tmp, path)

def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

def atomic_table(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

def expected() -> range:
    return range(N)

def dyn(root: Path, f: int) -> Path:
    return root / f'frames/dynamic_meshes/frame_{f:03d}/dynamic_frame_{f:03d}_manifest.json'

def actor(root: Path, f: int) -> Path:
    return root / f'frames/actor_meshes/frame_{f:03d}/actor_frame_{f:03d}_manifest.json'

def composed(root: Path, f: int) -> Path:
    return composed_manifest_path(root, f)

def xml(root: Path, f: int) -> Path:
    return root / f'sionna_xml/frame_{f:03d}_sionna.xml'

def run_relative_path(root: Path, path: Path, label: str) -> str:
    root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise Error(f'{label} is outside the selected run root: {resolved}') from exc

def generated_index_rows(root: Path, frame_ids: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    composed_rows = []
    xml_rows = []
    for f in frame_ids:
        composed_path = composed(root, f)
        xml_path = xml(root, f)
        composed_relative = run_relative_path(root, composed_path, 'composed_manifest_path')
        xml_relative = run_relative_path(root, xml_path, 'xml_path')
        composed_rows.append({'frame_id': f, 'source_sample_index': f, 'composed_manifest_path': composed_relative})
        xml_rows.append({'frame_id': f, 'source_sample_index': f, 'composed_manifest_path': composed_relative, 'xml_path': xml_relative})
    return composed_rows, xml_rows

def rowfile(root: Path, f: int) -> Path:
    return root / f'rt_results/staging/frame_{f:03d}.csv'

def sample_metadata(root: Path) -> dict[int, tuple[int, float]]:
    samples = read(root / 'frames/sampled_frames.json').get('frames', [])
    visual = read(root / 'frames/dynamic_visual_frames.json').get('frames', [])
    if [x.get('frame_id') for x in samples] != list(expected()) or [x.get('frame_id') for x in visual] != list(expected()):
        raise Error('sampled/dynamic visual frame IDs are not exactly 0..2445')
    result = {}
    for (s, v) in zip(samples, visual, strict=True):
        f = s['frame_id']
        src = v.get('source_sample_index')
        ts = v.get('timestamp', {}).get('seconds')
        if src != f or not isinstance(ts, (int, float)) or isinstance(ts, bool):
            raise Error(f'frame {f}: invalid source_sample_index/timestamp')
        if isinstance(s.get('timestamp'), dict) and s['timestamp'].get('seconds') != ts:
            raise Error(f'frame {f}: sampled timestamp mismatch')
        result[f] = (src, float(ts))
    return result

def resolve_manifest_path(run_root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise Error('manifest mesh path must be a non-empty string')
    try:
        candidate = Path(value).expanduser()
        run_root = run_root.expanduser().resolve()
        if candidate.is_absolute():
            return candidate.resolve()
        resolved = (run_root / candidate).resolve()
        try:
            resolved.relative_to(run_root)
        except ValueError as exc:
            raise Error(f'manifest mesh path escapes run root: {value}') from exc
        return resolved
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise Error(f'invalid manifest mesh path: {value!r}') from exc


def valid_dynamic(path: Path, f: int, run_root: Path) -> bool:
    try:
        d = read(path)
        es = d.get('exported_visuals', [])
        return d.get('frame_id') == f and d.get('source_sample_index') == f and (len(es) == 21) and all((resolve_manifest_path(run_root, x.get('exported_mesh_path')).is_file() for x in es))
    except Error:
        return False

def valid_actor(path: Path, f: int, run_root: Path) -> bool:
    try:
        d = read(path)
        es = d.get('exported_actors', [])
        return d.get('frame_id') == f and d.get('source_sample_index') == f and (len(es) == 1) and resolve_manifest_path(run_root, es[0].get('exported_mesh_path')).is_file()
    except Error:
        return False

def valid_composed(path: Path, f: int, run_root: Path) -> bool:
    try:
        d = read(path)
        es = d.get('entries', [])
        return d.get('frame_id') == f and d.get('source_sample_index') == f and ((d.get('static_count'), d.get('dynamic_count'), d.get('actor_count'), d.get('total_count')) == (11, 21, 1, 33)) and (len(es) == 33) and all((resolve_manifest_path(run_root, x.get('mesh_path')).is_file() for x in es))
    except Error:
        return False

def valid_xml(path: Path, f: int) -> bool:
    return path.is_file() and path.stat().st_size > 0 and (f'frame{f}' in path.read_text(errors='ignore'))

def valid_rows(path: Path, f: int, src: int, ts: float) -> list[dict[str, Any]] | None:
    try:
        with path.open(newline='') as h:
            rows = list(csv.DictReader(h))
        if len(rows) != 6 or [x.get('rx_id') for x in rows] != list(RX):
            return None
        for r in rows:
            if int(r['frame_id']) != f or int(r['source_sample_index']) != src or float(r['timestamp']) != ts or (r['sanity_ok'] not in ('True', True)):
                return None
            for k in ('num_paths', 'tau_min', 'tau_max', 'delay_spread', 'path_gain_sum', 'path_gain_db', 'rx_power_dbm'):
                if not math.isfinite(float(r[k])):
                    return None
        return rows
    except Exception:
        return None

def one_solve(*, f: int, src: int, ts: float, scene: Path, exp: dict[str, Any], rx: dict[str, Any], py: Path, env: dict[str, str]) -> dict[str, Any]:
    """Run exactly one PathSolver; TAU_STATS_SCRIPT performs solve + CIR extraction."""
    vec = lambda p: ','.join((str(x) for x in p))
    result = subprocess.run([str(py), '-c', TAU_STATS_SCRIPT, str(scene), str(exp['frequency_hz']), vec(exp['tx_position']), vec(rx['position'])], cwd=PROJECT_ROOT, env=env, text=True, capture_output=True)
    payload = None
    for line in result.stdout.splitlines():
        if line.startswith('RESULT_JSON '):
            payload = json.loads(line[12:])
    error = ''
    if result.returncode or not isinstance(payload, dict):
        error = (result.stderr or result.stdout or 'missing RESULT_JSON')[-1000:]
    else:
        required = ('num_paths', 'tau_min', 'tau_max', 'path_gain_sum', 'path_gain_db')
        if payload.get('gain_error') or int(payload.get('num_paths') or 0) <= 0 or any((not isinstance(payload.get(k), (int, float)) or not math.isfinite(float(payload[k])) for k in required[1:])):
            error = 'missing paths, CIR failure, or non-finite required metric'
    ok = not error
    tau_min = payload.get('tau_min') if payload else ''
    tau_max = payload.get('tau_max') if payload else ''
    gain = payload.get('path_gain_db') if payload else ''
    return {'frame_id': f, 'source_sample_index': src, 'timestamp': ts, 'rx_id': rx['id'], 'xml_path': str(scene), 'tx_power_dbm': exp['tx_power_dbm'], 'tx_x': exp['tx_position'][0], 'tx_y': exp['tx_position'][1], 'tx_z': exp['tx_position'][2], 'rx_x': rx['position'][0], 'rx_y': rx['position'][1], 'rx_z': rx['position'][2], 'frequency_hz': exp['frequency_hz'], 'num_paths': payload.get('num_paths', '') if payload else '', 'tau_min': tau_min, 'tau_max': tau_max, 'delay_spread': float(tau_max) - float(tau_min) if ok else '', 'path_gain_sum': payload.get('path_gain_sum', '') if payload else '', 'path_gain_db': gain, 'rx_power_dbm': float(exp['tx_power_dbm']) + float(gain) if ok else '', 'gain_method': payload.get('gain_method', '') if payload else '', 'gain_error': payload.get('gain_error', '') if payload else '', 'a_shape': json.dumps(payload.get('a_shape')) if payload else '', 'tau_cir_shape': json.dumps(payload.get('tau_cir_shape')) if payload else '', 'valid_shape': json.dumps(payload.get('valid_shape')) if payload else '', 'tau_shape': json.dumps(payload.get('tau_shape')) if payload else '', 'gain_debug': payload.get('gain_debug', '') if payload else '', 'sanity_ok': ok, 'error_message': error}

def run(cmd: list[str], name: str, metrics: dict[str, Any]) -> None:
    started = time.monotonic()
    r = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True)
    metrics['stages'].setdefault(name, {'wall_seconds': 0.0, 'runs': 0, 'failures': 0})
    m = metrics['stages'][name]
    m['wall_seconds'] += time.monotonic() - started
    m['runs'] += 1
    if r.returncode:
        m['failures'] += 1
        raise Error(f'{name} failed: {r.stderr[-1000:]}')

def compose_frame_command(root: Path, frame_id: int, static_manifest: Path | None = None) -> list[str]:
    manifest = static_manifest or resolve_static_manifest(root)
    return [
        sys.executable,
        str(SCRIPTS / 'dynamic_rigid/compose_frame_scene.py'),
        '--frame-id', str(frame_id),
        '--static-manifest', str(manifest),
        '--dynamic-manifest', str(dyn(root, frame_id)),
        '--actor-frame-manifest', str(actor(root, frame_id)),
        '--output-manifest', str(composed(root, frame_id)),
    ]

def preflight(root: Path) -> dict[str, Any]:
    meta = sample_metadata(root)
    e = load_experiment_config(root / 'config/experiment_config.json')
    if e['num_frames'] != N or tuple(e['tx_position']) != TX or e['frequency_hz'] != 28000000000.0 or ([x['id'] for x in e['rx_list']] != list(RX)) or ([tuple(x['position']) for x in e['rx_list']] != list(RX_POS)):
        raise Error('non-canonical TX/RX coordinates, frequency, receiver order, or frame count')
    counts = {'dynamic_manifests': sum((valid_dynamic(dyn(root, f), f, root) for f in expected())), 'actor_manifests': sum((valid_actor(actor(root, f), f, root) for f in expected())), 'composed_manifests': sum((valid_composed(composed(root, f), f, root) for f in expected())), 'sionna_xml': sum((valid_xml(xml(root, f), f) for f in expected()))}
    for k in ('dynamic_manifests', 'actor_manifests'):
        if counts[k] != N:
            raise Error(f'{k} valid={counts[k]}, expected {N}')
    return {'preflight': 'PASS', 'frames': N, 'receivers': list(RX), 'counts': counts, 'rt_rows_expected': N * 6, 'actor_timing': 'model-based sampling; runtime-perfect actor phase alignment is not claimed'}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--preflight', action='store_true')
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--probe-frame', type=int)
    ap.add_argument('--probe-rx')
    ap.add_argument('--sionna-python', type=Path)
    a = ap.parse_args()
    probe = a.probe_frame is not None or a.probe_rx is not None
    if (a.probe_frame is None) != (a.probe_rx is None) or sum((bool(x) for x in (a.preflight, a.run, probe))) != 1:
        raise Error('choose --preflight, --run, or both --probe-frame and --probe-rx')
    root = a.root.resolve()
    static_manifest = resolve_static_manifest(root)
    summary = preflight(root)
    if a.preflight:
        print(json.dumps(summary, sort_keys=True))
        return
    exp = load_experiment_config(root / 'config/experiment_config.json')
    py = find_sionna_python(a.sionna_python)
    env = runtime_env()
    if probe:
        if a.probe_frame not in expected() or a.probe_rx not in RX:
            raise Error('probe frame/RX is not canonical')
        rx = next((x for x in exp['rx_list'] if x['id'] == a.probe_rx))
        (src, ts) = sample_metadata(root)[a.probe_frame]
        if not valid_xml(xml(root, a.probe_frame), a.probe_frame):
            raise Error('probe XML is not valid')
        row = one_solve(f=a.probe_frame, src=src, ts=ts, scene=xml(root, a.probe_frame), exp=exp, rx=rx, py=py, env=env)
        if not row['sanity_ok']:
            raise Error(f"probe failed: {row['error_message']}")
        print(json.dumps({'probe': 'PASS', 'frame_id': a.probe_frame, 'rx_name': a.probe_rx, 'tx': exp['tx_position'], 'rx': rx['position'], 'frequency_hz': exp['frequency_hz'], 'receiver_order': list(RX), 'solver_settings': SOLVER_SETTINGS, 'metrics': {k: row[k] for k in ('num_paths', 'tau_min', 'tau_max', 'delay_spread', 'path_gain_sum', 'path_gain_db', 'rx_power_dbm', 'a_shape', 'tau_cir_shape', 'valid_shape', 'tau_shape')}}, sort_keys=True))
        return
    meta = sample_metadata(root)
    metrics = {'stages': {}, 'started_unix': time.time(), 'expected_rows': N * 6}
    cfg = root / 'config/experiment_config.json'
    for f in expected():
        if not valid_composed(composed(root, f), f, root):
            if composed(root, f).exists():
                raise Error(f'invalid composed manifest {composed(root, f)}')
            run(compose_frame_command(root, f, static_manifest), 'compose', metrics)
        if not valid_xml(xml(root, f), f):
            if xml(root, f).exists():
                raise Error(f'invalid XML {xml(root, f)}')
            run([sys.executable, str(SCRIPTS / 'dynamic_rigid/build_frame_sionna_xml.py'), '--frame-id', str(f), '--input-manifest', str(composed(root, f)), '--output-xml', str(xml(root, f))], 'xml', metrics)
    if any((not valid_composed(composed(root, f), f, root) or not valid_xml(xml(root, f), f) for f in expected())):
        raise Error('composed/XML final validation failed')
    composed_index = root / 'frames/composed_manifests/composed_manifest_index.csv'
    xml_index = root / 'sionna_xml/sionna_xml_index.csv'
    composed_rows, xml_rows = generated_index_rows(root, expected())
    if not composed_index.exists():
        atomic_table(composed_index, ['frame_id', 'source_sample_index', 'composed_manifest_path'], composed_rows)
    if not xml_index.exists():
        atomic_table(xml_index, ['frame_id', 'source_sample_index', 'composed_manifest_path', 'xml_path'], xml_rows)
    allrows = []
    resumed = new = 0
    for f in expected():
        (src, ts) = meta[f]
        existing = valid_rows(rowfile(root, f), f, src, ts)
        if existing is not None:
            allrows += existing
            resumed += 6
            continue
        if rowfile(root, f).exists():
            raise Error(f'invalid RT chunk {rowfile(root, f)}')
        rows = []
        started = time.monotonic()
        for rx in exp['rx_list']:
            r = one_solve(f=f, src=src, ts=ts, scene=xml(root, f), exp=exp, rx=rx, py=py, env=env)
            if not r['sanity_ok']:
                raise Error(f"RT frame={f} rx={rx['id']} failed: {r['error_message']}")
            rows.append(r)
        atomic_csv(rowfile(root, f), rows)
        checked = valid_rows(rowfile(root, f), f, src, ts)
        if checked is None:
            raise Error(f'generated invalid RT chunk frame {f}')
        allrows += checked
        new += 6
        metrics['stages'].setdefault('rt', {'wall_seconds': 0.0, 'runs': 0, 'failures': 0})
        metrics['stages']['rt']['wall_seconds'] += time.monotonic() - started
        metrics['stages']['rt']['runs'] += 1
        if (f + 1) % 10 == 0:
            print(f'[rt] completed_frames={f + 1}/{N} resumed_rows={resumed} new_rows={new}', flush=True)
    if len(allrows) != N * 6:
        raise Error('RT final row count mismatch')
    allrows.sort(key=lambda r: (int(r['frame_id']), RX.index(r['rx_id'])))
    final = root / 'rt_results' / f'rt_{N}frames_multi_rx.csv'
    if final.exists():
        raise Error(f'refusing to overwrite final RT CSV: {final}')
    atomic_csv(final, allrows)
    metrics.update({'resumed_rows': resumed, 'new_rows': new, 'output_bytes': final.stat().st_size, 'finished_unix': time.time(), 'solver_settings': SOLVER_SETTINGS})
    atomic_json(root / 'rt_results/rt_restart_metrics.json', metrics)
    atomic_json(root / 'rt_results/rt_validation_summary.json', {'passed': True, 'rows': N * 6, 'frames': N, 'receiver_order': list(RX), 'resumed_rows': resumed, 'new_rows': new, 'solver_settings': SOLVER_SETTINGS})
    print(json.dumps({'result': 'PASS', 'rows': N * 6, 'resumed_rows': resumed, 'new_rows': new}))
if __name__ == '__main__':
    try:
        main()
    except Error as e:
        print(f'ERROR: {e}', file=sys.stderr)
        raise SystemExit(1)
