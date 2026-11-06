"""Advance full22 cases only through actual rendered UI; stop on first real error."""
import argparse
import json
import subprocess
import sys
import time
from . import wanjialing_continuous_live as q

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--limit',type=int,default=12)
args=parser.parse_args()
cases=json.loads((q.ROOT/'cases.json').read_text())
# A controller may be resumed while its owned browser still awaits a valid long
# response. Wait for the original operation; never submit a duplicate round.
while True:
    active=[sid for sid in cases.values() if q.api.call('GET','/sessions/'+sid+'/progress')['active']]
    if not active:break
    print('WAIT_EXISTING_OPERATION',','.join(active),flush=True)
    time.sleep(10)
for turn in range(1,args.limit+1):
    for engine,sid in cases.items():
        snapshot=q.api.call('GET','/sessions/'+sid)
        actual=snapshot['turn_count']
        if actual>=turn:
            if actual==turn and not (q.ROOT/sid/('audit-'+str(turn)+'.json')).exists():q.record(sid)
            continue
        if snapshot['war_state']['mission']['status']=='completed':continue
        if actual!=turn-1:raise ValueError('Unexpected retained turn')
        print('UI START',engine,sid,turn,flush=True)
        path=q.ROOT/(engine+'-driver-'+str(turn)+'.log')
        if path.exists():raise ValueError('Preserve evidence '+str(path))
        with path.open('w') as stream:
            subprocess.run(['node','tools/qa/wanjialing_continuous_browser.mjs',
                '/home/spikebai/.npm/_npx/31e32ef8478fbf80/node_modules/playwright-core/package.json',
                'advance',sid,str(turn)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=3700)
        q.record(sid)
    current={e:q.api.call('GET','/sessions/'+s) for e,s in cases.items()}
    if all(s['war_state']['mission']['status']=='completed' for s in current.values()):
        q.save('continuous-result.json',dict(passed=True,cases={e:dict(session_id=cases[e],turn=s['turn_count'],
            winner=s['war_state']['mission'].get('winner'),world_hash=q.api.digest(s['war_state'])) for e,s in current.items()},
            scope='Full22 bilateral estimated campaign to program outcome through real UI; not full historical process/calibration'))
        print('BOTH PROGRAM OUTCOMES COMPLETED',flush=True)
        sys.exit(0)
raise SystemExit('Retained active campaigns at declared QA limit; not accepted as completed')
