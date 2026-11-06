"""Isolated actual-turn and Native read-only conversion-preview evidence.

Explicit QA estimates derived through the normal historical-to-synthetic path.
This does not admit new units or claim a completed physical split.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid

from tools.qa import force_task_execution_live as api

ROOT=Path('.cache/qa/formation-conversion-2026-11-02')
api.ROOT=ROOT
api.PORT=19142
call=api.call


def save(path,value):
    target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def serve():
    folder=(ROOT/'api').resolve();folder.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    draft_file=ROOT/'base-drafts.json'
    if not draft_file.exists():
        from backend import scenario_builder
        from tools.qa.campaign_plan_fixture import inputs,NOTE
        from verify_support_dynamics import config
        source,parameters=inputs()
        parameters['support_dynamics']={**config(),'food_work_per_hour':.2}
        for actor in parameters['actors'].values():actor['personnel']=10000
        for support in parameters['support'].values():support['stock']=0
        result={}
        for engine in ('afsim','narrative'):
            draft=scenario_builder.stage_historical(source,parameters,
                construction={'source':'dsh_native_skill','explanation':NOTE+' 固定QA输入，非本次模型生成'},
                execution_backend=engine)
            result[engine]=dict(id=draft['id'],battle=source['definition']['battle'])
        save('base-drafts.json',result)
    api.serve()


def revisions(base):
    v=call('GET',base+'/commands')
    return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'])


def proposal_body(base,unit_id,committed):
    return dict(**revisions(base),kind='split',unit_ids=[unit_id],
        allocations=[dict(id='left',label='左翼计算分队',committed=committed//2),
                     dict(id='right',label='右翼计算分队',committed=committed-committed//2)],
        assumption='软件当前实态分配QA；人数装备为显式估计，不是历史编制，尚不执行分兵',limit=1)


def unit(snapshot):
    return next(u for u in snapshot['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')


def run(engine):
    case_path=ROOT/engine/'case.json'
    if case_path.exists():raise ValueError('Case exists; preserve it rather than repeating a committed turn')
    source=json.loads((ROOT/'base-drafts.json').read_text())[engine]
    draft=call('POST','/scenarios/from-historical',dict(base_draft_id=source['id'],execution_backend=engine))['draft']
    created=call('POST','/sessions',dict(scenario='有损实态分配提案QA，不是历史验收',battle=source['battle'],
        product_mode='synthetic',scenario_draft_id=draft['id'],synthetic_configuration=draft['configuration'],
        execution_backend=engine,simulation_mode='open',time_step='30分钟',agent_mode='native',persist_roles=True))
    base='/sessions/'+created['session_id'];initial=call('POST',base+'/init')
    v=call('GET',base+'/commands');selected=next(r for r in v['units'] if r['name']==unit(initial)['name'])
    blue=next(r for r in v['units'] if r['team']=='blue')
    case=dict(engine=engine,session_id=created['session_id'],unit_id=selected['id'],blue_id=blue['id'],initial=initial)
    save(engine+'/case.json',case)
    call('PUT',base+'/commands',dict(**revisions(base),control_team='red',director=True,no_fire=False,
        intent='QA双方均有明确命令；蓝方射击红方159师，检验实际有损状态，非历史命令。',
        orders=[dict(unit_id=r['id'],action='fire',target_id=selected['id'],duration='next') if r['id']==blue['id']
                else dict(unit_id=r['id'],action='hold',duration='until_turn',end_turn=100) for r in v['units']]))
    started=time.monotonic()
    after=call('POST',base+'/next',{**revisions(base),'batch_id':uuid.uuid4().hex})
    save(engine+'/after-turn.json',after)
    assert after['turn_count']==1 and after['war_state']['simulation_clock']['elapsed_seconds']==1800
    assert unit(after)['personnel']['casualties']>0
    if engine=='afsim':assert after['afsim']['returncode']==0 and after['afsim']['model_skipped']
    else:assert after['war_state']['dsh_execution']['effects_source']=='dsh_model_estimate'
    check_preview(case,after,started)


def check_preview(case,after,started):
    engine=case['engine'];base='/sessions/'+case['session_id']
    before=call('GET',base);commands=call('GET',base+'/commands');org=call('GET',base+'/force-organization')
    assert before['war_state']==after['war_state'] and before['history']==after['history']
    body=proposal_body(base,case['unit_id'],unit(after)['personnel']['committed'])
    first=call('POST',base+'/force-organization/conversion-preview',body)
    second=call('POST',base+'/force-organization/conversion-preview',
        {**revisions(base),**first['next_args']})
    save(engine+'/preview.json',dict(first=first,second=second))
    assert first['totals_before']==first['totals_after']==second['totals_before']==second['totals_after']
    rows=first['rows']+second['rows'];assert len(rows)==2 and second['next_args'] is None
    assert sum(r['personnel']['current'] for r in rows)==unit(after)['personnel']['current']
    assert sum(r['personnel']['casualties'] for r in rows)==unit(after)['personnel']['casualties']
    assert all(not p['runtime_admitted'] and p['readonly'] for p in (first,second))
    latest=call('GET',base)
    assert latest['war_state']==before['war_state'] and latest['history']==before['history']
    assert call('GET',base+'/commands')==commands and call('GET',base+'/force-organization')==org
    registered={u.get('calculation_unit_id') or u.get('exercise_unit_id') or u.get('historical_unit_id')
                for team in ('red','blue') for u in latest['war_state'][team+'_units']}
    assert all(r['proposed_calculation_id'] not in registered for r in rows)
    save(engine+'/result.json',dict(passed=True,engine=engine,session_id=case['session_id'],turn=1,
        elapsed_seconds=round(time.monotonic()-started,2),losses=unit(after)['personnel']['casualties'],
        preview_only=True,runtime_admitted=False,world_history_commands_organization_unchanged=True,
        totals=first['totals_before'],scope='Actual damaged QA synthetic world; read-only allocation, NOT physical split or historical calibration'))
    print('PASS',engine,'actual turn plus unchanged-world preview',unit(after)['personnel']['casualties'],'losses',flush=True)


def resume_preview(engine):
    case=json.loads((ROOT/engine/'case.json').read_text())
    after=json.loads((ROOT/engine/'after-turn.json').read_text())
    assert after['turn_count']==1
    print('Explicit preview-only resume from committed T1; no model or physics turn repeated',flush=True)
    check_preview(case,after,time.monotonic())


def chat(engine,attempt):
    if not attempt.isalnum():raise ValueError('Attempt label must be alphanumeric')
    prefix=engine+'/chat-'+attempt
    if (ROOT/(prefix+'-response.json')).exists():raise ValueError('Preserve previous actual chat evidence')
    case=json.loads((ROOT/engine/'case.json').read_text());base='/sessions/'+case['session_id']
    before=call('GET',base);current=unit(before);n=current['personnel']['committed'];v=call('GET',base+'/commands')
    args={k:value for k,value in proposal_body(base,case['unit_id'],n).items()
          if k not in ('expected_turn','revision','world_version')}
    marker='CONVERSION-READONLY-'+case['session_id']+'-'+attempt
    question=(marker+'。只读核对当前第159师，不下令、不修改战局。请先实际调用get_afsim_observation读取当前单位，'
        '然后真实调用preview_force_conversion，参数为'+json.dumps(args,ensure_ascii=False)+'。'
        '沿next_args读完两项预览。判断总投入、现有、累计战斗减员、各装备账与库存是否守恒；'
        '不能把建议ID说成已登记执行单位。最后只用一个JSON对象回答：turn,personnel_committed,personnel_current,'
        'casualties,preview_rows,totals_equal,runtime_admitted,executed,world_unit_count。executed表示是否实际分兵。')
    started=time.monotonic();response=call('POST',base+'/chat',{'message':question});save(prefix+'-response.json',response)
    latest=call('GET',base)
    assert latest['war_state']==before['war_state'] and latest['history']==before['history']
    assert call('GET',base+'/commands')==v
    expected=dict(turn=1,personnel_committed=n,personnel_current=current['personnel']['current'],
        casualties=current['personnel']['casualties'],preview_rows=2,totals_equal=True,
        runtime_admitted=False,executed=False,world_unit_count=sum(len(before['war_state'][t+'_units']) for t in ('red','blue')))
    content=response['chat_messages'][-1]['content'];found=[]
    for i,c in enumerate(content):
        if c!='{':continue
        try:value,_=json.JSONDecoder().raw_decode(content[i:])
        except ValueError:continue
        if isinstance(value,dict) and expected.keys()<=value.keys():found.append(value)
    assert len(found)==1,'Expected one complete factual answer'
    assert all(found[0][k]==value for k,value in expected.items()),(found[0],expected)
    save(prefix+'-review.json',dict(passed=True,marker=marker,expected=expected,answer=found[0],
        unchanged=True,elapsed_seconds=round(time.monotonic()-started,2),native_call_review_pending=True))
    print('PASS',engine,'production Native chat numerical and no-execution claims',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['serve','afsim','narrative','chat','resume-preview']);parser.add_argument('--live',action='store_true')
    parser.add_argument('--engine',choices=['afsim','narrative'],default='afsim')
    parser.add_argument('--attempt',default='first');args=parser.parse_args()
    if args.mode=='serve':serve()
    elif not args.live:parser.error('Actual configured engine/model calls require --live')
    elif args.mode=='chat':chat(args.engine,args.attempt)
    elif args.mode=='resume-preview':resume_preview(args.engine)
    else:run(args.mode)
