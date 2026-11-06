"""Audited zero-time handoff of identities and process metadata.

This prepares a complete world for validation, never a session/command/platform
commit. It does not advance physics, score goals, or create historical facts.
"""
import copy
import re

from . import formation_registry as registry, formation_conversion as conversion, missions
from .formation_runtime import physical_digest

LEGACY_VERSION='formation-process-handoff-1'
PREVIOUS_VERSION='formation-process-handoff-2'
VERSION='formation-process-handoff-3'
METADATA=('unit_participation','campaign','campaign_plan')


def _metadata(world):return {k:copy.deepcopy(world[k]) for k in METADATA if k in world}


def check_receipt(event):
    value=event.get('process_handoff')
    fields={'version','source_world_digest','after_world_digest','source_registry_kind','unit_order_before','before_metadata','after_metadata_hashes'}
    if (not isinstance(value,dict) or set(value)!=fields or value['version'] not in (LEGACY_VERSION,PREVIOUS_VERSION,VERSION)
            or value['source_registry_kind'] not in ('missing','null','ledger')):
        raise ValueError('编组过程接续回执字段或版本非法')
    for k in ('source_world_digest','after_world_digest'):
        if not isinstance(value[k],str) or not re.fullmatch('[a-f0-9]{64}',value[k]):raise ValueError('过程接续世界摘要非法')
    order=value['unit_order_before']
    if not isinstance(order,dict) or set(order)!={'red','blue'}:raise ValueError('过程接续前名单不完整')
    for ids in order.values():
        if (not isinstance(ids,list) or any(not isinstance(i,str) or not re.fullmatch('[a-f0-9]{64}',i) for i in ids)
                or len(ids)!=len(set(ids))):
            raise ValueError('过程接续前名单身份非法')
    if (not isinstance(value['before_metadata'],dict) or set(value['before_metadata'])-set(METADATA)
            or any(v is not None and not isinstance(v,dict) for v in value['before_metadata'].values())
            or not isinstance(value['after_metadata_hashes'],dict)
            or set(value['after_metadata_hashes'])!=set(value['before_metadata'])
            or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in value['after_metadata_hashes'].values())):
        raise ValueError('参与、战役或目标接续记录不完整')


def _origin(event,metadata):
    from . import force_organization
    ids=[force_organization.leaf_key(event['team'],u) for u in event['proposal']['before']]
    rows=(metadata.get('unit_participation') or {}).get('actors',{})
    return dict(registry_revision=event['revision'],source_actor_ids=ids,
        inherited_counts={i:rows.get(i,{}).get('transition_count') for i in ids},
        counter_scope='own_since_identity_created; inherited counts may share ancestors and must not be summed')


def actor_origin(world,unit,team):
    if not unit.get('runtime_allocation'):return None
    identity=registry.key(team,unit)
    for event in reversed((world.get('formation_registry') or {}).get('transactions',[])):
        if event['team']==team and any(registry.key(team,u)==identity for u in event['proposal']['after']):
            value=event.get('process_handoff')
            if value is None:raise ValueError('执行身份缺少参与过程接续记录')
            return _origin(event,value['before_metadata'])
    raise ValueError('参与状态引用未登记的转换身份')


def _participation(before,after,event):
    from . import force_organization, unit_participation as part
    state=before.get('unit_participation')
    if state is None:return
    value=copy.deepcopy(state);old_ids=[force_organization.leaf_key(event['team'],u) for u in event['proposal']['before']]
    rows=[state['actors'][i] for i in old_ids];statuses={r['status'] for r in rows}
    if len(statuses)!=1:raise ValueError('合并前参与状态须一致，不能借改名提前入场或返场')
    for identity in old_ids:value['actors'].pop(identity)
    origin=_origin(event,_metadata(before))
    for u in event['proposal']['after']:
        identity=force_organization.leaf_key(event['team'],u)
        value['actors'][identity]=dict(team=event['team'],name=u['name'],status=rows[0]['status'],pending=None,
            transition_count=0,status_since=max(r['status_since'] for r in rows),last_transition=None,
            conversion_origin=copy.deepcopy(origin))
    # The original physical receipts remain in before_metadata. A bookkeeping
    # operation emits no new physical transition, including inherited returns.
    value['last_changes']=[r for r in value['last_changes'] if r['entity_id'] not in old_ids]
    part._seal(value);after['unit_participation']=value


def _campaign(before,after,event,*,legacy=False,envelope=True):
    state=before.get('campaign')
    if state is None:return
    value=copy.deepcopy(state);rows=[state['actors'][u['name']] for u in event['proposal']['before']]
    for u in event['proposal']['before']:value['actors'].pop(u['name'])
    captures=sum(r['captured_this_turn'] for r in rows)
    counts=conversion._apportion(captures,[u['personnel'].get('captured',0) for u in event['proposal']['after']])
    from . import campaign
    for u,count in zip(event['proposal']['after'],counts):
        origins=registry.origin_templates(after,u,event['team'])
        if len(origins)!=1:raise ValueError('战役过程接续暂不支持跨根历史改编')
        original=before['mission']['definition']['initial_state']['campaign']['actors'][origins[0]['name']]
        value['actors'][u['name']]=dict(active=campaign.release_seconds(after,u)==0,
            fortification_integrity=min(r['fortification_integrity'] for r in rows),
            base_protection=original['base_protection'],
            base_entrenchment=original['base_entrenchment'] if legacy else min(r['base_entrenchment'] for r in rows),captured_this_turn=count)
        if envelope and not legacy:
            components=campaign.fortification_envelope(rows)
            if len(components)>1:value['actors'][u['name']]['fortification_components']=components
    after['campaign']=value


