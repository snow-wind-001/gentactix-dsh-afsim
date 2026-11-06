"""One real high-effort DSH plan over an unchanged external world; incurs model usage."""
from pathlib import Path
import argparse
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / '.cache/qa/afsim-bridge/live-workflow')
    args = parser.parse_args(); directory = args.out.resolve(); directory.mkdir(parents=True, exist_ok=True)
    os.environ.update(GENTACTIX_SESSION_DIR=str(directory / 'sessions'), GENTACTIX_TRACE_DIR=str(directory / 'traces'),
        GENTACTIX_DSH_HOME=str(directory / 'dsh-home'), GENTACTIX_DSH_WORKSPACE=str(directory / 'dsh-workspace'),
        GENTACTIX_ROLE_INDEX=str(directory / 'roles.json'), GENTACTIX_DSH_PATCHES='[]')
    from backend import main as api, harness_engine as h
    from fastapi.testclient import TestClient
    from gentactix import missions
    client = TestClient(api.app); spec = next(m for m in missions.catalog() if m['profile'] == 'underground')
    instruction = '仅红方第一个可用单位向东移动约100米；其他单位本轮全部待命。不要开火。'
    try:
        response = client.post('/api/sessions', json={'scenario': spec['battle'] + '；固定局部教学验收。',
            'mission_id': spec['id'], 'execution_backend': 'afsim', 'persist_roles': False})
        response.raise_for_status(); sid = response.json()['session_id']
        started = time.monotonic(); response = client.post(f'/api/sessions/{sid}/init'); response.raise_for_status()
        before = response.json()['war_state']; init_wall = time.monotonic() - started
        print('INIT', sid, 'seconds', round(init_wall, 3), flush=True)
        view = client.get(f'/api/sessions/{sid}/commands').json()
        started = time.monotonic()
        response = client.post(f'/api/sessions/{sid}/next', json={'batch_id': 'live-planner', 'instruction': instruction,
            'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']})
        if response.status_code != 200: raise RuntimeError(response.text)
        snapshot = response.json(); after = snapshot['war_state']; record = api._SESSIONS[sid]['trajectory'][-1]
        mission_prompt = missions.prompt(before, instruction, '')
        report = {'session_id': sid, 'battle': spec['battle'], 'initial_state': 'versioned_synthetic_teaching',
            'live_dsh': True, 'live_afsim': True, 'initialization_s': round(init_wall, 3),
            'turn_wall_s': round(time.monotonic() - started, 3), 'engine_meta': snapshot['engine_meta'],
            'afsim': snapshot['afsim'], 'new_prompt_chars': len(record['prompt']),
            'previous_full_state_prompt_chars': len(mission_prompt),
            'prompt_reduction_ratio': round(1 - len(record['prompt']) / len(mission_prompt), 4),
            'clock_seconds': after['simulation_clock']['elapsed_seconds'],
            'roster_before': [len(before[t]) for t in ('red_units', 'blue_units')],
            'roster_after': [len(after[t]) for t in ('red_units', 'blue_units')],
            'policies': [e['request_config'] for r in record['runs'] for e in r['events'] if 'request_config' in e]}
        missions.validate(after)
        (directory / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k not in ('engine_meta', 'afsim', 'policies')}, ensure_ascii=False), flush=True)
        print('META', snapshot['engine_meta'], flush=True)
        print('POLICIES', report['policies'], flush=True)
    finally:
        h.close_harness()


if __name__ == '__main__':
    main()
