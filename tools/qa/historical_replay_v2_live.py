"""Isolated native/source-replay acceptance, explicitly not combat acceptance."""
import argparse
import json
from pathlib import Path
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=18990)
parser.add_argument('--mode', choices=('native', 'dsh'), required=True)
parser.add_argument('--live', action='store_true')
parser.add_argument('--output', type=Path, default=Path('.cache/qa/historical-replay-v2/live'))
args = parser.parse_args()
if not args.live or not 18900 <= args.port <= 18999:
    raise SystemExit('Use --live with an isolated QA port (18900–18999).')
args.output.mkdir(parents=True, exist_ok=True)
base = f'http://127.0.0.1:{args.port}'
result = {'scope': 'pinned source replay and roster references; not combat simulation',
          'mode': args.mode, 'cases': [], 'passed': False}


def call(method, path, data=None):
    request = urllib.request.Request(base + path, method=method,
        data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=1200) as response:
        return json.load(response)


def save():
    (args.output / (args.mode + '-result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))


try:
    health = call('GET', '/api/health')
    assert not health['build']['restart_required'], 'Backend must run current source'
    battles = call('GET', '/api/battles')['battles']
    if args.mode == 'dsh':
        names = ('武汉会战', '徐州会战总览', '冀中五一反扫荡')
        battles = [b for b in battles if any(n in b['name'] for n in names)]
        assert len(battles) == 3
    for index, battle in enumerate(battles, 1):
        started = time.monotonic()
        created = call('POST', '/api/sessions', {'scenario': '版本化来源回放及具名编制核对；不进行交战验收',
            'battle': battle['name'], 'product_mode': 'analysis', 'simulation_mode': 'replay',
            'execution_backend': 'afsim' if args.mode == 'native' else 'narrative', 'persist_roles': False})
        sid = created['session_id']; path = '/api/sessions/' + sid
        initial = call('POST', path + '/init')
        world = initial['war_state']; record = world['history_replay']
        assert record['version'] == 'strict-history-2'
        units = world['red_units'] + world['blue_units']
        assert all(u['lat'] is None and u['lng'] is None for u in units)
        entry = {'battle': battle['name'], 'session_id': sid, 'roster_count': len(units),
                 'source_hash': record['dataset_hash'], 'version': record['version']}
        if args.mode == 'native':
            evidence = world['afsim']
            assert evidence['source'] == 'dsh_native_mcp_controller' and evidence['status'] == 'completed'
            assert evidence['returncode'] == 0 and evidence['combat_entity_count'] == 0
            assert evidence['entity_count'] == len(record['geo_references'])
            assert evidence['historical_roster_count'] == len(units)
            assert evidence['battlefield_initialized'] is False
            entry.update(native_entities=evidence['entity_count'], combat_entities=evidence['combat_entity_count'],
                         process_id=evidence['process_id'], native_version=evidence.get('version'))
        else:
            assert units and 'DSH节点分析' in initial['history'][0]
            assert initial['engine_meta']['finish_reason'] == 'completed'
            assert 'afsim' not in world
        if units:
            after = call('POST', path + '/next', {'expected_turn': 0})
            next_units = after['war_state']['red_units'] + after['war_state']['blue_units']
            assert [u['historical_unit_id'] for u in units] == [u['historical_unit_id'] for u in next_units]
            assert after['war_state']['historical_initial'] == world['historical_initial']
            assert after['war_state']['history_replay']['dataset_hash'] == record['dataset_hash']
            entry['advance_verified'] = True
        (args.output / (args.mode + '-' + sid + '-initial.json')).write_text(json.dumps(initial, ensure_ascii=False))
        entry.update(passed=True, elapsed_seconds=round(time.monotonic() - started, 2))
        result['cases'].append(entry); save()
        print('PASS', index, '/', len(battles), battle['name'], 'roster', len(units), entry['elapsed_seconds'], flush=True)
    result['passed'] = True; save()
except Exception as exc:
    result['error'] = str(exc); save(); raise
