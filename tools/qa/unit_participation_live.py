"""Isolated normal HTTP/native participation QA; all numeric inputs are estimates.

The server uses the saved model configuration read-only. No user games, role
index or DSH workspace are loaded. --run requires an explicit --live flag.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid
from tools.qa import force_task_execution_live as workflow

ROOT=Path('.cache/qa/unit-participation-2026-11-01/integration/live')
PORT=19120
workflow.PORT=PORT
call=workflow.call


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def serve():
    folder=(ROOT/'http').resolve();folder.mkdir(parents=True,exist_ok=True)
    for name,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                        ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+name]=str(folder/suffix)
    from backend import main,harness_engine
    import uvicorn
    try:uvicorn.run(main.app,host='127.0.0.1',port=PORT,log_level='warning')
    finally:harness_engine.close_harness()


def revision(base):
    v=call('GET',base+'/commands')
    return {k:v[k] for k in ('revision','world_version')}|{'expected_turn':v['turn']}


def draft(order):
    from gentactix.commands import DRAFT_FIELDS
    return {k:copy.deepcopy(v) for k,v in order.items() if k in DRAFT_FIELDS}


def queue(base,orders):
    return call('PUT',base+'/commands',{**revision(base),'control_team':'red','director':True,
        'no_fire':False,'intent':'软件QA显式参与控制，物理数值未历史标定','orders':orders})


def move(case,kind,point):
    base='/sessions/'+case['session_id'];view=call('GET',base+'/commands')
    rows=[draft(o) for o in view['orders'] if o['unit_id']!=case['unit_id']]
    rows.append(dict(unit_id=case['unit_id'],action='move',duration='until_arrived',destination=point,participation=kind))
    return queue(base,rows)


def create(engine,*,tag=None,combat=True,gear=False):
    from tools.qa.campaign_plan_fixture import inputs,NOTE
    tag=tag or engine;folder=ROOT/tag;path=folder/'case.json'
    if path.exists():raise ValueError('Preserve existing case; choose a new tag')
    source,p=inputs()
    if gear:
        p['actors']['ww2.cn.division159']['equipment'].update(transport=20,artillery=4)
        p['assumptions']+='；本装备正例另设第159师20件运输装备、4门炮，仅验证分类损伤连续，不是历史实有量。'
    created=call('POST','/sessions',dict(scenario='单位参与状态验收 '+tag+'；'+NOTE,
        battle=source['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
        execution_backend=engine,agent_mode='native',persist_roles=True,
        historical_parameters=p,historical_initial_version='1.2.0'))
    sid=created['session_id'];base='/sessions/'+sid;initial=call('POST',base+'/init')
    view=call('GET',base+'/commands');red=next(u for u in view['units'] if u['name']=='第159师')
    blue=next(u for u in view['units'] if u['team']=='blue')
    orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=100) for u in view['units']]
    if combat:
        for a,b in ((red,blue),(blue,red)):
            row=next(o for o in orders if o['unit_id']==a['id']);row.update(action='fire',target_id=b['id'],duration='next');row.pop('end_turn')
    queue(base,orders)
    case=dict(session_id=sid,unit_id=red['id'],blue_id=blue['id'],engine=engine,tag=tag,
        origin=red['position'],rear=dict(lat=red['position']['lat']+.001,lng=red['position']['lng']),initial=initial,combat=combat,gear=gear)
    save(path,case);print('Created',tag,sid,flush=True);return case


def advance(case,label):
    base='/sessions/'+case['session_id'];began=time.monotonic()
    snap=call('POST',base+'/next',{**revision(base),'batch_id':uuid.uuid4().hex})
    save(ROOT/case['tag']/('turn-'+str(snap['turn_count'])+'.json'),snap)
    if case['engine']=='afsim':
        assert snap['war_state']['afsim']['returncode']==0
        assert snap['war_state']['afsim']['model_skipped'],'All active units are explicitly controlled'
    view=call('GET',base+'/commands');row=next(u for u in view['units'] if u['id']==case['unit_id'])
    print('PASS',case['engine'],label,'turn',snap['turn_count'],'status',row['capabilities']['participation']['status'],
        'seconds',round(time.monotonic()-began,3),flush=True)
    return snap


def member(snap,case):
    return next(u for u in snap['war_state']['red_units'] if u['name']=='第159师')


def task(case):
    from verify_force_task_execution import execution
    base='/sessions/'+case['session_id'];v=call('GET',base+'/force-organization')
    rev=lambda x:dict(expected_turn=x['turn'],revision=x['command_revision'],world_version=x['world_version'],organization_revision=x['revision'])
    v=call('POST',base+'/force-organization/detach',{**rev(v),'unit_ids':[case['unit_id']],
        'label':'参与状态原任务群','assumption':'软件QA临时任务，非历史改隶'})
    group=v['groups'][-1]['id'];data={**rev(v),'group_id':group,'task':{'kind':'defend'},'replace_existing':True,
        'execution':execution('退出期间保留原任务',start=v['turn']+1,finish=dict(kind='turn',end_turn=100,minimum_executions=20))}
    preview=call('POST',base+'/force-organization/task-preview',data)
    call('POST',base+'/force-organization/tasks',{**data,'preview_hash':preview['preview_hash']})
    return call('GET',base+'/force-organization/tasks')['rows'][-1]['id']


def run(engine,tag=None,gear=False):
    case=create(engine,tag=tag,gear=gear);base='/sessions/'+case['session_id'];result={'passed':False,'engine':engine,'session_id':case['session_id']}
    try:
        combat=advance(case,'actual combat');damaged=copy.deepcopy(member(combat,case))
        assert damaged['personnel']['casualties']>0,'This live case must include actual damage before withdrawal'
        if gear:assert any(e['damaged']+e['destroyed']>0 for e in damaged['equipment']),'Equipment case requires an actual classified loss'
        view=call('GET',base+'/commands')
        queue(base,[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=100) for u in view['units']])
        task_id=task(case);first=advance(case,'original task')
        move(case,'withdraw',case['rear']);rear=advance(case,'withdraw arrival')
        for _ in range(3):rear=advance(case,'rear waiting')
        current=member(rear,case);registry=rear['war_state']['unit_participation']
        row=next(r for r in registry['actors'].values() if r['name']==current['name'])
        assert row['status']=='reserve'
        assert current['personnel']==member(first,case)['personnel']
        assert current['equipment']==member(first,case)['equipment']
        assert current['logistics']['food']<member(first,case)['logistics']['food']
        members=call('GET',base+'/force-organization/tasks?kind=members&task_id='+task_id)['rows']
        assert next(m for m in members if m['unit_id']==case['unit_id'])['status']=='blocked'
        move(case,'reenter',case['origin']);back=advance(case,'reentry');final=advance(case,'original task resumes')
        final_member=member(final,case)
        assert final_member['personnel']==damaged['personnel']
        assert final_member['equipment']==damaged['equipment']
        final_row=next(r for r in final['war_state']['unit_participation']['actors'].values() if r['name']==final_member['name'])
        assert final_row['status']=='deployed'
        members=call('GET',base+'/force-organization/tasks?kind=members&task_id='+task_id)['rows']
        assert next(m for m in members if m['unit_id']==case['unit_id'])['executions']==2
        assert set(registry['actors'])==set(final['war_state']['unit_participation']['actors'])
        result.update(passed=True,turn=final['turn_count'],task_id=task_id,actual_afsim=engine=='afsim',actual_model=engine!='afsim',
            damage_before_withdrawal=damaged['personnel'],final_personnel=final_member['personnel'],
            damaged_equipment=damaged['equipment'],final_equipment=final_member['equipment'],positive_equipment=gear,
            rear_food=current['logistics']['food'],final_food=final_member['logistics']['food'],scope='Actual command/participation/account/task chain, not full historical campaign or off-map process')
    except Exception as exc:
        result['error']=str(exc);raise
    finally:save(ROOT/case['tag']/'result.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serve',action='store_true')
    parser.add_argument('--run',choices=['afsim','narrative']);parser.add_argument('--create',choices=['afsim','narrative'])
    parser.add_argument('--tag');parser.add_argument('--live',action='store_true');parser.add_argument('--gear',action='store_true');args=parser.parse_args()
    if args.serve:serve()
    elif not args.live:parser.error('--live required for engine/model execution')
    elif args.run:run(args.run,args.tag,args.gear)
    elif args.create:create(args.create,tag=args.tag,combat=False,gear=args.gear)
