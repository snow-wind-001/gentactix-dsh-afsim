"""Audited detached command/organization handoff, not a platform transaction.

Uses existing command IDs, task lifecycle and the world's ownership journal.
Old decisions and receipts retain their IDs. No SDK sessions are forked/cloned.
"""
import copy
from contextlib import contextmanager
import uuid

from . import commands, formation_continuity as continuity, formation_registry as registry
from . import force_organization as forces, force_task_execution as tasks, missions

VERSION='formation-session-handoff-1'


def _base(cs):return {k:copy.deepcopy(v) for k,v in cs.items() if k!='formation_handoffs'}


def _detached(session):
    # Reuse the checkpoint boundary: a live observer may contain thread locks,
    # and progress/adapter objects are rebuilt by the host, never persisted.
    from backend.session_store import serializable
    return serializable(session)


def remap(cs,identity):
    """Resolve a frozen command reference through all recorded conversions."""
    values=[identity]
    for event in cs.get('formation_handoffs',[]):
        values=list(dict.fromkeys(i for old in values for i in event['command_map'].get(old,[old])))
    return values


def task_origin(cs,identity):
    for event in cs.get('formation_handoffs',[]):
        record=event['before_command_state'].get('task_plans',{}).get(identity)
        if record and 'execution' in record:
            runtime=record['execution']
            return copy.deepcopy(runtime.get('identity_origin') or {k:runtime[k] for k in ('members','chains')})
    return None


def member_origin(cs,task_id,member):
    for event in reversed(cs.get('formation_handoffs',[])):
        sources=[i for i,new in event['command_map'].items() if member in new]
        record=event['before_command_state'].get('task_plans',{}).get(task_id)
        if not sources or not record or 'execution' not in record:continue
        states=record['execution']['member_states'];counts={i:states[i]['executions'] for i in sources if i in states}
        if counts:return dict(registry_revision=event['registry_revision'],source_members=sources,
            inherited_execution_counts=counts,counts_must_not_be_summed=True,
            scope='每个当前承担者的已交付轮次含继承；共享来源不可相加，后续仍须取得实际回执')
    return None


def current_task(cs,task):
    value=copy.deepcopy(task)
    if 'roles' in value:
        roles={}
        for old,role in value['roles'].items():
            for identity in remap(cs,old):
                if identity in roles and roles[identity]!=role:raise ValueError('合并后任务分工冲突')
                roles[identity]=role
        value['roles']=roles
    if value.get('target_id'):
        targets=remap(cs,value['target_id'])
        if len(targets)!=1:raise ValueError('原单一任务目标已细分，须明确重新选择目标')
        value['target_id']=targets[0]
    if value.get('order',{}).get('target_id'):
        targets=remap(cs,value['order']['target_id'])
        if len(targets)!=1:raise ValueError('原单一任务目标已细分，须明确重新选择目标')
        value['order']['target_id']=targets[0]
    return value


def _target(order,mapping):
    value=copy.deepcopy(order)
    if value.get('target_id') in mapping:
        targets=mapping[value['target_id']]
        if len(targets)!=1:raise ValueError('现有单一攻击目标即将细分，须先明确取消或重新选择目标')
        value['target_id']=targets[0]
    return value


