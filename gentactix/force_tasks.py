"""Read-only task decomposition and explicit queue commits; no battle effects.

Uses existing unit actions, resources and movement validation. A task is an
intent with one primary action per leaf, not an autonomous campaign executor.
"""
import copy
import uuid
from . import commands,force_organization as forces,missions

VERSION='force-task-plan-1'
ROLES=('maneuver','fire_support','engineer','reserve','sustain')
KINDS=('uniform','advance','assault','defend','withdraw','sustain')
DRAFT_FIELDS=commands.DRAFT_FIELDS


def _task(session,group_id,task):
    commands.assert_writable(session)
    if not isinstance(task,dict) or set(task)-{'kind','destination','target_id','roles','end_turn','order','participation'}:
        raise ValueError('兵团任务字段非法')
    if task.get('kind') not in KINDS:raise ValueError('兵团任务类型非法')
    if task['kind']=='uniform':
        if set(task)!={'kind','order'} or not isinstance(task['order'],dict):raise ValueError('统一行动须提供order')
        if set(task['order'])-(set(DRAFT_FIELDS)-{'id','unit_id'}):
            raise ValueError('统一行动含非法命令字段')
    elif 'order' in task:raise ValueError('分工任务不能混入统一order')
    if 'participation' in task:
        expected={'advance':'reenter','withdraw':'withdraw'}.get(task['kind'])
        if expected is None or task['participation']!=expected:raise ValueError('退出参与仅用于withdraw，重新投入仅用于advance')
    ids=forces.effective_member_ids(session,group_id)
    if not ids:raise ValueError('此节点没有当前指挥下级，已配属单位须通过临时指挥链下令')
    cs=commands.state(session);units=commands.resolve_units(session,cs)
    if any(units[i][0].get('ambiguous') or (not cs['director'] and units[i][0]['team']!=cs['control_team']) for i in ids):
        raise ValueError('没有全部下级的指挥权限')
    roles=task.get('roles',{})
    if not isinstance(roles,dict) or set(roles)-set(ids) or any(v not in ROLES for v in roles.values()):
        raise ValueError('任务分工须引用当前下级和已支持角色')
    if task['kind'] in ('advance','assault','withdraw') and 'destination' not in task:
        raise ValueError('此任务需要在地图选择机动目标')
    if 'destination' in task:commands.position(task['destination'])
    spec=session['war_state'].get('mission',{}).get('definition')
    if spec and 'destination' in task and missions.distance(task['destination'],spec['map_center'])>spec['map_radius_km']:
        raise ValueError('任务地域超出本局计算范围')
    if task['kind']=='assault' and not task.get('target_id'):raise ValueError('进攻任务须明确选择敌方目标')
    if task.get('target_id'):
        enemy=units.get(task['target_id'])
        if (not enemy or enemy[0].get('ambiguous') or not commands.available(enemy[1])
                or enemy[0]['team']==units[ids[0]][0]['team']):raise ValueError('任务目标不存在、已失能或属于己方')
        from . import campaign
        if campaign.release_seconds(session['war_state'],enemy[1])>0:raise ValueError('任务目标尚未入场，不能提前攻击')
    if 'end_turn' in task:commands.validate_duration(dict(action='hold',duration='until_turn',end_turn=task['end_turn']),session['turn_count'])
    return ids,cs,units


def _role(unit,explicit):
    if explicit:return explicit,'用户或DSH明确指定的任务分工'
    # Organic guns do not turn an entire infantry division into an artillery unit.
    from .unit_types import classify_unit
    profile=classify_unit(unit.get('type','')) or {}
    if profile.get('id')=='engineer' or '工兵' in unit.get('type',''):return 'engineer','已登记工兵类型'
    if unit.get('formation',{}).get('role')=='support':
        guns=any(e.get('category')=='artillery' and e.get('operational',0)>0 for e in unit.get('equipment',[]))
        return ('fire_support' if guns else 'sustain'),'已登记支援编组及装备'
    return 'maneuver','已登记作战编组；不将附属火炮当作整个单位兵种'


