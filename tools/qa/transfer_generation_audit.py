"""Read-only review and owned cold-restart evidence for real transfer generation."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import urllib.request

ROOT=Path('.cache/qa/transfer-generation-2026-11-03')
API='http://127.0.0.1:19338'


def wire(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def get(path):
    with urllib.request.urlopen(API+path,timeout=90) as response:return json.load(response)


def save(path,value):
    if path.exists():raise ValueError('Preserve earlier evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def capture():
    result={}
    for name,manifest in [('half_hour',ROOT/'live-case.json'),('six_hour',ROOT/'longstep/live-case.json')]:
        info=json.loads(manifest.read_text());sid=info['session_id'];base='/api/sessions/'+sid
        progress=get(base+'/progress');assert not progress['active']
        session=get(base+'/export')['session'];path=ROOT/'api/sessions'/(sid+'.json')
        result[name]=dict(session=session,progress=progress,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          mtime_ns=path.stat().st_mtime_ns,step_seconds=info['step_seconds'])
    return result


def review(captured):
    from backend import session_store,checkpoint_codec
    from gentactix import campaign_windows,missions
    from unittest.mock import patch
    rows=[]
    for name,value in captured.items():
        session=value['session'];sid=session['id'];turns=[]
        with patch.object(campaign_windows,'load',side_effect=AssertionError('Frozen recovery may not read registry')):
            session_store.validate(session)
        stored=checkpoint_codec.decode(json.loads((ROOT/'api/sessions'/(sid+'.json')).read_text()))
        assert wire(stored)==wire(session_store.serializable(session))
        bindings={i:b['session_id'] for i,b in session['command_state']['agent_sessions'].items()}
        traces=[t for t in session['trajectory'] if t['turn']>0]
        for trace in traces:
            before,after=trace['before'],trace['after'];turn=trace['turn']
            missions.validate(after)
            assert after['historical_initial']==before['historical_initial']
            assert after['blue_units']==before['blue_units']==[] and len(after['red_units'])==4
            assert after['simulation_clock']['elapsed_seconds']-before['simulation_clock']['elapsed_seconds']==value['step_seconds']
            assert after['dsh_execution']['source']=='dsh_native_runtime'
            assert after['dsh_execution']['effects_source']=='dsh_model_estimate' and 'afsim' not in after
            prior={u['historical_unit_id']:u for u in before['red_units']}
            assert set(prior)=={u['historical_unit_id'] for u in after['red_units']}
            ledger={r['unit']:r for r in after['mission']['ledger']}
            assert len(ledger)==4
            units=[]
            for unit in after['red_units']:
                old=prior[unit['historical_unit_id']];receipt=ledger[unit['name']]
                # First model receipt adds the existing explicit provenance
                # default. Compare every other field, without rewriting worlds.
                def physical(row):
                    return {**row,'carried_forward':row.get('carried_forward',False)}
                assert physical(unit['personnel'])==physical(old['personnel'])
                assert [physical(e) for e in unit['equipment']]==[physical(e) for e in old['equipment']]
                for kind in ('food','ammo'):
                    expected=old['logistics'][kind]+receipt[kind+'_received']-receipt[kind+'_spent']
                    assert math.isclose(expected,unit['logistics'][kind],rel_tol=0,abs_tol=1e-9)
                    assert receipt[kind+'_received']==0
                assert receipt['ammo_spent']==0
                units.append(dict(identity=unit['historical_unit_id'],action=receipt['action'],
                    food_spent=receipt['food_spent'],food_after=unit['logistics']['food'],
                    fatigue=unit['formation']['fatigue'],position=[unit['lat'],unit['lng']]))
            receipts=[r for r in session['command_state']['receipts'] if r['turn']==turn]
            assert len(receipts)==len({r['unit_id'] for r in receipts})==4
            native=[d for d in trace['decisions'] if d.get('source')=='native_unit_agent']
            for decision in native:
                assert decision['proposal']['source']=='dsh_native_unit_order_tool'
                assert decision['proposal']['session_id']==bindings[decision['unit_id']]
            assert trace['guards']['report']['status']=='screened'
            assert not trace['guards']['movement_violations'] and not trace['guards']['numeric_flags']
            assert not after['campaign_plan']['outcomes']['blue'] and after['campaign_plan']['side_progress']['blue']==0
            turns.append(dict(turn=turn,elapsed_seconds=after['simulation_clock']['elapsed_seconds'],
                native_decisions=len(native),units=units,mission_status=after['mission']['status']))
        assert traces[-1]['after']==session['war_state']
        rows.append(dict(name=name,session_id=sid,turns=turns,native_bindings=len(bindings),
                         whole_checkpoint_exact=True,history_calibrated=False))
    frozen=json.loads((ROOT/'final-source-freeze.json').read_text())
    changed=[p for p,digest in frozen.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest]
    assert not changed,changed
    from tools.afsim.launch import layout
    jobs=layout(Path.cwd())['workspace']/'jobs'
    before=set(json.loads((ROOT/'afsim-jobs-before-process.json').read_text()))
    after={p.name for p in jobs.iterdir() if p.is_dir()}
    assert before==after
    return dict(passed=True,sessions=rows,source_files_unchanged=len(frozen),
        afsim_jobs_exactly_unchanged=len(after),whole_frozen_sessions_valid=True,
        scope='Actual generated estimates, two independently initialized step variants; not seven-day historical calibration.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['audit','snapshot','verify'])
    parser.add_argument('--output',help='Explicit new evidence filename; never replace previous results')
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required for owned read-only API19338')
    current=capture()
    if args.mode=='snapshot':
        save(ROOT/'cold-before.json',current);print('PASS two complete owned sessions captured before restart');return
    result=review(current)
    if args.mode=='verify':
        before=json.loads((ROOT/'cold-before.json').read_text())
        assert wire(current)==wire(before)
        result['cold_complete_session_progress_bindings_file_bytes_mtime_exact']=True
    filename=args.output or ('cold-review.json' if args.mode=='verify' else 'process-checkpoint-audit.json')
    if Path(filename).name!=filename:raise ValueError('Evidence filename must stay inside the owned root')
    save(ROOT/filename,result)
    print('PASS',args.mode,[(row['name'],len(row['turns'])) for row in result['sessions']],
          'frozen source',result['source_files_unchanged'],'unchanged AFSIM jobs',result['afsim_jobs_exactly_unchanged'])


if __name__=='__main__':main()
