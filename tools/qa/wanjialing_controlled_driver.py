"""Actual full22 physical interventions, fixing all other intended orders."""
import json
import subprocess
from . import wanjialing_continuous_live as q

info=json.loads((q.ROOT/'branches.json').read_text())
cases=info['cases']
for variant,sid in cases.items():
    if not (q.ROOT/sid/'before.json').exists():
        full=q.api.call('GET','/sessions/'+sid+'/export')['session']
        assert full['turn_count']==0
        q.save(sid+'/before.json',full)
        q.save(sid+'/configured.json',dict(session_id=sid,agents=[],variant=variant,
            scope='Actual detached branch, explicit22manual controls; no Native autonomous decisions claimed'))
for turn in range(1,9):
    active={v:s for v,s in cases.items() if q.api.call('GET','/sessions/'+s)['war_state']['mission']['status']!='completed'}
    for variant,sid in active.items():q.branch_orders(sid)
    if len(active)==2:
        orders={v:json.loads((q.ROOT/s/('orders-'+str(turn)+'.json')).read_text())['orders'] for v,s in active.items()}
        changed=[(a,b) for a,b in zip(orders['breakout'],orders['hold']) if a!=b]
        assert len(changed)==1,changed
        assert changed[0][0]['unit_id']==json.loads((q.ROOT/info['source']/'configured.json').read_text())['ids']['ww2.jp.division106']
    for variant,sid in active.items():
        path=q.ROOT/(variant+'-controlled-'+str(turn)+'.log')
        if path.exists():raise ValueError('Preserve evidence '+str(path))
        with path.open('w') as stream:
            subprocess.run(['node','tools/qa/wanjialing_continuous_browser.mjs',
                '/home/spikebai/.npm/_npx/31e32ef8478fbf80/node_modules/playwright-core/package.json',
                'advance',sid,str(turn)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=3700)
        q.record(sid)
    current={v:q.api.call('GET','/sessions/'+s) for v,s in cases.items()}
    if all(s['war_state']['mission']['status']=='completed' for s in current.values()):break
summary={v:dict(session_id=cases[v],turn=s['turn_count'],status=s['war_state']['mission']['status'],
    winner=s['war_state']['mission'].get('winner'),world_hash=q.api.digest(s['war_state'])) for v,s in current.items()}
q.save('controlled-result.json',dict(cases=summary,passed=all(s['status']=='completed' for s in summary.values()),
    comparison='Same22 estimated T0, same other orders over common physical turns; only106breakout/hold differs. Not historical causality or calibrated loss attribution.'))
print(json.dumps(summary),flush=True)
