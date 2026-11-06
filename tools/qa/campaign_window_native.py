"""Real readonly Native scope lookup plus one AFSIM QA integration step.

This is not a reconstructed five-day campaign or calibrated casualty test.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('--live required for configured model and AFSIM')
    root=Path('.cache/qa/campaign-window-2026-11-01/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import main as app, scenario_builder as sb, scenario_assembly as sa
    from backend import harness_engine as h, runtime_bridge, afsim_world, afsim_rules
    from gentactix import historical_operations as ho, missions, sim_clock
    from tools.qa.campaign_window_fixture import inputs
    from tools.upgrade_wanjialing import BATTLE
    s,p=inputs();basis=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',termination_mode='objectives')
    assembly=sa.create(basis);before=copy.deepcopy(assembly.configuration);calls=[]
    result=dict(passed=False,actual_model=True,actual_afsim=False,cases=[],
        scope='Readonly window/source/partial-force interpretation and one 22-actor numerical QA step; not a full historical window')
    def save(): (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def dispatch(context,payload):
        response=app._native_tool_dispatch(context,payload)
        calls.append(dict(tool=payload.get('tool'),args=payload.get('args'),response=response))
        return response
    runtime_bridge.register_dispatcher(dispatch)
    observer=h.RunObserver('会战窗口来源与投入范围只读验收')
    part=next(k for k in assembly.parts if 'ww2.jp.regiment149' in assembly.assigned(k))
    cases=[('globals',
        '只根据readonly_campaign_window与actor_counts回答JSON：'
        '{"window_id":"ID","actors":两方actor_counts合计整数,"source_version":"绑定的历史初态版本",'
        '"planning_end":"bounds.end原字符串","forces_follow_historical_orders":是否强迫按史实时钟执行布尔值}。',
        dict(window_id='WJL-oct6-10',actors=22,source_version='1.3.0',planning_end='1938-10-11T00:00:00',forces_follow_historical_orders=False)),
        (part,'只检查本片ww2.jp.regiment149的parent_id、facts、window_scope。回答JSON：'
        '{"administrative_parent_id":"行政上级ID","presence_basis":"window_scope原字符串",'
        '"whole_regiment_strength_known":是否已核全联队人数布尔值,"may_treat_as_confirmed_oct6_presence":是否可称6日确证在场布尔值}。',
        dict(administrative_parent_id='ww2.jp.division101',presence_basis='prior_reference',whole_regiment_strength_known=False,may_treat_as_confirmed_oct6_presence=False))]
    try:
        for index,(part,question,expected) in enumerate(cases):
            start=len(calls);began=time.monotonic()
            reply,binding=h.unit_run(None,'先实际调用read_scenario_skill和get_scenario_basis。'
                '只读审查，不调用更新工具，不补造未知人数、阵位或到场。'+question,observer,
                context=assembly.context(part,read_only=True),namespace='campaign-window-'+assembly.id,role='scenario-builder',dispose_on_failure=True)
            answer=h.parse_json_object(reply.final_response);actual=calls[start:]
            result['cases'].append(dict(part=part,answer=answer,expected=expected,calls=actual,
                seconds=round(time.monotonic()-began,3),finish_reason=reply.finish_reason,binding=binding));save()
            assert reply.finish_reason=='completed' and answer==expected,'Real public answer differs; retained result.json'
            assert {'read_scenario_skill','get_scenario_basis'}<={c['tool'] for c in actual}
            assert not any(c['tool']=='update_scenario_configuration' for c in actual)
            assert assembly.configuration==before and assembly.revision==0
            print('PASS real Native readonly',part,flush=True)
        world=ho.initial(s,p);scene=afsim_world.compile_scene(world,[],1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Native integration required')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(world,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(world,'30分钟')
        missions.validate(after)
        assert len(after['red_units'])==17 and len(after['blue_units'])==5
        assert after['historical_initial']==world['historical_initial']
        assert after['mission']['definition']['historical_calculation']['parameters']['campaign_scope']==p['campaign_scope']
        for _,u in missions.units(after):
            a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        (root/'afsim-world.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
        result.update(passed=True,actual_afsim=True,afsim=evidence,units=22,configuration_unchanged=True)
        print('PASS native 22-actor hold integration and resource accounts',flush=True)
    except Exception as exc:
        result['error']=str(exc);raise
    finally:
        result['observer']=observer.meta();save();sa.close(assembly.id);h.close_harness()
        print('Evidence:',root,flush=True)


if __name__=='__main__':main()
