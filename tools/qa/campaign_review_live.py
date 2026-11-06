"""AFSIM executes one real turn; DSH reads its committed operational state."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Use --live')
    root=Path('.cache/qa/cheqiao-complete/review')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(Path('.cache/qa/ww2-phases/runtime/llm.enc').resolve())
    from backend import afsim_world,afsim_rules,afsim_state,runtime_bridge,harness_engine as h
    from backend.main import _native_tool_dispatch
    from gentactix import historical_operations as ho,missions,sim_clock
    from tools.qa.campaign_fixture import inputs
    result={'passed':False,'scope':'actual native process observation QA; not full historical battle'}
    responses=[]
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload)
        responses.append({'tool':payload.get('tool'),'ok':response.get('ok'),
                          'total_units':response.get('total_units'),'error':response.get('error')})
        return response
    runtime_bridge.register_dispatcher(dispatch)
    policy=h.role_policy('chat');assert policy['reasoning_effort']=='high' and policy['max_tokens']==65536
    try:
        before=ho.initial(*inputs());scene=afsim_world.compile_scene(before,[],1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            positions,evidence=afsim_world.run_scene({},scene)
            world=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        world['current_time'],world['simulation_clock']=sim_clock.target(before,'30分钟');world['afsim']=evidence
        missions.validate(world)
        session={'id':'campaign-native-review','war_state':world,'turn_count':1,'time_step':'30分钟',
                 'execution_backend':'afsim','history':[],'trajectory':[],'use_rag':False,'scenario_input':'明确QA过程验证'}
        original=copy.deepcopy(session);observer=h.RunObserver('完整战役过程只读复核')
        _,answer=h.ask_xuanji([],world,[],
            '只调用get_afsim_observation一次，limit=16。根据实际返回，列出各单位是否已经入场、最早入场时间、工事完整度、'
            '本轮被俘数，再说明三项战役目标当前是否满足、会否因只占据点提前结束。500字以内；不下命令、不试算、不查额外资料。'
            '这是QA估计配置，不能称作历史实测。',observer=observer,native_context=afsim_state.operation_context(session))
        assert session==original
        calls=[]
        for path in (root/'dsh-home').glob('sessions/*/*/session.v4.jsonl'):
            for line in path.read_text().splitlines():
                row=json.loads(line)
                if row.get('type')=='tool/call':
                    data=row.get('data') or {};calls.append({'name':data.get('name'),'arguments':data.get('arguments',data.get('args'))})
        assert any(r['name']=='get_afsim_observation' for r in calls)
        assert any(r['tool']=='get_afsim_observation' and r['ok'] is True and r['total_units']==3 for r in responses),responses
        (root/'answer.txt').write_text(answer+'\n')
        (root/'world.json').write_text(json.dumps(world,ensure_ascii=False,indent=2)+'\n')
        result.update(passed=True,world_unchanged=True,tools=calls,responses=responses,engine_meta=observer.meta())
        print('PASS native state and real DSH observation',flush=True)
    finally:
        h.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        Path('.cache/qa/cheqiao-complete/review-latest.json').write_text(json.dumps({'directory':str(root),'passed':result['passed']})+'\n')


if __name__=='__main__':main()
