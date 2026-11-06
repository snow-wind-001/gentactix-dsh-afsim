"""Source-bound operational inputs and read-only guards; never execute combat.

AFSIM owns physical process effects when selected; DSH effects are validated
estimates. Legacy native goals and the optional host goal DAG have separate
provenance. This module validates process inputs and exposes their scope.
"""
import copy
from datetime import datetime
import math

VERSION='combined-operation-1'
DEFENSIVE_DELAY='defensive-delay-1'
WAITING_ACTIONS=('hold','resupply','restore_comms','recon')
FORTIFICATION_COMPONENT_LIMIT=101


def fortification_components(row):
    """Copy latent defensive facets; these are not units or additive stocks."""
    return copy.deepcopy(row.get('fortification_components') or [{
        'base_entrenchment':row['base_entrenchment'],
        'fortification_integrity':row['fortification_integrity']}])


def fortification_envelope(rows):
    """Canonical metadata join for common future construction/shell erosion.

    A facet dominated in both base and integrity can never become the weaker
    one under their monotone Native operations. Do not mix minima from facets.
    """
    pairs=set()
    for row in rows:
        for part in fortification_components(row):
            _fields(part,{'base_entrenchment','fortification_integrity'},'工事侧面')
            _number(part['base_entrenchment'],0,100,'工事侧面基准')
            _number(part['fortification_integrity'],0,100,'工事侧面完整度')
            pairs.add((float(part['base_entrenchment']),float(part['fortification_integrity'])))
    result=[];lowest=101
    for base,integrity in sorted(pairs):
        if integrity>=lowest:continue
        result.append(dict(base_entrenchment=base,fortification_integrity=integrity));lowest=integrity
    if not result or len(result)>FORTIFICATION_COMPONENT_LIMIT:raise ValueError('工事侧面摘要为空或超出支持范围')
    return result


def _validate_fortification_components(row):
    parts=row['fortification_components']
    if not isinstance(parts,list) or not 2<=len(parts)<=FORTIFICATION_COMPONENT_LIMIT:
        raise ValueError('工事侧面须为2至101项有界状态，不是新增部队或工事数量')
    for part in parts:
        _fields(part,{'base_entrenchment','fortification_integrity'},'工事侧面')
        _number(part['base_entrenchment'],0,100,'工事侧面基准')
        _number(part['fortification_integrity'],0,100,'工事侧面完整度')
    if (row['base_entrenchment']!=min(p['base_entrenchment'] for p in parts)
            or row['fortification_integrity']!=min(p['fortification_integrity'] for p in parts)):
        raise ValueError('工事侧面与摘要基准/完整度不一致')


def required(snapshot,parameters=None):
    from . import campaign_scope
    if parameters is not None and campaign_scope.enabled(parameters):return True
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    return any(r['kind']=='combined_operation' for r in phase.get('process_requirements',[]))


def template(snapshot,identities):
    note='待填写有来源的过程范围；入场时点、工事效能和目标阈值是独立计算估计，不是已核实战果。'
    return {'version':VERSION,
        'arrivals':{i:{'not_before':None,'assumption':note} for i in identities},
        'fortifications':{i:{'integrity':None,'degradation_per_shell':None,'assumption':note} for i in identities},
        'surrender':{'enabled':None,'range_m':None,'suppression_threshold':None,'ammo_threshold':None,'assumption':note},
        'objective':{'relief_regions':None,'min_force_fraction':None,'assumption':note},'assumption':note}


def _fields(value,keys,label):
    if not isinstance(value,dict):raise ValueError(label+'必须为对象')
    missing=set(keys)-set(value);extra=set(value)-set(keys)
    if missing or extra:
        raise ValueError(label+'字段不完整或越界；缺少：'+','.join(sorted(missing))+'；多余：'+','.join(sorted(extra)))


def _text(value,label):
    if not isinstance(value,str) or not value.strip():raise ValueError(label+'必须说明估计依据')


def _number(value,low,high,label):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f'{label}必须为{low:g}至{high:g}的有限数值')


def _time(value,label):
    try:result=datetime.fromisoformat(value)
    except (ValueError,TypeError) as exc:raise ValueError(label+'必须为明确日期时间') from exc
    if result.tzinfo is not None:raise ValueError(label+'使用已说明的当地时间，不混入时区偏移')
    return result


