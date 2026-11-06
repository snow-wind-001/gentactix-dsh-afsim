"""Real DSH reads frozen event/command evidence, with no battle mutation."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Use --live for the configured real model')
    root=Path('.cache/qa/wanjialing-sources-2026-10-31/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from gentactix import history_replay
    from tools.upgrade_wanjialing import BATTLE
    from backend import harness_engine as h,runtime_bridge,afsim_state
    from backend.main import _native_tool_dispatch
    pinned=history_replay.pin(BATTLE,version='1.1.0');world=history_replay.frame_pinned(pinned,7)
    s=dict(id='wjl-source-links-qa',war_state=world,turn_count=7,battle_choice=BATTLE,
        execution_backend='narrative',product_mode='analysis',simulation_mode='replay',use_rag=False,history=[])
    saved=copy.deepcopy(s);calls=[];observer=h.RunObserver('万家岭来源关联真实核验');result={'passed':False}
    def dispatch(context,payload):
        r=_native_tool_dispatch(context,payload);calls.append({'tool':payload.get('tool'),'args':payload.get('args'),'response':r});return r
    runtime_bridge.register_dispatcher(dispatch)
    try:
        prompt=('请实际调用retrieve_history(kind="operations",limit=1)，不指定phase_id时应读取当前回溯事件的8日阶段；沿next_args读完。'
            '再读取kind=relations,phase_id=oct7_attack,unit_id=ww2.cn.division161.wjl_part,limit=1。'
            '只依据工具回答：8日天明后张古山最高点由哪方夺回？7日的配属是否证明整个161师永久改隶66军？工具是否给出精确地名/阵位坐标？'
            '仅返回JSON {"after_dawn_oct8_control":"red或blue", "whole_161_permanently_reassigned":布尔值,"precise_positions_supplied":布尔值}。'
            '不要下命令，不改史料，不将论文转引说成原件已核。')
        run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(s))
        answer=h.parse_json_object(run.final_response)
        assert answer=={'after_dawn_oct8_control':'blue','whole_161_permanently_reassigned':False,'precise_positions_supplied':False},answer
        reads=[c for c in calls if c['tool']=='retrieve_history'];assert len(reads)>=3,reads
        operations=[o for c in reads for o in c['response'].get('operations',[])];assert {o['id'] for o in operations}=={'WJL-Oct8-zhanggu','WJL-Oct8-hills'}
        assert any(c['response'].get('relations') for c in reads);assert s==saved
        result.update(passed=True,answer=answer,world_unchanged=True,meta=observer.meta())
        print('PASS real DSH: current event phase, paged recapture evidence and partial operational attachment',flush=True)
    finally:
        result['calls']=calls;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2))
        h.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
