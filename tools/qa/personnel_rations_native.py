"""Opt-in native ration-mass checks; all rates/capacities remain QA estimates."""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--root',type=Path,default=Path('.cache/qa/personnel-rations-2026-11-03/native'));args=parser.parse_args()
    if not args.live:parser.error('--live required for actual native AFSIM')
    root=args.root
    if root.exists():raise ValueError('Preserve previous evidence')
    root.mkdir()
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import afsim_world,afsim_rules,harness_engine
    from gentactix import missions,historical_operations as ho,support_dynamics as sd,sim_clock
    from verify_personnel_rations import parameters,config
    from verify_supply_schedule import config as scheduled_config
    rows=[];result=dict(passed=False,cases=rows,actual_afsim=True,history_calibrated=False)
    def run(label,before,step,moving=False):
        old=copy.deepcopy(before);orders=[]
        for team,u in missions.units(before):
            orders.append(dict(unit=u['name'],action='move',lat=u['lat']+.0009,lng=u['lng'])
                          if moving and team=='red' else dict(unit=u['name'],action='hold'))
        seconds=sim_clock.duration_seconds(step)
        scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        (root/(label+'.afsim')).write_text(scene['script'])
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physical fallback')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,step);after['afsim']=evidence
        missions.evaluate(after);missions.validate(after);assert before==old
        assert after['historical_initial']==before['historical_initial']
        assert evidence['status']=='completed' and evidence['returncode']==0
        cfg=sd.configuration(before);accounts={r['unit']:r for r in after['mission']['ledger']}
        units=[]
        for _,u in missions.units(after):
            prior=next(v for _,v in missions.units(before) if v['name']==u['name']);account=accounts[u['name']]
            assert u['personnel']['current']==prior['personnel']['current']
            if not before['mission']['definition'].get('supply_schedule'):
                expected=sd.expected(cfg,prior,account['action'],seconds)
                assert abs(account['food_spent']-expected['consumed'])<1e-6
            assert u['sustainment']['version']==sd.PERSONNEL_VERSION
            units.append(dict(name=u['name'],current=u['personnel']['current'],food_mass_kg=sd.food_mass(cfg,u),
                food_received=account['food_received'],food_spent=account['food_spent'],
                nutrition=u['sustainment']['last_receipt']))
        rows.append(dict(label=label,seconds=seconds,units=units))
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
        print('PASS actualAFSIM',label,flush=True);return after
    try:
        s,p=parameters()
        for node in p['support'].values():node['stock']=0;node['inventory']={k:0 for k in node['inventory']}
        initial=ho.initial(s,p)
        run('same-initial-hold',initial,'30分钟');run('same-initial-red-move',initial,'30分钟',True)
        s,p=parameters(0);p['supply_schedule']=scheduled_config();p['clock']['time_step']='2小时'
        scheduled=run('scheduled-late-food',ho.initial(s,p),'2小时')
        self_red=scheduled['red_units'][0]
        assert self_red['sustainment']['last_receipt']['unmet']==1.5
        assert self_red['sustainment']['last_receipt']['consumed']==1.5
        assert all(sd.food_mass(config(),u)<=sd.food_capacity(config(),u)*config()['food_kg_per_work']+1e-6 for _,u in missions.units(scheduled))
        draft=json.loads(Path('.cache/qa/transfer-generation-2026-11-03/authoritative-draft.json').read_text())
        p=copy.deepcopy(draft['parameters']);nutrition=p['support_dynamics'];nutrition.pop('food_work_per_hour')
        nutrition.update(version=sd.PERSONNEL_VERSION,ration_kg_per_person_day=.75,food_kg_per_work=125,
            carried_kg_per_committed_person=.5,assumption='Explicit software QA dry-food/carrying estimates replacing the old root-rate only; not historical rations or loss calibration.')
        p['clock']['time_step']='6小时'
        (root/'large-parameters.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
        world=ho.initial(draft['initial'],p)
        assert sum(u['personnel']['current'] for u in world['red_units'])==33500
        first=run('four-army-six-hour-1',world,'6小时')
        second=run('four-army-six-hour-2',first,'6小时')
        assert all(u['logistics']['food']==0 for u in second['red_units'])
        assert all(u['sustainment']['shortage_hours']>0 for u in second['red_units'])
        result['passed']=True
    finally:
        harness_engine.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
