"""Real DSH copies typed ancestor paths before/after temporary reassignment."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for actual configured DSH')
    root=Path('.cache/qa/force-observation-2026-10-31/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from tools.qa.initial_command_fixture import session
    from gentactix import force_organization as f,commands
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    calls=[];observer=h.RunObserver('指挥成员、祖先路径与兼容依据真实核对')
    result={'passed':False,'actual_dsh':True,'cases':[]}
    def dispatch(context,payload):
        value=_native_tool_dispatch(context,payload)
        calls.append({'tool':payload.get('tool'),'args':payload.get('args'),'response':value});return value
    runtime_bridge.register_dispatcher(dispatch)
    def ask(s,prompt,label):
        old=copy.deepcopy(s);start=len(calls)
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(s))
        answer=h.parse_json_object(run.final_response)
        assert s==old,'Readonly observation changed host state'
        record={'case':label,'answer':answer,'calls':copy.deepcopy(calls[start:]),'world_unchanged':True}
        result['cases'].append(record)
        assert record['calls'] and all(c['tool']=='get_force_organization' for c in record['calls'])
        return answer
    try:
        s=session()
        a=ask(s,'实际调用get_force_organization(kind=members,node_id=ww2.cn.army66,limit=1,hierarchy=command)，沿next_args读完。'
            '再分别查询ww2.cn.division161的command和historical成员。仅返回JSON：active_members为成员名称字符串数组，'
            'full161_current_count和administrative_count为两个视图的成员整数总数；chain为一维字符串ID数组，'
            '原样复制66军任一实际成员的command_chain（不是成员ID集合，不返回两份嵌套数组）。','source_opening')
        assert set(a['active_members'])=={'第159师','第161师万家岭投入部'},a
        assert a['full161_current_count']==0 and a['administrative_count']==1,a
        assert a['chain']==['ww2.cn.warzone9','ww2.cn.corps1','ww2.cn.army66'],a
        print('PASS actual DSH copies one typed opening ancestor chain and both membership views',flush=True)
        identity=next(i for i,(e,u) in commands.resolve_units(s).items() if e['name']=='第161师万家岭投入部')
        s['force_organization']=f.detach(s,[identity],'临时方向群','QA显式临时调动，不改历史编制')
        top=f.state(s)['groups'][0]['id']
        other=next(i for i,(e,u) in commands.resolve_units(s).items() if u.get('historical_unit_id')=='ww2.cn.division90')
        s['force_organization']=f.detach(s,[other],'另一路分遣','QA另一独立叶子')
        sibling=next(g['id'] for g in f.state(s)['groups'] if g['label']=='另一路分遣')
        s['force_organization']=f.wrap(s,[top,sibling],'共同方向指挥','QA保留原下级，祖先顺序不等于编号顺序')
        s['force_organization']=f.detach(s,[identity],'侦察分遣','QA下级临时指挥',parent_id=top)
        chain=f.command_chain(s,next(k for k,r in f.leaves(s).items() if r[0]==identity))
        a=ask(s,f'实际查询临时群{top}的members、ww2.cn.army66的command成员，以及kind=nodes,node_id=ww2.cn.army66,hierarchy=command的节点详情。'
            '仅返回JSON：task_members为该群成员名称数组；ancestor_chain为该群任一成员command_chain的一维字符串ID数组；'
            'still_under_army66为66军当前成员名称数组；administrative_parent为该临时群成员administrative_path最后一项id字符串；'
            'army66_effective_count取ID为ww2.cn.army66节点的execution_count整数，army66_opening_count取同节点command_execution_count整数。'
            '按工具结果区分临时祖先路径与行政参考，不额外补历史上级。','temporary_transfer')
        assert a['task_members']==['第161师万家岭投入部'] and a['ancestor_chain']==chain,a
        assert a['still_under_army66']==['第159师'] and a['administrative_parent']=='ww2.cn.division161',a
        assert a['army66_effective_count']==1 and a['army66_opening_count']==2,a
        print('PASS actual DSH reads three temporary levels and excludes old command authority',flush=True)
        old=session(enabled=False)
        a=ask(old,'实际查询get_force_organization(kind=members,node_id=ww2.cn.division161,hierarchy=command)。'
            '仅返回JSON：member_names为成员名称数组，basis为该成员command_path最后一项basis字符串，'
            'immediate_parent为该成员command_path最后一项id字符串，has_source_opening为顶层是否有command_baseline的布尔值。'
            '软件行政回退不等于新核实的历史开局指挥。','legacy_compatibility')
        assert a=={'member_names':['第161师万家岭投入部'],'basis':'legacy_administrative_fallback',
                   'immediate_parent':'ww2.cn.division161','has_source_opening':False},a
        print('PASS actual DSH identifies legacy software fallback without claiming opening evidence',flush=True)
        result.update(passed=True,meta=observer.meta())
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2)+'\n')
        h.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
