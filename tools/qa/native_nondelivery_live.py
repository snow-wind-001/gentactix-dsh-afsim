"""Isolated real API/native check of command delivery over a saved live initial state.

All 19 orders are explicitly controlled for this test. No model is requested;
this complements, and does not replace, the separate full DSH long run.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',action='store_true');p.add_argument('--run',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True);args=p.parse_args()
    if not args.native:p.error('--native required')
    root=Path('.cache/qa/native-nondelivery-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for k,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),
                     ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+k]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from fastapi.testclient import TestClient
    from backend import main as api,session_store,harness_engine as h,runtime_bridge
    from gentactix import missions
    runtime_bridge.register_dispatcher(api._native_tool_dispatch)
    world=json.loads((args.run/'initialization.json').read_text())['war_state']
    initial=copy.deepcopy(world)
    s=api._new_session('原生命令交付回执QA','30分钟',False,world['mission']['definition']['battle'],False,False)
    s.update(war_state=world,mission_id=world['mission']['id'],turn_count=0,
        execution_backend='afsim',simulation_mode='open',product_mode='historical',
        historical_definition=copy.deepcopy(world['mission']['definition']))
    session_store.validate(s);session_store.save(s);api._SESSIONS[s['id']]=s
    client=TestClient(api.app);path='/api/sessions/'+s['id'];result={'passed':False}
    def revision(v):return {'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
    try:
        v=client.get(path+'/commands').json()
        orders=[{'unit_id':u['id'],'action':'recon' if '曹甸' in u['name'] else 'hold','duration':'next'} for u in v['units']]
        response=client.put(path+'/commands',json={**revision(v),'orders':orders,'control_team':'red',
            'director':True,'no_fire':False,'intent':'显式全部人工命令，仅检查未交付与已交付的原生回执，不代表历史战斗。'})
        assert response.status_code==200,response.text
        v=client.get(path+'/commands').json();request={**revision(v),'batch_id':uuid.uuid4().hex}
        with patch.object(h,'get_ai_response',side_effect=AssertionError('Complete manual batch must skip model')), \
             patch.object(missions,'advance',side_effect=AssertionError('No Python battle fallback')):
            response=client.post(path+'/next',json=request)
        assert response.status_code==200,response.text
        snapshot=response.json();after=snapshot['war_state'];native=after['afsim']
        assert native['returncode']==0 and native['entity_count']==19 and native['model_skipped']
        rows=client.get(path+'/unit-decisions?start_turn=1&end_turn=1').json()['items']
        assert len(rows)==19
        summaries=[]
        for r in rows:
            unit=next(u for _,u in missions.units(after) if u['name']==r['unit_name'])
            done=unit['formation']['last_execution']['command_done']
            assert r['source']=='human'
            assert r['status']==('completed' if done else 'blocked')
            if not done:assert '未交付' in r['reason'] and '未交付' in r['rationale']
            summaries.append({'unit':r['unit_name'],'action':r['action'],'status':r['status'],'native_command_done':done})
        assert sum(x['native_command_done']==0 for x in summaries)==5
        assert world==initial
        replay=client.post(path+'/next',json=request);assert replay.status_code==200 and replay.json()['command_result']['replayed']
        restored,errors=session_store.load_all();assert not errors and restored[s['id']]['war_state']==after
        result={'passed':True,'model_calls':0,'session_id':s['id'],'native_artifact':native['artifact'],
                'receipts':summaries,'idempotent':True,'checkpoint_restored':True}
        (root/'response.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
        (root/'receipts.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        print('PASS 19 real API/native receipts: 14 delivered, 5 undelivered; checkpoint/idempotence',flush=True)
    finally:
        h.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(root)


if __name__=='__main__':main()
