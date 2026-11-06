"""Versioned domain task lifecycle over existing command preparation/receipts.

No agent transport, battle effects, invented communications or second physical
world. Preparation is detached; the usual world/command checkpoint commits it.
"""
import copy
import uuid
from . import commands, missions, force_organization as forces

VERSION='force-task-execution-1'
TERMINAL={'completed','failed','cancelled'}
STATES=TERMINAL|{'queued','waiting_time','waiting_dependency','preparing','executing','blocked'}
MEMBER_STATES={'queued','waiting_time','waiting_dependency','preparing','executing','blocked','completed','manual_override','detached','unavailable'}


def _records(cs):
    plans=cs.get('task_plans',{})
    if not isinstance(plans,dict) or any(not isinstance(r,dict) for r in plans.values()):raise ValueError('任务登记须为对象映射')
    return {i:r for i,r in plans.items() if 'execution' in r}


def _combine(mode, values):
    return all(values) if mode=='all' else any(values)


def _dependency_order(records):
    visiting=set();visited=set();ordered=[]
    def visit(identity):
        if identity in visiting:raise ValueError('持续任务依赖成环')
        if identity in visited:return
        visiting.add(identity)
        for dep in records[identity]['execution']['definition']['after']['task_ids']:visit(dep)
        visiting.remove(identity);visited.add(identity);ordered.append(identity)
    for identity in records:visit(identity)
    return ordered


def _fields(value, fields, label):
    if not isinstance(value,dict) or set(value)!=set(fields):raise ValueError(label+'字段缺失或越界')


def _ids(value, allowed, label):
    if not isinstance(value,list) or len(value)>256 or any(not isinstance(i,str) or i not in allowed for i in value) or len(value)!=len(set(value)):
        raise ValueError(label+'须为不重复的已登记身份')


def validate_definition(session, group_id, task, value, *, issued_turn=None):
    _fields(value,{'version','label','not_before_turn','after','finish','assumption'},'持续任务定义')
    if value['version']!=VERSION:raise ValueError('持续任务版本不支持')
    for key,limit in [('label',120),('assumption',2000)]:
        if not isinstance(value[key],str) or not value[key].strip() or len(value[key])>limit:raise ValueError('持续任务名称/依据须为有界非空文字')
    start=value['not_before_turn'];issued=session['turn_count'] if issued_turn is None else issued_turn
    if type(start) is not int or not issued<start<=issued+1000:raise ValueError('任务起始须为发出后1至1000回合内')
    if task.get('end_turn') or task.get('order',{}).get('duration')=='until_turn':
        raise ValueError('持续任务窗口由finish声明，不再叠加旧单轮准备截止')
    _fields(value['after'],{'mode','task_ids','goal_ids'},'持续任务前置')
    after=value['after']
    if after['mode'] not in ('all','any'):raise ValueError('持续任务前置须为all或any')
    cs=commands.state(session);plans=_records(cs)
    _ids(after['task_ids'],plans,'任务前置')
    # When restoring a retired group its frozen members still carry the team.
    units=commands.resolve_units(session,cs)
    candidates=forces.effective_member_ids(session,group_id) if issued_turn is None else []
    team=units[candidates[0]][0]['team'] if candidates else None
    goals={n['id']:n for n in session['war_state'].get('mission',{}).get('definition',{}).get('campaign_plan',{}).get('nodes',[])}
    _ids(after['goal_ids'],goals,'目标前置')
    if team and any(plans[i]['execution']['team']!=team for i in after['task_ids']):raise ValueError('不能引用敌方持续任务为己方前置')
    finish=value['finish']
    if not isinstance(finish,dict):raise ValueError('持续任务须有程序完成判据')
    if finish.get('kind')=='arrived':
        _fields(finish,{'kind'},'到达完成判据')
        if not (task['kind'] in ('advance','withdraw') or task['kind']=='uniform' and task['order'].get('action')=='move') or 'reserve' in task.get('roles',{}).values():
            raise ValueError('全员到达判据只适用于全体机动任务；预备/攻坚须使用目标或任务窗口')
    elif finish.get('kind')=='goal':
        _fields(finish,{'kind','goal_id'},'目标完成判据')
        if not isinstance(finish['goal_id'],str) or finish['goal_id'] not in goals:raise ValueError('完成目标未登记')
    elif finish.get('kind')=='turn':
        _fields(finish,{'kind','end_turn','minimum_executions'},'任务窗口判据')
        if type(finish['end_turn']) is not int or not start<=finish['end_turn']<=issued+1000 or type(finish['minimum_executions']) is not int or not 1<=finish['minimum_executions']<=1000:
            raise ValueError('任务窗口及最少实际执行次数非法')
    else:raise ValueError('持续任务完成判据未支持')
    refs=after['goal_ids']+([finish['goal_id']] if finish['kind']=='goal' else [])
    if team and any(goals[i]['team']!=team for i in refs):raise ValueError('任务只能绑定己方目标')
    if len([r for r in plans.values() if r['execution']['status'] not in TERMINAL])>=256 and issued_turn is None:raise ValueError('同时活动的持续任务最多256项')
    return copy.deepcopy(value)


