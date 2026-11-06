"""Advance the actual DSH QA game after cold restore and beyond its reference horizon."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import uuid


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for the actual configured DSH')
    root=Path('.cache/qa/campaign-plan-2026-10-31/dsh-step');sid=json.loads((root/'result.json').read_text())['session_id']
    def call(method,path,data=None):
        req=urllib.request.Request('http://127.0.0.1:19108/api/sessions/'+sid+path,method=method,
            headers={'Content-Type':'application/json'},data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req,timeout=900) as r:return json.load(r)
        except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+' '+exc.read().decode()) from exc
    result={'passed':False,'session_id':sid,'cold_restored':True,'turns':[]}
    try:
        current=call('GET','')
        while current['turn_count']<3:
            view=call('GET','/commands');call('PUT','/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
                control_team='red',director=True,no_fire=False,intent='延续冷恢复的同一战局，全部待命；只估计本轮资源变化。目标未满足，不按参考轮数结束。',
                orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]))
            view=call('GET','/commands');current=call('POST','/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],batch_id=uuid.uuid4().hex))
            (root/f'after-{current["turn_count"]}.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
            assert current['war_state']['mission']['status']=='active'
            assert current['war_state']['campaign_plan']['turn']==current['turn_count']
            assert current['war_state']['simulation_clock']['elapsed_seconds']==current['turn_count']*1800
            result['turns'].append(current['turn_count']);print('Committed actual DSH goal round',current['turn_count'],flush=True)
        assert current['turn_count']==3 and current['war_state']['mission']['definition']['deadline_turn']==2
        result.update(passed=True,reference_exceeded=True,final_status='active')
        print('PASS actual DSH: cold continuation and third round beyond two-round reference, no premature settlement',flush=True)
    finally:(root/'resume-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
