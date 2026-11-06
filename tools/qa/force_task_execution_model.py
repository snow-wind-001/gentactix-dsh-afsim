"""Actual DSH Native reads an actual AFSIM persistent-task trajectory, readonly."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for the configured real model')
    base=Path('.cache/qa/force-task-execution-2026-10-31');root=base/'model'/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    session=json.loads((base/'afsim/export.json').read_text())['session'];before=copy.deepcopy(session);calls=[]
    observer=h.RunObserver('真实持续任务的Native分页读取');result=dict(passed=False,actual_model=True,actual_afsim_input=True)
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload);calls.append(dict(tool=payload.get('tool'),args=payload.get('args'),response=response));return response
    runtime_bridge.register_dispatcher(dispatch)
    try:
        prompt=('只读核验实际AFSIM结果。只使用get_force_tasks：先kind=tasks,limit=1沿next_args读完；'
            '再按每项member_args读成员与executions；对预备方向按event_args沿next_args读完状态事件。'
            '不能把应用接受当实际收令，不能因任务确认就宣称部队已行动。'
            '只返回JSON {"tasks":[{"label":"实际任务名称","status":"工具实际状态","member_name":"实际成员名称","executions":整数}],'
            '"reserve_waited_before_execution":布尔值,"application_acceptance_equals_delivery":布尔值}。')
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
        answer=h.parse_json_object(run.final_response);items={r['label']:r for r in answer['tasks']}
        assert items=={'先行方向':dict(label='先行方向',status='completed',member_name='第159师',executions=1),
                      '预备方向':dict(label='预备方向',status='completed',member_name='第51师',executions=1)},answer
        assert answer['reserve_waited_before_execution'] is True and answer['application_acceptance_equals_delivery'] is False
        assert all(c['tool']=='get_force_tasks' for c in calls) and len({r['id'] for c in calls for r in c['response'].get('rows',[]) if c['args'].get('kind','tasks')=='tasks'})==2
        assert any(c['args'].get('kind')=='events' and any(r['status']=='waiting_dependency' for r in c['response'].get('rows',[])) for c in calls)
        assert sum(len(c['response'].get('rows',[])) for c in calls if c['args'].get('kind')=='members')==2
        assert session==before
        result.update(passed=True,answer=answer,world_unchanged=True,meta=observer.meta())
        print('PASS actual DSH Native reads both tasks, members and reserve wait events without writing state',flush=True)
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2));h.close_harness();print('Evidence:',root,flush=True)
