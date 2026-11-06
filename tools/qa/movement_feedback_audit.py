"""Terminal public22 audit with typed exports and actual movement receipts."""
import argparse
import json
from pathlib import Path
import urllib.request

from gentactix import missions, movement_feedback as mf
from .unit_order_retry_audit import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args();root=args.directory
    if not args.live:parser.error('--live required to read the terminal owned QA API')
    if (root/'audit.json').exists():parser.error('Preserve prior audit')
    terminal=json.loads((root/'result.json').read_text())
    if not terminal.get('passed'):raise ValueError('Real UI round did not pass')
    sid=terminal['session_id'];base='http://127.0.0.1:19227/api/sessions/'+sid
    with urllib.request.urlopen(base+'/progress') as response:progress=json.load(response)
    if progress['active']:raise ValueError('Do not snapshot an in-flight operation')
    before=json.loads((root.parent/(sid+'-before-final-source-restart.json')).read_text())['session']
    with urllib.request.urlopen(base+'/export') as response:after=json.load(response)['session']
    for name,value in [('authoritative-before.json',before),('authoritative-after.json',after)]:
        p=root/name
        if p.exists():raise ValueError('Preserve typed evidence '+str(p))
        p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    result=audit(root,authoritative_before=root/'authoritative-before.json',authoritative_after=root/'authoritative-after.json')
    receipts={r['unit_name']:r for r in after['command_state']['receipts'] if r['turn']==after['turn_count']}
    assert len(receipts)==22
    orders=[]
    for _,unit in missions.units(before['war_state']):
        row=receipts[unit['name']];order=dict(row.get('planned') or {})
        order.update(unit=unit['name'],action=row['action']);orders.append(order)
    checked=mf.validate_transition(before['war_state'],after['war_state'],orders,3600,source='dsh_model_estimate')
    assert checked==after['war_state']['dsh_execution']['movement']
    result.update(movement=checked,actual_orders=orders,motion_scope='Necessary time/ground/fatigue admission; not historical calibration')
    (root/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PASS terminal22 structured proofs, typed sources/accounts/clock and explicit motion admission')


if __name__=='__main__':main()
