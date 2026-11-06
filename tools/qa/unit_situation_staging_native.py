"""Final-source Native observation of a delayed actor in the Wuhan79 QA world."""
import argparse
import copy
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=args.out
    if root.exists():parser.error('Preserve previous evidence')
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import harness_engine as h,runtime_bridge,unit_planning,unit_order_submission
    from backend.main import _native_tool_dispatch
    from gentactix import commands,historical_operations,unit_participation
    from tools.qa.large_formation_fixture import inputs
    from .unit_situation_index_native import observation_results
    source,parameters=inputs();parameters.pop('campaign_plan',None)
    target=next(u['id'] for u in reversed(source['definition']['units']) if u['team']=='blue' and u['id'] in parameters['actors'])
    parameters['campaign']['arrivals'][target]['not_before']=(datetime.fromisoformat(parameters['clock']['start'])+timedelta(hours=1)).isoformat()
    world=historical_operations.initial(source,parameters)
    session=dict(id=uuid.uuid4().hex[:12],turn_count=0,role_epoch=0,execution_backend='narrative',agent_mode='native',
        product_mode='historical',simulation_mode='open',time_step='30分钟',war_state=world)
    session['command_state']=commands.replace_queue(session,[],control_team='red',director=True,no_fire=False,intent='只读单位候选与旧版到场状态核验；不是完整历史部署或物理推演')
    view=commands.view(session);identity=next(u['id'] for u in view['units'] if u['team']=='red')
    tail=view['units'][-1];assert tail['capabilities']['arrival']['status']=='staging'
    assert not unit_participation.supported(world) and len(view['units'])==79
    session['command_state']['unit_agents']=[identity];prepared=commands.prepare(session);saved=copy.deepcopy(session)
    observer=h.RunObserver('Final Native79 index and staging evidence');runtime_bridge.register_dispatcher(_native_tool_dispatch)
    real=h.unit_run;captures=[]
    def capture(binding,prompt,*args,**kwargs):
        captures.append(dict(chars=len(prompt),packet=json.loads(prompt.split('\n')[-1])))
        return real(binding,prompt,*args,**kwargs)
    h.unit_run=capture;started=time.monotonic()
    files=[Path('data/historical_initial/AJ06-wuhan/1.1.0.json'),Path('tools/qa/large_formation_fixture.py')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result=dict(passed=False,physical_turn=False,actual_model=True,source='final_staging_v2',source_files=hashes,
        scope='One Native unit reads delayed tail in sourced79-identity QA estimates; no full historical, physical campaign or performance acceptance')
    try:
        orders,decisions=unit_planning.plan(session,prepared,observer,instruction=
            '这是只读到场状态核验。先使用known_units最末条的detail_query查询该单位当前详细观察，'
            '核对arrival.status与计划时间。只通过submit_unit_order提交本单位hold(duration=next)候选，'
            '公开依据须指出该具名单位尚未到场，不能把有现员当作已参战。不要执行物理推演或输出内部推理。')
        assert len(captures)==len(orders)==len(decisions)==1 and orders[0]['action']=='hold'
        packet=captures[0]['packet'];assert len(packet['known_units'])==79
        assert packet['known_units'][-1]['arrival']==tail['capabilities']['arrival']
        details=list(observation_results(observer));assert details
        found=[(a,r) for a,r in details if a==packet['known_units'][-1]['detail_query']]
        assert found and found[-1][1]['units'][0]['arrival']['status']=='staging'
        ctx=unit_order_submission.context(session,prepared,identity,operation_id=observer.operation_id)
        for query,reply in details:assert _native_tool_dispatch(ctx,dict(tool='get_afsim_observation',args=query))==reply
        proposal,proof=unit_order_submission.submitted(observer,ctx)
        assert proof==decisions[0]['proposal'] and tail['name'] in proposal['rationale']
        assert any(word in proposal['rationale'] for word in ('尚未','未到场','staging'))
        assert session==saved and all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in hashes.items())
        result.update(passed=True,seconds=round(time.monotonic()-started,3),all79indexed=True,tail=tail['name'],
            tail_arrival=packet['known_units'][-1]['arrival'],prompt_chars=captures[0]['chars'],
            native_order_proof=proof,source_world_unchanged=True,query_count=len(details))
        print('PASS finalsourceNative79index,delayedtaildetail,correctpublicbasis andholdproof; no physicalturn',flush=True)
    finally:
        h.unit_run=real;result.setdefault('seconds',round(time.monotonic()-started,3))
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (root/'public-runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2)+'\n')
        (root/'prompt-packets.json').write_text(json.dumps(captures,ensure_ascii=False,indent=2)+'\n')
        h.close_harness()


if __name__=='__main__':main()