def _proposal(task,role):
    kind=task['kind'];target=task.get('target_id')
    if kind=='uniform':return copy.deepcopy(task['order']),'按明确统一行动分派'
    if role=='reserve':return {'action':'hold','duration':'next'},'预备或掩护分队保持位置，等待后续命令'
    if kind in ('advance','withdraw'):
        return dict(action='move',duration='until_arrived',destination=task['destination'],
            **({'participation':task['participation']} if 'participation' in task else {})),'按本单位预算分段机动，未到达前持续'
    if kind=='sustain' or role=='sustain':return dict(action='resupply',duration='next'),'本单位申请补给；不冒充已实现为其他单位运输'
    if role=='fire_support' and target:
        return dict(action='bombard',target_id=target,duration='next'),'以本单位登记炮兵执行间瞄支援，仍受射程、弹药和周期约束'
    if role=='engineer':
        return dict(action='fortify' if kind=='defend' else 'hold',duration='next'),(
            '在当前地域构筑防御，须有登记材料' if kind=='defend' else '尚未指定独立工程作业，本轮保留工程力量')
    if target:return dict(action='fire',target_id=target,duration='next'),'机动编组攻击明确目标；超出射程时须接近或等待'
    return dict(action='hold',duration='next'),'守备当前地域，未指定交战对象'


@commands.readonly_validation
def preview(session,group_id,task,*,replace_existing=False,execution=None):
    if type(replace_existing) is not bool:raise ValueError('覆盖已有命令选项须为布尔值')
    ids,cs,units=_task(session,group_id,task);existing={o['unit_id']:o for o in cs['orders']}
    rows=[]
    for identity in ids:
        entry,unit=units[identity];role,basis=_role(unit,task.get('roles',{}).get(identity))
        row={'unit_id':identity,'name':entry['name'],'team':entry['team'],'role':role,'role_basis':basis,
            'order':None,'reason':'','status':'unavailable','existing_order':None}
        if identity in existing:row['existing_order']={k:copy.deepcopy(existing[identity].get(k)) for k in ('id','action','duration','destination','target_id','status')}
        if not commands.available(unit):row['reason']='单位失能；保留组织和人员账，不派发行动'
        else:
            order,reason=_proposal(task,role);order['unit_id']=identity
            try:
                commands.step_order(session,order,cs);row.update(order=order,reason=reason,status='ready')
            except ValueError as exc:
                cause=str(exc)
                # Only maneuver assault elements advance when a shot is invalid;
                # support units do not guess a battery position or invent a target.
                alternative=(dict(unit_id=identity,action='move',duration='until_arrived',destination=task['destination'])
                    if task['kind']=='assault' and role=='maneuver' and not cs['no_fire']
                    and order['action'] in commands.capabilities(session,unit,entry['team'])['actions'] else None)
                position=commands.known_position(unit)
                if alternative and position and commands.distance(position,alternative['destination'])<=.01:
                    alternative=None
                    cause+='；已到达任务地域但目标仍不可交战，请调整地域或交战对象'
                if alternative:
                    try:
                        commands.step_order(session,alternative,cs)
                        row.update(order=alternative,reason='本轮射击受限：'+cause+'；先按给定目标机动',status='ready')
                    except ValueError as move_exc:cause+='；机动亦受限：'+str(move_exc)
                if row['order'] is None:
                    hold=dict(unit_id=identity,action='hold',duration='next')
                    try:
                        commands.step_order(session,hold,cs)
                        row.update(order=hold,reason='等待后续任务：'+cause,status='waiting')
                    except ValueError as hold_exc:row.update(reason=str(hold_exc),status='blocked')
            if row['order'] and row['order']['action'] in commands.PREPARATION_ACTIONS and task.get('end_turn'):
                row['order'].update(duration='until_turn',end_turn=task['end_turn'])
            if row['existing_order'] and not replace_existing:
                row['status']='manual_kept';row['reason']='保留已有人工单位命令；候选不覆盖。'+row['reason']
        rows.append(row)
    if execution is not None:
        from . import force_task_execution as lifecycle
        execution=lifecycle.validate_definition(session,group_id,task,execution)
        phase,reason=lifecycle.gate(session,execution,lifecycle._records(cs))
        if phase!='preparing':
            for row in rows:
                if row['order'] is not None and row['status']!='manual_kept':
                    row.update(order=dict(unit_id=row['unit_id'],action='hold',duration='next'),status='waiting',reason=reason)
    result={'version':VERSION,'group_id':group_id,'task':copy.deepcopy(task),
        'replace_existing':replace_existing,'world_version':commands.world_version(session),
        'command_revision':cs['revision'],'organization_revision':forces.state(session)['revision'],
        'rows':rows,'scope':'只读任务分解；每单位一项主要动作，非战果预测，确认后才进入原命令队列',
        'conflict_count':sum(r['existing_order'] is not None for r in rows),
        'candidate_count':sum(r['order'] is not None and r['status']!='manual_kept' for r in rows)}
    if execution is not None:
        result['execution']=execution
        result['scope']='持续任务确认预览；等待前置时明确待命，后续逐轮通过原命令与资源校验；人工改令后不自动重新接管'
    result['preview_hash']=missions.digest(result)
    return result


