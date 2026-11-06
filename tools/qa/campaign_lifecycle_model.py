"""Real DSH Native queries a frozen actual AFSIM gap checkpoint; no writes."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Actual configured model requires --live')
    base=Path('.cache/qa/campaign-lifecycle-2026-10-31');root=base/'model'/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    session=json.loads((base/'afsim/gap-export.json').read_text())['session'];before=copy.deepcopy(session)
    assert session['turn_count']==4 and session['war_state']['campaign_lifecycle']['phase_index']==3
    calls=[];observer=h.RunObserver('真实DSH分页核对十阶段与时间间隙');result=dict(passed=False,actual_model=True,actual_afsim_input=True,source_turn=4)
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload);calls.append(dict(tool=payload.get('tool'),args=payload.get('args'),response=response));return response
    runtime_bridge.register_dispatcher(dispatch)
    try:
        prompt=('只读核对冻结的实际AFSIM检查点。先get_campaign_lifecycle(limit=3)，沿next_args读取全部阶段；'
            '再get_campaign_objectives(limit=3)，沿next_args读完，确认milestone10实际状态。'
            '只返回JSON {"phase_count":整数,"current_phase_number":从1计数的阶段号,"completed_phases":整数,'
            '"elapsed_seconds":实际全局秒数,"minimum_remaining_seconds":当前阶段最短还需秒数,'
            '"future_goal_status":"milestone10的实际工具状态","all_campaign_stages_complete":布尔值}。'
            '阶段与任务次数、全局已过时间与单轮时长须区分。尚未采样不能说条件为假。不得写入状态或自行推进。')
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
        answer=h.parse_json_object(run.final_response)
        expected=dict(phase_count=10,current_phase_number=4,completed_phases=3,elapsed_seconds=7200,
            minimum_remaining_seconds=3600,future_goal_status='waiting_phase',all_campaign_stages_complete=False)
        assert answer==expected,answer
        stages={r['id'] for c in calls if c['tool']=='get_campaign_lifecycle' for r in c['response'].get('rows',[])}
        goals={r['id'] for c in calls if c['tool']=='get_campaign_objectives' for r in c['response'].get('nodes',[])}
        assert len(stages)==10 and len(goals)==10
        assert {c['tool'] for c in calls}=={'get_campaign_lifecycle','get_campaign_objectives'}
        assert session==before
        result.update(passed=True,answer=answer,world_unchanged=True,meta=observer.meta())
        print('PASS real DSH Native: all stages/goals read, gap and future status correct, frozen world unchanged',flush=True)
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2));h.close_harness();print('Evidence:',root,flush=True)
