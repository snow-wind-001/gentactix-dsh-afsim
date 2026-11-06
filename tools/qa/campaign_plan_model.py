"""Actual DSH reads an AFSIM-produced partial-direction state through native tools."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for the configured real model')
    base=Path('.cache/qa/campaign-plan-2026-10-31');root=base/'model'/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    snapshot=json.loads((base/'native/one-axis.json').read_text());world=snapshot['war_state']
    session=dict(id='campaign-objective-model-qa',war_state=world,turn_count=snapshot['turn_count'],
        time_step='30分钟',role_epoch=0,product_mode='historical',simulation_mode='open',execution_backend='afsim',
        battle_choice=world['mission']['definition']['battle'],history=[],use_rag=False)
    before=copy.deepcopy(session);calls=[];result={'passed':False,'actual_dsh':True,'actual_afsim_input':True}
    observer=h.RunObserver('真实AFSIM局部目标后的DSH任务观察')
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload)
        calls.append({'tool':payload.get('tool'),'args':payload.get('args'),'response':response});return response
    runtime_bridge.register_dispatcher(dispatch)
    try:
        prompt=('只读核验。实际调用get_campaign_objectives(kind="nodes",limit=2)，沿next_args读完所有节点；'
            '再按preserve节点的member_args查询承担单位，可用limit=2，沿next_args读完。只用此工具，不下令、不调用执行工具。'
            '只返回JSON {"north_status":"实际状态","south_status":"实际状态","preserve_status":"实际状态",'
            '"red_total_ready":布尔值,"blue_has_own_goal":布尔值,"preserve_members":整数,"automatically_issues_orders":布尔值}。'
            '注意区分目标评分与自动下令，不把一个方向达成当作全役已结束；不要输出推理过程。')
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
        answer=h.parse_json_object(run.final_response)
        assert answer==dict(north_status='completed',south_status='active',preserve_status='waiting_dependency',
            red_total_ready=False,blue_has_own_goal=True,preserve_members=5,automatically_issues_orders=False),answer
        nodes={r['id'] for c in calls for r in c['response'].get('nodes',[])}
        members={r['unit_id'] for c in calls for r in c['response'].get('members',[])}
        assert len(nodes)==4 and len(members)==5,(nodes,members)
        assert all(c['tool']=='get_campaign_objectives' for c in calls)
        assert session==before
        result.update(passed=True,answer=answer,world_unchanged=True,meta=observer.meta())
        print('PASS real DSH: reads all four direction goals and five members, keeps partial success separate from whole campaign',flush=True)
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2));h.close_harness()
        print('Evidence:',root,flush=True)


if __name__=='__main__':main()
