"""Read actual before/after frames and audit passive seconds; never repair state."""
import argparse
import json
import math
from pathlib import Path


def review(root):
    from gentactix import combat_effects, missions
    from gentactix.fire_process import GROUND_FIRE
    rows=[];violations=[]
    for path in sorted(root.glob('*/turn-*.json')):
        frame=json.loads(path.read_text());before=frame['before']['war_state'];after=frame['after']['war_state']
        elapsed=after['simulation_clock']['elapsed_seconds']-before['simulation_clock']['elapsed_seconds']
        if not elapsed>0:raise ValueError('Expected an actual positive-duration frame: '+str(path))
        actions={r['unit']:r['action'] for r in after['mission']['last_orders']}
        index={u['name']:u for _,u in missions.units(after)};ref=combat_effects.reference(before)
        count=0;bad=[]
        for _,old in missions.units(before):
            name=old['name'];action=actions.get(name)
            if action is None:raise ValueError('Missing executed action: '+name)
            if action in GROUND_FIRE:continue
            prior=old['formation'].get('reload_remaining_s',old['formation']['reload_remaining']*ref['artillery_cycle_s'])
            current=index[name]['formation'].get('reload_remaining_s',index[name]['formation']['reload_remaining']*ref['artillery_cycle_s'])
            expected=max(0,prior-elapsed);count+=1
            if not math.isclose(current,expected,rel_tol=0,abs_tol=1e-6):
                item=dict(frame=str(path.relative_to(root)),backend=path.parent.name,turn=frame['after']['turn_count'],unit=name,
                    action=action,elapsed_seconds=elapsed,before_reload_s=prior,after_reload_s=current,expected_reload_s=expected)
                bad.append(item);violations.append(item)
        rows.append(dict(frame=str(path.relative_to(root)),backend=path.parent.name,turn=frame['after']['turn_count'],
            passive_units_checked=count,violation_count=len(bad)))
    if not rows:raise ValueError('No actual before/after frames found')
    return dict(passed=not violations,scope='Passive cooldown seconds only; not combat outcome or historical calibration',
        state_repaired=False,model_calls=0,frames=len(rows),checks=rows,violations=violations)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('Preserve existing evidence; choose another output')
    result=review(a.run);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'],frames=result['frames'],violations=len(result['violations']),state_repaired=False)))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
