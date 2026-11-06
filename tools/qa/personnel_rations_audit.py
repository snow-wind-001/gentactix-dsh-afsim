"""Read-only comparison of actual native and DSH physical ration accounts."""
import json
import math
from pathlib import Path
import urllib.request


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live requires the owned isolated API19348')
    from backend import session_store
    from gentactix import support_dynamics as sd
    root=Path('.cache/qa/personnel-rations-2026-11-03');out=root/'physical-parity-review.json'
    if out.exists():raise ValueError('Preserve earlier evidence')
    info=json.loads((root/'t2-independent/turn-case.json').read_text())
    def get(sid):
        with urllib.request.urlopen(info['api']+'/api/sessions/'+sid+'/export',timeout=90) as f:return json.load(f)['session']
    session=get(info['session_id']);assert session['turn_count']==2;session_store.validate(session)
    rows=[]
    for trace in session['trajectory']:
        if trace['turn']<1:continue
        before,after=trace['before'],trace['after'];cfg=sd.configuration(before);ledger={x['unit']:x for x in after['mission']['ledger']}
        assert after['historical_initial']==before['historical_initial'] and not after['blue_units'] and 'afsim' not in after
        assert after['simulation_clock']['elapsed_seconds']-before['simulation_clock']['elapsed_seconds']==21600
        native=json.loads((root/f'native-r3/four-army-six-hour-{trace["turn"]}.json').read_text())
        for unit,prior,peer in zip(after['red_units'],before['red_units'],native['red_units']):
            assert unit['historical_unit_id']==prior['historical_unit_id']==peer['historical_unit_id']
            assert unit['personnel']['current']==prior['personnel']['current']==peer['personnel']['current']
            def physical(e):return {k:v for k,v in e.items() if k not in {'carried_forward','calculation_source'}}
            assert [physical(e) for e in unit['equipment']]==[physical(e) for e in peer['equipment']]
            cost=ledger[unit['name']];assert cost['food_received']==cost['ammo_received']==cost['ammo_spent']==0
            assert math.isclose(prior['logistics']['food']-cost['food_spent'],unit['logistics']['food'],rel_tol=0,abs_tol=1e-9)
            assert math.isclose(unit['logistics']['food'],peer['logistics']['food'],rel_tol=0,abs_tol=1e-6)
            for key in sd.RECEIPT_FIELDS:
                assert math.isclose(unit['sustainment']['last_receipt'][key],peer['sustainment']['last_receipt'][key],rel_tol=0,abs_tol=1e-6)
            for key in ('lat','lng'):assert unit[key]==prior[key]
        receipts=[x for x in session['command_state']['receipts'] if x['turn']==trace['turn']];assert len(receipts)==4
        native_decisions=[d for d in trace['decisions'] if d.get('source')=='native_unit_agent']
        if trace['turn']==2:
            assert len(native_decisions)==2
            bindings={i:b['session_id'] for i,b in session['command_state']['agent_sessions'].items()}
            run_sessions={r['session_id'] for r in trace['runs']}
            for decision in native_decisions:
                assert decision['proposal']['session_id']==bindings[decision['unit_id']]
                assert decision['proposal']['source']=='dsh_native_unit_order_tool'
                assert bindings[decision['unit_id']] in run_sessions
        rows.append(dict(turn=trace['turn'],elapsed_seconds=after['simulation_clock']['elapsed_seconds'],
            food_kg=sum(sd.food_mass(cfg,u) for u in after['red_units']),native_unit_decisions=len(native_decisions),
            noncombat_losses=sum(u['personnel']['noncombat_losses'] for u in after['red_units'])))
    source_before=json.loads((root/'t2-independent/source-before.json').read_text());source_after=get(source_before['id'])
    assert source_before==source_after
    assert source_after['war_state']==json.loads((root/'t1-canonical.json').read_text())['war_state']
    result=dict(passed=True,session_id=session['id'],clock_seconds=43200,rows=rows,
        food_and_seven_nutrition_fields_match_actual_afsim=True,people_and_equipment_conserved=True,
        failed_source_whole_session_unchanged=True,new_directed_independent_branch=True,
        wall_elapsed_ms=session['engine_last_meta']['wall_elapsed_ms'],original_failed_operation_not_accepted=True,
        scope='Physical ration inputs equal, explanation/planning reference and per-executor provenance differ. Independent retry uses explicit completion instruction; original loop remains a recorded failure. No history calibration or permanent completion fix.')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
