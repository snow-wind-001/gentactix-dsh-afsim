"""Opt-in real DSH/AFSIM regression for bilateral complete decisions and fire.

This is an isolated synthetic acceptance exercise, not a historical validation.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--custom', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; this invokes the configured model')
    out = ROOT / '.cache/qa/history-process' / ('live-custom' if args.custom else 'live')
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(GENTACTIX_SESSION_DIR=str(out/'sessions'), GENTACTIX_TRACE_DIR=str(out/'traces'),
        GENTACTIX_DSH_HOME=str(out/'dsh-home'), GENTACTIX_DSH_WORKSPACE=str(out/'workspace'),
        GENTACTIX_ROLE_INDEX=str(out/'roles.json'), GENTACTIX_DSH_PATCHES='[]')
    from backend import main as api, harness_engine as h
    from fastapi.testclient import TestClient
    from gentactix import missions
    client = TestClient(api.app)
    def post(path, payload=None):
        r = client.post(path, json=payload) if payload is not None else client.post(path)
        if r.status_code != 200:
            raise RuntimeError(r.text)
        return r.json()
    try:
        payload = {'scenario':'双边完整决策与原生炮击验收；合成测试，不作为历史过程复原。',
            'mission_id':'CA-AJ18-v1','execution_backend':'afsim','persist_roles':False}
        if args.custom:
            import copy
            from gentactix import combined_arms
            cfg = combined_arms.configuration('CA-AJ18-v1')
            cfg['teams']['red'] = [cfg['teams']['red'][0], cfg['teams']['red'][2]]
            cfg['teams']['red'][0]['personnel'] = 1234
            extra = copy.deepcopy(cfg['teams']['blue'][0]); extra['name'] = '蓝方自定义增援编组'
            cfg['teams']['blue'].append(extra)
            payload['synthetic_configuration'] = cfg
        sid = post('/api/sessions', payload)['session_id']
        post(f'/api/sessions/{sid}/init')
        view = client.get(f'/api/sessions/{sid}/commands').json()
        start = time.monotonic()
        snapshot = post(f'/api/sessions/{sid}/next', {'batch_id':'bilateral-live',
            'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version'],
            'instruction':'这是明确的双边验收命令：红方支援团对蓝方支援团bombard，蓝方支援团对红方支援团bombard；其余四单位明确hold。双方全部六单位均提交命令、目标和简短公开理由。仅允许本轮这两次炮击，不要移动、架桥或航空支援。'})
        world = snapshot['war_state']; missions.validate(world)
        if args.custom:
            assert [len(world[t+'_units']) for t in ('red','blue')] == [2,4]
            assert world['red_units'][0]['personnel']['committed'] == 1234
            assert snapshot['settings']['synthetic_configuration'] == cfg
        receipts = api._SESSIONS[sid]['command_state']['receipts']
        assert len(receipts) == 6 and all(r['source'] != 'default_hold' for r in receipts)
        assert {r['team'] for r in receipts if r['action']=='bombard'} == {'red','blue'}
        assert len(world['engagements']) == 2
        assert all(u['personnel']['casualties'] > 0 for t in ('red','blue') for u in world[t+'_units'] if '支援' in u['name'])
        result = {'passed':True,'historical_validation':False,'native_dsh':True,'native_afsim':True,
            'seconds':round(time.monotonic()-start,2),'session_id':sid,'receipts':receipts,
            'engagements':world['engagements'],'engine_meta':snapshot['engine_meta'],
            'afsim':snapshot['afsim']}
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({k:result[k] for k in ('passed','historical_validation','seconds','session_id')},ensure_ascii=False),flush=True)
    finally:
        h.close_harness()


if __name__ == '__main__':
    main()
