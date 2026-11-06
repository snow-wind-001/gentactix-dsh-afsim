"""Real DSH/AFSIM local WWII phases with sourced IDs and explicit QA estimates."""
import argparse
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--port',type=int,default=18998)
    p.add_argument('--case',choices=['taierzhuang','wanjialing'],required=True)
    p.add_argument('--session',help='Use the existing owned QA session created in the frontend')
    p.add_argument('--resume',action='store_true',help='Continue an owned session after a QA driver failure')
    a=p.parse_args()
    if not a.live or not 18900<=a.port<=18999:p.error('Use --live with an isolated QA service')
    from gentactix import missions, sim_clock
    root=Path('.cache/qa/ww2-phases');label=a.case
    result={'passed':False,'checks':[],'historical_fit_verified':False}
    def save(name,v):(root/(label+'-'+name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    def check(v,s):
        if not v:raise AssertionError(s)
        result['checks'].append(s);print('PASS',s,flush=True)
    def call(method,path,value=None,expected=200):
        req=urllib.request.Request(f'http://127.0.0.1:{a.port}'+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as f:status,answer=f.status,json.load(f)
        except urllib.error.HTTPError as exc:status,answer=exc.code,json.loads(exc.read())
        if status!=expected:raise RuntimeError(str(status)+': '+str(answer)[:1500])
        return answer
    def view(sid):
        v=call('GET',f'/api/sessions/{sid}/commands');return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def advance(sid,instruction=''):
        _,rev=view(sid);return call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
    started=time.monotonic()
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        if a.session:
            sid=a.session;initial=(json.loads((root/(label+'-initial.json')).read_text()) if a.resume else call('GET',f'/api/sessions/{sid}'))
        else:
            draft=json.loads((root/(label+'-draft.json')).read_text());params=draft['parameters']
            check(draft['construction']['source']=='dsh_native_skill' and draft['validation']['scope']=='native_load','actual DSH skill configuration loaded in AFSIM')
            sid=call('POST','/api/sessions',{'scenario':label+'具名单位局部QA；人数、装备配额、部署和效能为显式估计，不是全战役历史复原。',
                'battle':draft['initial']['definition']['battle'],'product_mode':'historical','execution_backend':'afsim',
                'historical_parameters':params,'scenario_draft_id':draft['id'],'use_rag':True,'persist_roles':False})['session_id']
            initial=call('POST',f'/api/sessions/{sid}/init')
        result['session_id']=sid;save('initial',initial)
        check(initial['turn_count']==0,'begin from an unmodified initialized QA state')
        w=initial['war_state'];facts=copy.deepcopy(w['historical_initial'])
        expected={'ww2.cn.division31','ww2.jp.seya_detachment'} if label=='taierzhuang' else {'ww2.cn.army4','ww2.cn.army66','ww2.cn.army74','ww2.jp.division106'}
        check({u['historical_unit_id'] for t in ('red','blue') for u in w[t+'_units']}==expected,'native actors match the sourced phase without relief or headquarters entities')
        check(w['afsim']['entity_count']==len(expected),'actual native actor count')
        if label=='wanjialing':
            center=w['mission']['definition']['map_center']
            check(missions.distance(center,{'lat':29.365246,'lng':115.581335})<1,'model locality uses Moxi rather than the county memorial')
        answer=(json.loads((root/(label+'-turn1.json')).read_text()) if a.resume else advance(sid,'先实际调用get_afsim_observation读取本局，再调用retrieve_history检索本战役的建模约束而非强制历史结局。所有红方单位各自fire唯一蓝方；蓝方fire当前第一个红方单位。双方所有可行动单位明确目标和公开理由。结果由AFSIM产生，不改写人员或套历史伤亡配额。不移动。'))
        save('turn1',answer)
        check(not answer['war_state']['afsim']['model_skipped'] and len(answer['war_state']['afsim']['orders'])==len(expected),'real DSH supplies all bilateral orders before native effects')
        saved=call('GET',f'/api/sessions/{sid}/export')['session']
        record=next(r for r in saved['trajectory'] if r.get('turn')==1)
        calls={e.get('name') for run in record['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
        check({'get_afsim_observation','retrieve_history'}<=calls and saved['use_rag'],'native planning actually observes and retrieves enabled source constraints')
        main=copy.deepcopy(answer['war_state']);current=call('GET',f'/api/sessions/{sid}');completed=current['turn_count']
        before_compare=copy.deepcopy(current['war_state']);v,rev=view(sid)
        branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':1,'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']})
        save('counterfactual',branch)
        check(branch['alternative']['blue_units'][0]['personnel']['casualties']==0 and main['blue_units'][0]['personnel']['casualties']>0,'withholding red fire changes blue losses')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==before_compare,'native counterfactual does not change the main battle')
        ledger=[]
        for turn in range(1,9):
            if turn>1 and turn<=completed:
                answer=json.loads((root/(label+'-turn'+str(turn)+'.json')).read_text())
            elif turn>1:
                v,rev=view(sid);red=next(u for u in v['units'] if u['team']=='red');blue=next(u for u in v['units'] if u['team']=='blue')
                orders=[{'unit_id':u['id'],'action':'fire','target_id':blue['id'] if u['team']=='red' else red['id'],'duration':'next'}
                        if 'fire' in u['capabilities']['actions'] else {'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units']]
                call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
                answer=advance(sid);save('turn'+str(turn),answer)
            w=answer['war_state'];missions.validate(w)
            for _,u in missions.units(w):
                r=u['personnel'];check(r['committed']==r['current']+r['casualties']+r['noncombat_losses'],str(turn)+' '+u['name']+' personnel conservation')
                check(r['casualties']==sum(r.get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties')),str(turn)+' '+u['name']+' classified losses conserve')
                check(all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']),str(turn)+' '+u['name']+' equipment conservation')
            check(w['historical_initial']==facts,str(turn)+' source snapshot unchanged')
            ledger.append({'turn':turn,'clock':w['current_time'],'units':[{'name':u['name'],'personnel':u['personnel'],'logistics':u['logistics'],'last_execution':u['formation']['last_execution']} for _,u in missions.units(w)]})
        save('ledger',ledger)
        stop=datetime.fromisoformat(initial['war_state']['current_time'])+timedelta(seconds=8*sim_clock.duration_seconds(initial['time_step']))
        check(datetime.fromisoformat(w['current_time'])==stop,'eight rounds advance exactly the configured clock')
        check(w['mission']['status']!='active','programmatic local objective stops at its deadline')
        before=copy.deepcopy(w)
        analysis=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际读取get_afsim_observation和get_afsim_changes完整分页，再用retrieve_history核对本战役约束。简短表列每单位累计阵亡、负伤和减员；区分四小时历时、有效火力时长和弹药耗尽后待命。历史歼敌/伤亡/被俘不通约，局部QA数值和部署不是史实实到量；不套全战役减员配额，不改战局。'})
        save('analysis',analysis)
        check(analysis['war_state']==before and analysis['engine_meta']['finish_reason']=='completed','real DSH reads current effects without changing authoritative state')
        _,rev=view(sid);call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex},expected=422)
        check(call('GET',f'/api/sessions/{sid}')['war_state']==before,'completed goal cannot advance or repeat losses')
        result.update(passed=True,seconds=round(time.monotonic()-started,2),totals={u['name']:u['personnel'] for _,u in missions.units(w)})
    except Exception as exc:
        result['error']=str(exc);raise
    finally:save('result',result)


if __name__=='__main__':main()
