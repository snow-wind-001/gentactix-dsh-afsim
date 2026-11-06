"""Exclusive commitments rooted in the existing frozen initial state.

Intervals identify accounting shares, not individual soldiers or weapon serials.
Replay derives the active identity reference; there is no second mutable world
or cached roster. Staging is detached until all process contracts can migrate.
"""
import copy
from fractions import Fraction
import math

from . import formation_conversion as conversion, missions

VERSION='formation-ownership-1'
UNIT_IDENTITY=(*conversion.IDENTITY,'type','speed','attack_range','ground_control_radius_km',
    'supply_node_id','parameter_sources','calculation_unit_id','formation_part','runtime_allocation',
    'historical_reference','exercise_reference','source_historical_unit_id')


def _identity(unit):
    return unit.get('calculation_unit_id') or unit.get('historical_unit_id') or unit.get('exercise_unit_id') or unit['name']


def key(team,unit):
    return missions.digest([team,_identity(unit)])


def _projection(unit):
    return {**{k:copy.deepcopy(unit[k]) for k in UNIT_IDENTITY if k in unit},
        'personnel_reference':{k:unit['personnel'][k] for k in ('committed','source') if k in unit['personnel']},
        'equipment_reference':[{k:e[k] for k in ('category','name','committed','source') if k in e} for e in unit['equipment']],
        'formation_reference':{k:unit['formation'][k] for k in ('role','motorized','source') if k in unit['formation']}}


def _intervals(values):
    """Canonical half-open shares, with overlap always rejected."""
    if not isinstance(values,list):raise ValueError('归属区间须为列表')
    result=[]
    for row in sorted(values):
        if (not isinstance(row,list) or len(row)!=2 or any(type(x) is not int for x in row)
                or not 0<=row[0]<row[1]):raise ValueError('归属区间须为非空整数半开区间')
        if result and row[0]<result[-1][1]:raise ValueError('人员或装备归属区间重复')
        if result and row[0]==result[-1][1]:result[-1][1]=row[1]
        else:result.append(list(row))
    return result


def _count(intervals):return sum(b-a for a,b in intervals)


def _take(intervals,count):
    taken=[];remaining=[]
    for start,end in intervals:
        amount=min(count,end-start)
        if amount:taken.append([start,start+amount])
        if start+amount<end:remaining.append([start+amount,end])
        count-=amount
    if count:raise ValueError('分配超出唯一归属容量')
    return taken,remaining


def _seed(world):
    spec=world['mission']['definition']
    if missions.digest(spec)!=world['mission']['definition_hash']:
        raise ValueError('根账来源定义与摘要不一致')
    initial=spec['initial_state'];roots={};active={}
    for team,unit in missions.units(initial):
        identity=key(team,unit)
        if identity in active:raise ValueError('初态执行身份重复，不能建立唯一归属')
        if unit.get('runtime_allocation'):raise ValueError('根账不能来自已转换分队的伪初态')
        part=unit.get('formation_part')
        scale=Fraction(part['numerator'],part['denominator']) if part else Fraction(1)
        equipment={e['category']:e['committed'] for e in unit['equipment']}
        committed=unit['personnel']['committed']
        if committed<1:raise ValueError('唯一根账需要明确正数投入，不能补造缺载兵额')
        roots[identity]=dict(team=team,origin_id=_identity(unit),historical_unit_id=unit.get('historical_unit_id'),
            committed=committed,equipment=equipment,scale=scale)
        ownership={identity:dict(personnel=[[0,committed]],equipment={c:[[0,n]] if n else [] for c,n in equipment.items()})}
        active[identity]=dict(team=team,unit=copy.deepcopy(unit),ownership=ownership)
    return roots,active


def _combine(ownerships):
    result={}
    for ownership in ownerships:
        for root,row in ownership.items():
            target=result.setdefault(root,dict(personnel=[],equipment={c:[] for c in row['equipment']}))
            target['personnel'].extend(copy.deepcopy(row['personnel']))
            if set(target['equipment'])!=set(row['equipment']):raise ValueError('分类装备归属字段不一致')
            for c,intervals in row['equipment'].items():target['equipment'][c].extend(copy.deepcopy(intervals))
    for row in result.values():
        row['personnel']=_intervals(row['personnel'])
        row['equipment']={c:_intervals(v) for c,v in row['equipment'].items()}
    return result


