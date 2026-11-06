"""Real AFSIM roundtrips for the catalog; generic initial states are labelled synthetic.

This acceptance does not reconstruct the historical order of battle and never
calls an LLM. Existing versioned teaching initial states are reused where present.
"""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / '.cache/qa/afsim-bridge/catalog')
    args = parser.parse_args(); output = args.out.resolve(); output.mkdir(parents=True, exist_ok=True)
    os.environ.update(GENTACTIX_SESSION_DIR=str(output / 'sessions'), GENTACTIX_TRACE_DIR=str(output / 'traces'),
        GENTACTIX_DSH_HOME=str(output / 'dsh-home'), GENTACTIX_DSH_WORKSPACE=str(output / 'dsh-workspace'),
        GENTACTIX_ROLE_INDEX=str(output / 'roles.json'), GENTACTIX_DSH_PATCHES='[]')
    from backend import main as api, harness_engine as h
    from fastapi.testclient import TestClient
    from gentactix import adjudication_lib, anchors, missions, commands
    client = TestClient(api.app)
    local = {entry['battle']: entry for entry in missions.catalog()}
    results = []
    try:
        for battle in adjudication_lib.list_battles():
            api._SESSIONS.clear(); started = time.monotonic()
            try:
                native = local.get(battle)
                nodes = anchors.collect_available_nodes(battle, battle=battle)
                if not nodes:
                    raise ValueError('战役没有可核验的装载参考点')
                lat, lng = next(iter(nodes.values()))
                fixture = {'current_time': '某日00:00', 'current_terrain': '丘陵森林', 'era': '合成实体适配验收',
                    'red_units': [{'name': '教学红方', 'type': '徒步步兵', 'lat': lat, 'lng': lng, 'hp': 100}],
                    'blue_units': [{'name': '教学蓝方', 'type': '徒步步兵', 'lat': lat + .005, 'lng': lng + .005, 'hp': 100}],
                    'engagements': [], 'center': [lat, lng]}
                request = {'scenario': battle + '；合成实体适配验收，不代表历史编制。', 'battle': battle,
                    'execution_backend': 'afsim', 'time_step': native['time_step'] if native else '15分钟',
                    'mission_id': native['id'] if native else None, 'persist_roles': False}
                response = client.post('/api/sessions', json=request)
                response.raise_for_status(); sid = response.json()['session_id']
                # Only generic initial-state narration is replaced. The external
                # engine and every subsequent control/commit call are real.
                with patch.object(h, 'get_ai_response_with_retry', return_value=fixture):
                    response = client.post(f'/api/sessions/{sid}/init')
                if response.status_code != 200:
                    raise RuntimeError(response.text)
                before = copy.deepcopy(response.json()['war_state'])
                view = client.get(f'/api/sessions/{sid}/commands').json()
                orders = [{'unit_id': unit['id'], 'action': 'hold', 'duration': 'next'} for unit in view['units'] if unit['available']]
                first = next((unit for unit in view['units'] if unit['available'] and unit['capabilities']['move_km'] > .2), None)
                if first:
                    origin = first['position']
                    goal = commands.towards(origin, {'lat': origin['lat'] + .002, 'lng': origin['lng']}, .1)
                    orders = [({'unit_id': first['id'], 'action': 'move', 'duration': 'next', 'destination': goal}
                               if order['unit_id'] == first['id'] else order) for order in orders]
                response = client.put(f'/api/sessions/{sid}/commands', json={'orders': orders,
                    'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version'],
                    'director': True})
                if response.status_code != 200: raise RuntimeError(response.text)
                view = response.json()
                with patch.object(h, 'get_ai_response', side_effect=AssertionError('完整人工批次不应调用模型')):
                    response = client.post(f'/api/sessions/{sid}/next', json={'batch_id': 'catalog-roundtrip',
                        'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']})
                if response.status_code != 200: raise RuntimeError(response.text)
                snapshot = response.json(); after = snapshot['war_state']; evidence = snapshot['afsim']
                assert evidence['source'] == 'dsh_native_mcp_controller' and evidence['status'] == 'completed'
                assert evidence['model_skipped'] is True
                assert len(after['red_units']) == len(before['red_units']) and len(after['blue_units']) == len(before['blue_units'])
                if native:
                    missions.validate(after)
                results.append({'battle': battle, 'passed': True, 'initial_state': 'versioned_teaching' if native else 'synthetic_adapter_fixture',
                    'units': evidence['entity_count'], 'simulation_seconds': evidence['seconds'], 'execution_ms': evidence['wall_ms'],
                    'wall_s': round(time.monotonic() - started, 3), 'process_id': evidence['process_id'],
                    'ledger': 'teaching_conservation_verified' if native else 'unchanged_or_unknown',
                    'historical_combat_calibration': 'not_validated'})
                print('PASS', len(results), battle, results[-1]['wall_s'], 's', flush=True)
            except Exception as exc:
                results.append({'battle': battle, 'passed': False, 'error': str(exc)[:1600]})
                print('FAIL', len(results), battle, str(exc)[:500], flush=True)
            (output / 'results.json').write_text(json.dumps({'cases': results, 'live_external_engine': True,
                'live_llm': False, 'historical_oob_claim': False}, ensure_ascii=False, indent=2))
    finally:
        h.close_harness()
    print('RESULT', sum(case['passed'] for case in results), '/', len(results), flush=True)
    return 0 if all(case['passed'] for case in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
