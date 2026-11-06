"""Actual AFSIM timing comparisons; no model, API mocks or historical fit claim."""
import argparse
import copy
import json
import os
from pathlib import Path

ROOT=Path('.cache/qa/c2-observation-2026-10-31/native')


def main():
    global ROOT
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--out',type=Path,default=ROOT)
    args=parser.parse_args()
    if not args.live:parser.error('Actual native execution requires --live')
    ROOT=args.out
    ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'result.json').exists():raise SystemExit('Preserve existing actual run')
    for key,suffix in [('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((ROOT/suffix).resolve())
    from backend import afsim_world,afsim_rules,harness_engine as h
    from gentactix import historical_operations as ho,missions,sim_clock,combat_effects
    from tools.qa.historical_operational_fixture import inputs,NOTE
    samples=[]
    def world(step):
        source,p=inputs();p['clock']['time_step']=step;p['goal']['deadline_turn']=20
        for a in p['actors'].values():a['formation']['intel_age_min']=10.25
        p['actors'][next(reversed(p['actors']))]['formation']['intel_confidence']=0
        return ho.initial(source,p)
    def run(label,before,step,recon=False):
        saved=copy.deepcopy(before);orders=[dict(unit=u['name'],action='hold') for _,u in missions.units(before)]
        if recon:orders[0]['action']='recon'
        seconds=sim_clock.duration_seconds(step);scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        positions,evidence=afsim_world.run_scene({},scene)
        (ROOT/(label+'-native-receipt.json')).write_text(json.dumps(dict(before=before,orders=orders,evidence=evidence),ensure_ascii=False,indent=2))
        after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,step);missions.validate(after)
        assert before==saved
        receipts=after['combined_arms']['events'];first=after['red_units'][0]
        event=next((e for e in receipts if e['action']=='recon'),None)
        if event:assert abs(first['formation']['intel_age_min']-(seconds-event['seconds'])/60)<1e-7
        else:
            for (_,a),(_,b) in zip(missions.units(before),missions.units(after)):
                assert abs(b['formation']['intel_age_min']-a['formation']['intel_age_min']-seconds/60)<1e-7
        assert after['blue_units'][-1]['formation']['intel_confidence']==0
        (ROOT/(label+'.json')).write_text(json.dumps(dict(before=before,after=after,evidence=evidence),ensure_ascii=False,indent=2))
        row=dict(label=label,seconds=seconds,age_min=first['formation']['intel_age_min'],refresh=event,
            confidence=first['formation']['intel_confidence'],
            returncode=evidence['returncode'],intelligence=after['combined_arms']['intelligence'])
        samples.append(row);print('PASS actual native',row,flush=True);return after
    result=dict(passed=False,actual_afsim=True,model_calls=False,samples=samples,assumption=NOTE)
    try:
        full=run('full-30',world('30分钟'),'30分钟')
        half=run('half-15a',world('15分钟'),'15分钟');half=run('half-15b',half,'15分钟')
        assert full['red_units'][0]['formation']['intel_age_min']==half['red_units'][0]['formation']['intel_age_min']
        assert abs(full['red_units'][0]['formation']['intel_confidence']-half['red_units'][0]['formation']['intel_confidence'])<1e-7
        assert full['red_units'][0]['formation']['intel_confidence']==70
        run('subminute',world('0.5分钟'),'0.5分钟')
        refreshed=run('recon-30',world('30分钟'),'30分钟',True)
        assert samples[-1]['refresh'] is not None
        run('post-recon-30',refreshed,'30分钟')
        run('recon-not-delivered',world('0.5分钟'),'0.5分钟',True)
        assert samples[-1]['refresh'] is None
        legacy=world('15分钟');profile=combat_effects.reference(legacy)
        profile['version']='aggregate-fire-cycles-2.1';profile['definition_hash']=combat_effects.digest({k:v for k,v in profile.items() if k!='definition_hash'})
        legacy['combat_reference']=profile;run('legacy-15',legacy,'15分钟')
        result.update(passed=True,clock_partition_age_equal=True,clock_partition_confidence_equal=True,
            scope='Intelligence-age/confidence timing and receipt parity only; command networking and whole-physics step invariance are not accepted here')
    finally:
        (ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));h.close_harness()


if __name__=='__main__':main()
