"""Actual sourced first-campaign configuration, decisions and native/DSH execution."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from gentactix import missions
from tools.qa.korean_first_fixture import BATTLE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--port',type=int,default=18998);p.add_argument('--session',required=True)
    p.add_argument('--out',type=Path,default=Path('.cache/qa/korean-first'));args=p.parse_args()
    if not args.live or not 18900<=args.port<=18999:p.error('Use --live with an isolated QA service')
    root=args.out;root.mkdir(parents=True,exist_ok=True);base=f'http://127.0.0.1:{args.port}'
    result={'passed':False,'checks':[],'scope':'Source identities and phase bindings with explicit QA estimates; no historical effectiveness acceptance'}
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,value=None,expected=200):
        request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(request,timeout=1200) as response:status,answer=response.status,json.load(response)
        except urllib.error.HTTPError as exc:status,answer=exc.code,json.loads(exc.read())
        if status!=expected:raise RuntimeError(str(status)+': '+str(answer)[:1800])
        return answer
    def view(sid):
        v=call('GET',f'/api/sessions/{sid}/commands')
        return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def advance(sid,label,orders=None,instruction=''):
        v,rev=view(sid)
        if orders is not None:
            call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,
                'no_fire':False,'unit_agents':[],'intent':instruction});v,rev=view(sid)
        after=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
        save(label+'-turn'+str(after['turn_count']),after)
        for _,u in missions.units(after['war_state']):
            a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
            assert a['casualties']==sum(a.get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        return after
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh backend source')
        sid=args.session;initial=call('GET',f'/api/sessions/{sid}');save('opening-initial',initial)
        check(initial['turn_count']==0 and initial['war_state']['afsim']['entity_count']==2,'sourced draft initializes two actual native actors')
        check(len(initial['war_state']['historical_initial']['definition']['units'])==62,'full source reference graph retained outside model context')
        draft=json.loads((root/'opening-draft.json').read_text());params=draft['parameters']
        for label,edit in (('early',lambda q:q['clock'].update(start='1950-10-25 09:50')),
                           ('region',lambda q:q['area'].update(center={'lat':39.97278,'lng':125.80528},radius_km=40))):
            bad=copy.deepcopy(params);edit(bad)
            rejected=call('POST','/api/historical-scenarios/validate',{'parameters':bad,'parent_draft_id':draft['id'],'execution_backend':'afsim'},expected=422)
            check('计算窗口' in str(rejected) if label=='early' else '阶段地域' in str(rejected),label+' source phase constraint rejects invalid configuration')
        snap=advance(sid,'opening',instruction='先实际读取观察。两个可行动单位都明确下令：354团与韩军加强第3营本轮相互fire，核对真实ID与射程。保持史料身份，结果由AFSIM产生，不强制历史歼灭数量。')
        check(not snap['war_state']['afsim']['model_skipped'] and len(snap['war_state']['afsim']['orders'])==2,'real DSH plans both sides before native fire')
        facts=copy.deepcopy(snap['war_state']);v,rev=view(sid);red=next(u for u in v['units'] if u['team']=='red')
        branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':1,'orders':[{'unit_id':red['id'],'action':'hold','duration':'next'}]});save('opening-counterfactual',branch)
        check(branch['alternative']['blue_units'][0]['personnel']['casualties']==0 and facts['blue_units'][0]['personnel']['casualties']>0,'withholding red fire changes blue losses without historical quota')
        check(call('GET',f'/api/sessions/{sid}')['war_state']==facts,'counterfactual leaves main battle unchanged')
        for _ in range(2):
            v,_=view(sid);teams={u['team']:u['id'] for u in v['units']}
            orders=[{'unit_id':u['id'],'action':'fire','target_id':teams['blue' if u['team']=='red' else 'red'],'duration':'next'} for u in v['units']]
            snap=advance(sid,'opening',orders)
        check(snap['war_state']['current_time'].endswith('11:50') and snap['war_state']['mission']['status']!='active','opening ends before unbound reinforcements')
        reference=next(r['historical_reference'] for r in snap['war_state']['combat_assessment']['units'] if r.get('historical_reference'))
        check(reference['reported_captured']==161 and reference['committed_approx'] is None,'native observation preserves captured-versus-killed source scope')
        v,rev=view(sid);blocked=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex},expected=422)
        check(call('GET',f'/api/sessions/{sid}')['turn_count']==3,'completed window cannot advance or repeat casualties')
        main=copy.deepcopy(snap['war_state'])
        chat=call('POST',f'/api/sessions/{sid}/chat',{'message':'实际调用工具读取本局所有单位。区分本局估计投入人数与史料未核人数，核对当前累计死伤；说明历史毙325、俘161和480余、484异文不可合成战死486，也不属于本局12时前同一窗口。简明回答，不改战局。'});save('opening-analysis',chat)
        check(chat['war_state']==main and chat['engine_meta']['finish_reason']=='completed','real DSH reads current losses and source distinctions without mutation')

        # Same frozen source and numerical inputs; explicitly disable AFSIM.
        independent=call('POST','/api/historical-scenarios/validate',{'parameters':params,'parent_draft_id':draft['id'],'execution_backend':'narrative'})
        solo=call('POST','/api/sessions',{'scenario':'两水洞同源DSH独立QA；数值和部署为估计','battle':BATTLE,'product_mode':'historical','execution_backend':'narrative',
            'historical_parameters':params,'scenario_draft_id':independent['id'],'persist_roles':False})['session_id']
        solo_initial=call('POST',f'/api/sessions/{solo}/init');save('independent-initial',solo_initial)
        check(solo_initial['war_state']['historical_initial']==initial['war_state']['historical_initial'],'AFSIM off uses exactly the same frozen historical facts')
        solo_after=advance(solo,'independent',instruction='双方每个单位明确下令并相互fire，仅推进30分钟。根据相同估计初态、射程与资源估计结果，不以战果配额扣兵，区分新增阵亡负伤并保持全部账目守恒。')
        check('afsim' not in solo_after['war_state'] and solo_after['war_state']['dsh_execution']['effects_source']=='dsh_model_estimate','DSH-only effects do not claim native execution')
        result.update(passed=True,opening_session=sid,independent_session=solo,
            totals={u['name']:{k:u['personnel'][k] for k in ('committed','current','casualties','killed','wounded')} for _,u in missions.units(main)})
        save('opening-result',result)
    except Exception as exc:
        result['error']=str(exc);save('opening-result',result);raise


if __name__=='__main__':main()
