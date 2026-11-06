"""Single-order intervention in native AFSIM; no historical loss quotas."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--trace',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('Use --live')
    root=Path('.cache/qa/observation-review-2026-10-29/counterfactual')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from backend import afsim_world,afsim_rules,harness_engine as h
    from gentactix import missions,sim_clock,combat_effects
    trace=json.loads(args.trace.read_text());before=trace['before'];original=copy.deepcopy(before)
    source_orders=trace['external_execution']['orders'];artillery=next(u['name'] for u in before['red_units'] if u['type']=='炮兵')
    result={'passed':False,'scope':'one-order model counterfactual; not proof of historical causation','cases':[]}
    try:
        for label in ('recorded_suppression','recon_instead'):
            orders=copy.deepcopy(source_orders)
            if label=='recon_instead':
                index=next(i for i,r in enumerate(orders) if r['unit']==artillery)
                orders[index]={'unit':artillery,'action':'recon'}
            scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
            with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
                positions,evidence=afsim_world.run_scene({},scene)
                after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                    afsim_world.apply_observations(before,positions,scene))
            after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
            missions.validate(after);assert before==original
            if label=='recorded_suppression':
                for team in ('red','blue'):
                    assert [u['personnel'] for u in after[team+'_units']]==[u['personnel'] for u in trace['after'][team+'_units']]
            gun=next(u for u in after['red_units'] if u['name']==artillery)
            result['cases'].append({'label':label,'native':{k:evidence[k] for k in ('returncode','artifact','wall_ms')},
                'artillery':{k:gun['formation']['last_execution'].get(k) for k in ('action','shots','fire_cycles')},
                'red_casualties':sum(u['personnel']['casualties'] for u in after['red_units']),
                'defenders':[{'name':u['name'],'personnel':{k:u['personnel'].get(k) for k in ('current','casualties','captured')},
                    'fortification_integrity':after['campaign']['actors'][u['name']]['fortification_integrity'],
                    'suppression':u['formation']['suppression']} for u in after['blue_units'][:2]]})
            (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2))
        a,b=result['cases'];assert a['artillery']['shots']>0 and b['artillery']['shots']==0
        assert b['defenders'][0]['personnel']['current']>a['defenders'][0]['personnel']['current']
        assert b['defenders'][0]['fortification_integrity']>a['defenders'][0]['fortification_integrity']
        result['passed']=True
    finally:
        h.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
