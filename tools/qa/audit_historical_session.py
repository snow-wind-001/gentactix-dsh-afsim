"""Read-only audit of persisted historical sessions; does not certify history fit."""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from backend import afsim_world
from gentactix import campaign, formation_parts, missions, sim_clock


def audit(session):
    errors=[];checks=Counter();actions=Counter();rows=[]
    def check(ok,label,turn):
        checks[label]+=1
        if not ok:errors.append({'turn':turn,'check':label})
    records=sorted((t for t in session['trajectory'] if t['turn']>0),key=lambda t:t['turn'])
    prior=None
    for record in records:
        turn=record['turn'];before=record['before'];after=record['after']
        check(turn==len(rows)+1,'continuous_turns',turn)
        if prior is not None:check(prior==before,'continuous_world',turn)
        missions.validate(before);missions.validate(after)
        check(after['current_time']==sim_clock.target(before,session['time_step'])[0],'clock',turn)
        old={u['name']:u for _,u in missions.units(before)}
        check([(t,u['name']) for t,u in missions.units(before)]==[(t,u['name']) for t,u in missions.units(after)],'roster',turn)
        receipts=[r for r in session['command_state']['receipts'] if r['turn']==turn]
        check(len(receipts)==len(old) and len({r['unit_id'] for r in receipts})==len(old),'unit_decisions',turn)
        actions.update(r['team']+':'+r['action'] for r in receipts)
        native=after['afsim'];scene=json.loads((Path(native['artifact'])/'entities.json').read_text())
        log=Path('vendor/afsim/local/afsim/state/mcp/processes')/(native['process_id']+'.stdout.txt')
        positions=afsim_world.parse_observations(log.read_text(),scene)
        ids={e['name']:i for i,e in scene['entities'].items()};ledger={r['unit']:r for r in after['mission']['ledger']}
        check(native['returncode']==0,'native_success',turn)
        for team,u in missions.units(after):
            p=u['personnel'];prev=old[u['name']];r=ledger.get(u['name'])
            check(p['current']+p['casualties']+p['noncombat_losses']==p['committed'],'personnel_balance',turn)
            check(sum(p.get(k,0) for k in ('killed','wounded','captured','missing','unclassified_casualties'))==p['casualties'],'casualty_categories',turn)
            check(p['casualties']>=prev['personnel']['casualties'] and p['noncombat_losses']>=prev['personnel']['noncombat_losses'],'cumulative_losses',turn)
            check(all(e['operational']+e['damaged']+e['destroyed']==e['committed'] for e in u['equipment']),'equipment_balance',turn)
            check(missions.distance(u,positions[ids[u['name']]])<.001,'native_position',turn)
            if r:
                for key in ('food','ammo'):
                    received=r.get(key+'_received',r['delivery'])
                    value=prev['logistics'][key]+(received-r[key+'_spent'])/formation_parts.scale(u)
                    check(abs(value-u['logistics'][key])<.00001,key+'_continuity',turn)
            else:check(prev['personnel']['current']==0,'ledger_scope',turn)
            if campaign.release_seconds(before,prev)>=sim_clock.duration_seconds(session['time_step']):
                check(missions.distance(u,prev)<.001,'waiting_unit_did_not_move',turn)
        if after.get('campaign'):check(campaign.assess(after)==after['campaign']['objective'],'campaign_goal_predicates',turn)
        rows.append({'turn':turn,'time':after['current_time'],'model_skipped':native.get('model_skipped'),
            'losses':{t:sum(u['personnel']['casualties'] for u in after[t+'_units']) for t in ('red','blue')},
            'noncombat':{t:sum(u['personnel']['noncombat_losses'] for u in after[t+'_units']) for t in ('red','blue')},
            'zero_ammo':sum(u['logistics']['ammo']==0 for _,u in missions.units(after))})
        prior=after
    world=session['war_state'];mission=world['mission']
    check(len(records)==session['turn_count'],'all_committed_rounds_present',session['turn_count'])
    return {'software_checks_passed':not errors,'errors':errors,'checks':dict(checks),'turns':len(rows),
        'deadline_turn':mission['definition']['deadline_turn'],'selected_window_reached':mission['turn']==mission['definition']['deadline_turn'],
        'mission_status':mission['status'],'winner':mission.get('winner'),'actions':dict(actions),'rows':rows,
        'full_campaign_verified':False,'historical_fit_verified':False,
        'scope':'Committed native rounds and deterministic accounting only; a selected window is not a whole historical campaign.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('session',type=Path);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    saved=json.loads(args.session.read_text());result=audit(saved['session'])
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','checks')},ensure_ascii=False))
    return int(not result['software_checks_passed'])


if __name__=='__main__':raise SystemExit(main())
