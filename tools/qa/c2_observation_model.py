"""Recheck actual T+10 world with a fresh configured DSH run; never change its source."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--recon',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('Actual configured DSH requires --live')
    root=Path('.cache/qa/c2-observation-2026-10-31/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import dsh_simulation,harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    from gentactix import c2_observation,fire_process,missions,reporting
    parent=Path('.cache/qa/campaign-lifecycle-2026-10-31/narrative')
    snapshot=json.loads((parent/'after-10.json').read_text());before=copy.deepcopy(snapshot['war_state'])
    bad=json.loads((parent/'after-11.json').read_text())['war_state']
    frozen=copy.deepcopy(before);orders=[dict(unit=u['name'],action='hold') for _,u in missions.units(before)]
    delays={u['name']:fire_process.delay_seconds(before,u) for _,u in missions.units(before)}
    try:c2_observation.validate_transition(before,bad,orders,[],1800,source='dsh_model_estimate',minimum_delays=delays)
    except ValueError as exc:
        (root/'original-failure-replay.json').write_text(json.dumps(dict(rejected=True,error=str(exc),source_turn=10,
            original_bad_turn=11,source_world_unchanged=before==frozen),ensure_ascii=False,indent=2))
    else:raise AssertionError('Original 180→1830 minute failure was not rejected')
    if args.recon:orders[0]['action']='recon'
    (root/'executed-source.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in map(Path,[
        'backend/dsh_simulation.py','backend/campaign_model.py','backend/harness_engine.py','gentactix/c2_observation.py',
        'gentactix/combined_arms.py','plugins/dsh-gentactix/index.mjs'])},ensure_ascii=False,indent=2))
    session=dict(id='c2-frozen-actual-turn10',war_state=before,turn_count=10,time_step='30分钟',
        execution_backend='narrative',agent_mode='native',product_mode='historical',simulation_mode='open',
        mission_id=before['mission']['definition']['id'],history=snapshot['history'])
    runtime_bridge.register_dispatcher(_native_tool_dispatch);observer=h.RunObserver('情报分钟量纲真实复测 T+11')
    result=dict(passed=False,actual_model=True,actual_afsim=False,source_turn=10,source='actual prior lifecycle checkpoint',recon=args.recon,
        scope='Independent effect/clock estimate over an actual frozen world; not a persistent-task or whole-UI continuation')
    try:
        intent=('仅第90师执行recon，其余待命；本例无来袭或已知通信阻断。按实际成功侦察事件时点记账，不能只因命令是recon就把轮末年龄设为零。'
            if args.recon else '全部六个单位明确待命。无recon，无新情报，intel_age_min按分钟累积本轮30分钟。')
        response,_,_=dsh_simulation.advance(session,None,observer,fixed_orders=orders,
            instruction=intent+'战报仅描述本轮物理过程，不自行宣布阶段/目标结算。')
        after=response['updated_state'];assert before==frozen
        for index,((_,a),(_,b)) in enumerate(zip(missions.units(before),missions.units(after))):
            if args.recon and index==0:assert b['formation']['intel_age_min']<a['formation']['intel_age_min']+30
            else:assert abs(b['formation']['intel_age_min']-a['formation']['intel_age_min']-30)<1e-7
            assert b['personnel']==a['personnel'] and b['logistics']['ammo']==a['logistics']['ammo']
            assert b['logistics']['food']==a['logistics']['food']-2
        assert after['dsh_execution']['intelligence']['refreshed_units']==int(args.recon)
        (root/'before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
        (root/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
        (root/'public-report.txt').write_text(response.get('report',''))
        result.update(passed=True,meta=observer.meta(),world_unchanged=True,age_min=after['red_units'][0]['formation']['intel_age_min'],
            intelligence=after['dsh_execution']['intelligence'],known_report_issues=reporting.inspect(response.get('report',''),after,before,turn=11))
        print(json.dumps({k:v for k,v in result.items() if k!='known_report_issues'},ensure_ascii=False),flush=True)
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));h.close_harness()


if __name__=='__main__':main()
