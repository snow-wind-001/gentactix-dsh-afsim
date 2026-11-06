"""Real AFSIM control/intervention for a mixed formation task; numerical QA."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Use --live for real AFSIM')
    root=Path('.cache/qa/force-tasks-2026-10-31/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),
                       ('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from verify_force_tasks import session,ForceTaskTests
    from gentactix import force_tasks as t,commands,missions,sim_clock
    from backend import afsim_world,afsim_rules,harness_engine
    s,ids,g,enemy=session();s['execution_backend']='afsim';before=copy.deepcopy(s)
    task=ForceTaskTests().intent(ids,enemy);plan=t.preview(s,g,task)
    s['command_state']=t.commit(s,g,task,plan['preview_hash']);prepared=commands.prepare(s)
    orders=[r['order'] for r in prepared['manual']];results={}
    try:
        for label,chosen in [('hold',[]),('mixed-task',orders)]:
            scene=afsim_world.compile_scene(before['war_state'],chosen,1800,native_rules=True)
            started=time.monotonic()
            with patch.object(missions,'advance',side_effect=AssertionError('Actual AFSIM required')):
                positions,evidence=afsim_world.run_scene({},scene)
                after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                    afsim_world.apply_observations(before['war_state'],positions,scene))
            after['current_time'],after['simulation_clock']=sim_clock.target(before['war_state'],'30分钟')
            missions.validate(after)
            (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False))
            results[label]={'world':after,'seconds':round(time.monotonic()-started,3)}
        hold=results['hold']['world'];after=results['mixed-task']['world']
        assert sum(u['personnel']['casualties'] for u in hold['blue_units'])==0
        damage=sum(u['personnel']['casualties'] for u in after['blue_units']);assert damage>0
        new={u['name']:u for _,u in missions.units(after)}
        units=commands.resolve_units(s)
        artillery=units[ids[1]][1];engineer=units[ids[2]][1];reserve=units[ids[3]][1]
        assert new[artillery['name']]['formation']['shells']<artillery['formation']['shells']
        assert missions.distance(new[engineer['name']],engineer)<.001
        assert missions.distance(new[reserve['name']],reserve)<.001
        cs,decisions=commands.finish(s,prepared,after,executed=orders)
        own=[r for r in cs['receipts'] if r['unit_id'] in ids]
        assert len(own)==4 and all(r['task_context']['group_id']==g for r in own)
        assert len(after['red_units'])+len(after['blue_units'])==79
        summary={'passed':True,'scope':'79 numerical QA leaves, explicit roles, same-state native intervention; not historical calibration',
            'actions':{r['role']:r['order']['action'] for r in plan['rows']},'hold_blue_casualties':0,
            'mixed_blue_casualties':damage,'receipts':own,'times':{k:v['seconds'] for k,v in results.items()}}
        (root/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        print('PASS real mixed fire/artillery/engineer-wait/reserve task vs hold; receipts preserve task source',flush=True)
    finally:
        harness_engine.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
