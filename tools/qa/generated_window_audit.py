"""Read-only ledger/goal/SDK audit of an actually generated transfer window."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('engine',choices=['narrative','afsim'])
    parser.add_argument('--allow-active',action='store_true')
    args=parser.parse_args();folder=args.root/args.engine
    info=json.loads((folder/'case.json').read_text())
    def get(suffix):
        with urllib.request.urlopen(info['api']+'/api/sessions/'+info['session_id']+suffix,timeout=60) as response:
            return json.load(response)
    before=json.loads((folder/'initial.json').read_text())
    session=get('/export')['session'];world=session['war_state']
    from backend import checkpoint_codec,session_store
    from gentactix import missions,support_dynamics as sd
    session_store.validate(session)
    assert not get('/progress')['active'],'Observe the existing operation before auditing it'
    if not args.allow_active:
        assert world['mission']['status']=='completed' and world['mission']['winner']=='red'
        assert all(n['status']=='completed' for n in world['campaign_plan']['nodes'].values())
        assert world['campaign_plan']['side_progress']['red']==2
    assert len(world['campaign_plan']['nodes'])==info['goal_count']
    assert not world['campaign_plan']['outcomes']['blue']
    assert world['campaign_plan']['side_progress']['blue']==0
    bindings={i:b['session_id'] for i,b in session['command_state']['agent_sessions'].items()}
    native_turns=[];turns=[]
    for trace in session['trajectory']:
        if trace['turn']==0:continue
        old,new=trace['before'],trace['after'];missions.validate(new)
        assert new['historical_initial']==before['war_state']['historical_initial']
        assert new['simulation_clock']['elapsed_seconds']-old['simulation_clock']['elapsed_seconds']==info['step_seconds']
        assert len(new['red_units'])==info['actor_count'] and not new['blue_units']
        prior={u['historical_unit_id']:u for u in old['red_units']}
        ledger={r['unit']:r for r in new['mission']['ledger']}
        assert len(ledger)==info['actor_count']
        rows=[];cfg=new['mission']['definition']['support_dynamics']
        for u in new['red_units']:
            p=prior[u['historical_unit_id']];r=ledger[u['name']]
            assert u['personnel']['committed']==p['personnel']['committed']
            assert sum(u['personnel'][k] for k in ('current','casualties','noncombat_losses'))==u['personnel']['committed']
            assert u['personnel']['casualties']==0,'Noncontact QA cannot invent combat losses'
            for a,b in zip(u['equipment'],p['equipment']):
                for key in ('category','committed','operational','damaged','destroyed','damage_load'):
                    assert a[key]==b[key]
            quote=sd.expected(cfg,p,r['action'],info['step_seconds'])
            for key in sd.RECEIPT_FIELDS:
                assert math.isclose(u['sustainment']['last_receipt'][key],quote[key],rel_tol=0,abs_tol=1e-6),(u['name'],key)
            for kind in ('food','ammo'):
                assert r[kind+'_received']==0
                assert math.isclose(p['logistics'][kind]-r[kind+'_spent'],u['logistics'][kind],rel_tol=0,abs_tol=1e-6)
            assert r['ammo_spent']==0
            sd.validate_food_loading(cfg,u)
            distance=missions.distance(p,u)
            if r['action']=='hold':assert distance<=1e-5
            else:assert distance<=p['speed']*info['step_seconds']/3600/new['mission']['definition']['geometry']['terrain_factor']+1e-3
            rows.append(dict(identity=u['historical_unit_id'],action=r['action'],moved_km=distance,
                current=u['personnel']['current'],food_kg=sd.food_mass(cfg,u),food_spent=r['food_spent']))
        receipts=[r for r in session['command_state']['receipts'] if r['turn']==trace['turn']]
        assert len(receipts)==len({r['unit_id'] for r in receipts})==info['actor_count']
        for decision in trace['decisions']:
            if decision.get('source')=='native_unit_agent':
                assert decision['proposal']['source']=='dsh_native_unit_order_tool'
                assert decision['proposal']['session_id']==bindings[decision['unit_id']]
                native_turns.append(trace['turn'])
        assert trace['guards']['report']['status']=='screened'
        assert not trace['guards']['movement_violations'] and not trace['guards']['numeric_flags']
        if args.engine=='afsim':
            assert new['afsim']['status']=='completed' and new['afsim']['returncode']==0
            assert new['afsim']['entity_count']==info['actor_count'] and new['afsim']['model_skipped']
        else:
            assert not new.get('afsim')
            assert new['dsh_execution']['effects_source']=='dsh_model_estimate'
        turns.append(dict(turn=trace['turn'],units=rows))
    assert 1 in native_turns and 2 in native_turns,'Actual same unit session must be consumed after cold restore'
    raw=args.root/'api/sessions'/(session['id']+'.json')
    assert checkpoint_codec.decode(json.loads(raw.read_text()))==session_store.serializable(session)
    frozen=json.loads((args.root/'stable-source-freeze.json').read_text())
    assert all(hashlib.sha256(Path(n).read_bytes()).hexdigest()==h for n,h in frozen.items())
    output=folder/('partial-audit.json' if args.allow_active else 'completed-audit.json')
    assert not output.exists(),'Preserve earlier evidence'
    result=dict(passed=True,session_id=session['id'],engine=args.engine,turns=turns,
        same_native_session_consumed_turns=native_turns,whole_checkpoint_exact=True,
        source_files_unchanged=len(frozen),complete_calculation_goals=world['mission']['status']=='completed',
        scope='Actual generated estimated loads and normal orders; no historical strength, equipment or loss calibration. Move/hold responsiveness is not an independent counterfactual experiment.')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PASS',args.engine,session['id'],len(turns),'actual turns; ledger, goals, same SDK bindings and checkpoint')


if __name__=='__main__':main()
