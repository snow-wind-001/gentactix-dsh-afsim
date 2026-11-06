"""Read-only audit of committed long-run frames, native positions and ledgers.

Partial runs stay partial. Software consistency is separate from historical fit.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from backend import afsim_world
from gentactix import formation_parts,missions,sim_clock


def review(root):
    result=json.loads((root/'result.json').read_text())
    before=json.loads((root/'initialization.json').read_text())['war_state']
    roster=[(t,u['name']) for t,u in missions.units(before)]
    errors=[];rows=[];checks=Counter();blue_actions=Counter()
    def check(ok,label,turn):
        checks[label]+=1
        if not ok:errors.append({'turn':turn,'check':label})
    for completed in result['turns']:
        turn=completed['turn']
        snap=json.loads((root/f'turn-{turn:02d}-response.json').read_text());after=snap['war_state']
        receipts=json.loads((root/f'turn-{turn:02d}-receipts.json').read_text())
        check(turn==len(rows)+1 and snap['turn_count']==turn,'continuous_turns',turn)
        check(after['current_time']==sim_clock.target(before,snap['time_step'])[0],'clock',turn)
        check(roster==[(t,u['name']) for t,u in missions.units(after)],'roster',turn)
        check(len(receipts)==len(roster) and len({r['unit_id'] for r in receipts})==len(roster),'decisions',turn)
        blue_actions.update(r['action'] for r in receipts if r['team']=='blue')
        native=after['afsim'];job=Path(native['artifact']);scene=json.loads((job/'entities.json').read_text())
        log=Path('vendor/afsim/local/afsim/state/mcp/processes')/(native['process_id']+'.stdout.txt')
        positions=afsim_world.parse_observations(log.read_text(),scene)
        identity={v['name']:k for k,v in scene['entities'].items()}
        old={u['name']:u for _,u in missions.units(before)}
        ledger={r['unit']:r for r in after['mission']['ledger']}
        for _,u in missions.units(after):
            p=u['personnel'];prior=old[u['name']];entry=ledger.get(u['name'])
            check(p['current']+p['casualties']+p['noncombat_losses']==p['committed'],'personnel',turn)
            check(sum(p.get(k,0) for k in ('killed','wounded','missing','captured','unclassified_casualties'))==p['casualties'],'casualty_categories',turn)
            check(all(e['operational']+e['damaged']+e['destroyed']==e['committed'] for e in u['equipment']),'equipment',turn)
            check(missions.distance(u,positions[identity[u['name']]])<.001,'native_position',turn)
            if entry is None:
                # Native DTO deliberately omits resource rows for actors which
                # already had no available personnel before the round.
                check(prior['personnel']['current']==0,'ledger_scope',turn)
                continue
            scale=formation_parts.scale(u)
            for key in ('food','ammo'):
                expected=prior['logistics'][key]+(entry['delivery']-entry[key+'_spent'])/scale
                check(abs(expected-u['logistics'][key])<.0001,key+'_ledger',turn)
        rows.append({'turn':turn,'time':after['current_time'],
            'depots':{n['team']:n['stock'] for n in after['supply_nodes']},
            'zero_food':{team:sum(u['personnel']['current']>0 and u['logistics']['food']==0 for u in after[team+'_units']) for team in ('red','blue')},
            'noncombat':{team:sum(u['personnel']['noncombat_losses'] for u in after[team+'_units']) for team in ('red','blue')},
            'inactive_losses':[{'name':u['name'],'noncombat_delta':u['personnel']['noncombat_losses']-old[u['name']]['personnel']['noncombat_losses']}
                for _,u in missions.units(after) if not after['campaign']['actors'][u['name']]['active']
                and u['personnel']['noncombat_losses']>old[u['name']]['personnel']['noncombat_losses']],
            'native_ms':completed['native_ms'],'engine_ms':completed['engine_ms']})
        before=after
    warnings=[]
    for team in ('red','blue'):
        depleted=next((r['turn'] for r in rows if r['depots'][team]==0),None)
        if depleted is not None:warnings.append({'kind':'depot_exhausted','team':team,'first_turn':depleted})
    inactive=[{'turn':r['turn'],'units':r['inactive_losses']} for r in rows if r['inactive_losses']]
    if inactive:warnings.append({'kind':'noncombat_loss_before_release','events':inactive,
        'interpretation':'Current model consumes resources before release; entry/departure logistics semantics need separate validation.'})
    samples=[r['engine_ms'] for r in rows if isinstance(r['engine_ms'],(int,float))]
    return {'scope':'committed frames only; no historical calibration or model reasoning correctness claim',
        'software_checks_passed':not errors,'errors':errors,'check_counts':dict(checks),
        'reviewed_turns':len(rows),'full_window_reached':len(rows)==57,
        'historical_fit_verified':False,'code_generations':len(list(root.glob('code-*.json'))),
        'blue_decisions':dict(blue_actions),'warnings':warnings,'rows':rows,
        'timing_medians_ms':{'engine':statistics.median(samples) if samples else None,
            'native':statistics.median([r['native_ms'] for r in rows]) if rows else None}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();result=review(args.root)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('software_checks_passed','errors','reviewed_turns','full_window_reached','timing_medians_ms')},ensure_ascii=False))
    if result['errors']:raise SystemExit(1)


if __name__=='__main__':main()
