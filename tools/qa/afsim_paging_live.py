"""Real native DSH paging over a synthetic 24-entity external world; costs tokens."""
from pathlib import Path
import copy
import json
import os
import sys
import time
from unittest.mock import patch
import argparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def audit(session, directory, wall_s=None):
    from gentactix import commands
    record = session['trajectory'][-1]
    before, after = record['before'], record['after']
    native = [event for run in record['runs'] for event in run['events']
              if event.get('type') == 'tool/call' and event.get('name') == 'get_afsim_observation']
    assert any(json.loads(event['arguments'])['offset'] == 16 for event in native)
    assert len(after['red_units']) == 12 and len(after['blue_units']) == 12
    for team in ('red_units', 'blue_units'):
        for a,b in zip(before[team],after[team]):
            assert a['personnel']['current'] == b['personnel']['current']
    assert commands.known_position(after['blue_units'][-1]) != commands.known_position(before['blue_units'][-1])
    report = {'passed':True,'synthetic_entities':24,'native_paging_calls':len(native),'live_model':True,
        'live_afsim':True,'wall_s':wall_s, 'engine_meta':session['engine_last_meta'],
        'prompt_chars':len(record['prompt']),'entity_count':after['afsim']['entity_count'],'ledger_continuous':True}
    (directory / 'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-existing',action='store_true',help='Recheck saved real evidence without another model call')
    args = parser.parse_args()
    directory = ROOT / '.cache/qa/afsim-bridge/paging-live'; directory.mkdir(parents=True,exist_ok=True)
    if args.audit_existing:
        file = max((directory / 'sessions').glob('*.json'), key=lambda p:p.stat().st_mtime)
        return audit(json.loads(file.read_text())['session'], directory)
    os.environ.update(GENTACTIX_SESSION_DIR=str(directory / 'sessions'), GENTACTIX_TRACE_DIR=str(directory / 'traces'),
        GENTACTIX_DSH_HOME=str(directory / 'dsh-home'), GENTACTIX_DSH_WORKSPACE=str(directory / 'dsh-workspace'),
        GENTACTIX_ROLE_INDEX=str(directory / 'roles.json'), GENTACTIX_DSH_PATCHES='[]')
    from backend import main as api, harness_engine as h
    from fastapi.testclient import TestClient
    client = TestClient(api.app)
    unit = {'type':'徒步步兵','hp':100,'lat':29.91,'lng':102.23,'personnel':{'initial':100,'current':100,'killed':0,'wounded':0,'missing':0}}
    fixture = {'current_time':'1935-05-29 06:00','era':'现代','current_terrain':'丘陵森林','engagements':[],
        'center':[29.91,102.23], **{team + '_units':[dict(copy.deepcopy(unit),name=team + str(i + 1),
             lat=29.91 + i*.002 + (.03 if team=='blue' else 0)) for i in range(12)] for team in ('red','blue')}}
    try:
        r = client.post('/api/sessions',json={'scenario':'24实体分页与账本连续性软件验收；完全合成，不代表历史部队。',
            'execution_backend':'afsim','time_step':'15分钟','persist_roles':False})
        r.raise_for_status(); sid = r.json()['session_id']
        with patch.object(h, 'get_ai_response_with_retry',return_value=fixture):
            r = client.post(f'/api/sessions/{sid}/init')
        r.raise_for_status()
        view = client.get(f'/api/sessions/{sid}/commands').json(); start = time.monotonic()
        r = client.post(f'/api/sessions/{sid}/next',json={'batch_id':'paging-live',
            'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version'],
            'instruction':'先真实调用get_afsim_observation工具，offset=16、limit=8，读取末页。然后只让蓝方blue12向东移动50米；所有其他单位待命。不要开火，不猜单位ID。'})
        if r.status_code != 200: raise RuntimeError(r.text)
        audit(api._SESSIONS[sid], directory, round(time.monotonic()-start,3))
    finally:
        h.close_harness()


if __name__ == '__main__':
    main()