def _scale(roots,ownership):
    return sum((roots[r]['scale']*Fraction(_count(row['personnel']),roots[r]['committed'])
                for r,row in ownership.items()),Fraction())


def _check_unit(roots,record,unit):
    if _projection(unit)!=_projection(record['unit']):raise ValueError('执行身份、投入或固定参数与归属登记不一致')
    # The live ledger also validates later movement. Operation admission is
    # checked separately by verify_proposal and must not prohibit that movement.
    conversion._check(unit,for_reorganization=False)
    ownership=record['ownership']
    if unit['personnel']['committed']!=sum(_count(r['personnel']) for r in ownership.values()):
        raise ValueError('人员投入与唯一归属容量不一致')
    for e in unit['equipment']:
        if e['committed']!=sum(_count(r['equipment'][e['category']]) for r in ownership.values()):
            raise ValueError('分类装备投入与唯一归属容量不一致')
    metadata=unit.get('runtime_allocation')
    if metadata:
        expected={roots[r]['origin_id']:dict(committed=_count(row['personnel']),
            resource_scale=float(roots[r]['scale']*Fraction(_count(row['personnel']),roots[r]['committed'])),
            historical_unit_id=roots[r]['historical_unit_id']) for r,row in ownership.items() if row['personnel']}
        actual=metadata.get('origins')
        if not isinstance(actual,dict) or set(actual)!=set(expected):raise ValueError('根账来源身份与唯一归属不一致')
        for identity,wanted in expected.items():
            row=actual[identity]
            if (set(row)!=set(wanted) or row['committed']!=wanted['committed']
                    or row['historical_unit_id']!=wanted['historical_unit_id']
                    or not math.isclose(row['resource_scale'],wanted['resource_scale'],rel_tol=1e-12,abs_tol=1e-12)):
                raise ValueError('根账份额或资源尺度与唯一归属不一致')
    if not math.isclose(conversion.resource_scale(unit),float(_scale(roots,ownership)),rel_tol=1e-12,abs_tol=1e-12):
        raise ValueError('固定资源尺度不能在重编时重置')


def _complete(roots,active):
    names=[row['unit']['name'] for row in active.values()]
    if len(names)!=len(set(names)):raise ValueError('活动编组名称重复，不能建立含同名实体的执行集合')
    total=_combine([row['ownership'] for row in active.values()])
    if set(total)!=set(roots):raise ValueError('根账归属遗漏或额外生成')
    for identity,root in roots.items():
        row=total[identity]
        if row['personnel']!=[[0,root['committed']]]:raise ValueError('人员根账归属未完整覆盖')
        if row['equipment']!={c:[[0,n]] if n else [] for c,n in root['equipment'].items()}:
            raise ValueError('分类装备根账归属未完整覆盖')


def _allocate(roots,selected,after,team,kind):
    pool=_combine([r['ownership'] for r in selected]);result={}
    if kind=='merge':return {key(team,after[0]):pool}
    # Origin counts come from the revalidated proposal. Equipment shares are
    # assigned independently; a truck is not a fractional number of soldiers.
    remaining=copy.deepcopy(pool)
    for unit in after:
        owned={r:dict(personnel=[],equipment={c:[] for c in row['equipment']}) for r,row in pool.items()}
        origins=unit['runtime_allocation']['origins']
        for root,row in remaining.items():
            wanted=origins.get(roots[root]['origin_id'],{}).get('committed',0)
            owned[root]['personnel'],row['personnel']=_take(row['personnel'],wanted)
        for e in unit['equipment']:
            count=e['committed'];category=e['category']
            for root,row in remaining.items():
                amount=min(count,_count(row['equipment'][category]));count-=amount
                owned[root]['equipment'][category],row['equipment'][category]=_take(row['equipment'][category],amount)
            if count:raise ValueError('分类装备归属容量不足')
        result[key(team,unit)]={r:row for r,row in owned.items() if row['personnel'] or any(row['equipment'].values())}
    if any(row['personnel'] or any(row['equipment'].values()) for row in remaining.values()):
        raise ValueError('转换后仍有未分配的人员或装备归属')
    return result