def _goals(before,after):
    from . import campaign_plan as goals
    if goals.definition(before) is None:
        # Reuse the legacy evaluator on disposable copies. Its prospective
        # score must agree, but neither copy is ever returned or committed.
        a=copy.deepcopy(before);b=copy.deepcopy(after)
        missions.evaluate(a);missions.evaluate(b)
        if a['mission']!=b['mission'] or (a.get('campaign') or {}).get('objective')!=(b.get('campaign') or {}).get('objective'):
            raise ValueError('转换改变了目标物理观察，旧目标也不能仅靠重绑定绕过')
        return
    goals.validate_state(before)
    if goals.definition(before)!=goals.definition(after):raise ValueError('接续不能替换冻结目标图')
    old_index=goals._units(before);new_index=goals._units(after)
    for node in goals.definition(before)['nodes']:
        if goals._predicate(before,node,old_index)!=goals._predicate(after,node,new_index):
            raise ValueError('转换改变了目标物理观察，不能仅重绑定；须采用后续有代价的重组规则或先完成同地集结')
    state=copy.deepcopy(before['campaign_plan']);state['input_hash']=goals._input_hash(after);goals._seal(state)
    # No evaluator invocation against the authoritative candidate, phase
    # settlement, completion, hold-time increment, or physical repair occurs.
    after['campaign_plan']=state


def _derive(before,proposal,team,*,legacy=False,envelope=True):
    from . import unit_participation as part
    for unit in proposal['before']:
        view=part.unit_view(before,unit,team)
        if view['pending'] or view['status'] in ('staging','withdrawing','returning'):
            raise ValueError('尚未到场或在途参与状态须先完整交接，不能通过分合兵清空请求')
    value=registry.stage(before,proposal,team=team);after=value['world'];event=after['formation_registry']['transactions'][-1]
    _participation(before,after,event);_campaign(before,after,event,legacy=legacy,envelope=envelope);_goals(before,after)
    return value


def _seal(state):state['state_hash']=missions.digest({k:v for k,v in state.items() if k!='state_hash'})


def _without_latest_receipt(world):
    value=copy.deepcopy(world);state=value['formation_registry'];state['transactions'][-1].pop('process_handoff',None);_seal(state)
    return value


def _undo_latest(world,event):
    value=copy.deepcopy(world);receipt=event['process_handoff'];team=event['team']
    new={registry.key(team,u) for u in event['proposal']['after']}
    current={(t,registry.key(t,u)):u for t,u in missions.units(value) if not (t==team and registry.key(t,u) in new)}
    current.update({(team,registry.key(team,u)):copy.deepcopy(u) for u in event['proposal']['before']})
    expected={(t,i) for t,ids in receipt['unit_order_before'].items() for i in ids}
    if set(current)!=expected:raise ValueError('过程接续前后名单不能完整逆向对应')
    for t in ('red','blue'):value[t+'_units']=[current[t,i] for i in receipt['unit_order_before'][t]]
    state=value['formation_registry'];state['transactions'].pop()
    kind=receipt['source_registry_kind']
    if kind=='missing':value.pop('formation_registry')
    elif kind=='null':value['formation_registry']=None
    else:_seal(state)
    for field in METADATA:
        if field in receipt['before_metadata']:value[field]=copy.deepcopy(receipt['before_metadata'][field])
        else:value.pop(field,None)
    return value


def validate(world):
    state=world.get('formation_registry')
    if not state:return
    for event in state['transactions']:
        if 'process_handoff' not in event:raise ValueError('归属候选尚未完成参与、战役和目标观察接续')
        check_receipt(event)
    if not state['transactions']:return
    event=state['transactions'][-1]
    if (event['turn'],event['elapsed_seconds'])!=(world['mission']['turn'],world['simulation_clock']['elapsed_seconds']):return
    receipt=event['process_handoff']
    if physical_digest(_without_latest_receipt(world))!=receipt['after_world_digest']:
        raise ValueError('当前物理或目标观察与零时间接续回执不一致')
    before=_undo_latest(world,event)
    if physical_digest(before)!=receipt['source_world_digest']:raise ValueError('过程接续前态不能由当前世界和冻结记录重建')
    expected=_derive(before,event['proposal'],event['team'],legacy=receipt['version']==LEGACY_VERSION,
        envelope=receipt['version']==VERSION)['world']
    expected_metadata=_metadata(expected)
    if ({k:missions.digest(v) for k,v in expected_metadata.items()}!=receipt['after_metadata_hashes']
            or expected_metadata!=_metadata(world)):
        raise ValueError('过程状态接续不是从已记录前态独立推导的结果')


def prepare(world,proposal,*,team):
    """Fully check a detached world; commands/tasks/platforms stay unadmitted."""
    missions.validate(world,allow_prepared=True)
    value=_derive(world,proposal,team);after=value['world'];event=after['formation_registry']['transactions'][-1]
    receipt=dict(version=VERSION,source_world_digest=physical_digest(world),after_world_digest=physical_digest(after),
        source_registry_kind='missing' if 'formation_registry' not in world else 'null' if world['formation_registry'] is None else 'ledger',
        unit_order_before={t:[registry.key(t,u) for side,u in missions.units(world) if side==t] for t in ('red','blue')},
        before_metadata=_metadata(world),after_metadata_hashes={k:missions.digest(v) for k,v in _metadata(after).items()})
    event['process_handoff']=receipt;_seal(after['formation_registry'])
    missions.validate(after,allow_prepared=True)
    value['continuity']=dict(version=VERSION,world_prepared=True,clock_advanced=False,goals_evaluated=False,
        physics_executed=False,participation_history_preserved=True,command_task_platform_admitted=False)
    return value