def commit(session,group_id,task,preview_hash,*,replace_existing=False,execution=None):
    plan=preview(session,group_id,task,replace_existing=replace_existing,execution=execution)
    if plan['preview_hash']!=preview_hash:raise commands.Conflict('任务预览已过期或输入改变，请重新预览')
    selected=[r for r in plan['rows'] if r['order'] is not None and r['status']!='manual_kept']
    if not selected:raise ValueError('没有新增可暂存任务；已有人工命令已保留，或单位均不可行动')
    expired={r['unit_id'] for r in plan['rows'] if r['status']=='unavailable'}
    replaced={r['unit_id'] for r in selected}|expired;cs=commands.state(session)
    retained=[{k:copy.deepcopy(v) for k,v in o.items() if k in DRAFT_FIELDS} for o in cs['orders'] if o['unit_id'] not in replaced]
    result=commands.replace_queue(session,retained+([] if execution is not None else [r['order'] for r in selected]),
        **{k:cs[k] for k in ('control_team','director','no_fire','intent')})
    for archived in result['archive']:
        if archived['unit_id'] in expired and any(o['id']==archived['id'] for o in cs['orders']):
            archived.update(status='expired',reason='任务预览确认：该下级已失能，原命令终止，人员账保留')
    task_id=uuid.uuid4().hex;rows={r['unit_id']:r for r in selected};units=commands.resolve_units(session)
    chains=forces.effective_command_chains(session)
    result.setdefault('task_plans',{})[task_id]={'version':VERSION,'group_id':group_id,
        'task':copy.deepcopy(task),'replace_existing':replace_existing,'preview_hash':preview_hash,
        'issued_turn':session['turn_count'],'issued_session_id':session['id'],
        'organization_revision':plan['organization_revision']}
    if execution is not None:
        from . import force_task_execution as lifecycle
        lifecycle.attach(session,result,task_id,plan['execution'],plan['rows'])
        return result
    for order in result['orders']:
        if order['unit_id'] in rows:
            row=rows[order['unit_id']];unit=units[order['unit_id']][1]
            order['task_context']={'version':VERSION,'task_id':task_id,'group_id':group_id,
                'kind':task['kind'],'role':row['role'],'reason':row['reason'],'preview_hash':preview_hash,
                'organization_revision':plan['organization_revision'],'issued_turn':session['turn_count'],
                'issued_session_id':session['id'],'command_chain':chains.get(forces.leaf_key(row['team'],unit),[])}
    return result


def observation(session,args):
    """Bounded model projection; the full candidate stays in host memory."""
    if not isinstance(args,dict) or set(args)-{'group_id','task','replace_existing','execution','offset','limit','preview_hash'}:
        raise ValueError('任务预览工具字段非法')
    offset=args.get('offset',0);limit=args.get('limit',8)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=16:
        raise ValueError('任务预览每页1至16项，偏移须为非负整数')
    plan=preview(session,args.get('group_id'),args.get('task'),replace_existing=args.get('replace_existing',False),execution=args.get('execution'))
    if args.get('preview_hash') and args['preview_hash']!=plan['preview_hash']:
        raise commands.Conflict('任务预览版本已变化，请重新从第一页读取')
    rows=plan.pop('rows');plan['rows']=rows[offset:offset+limit];plan['total_rows']=len(rows)
    plan['next_args']={**args,'offset':offset+limit,'limit':limit,'preview_hash':plan['preview_hash']} if offset+limit<len(rows) else None
    return {'ok':True,**plan}
