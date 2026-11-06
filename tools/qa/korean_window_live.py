"""Real DSH whole-session observation after the exclusive-turn query clarification."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--verify-errors',action='store_true',help='Verify a readable rejected query and a successful full observation')
    args=p.parse_args()
    if not args.live:p.error('Use --live against the owned isolated API18998')
    root=Path('.cache/qa/korean-series');result={'passed':False,'checks':[]}
    prefix='bridge-recovery-' if args.verify_errors else ''
    def save(label,value):(root/(prefix+label+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    def check(value,label):
        if not value:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,data=None):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source and protocol')
        sid=json.loads((root/'KW05-fifth-initial.json').read_text())['session_id']
        original=call('GET',f'/api/sessions/{sid}/export')['session'];before=copy.deepcopy(original['war_state'])
        from backend import afsim_state
        summary=afsim_state.changes(original,{'mode':'aggregate','limit':16})
        save('full-window-ledger',summary)
        mortar=next(r for r in summary['units'] if r['name']=='英第170独立迫击炮连C分队')
        check(summary['window']['full_session'] and summary['window']['includes_first_turn'],'default aggregate includes all eight turns')
        check(mortar['execution']['totals']['artillery_shells_fired']['known_sum']==240,'complete native mortar ledger is 240 shells')
        home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions')
        offsets={str(path):path.stat().st_size for path in home.glob('*/*/session.v4.jsonl')}
        question=('只读软件验收，不下令不修改战局：先实际调用get_afsim_changes(mode="changes",offset=16)，故意不提供view_version，'
            '以验证非法翻页能否返回明确错误。收到拒绝后，实际使用完整aggregate从开局到当前恢复读取，'
            '简短说明具体错误与恢复方式、迫击炮累计发射量；不伪称第一步成功。' if args.verify_errors else
            '请重新核对本局自开局到现在所有单位的累计减员、炮弹实际发射和自身有效火力周期。用一个简短表格，列清统计涵盖的回合；区分全部历时和局部统计窗口，以及炮弹耗尽后待命。保留史料损失与模型估计的区别。只读。')
        answer=call('POST',f'/api/sessions/{sid}/chat',{'message':question})
        save('full-window-analysis',answer)
        check(answer['engine_meta']['finish_reason']=='completed','real DSH completes the natural cumulative question')
        check(answer['war_state']==before and call('GET',f'/api/sessions/{sid}')['war_state']==before,'analysis does not change the committed world')
        calls=[];errors=[]
        for path in home.glob('*/*/session.v4.jsonl'):
            offset=offsets.get(str(path),0)
            if path.stat().st_size==offset:continue
            with path.open('rb') as f:
                if path.stat().st_size>=offset:f.seek(offset)
                for line in f:
                    if not line.endswith(b'\n'):continue
                    row=json.loads(line)
                    if row.get('type')=='tool/result':
                        message=(row.get('data') or {}).get('message') or {}
                        if message.get('isError'):
                            errors.extend(block.get('text','')[:400] for block in message.get('content',[]) if block.get('type')=='text')
                    if row.get('type')!='tool/call':continue
                    data=row.get('data') or {};parameters=data.get('arguments') or {}
                    if isinstance(parameters,str):parameters=json.loads(parameters)
                    calls.append({'session_id':path.parent.name,'seq':row.get('seq'),'name':data.get('name'),'arguments':parameters})
        save('full-window-tool-calls',calls)
        save('native-errors',errors)
        aggregates=[r for r in calls if r['name']=='get_afsim_changes' and r['arguments'].get('mode')=='aggregate']
        check(any(r['arguments'].get('since_turn',0)==0 and r['arguments'].get('through_turn',8)==8 for r in aggregates),
            'native events prove selection of the complete aggregate without an explicit tool parameter in the question')
        if args.verify_errors:
            check(any('view_version' in error for error in errors) and not any('fetch failed' in error for error in errors),
                'real native tool rejection exposes the Chinese version error rather than a broken transport')
            invalid=[c for c in calls if c['name']=='get_afsim_changes' and c['arguments'].get('offset',0)>0 and 'view_version' not in c['arguments']]
            result['ordered_error_recovery_verified']=any(a['session_id']==b['session_id'] and a['seq']<b['seq']
                for a in invalid for b in aggregates)
            result['scope']='Error reporting and successful observation; call order is separately recorded, never inferred from model prose.'
        result.update(passed=True,engine_meta=answer['engine_meta'])
    except Exception as exc:result['error']=str(exc);raise
    finally:save('full-window-result',result)


if __name__=='__main__':main()
