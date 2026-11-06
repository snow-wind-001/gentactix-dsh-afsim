"""Real AFSIM timed delivery contrasts; all inputs are uncalibrated QA priors."""
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
    parser.add_argument('--smoke',action='store_true',help='Only six-hour initial execution')
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=Path('.cache/qa/supply-schedule-2026-11-01/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from verify_supply_schedule import world
    from gentactix import missions,sim_clock
    from backend import afsim_rules,afsim_world,harness_engine
    result={'passed':False,'actual_model':False,'actual_afsim':True,'cases':[],
            'scope':'Fixed-time food/ammo/classified supply over QA actors; not historical calibration or individual convoy transit'}
    def save():(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def run(label,before):
        frozen=copy.deepcopy(before);seconds=sim_clock.duration_seconds(before['mission']['definition']['time_step'])
        scene=afsim_world.compile_scene(before,[],seconds,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Native required')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,before['mission']['definition']['time_step'])
        missions.evaluate(after);missions.validate(after);assert before==frozen
        assert len(missions.units(after))==3
        for _,u in missions.units(after):
            p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        path=root/(label+'.json');path.write_text(json.dumps(after,ensure_ascii=False)+'\n')
        result['cases'].append({'label':label,'elapsed_s':after['simulation_clock']['elapsed_seconds'],
            'food':{u['name']:u['logistics']['food'] for _,u in missions.units(after)},'native':evidence})
        save();print('PASS',label,flush=True);return after
    try:
        long=run('6h',world())
        if args.smoke:
            result['passed']=True;return
        finals={21600:long}
        for label,step,count in [('60m','1小时',6),('15m','15分钟',24),('5m','5分钟',72)]:
            state=world(step=step)
            for i in range(count):state=run(label+'-'+str(i+1),state)
            finals[sim_clock.duration_seconds(step)]=state
        base={u['name']:u for _,u in missions.units(long)}
        for step,state in finals.items():
            for _,u in missions.units(state):
                prior=base[u['name']]
                for key in ('food','ammo'):assert abs(u['logistics'][key]-prior['logistics'][key])<1e-6
                for key in ('shortage_hours','noncombat_remainder'):assert abs(u['sustainment'][key]-prior['sustainment'][key])<1e-6
                assert u['personnel']==prior['personnel']
                for key in ('shells','aa_rounds','fuel_liters','spares','materials'):assert u['formation'][key]==prior['formation'][key]
            for left,right in zip(long['supply_nodes'],state['supply_nodes']):
                assert abs(left['stock']-right['stock'])<1e-6
                for key in ('food','ammo'):assert abs(left['commodities'][key]-right['commodities'][key])<1e-6
        result.update(passed=True,hold_supply_partition_invariance=True,steps_seconds=sorted(finals),total_elapsed_seconds=21600,
            comparison_scope='same stationary hold orders and schedule; not fire/movement/terrain or all outcome invariance')
    except Exception as exc:
        result['error']=str(exc);raise
    finally:
        save();harness_engine.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
