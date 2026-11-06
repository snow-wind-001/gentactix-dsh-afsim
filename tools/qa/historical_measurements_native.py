"""Actual Native reads of scoped historical quantities; no simulation writes."""
import argparse
import copy
import json
import os
from pathlib import Path
import time

ROOT=Path('.cache/qa/campaign-materials-2026-11-02')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:raise SystemExit('Use --live for actual configured model calls')
    folder=ROOT/'native'/str(time.time_ns());folder.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((folder/suffix).resolve())
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    from gentactix import history_replay
    from tools.upgrade_wanjialing import BATTLE
    pinned=history_replay.pin(BATTLE,version='1.4.0')
    session=dict(id='wjl-numeric-materials-qa',war_state=history_replay.frame_pinned(pinned,0),turn_count=0,
        battle_choice=BATTLE,execution_backend='narrative',product_mode='analysis',simulation_mode='replay',use_rag=False,history=[])
    before=copy.deepcopy(session);calls=[];observer=h.RunObserver('阶段数值资料及统计对象核验')
    result=dict(passed=False,actual_model=True,cases=[],private_reasoning_read=False)
    def dispatch(context,payload):
        reply=_native_tool_dispatch(context,payload)
        calls.append(dict(tool=payload.get('tool'),args=payload.get('args'),response=reply))
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    def save():
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (folder/'public-tools.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2)+'\n')
    def ask(phase,question,expected):
        start=len(calls);began=time.monotonic()
        prompt=('调用现有retrieve_history(kind="measurements",phase_id="'+phase+'",limit=1)，省略query，沿next_args读完。'
            '只能依据本次固定1.4.0阶段数值资料；不调用写入工具，不将来源数字当本局状态。不输出私有思考。'+question)
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
        answer=h.parse_json_object(run.final_response)
        selected=calls[start:];rows=[r for c in selected if c['tool']=='retrieve_history' for r in c['response'].get('measurements',[])]
        result['cases'].append(dict(phase=phase,answer=answer,seconds=round(time.monotonic()-began,3),tool_calls=len(selected),
            unique_measurements=len({r['id'] for r in rows})))
        save();assert answer==expected,(phase,answer)
        assert len({r['id'] for r in rows})==(2 if phase=='oct10_attacks' else 1)
        assert session==before,'Readonly Native query changed host state'
        print('PASS actual Native numerical scope',phase,'seconds',result['cases'][-1]['seconds'],flush=True)
    try:
        ask('oct6_orders','只返回JSON {"reported_number":整数,"statistic":"来源statistic",'
            '"whole_detachment_strength_known":布尔值,"add_to_trapped_division":布尔值,"original_archive_examined":布尔值}。',
            dict(reported_number=2700,statistic='replacement_basis',whole_detachment_strength_known=False,add_to_trapped_division=False,original_archive_examined=False))
        ask('oct7_attack','只返回JSON {"enemy_relation":"来源relation","enemy_lower":整数,'
            '"date_precision":"来源precision","is_casualty_count":布尔值}。',
            dict(enemy_relation='gt',enemy_lower=300,date_precision='hour',is_casualty_count=False))
        ask('oct8_counterattacks','只返回JSON {"enemy_relation":"来源relation","enemy_lower":整数,'
            '"date_precision":"来源precision","exact_clock_known":布尔值,"whole_division_count":布尔值}。',
            dict(enemy_relation='gt',enemy_lower=1000,date_precision='period',exact_clock_known=False,whole_division_count=False))
        ask('oct9_final_orders','只返回JSON {"lower":整数,"upper":整数,"statistic":"来源statistic",'
            '"denominator":"per_division或whole_army","actual_selected_proven":布尔值,"casualties":布尔值}。',
            dict(lower=200,upper=500,statistic='ordered_detachment',denominator='per_division',actual_selected_proven=False,casualties=False))
        ask('oct10_attacks','只返回JSON {"personnel_relation":"来源relation","personnel_lower":整数,'
            '"horses_relation":"来源relation","horses_lower":整数,"transport_vehicles_known":布尔值,"whole_division_survivors_known":布尔值}。',
            dict(personnel_relation='gt',personnel_lower=1000,horses_relation='gt',horses_lower=300,transport_vehicles_known=False,whole_division_survivors_known=False))
        result.update(passed=True,world_unchanged=session==before,meta=observer.meta())
    except BaseException as exc:
        result.update(error=str(exc),world_unchanged=session==before,meta=observer.meta());raise
    finally:
        save();h.close_harness();print('Evidence',folder,flush=True)


if __name__=='__main__':main()
