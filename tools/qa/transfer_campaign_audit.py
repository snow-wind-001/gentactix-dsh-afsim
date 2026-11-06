"""Independent continuity/accounting review of accepted public API checkpoints."""
import copy
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',default='accepted-source-freeze.json')
    parser.add_argument('--output',default='public-checkpoint-audit.json')
    args=parser.parse_args()
    from backend import checkpoint_codec, session_store, afsim_state
    from gentactix import campaign_windows as cw
    root=Path('.cache/qa/transfer-window-2026-11-03');base=root/'live-final'
    if (root/args.output).exists():raise SystemExit('Preserve earlier audit evidence')
    # Use canonical Python HTTP JSON / checkpoint numbers. Browser evidence
    # JSON.stringify normalizes e.g. 3.0 to 3 and cannot prove frozen hashes.
    session=json.loads((base/'authoritative-final.json').read_text())
    initial=json.loads((base/'initial.json').read_text())['war_state']
    current=copy.deepcopy(initial);rows=[];source=initial['historical_initial']
    native_sessions={i:b['session_id'] for i,b in json.loads((base/'cold-before.json').read_text())['command_state']['agent_sessions'].items()}
    with patch.object(cw,'load',side_effect=AssertionError('Frozen recovery must not read current window registry')):
        session_store.validate(session)
    from gentactix import missions
    for trace in (t for t in session['trajectory'] if t['turn']>0):
        world=trace['after'];turn=trace['turn'];previous={u['name']:u for u in current['red_units']}
        with patch.object(cw,'load',side_effect=AssertionError('Frozen world validation must not read current window registry')):
            missions.validate(world)
        assert world['historical_initial']==source and len(world['red_units'])==4 and world['blue_units']==[]
        assert {u['historical_unit_id'] for u in world['red_units']}=={u['historical_unit_id'] for u in initial['red_units']}
        assert world['simulation_clock']['elapsed_seconds']==turn*1800
        assert set(u['name'] for u in world['red_units'])==set(previous)
        ledger={r['unit']:r for r in world['mission']['ledger']};assert set(ledger)==set(previous)
        spent=0
        for unit in world['red_units']:
            old=previous[unit['name']];receipt=ledger[unit['name']]
            # Native execution adds provenance and casualty classification;
            # physical conservation concerns the known numerical accounts.
            for field in ('committed','current','casualties','noncombat_losses','source'):
                assert unit['personnel'][field]==old['personnel'][field]
            assert sum(unit['personnel'][k] for k in ('killed','wounded','missing','captured','unclassified_casualties'))==0
            for item,prior in zip(unit['equipment'],old['equipment']):
                for field in ('category','committed','operational','damaged','destroyed','damage_load','source'):
                    assert item[field]==prior[field]
            assert old['logistics']['food']+receipt['food_received']-receipt['food_spent']==unit['logistics']['food']==receipt['food_after']
            assert old['logistics']['ammo']+receipt['ammo_received']-receipt['ammo_spent']==unit['logistics']['ammo']==receipt['ammo_after']
            assert receipt['food_received']==receipt['ammo_received']==receipt['ammo_spent']==0
            spent+=receipt['food_spent']
        receipts=[r for r in session['command_state']['receipts'] if r['turn']==turn]
        assert len(receipts)==len({r['unit_id'] for r in receipts})==4
        bindings={i:b['session_id'] for i,b in session['command_state']['agent_sessions'].items()}
        assert bindings==native_sessions and len(bindings)==2
        evidence=world['afsim'];assert evidence['status']=='completed' and evidence['returncode']==0 and evidence['entity_count']==4
        for decision in trace['decisions']:
            if decision.get('source')=='native_unit_agent':
                assert decision['proposal']['session_id']==native_sessions[decision['unit_id']]
        assert trace['guards']['report']['status']=='screened'
        assert not trace['guards']['movement_violations'] and not trace['guards']['numeric_flags']
        plan=world['campaign_plan'];assert not plan['outcomes']['blue'] and plan['side_progress']['blue']==0
        rows.append(dict(turn=turn,elapsed_seconds=world['simulation_clock']['elapsed_seconds'],
            food_spent=spent,food_after=sum(u['logistics']['food'] for u in world['red_units']),
            status=world['mission']['status'],winner=world['mission']['winner'],
            native_decisions=sum(d.get('source')=='native_unit_agent' for d in trace['decisions'])))
        current=world
    assert current['mission']['status']=='completed' and current['mission']['winner']=='red'
    assert current['campaign_plan']['side_progress']['red']==2
    details=afsim_state.observation(session,{'detail':True,'limit':16})['units'];assert len(details)==4
    stored=base/'api/sessions'/(session['id']+'.json')
    restored=checkpoint_codec.decode(json.loads(stored.read_text()))
    assert restored==session_store.serializable(session)
    frozen=json.loads((root/args.freeze).read_text())
    changed=[p for p,digest in frozen.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest]
    assert not changed,changed
    result=dict(passed=True,checkpoints=rows,whole_final_checkpoint_exact=True,source_files_unchanged=len(frozen),
        four_army_ids_and_two_sdk_sessions_continuous=True,resource_equations_exact=True,all_four_final_details=True,
        scope='Four-army, 12000-person explicit QA loads. Zero classified equipment is not a nonzero-equipment test. No historical daily strengths, routes or loss calibration claimed.')
    (root/args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
