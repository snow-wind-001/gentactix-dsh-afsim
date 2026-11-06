"""Real DSH aggregate selection over an existing committed AFSIM battle."""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--session',default='ab9e42f20993');args=p.parse_args()
    if not args.live:p.error('Use --live only against the owned isolated QA service')
    from backend import afsim_state
    root=Path('.cache/qa/change-summary');root.mkdir(parents=True,exist_ok=True)
    checks=[];out={'passed':False,'checks':checks,'historical_fit_verified':False}
    def save(n,v):(root/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def check(v,s):
        if not v:raise AssertionError(s)
        checks.append(s);print('PASS',s,flush=True)
    def call(method,path,data=None):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source and native protocol')
        sid=args.session;out['session_id']=sid
        document=call('GET',f'/api/sessions/{sid}/export')['session'];before=copy.deepcopy(document['war_state'])
        check(before['afsim']['source']=='dsh_native_mcp_controller','source world contains committed native execution evidence')
        def pages(query):
            result=[]
            while True:
                response=afsim_state.changes(document,query);result.append(response)
                if response['next_args'] is None:return result
                query=response['next_args']
        detail=pages({'since_turn':0,'limit':16});aggregate=pages({'mode':'aggregate','since_turn':0,'limit':16})
        rows=[r for page in aggregate for r in page['units']]
        check(sum(len(p['changes']) for p in detail)==sum(r['change_count'] for r in rows),'aggregate covers every committed unit change')
        original={}
        for r in document['trajectory']:
            if r['turn']<=0:continue
            for c in r.get('changes',[]):
                receipt=((c.get('fields',{}).get('formation',{}).get('after') or {}).get('last_execution') or {})
                if receipt.get('turn')!=r['turn']:continue
                target=original.setdefault((c['team'],c['name']),{'fire_cycles':0,'artillery_shells_fired':0,'received_shells':0})
                target['fire_cycles']+=receipt.get('fire_cycles',0)
                target['received_shells']+=receipt.get('received_shells',0)
                if receipt.get('action') in ('bombard','suppress'):target['artillery_shells_fired']+=receipt['shots']
        for row in rows:
            for field,value in original[(row['team'],row['name'])].items():
                check(row['execution']['totals'][field]['known_sum']==value,row['name']+' exact '+field+' total')
        size=lambda ps:sum(len(json.dumps(p,ensure_ascii=False,separators=(',',':'))) for p in ps)
        check(size(aggregate)<size(detail)*.4,'same ledger window aggregate payload is less than forty percent of detail pages')
        out['payload']={'detail_chars':size(detail),'aggregate_chars':size(aggregate),'detail_pages':len(detail),'aggregate_pages':len(aggregate)}
        save('aggregate',aggregate)
        started=time.time()
        answer=call('POST',f'/api/sessions/{sid}/chat',{'message':'请核对本局从开始到当前的四个单位：人数变化与死伤分类，火炮/装甲待修与毁损，间瞄炮弹实际发射和到货、自身有效火力时长及周期。用简短表格，指出净库存和弹数、累计历时与有效火力时长的区别，以及哪些数字只是教学估计。只读，不改局。'})
        text=answer['chat_messages'][-1]['content']
        save('natural-answer',{'answer':text,'engine_meta':answer['engine_meta']})
        check(answer['engine_meta']['finish_reason']=='completed','natural question completes through the real DSH model')
        check(answer['war_state']==before and call('GET',f'/api/sessions/{sid}')['war_state']==before,'analysis leaves the main authoritative world unchanged')
        home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions');calls=[]
        for path in home.glob('*/*/session.v4.jsonl'):
            if path.stat().st_mtime<started:continue
            for line in path.open():
                if not line.endswith('\n'):continue
                row=json.loads(line)
                if row.get('type')!='tool/call':continue
                data=row.get('data') or {};parameters=data.get('arguments') or {}
                if isinstance(parameters,str):parameters=json.loads(parameters)
                calls.append({'session_id':path.parent.name,'seq':row.get('seq'),'name':data.get('name'),'arguments':parameters})
        save('native-tool-calls',calls)
        summaries=[c for c in calls if c['name']=='get_afsim_changes' and c['arguments'].get('mode')=='aggregate']
        check(any(c['arguments'].get('since_turn')==0 for c in summaries),'native event proves DSH selected the full-window aggregate without an explicit tool instruction in the question')
        out.update(passed=True,engine_meta=answer['engine_meta'])
    except Exception as exc:out['error']=str(exc);raise
    finally:save('result',out)


if __name__=='__main__':main()