def _advance(world,roots,active,event,seen,operations,revision,last_at):
    fields={'revision','team','turn','elapsed_seconds','proposal','ownership_after'}
    if isinstance(event,dict) and 'process_handoff' in event:
        fields.add('process_handoff')
        from . import formation_continuity
        formation_continuity.check_receipt(event)
    if not isinstance(event,dict) or set(event)!=fields:raise ValueError('归属转换事务字段非法')
    team=event['team'];proposal=event['proposal'];at=(event['turn'],event['elapsed_seconds'])
    if (type(event['revision']) is not int or event['revision']!=revision or team not in ('red','blue')
            or any(type(n) is not int or n<0 for n in at) or any(now<previous for now,previous in zip(at,last_at))
            or event['turn']>world['mission']['turn'] or event['elapsed_seconds']>world['simulation_clock']['elapsed_seconds']):
        raise ValueError('归属事务序号、时钟或阵营非法')
    conversion.verify_proposal(proposal)
    from . import combat_effects
    if proposal['request'].get('damage_quantum')!=combat_effects.reference(world).get('damage_quantum'):
        raise ValueError('转换毁伤精度与本局冻结参照不一致')
    operation=proposal['request']['operation_id']
    if operation in operations:raise ValueError('转换操作身份重复，不能重放')
    spec=world['mission']['definition']
    mode='synthetic' if spec.get('historical_synthetic') or spec.get('synthetic_configuration') else 'historical'
    if proposal['kind']=='split':
        request=proposal['request']
        if request['product_mode']!=mode:raise ValueError('转换用途与冻结想定不一致，不能绕过历史约束')
        snapshot=request['historical_snapshot']
        if (mode=='historical' or snapshot is not None) and snapshot!=world.get('historical_initial'):
            raise ValueError('历史下级必须绑定本局冻结来源，不能替换资料版本')
    before=proposal['before'];after=proposal['after'];old=[key(team,u) for u in before];new=[key(team,u) for u in after]
    if len(set(old))!=len(old) or any(identity not in active for identity in old):
        raise ValueError('转换前态身份未知或已退役，不能再次消费')
    for identity,unit in zip(old,before):_check_unit(roots,active[identity],unit)
    if len(set(new))!=len(new) or any(identity in seen for identity in new):
        raise ValueError('转换新身份重复或已使用，不能复制改名后再次登记')
    owned=_allocate(roots,[active[i] for i in old],after,team,proposal['kind'])
    if event['ownership_after']!=owned:raise ValueError('人员或分类装备唯一归属分配不符，重新摘要不能授权')
    replacements={key(team,u):dict(team=team,unit=copy.deepcopy(u),ownership=owned[key(team,u)]) for u in after}
    for row in replacements.values():_check_unit(roots,row,row['unit'])
    result={};inserted=False
    for identity,row in active.items():
        if identity in old:
            if not inserted:result.update(replacements);inserted=True
        else:result[identity]=row
    _complete(roots,result);seen.update(new);operations.add(operation)
    return result,at


def _replay(world,state):
    if (not isinstance(state,dict) or set(state)!={'version','definition_hash','transactions','state_hash'}
            or state['version']!=VERSION or state['definition_hash']!=world['mission']['definition_hash']
            or state['state_hash']!=missions.digest({k:v for k,v in state.items() if k!='state_hash'})
            or not isinstance(state['transactions'],list)):
        raise ValueError('归属登记版本、来源或摘要非法')
    roots,active=_seed(world);seen=set(active);operations=set();last=(0,0)
    for i,event in enumerate(state['transactions'],1):active,last=_advance(world,roots,active,event,seen,operations,i,last)
    return roots,active


def validate(world):
    """Check registered current leaves; absent legacy data stays absent."""
    state=world.get('formation_registry')
    if state is None:
        if any(u.get('runtime_allocation') is not None for _,u in missions.units(world)):
            raise ValueError('运行中分配缺少唯一归属登记，不能信任单位自报尺度')
        return None
    roots,active=_replay(world,state);actual={}
    for team,u in missions.units(world):
        identity=key(team,u)
        if identity in actual:raise ValueError('活动执行身份重复')
        actual[identity]=(team,u)
    if set(actual)!=set(active):raise ValueError('活动执行集合与唯一归属登记不一致')
    for identity,(team,u) in actual.items():_check_unit(roots,active[identity],u)
    return dict(revision=len(state['transactions']),root_count=len(roots),active={k:copy.deepcopy(row['ownership']) for k,row in active.items()})


def reference(world):
    """Detached immutable identity reference for later validator integration."""
    if world.get('formation_registry') is None:
        validate(world)
        return copy.deepcopy(missions.units(world['mission']['definition']['initial_state']))
    validate(world);_,active=_replay(world,world['formation_registry'])
    return [(row['team'],copy.deepcopy(row['unit'])) for row in active.values()]


