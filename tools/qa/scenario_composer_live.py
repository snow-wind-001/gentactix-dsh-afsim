"""Explicit live acceptance: sourced basis -> DSH skill -> edited AFSIM draft -> exercise."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--out',type=Path,default=ROOT/'.cache/qa/history-process/composer-live');args=p.parse_args()
    if not args.live:p.error('--live is required')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(GENTACTIX_SESSION_DIR=str(out/'sessions'),GENTACTIX_TRACE_DIR=str(out/'traces'),GENTACTIX_DSH_HOME=str(out/'dsh-home'),GENTACTIX_DSH_WORKSPACE=str(out/'workspace'),GENTACTIX_ROLE_INDEX=str(out/'roles.json'),GENTACTIX_DSH_PATCHES='[]')
    from backend import main as api,harness_engine as h,session_store
    from fastapi.testclient import TestClient
    from gentactix import combined_arms,missions
    client=TestClient(api.app)
    mission=next(s for s in combined_arms.catalog() if '全面反攻与受降总览' in s['battle'])
    def post(path,payload=None):
        r=client.post(path,json=payload) if payload is not None else client.post(path)
        if r.status_code!=200:raise RuntimeError(r.text)
        return r.json()
    try:
        start=time.monotonic()
        draft=post('/api/scenarios/build',{'mission_id':mission['id'],'instruction':'保留史料来源绑定；红方分两个演习分队（各1500人），蓝方一个守备编组1000人。装甲、火炮、防空配额为0；工兵6、运输12、其他库存沿用种子。位置保持局部范围内，说明人数、装备与部署是演习估计。必须实际调用skill、基础读取和配置校验工具。'})
        (out/'generated.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2))
        assert draft['construction']['source']=='dsh_native_skill'
        assert draft['afsim']['source']=='dsh_native_mcp_controller' and draft['afsim']['returncode']==0
        config=copy.deepcopy(draft['configuration'])
        assert [len(config['teams'][t]) for t in ('red','blue')]==[2,1]
        config['teams']['blue'][0]['personnel']=900
        config['teams']['red'][0]['position']['lat']+=.001
        stale=client.post('/api/sessions',json={'scenario':'禁止跳过验证','mission_id':mission['id'],'execution_backend':'afsim','synthetic_configuration':config,'scenario_draft_id':draft['id']})
        assert stale.status_code==422
        verified=post('/api/scenarios/validate',{'mission_id':mission['id'],'configuration':config,'parent_draft_id':draft['id']})
        sid=post('/api/sessions',{'scenario':'史实基础派生合成演习实测；不是完整历史过程复原。','mission_id':mission['id'],'execution_backend':'afsim','synthetic_configuration':config,'scenario_draft_id':verified['id'],'persist_roles':False})['session_id']
        snap=post(f'/api/sessions/{sid}/init')
        assert snap['war_state']['blue_units'][0]['personnel']['current']==900
        view=client.get(f'/api/sessions/{sid}/commands').json()
        revision={k:view[v] for k,v in [('expected_turn','turn'),('revision','revision'),('world_version','world_version')]}
        r=client.put(f'/api/sessions/{sid}/commands',json={**revision,'director':True,'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']]});assert r.status_code==200,r.text
        view=client.get(f'/api/sessions/{sid}/commands').json()
        after=post(f'/api/sessions/{sid}/next',{'batch_id':'composer-live','expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version']})
        missions.validate(after['war_state']);restored,errors=session_store.load_all();assert not errors and sid in restored
        result={'passed':True,'session_id':sid,'historical_validation':False,'draft_id':verified['id'],'seconds':round(time.monotonic()-start,2),'roster':[len(after['war_state'][t+'_units']) for t in ('red','blue')],'source_names':[u['historical_reference']['name'] for t in ('red','blue') for u in after['war_state'][t+'_units']],'stale_edit_rejected':True,'turn_count':after['turn_count'],'afsim':after['afsim']}
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:result[k] for k in ('passed','session_id','seconds','roster')},ensure_ascii=False),flush=True)
    finally:h.close_harness()


if __name__=='__main__':main()
