"""Real DSH repairs a cloned draft; AFSIM loads it and exercises release timing.

No existing game/configuration is written. The timing probe is software QA,
not historical calibration or a continuation of the saved Cheqiao game.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--draft',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('Use --live for real DSH and native execution')
    root=Path('.cache/qa/departure-review-2026-10-29/live')/str(time.time_ns())
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import scenario_builder,scenario_assembly,afsim_world,afsim_rules,afsim_state,runtime_bridge,harness_engine as h
    from backend.main import _native_tool_dispatch
    from gentactix import historical_operations as ho,missions,sim_clock,campaign
    from verify_cheqiao_campaign import CheqiaoCampaignTests,BATTLE
    original_bytes=args.draft.read_bytes();old=json.loads(original_bytes)
    basis=scenario_builder.historical_basis(BATTLE,'core_march5_6',version='1.3.0',time_step='30分钟')
    assembly=scenario_assembly.create(basis)
    # Seed only the isolated candidate with a previous real-model configuration.
    assembly.configuration=copy.deepcopy(old['parameters'])
    identity='ww2.jp.caodian_relief';responses=[]
    result={'passed':False,'scope':'DSH input repair, full native load and isolated timing QA; not full campaign acceptance'}
    def dispatch(context,payload):
        response=_native_tool_dispatch(context,payload)
        responses.append({'tool':payload.get('tool'),'args':payload.get('args'),
            'ok':response.get('ok'),'updated':response.get('updated'),'valid':response.get('valid'),
            'error':response.get('error')})
        return response
    runtime_bridge.register_dispatcher(dispatch)
    assert h.role_policy('scenario-builder')['reasoning_effort']=='high'
    assert h.role_policy('scenario-builder')['max_tokens']==65536
    def run(label,before,orders,seconds=1800):
        immutable=copy.deepcopy(before)
        scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat fallback')):
            positions,evidence=afsim_world.run_scene({},scene)
            world=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        if seconds==1800:world['current_time'],world['simulation_clock']=sim_clock.target(before,'30分钟')
        world['afsim']=evidence;missions.validate(world);assert before==immutable
        (root/(label+'.json')).write_text(json.dumps(world,ensure_ascii=False,indent=2))
        result.setdefault('native',[]).append({'label':label,**{k:evidence[k] for k in ('returncode','entity_count','artifact','wall_ms')}})
        return world
    try:
        bad=copy.deepcopy(assembly.configuration['campaign']['arrivals'][identity])
        bad.update(event_kind='departure',reference_id='cq_caodian_departure')
        rejected=assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':{'campaign':{'arrivals':{identity:bad}}}})
        assert not rejected['updated'] and '启程参考时间窗' in rejected['error']
        assert assembly.revision==0 and assembly.configuration==old['parameters']
        result['old_0600_rejected']=rejected['error']
        observer=h.RunObserver('启程参考修复验证')
        h.enable_afsim_runtime()
        answer=h._run_brain(
            '这是已生成草稿的局部修复验收。先调用read_scenario_skill、get_scenario_basis。'
            '根据本次史料参考，仅修复campaign.arrivals.ww2.jp.caodian_relief的not_before、event_kind、reference_id和assumption。'
            '不得修改其他字段、兵力、位置或战果；不要把资料的宽时段称为精确史实。'
            '使用update_scenario_configuration提交最小补丁，再validate_scenario_configuration验证。'
            '最终只返回JSON {"revision":当前版本,"configuration_hash":"工具返回哈希","explanation":"修正依据与限制"}。',
            None,role='scenario-builder',observer=observer,native_context=assembly.context('globals'))
        receipt=h.parse_json_object(answer.final_response)
        assert {'read_scenario_skill','get_scenario_basis','update_scenario_configuration','validate_scenario_configuration'}<={r['tool'] for r in responses}
        assert receipt['revision']==assembly.revision>0
        assert receipt['configuration_hash']==missions.digest(assembly.configuration)
        expected=copy.deepcopy(old['parameters'])
        expected['campaign']['arrivals'][identity]=copy.deepcopy(assembly.configuration['campaign']['arrivals'][identity])
        assert assembly.configuration==expected
        world=ho.initial(basis['initial'],assembly.configuration)
        loaded=run('full-native-load',world,[],.001)
        assert len(loaded['red_units'])+len(loaded['blue_units'])==19
        result.update(repair_receipt=receipt,repair_engine=observer.meta(),schedule=assembly.configuration['campaign']['arrivals'][identity])
        (root/'parameters.json').write_text(json.dumps(assembly.configuration,ensure_ascii=False,indent=2))
        (root/'basis.json').write_text(json.dumps(basis,ensure_ascii=False,indent=2))
        print('PASS real DSH minimal draft repair and full 19-entity native load',flush=True)

        s,p,i=CheqiaoCampaignTests().departure_inputs()
        p['goal']['deadline_turn']=4  # Keep this QA mission open for the post-release move.
        target=copy.deepcopy(p['actors'][i]['position']);p['actors'][i]['position']['lat']+=.01
        before=ho.initial(s,p);name=before['blue_units'][-1]['name']
        waiting=run('qa-wait',before,[])
        assert not waiting['campaign']['actors'][name]['active']
        released=run('qa-release',waiting,[])
        assert released['campaign']['actors'][name]['active']
        for w in (waiting,released):
            unit=w['blue_units'][-1]
            assert (unit['lat'],unit['lng'])==(before['blue_units'][-1]['lat'],before['blue_units'][-1]['lng'])
            for field,value in before['blue_units'][-1]['personnel'].items():
                assert unit['personnel'][field]==value
            assert all(unit['personnel'][key]==0 for key in ('killed','wounded','captured','missing'))
        moved=run('qa-commanded-move',released,[{'unit':name,'action':'move',**target}])
        assert missions.distance(moved['blue_units'][-1],target)<missions.distance(released['blue_units'][-1],target)
        assert campaign.observation(moved)['actors'][-1]['event_kind']=='departure'
        print('PASS native wait, release without teleport and commanded movement',flush=True)

        session={'id':'departure-observer-qa','war_state':loaded,'turn_count':0,'time_step':'30分钟',
                 'execution_backend':'afsim','history':[],'trajectory':[],'use_rag':False}
        observation=afsim_state.observation(session,{'offset':16,'limit':16})
        unit=next(u for u in observation['units'] if u['name'].startswith('曹甸'))
        frozen=copy.deepcopy(session);reader=h.RunObserver('启程时点原生观测验证')
        answer=h._run_brain('只调用get_afsim_observation读取这个单位：'+unit['id']+'。'
            '根据实际观测返回JSON {"name":"单位名","not_before":"可行动起点","active":是否已解锁,"event_kind":"时点类型",'
            '"reference_id":"时点引用","meaning":"说明解锁与真正移动／接敌的区别"}。不要下命令或更改配置。',
            None,role='chat',observer=reader,native_context=afsim_state.operation_context(session))
        observed=h.parse_json_object(answer.final_response)
        expected_schedule=next(r for r in campaign.observation(loaded)['actors'] if r['name']==unit['name'])
        assert observed['name']==unit['name'] and observed['active'] is False
        assert observed['not_before']==expected_schedule['not_before']
        assert observed['event_kind']=='departure' and observed['reference_id']=='cq_caodian_departure'
        assert any(r['tool']=='get_afsim_observation' for r in responses)
        assert session==frozen and args.draft.read_bytes()==original_bytes
        result.update(passed=True,observation=observed,observation_engine=reader.meta(),tools=responses,original_draft_unchanged=True)
        print('PASS real DSH observation and preserved original draft',flush=True)
    finally:
        scenario_assembly.close(assembly.id);h.close_harness()
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        Path('.cache/qa/departure-review-2026-10-29/live-latest.txt').write_text(str(root))
        print(str(root),flush=True)


if __name__=='__main__':main()
