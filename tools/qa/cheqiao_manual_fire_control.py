"""Test a human artillery hold through real DSH planning and native AFSIM.

Uses a copy of the recorded pre-T+2 world; it never advances the saved game.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--recorded',type=Path,help='Recheck a saved real-run payload without another model/native execution')
    p.add_argument('--config',type=Path,required=True);args=p.parse_args()
    if args.live==bool(args.recorded):p.error('Choose exactly one of --live or --recorded')
    root=Path('.cache/qa/departure-review-2026-10-29/control')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from gentactix import commands,missions
    from backend import afsim_turns,harness_engine as h,runtime_bridge
    from backend.main import _native_tool_dispatch
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    original=args.trace.read_bytes();trace=json.loads(original);world=trace['before']
    session={'id':'cheqiao-manual-fire-qa','war_state':copy.deepcopy(world),'turn_count':world['mission']['turn'],
        'mission_id':world['mission']['id'],'time_step':'30分钟','simulation_mode':'open','execution_backend':'afsim',
        'history':[],'trajectory':[],'use_rag':False,'battle_choice':'抗日战争-车桥战役-1944.03.05至1944.03.06',
        'scenario_input':'车桥历史条件开放推演；使用已有计算初态，数值与位置仍为未标定估计。'}
    cs=commands.state(session)
    artillery=next(u for u in world['red_units'] if u['type']=='炮兵')
    actor=next(u for u in cs['registry'] if u['name']==artillery['name'])
    session['command_state']=commands.replace_queue(session,[{'unit_id':actor['id'],'action':'hold','duration':'next'}],
        control_team='red',director=False,no_fire=False,
        intent='炮兵09时以前侦察准备，本轮已人工下达炮兵待命。其他单位结合现态自行决策，不预定胜负或历史伤亡。')
    before=copy.deepcopy(session);prepared=commands.prepare(session)
    assert len(prepared['manual'])==1 and prepared['manual'][0]['order']=={'unit':artillery['name'],'action':'hold'}
    observer=h.RunObserver('人工炮兵命令与DSH全局规划验证')
    result={'passed':False,'scope':'one controlled real-model turn, not automatic time policy or historical calibration'}
    try:
        assert h.role_policy('engine')['reasoning_effort']=='high'
        assert h.role_policy('engine')['max_tokens']==65536
        if args.recorded:
            assert json.loads((args.recorded/'before.json').read_text())==world
            payload=json.loads((args.recorded/'payload.json').read_text())
            executed=payload['external_execution']['orders']
            result['evidence_reused_from']=str(args.recorded)
        else:
            h.enable_afsim_runtime()
            with patch.object(missions,'advance',side_effect=AssertionError('No Python combat fallback')):
                payload,executed,prompt=afsim_turns.advance(session,prepared,observer)
        after=payload['updated_state']
        # Keep expensive real-run evidence even if a presentation assertion fails.
        (root/'payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        (root/'before.json').write_text(json.dumps(world,ensure_ascii=False,indent=2))
        actual=next(o for o in executed if o['unit']==artillery['name'])
        assert actual['action']=='hold'
        gun=next(u for u in after['red_units'] if u['name']==artillery['name'])
        receipt=gun['formation']['last_execution']
        assert receipt['shots']==0 and receipt['fire_cycles']==0
        assert gun['formation']['shells']==artillery['formation']['shells']+receipt['received_shells']-receipt['shots']
        assert payload['external_execution']['returncode']==0
        assert payload['external_execution']['model_skipped'] is False
        assert len(after['red_units'])+len(after['blue_units'])==19
        assert after['mission']['turn']==world['mission']['turn']+1
        assert session==before and args.trace.read_bytes()==original
        command_result,_=commands.finish(session,prepared,after,executed=executed,rationales=payload['decisions'],runs=observer.runs)
        human=next(r for r in command_result['receipts'] if r['unit_id']==actor['id'])
        assert human['source']=='human'
        result.update(passed=True,artillery_order=actual,artillery_execution=receipt,human_receipt=human,
            planned_decisions=len(payload['decisions']),executed_orders=len(executed),
            engine=observer.meta() if not args.recorded else {'scope':'retained real-model output; no new inference'},
            native={k:payload['external_execution'][k] for k in ('returncode','artifact','entity_count','wall_ms')},
            original_trace_unchanged=True)
        (root/'before.json').write_text(json.dumps(world,ensure_ascii=False,indent=2))
        (root/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
        (root/'decisions.json').write_text(json.dumps(payload['decisions'],ensure_ascii=False,indent=2))
        print('PASS human hold retained, real DSH planned remaining units, native artillery shots=0',flush=True)
    finally:
        h.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(str(root),flush=True)


if __name__=='__main__':main()