def _definition_hash(record):
    runtime=record['execution']
    frozen=runtime.get('identity_origin') or runtime
    return missions.digest({k:record[k] for k in ('group_id','task')}|dict(definition=runtime['definition'],team=runtime['team'],
        members=frozen['members'],chains=frozen['chains']))


def _stamp(runtime):
    runtime['state_hash']=missions.digest({k:v for k,v in runtime.items() if k!='state_hash'})


def _status(runtime,status,reason,turn):
    if (runtime['status'],runtime['reason'])!=(status,reason):
        runtime['events'].append(dict(turn=turn,status=status,reason=reason))
    runtime.update(status=status,reason=reason)


def attach(session, cs, task_id, definition, rows):
    record=cs['task_plans'][task_id];units=commands.resolve_units(session,cs)
    members=[r['unit_id'] for r in rows]
    existing=_records(commands.state(session))
    if any(set(members)&set(r['execution']['members']) for r in existing.values() if r['execution']['status'] not in TERMINAL):
        raise ValueError('承担单位已有持续任务；请先明确取消旧任务，不静默覆盖')
    chains=forces.effective_command_chains(session)
    runtime=dict(version=VERSION,definition=copy.deepcopy(definition),members=members,team=units[members[0]][0]['team'],
        chains={i:chains.get(forces.leaf_key(units[i][0]['team'],units[i][1]),[]) for i in members},
        status='queued',reason='任务已确认进入应用队列；未证明部队实际收令',last_turn=session['turn_count'],
        member_states={r['unit_id']:dict(status='manual_override' if r['status']=='manual_kept' else 'queued',
            reason='保留已有人工命令，不自动接管' if r['status']=='manual_kept' else '等待逐轮校验与实际交付',
            executions=0,last_receipt_id=None,last_order_id=None) for r in rows},events=[])
    record['execution']=runtime;runtime['definition_hash']=_definition_hash(record);_stamp(runtime)


