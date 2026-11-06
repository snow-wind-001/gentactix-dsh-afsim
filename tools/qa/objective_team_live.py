"""Opt-in goal-owner acceptance on the owned API, with real DSH and AFSIM.

All numerical strengths and positions are explicit software QA assumptions.
This verifies local goal/control contracts, not historical reconstruction.
"""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('Use --live with the owned isolated API18998')
    root=Path('.cache/qa/objective-team');result={'passed':False,'checks':[],
        'historical_fit_verified':False,'numeric_inputs':'explicit QA estimates'}
    def save(name,value):
        (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,data=None,expected=200):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,
            headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as f:status,value=f.status,json.load(f)
        except urllib.error.HTTPError as exc:status,value=exc.code,json.loads(exc.read())
        if status!=expected:raise RuntimeError(str(status)+': '+str(value)[:1800])
        return value
    def revision(sid):
        v=call('GET',f'/api/sessions/{sid}/commands')
        return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def conserved(w):
        for team in ('red','blue'):
            for u in w[team+'_units']:
                p=u['personnel']
                assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
                assert p['casualties']==sum(p.get(k) or 0 for k in
                    ('killed','wounded','missing','captured','unclassified_casualties'))
                for e in u['equipment']:assert e['committed']==sum(e[k] for k in ('operational','damaged','destroyed'))
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        sid=json.loads((root/'session.json').read_text())['session_id'];result['native_session']=sid
        current=call('GET',f'/api/sessions/{sid}');check(current['turn_count']==1,'resume actual UI first move')
        exported=call('GET',f'/api/sessions/{sid}/export')['session']
        turn=next(t for t in exported['trajectory'] if t['turn']==1)
        calls={e.get('name') for run in turn['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
        save('first-turn-tool-calls',sorted(calls))
        check({'get_afsim_observation','retrieve_history'}<=calls,'real planner observes and retrieves historical phase')
        v,rev=revision(sid)
        call('PUT',f'/api/sessions/{sid}/commands',{**rev,'control_team':'red','director':True,
            'no_fire':False,'unit_agents':[],'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units']]})
        _,rev=revision(sid)
        after=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,
            'instruction':'双方明确原地待命，由AFSIM计算蓝方连续控制，不生成交火。'})
        save('native-final',after);w=after['war_state'];conserved(w)
        check(w['mission']['winner']=='blue' and w['mission']['progress']==2,'blue control wins at the second consecutive round')
        check(w['current_time']=='1951-10-05 05:00' and w['afsim']['model_skipped'],'manual batch skips planning and advances exactly 30 minutes')
        check(all(u['personnel']['casualties']==0 for t in ('red','blue') for u in w[t+'_units']),'movement and hold never trigger a casualty quota')
        _,rev=revision(sid)
        rejected=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex},expected=422)
        save('native-finished-rejection',rejected)
        check(call('GET',f'/api/sessions/{sid}')['war_state']==w,'finished local goal rejects extra advancement without mutation')
        home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions')
        offsets={str(p):p.stat().st_size for p in home.glob('*/*/session.v4.jsonl')}
        answer=call('POST',f'/api/sessions/{sid}/chat',{'message':
            '请实际读取原生态势工具，简短说明当前局部目标归哪一方、连续控制进度和胜方。'
            '这是10月5日第一线开放推演，是否能据此声称10月6日主峰巩固或整个战役已经复原？'
            '双方移动与待命无伤亡是否合理？区分模型估计与历史事实，只读。'})
        save('native-analysis',answer)
        check(answer['engine_meta']['finish_reason']=='completed','real DSH completes readonly goal interpretation')
        check(answer['war_state']==w and call('GET',f'/api/sessions/{sid}')['war_state']==w,'analysis preserves the authoritative native world')
        events=[]
        for p in home.glob('*/*/session.v4.jsonl'):
            if p.stat().st_size==offsets.get(str(p),0):continue
            with p.open('rb') as f:
                f.seek(offsets.get(str(p),0))
                for line in f:
                    if not line.endswith(b'\n'):continue
                    event=json.loads(line)
                    if event.get('type')=='tool/call':events.append({'seq':event.get('seq'),**(event.get('data') or {})})
        save('analysis-tool-calls',events)
        check(any(e.get('name')=='get_afsim_observation' for e in events),'native events prove actual AFSIM-state observation')
        draft=json.loads((root/'current-draft.json').read_text())
        narrative=call('POST','/api/historical-scenarios/validate',{'parameters':draft['parameters'],
            'parent_draft_id':draft['id'],'execution_backend':'narrative','operation_id':uuid.uuid4().hex})
        save('narrative-draft',narrative)
        check(narrative['afsim'] is None and narrative['parameters']==draft['parameters'],'DSH-only validates the exact same historical configuration without AFSIM')
        nsid=call('POST','/api/sessions',{'scenario':'马良山同源蓝方目标DSH独立QA，数量部署为估计',
            'battle':draft['initial']['definition']['battle'],'product_mode':'historical','execution_backend':'narrative',
            'use_rag':True,'historical_parameters':narrative['parameters'],'scenario_draft_id':narrative['id'],
            'persist_roles':False})['session_id'];result['narrative_session']=nsid;save('live-session-ids',result)
        initial=call('POST',f'/api/sessions/{nsid}/init');save('narrative-initial',initial)
        check(initial['war_state']['historical_initial']==w['historical_initial'],'same sourced historical identities and facts across both engines')
        check(initial['war_state']['mission']['definition']['objective_team']=='blue','DSH-only initialization retains the explicit blue goal')
        move=('AFSIM已关闭，这是开放推演的明确人为决策，不复现历史命令。双方单位都执行move：'
            '红方571团向北后撤约800米退出目标区；蓝方3RAR到已配置目标中心。'
            '不开火，不编造减员，不补满库存，不超过30分钟机动预算。'
            '用完整JSON提交双方所有单位、命令和决策；目标蓝方连续控制2轮交程序判定。')
        for turn,instruction in ((1,move),(2,'双方全部原地待命，不开火不移动，不编造损失；保留蓝方目标、双方全部单位与连续库存，30分钟后由程序判定。')):
            _,rev=revision(nsid)
            current=call('POST',f'/api/sessions/{nsid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
            save('narrative-turn'+str(turn),current);nw=current['war_state'];conserved(nw)
            check(nw.get('afsim') is None and nw['dsh_execution']['effects_source']=='dsh_model_estimate','turn '+str(turn)+' explicitly identifies DSH estimated effects')
            check(nw['mission']['progress']==turn,'turn '+str(turn)+' program judges blue control from actual candidate positions')
            check(all(u['personnel']['casualties']==0 for t in ('red','blue') for u in nw[t+'_units']),'turn '+str(turn)+' DSH creates no losses without fire')
        check(nw['mission']['winner']=='blue' and nw['current_time']=='1951-10-05 05:00','DSH-only same-owner goal finishes at the same program deadline')
        result['passed']=True
    except Exception as exc:
        result['error']=str(exc);raise
    finally:save('live-results',result)


if __name__=='__main__':main()