def _schedule_fields(row, label, *, parent=False):
    optional = ({'parts'} if parent and isinstance(row, dict) and 'parts' in row else set())
    if isinstance(row, dict) and ('event_kind' in row or 'reference_id' in row):
        optional |= {'event_kind', 'reference_id'}
    _fields(row, {'not_before', 'assumption'} | optional, label)
    if 'event_kind' in row:
        from .historical_constraints import EVENT_KINDS
        if row['event_kind'] not in EVENT_KINDS:
            raise ValueError(label+'时点类型须为departure（启程）或battlefield_entry（前沿入场）')
        _text(row['reference_id'], label+'接敌参考')


def _region(value,label,area):
    _fields(value,{'center','radius_km'},label)
    _fields(value['center'],{'lat','lng'},label+'中心')
    _number(value['center']['lat'],-90,90,label+'纬度');_number(value['center']['lng'],-180,180,label+'经度')
    _number(value['radius_km'],.01,20,label+'半径')
    from . import missions
    if missions.distance(value['center'],area['center'])+value['radius_km']>area['radius_km']+.001:
        raise ValueError(label+'超出计算地域')


def validate_parameters(snapshot,parameters):
    from . import campaign_scope
    value=parameters.get('campaign')
    if not required(snapshot,parameters):
        if value is not None:raise ValueError('当前来源阶段未声明完整联合作战需求，不能迁入其他战役过程')
        return None
    if value is None:raise ValueError('完整战役必须绑定入场、工事、受降与多方向目标，不能退回局部占点模板')
    _fields(value,{'version','arrivals','fortifications','surrender','objective','assumption'}|
        ({'objective_policy'} if 'objective_policy' in value else set()),'战役过程')
    if 'objective_policy' in value:
        if (value['objective_policy']!=DEFENSIVE_DELAY or parameters['goal']['profile']!='delay'
                or not campaign_scope.enabled(parameters)):
            raise ValueError('防御迟滞规则版本须为defensive-delay-1，且绑定会战范围与delay目标')
        if parameters.get('campaign_plan'):
            raise ValueError('campaign.objective_policy=defensive-delay-1不能与campaign_plan目标图同时使用；'
                '保留目标图时从campaign移除此可选字段（不要移入campaign.objective），迟滞条件由目标节点表达。')
    if value['version']!=VERSION:raise ValueError('战役过程版本不支持')
    _text(value['assumption'],'战役过程')
    ids=set(parameters['actors']);start=_time(parameters['clock']['start'],'战役起点')
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    from . import campaign_scope
    end=campaign_scope.end_time(snapshot,parameters)
    _fields(value['arrivals'],ids,'部队入场')
    for identity,row in value['arrivals'].items():
        _schedule_fields(row,identity+'入场',parent=True)
        if not start<=_time(row['not_before'],identity+'入场')<=end:raise ValueError('入场时点超出本战役窗口：'+identity)
        _text(row['assumption'],identity+'入场')
        if 'parts' in row:
            if not isinstance(row['parts'],dict) or not row['parts']:
                raise ValueError(identity+' arrivals.parts必须为以分队ID为键的非空对象；各值仅含not_before和assumption，不是id条目的列表')
            partitions=parameters.get('partitions') or {}
            if not isinstance(partitions,dict):raise ValueError('分批入场必须引用有效分队配置')
            groups=partitions.get('groups',{})
            if not isinstance(groups,dict):raise ValueError('partitions.groups必须为以父单位ID为键的对象')
            group=groups.get(identity,{})
            if not isinstance(group,dict) or not isinstance(group.get('parts'),list) or not all(isinstance(p,dict) for p in group['parts']):
                raise ValueError('partitions.groups中对应父单位的互斥分队parts必须为列表，各项包含id；不能与arrivals.parts对象混淆')
            part_ids={p.get('id') for p in group['parts']}
            if set(row['parts'])-part_ids:
                raise ValueError('分批入场必须引用已配置的互斥计算分队，不能复制或虚构部队')
            for part,entry in row['parts'].items():
                _schedule_fields(entry,'分批入场')
                if not start<=_time(entry['not_before'],'分批入场')<=end:raise ValueError('分批入场超出战役窗口')
                _text(entry['assumption'],'分批入场')
    _fields(value['fortifications'],ids,'工事参数')
    for identity,row in value['fortifications'].items():
        _fields(row,{'integrity','degradation_per_shell','assumption'},identity+'工事')
        _number(row['integrity'],0,100,identity+'工事完整度')
        _number(row['degradation_per_shell'],0,100,identity+'每发工事损耗系数')
        _text(row['assumption'],identity+'工事')
    surrender=value['surrender'];_fields(surrender,{'enabled','range_m','suppression_threshold','ammo_threshold','assumption'},'受降')
    if type(surrender['enabled']) is not bool:raise ValueError('受降开关必须为布尔值')
    _number(surrender['range_m'],1,1000,'受降接近距离')
    _number(surrender['suppression_threshold'],0,100,'受降压制阈值')
    _number(surrender['ammo_threshold'],0,100,'受降弹药阈值');_text(surrender['assumption'],'受降')
    objective=value['objective'];_fields(objective,{'relief_regions','min_force_fraction','assumption'},'联合作战目标')
    transfer=phase.get('interaction',{}).get('kind')=='non_contact_transfer'
    if transfer:
        if (not campaign_scope.enabled(parameters) or parameters['goal'].get('termination_mode')!='objectives'
                or not parameters.get('campaign_plan') or surrender['enabled']):
            raise ValueError('非接敌会战转移须绑定目标完成制和目标图，不能配置虚构受降')
    allowed=('crossing','breakout') if transfer else ('assault','delay') if campaign_scope.enabled(parameters) else ('assault',)
    if parameters['goal']['profile'] not in allowed:raise ValueError('联合作战须使用攻点/区域控制或防御迟滞目标')
    town={'center':parameters['goal']['objective'],'radius_km':parameters['goal']['radius_km']}
    _region(town,'据点目标',parameters['area'])
    if transfer and objective['relief_regions']!=[]:
        raise ValueError('非接敌转移不配置虚构阻援区，应以目标图的到达、保存和资源条件评分')
    optional_regions=transfer or bool(parameters.get('campaign_plan'))or value.get('objective_policy')==DEFENSIVE_DELAY
    if not isinstance(objective['relief_regions'],list) or not (0 if optional_regions else 1)<=len(objective['relief_regions'])<=6:
        raise ValueError('完整战役必须单独定义1至6个阻援区域')
    for row in objective['relief_regions']:_region(row,'阻援区域',parameters['area'])
    _number(objective['min_force_fraction'],.001,1,'有生力量保持比例');_text(objective['assumption'],'联合作战目标')
    return copy.deepcopy(value)