def validate(session, cs=None):
    cs=cs or commands.state(session);records=_records(cs);registry={r['id']:r for r in cs['registry']}
    if len(records)>4096:raise ValueError('持续任务登记超过本版容量，须显式归档')
    for identity,record in records.items():
        _fields(record,{'version','group_id','task','replace_existing','preview_hash','issued_turn','issued_session_id','organization_revision','execution'},'持续任务登记')
        if type(record['issued_turn']) is not int or not 0<=record['issued_turn']<=session['turn_count']:raise ValueError('任务发出回合非法')
        runtime=record['execution']
        expected={'version','definition','members','team','chains','status','reason','last_turn','member_states','events','definition_hash','state_hash'}
        if 'identity_origin' in runtime:
            from . import formation_session
            expected.add('identity_origin')
            if runtime['identity_origin']!=formation_session.task_origin(cs,identity):raise ValueError('任务冻结承担者来源与身份交接不一致')
            if runtime['status'] not in TERMINAL and runtime['members']!=list(dict.fromkeys(
                    i for old in runtime['identity_origin']['members'] for i in formation_session.remap(cs,old))):
                raise ValueError('持续任务承担者与身份接续的完整下级集合不一致')
        _fields(runtime,expected,'持续任务运行状态')
        if runtime['version']!=VERSION or runtime['status'] not in STATES:raise ValueError('持续任务状态/版本非法')
        _ids(runtime['members'],registry,'冻结承担单位')
        if not runtime['members'] or runtime['team'] not in ('red','blue') or any(registry[i]['team']!=runtime['team'] for i in runtime['members']):raise ValueError('持续任务承担者为空或跨方')
        validate_definition(session,record['group_id'],record['task'],runtime['definition'],issued_turn=record['issued_turn'])
        if runtime['definition_hash']!=_definition_hash(record):raise ValueError('冻结任务定义/承担者已改变')
        if runtime['state_hash']!=missions.digest({k:v for k,v in runtime.items() if k!='state_hash'}):raise ValueError('持续任务运行状态摘要不一致')
        if type(runtime['last_turn']) is not int or runtime['last_turn']!=session['turn_count']:raise ValueError('任务与世界回合不一致')
        if not isinstance(runtime['member_states'],dict) or not isinstance(runtime['chains'],dict) or set(runtime['member_states'])!=set(runtime['members']) or set(runtime['chains'])!=set(runtime['members']):raise ValueError('任务成员状态不完整')
        for row in runtime['member_states'].values():
            _fields(row,{'status','reason','executions','last_receipt_id','last_order_id'},'任务下级状态')
            if row['status'] not in MEMBER_STATES or type(row['executions']) is not int or row['executions']<0:raise ValueError('任务执行计数/状态非法')
        if not isinstance(runtime['events'],list) or any(not isinstance(e,dict) or set(e)!={'turn','status','reason'} or e['status'] not in STATES or type(e['turn']) is not int or e['turn']>session['turn_count'] for e in runtime['events']):raise ValueError('任务事件非法')
        for dep in runtime['definition']['after']['task_ids']:
            if records[dep]['execution']['team']!=runtime['team']:raise ValueError('任务依赖跨阵营')
        config=runtime['definition'];goal_ids=config['after']['goal_ids']+([config['finish']['goal_id']] if config['finish']['kind']=='goal' else [])
        goals={n['id']:n for n in session['war_state'].get('mission',{}).get('definition',{}).get('campaign_plan',{}).get('nodes',[])}
        if any(goals[i]['team']!=runtime['team'] for i in goal_ids):raise ValueError('任务目标引用跨阵营')
    _dependency_order(records)
    for order in cs['orders']:
        context=order.get('task_context') or {}
        if context.get('execution_version')==VERSION and (context.get('task_id') not in records or order['unit_id'] not in records[context['task_id']]['execution']['members'] or type(context.get('activated')) is not bool):raise ValueError('持续任务命令绑定非法')
    return True


def gate(session, definition, records):
    if session['turn_count']+1<definition['not_before_turn']:return 'waiting_time','未到任务起始回合'
    after=definition['after'];goals=session['war_state'].get('campaign_plan',{}).get('nodes',{})
    values=[records[i]['execution']['status']=='completed' for i in after['task_ids']]+[goals[i]['status']=='completed' for i in after['goal_ids']]
    if values and not _combine(after['mode'],values):return 'waiting_dependency','前置任务或目标尚未达成；预备力量待命'
    return 'preparing','前置已满足，按当前能力与资源准备下级命令'


