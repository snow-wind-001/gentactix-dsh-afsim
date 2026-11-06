"""Real native-engine sensitivity and uniform battle-schema acceptance."""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',action='store_true');args=parser.parse_args()
    out=ROOT/'.cache/qa/combined-arms'/('run-'+str(time.time_ns()));out.mkdir(parents=True)
    (out.parent/'latest.json').write_text(json.dumps({'directory':str(out)}))
    for name,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')):
        os.environ['GENTACTIX_'+name]=str(out/suffix)
    os.environ['GENTACTIX_DSH_PATCHES']='[]'
    from backend import afsim_world,afsim_rules
    from gentactix import missions,combined_arms,sim_clock,fire_control,commands
    results=[]
    def case(name,fn):
        start=time.monotonic()
        try:r={'case':name,'passed':True,**(fn() or {})}
        except Exception as e:r={'case':name,'passed':False,'error':str(e)[:1500]}
        r['seconds']=round(time.monotonic()-start,3);results.append(r)
        print(json.dumps(r,ensure_ascii=False),flush=True);(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    def initial():return missions.initial('CA-AJ18-v1')
    def turn(w,orders):
        scene=afsim_world.compile_scene(w,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Python combat executor used')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(w,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(w,'30分钟')
        after['afsim']={k:v for k,v in evidence.items() if k!='native_effects'}
        after['afsim']['effects_source']=afsim_rules.VERSION
        missions.validate(after);fire_control.enforce(after,w)
        return after
    def order(w,i,action,target=None,**kw):
        o={'unit':w['red_units'][i]['name'],'action':action,**kw}
        if target is not None:o['target']=w['blue_units'][target]['name']
        return o
    def fire():
        w=initial();a=turn(w,[order(w,2,'bombard',0)])
        b=copy.deepcopy(w);b['blue_units'][0]['formation'].update(entrenchment=90,protection=.9,dispersion_km2=3)
        b=turn(b,[order(b,2,'bombard',0)])
        loss=lambda x:x['blue_units'][0]['personnel']['casualties']
        assert loss(a)>loss(b),(loss(a),loss(b))
        assert a['red_units'][2]['formation']['last_execution']['shots']==24
        assert a['red_units'][2]['formation']['reload_remaining']==1
        assert 'bombard' not in combined_arms.actions(a,a['red_units'][2],'red')
        restored=turn(a,[]);assert restored['red_units'][2]['formation']['reload_remaining']==0
        assert a['blue_units'][0]['formation']['suppression']>0
        return {'open_loss':loss(a),'protected_dispersed_loss':loss(b),'salvo':24,'reload_enforced':True,'suppression':a['blue_units'][0]['formation']['suppression']}
    case('classified_fire_protection_dispersion_suppression_and_reload',fire)
    def transport():
        w=initial();a=turn(w,[])
        missing=copy.deepcopy(w);e=next(e for e in missing['red_units'][0]['equipment'] if e['category']=='transport');e.update(operational=0,damaged=0,destroyed=e['committed'])
        b=turn(missing,[])
        assert a['mission']['ledger'][0]['delivery']==2 and b['mission']['ledger'][0]['delivery']==0
        repair=turn(w,[order(w,0,'repair_equipment')]);u=repair['red_units'][0]
        assert u['formation']['spares']==18 and u['formation']['last_execution']['repaired']==2
        dry=copy.deepcopy(w);dry['red_units'][0]['formation']['fuel_liters']=0
        dry=turn(dry,[]);assert dry['mission']['ledger'][0]['delivery']==0
        return {'no_transport_delivery':0,'no_fuel_delivery':0,'repaired':2,'spares_spent':2,'normal_delivery_tons':a['red_units'][0]['formation']['last_execution']['delivery_tons_milli']/1000}
    case('transport_fuel_spares_and_equipment_conservation',transport)
    def bridge():
        w=initial();b=w['combined_arms']['bridge'];u=w['red_units'][0];u.update(lat=b['lat'],lng=b['lng']-.002)
        destination={'lat':b['lat'],'lng':b['lng']+.005}
        closed=turn(w,[order(w,0,'move',**destination)]);assert closed['red_units'][0]['formation']['last_execution']['blocked']==1
        assert commands.distance(u,closed['red_units'][0])<.001
        built=turn(w,[order(w,0,'build_bridge')]);built=turn(built,[order(built,0,'build_bridge')])
        assert built['combined_arms']['bridge']['progress']==100 and built['combined_arms']['bridge']['materials']==32
        limited=copy.deepcopy(w);limited['combined_arms']['bridge'].update(progress=100,capacity=1)
        limited['red_units'][1].update(lat=b['lat']+.001,lng=b['lng']-.002)
        crossing=turn(limited,[order(limited,0,'move',**destination),order(limited,1,'move',**destination)])
        assert crossing['red_units'][1]['formation']['last_execution']['blocked']==2
        assert crossing['combined_arms']['bridge']['used']==1
        return {'closed_movement_blocked':True,'construction_turns':2,'material_cost':8,'capacity_limited':True}
    case('engineering_bridge_construction_and_shared_crossing_capacity',bridge)
    def command():
        w=initial();destination={'lat':w['red_units'][0]['lat']+.004,'lng':w['red_units'][0]['lng']}
        fast=copy.deepcopy(w);fast['red_units'][0]['formation'].update(fatigue=0,suppression=0,signal=100)
        slow=copy.deepcopy(w);slow['red_units'][0]['formation'].update(fatigue=70,suppression=70,signal=10)
        a=turn(fast,[order(fast,0,'move',**destination)]);b=turn(slow,[order(slow,0,'move',**destination)])
        fa=a['red_units'][0]['formation']['last_execution'];fb=b['red_units'][0]['formation']['last_execution']
        assert fa['distance_milli']>fb['distance_milli'] and fa['delay_s']<fb['delay_s']
        recon=turn(w,[order(w,2,'recon')]);assert recon['red_units'][2]['formation']['intel_age_min']==0
        old=copy.deepcopy(w);old['red_units'][2]['formation'].update(intel_age_min=180,intel_confidence=30)
        old=turn(old,[order(old,2,'bombard',0)]);fresh=turn(recon,[order(recon,2,'bombard',0)])
        assert fresh['blue_units'][0]['personnel']['casualties']>old['blue_units'][0]['personnel']['casualties']
        return {'fast_distance_m':fa['distance_milli']/1000,'degraded_distance_m':fb['distance_milli']/1000,
                'fast_delay_s':fa['delay_s'],'degraded_delay_s':fb['delay_s'],'recon_age_min':0}
    case('fatigue_suppression_communication_delay_and_intel_freshness',command)
    def air():
        w=initial();w['combined_arms']['aa_loss_remainder']={'red':0,'blue':.95}
        a=turn(w,[order(w,0,'air_support',0)])
        noaa=copy.deepcopy(w)
        for u in noaa['blue_units']:u['formation']['aa_rounds']=0
        b=turn(noaa,[order(noaa,0,'air_support',0)])
        assert sum(u['formation']['last_execution']['aa_spent'] for u in a['blue_units'])>0
        assert a['air_operations']['assets']['red']['destroyed']>b['air_operations']['assets']['red']['destroyed']
        assert b['blue_units'][0]['personnel']['casualties']>=a['blue_units'][0]['personnel']['casualties']
        return {'armed_aircraft_losses':a['air_operations']['assets']['red']['destroyed'],'empty_aa_losses':b['air_operations']['assets']['red']['destroyed'],
                'defense_rounds_spent':sum(u['formation']['last_execution']['aa_spent'] for u in a['blue_units'])}
    case('native_air_strike_defense_ammunition_and_aircraft_ledger',air)
    if args.catalog:
        for spec in combined_arms.catalog():
            def check(spec=spec):
                w=missions.initial(spec['id']);after=turn(w,[]);reloaded=json.loads(json.dumps(after));missions.validate(reloaded)
                return {'battle':spec['battle'],'era':spec['combined_rules']['era'],'turn':after['mission']['turn']}
            case('catalog/'+spec['id'],check)
    (out/'summary.json').write_text(json.dumps({'passed':sum(x['passed'] for x in results),'failed':sum(not x['passed'] for x in results),'directory':str(out)},ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(x['passed'] for x in results) else 1)


if __name__=='__main__':main()