def bind(snapshot,parameters):
    value=validate_parameters(snapshot,parameters)
    if value is not None:value['objective']['town']={'center':copy.deepcopy(parameters['goal']['objective']),
        'radius_km':parameters['goal']['radius_km']}
    return value


def definition(world):
    return world.get('mission',{}).get('definition',{}).get('campaign_definition')


def actor_key(unit):
    return unit.get('formation_part',{}).get('group_id',unit.get('historical_unit_id') or unit.get('exercise_unit_id'))


def source_actor_key(world,unit):
    """Resolve configuration through the frozen root, not a new child label."""
    if unit.get('runtime_allocation'):
        from . import formation_registry
        origins=formation_registry.origin_templates(world,unit)
        if len(origins)!=1:raise ValueError('战役配置接续需要唯一冻结根编组')
        unit=origins[0]
    return actor_key(unit)


def rebind_exercise(spec, baseline):
    """Bind an edited initial roster, never a running world's actual ledgers.

    Each exercise-only actor gets a distinct process key. Calculation parts keep
    their parent key but copy the schedule of their selected source part. This
    is an explicit input variant, not reinforcement or historical renaming.
    """
    from . import missions
    original = baseline['campaign_definition']
    source = {(team, u.get('calculation_unit_id', u.get('historical_unit_id'))): u
              for team, u in missions.units(baseline['initial_state'])}
    config = copy.deepcopy(original)
    config['arrivals'] = {}; config['fortifications'] = {}
    for team, unit in missions.units(spec['initial_state']):
        origin_id = unit.get('historical_reference', {}).get('id')
        origin = source.get((team, origin_id))
        if origin is None:
            raise ValueError('合成会战单位缺少同阵营冻结来源，不能猜测入场和工事参数')
        if not unit.get('formation_part') and not unit.get('historical_unit_id'):
            unit['exercise_unit_id'] = 'exercise.' + missions.digest({
                'team': team, 'name': unit['name'], 'basis_id': origin_id})[:24]
        key, origin_key = actor_key(unit), actor_key(origin)
        if key not in config['arrivals']:
            arrival = copy.deepcopy(original['arrivals'][origin_key]); arrival.pop('parts', None)
            config['arrivals'][key] = arrival
            config['fortifications'][key] = copy.deepcopy(original['fortifications'][origin_key])
        if unit.get('formation_part'):
            source_part = origin['formation_part']['part_id']
            if source_part in original['arrivals'][origin_key].get('parts', {}):
                config['arrivals'][key].setdefault('parts', {})[unit['formation_part']['part_id']] = copy.deepcopy(
                    schedule(original, origin))
    spec['campaign_definition'] = config
    world = spec['initial_state']
    world['campaign'] = initial_state(world, config, world['current_time'])
    if world['campaign'] != baseline['initial_state']['campaign']:
        world['campaign']['source'] = '合成演习过程估计；按所选基础编组继承入场与工事参数，新增身份不是历史增援'