def prepare(session, cs):
    """Detached command policy expansion, not battle or agent execution."""
    if not _records(cs):return cs
    validate(session,cs)
    from . import force_tasks
    result=copy.deepcopy(cs);records=_records(result);units=commands.resolve_units(session,result)
    chains=forces.effective_command_chains(session);turn=session['turn_count']+1
    owned=lambda o:o.get('task_context',{}).get('execution_version')==VERSION
    drafts=[{k:copy.deepcopy(v) for k,v in o.items() if k in force_tasks.DRAFT_FIELDS} for o in cs['orders'] if not owned(o)]
    old_owned={o['unit_id']:o for o in cs['orders'] if owned(o)};contexts={}
    for identity,record in records.items():
        runtime=record['execution']
        if runtime['status'] in TERMINAL:continue
        try:allowed=set(forces.effective_member_ids(session,record['group_id']))
        except ValueError:allowed=set()
        phase,reason=gate(session,runtime['definition'],records)
        shadow={**session,'command_state':{**result,'orders':[o for o in cs['orders'] if not owned(o)]}}
        from . import formation_session
        task=formation_session.current_task(cs,record['task'])
        if 'roles' in task:task['roles']={i:r for i,r in task['roles'].items() if i in allowed}
        try:rows={r['unit_id']:r for r in force_tasks.preview(shadow,record['group_id'],task)['rows']}
        except ValueError:rows={}
        active=0;blocked=0
        for member in runtime['members']:
            state=runtime['member_states'][member];pair=units.get(member)
            current=next((o for o in cs['orders'] if o['unit_id']==member and not owned(o)),None)
            cancelled=any(o.get('task_context',{}).get('task_id')==identity and o.get('task_context',{}).get('execution_version')==VERSION and o['unit_id']==member and o.get('status')=='cancelled' and o.get('reason','').startswith('用户') for o in cs['archive'])
            if state['status']=='manual_override':
                state.update(status='manual_override',reason='人工单位命令优先；持续任务不自动重新接管');blocked+=1;continue
            from . import unit_participation
            temporary=bool(current and current.get('participation'))
            participation=unit_participation.unit_view(session['war_state'],pair[1],pair[0]['team']) if pair and 'unit_participation' in session['war_state'] else None
            reserved=bool(participation and (participation['pending'] or not participation['controls_objectives']))
            task_participation=task.get('participation') or task.get('order',{}).get('participation')
            if temporary:
                state.update(status='blocked',reason='参与状态机动或后方待命；原任务保留，重新投入后按原权限及窗口恢复');blocked+=1;continue
            if current or cancelled:
                state.update(status='manual_override',reason='人工单位命令优先；持续任务不自动重新接管');blocked+=1;continue
            if not pair or not commands.available(pair[1]):
                state.update(status='unavailable',reason='承担单位不在场或已失能；未推定全歼');blocked+=1;continue
            if member not in allowed or chains.get(forces.leaf_key(pair[0]['team'],pair[1]),[])!=runtime['chains'][member] or not cs['director'] and pair[0]['team']!=cs['control_team']:
                state.update(status='detached',reason='当前指挥关系或权限已改变，旧任务停止派发');blocked+=1;continue
            row=rows.get(member)
            waiting_participation=reserved and not task_participation
            if waiting_participation:
                row=dict(order=dict(unit_id=member,action='hold',duration='next'),role=(row or {}).get('role','reserve'),
                    reason='参与状态机动或后方待命；明确等待且不计为原任务执行，重新投入后按原窗口恢复')
            if not row or row['order'] is None:
                state.update(status='blocked',reason=row['reason'] if row else '任务分工无法在当前编制/能力下形成合法命令');blocked+=1;continue
            draft=copy.deepcopy(row['order']);intended='hold' if waiting_participation else force_tasks._proposal(task,row['role'])[0]['action']
            # A validated assault approach is a real task action. Keep a failed
            # fire/support fallback to hold distinct: waiting is not delivery.
            if (task['kind']=='assault' and row['role']=='maneuver' and row['status']=='ready'
                    and intended=='fire' and draft['action']=='move'):
                intended='move'
            activated=phase=='preparing' and not waiting_participation
            if not activated:draft=dict(unit_id=member,action='hold',duration='next')
            else:draft['duration']='until_arrived' if draft['action']=='move' else 'next';draft.pop('end_turn',None)
            old=old_owned.get(member)
            if old and all(old.get(k)==draft.get(k) for k in ('action','duration','destination','target_id','air_pool','participation')):draft['id']=old['id']
            drafts.append(draft);active+=1
            if waiting_participation:blocked+=1
            state.update(status='blocked' if waiting_participation else phase if not activated else 'preparing',
                reason=row['reason'] if waiting_participation or activated else reason)
            contexts[member]=dict(version=force_tasks.VERSION,execution_version=VERSION,task_id=identity,group_id=record['group_id'],
                kind=task['kind'],role=row['role'],reason=state['reason'],preview_hash=record['preview_hash'],
                organization_revision=forces.state(session)['revision'],issued_turn=record['issued_turn'],issued_session_id=record['issued_session_id'],
                command_chain=runtime['chains'][member],expected_action=intended,activated=activated)
        _status(runtime,phase if active and not blocked else 'blocked',reason if active and not blocked else '部分或全部承担者受限；逐成员原因保留',turn)
        _stamp(runtime)
    # The existing queue validator owns action/air reservations and normalization.
    prior_archive=len(result['archive'])
    queued=commands.replace_queue({**session,'command_state':result},drafts,**{k:cs[k] for k in ('control_team','director','no_fire','intent')})
    for old in queued['archive'][prior_archive:]:
        if owned(old):old['reason']='持续任务轮次调整；不代表人工改令'
    for order in queued['orders']:
        if order['unit_id'] in contexts:
            context=contexts[order['unit_id']]
            # Deterministic per-turn IDs preserve read-only repeated preparation;
            # unfinished movement keeps its existing intent ID for crossing.
            if 'id' not in next(d for d in drafts if d['unit_id']==order['unit_id']):
                order['id']=uuid.uuid5(uuid.NAMESPACE_URL,f"{session['id']}:{context['task_id']}:{order['unit_id']}:{turn}:{missions.digest({k:order.get(k) for k in ('action','duration','destination','target_id')})}").hex
            order['task_context']=context
            records[context['task_id']]['execution']['member_states'][order['unit_id']]['last_order_id']=order['id']
    for record in records.values():_stamp(record['execution'])
    queued['task_plans']=result['task_plans']
    return queued


