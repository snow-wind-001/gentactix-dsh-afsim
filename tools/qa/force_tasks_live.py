"""Real DSH paged mixed-task preview, preserving a prior human order."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live to call configured DSH model')
    root=Path('.cache/qa/force-tasks-2026-10-31/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from verify_force_tasks import session,ForceTaskTests
    from gentactix import commands,force_tasks as t
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    s,ids,g,enemy=session();s['execution_backend']='afsim'
    s['command_state']=commands.replace_queue(s,[dict(unit_id=ids[0],action='recon',duration='next')],control_team='red',director=False,no_fire=False,intent='人工侦察优先')
    task=ForceTaskTests().intent(ids,enemy);expected=t.preview(s,g,task);before=copy.deepcopy(s);calls=[]
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload)
        calls.append({'tool':payload.get('tool'),'args':payload.get('args'),'response':response})
        return response
    runtime_bridge.register_dispatcher(dispatch);observer=h.RunObserver('兵团任务只读分解真实验证');result={'passed':False}
    try:
        prompt=('请调用preview_force_task，只读检查以下任务，limit=2，沿next_args读完，不写命令或状态。'
            '如行状态manual_kept，有效行动为existing_order.action，不能误称候选已覆盖人工命令；'
            '其他行为order.action。仅返回JSON {"effective_actions":{"实际unit_id":"动作"},"candidate_count":待暂存数,"conflict_count":已有命令数}。输入：'
            +json.dumps({'group_id':g,'task':task,'replace_existing':False},ensure_ascii=False))
        run=h._run_brain(prompt,None,observer=observer,role='chat',native_context=afsim_state.operation_context(s))
        answer=h.parse_json_object(run.final_response)
        actual={r['unit_id']:(r['existing_order']['action'] if r['status']=='manual_kept' else r['order']['action']) for r in expected['rows']}
        assert answer['effective_actions']==actual,answer
        assert answer['candidate_count']==3 and answer['conflict_count']==1,answer
        assert sum(c['tool']=='preview_force_task' for c in calls)>=2
        assert s==before
        result.update(passed=True,answer=answer,world_unchanged=True,engine_meta=observer.meta())
        print('PASS real DSH distinguishes 4 roles, two preview pages and preserved human reconnaissance',flush=True)
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2))
        h.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