def schedule(config,unit,*,world=None):
    if unit.get('runtime_allocation'):
        if world is None:raise ValueError('重编单位入场须解析本局冻结根身份')
        from . import formation_registry
        origins=formation_registry.origin_templates(world,unit)
        if len(origins)!=1:raise ValueError('跨根部队入场接续尚未支持')
        unit=origins[0]
    key=actor_key(unit)
    if key not in config['arrivals']:raise ValueError('战役部队缺少冻结的入场参数')
    row=config['arrivals'][key]
    return row.get('parts',{}).get(unit.get('formation_part',{}).get('part_id'),row)


def scheduled_time(config,unit,*,world=None):
    return schedule(config,unit,world=world)['not_before']


def schedule_metadata(config,unit,*,world=None):
    entry=schedule(config,unit,world=world)
    return {k:entry[k] for k in ('event_kind','reference_id') if k in entry}


def initial_state(world,config,start):
    actors={}
    for team in ('red','blue'):
        for unit in world[team+'_units']:
            key=actor_key(unit);fort=config['fortifications'][key]
            actors[unit['name']]={'active':_time(scheduled_time(config,unit),'入场')<=_time(start,'起点'),
                'fortification_integrity':fort['integrity'],'base_protection':unit['formation']['protection'],
                'base_entrenchment':unit['formation']['entrenchment'],'captured_this_turn':0}
    return {'version':VERSION,'source':'显式战役过程估计；原始档案缺载量不补造',
        'actors':actors,'objective':{'town_control':False,'relief_denied':False,'force_preserved':True},'turn':0}


def capture_target(world,order):
    value=definition(world)
    if value is None or not value['surrender']['enabled']:raise ValueError('本局未启用受降过程')
    index={u['name']:(t,u) for t in ('red','blue') for u in world[t+'_units']}
    team,actor=index[order['unit']];item=index.get(order.get('target'))
    if item is None or item[0]==team or item[1]['personnel']['current']<=0:
        raise ValueError('受降目标须为有可用人员的敌方单位')
    target=item[1];rule=value['surrender']
    from . import missions
    if missions.distance(actor,target)*1000>rule['range_m']+1:raise ValueError('尚未接近受降目标')
    from . import suppression_state
    if suppression_state.value(target)<rule['suppression_threshold'] and target['logistics']['ammo']>rule['ammo_threshold']:
        raise ValueError('目标尚未满足受降条件；不能无条件清空敌方人员')
    return target


def release_seconds(world,unit):
    value=definition(world)
    if value is None:return 0
    return max(0,(_time(scheduled_time(value,unit,world=world),'入场')-_time(world['current_time'],'当前计算时间')).total_seconds())


def check_order(world,order):
    if definition(world) is None:return
    index={u['name']:u for t in ('red','blue') for u in world[t+'_units']}
    unit=index[order['unit']]
    if release_seconds(world,unit)>0 and order['action'] not in WAITING_ACTIONS:
        raise ValueError('该部队尚处集结等待阶段，不能提前行动：'+unit['name'])
    target=index.get(order.get('target'))
    if target is not None and release_seconds(world,target)>0:
        raise ValueError('不能攻击尚未入场的后续部队：'+target['name'])
    if order['action']=='capture':capture_target(world,order)


