"""Real DSH read-only task-member paging over isolated numerical QA leaves."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--hierarchy',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('Use --live to call the configured model')
    root=Path('.cache/qa/'+('force-hierarchy-2026-10-31' if args.hierarchy else 'campaign-contracts-2026-10-31')+'/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    # Existing encrypted LLM config is read as configured; no budget/effort overrides.
    from verify_campaign_contracts import ForceMemberTests
    from gentactix import commands,force_organization as f
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    session=ForceMemberTests().partitioned_session()
    ids=[i for i,(e,_) in commands.resolve_units(session).items() if e['team']=='red'][1:4]
    session['force_organization']=f.detach(session,ids,'只读成员验证群','明确数值QA，不是历史真实部署')
    group=session['force_organization']['groups'][0]['id']
    if args.hierarchy:
        session['force_organization']=f.detach(session,ids[:2],'下级群','QA二级任务群',parent_id=group)
        child=next(g['id'] for g in f.state(session)['groups'] if g['label']=='下级群')
        session['force_organization']=f.detach(session,ids[:1],'先遣群','QA三级任务群',parent_id=child)
    saved=copy.deepcopy(session);calls=[]
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload)
        if payload.get('tool')=='get_force_organization':
            calls.append({'args':payload.get('args'),'result':response})
        return response
    runtime_bridge.register_dispatcher(dispatch)
    observer=h.RunObserver('会战任务群成员真实只读验证')
    result={'passed':False,'scope':'真实DSH工具分页；数值QA，无战局推进或历史效能标定'}
    try:
        answer=h._run_brain('请核对任务群'+group+'。必须调用get_force_organization，kind=members，node_id为此群，limit=2，'
            '沿next_args读完；不要从同父编号猜成员。只返回JSON：'
            '{"command_ids":[实际command_id],"calculation_unit_ids":[实际calculation_unit_id],'
            '"personnel_total":可用人员合计,"organization_revision":工具返回revision}。'
            +('本次另加command_chains对象，以每个实际command_id为键，值为从上级到直属群的完整command_chain列表；所有三个单位均需列出，不按父级重复计算人数。' if args.hierarchy else '')
            +'只读，不写命令或状态。',
            None,observer=observer,role='chat',native_context=afsim_state.operation_context(session))
        data=h.parse_json_object(answer.final_response)
        actual=[u for i,(_,u) in commands.resolve_units(session).items() if i in ids]
        assert set(data['command_ids'])==set(ids),data
        assert set(data['calculation_unit_ids'])=={u['calculation_unit_id'] for u in actual},data
        assert data['personnel_total']==sum(u['personnel']['current'] for u in actual),data
        assert data['organization_revision']==f.state(session)['revision'],data
        if args.hierarchy:
            expected={i:f.command_chain(session,f.leaf_key(e['team'],u))
                for i,(e,u) in commands.resolve_units(session).items() if i in ids}
            assert data['command_chains']==expected,data
        assert len(calls)>=2 and any(c['args'].get('offset',0)>0 for c in calls)
        assert session==saved
        result.update(passed=True,answer=data,world_unchanged=True,engine_meta=observer.meta())
        print('PASS real DSH exact calculation members, pagination and totals',flush=True)
    finally:
        result['calls']=calls
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2))
        h.close_harness()
        print('Evidence:',root,flush=True)


if __name__=='__main__':main()