def _derive(session,world):
    before=commands.state(session);event=world['formation_registry']['transactions'][-1];team=event['team']
    old=commands.resolve_units(session,before);old_by_key={registry.key(r['team'],u):i for i,(r,u) in old.items()}
    source_ids=[old_by_key[registry.key(team,u)] for u in event['proposal']['before']]
    cs=copy.deepcopy(before)
    for row in cs['registry']:
        if row['id'] in source_ids:row.update(retired=True,retired_turn=session['turn_count'],present=False)
    after={**_detached(session),'war_state':copy.deepcopy(world),'command_state':cs}
    cs=commands.state(after);after['command_state']=cs;new=commands.resolve_units(after,cs)
    by_key={registry.key(r['team'],u):i for i,(r,u) in new.items()}
    targets=[by_key[registry.key(team,u)] for u in event['proposal']['after']]
    mapping={i:list(targets) for i in source_ids}
    leaves={forces.leaf_key(team,u):[forces.leaf_key(team,v) for v in event['proposal']['after']] for u in event['proposal']['before']}
    org=forces.state(session);owners={key:g['id'] for g in org['groups'] for key in g['members']}
    if len({owners.get(key) for key in leaves})>1:raise ValueError('合并前直接指挥关系不同，须先明确调整配属')
    for group in org['groups']:group['members']=list(dict.fromkeys(i for key in group['members'] for i in leaves.get(key,[key])))
    org['revision']+=1;org['events'].append(dict(kind='formation_conversion',revision=org['revision'],
        registry_revision=event['revision'],turn=session['turn_count'],leaf_map=copy.deepcopy(leaves)))
    after['force_organization']=org
    # One human intent can fan out only when its action does not reserve an
    # external package. Merge requires equivalent orders, not a guessed winner.
    selected=[o for o in before['orders'] if o['unit_id'] in mapping]
    signatures=[{k:v for k,v in o.items() if k not in ('unit_id','id')} for o in selected]
    if len(source_ids)>1 and (selected and len(selected)!=len(source_ids) or signatures and any(s!=signatures[0] for s in signatures)):
        raise ValueError('合并前人工或任务命令不同，不能静默覆盖冲突决策')
    if len(targets)>1 and any(o['action']=='air_support' for o in selected):
        raise ValueError('航空资源预约不能复制，须先明确新的请求单位')
    orders=[_target(o,mapping) for o in before['orders'] if o['unit_id'] not in mapping]
    template=selected[0] if selected else None
    if template:
        for target in targets:
            order=_target(template,mapping);order['unit_id']=target
            namespace,_=commands.identity_namespace(session)
            order['id']=uuid.uuid5(uuid.NAMESPACE_URL,f'formation:{namespace}:{event["revision"]}:{template["id"]}:{target}').hex
            if order.get('task_context'):
                order['task_context']['organization_revision']=org['revision']
            orders.append(order)
    cs['orders']=orders
    cs['archive'].extend({**copy.deepcopy(o),'status':'cancelled','reason':'编组身份接续；非用户取消或物理执行'} for o in selected)
    cs['unit_agents']=list(dict.fromkeys(i for old_id in before['unit_agents'] for i in mapping.get(old_id,[old_id])))
    # agent_sessions stays exactly as before. Native AgentRegistry allocates a
    # distinct session for a new ID on its first real decision, once admitted.
    cs['revision']=before['revision']+1
    chains=forces.effective_command_chains(after)
    for identity,record in cs.get('task_plans',{}).items():
        runtime=record.get('execution')
        if not runtime or runtime['status'] in tasks.TERMINAL:continue
        # Check role and target semantics before changing any frozen record.
        proposed_cs={**cs,'formation_handoffs':cs.get('formation_handoffs',[])+[dict(command_map=mapping)]}
        current_task(proposed_cs,record['task'])
        affected=[i for i in runtime['members'] if i in mapping]
        if not affected:continue
        if len(source_ids)>1 and set(affected)!=set(source_ids):raise ValueError('不同持续任务承担者不能隐式合并')
        runtime.setdefault('identity_origin',{k:copy.deepcopy(runtime[k]) for k in ('members','chains')})
        states=runtime['member_states'];old_states=[states[i] for i in affected]
        if len({r['status'] for r in old_states})>1:raise ValueError('合并前任务执行/人工接管状态不同')
        inherited=copy.deepcopy(old_states[0]);inherited['executions']=min(r['executions'] for r in old_states)
        # Receipt IDs are historical references, not receipts for new actors.
        inherited.update(last_order_id=None,last_receipt_id=None)
        runtime['members']=list(dict.fromkeys(i for old_id in runtime['members'] for i in mapping.get(old_id,[old_id])))
        runtime['member_states']={i:copy.deepcopy(states[i] if i not in targets else inherited) for i in runtime['members']}
        runtime['chains']={i:chains.get(forces.leaf_key(new[i][0]['team'],new[i][1]),[]) for i in runtime['members']}
        tasks._stamp(runtime)
    for order in cs['orders']:
        context=order.get('task_context') or {};r=cs.get('task_plans',{}).get(context.get('task_id'),{}).get('execution')
        if r and context.get('execution_version')==tasks.VERSION:context['command_chain']=r['chains'][order['unit_id']]
    return after,mapping,leaves


def _receipt(cs):
    value=copy.deepcopy(cs);value['formation_handoffs'].pop()
    return missions.digest(value)