def validate_state(world):
    spec=definition(world);state=world.get('campaign')
    if spec is None:
        if state is not None:raise ValueError('缺少冻结定义的战役状态')
        return
    if not isinstance(state,dict):raise ValueError('缺少完整战役过程状态')
    _fields({k:v for k,v in state.items() if k!='execution_source'}, {'version','source','actors','objective','turn'},'战役状态')
    if state['version']!=VERSION or state['turn']!=world['mission']['turn']:raise ValueError('战役状态版本或回合不一致')
    original=world['mission']['definition']['initial_state']['campaign']
    if state['source']!=original['source']:raise ValueError('战役过程来源不得改写为历史实测')
    units={u['name']:u for team in ('red','blue') for u in world[team+'_units']}
    _fields(state['actors'],units,'战役部队状态')
    for name,row in state['actors'].items():
        optional={'fortification_components'} if 'fortification_components' in row else set()
        _fields(row,{'active','fortification_integrity','base_protection','base_entrenchment','captured_this_turn'}|optional,name+'过程状态')
        if type(row['active']) is not bool or row['active']!=(release_seconds(world,units[name])==0):raise ValueError('战役部队入场标志与计算时钟不一致')
        _number(row['fortification_integrity'],0,100,'工事完整度')
        _number(row['base_protection'],0,1,'原始防护');_number(row['base_entrenchment'],0,100,'工事基准')
        if optional:_validate_fortification_components(row)
        from . import formation_registry
        origins=formation_registry.origin_templates(world,units[name])
        if len(origins)!=1:raise ValueError('战役基础参数尚不支持跨根重编')
        origin=original['actors'][origins[0]['name']]
        if row['base_protection']!=origin['base_protection']:raise ValueError('原始防护不能在回合中改写')
        # Native construction can raise this base during ordinary turns.
        # Zero-time conversion preserves it through its own handoff receipt.
        if type(row['captured_this_turn']) is not int or not 0<=row['captured_this_turn']<=min(units[name]['personnel']['casualties'],units[name]['personnel'].get('captured',0)):
            raise ValueError('本轮被俘数必须包含在累计减员中')
    _fields(state['objective'],{'town_control','relief_denied','force_preserved'},'战役目标状态')
    if any(type(v) is not bool for v in state['objective'].values()):raise ValueError('战役目标须为已计算的布尔标志')


def assess(world):
    """Read-only goal predicates for review/DSH validation, not battle effects."""
    spec=definition(world)
    if spec is None:return None
    from . import missions
    owner=missions.objective_team(world['mission']['definition']);threshold=world['mission']['definition']['combined_rules']['suppression_control_threshold']
    alive={team:[u for u in world[team+'_units'] if u['personnel']['current']>0 and release_seconds(world,u)==0]
           for team in ('red','blue')}
    opponent='blue' if owner=='red' else 'red'
    def holds(region):
        from . import suppression_state
        own=any(missions.distance(u,region['center'])<=region['radius_km'] and suppression_state.value(u)<threshold for u in alive[owner])
        enemy=any(missions.distance(u,region['center'])<=region['radius_km'] for u in alive[opponent])
        return own and not enemy
    troops=sum(u['personnel']['current'] for u in world[owner+'_units']);committed=sum(u['personnel']['committed'] for u in world[owner+'_units'])
    objective=spec['objective']
    return {'town_control':holds(objective['town']),
        'relief_denied':bool(objective['relief_regions']) and all(holds(r) for r in objective['relief_regions']),
        'force_preserved':troops>=committed*objective['min_force_fraction']}


def delay_assess(world):
    """Versioned read-only goal; future arrivals cannot satisfy survival."""
    spec=definition(world)
    if not spec or spec.get('objective_policy')!=DEFENSIVE_DELAY:return None
    from . import missions,formation_parts
    mission=world['mission']['definition'];owner=missions.objective_team(mission)
    opponent='blue' if owner=='red' else 'red'
    arrived=[u for u in world[owner+'_units'] if release_seconds(world,u)==0]
    committed=sum(u['personnel']['committed'] for u in arrived)
    current=sum(u['personnel']['current'] for u in arrived)
    survivors=sum(any(u['personnel']['current']>0 and release_seconds(world,u)==0 for u in members)
                  for members in formation_parts.buckets(world,owner))
    breached=any(u['personnel']['current']>0 and release_seconds(world,u)==0
                 and missions.distance(u,mission['exit'])<=.6 for u in world[opponent+'_units'])
    fraction=spec['objective']['min_force_fraction']
    return {'survivors':survivors,'required_survivors':mission['combined_rules']['required_survivors'],
        'arrived_committed':committed,'arrived_current':current,'minimum_force_fraction':fraction,
        'exit_breached':breached,'condition':survivors>=mission['combined_rules']['required_survivors']
            and not breached and current>=committed*fraction}


def observation(world):
    value=definition(world)
    if value is None:return None
    return {'version':VERSION,'scope':'入场时点和战役参数是明确估计；状态来自当前已提交运行，不是历史实测部署',
        **({'objective_policy':DEFENSIVE_DELAY,'delay_goal':delay_assess(world),
            'spatial_metrics_note':'据点与阻援区域为参考态势，不作为本迟滞目标的夺控条件'} if value.get('objective_policy')==DEFENSIVE_DELAY else {}),
        'turn':world['campaign']['turn'],'objective':copy.deepcopy(world['campaign']['objective']),
        'surrender':copy.deepcopy(value['surrender']),
        'actors':[{'name':u['name'],'team':team,'not_before':scheduled_time(value,u,world=world),
            **schedule_metadata(value,u,world=world),
            **copy.deepcopy(world['campaign']['actors'][u['name']])}
            for team in ('red','blue') for u in world[team+'_units']]}
