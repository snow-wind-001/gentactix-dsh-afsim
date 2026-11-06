"""Compare terminal22 public frames with matched orders, without equal-outcome claims."""
import argparse
import json
import urllib.request

from gentactix import missions, movement_feedback as mf
from .movement_feedback_live import ROOT


def receipt_orders(session):
    receipts={r['unit_name']:r for r in session['command_state']['receipts'] if r['turn']==session['turn_count']}
    assert len(receipts)==22
    return {name:{k:v for k,v in (row.get('planned') or dict(unit=name,action='hold')).items()
                  if k not in ('intent_id','cancel_crossing')} for name,row in receipts.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required to read owned terminal QA API')
    out=ROOT/'matched-frame-comparison.json'
    if out.exists():raise ValueError('Preserve comparison')
    accepted=json.loads((ROOT/'afsim-t1/result.json').read_text());assert accepted['passed']
    before=json.loads((ROOT/'afsim-matched-before.json').read_text())
    sid=accepted['session_id']
    with urllib.request.urlopen('http://127.0.0.1:19227/api/sessions/'+sid+'/export') as r:after=json.load(r)['session']
    (ROOT/'afsim-t1/authoritative-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'afsim-t1/authoritative-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
    original=json.loads((ROOT/'dsh-t1-review/authoritative-before.json').read_text())
    dsh=json.loads((ROOT/'dsh-t1-review/authoritative-after.json').read_text())
    orders=receipt_orders(after);other=receipt_orders(dsh)
    assert orders==other,'Actual normalized physical orders differ'
    assert before['war_state']['mission']['definition']==original['war_state']['mission']['definition']
    assert after['turn_count']==dsh['turn_count']==1
    assert after['war_state']['simulation_clock']['elapsed_seconds']==dsh['war_state']['simulation_clock']['elapsed_seconds']==3600
    w=after['war_state'];receipt=w['combined_arms']['movement_feedback']
    native={r['unit']:r for r in receipt['units']}
    checked=mf.validate_transition(before['war_state'],w,list(orders.values()),3600,source='afsim_native_estimate',native=native)
    assert checked==receipt
    old={u['historical_unit_id']:u for _,u in missions.units(before['war_state'])}
    af={u['historical_unit_id']:u for _,u in missions.units(w)}
    model={u['historical_unit_id']:u for _,u in missions.units(dsh['war_state'])}
    rows=[]
    for identity,u in af.items():
        prior=old[identity];v=model[identity];p=u['personnel']
        assert p['committed']==prior['personnel']['committed']==p['current']+p['casualties']+p['noncombat_losses']
        for e,e0 in zip(u['equipment'],prior['equipment']):
            assert e['committed']==e0['committed']==e['operational']+e['damaged']+e['destroyed']
        rows.append(dict(unit=u['name'],action=orders[u['name']]['action'],
            position_difference_m=missions.distance(u,v)*1000,
            afsim_fatigue=u['formation']['fatigue'],dsh_fatigue=v['formation']['fatigue'],
            afsim_casualties=p['casualties'],dsh_casualties=v['personnel']['casualties'],
            afsim_food=u['logistics']['food'],dsh_food=v['logistics']['food'],
            afsim_ammo=u['logistics']['ammo'],dsh_ammo=v['logistics']['ammo']))
    result=dict(passed=True,actors=22,actual_afsim=True,actual_dsh=True,source_version='1.4.0',window_version='1.5.0',
        same_normalized_orders=True,clock_seconds=3600,rows=rows,
        scope='One matched frame of necessary motion/fatigue/resource constraints; actual effects may differ, not full-window or historical efficacy acceptance')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PASS matched22 actual orders/clock, native movement receipts and continuous accounts')
    print('Max position delta(m)',max(r['position_difference_m'] for r in rows),'fatigue differences',
        sum(r['afsim_fatigue']!=r['dsh_fatigue'] for r in rows))


if __name__=='__main__':main()
