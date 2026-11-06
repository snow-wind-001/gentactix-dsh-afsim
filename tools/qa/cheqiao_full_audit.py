"""Audit an actual DSH-generated full-window draft, without filling any gaps."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from gentactix import campaign, historical_operations, missions


def audit(draft):
    errors=[]
    def check(condition, message):
        if not condition:errors.append(message)
    snapshot=draft['initial'];p=draft['parameters']
    world=historical_operations.initial(snapshot,p)
    missions.validate(world)
    units=list(missions.units(world))
    check(snapshot['version'] in ('1.1.0','1.2.0') and snapshot['phase_id']=='core_march5_6','wrong source version/window')
    check(len(p['actors'])==15,'not all fifteen sourced actors are configured')
    check(len(units)==19,'expected fifteen parents with two-way assault and four relief batches (nineteen leaves)')
    check(p['goal']['deadline_turn']==57 and p['clock']['time_step']=='30分钟','full fifty-seven-turn window not preserved')
    check(datetime.fromisoformat(p['clock']['start'])==datetime(1944,3,5,1,50),'opening time changed')
    groups=(p.get('partitions') or {}).get('groups',{})
    assault=groups.get('ww2.cn.new4_regiment7',{}).get('parts',[])
    relief=groups.get('ww2.jp.huaian_relief',{}).get('parts',[])
    check(len(assault)==2 and len(relief)==4,'required disjoint assault/relief allocations missing')
    if snapshot['version']=='1.2.0':
        phase=next(x for x in snapshot['definition']['phases'] if x['id']==snapshot['phase_id'])
        bounds=phase['input_constraints']['personnel'][0]
        check(bounds['minimum']<=p['actors'][bounds['unit_id']]['personnel']<=bounds['maximum'],
              'town garrison exceeds explicit source-associated modelling envelope')
        center=p['goal']['objective']
        check(any(x['position']['lat']>center['lat'] for x in assault) and
              any(x['position']['lat']<center['lat'] and x['position']['lng']<center['lng'] for x in assault),
              'assault partition positions do not represent separate north and southwest approaches')
        refs={x['id']:x for x in phase['input_constraints']['entries']}
        entries=p['campaign']['arrivals']['ww2.jp.huaian_relief'].get('parts',{})
        check({x.get('reference_id') for x in entries.values()}==set(refs),'not all contact references are bound')
        for part in relief:
            entry=entries.get(part['id'],{});ref=refs.get(entry.get('reference_id'))
            check(entry.get('event_kind')=='battlefield_entry' and bool(ref) and
                  missions.distance(part['position'],ref['region']['center'])<=ref['region']['radius_km']+.001,
                  'requested forward entry was incorrectly located at a remote departure base')
    check(len(p['campaign']['objective']['relief_regions'])==2,'northwest/south blocking regions missing')
    actual=[]
    for _,u in units:
        when=datetime.fromisoformat(campaign.scheduled_time(world['mission']['definition']['campaign_definition'],u))
        if u['historical_unit_id']=='ww2.jp.huaian_relief':actual.append(when)
        if u['historical_unit_id']=='ww2.cn.new4_regiment7':
            check(when==datetime(1944,3,5,1,50),'simultaneous two-route initial assault became an unsupported later echelon')
    expected=[datetime(1944,3,5,15,15),datetime(1944,3,5,16),datetime(1944,3,5,17,30),datetime(1944,3,6,2,30)]
    check(sorted(actual)==expected,'four relief leaves do not have the four explicitly requested source/estimate arrival times')
    check(all(u['facts'][f]['value'] is None for u in snapshot['definition']['units']
        for f in ('personnel','equipment','position')),'model parameters contaminated unknown source facts')
    evidence=draft.get('afsim') or {}
    check(evidence.get('status')=='completed' and evidence.get('returncode')==0,'missing successful actual AFSIM load')
    check(evidence.get('entity_count')==len(units),'native entity count disagrees with configured leaves')
    check(draft['construction'].get('source')=='dsh_native_skill','missing DSH native skill construction')
    return {'passed':not errors,'errors':errors,'scope':'full-window input/load audit; not turn execution or historical outcome acceptance',
        'draft_id':draft['id'],'version':snapshot['version'],'actors':len(p['actors']),'leaves':len(units),
        'clock':p['clock'],'deadline_turn':p['goal']['deadline_turn'],
        'relief_arrivals':[d.isoformat() for d in sorted(actual)],
        'native':{k:evidence.get(k) for k in ('status','returncode','entity_count','wall_ms')},
        'initial_units':[{'name':u['name'],'team':team,'parent':u['historical_unit_id'],
            'personnel':u['personnel']['current'],'lat':u['lat'],'lng':u['lng'],
            'active':world['campaign']['actors'][u['name']]['active']} for team,u in units]}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('draft',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result=audit(json.loads(args.draft.read_text()))
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('initial_units','clock')},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