def validate_history(session,cs=None):
    world=session['war_state'];cs=cs if cs is not None else session.get('command_state') or {}
    events=cs.get('formation_handoffs',[]);ledger=(world.get('formation_registry') or {}).get('transactions',[])
    if not isinstance(events,list) or len(events)!=len(ledger):
        raise ValueError('运行中身份转换缺少对应会话交接记录')
    for value,event in zip(events,ledger):
        fields={'version','registry_revision','turn','command_map','leaf_map','before_command_state','before_organization',
            'after_command_revision','after_command_hash','after_organization_hash'}
        if (not isinstance(value,dict) or set(value)!=fields or value['version']!=VERSION
                or any(type(value[k]) is not int for k in ('registry_revision','turn'))
                or value['registry_revision']!=event['revision'] or value['turn']!=event['turn']):
            raise ValueError('会话身份交接版本/修订非法')
        before=value['before_command_state']
        if (not isinstance(before,dict) or not isinstance(value['before_organization'],dict)
                or type(value['after_command_revision']) is not int or type(before.get('revision')) is not int
                or type(value['before_organization'].get('revision')) is not int
                or value['after_command_revision']!=before['revision']+1):
            raise ValueError('会话交接前后命令修订不连续')
        if cs['revision']<value['after_command_revision'] or forces.state(session)['revision']<value['before_organization']['revision']+1:
            raise ValueError('会话命令或组织修订不能退回转换前')
        shadow={**session,'command_state':copy.deepcopy(before),'war_state':{'red_units':[],'blue_units':[]}}
        old_ids={}
        for unit in event['proposal']['before']:
            matches=[r['id'] for r in before['registry'] if (r['team'],r['name'])==(event['team'],unit['name']) and not r.get('retired')]
            if len(matches)!=1:raise ValueError('交接前执行身份不存在或有歧义')
            old_ids[forces.leaf_key(event['team'],unit)]=matches[0]
        for row in shadow['command_state']['registry']:
            if row['id'] in old_ids.values():row.update(retired=True,present=False)
        shadow['war_state'][event['team']+'_units']=event['proposal']['after']
        new_ids=list(commands.resolve_units(shadow))
        expected_map={i:new_ids for i in old_ids.values()}
        expected_leaf={i:[forces.leaf_key(event['team'],u) for u in event['proposal']['after']] for i in old_ids}
        if value['command_map']!=expected_map or value['leaf_map']!=expected_leaf:
            raise ValueError('命令或组织映射不符合原始身份生成规则')
        # Recompute every public command mapping from recorded source IDs and
        # the canonical command ID generator; do not trust a resealed map.
        source=continuity._undo_latest(world,event) if event is world['formation_registry']['transactions'][-1] and (event['turn'],event['elapsed_seconds'])==(world['mission']['turn'],world['simulation_clock']['elapsed_seconds']) else None
        if source is not None:
            old_cs=copy.deepcopy(value['before_command_state'])
            prefix=events[:len(events)-1]
            if prefix:old_cs['formation_handoffs']=copy.deepcopy(prefix)
            old={**_detached(session),'war_state':source,'command_state':old_cs,'force_organization':copy.deepcopy(value['before_organization'])}
            expected,mapping,leafs=_derive(old,world)
            if value['command_map']!=mapping or value['leaf_map']!=leafs:raise ValueError('命令或组织身份映射与转换前态不一致')
            # Normal subsequent queue edits may occur at the same physical
            # tick. The admission revision itself must still be exact.
            if cs['revision']==value['after_command_revision']:
                expected_cs=copy.deepcopy(expected['command_state']);expected_cs['formation_handoffs']=copy.deepcopy(events[:-1])
                if _receipt(cs)!=missions.digest(expected_cs) or value['after_command_hash']!=missions.digest(expected_cs):raise ValueError('候选命令接续不是从记录前态独立推导')
            if forces.state(session)['revision']==value['before_organization']['revision']+1:
                if session.get('force_organization')!=expected['force_organization'] or missions.digest(expected['force_organization'])!=value['after_organization_hash']:raise ValueError('候选任务群接续不一致')
    return True


def validate(session):
    world=session['war_state'];missions.validate(world,allow_prepared=True)
    if session['turn_count']!=world['mission']['turn'] or session['time_step']!=world['mission']['definition']['time_step']:
        raise ValueError('会话回合或步长与候选世界不一致')
    validate_history(session);forces.validate(session);commands.validate_saved(session,check_handoff=False)
    return True


def prepare(session,proposal,*,team):
    if session['war_state'].get('formation_registry'):validate(session)
    else:
        missions.validate(session['war_state']);commands.validate_saved(session);forces.validate(session)
    value=continuity.prepare(session['war_state'],proposal,team=team)
    after,mapping,leaves=_derive(session,value['world']);cs=after['command_state'];org=after['force_organization']
    cs.setdefault('formation_handoffs',[])
    event=dict(version=VERSION,registry_revision=value['revision'],turn=session['turn_count'],command_map=mapping,leaf_map=leaves,
        before_command_state=_base(commands.state(session)),before_organization=forces.state(session),
        after_command_revision=cs['revision'],after_command_hash=missions.digest(cs),after_organization_hash=missions.digest(org))
    cs['formation_handoffs'].append(event);validate(after)
    return dict(session=after,command_map=mapping,leaf_map=leaves,runtime_admitted=False,ownership=value['ownership'],
        continuity=value['continuity'],session_continuity=dict(version=VERSION,commands_prepared=True,organization_prepared=True,
            converted_source_commands=len(mapping),candidate_command_identities=len(next(iter(mapping.values()))),
            active_tasks=sum('identity_origin' in r.get('execution',{}) and r['execution']['status'] not in tasks.TERMINAL for r in cs.get('task_plans',{}).values()),
            agent_sessions_cloned=False,physics_executed=False,runtime_admitted=False),
        scope='会话命令和任务候选；尚未提交、执行或重建平台')


@contextmanager
def command_validation(session):
    """Internal legality-only scope; never a platform/physics authorization."""
    validate(session)
    with missions._prepared_validation(session['war_state']):yield


def command_probe(session):
    with command_validation(session):return commands.prepare(session)
