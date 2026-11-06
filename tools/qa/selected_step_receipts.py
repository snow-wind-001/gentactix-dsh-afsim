"""Re-read the existing real session after bounded receipt projection changes."""
import argparse
import json
from pathlib import Path
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Use --live against the owned 18998 service')
    from backend import afsim_state
    root=Path('.cache/qa/selected-step');sid='3fbde648595e';base='http://127.0.0.1:18998'
    def call(method,path,value=None):
        req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
    assert not call('GET','/api/health')['build']['restart_required']
    saved=call('GET',f'/api/sessions/{sid}/export')['session']
    query={'since_turn':0,'limit':16};pages=[];receipts={};counts={}
    while query is not None:
        page=afsim_state.changes(saved,query);pages.append(page);query=page['next_args']
        for item in page['changes']:
            change=item['change'];r=change.get('execution_receipt') or change.get('fields',{}).get('formation',{}).get('after',{}).get('last_execution')
            assert r and r['turn']==item['turn']
            receipts.setdefault(change['name'],[]).append(r)
            if item['turn']==1:counts[change['name']]=change['numeric_deltas']
    totals={name:{'fire_cycles':sum(r['fire_cycles'] for r in rows),'active_fire_s':sum(r['active_fire_s'] for r in rows),
                  'delivery_complete':all(all(k in r for k in ('received_shells','received_aa_rounds','received_fuel_liters','received_spares','received_materials')) for r in rows)} for name,rows in receipts.items()}
    assert len(pages)==2 and all(len(r)==16 for r in receipts.values())
    assert all(r['fire_cycles']==100 and r['delivery_complete'] for r in totals.values())
    assert counts['第31师']['personnel.killed']=={'before':None,'after':11}
    assert counts['日军濑谷支队']['personnel.killed']=={'before':None,'after':41}
    (root/'receipt-projection.json').write_text(json.dumps({'pages':pages,'totals':totals},ensure_ascii=False,indent=2))
    before=call('GET',f'/api/sessions/{sid}')['war_state']
    answer=call('POST',f'/api/sessions/{sid}/chat',{'message':'请重新实际读取get_afsim_observation，再用get_afsim_changes(since_turn=0,limit=16)沿next_args读完全部32条。每轮压缩记录新增execution_receipt，请逐轮累计双方fire_cycles和active_fire_s，检查received_*是否每轮明确为0；首轮阵亡与负伤已知after端点请查numeric_deltas，不因before为空丢弃after。用不超过600字给出双方累计减员、死伤、火力周期、累计有效火力时长和到货。分别说明总历时240分钟、单轮/步长15分钟。上次“先验本身偏低”的断言没有同窗口标定或单因素对照，需更正为未验证假设，不能按历史近3000强制扣兵。无需重复整个历史资料表，不改战局。'})
    (root/'receipt-analysis.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2))
    assert answer['war_state']==before and answer['engine_meta']['finish_reason']=='completed'
    (root/'receipt-result.json').write_text(json.dumps({'passed':True,'rows':32,'pages':2,'totals':totals,'readonly':True,'historical_fit_verified':False},ensure_ascii=False,indent=2))
    print('PASS all32 committed execution receipts, known first-turn after counts and native readonly analysis',flush=True)


if __name__=='__main__':main()