def finish(session, cs, after, receipts):
    records=_records(cs)
    if not records:return cs
    seen=set()
    for receipt in receipts:
        context=receipt.get('task_context') or {}
        if context.get('execution_version')!=VERSION or context.get('task_id') not in records:continue
        key=(context['task_id'],receipt['unit_id'])
        if key in seen:raise ValueError('同一任务承担者每轮只能取得一次执行回执，不能重复计数')
        seen.add(key)
    units={i:u for i,(_,u) in commands.resolve_units({**session,'war_state':after,'command_state':cs},cs).items()}
    turn=session['turn_count']+1
    # Restored JSON maps may have a different insertion order. A predecessor's
    # settlement must be visible to its dependants in this same committed frame.
    for identity in _dependency_order(records):
        record=records[identity]
        runtime=record['execution'];runtime['last_turn']=turn
        if runtime['status'] in TERMINAL:_stamp(runtime);continue
        for receipt in receipts:
            context=receipt.get('task_context') or {};member=receipt['unit_id']
            if context.get('execution_version')!=VERSION or context.get('task_id')!=identity:continue
            state=runtime['member_states'][member];state['last_receipt_id']=receipt['id']
            delivered=receipt['status'] in ('completed','executing') and receipt['action']==context['expected_action'] and context['activated']
            if delivered:state['executions']+=1
            if not context['activated']:continue
            # A legal fallback hold has no executor error. Preserve its concrete
            # planning restriction so the operator can revise the task.
            reason=receipt.get('reason') or ('已取得实际行动回执；不等于任务目标完成' if delivered
                else context.get('reason') or '实际行动未交付或受限')
            state.update(status='executing' if delivered else 'blocked',reason=reason)
        definition=runtime['definition'];criterion=definition['finish'];complete=False
        eligible,_=gate({**session,'war_state':after},definition,records)
        if criterion['kind']=='arrived':
            destination=record['task'].get('destination') or record['task'].get('order',{}).get('destination')
            complete=eligible=='preparing' and all(i in units and commands.available(units[i]) and commands.known_position(units[i]) and commands.distance(commands.known_position(units[i]),destination)<=.01 for i in runtime['members'])
        elif criterion['kind']=='goal':complete=eligible=='preparing' and after['campaign_plan']['nodes'][criterion['goal_id']]['status']=='completed'
        elif turn>=criterion['end_turn']:
            complete=all(s['executions']>=criterion['minimum_executions'] for s in runtime['member_states'].values())
            if not complete:_status(runtime,'failed','任务窗口结束，实际执行次数不足；未将待命替代或未交付计为完成',turn)
        if complete:_status(runtime,'completed','已满足冻结的实际到达/目标/执行窗口判据',turn)
        elif runtime['status'] not in TERMINAL:
            status,reason=gate({**session,'turn_count':session['turn_count'],'war_state':after},definition,records)
            if after.get('mission',{}).get('status')=='completed':_status(runtime,'cancelled','战局已结算；此任务未达完成判据',turn)
            elif all(s['status'] in ('manual_override','detached','unavailable','blocked') for s in runtime['member_states'].values()):_status(runtime,'blocked','承担者受限；原因见成员状态',turn)
            elif status in ('waiting_time','waiting_dependency'):_status(runtime,status,reason,turn)
            elif not any(s['executions'] for s in runtime['member_states'].values()):_status(runtime,'preparing','前置已满足，等待下一轮实际命令交付',turn)
            else:_status(runtime,'executing','持续任务尚未完成；后续仍须逐轮校验权限、能力和资源',turn)
        _stamp(runtime)
    terminal={i for i,r in records.items() if r['execution']['status'] in TERMINAL}
    retained=[]
    for order in cs['orders']:
        if order.get('task_context',{}).get('task_id') in terminal and order.get('task_context',{}).get('execution_version')==VERSION:
            cs['archive'].append({**order,'status':'expired','reason':'所属持续任务已终止'})
        else:retained.append(order)
    cs['orders']=retained
    return cs


