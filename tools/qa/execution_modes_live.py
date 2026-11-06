"""Isolated six-combination integration; --live is required for model usage."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import uuid

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--live',action='store_true');p.add_argument('--port',type=int,default=18982)
p.add_argument('--output',type=Path,default=Path('.cache/qa/historical-launch-fix/live'))
p.add_argument('--resume',action='store_true',help='Reuse completed genuine source-frame artifacts in the same QA directory')
a=p.parse_args()
if not a.live:raise SystemExit('Use --live; this invokes the configured model in an isolated backend.')
assert 18900<=a.port<=18999
a.output.mkdir(parents=True,exist_ok=True);base=f'http://127.0.0.1:{a.port}';checks=[]


def call(method,path,data=None):
    request=urllib.request.Request(base+path,data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None,
        headers={'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(request,timeout=1200) as response:return json.load(response)


def store(name,value):(a.output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def check(ok,label):
    if not ok:raise AssertionError(label)
    checks.append(label);print('PASS',label,flush=True)


def next_turn(identity):
    view=call('GET',f'/api/sessions/{identity}/commands')
    return call('POST',f'/api/sessions/{identity}/next',{'batch_id':uuid.uuid4().hex,
        'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version'],
        'instruction':'本轮双方以观察警戒为主，显式决定各单位行动；禁止凭空补满库存。'})


try:
    health=call('GET','/api/health');check(not health['build']['restart_required'],'fresh source backend')
    seed=call('GET','/api/scenarios/basis/CA-AJ18-v1');battle=seed['basis']['battle']
    for engine in ('narrative','afsim'):
        cached=a.output/('analysis-'+engine+'-turn.json')
        if a.resume and cached.exists():
            second=json.loads(cached.read_text());print('REUSED_GENUINE_SOURCE_FRAME',engine,flush=True)
        else:
            identity=call('POST','/api/sessions',{'scenario':'六组合隔离回溯验收','battle':battle,
                'product_mode':'analysis','simulation_mode':'replay','execution_backend':engine,'persist_roles':False})['session_id']
            first=call('POST',f'/api/sessions/{identity}/init');store('analysis-'+engine+'-init',first)
            second=call('POST',f'/api/sessions/{identity}/next',{'expected_turn':0});store('analysis-'+engine+'-turn',second)
        check(second['turn_count']==1 and second['war_state']['history_replay']['cursor']==1,'analysis/'+engine+' initialized and advanced exact source node')
        check(bool(second['war_state'].get('afsim'))==(engine=='afsim'),'analysis/'+engine+' reports actual engine')
        if engine=='narrative':check(second['engine_meta']['trace_runs']>0 and 'DSH节点分析' in second['history'][0],'real DSH source commentary recorded')
    started=time.monotonic()
    draft=call('POST','/api/scenarios/build',{'mission_id':'CA-AJ18-v1','execution_backend':'afsim','operation_id':uuid.uuid4().hex,
        'instruction':'保留当前史实参考，仅红方一个局部代表编组、蓝方一个代表编组，沿用种子数量、装备和位置。完整保留basis_id，少量单位以便验收。实际调用三个工具，不宣称历史数量已经复原。'})
    store('generated-afsim',draft);print('GENERATION_SECONDS',round(time.monotonic()-started,2),flush=True)
    check(draft['construction']['source']=='dsh_native_skill' and draft['afsim']['returncode']==0,'actual DSH skill and AFSIM load')
    dsh_draft=call('POST','/api/scenarios/validate',{'mission_id':'CA-AJ18-v1','configuration':draft['configuration'],
        'parent_draft_id':draft['id'],'execution_backend':'narrative','operation_id':uuid.uuid4().hex})
    store('validated-dsh',dsh_draft);check(dsh_draft['afsim'] is None,'DSH configuration validates without simulator')
    for purpose,engine in (('historical','narrative'),('historical','afsim'),('synthetic','narrative'),('synthetic','afsim')):
        request={'scenario':battle+'。六组合隔离验收。仅红方第74军第58师局部代表编组、蓝方第116师团局部代表编组各1个，不扩编。双方人员装备数量为教学估计，不强制历史结局。初始化1945-04-09 08:00。',
            'battle':battle,'time_step':'30分钟','product_mode':purpose,'simulation_mode':'open','execution_backend':engine,
            'persist_roles':False,'use_rag':True}
        if purpose in ('synthetic','historical'):
            selected=draft if engine=='afsim' else dsh_draft
            request.update(mission_id='CA-AJ18-v1',scenario_draft_id=selected['id'],synthetic_configuration=selected['configuration'])
        identity=call('POST','/api/sessions',request)['session_id']
        first=call('POST',f'/api/sessions/{identity}/init');store(purpose+'-'+engine+'-init',first)
        second=next_turn(identity);store(purpose+'-'+engine+'-turn',second)
        check(second['turn_count']==1,purpose+'/'+engine+' initialized and advanced')
        check(second['settings']['product_mode']==purpose and second['settings']['execution_backend']==engine,purpose+'/'+engine+' purpose/engine persisted')
        check(bool(second['war_state'].get('afsim'))==(engine=='afsim'),purpose+'/'+engine+' no false external receipt')
        check(len(second['war_state']['red_units'])==len(first['war_state']['red_units']) and len(second['war_state']['blue_units'])==len(first['war_state']['blue_units']),purpose+'/'+engine+' roster preserved')
        if purpose=='synthetic' and engine=='narrative':
            check(second['war_state']['dsh_execution']['effects_source']=='dsh_model_estimate','synthetic DSH supplies process effects')
            before_hash=hashlib.sha256(json.dumps(second['war_state'],sort_keys=True).encode()).hexdigest()
            view=call('GET',f'/api/sessions/{identity}/commands');unit=view['units'][0]
            comparison=call('POST',f'/api/sessions/{identity}/commands/compare',{'expected_turn':view['turn'],
                'revision':view['revision'],'world_version':view['world_version'],'turn':1,
                'orders':[{'unit_id':unit['id'],'action':'hold','duration':'next'}]})
            store('dsh-command-comparison',comparison)
            current=call('GET',f'/api/sessions/{identity}')
            check(comparison['source']=='dsh_native_runtime' and comparison['effects_source']=='dsh_model_estimate','DSH read-only command comparison uses same engine')
            check(before_hash==hashlib.sha256(json.dumps(current['war_state'],sort_keys=True).encode()).hexdigest(),'DSH comparison preserves main world')
    store('results',{'passed':True,'checks':checks,'six_combinations':True,'genuine_model_calls':True});print('ALL_PASSED',len(checks),flush=True)
except Exception as exc:
    store('results',{'passed':False,'checks':checks,'error':str(exc)});raise