def origin_templates(world,unit,team=None):
    """Resolve frozen origin templates of an already validated execution unit.

    Ownership is proved by validate at the world boundary. This accessor only
    resolves the immutable keys; it does not turn self-reported metadata into
    authority. Like formation_parts.scale, execution callers validate first.
    """
    if team is None:
        team=next((t for t,u in missions.units(world) if u is unit or u['name']==unit['name']),None)
    original={_identity(u):u for t,u in missions.units(world['mission']['definition']['initial_state']) if t==team}
    metadata=unit.get('runtime_allocation')
    identities=list(metadata['origins']) if metadata else [_identity(unit)]
    if not identities or any(identity not in original for identity in identities):
        raise ValueError('执行单位缺少同阵营冻结根身份')
    return [original[identity] for identity in identities]


def descendants(world,identity,team):
    """Resolve an immutable original selector into disjoint current leaves."""
    original={_identity(u) for t,u in missions.units(world['mission']['definition']['initial_state']) if t==team}
    if identity not in original:raise ValueError('目标选择器不在冻结原始身份中')
    return [u for t,u in missions.units(world) if t==team and
        identity in {_identity(origin) for origin in origin_templates(world,u,t)}]


def commitment_scale(world,unit,team):
    state=world.get('formation_registry')
    roots,active=_replay(world,state) if state is not None else _seed(world)
    identity=key(team,unit)
    if identity not in active:raise ValueError('资源尺度引用未知活动身份')
    _check_unit(roots,active[identity],unit)
    return float(_scale(roots,active[identity]['ownership']))


def stage(world,proposal,*,team):
    """Prepare an audited roster candidate. Never mutate or admit the world."""
    validate(world)
    old=world.get('formation_registry')
    state=copy.deepcopy(old) if old is not None else dict(version=VERSION,definition_hash=world['mission']['definition_hash'],transactions=[])
    if old is None:
        roots,active=_seed(world)
        for side,unit in missions.units(world):
            identity=key(side,unit)
            if identity not in active:raise ValueError('当前身份不在冻结初态')
            _check_unit(roots,active[identity],unit)
    else:roots,active=_replay(world,old)
    conversion.verify_proposal(proposal)
    for unit in proposal['before']:
        current=next((u for side,u in missions.units(world) if side==team and key(side,u)==key(team,unit)),None)
        if current!=unit:raise ValueError('转换前态与当前权威实态不一致，请重新预览')
    selected=[active[key(team,u)] for u in proposal['before']]
    owned=_allocate(roots,selected,proposal['after'],team,proposal['kind'])
    event=dict(revision=len(state['transactions'])+1,team=team,turn=world['mission']['turn'],
        elapsed_seconds=world['simulation_clock']['elapsed_seconds'],proposal=copy.deepcopy(proposal),ownership_after=owned)
    state['transactions'].append(event);state['state_hash']=missions.digest({k:v for k,v in state.items() if k!='state_hash'})
    roots,new_active=_replay(world,state)
    candidate=copy.deepcopy(world);candidate['formation_registry']=state
    for side in ('red','blue'):candidate[side+'_units']=[copy.deepcopy(row['unit']) for row in new_active.values() if row['team']==side]
    # Unchanged actors use their CURRENT state, not the immutable audit template.
    replaced={key(team,u) for u in proposal['before']}
    for side,unit in missions.units(world):
        identity=key(side,unit)
        if identity not in replaced:
            target=next(i for i,u in enumerate(candidate[side+'_units']) if key(side,u)==identity)
            candidate[side+'_units'][target]=copy.deepcopy(unit)
    view=validate(candidate)
    return dict(world=candidate,runtime_admitted=False,ownership_verified=True,revision=view['revision'],
        identity_map={identity:list(owned) for identity in replaced},
        ownership=dict(version=VERSION,verified=True,current_revision=len(state['transactions'])-1,
            candidate_revision=view['revision'],source_roots=view['root_count'],
            selected_roots=len({r for identity in replaced for r in active[identity]['ownership']}),
            current_entities=len(missions.units(world)),candidate_entities=len(missions.units(candidate)),
            scope='候选人员及分类装备份额互斥，根资源尺度不变；不是已提交执行身份'),
        scope='唯一归属及身份参考候选；命令、任务、目标和平台迁移未完成，不提交战局')
