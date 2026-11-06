"""Save/verify exact isolated backend worlds and test HTTP goal paging."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import urllib.parse

ROOT=Path('.cache/qa/campaign-plan-2026-10-31')


def get(path):
    with urllib.request.urlopen('http://127.0.0.1:19108/api'+path,timeout=10) as response:return json.load(response)


def digest(world):
    return hashlib.sha256(json.dumps(world,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    if not args.verify:
        records=[]
        for case,path in [('native-red','native/result.json'),('native-blue','native-blue/result.json'),
                          ('dsh','dsh-step/result.json'),('ui','browser-result.json')]:
            sid=json.loads((ROOT/path).read_text())['session_id'];snapshot=get('/sessions/'+sid)
            records.append(dict(case=case,session_id=sid,turn=snapshot['turn_count'],world_hash=digest(snapshot['war_state'])))
        (ROOT/'checkpoint-before.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));print('Saved',len(records),'QA world digests')
    else:
        for _ in range(50):
            try:get('/health');break
            except OSError:time.sleep(.2)
        else:raise SystemExit('Isolated API not ready')
        records=json.loads((ROOT/'checkpoint-before.json').read_text())
        for row in records:
            snapshot=get('/sessions/'+row['session_id'])
            assert digest(snapshot['war_state'])==row['world_hash'] and snapshot['turn_count']==row['turn']
        base='/sessions/'+records[0]['session_id']+'/campaign-objectives';page=get(base+'?limit=1');seen=[]
        assert page['view_version']!=page['plan_hash'] and page['readonly']
        while True:
            seen += [r['id'] for r in page['nodes']]
            if page['next_args'] is None:break
            page=get(base+'?'+urllib.parse.urlencode(page['next_args']))
        assert len(seen)==len(set(seen))==4
        for query in ['offset=1&limit=1','offset=1&limit=1&view_version='+'0'*64]:
            try:get(base+'?'+query)
            except urllib.error.HTTPError as exc:assert exc.code==422
            else:raise AssertionError('Missing/stale goal view token accepted')
        (ROOT/'all-backend-cold.json').write_text(json.dumps(dict(passed=True,cases=records,http_goal_paging=True,
            missing_and_stale_token_rejected=True),ensure_ascii=False,indent=2));print('PASS four exact cold-restored worlds and real HTTP versioned goal pages')
