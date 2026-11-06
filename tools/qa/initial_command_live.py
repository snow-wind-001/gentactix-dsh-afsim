"""Real DSH distinguishes opening command membership from historical parentage."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Use --live for configured real DSH')
    root=Path('.cache/qa/initial-command-2026-10-31/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from tools.qa.initial_command_fixture import session
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    s=session();before=copy.deepcopy(s);calls=[];obs=h.RunObserver('真实开局作战指挥核对');result={'passed':False}
    def dispatch(context,payload):
        answer=_native_tool_dispatch(context,payload);calls.append({'tool':payload.get('tool'),'args':payload.get('args'),'response':answer});return answer
    runtime_bridge.register_dispatcher(dispatch)
    try:
        prompt=('实际调用get_force_organization(kind=members,node_id=ww2.cn.army66,limit=1,hierarchy=command)并沿next_args读取完整两页。'
            '再分别读取node_id=ww2.cn.division161在command和historical视图的成员。'
            '不要把行政参考当当前指挥，不要推断全师永久改隶。仅返回JSON {"active_members":[实际具名成员名称],'
            '"full161_current_count":command成员数,"administrative_count":historical成员数,"chain":[66军下级的实际command_chain ID]}。')
        run=h._run_brain(prompt,None,role='chat',observer=obs,native_context=afsim_state.operation_context(s))
        answer=h.parse_json_object(run.final_response)
        assert set(answer['active_members'])=={'第159师','第161师万家岭投入部'},answer
        assert answer['full161_current_count']==0 and answer['administrative_count']==1,answer
        assert answer['chain']==['ww2.cn.warzone9','ww2.cn.corps1','ww2.cn.army66'],answer
        assert len(calls)>=4 and all(c['tool']=='get_force_organization' for c in calls)
        assert s==before;result.update(passed=True,answer=answer,world_unchanged=True,meta=obs.meta())
        print('PASS real DSH reads both operational members, original parent reference and actual command chain',flush=True)
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));(root/'runs.json').write_text(json.dumps(obs.runs,ensure_ascii=False,indent=2))
        h.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