def cancel(session, task_id):
    commands.assert_writable(session);cs=commands.state(session);validate(session,cs)
    record=_records(cs).get(task_id)
    if not record:raise ValueError('持续任务不存在')
    runtime=record['execution']
    if not cs['director'] and cs['control_team']!=runtime['team']:raise ValueError('无权撤销对方任务')
    if runtime['status'] in TERMINAL:raise ValueError('持续任务已终止')
    _status(runtime,'cancelled','用户明确撤销任务；已发生物理消耗和在途状态不回滚',session['turn_count']);_stamp(runtime)
    kept=[]
    for order in cs['orders']:
        if order.get('task_context',{}).get('task_id')==task_id and order.get('task_context',{}).get('execution_version')==VERSION:
            cs['archive'].append({**order,'status':'cancelled','reason':'持续任务取消；已耗资源不返还'})
        else:kept.append(order)
    cs['orders']=kept;cs['revision']+=1
    return cs


def observation(session,args=None):
    args=args or {}
    if not isinstance(args,dict) or set(args)-{'kind','task_id','offset','limit','view_version'}:raise ValueError('持续任务查询字段非法')
    kind=args.get('kind','tasks');limit=args.get('limit',8);offset=args.get('offset',0)
    if kind not in ('tasks','members','events') or type(limit) is not int or not 1<=limit<=16 or type(offset) is not int or offset<0:raise ValueError('持续任务分页须为有效类型、1至16条和非负偏移')
    cs=commands.state(session);validate(session,cs);records=_records(cs)
    token=missions.digest([commands.world_version(session),cs['revision'],forces.state(session)['revision'],records])
    if (offset and not args.get('view_version')) or args.get('view_version') and args['view_version']!=token:raise commands.Conflict('任务观察版本已变化，请从第一页重查')
    identity=args.get('task_id')
    if kind=='tasks':
        rows=[dict(id=i,label=r['execution']['definition']['label'],team=r['execution']['team'],group_id=r['group_id'],
            status=r['execution']['status'],reason=r['execution']['reason'],definition=copy.deepcopy(r['execution']['definition']),
            can_cancel=r['execution']['status'] not in TERMINAL and session.get('simulation_mode','open')=='open' and (cs['director'] or cs['control_team']==r['execution']['team']),
            member_count=len(r['execution']['members']),member_sample=r['execution']['members'][:4],
            member_args=dict(kind='members',task_id=i,limit=16,view_version=token),event_args=dict(kind='events',task_id=i,limit=16,view_version=token)) for i,r in records.items()]
    else:
        if identity not in records:raise ValueError('持续任务不存在')
        runtime=records[identity]['execution']
        if kind=='events':rows=copy.deepcopy(runtime['events'])
        else:
            units={r['id']:r for r in cs['registry']}
            from . import formation_session
            rows=[dict(unit_id=i,name=units[i]['name'],**copy.deepcopy(runtime['member_states'][i]),
                **({'conversion_origin':origin} if (origin:=formation_session.member_origin(cs,identity,i)) else {})) for i in runtime['members']]
    return dict(ok=True,readonly=True,version=VERSION,kind=kind,task_id=identity,turn=session['turn_count'],view_version=token,
        total=len(rows),offset=offset,rows=rows[offset:offset+limit],
        next_args={**args,'kind':kind,'offset':offset+limit,'limit':limit,'view_version':token} if offset+limit<len(rows) else None,
        scope='应用持续任务及实际命令回执；不是新战果算法或已标定通信模型。已接受不等于实际收令。')
