"""Opt-in AFSIM component checks for nine new, explicitly estimated local phases.

This bypasses model generation only in QA. It does not provide or certify the
normal DSH launch workflow; that is tested separately by korean_series_live.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Native AFSIM requires --live')
    out=Path('.cache/qa/korean-series/native')/str(time.time_ns());out.mkdir(parents=True)
    (out.parent/'latest.json').write_text(json.dumps({'directory':str(out)}))
    for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
        ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):
        os.environ['GENTACTIX_'+key]=str(out.resolve()/suffix)
    from backend import afsim_world,afsim_rules
    from gentactix import historical_initial as hi,missions,combined_arms,sim_clock
    from gentactix import historical_operations as ho
    from tools.qa.korean_series_fixture import inputs
    cases=[]
    for row in hi.catalog():
        if row['profile_id'] and row['profile_id'].startswith('KW') and row['profile_id']!='KW01-first':
            for phase in hi.definition(row['battle'])['phases'][1:]:cases.append((row['profile_id'],phase['id']))
    results=[]
    def native(world,orders):
        scene=afsim_world.compile_scene(world,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            positions,evidence=afsim_world.run_scene({},scene)
            observed=afsim_world.apply_observations(world,positions,scene)
            after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,observed)
        after['current_time'],after['simulation_clock']=sim_clock.target(world,'30分钟')
        missions.validate(after)
        return after,{k:v for k,v in evidence.items() if k!='native_effects'}
    try:
        for identity,phase in cases:
            record={'id':identity,'phase':phase,'passed':False,'historical_fit_verified':False};results.append(record)
            snapshot,params=inputs(identity,phase);world=ho.initial(snapshot,params)
            units=missions.units(world);orders=[]
            for team,u in units:
                target=min((e for t,e in units if t!=team),key=lambda e:missions.distance(u,e))
                action='bombard' if 'bombard' in combined_arms.actions(world,u,team) else 'fire'
                orders.append({'unit':u['name'],'action':action,'target':target['name']})
            baseline=copy.deepcopy(world)
            after,evidence=native(world,orders)
            held,hold_evidence=native(world,[o for o in orders if any(t=='blue' and u['name']==o['unit'] for t,u in units)])
            assert world==baseline
            assert evidence['returncode']==0 and evidence['entity_count']==len(units)
            assert after['historical_initial']==snapshot
            totals={t:sum(u['personnel']['casualties'] for u in after[t+'_units']) for t in ('red','blue')}
            assert totals['red']>0 and totals['blue']>0
            assert sum(u['personnel']['casualties'] for u in held['blue_units'])==0
            assert all(u['personnel']['committed']==u['personnel']['current']+u['personnel']['casualties']+u['personnel']['noncombat_losses']
                and u['personnel']['casualties']==sum(u['personnel'].get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
                and all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']) for _,u in missions.units(after))
            record.update(passed=True,totals=totals,entity_count=evidence['entity_count'],
                checks=['native completion','exact phase actor count','frozen facts','bilateral positive fire effects',
                    'withheld red fire yields zero blue casualties','personnel and classified equipment conservation','source world unchanged'],
                evidence=evidence,counterfactual_evidence=hold_evidence)
            (out/(identity+'-'+phase+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2))
            print(identity,phase,'PASS',totals,flush=True)
    except Exception as exc:
        if results:results[-1]['error']=str(exc)
        raise
    finally:
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
