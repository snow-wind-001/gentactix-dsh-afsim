"""Observed real SDK tool read over the retained actual22 T1 frame; no world execution."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=Path('.cache/qa/personnel-projection-2026-11-02/native-observed')
    if root.exists():parser.error('Preserve prior Native evidence')
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    from gentactix import missions,personnel_projection as p
    original=json.loads(Path('.cache/qa/personnel-projection-2026-11-02/branch-pre-advance.json').read_text())
    session=copy.deepcopy(original);session['id']=uuid.uuid4().hex[:12]
    before=copy.deepcopy(session);rows=[]
    target=next(u for u in session['war_state']['blue_units'] if u['name']=='日军第106师团')
    from gentactix import commands
    identity=next(r['id'] for r in commands.view(session)['units'] if r['name']==target['name'])
    expected=dict(current=target['personnel']['current'],committed=target['personnel']['committed'],personnel_strength_pct=p.strength_pct(target),
        legacy_hp=target['hp'],fatigue=target['formation']['fatigue'],full_establishment_proven=False)
    def dispatch(ctx,payload):
        reply=_native_tool_dispatch(ctx,payload)
        if payload.get('tool')=='get_afsim_observation':
            selected=[u for u in reply.get('units',[]) if u.get('name')==target['name']]
            rows.append(dict(tool=payload['tool'],arguments=payload.get('args'),units=selected))
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    observer=h.RunObserver('只读人员保有率真实SDK工具核验');began=time.monotonic()
    result=dict(passed=False,actual_model=True,source_turn=session['turn_count'],actors=len(missions.units(session['war_state'])),
        scope='Frozen actual22 T1 product frame, separate observed Native query; not a duplicate physical turn or historical calibration',private_reasoning_read=False)
    try:
        prompt=('调用get_afsim_observation(ids=["'+identity+'"],limit=1,detail=true)，只依据工具返回的当前状态，'
            '回答JSON：current、committed、personnel_strength_pct、legacy_hp、fatigue为数值，full_establishment_proven为布尔值。'
            '最后一项指是否已证明核定编制满员；人员数、累计投入、人员保有率与旧HP分开，不修改战局，不输出私有推理。')
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
        answer=h.parse_json_object(run.final_response)
        result.update(answer=answer,seconds=round(time.monotonic()-began,3),finish_reason=run.finish_reason,
            observations=rows,runs=[{k:r.get(k) for k in ('id','session_id','finish_reason','event_count')} for r in observer.runs])
        assert answer==expected,(answer,expected)
        assert rows and any(u.get('personnel_strength_pct')==expected['personnel_strength_pct'] for row in rows for u in row['units'])
        assert session==before
        result.update(passed=True,world_unchanged=True)
        print('PASS actual Native SDK observation',json.dumps(answer,ensure_ascii=False),flush=True)
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        h.close_harness()


if __name__=='__main__':main()
