"""Read-only current-state allocation proposals for runtime reorganization.

This is bookkeeping, not combat or a new state store. It does not admit a new
roster into a running mission: the existing identity, task, goal and native
platform contracts must all be rebound before such a proposal can be committed.
"""
import copy
from decimal import Decimal
import math
import re

from . import combat_effects, formation_parts, historical_initial, missions, motion_state

VERSION = 'formation-conversion-1'
ABSOLUTE_STOCK = formation_parts.RESOURCES
FRACTIONS = ('combat_damage_remainder', 'fatality_remainder', 'partition_noncombat_remainder')
FORMATION_FIELDS = {'role', 'motorized', 'fatigue', 'suppression', 'entrenchment', 'dispersion_km2', 'protection',
    'reload_remaining', 'reload_remaining_s', 'intel_age_min', 'intel_confidence', 'signal', 'source',
    'last_execution', 'last_density_sample', 'suppression_carry_ticks', motion_state.TASK_FIELD, *motion_state.FIELDS,
    *ABSOLUTE_STOCK, *FRACTIONS}
MAXIMUM = ('fatigue', 'suppression', 'intel_age_min', 'reload_remaining', 'reload_remaining_s', 'dispersion_km2')
MINIMUM = ('entrenchment', 'protection', 'intel_confidence', 'signal')
IDENTITY = ('name', 'historical_unit_id', 'exercise_unit_id', 'echelon', 'parent_id', 'historical_evidence')
UNIT_FIELDS = {*IDENTITY, 'type', 'parameter_sources', 'lat', 'lng', 'hp', 'speed', 'attack_range',
    'ground_control_radius_km', 'morale', 'supply', 'supply_node_id', 'personnel', 'equipment', 'logistics',
    'formation', 'sustainment', 'crossing', 'calculation_unit_id', 'formation_part', 'runtime_allocation',
    'historical_reference', 'exercise_reference', 'source_historical_unit_id', 'last_combat_effects'}


def _text(value, label, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(label+'须为明确、有界的非空文字')


def _integer(value, label, minimum=0):
    if type(value) is not int or not minimum <= value <= 10000000:
        raise ValueError(label+'须为有界非负整数')


def _number(value, label, minimum=0, maximum=100000000):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(label+'须为有界有限数值')


def resource_scale(unit):
    metadata = unit.get('runtime_allocation')
    if metadata is None:
        return formation_parts.scale(unit)
    if metadata.get('version') != VERSION:
        raise ValueError('未知运行中分配版本')
    scale = math.fsum(r['resource_scale'] for r in metadata['origins'].values())
    _number(scale, '根账资源尺度', 1e-12)
    return scale


def _origins(unit):
    metadata = unit.get('runtime_allocation')
    if metadata:
        rows = copy.deepcopy(metadata['origins'])
    else:
        key = unit.get('calculation_unit_id') or unit.get('historical_unit_id') or unit.get('exercise_unit_id')
        _text(key, '当前执行身份', 256)
        rows = {key: dict(committed=unit['personnel']['committed'], resource_scale=formation_parts.scale(unit),
                          historical_unit_id=unit.get('historical_unit_id'))}
    for key, row in rows.items():
        _text(key, '原始根账身份', 256)
        if set(row) != {'committed', 'resource_scale', 'historical_unit_id'}:
            raise ValueError('根账字段非法')
        _integer(row['committed'], '根账投入', 1); _number(row['resource_scale'], '根账资源尺度', 1e-12)
    if not rows or sum(r['committed'] for r in rows.values()) != unit['personnel']['committed']:
        raise ValueError('根账投入与当前执行单位不一致')
    return rows


def _check(unit, *, for_reorganization=True):
    if not isinstance(unit, dict):
        raise ValueError('当前单位须为完整实态')
    _text(unit.get('name'), '单位名称', 160)
    if set(unit)-UNIT_FIELDS:
        raise ValueError('未知单位状态或载荷字段须先登记迁移：'+','.join(sorted(set(unit)-UNIT_FIELDS)))
    p = unit.get('personnel') or {}
    if set(p)-{'committed','current','casualties','noncombat_losses','source','calculation_source',
               'breakdown_source','carried_forward',*combat_effects.COUNT_FIELDS}:
        raise ValueError('未知人员状态字段须先登记迁移')
    for k in ('committed', 'current', 'casualties', 'noncombat_losses'):
        _integer(p.get(k), '人员'+k)
    if p['committed'] < 1 or p['committed'] != p['current']+p['casualties']+p['noncombat_losses']:
        raise ValueError('当前人员账不守恒')
    combat_effects.validate_personnel(p)
    seen = set()
    for e in unit.get('equipment', []):
        if set(e)-{'category','name','committed','operational','damaged','destroyed','damage_load','source','calculation_source','carried_forward'}:
            raise ValueError('未知分类装备字段须先登记迁移')
        if e['category'] in seen:
            raise ValueError('分类装备重复')
        seen.add(e['category'])
        for k in ('committed', 'operational', 'damaged', 'destroyed'):
            _integer(e.get(k), '装备'+k)
        if e['committed'] != e['operational']+e['damaged']+e['destroyed']:
            raise ValueError('当前装备账不守恒')
        _number(e.get('damage_load',0),'装备毁伤余量',0,1)
        if e.get('damage_load',0)>=1:raise ValueError('装备毁伤余量达到整数，须先登记根账债')
    for k in ('lat', 'lng'):
        _number(unit.get(k), '位置'+k, -180, 180)
    if abs(unit['lat']) > 90:
        raise ValueError('纬度非法')
    if set(unit.get('logistics') or {}) != {'food','ammo'}:
        raise ValueError('未知库存字段须先登记迁移，不能复制未计量物资')
    for k in ('food', 'ammo'):
        _number(unit.get('logistics', {}).get(k), '归一化'+k, 0, 100)
    for k in ('hp','supply'):
        _number(unit.get(k),'状态'+k,0,100)
    if isinstance(unit.get('morale'),str):_text(unit['morale'],'士气描述',200)
    else:_number(unit.get('morale'),'士气量表',0,100)
    f = unit.get('formation') or {}
    if set(f)-FORMATION_FIELDS:
        raise ValueError('未定义状态迁移策略的编组字段：'+','.join(sorted(set(f)-FORMATION_FIELDS)))
    if motion_state.present(unit):motion_state.validate_unit(unit)
    if for_reorganization and f.get(motion_state.TASK_FIELD,{}).get('status') in ('waiting','moving','blocked'):
        raise ValueError('连续机动在途意图须先登记身份与等待交接，不能在重编时复制或清空')
    if 'suppression_carry_ticks' in f:
        from . import suppression_state
        suppression_state.validate_unit(unit)
    for k in ABSOLUTE_STOCK:
        _integer(f.get(k), '绝对库存'+k)
    for k in FRACTIONS:
        _number(f.get(k, 0), '损耗余量'+k, 0, 1)
        if f.get(k, 0) >= 1:
            raise ValueError('单位余量须小于1；整数债须先建立根账执行契约')
    for k in MAXIMUM+MINIMUM:
        if k in f:
            _number(f[k], '编组状态'+k)
    if unit.get('crossing'):
        raise ValueError('渡运或在途账须先登记完整交接；不能在重编时清空')
    s = unit.get('sustainment')
    from . import support_dynamics as sd
    if s:
        if (set(s)-{'version', 'shortage_hours', 'noncombat_remainder', 'last_receipt'}
                or s.get('version') not in {'time-sustainment-1','personnel-rations-1'}):
            raise ValueError('时间保障状态字段或版本非法')
        _number(s.get('shortage_hours'), '缺粮债')
        sd.validate_remainder(unit)
    sd.deferred_support(unit)  # A policy without a bound support state is invalid.
    _origins(unit)


def _weighted(total, weights):
    """Integer largest remainders; stock amounts need not be below headcount."""
    _integer(total, '待分配数量')
    denominator = sum(weights)
    if not denominator:
        if total:raise ValueError('非零分配没有权重')
        return [0]*len(weights)
    values = [total*c//denominator for c in weights]
    remaining = total-sum(values)
    order = sorted(range(len(values)), key=lambda i: (-(total*weights[i] % denominator), i))
    for i in order[:remaining]:
        values[i] += 1
    return values


def _apportion(total, capacities):
    """Loss categories cannot consume more than their allocated commitment."""
    if total > sum(capacities):
        raise ValueError('分配超过可用容量')
    return _weighted(total,capacities)


def _spread(total, weights):
    values = [total*w/sum(weights) for w in weights]
    # Keep rounding residue in one bucket, never create or discard a root debt.
    i = max(range(len(weights)), key=lambda k: weights[k])
    values[i] = total-math.fsum(v for j, v in enumerate(values) if j != i)
    return values


def _micro_debt(value):
    """Convert an already exact frozen quantum; never round carried damage."""
    _number(value,'毁伤余量',0,1)
    micro=Decimal(str(value))*1000000
    if micro!=micro.to_integral_value():raise ValueError('毁伤余量不符合冻结的1e-6精度')
    return int(micro)


def _precision_request(request,quantum):
    if quantum is not None:
        if type(quantum)not in (int,float)or quantum!=.000001:raise ValueError('未知冻结毁伤精度')
        request['damage_quantum']=quantum


def _names(unit, allocations, mode, snapshot):
    if mode == 'synthetic':
        for part in allocations:
            if set(part) != {'id', 'label', 'committed'}:
                raise ValueError('合成计算划分须明确id、label及投入分配')
            _text(part['label'], '分队名称', 40)
        return [dict(name=unit['name']+' · '+p['label']+('' if '计算分队' in p['label'] else '（计算分队）')) for p in allocations]
    if mode != 'historical' or snapshot is None:
        raise ValueError('历史细分须提供冻结来源，不能从任意名称生成部队')
    historical_initial.restore(snapshot)
    index = {u['id']: u for u in snapshot['definition']['units']}
    parent = index.get(unit.get('historical_unit_id'))
    if parent is None:
        raise ValueError('历史父单位不在冻结资料中')
    known_children = {u['id'] for u in index.values() if u['parent_id'] == parent['id']}
    selected = set(); residual = False; result = []
    for p in allocations:
        if set(p) != {'id', 'historical_unit_id', 'committed'}:
            raise ValueError('历史细分只接受来源身份与分配量，不能填造名字')
        identity = p['historical_unit_id']
        if identity is None:
            if residual:
                raise ValueError('未分配余部只能有一项')
            residual = True; result.append(dict(name=unit['name']+'未分配余部（估计）'))
            continue
        child = index.get(identity)
        if identity not in known_children or identity in selected:
            raise ValueError('细分须引用不重复的直接历史下级')
        parent_sides = (parent['team'], child['team'])
        if parent_sides[0] != parent_sides[1]:
            raise ValueError('历史下级阵营不一致')
        presence = next((r for r in child['presence'] if r['phase_id'] == snapshot['phase_id']), {})
        if presence.get('status') != 'reported_present':
            raise ValueError('该下级在本阶段尚未核定在场，不能生成到场部队')
        selected.add(identity)
        result.append(dict(name=child['name'], historical_unit_id=identity, echelon=child['echelon'],
                           parent_id=child['parent_id'], historical_evidence=copy.deepcopy(child['evidence'])))
    complete = parent.get('children_coverage', {}).get('status') == 'complete'
    if not residual and (not complete or selected != known_children):
        raise ValueError('下级覆盖未证明完整，须保留明确估计的未分配余部')
    return result


def _metadata(unit, operation_id, origins, mode, *, inherit_parent=False):
    old = unit.get('runtime_allocation') or {}
    parent = old.get('parent_identity') if inherit_parent else None
    extent = old.get('parent_extent') if inherit_parent else None
    result = dict(version=VERSION, operation_id=operation_id, product_mode=mode,
        parent_identity=copy.deepcopy(parent or {k:unit[k] for k in IDENTITY if k in unit}),
        parent_extent=copy.deepcopy(extent or dict(committed=unit['personnel']['committed'],origins=_origins(unit))),
        origins=origins)
    if 'support_remainder_policy' in old:
        result['support_remainder_policy']=old['support_remainder_policy']
    return result


def _totals(units):
    precise_motion = motion_state.validate_uniform(units)
    people = {k:sum(u['personnel'].get(k,0) for u in units) for k in ('committed','current','casualties','noncombat_losses')}
    people.update({k:sum(u['personnel'].get(k,0) for u in units) for k in ('killed','wounded','captured','missing')})
    people['unclassified_casualties'] = sum(u['personnel']['casualties']-sum(u['personnel'].get(k,0)
        for k in ('killed','wounded','captured','missing')) for u in units)
    gear = {category:{k:sum(e[k] for u in units for e in u['equipment'] if e['category']==category)
                      for k in ('committed','operational','damaged','destroyed')}
            for category in sorted({e['category'] for u in units for e in u['equipment']})}
    for category in gear:
        gear[category]['damage_load']=round(math.fsum(e.get('damage_load',0) for u in units for e in u['equipment'] if e['category']==category),12)
    fractions = {k:round(math.fsum(u['formation'].get(k,0) for u in units),12) for k in FRACTIONS}
    fractions['noncombat_remainder'] = round(math.fsum((u.get('sustainment') or {}).get('noncombat_remainder',0) for u in units),12)
    stock={k:sum(u['formation'][k] for u in units) for k in ABSOLUTE_STOCK}
    extra={}
    if precise_motion:
        fuel=sum(motion_state.fuel_load(u) for u in units)
        stock['fuel_liters'],credit=divmod(fuel,motion_state.SCALE)
        extra['motion_precision']={'fuel_microliters':fuel,'fuel_credit_microliters':credit}
    return dict(personnel=people,equipment=gear,absolute_stock=stock,
        normalized_stock={k:round(math.fsum(u['logistics'][k]*resource_scale(u) for u in units),12) for k in ('food','ammo')},
        resource_scale=round(math.fsum(resource_scale(u) for u in units),12),fractional_debts=fractions,**extra)


def _proposal(kind, before, after, request):
    for unit in after:
        _check(unit)
    a, b = _totals(before), _totals(after)
    if a != b:
        raise ValueError('当前实态转换不守恒')
    value = dict(version=VERSION,kind=kind,preview_only=True,runtime_admitted=False,
        request=copy.deepcopy(request),before=copy.deepcopy(before),after=after,totals_before=a,totals_after=b,
        scope='当前实态分配提案；不是战斗解算，不改变战局。身份、任务、目标、在途、原生平台和显示接入未验前不能提交。',
        policies=dict(integer_allocation='容量约束下最大余数法；估计分配，不是逐人历史身份',
            normalized_stock='固定根账资源尺度；不按剩余人数重置，不直接相加归一化覆盖',
            fractions='份额分配、合并相加；达到整数的合并债在根账执行契约接入前拒绝',
            state='分拆复制强度状态；合并取较差疲劳/压制/冷却/情报，不清零',
            location='分拆沿用当前位置；合并仅允许10米控制容差内同地，不平均异地坐标',
            receipts='旧执行和收支回执留在before前史，不复制成新实体已执行记录'))
    from . import support_dynamics as sd
    if motion_state.present(after[0]):
        value['policies']['motion_precision']=('疲劳整点与余量一起复制／取最差；整升燃油加微升信用为绝对库存，'
            '分拆按同一人员份额分配信用，不复制；合并先合计微升再规范化，不产生到货或消耗')
    if any(sd.deferred_support(u) for u in after):
        value['policies']['fractions']='份额分配、合并相加；已登记时间保障失能负荷延至后续有效暴露时取整，零时间不减员；其他整数债仍拒绝'
    value['proposal_hash'] = missions.digest(value)
    return value


def split_current(unit, allocations, *, assumption, operation_id, product_mode='historical', historical_snapshot=None, damage_quantum=None):
    _check(unit); _text(assumption,'分配依据'); _text(operation_id,'操作身份',64)
    if not isinstance(allocations,list) or not 2 <= len(allocations) <= 32:
        raise ValueError('当前细分须为2至32项互斥分配')
    ids = set()
    for p in allocations:
        if not isinstance(p,dict) or not isinstance(p.get('id'),str) or not re.fullmatch('[a-z0-9_]{1,32}',p['id']) or p['id'] in ids:
            raise ValueError('分队ID须有效且不重复')
        ids.add(p['id']); _integer(p.get('committed'),'分队投入',1)
    weights = [p['committed'] for p in allocations]
    if sum(weights) != unit['personnel']['committed']:
        raise ValueError('分队投入必须完整覆盖当前根账，不复制或遗漏人员')
    names = _names(unit,allocations,product_mode,historical_snapshot)
    if len({row['name'] for row in names})!=len(names):
        raise ValueError('分队名称重复，不能生成含糊的执行身份')
    request = dict(allocations=allocations,assumption=assumption,operation_id=operation_id,
                   product_mode=product_mode,historical_snapshot=historical_snapshot)
    _precision_request(request,damage_quantum)
    key = missions.digest([unit,request])[:20]
    leaves = [copy.deepcopy(unit) for _ in weights]
    for i, leaf in enumerate(leaves):
        leaf.update(names[i],calculation_unit_id='reorg::'+key+'::'+allocations[i]['id'])
        leaf.pop('formation_part',None)
        leaf.pop('last_combat_effects',None)
        leaf['personnel']['committed'] = weights[i]
        leaf['formation'].pop('last_execution',None)
        leaf['formation'].pop('last_density_sample',None)
        if leaf.get('sustainment'):leaf['sustainment'].pop('last_receipt',None)
    remaining = list(weights)
    known = ('killed','wounded','captured','missing')
    unknown = unit['personnel']['casualties']-sum(unit['personnel'].get(k,0) for k in known)
    for field in (*[k for k in known if k in unit['personnel']], 'unclassified_casualties', 'noncombat_losses'):
        total = unknown if field=='unclassified_casualties' else unit['personnel'][field]
        values = _apportion(total,remaining)
        for i, leaf in enumerate(leaves):
            leaf['personnel'][field] = values[i]; remaining[i] -= values[i]
    for i, leaf in enumerate(leaves):
        leaf['personnel']['current'] = remaining[i]
        leaf['personnel']['casualties'] = sum(leaf['personnel'].get(k,0) for k in (*known,'unclassified_casualties'))
    for j, equipment in enumerate(unit['equipment']):
        cap = _weighted(equipment['committed'],weights)
        committed = list(cap); destroyed = _apportion(equipment['destroyed'],cap)
        cap = [c-v for c,v in zip(cap,destroyed)]; damaged = _apportion(equipment['damaged'],cap)
        for i, leaf in enumerate(leaves):
            leaf['equipment'][j].update(committed=committed[i],destroyed=destroyed[i],damaged=damaged[i],operational=cap[i]-damaged[i])
        if 'damage_load' in equipment:
            for leaf, value in zip(leaves,_spread(equipment['damage_load'],weights)):
                leaf['equipment'][j]['damage_load']=value
    for field in ABSOLUTE_STOCK:
        for leaf, amount in zip(leaves,_weighted(unit['formation'][field],weights)):
            leaf['formation'][field] = amount
    if motion_state.present(unit):
        for leaf,amount in zip(leaves,_weighted(unit['formation'][motion_state.FUEL_FIELD],weights)):
            leaf['formation'][motion_state.FUEL_FIELD]=amount
    for field in FRACTIONS:
        if field in unit['formation']:
            values=([n/1000000 for n in _weighted(_micro_debt(unit['formation'][field]),weights)]
                if damage_quantum is not None and field=='combat_damage_remainder'else _spread(unit['formation'][field],weights))
            for leaf, amount in zip(leaves,values):leaf['formation'][field] = amount
    if unit.get('sustainment'):
        for leaf, amount in zip(leaves,_spread(unit['sustainment']['noncombat_remainder'],weights)):
            leaf['sustainment']['noncombat_remainder'] = amount
    origins = _origins(unit); remaining = list(weights); assigned = [{} for _ in weights]
    for identity, origin in origins.items():
        amounts = _apportion(origin['committed'],remaining)
        scales = _spread(origin['resource_scale'],amounts)
        for i, amount in enumerate(amounts):
            if amount:
                assigned[i][identity] = dict(committed=amount,resource_scale=scales[i],historical_unit_id=origin['historical_unit_id'])
            remaining[i] -= amount
    for i, leaf in enumerate(leaves):
        leaf['runtime_allocation'] = _metadata(unit,operation_id,assigned[i],product_mode)
        for field in ('personnel','equipment','logistics','position'):
            leaf.setdefault('parameter_sources',{})[field] = dict(kind='runtime_allocation',assumption=assumption,
                source_unit=unit.get('calculation_unit_id') or unit.get('historical_unit_id'),source_hash=missions.digest(unit))
    return _proposal('split',[unit],leaves,request)


def merge_current(units, *, assumption, operation_id, damage_quantum=None):
    _text(assumption,'合并依据'); _text(operation_id,'操作身份',64)
    if not isinstance(units,list) or not 2 <= len(units) <= 32:
        raise ValueError('合并须为2至32个互斥当前实体')
    for u in units:_check(u)
    precise_motion=motion_state.validate_uniform(units)
    ids = [u.get('calculation_unit_id') or u.get('historical_unit_id') for u in units]
    if len(set(ids)) != len(ids):raise ValueError('合并实体重复')
    first = units[0]; metadata = first.get('runtime_allocation')
    if not metadata or any(not u.get('runtime_allocation') or any(u['runtime_allocation'].get(k)!=metadata.get(k)
            for k in ('parent_identity','parent_extent','product_mode')) for u in units):
        raise ValueError('跨根历史合编须先登记完整身份及资源根账，不按名称合并')
    if any(missions.distance(first,u) > .01 for u in units):
        raise ValueError('须先实际同地集结；不能平均异地坐标后立即交战')
    fixed = ('type','speed','attack_range','ground_control_radius_km','supply_node_id')
    if any(any(u.get(k)!=first.get(k) for k in fixed) or u['formation'].get('motorized')!=first['formation'].get('motorized') for u in units):
        raise ValueError('不同兵种性能或补给绑定须先登记换装/保障交接')
    unit = copy.deepcopy(first); unit.update(copy.deepcopy(metadata['parent_identity']))
    request = dict(assumption=assumption,operation_id=operation_id)
    _precision_request(request,damage_quantum)
    unit['calculation_unit_id'] = 'reorg::'+missions.digest([units,request])[:20]+'::merged'
    unit.pop('formation_part',None)
    unit.pop('last_combat_effects',None)
    origins = {}
    for old in units:
        for key, row in _origins(old).items():
            if key not in origins:origins[key]=copy.deepcopy(row)
            else:
                origins[key]['committed']+=row['committed'];origins[key]['resource_scale']+=row['resource_scale']
    unit['runtime_allocation'] = _metadata(first,operation_id,origins,metadata['product_mode'],inherit_parent=True)
    total = _totals(units)
    if total['personnel']['committed'] != metadata['parent_extent']['committed']:
        unit['name'] += '合并部（估计）'
    for k,v in total['personnel'].items():
        if k in ('killed','wounded','missing','captured') and not all(k in u['personnel'] for u in units) and not v:
            unit['personnel'].pop(k,None)
        else:unit['personnel'][k]=v
    unit['personnel']['unclassified_casualties'] = unit['personnel']['casualties']-sum(unit['personnel'].get(k,0) for k in ('killed','wounded','missing','captured'))
    for e in unit['equipment']:
        values=total['equipment'][e['category']]
        if values['damage_load']>=1:raise ValueError('装备毁伤余量达到整数，须先接入根账债执行')
        e.update(values)
    scale = resource_scale(unit)
    unit['logistics'] = {k:math.fsum(u['logistics'][k]*resource_scale(u) for u in units)/scale for k in ('food','ammo')}
    from . import supply
    unit['supply'] = supply.index_value(unit)
    unit['hp']=min(u['hp'] for u in units)
    morale=[u['morale'] for u in units]
    if all(type(v) in (int,float) for v in morale):unit['morale']=min(morale)
    elif all(v==morale[0] for v in morale):unit['morale']=morale[0]
    else:raise ValueError('士气描述不可比较，须先登记可比量表，不能选择较好描述')
    unit['formation'].update(total['absolute_stock']);unit['formation'].pop('last_execution',None)
    unit['formation'].pop('last_density_sample',None)
    for field in MAXIMUM:
        if any(field in u['formation'] for u in units):
            unit['formation'][field]=max(u['formation'].get(field,0) for u in units)
    if precise_motion:
        # Keep intensive fatigue as a pair, and normalize conserved fuel stock.
        points,carry=divmod(max(motion_state.fatigue_load(u) for u in units),motion_state.SCALE)
        unit['formation'].update(fatigue=points,fatigue_carry_ticks=carry,
            fuel_credit_microliters=total['motion_precision']['fuel_credit_microliters'])
    from . import suppression_state
    if any(suppression_state.FIELD in u['formation'] for u in units):
        # Suppression is intensive. Preserve the existing conservative maximum,
        # choosing its integer and fraction together, never from different units.
        load=max(suppression_state.load(u) for u in units)
        points,carry=divmod(load,suppression_state.SCALE)
        unit['formation'].update(suppression=points,suppression_carry_ticks=carry)
    for field in MINIMUM:
        if field in first['formation']:unit['formation'][field]=min(u['formation'][field] for u in units)
    for field in FRACTIONS:
        value = (sum(_micro_debt(u['formation'].get(field,0))for u in units)/1000000
            if damage_quantum is not None and field=='combat_damage_remainder'else math.fsum(u['formation'].get(field,0) for u in units))
        if value>=1:raise ValueError('合并余量达到整数，须先接入根账债执行；不能清零或凭合并制造减员')
        if any(field in u['formation'] for u in units):unit['formation'][field]=value
    if any(bool(u.get('sustainment')) != bool(first.get('sustainment')) for u in units):
        raise ValueError('时间保障模型不一致')
    if first.get('sustainment'):
        if any(u['sustainment']['version']!=first['sustainment']['version'] for u in units):
            raise ValueError('时间保障模型版本不一致')
        debt = math.fsum(u['sustainment']['noncombat_remainder'] for u in units)
        from . import support_dynamics as sd
        if debt>=1 or any(sd.deferred_support(u) for u in units):
            unit['runtime_allocation']['support_remainder_policy']=sd.DEFERRED_SUPPORT_POLICY
        unit['sustainment'].update(shortage_hours=max(u['sustainment']['shortage_hours'] for u in units),noncombat_remainder=debt)
        unit['sustainment'].pop('last_receipt',None)
    return _proposal('merge',units,[unit],request)


def verify_proposal(proposal):
    """Recompute a detached proposal, not a hash-only authorization check."""
    if not isinstance(proposal,dict) or proposal.get('version')!=VERSION:
        raise ValueError('转换提案版本非法')
    try:
        if proposal['kind']=='split':
            expected=split_current(proposal['before'][0],**copy.deepcopy(proposal['request']))
        elif proposal['kind']=='merge':
            expected=merge_current(proposal['before'],**copy.deepcopy(proposal['request']))
        else:raise ValueError('未知转换种类')
    except (KeyError,TypeError,IndexError) as exc:
        raise ValueError('转换提案字段不完整') from exc
    if proposal!=expected:raise ValueError('转换提案与当前实态重新分配结果不一致')
    return True


def preparation(session, args):
    """Bounded, repeatable preview using the existing authoritative session.

    The candidate remains local to this call. No result cache, draft, command or
    world is written. Every page recomputes against the same world/revisions.
    """
    from . import commands, force_organization
    allowed={'kind','unit_ids','allocations','assumption','offset','limit','view_version'}
    if not isinstance(args,dict) or set(args)-allowed:
        raise ValueError('转换预览字段非法，不接受用户提供的实态、模式或提交指令')
    world=session.get('war_state') or {}
    if not world.get('mission',{}).get('definition',{}).get('combined_rules'):
        raise ValueError('需要已初始化的多兵种实态，不能从史料空值生成编组')
    missions.validate(world)
    ids=args.get('unit_ids');kind=args.get('kind');assumption=args.get('assumption')
    if (kind not in ('split','merge') or not isinstance(ids,list) or not 1<=len(ids)<=32
            or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids)):
        raise ValueError('须以已登记命令ID选择一个细分单位或多个合并单位')
    _text(assumption,'转换估计依据')
    index=commands.resolve_units(session)
    if any(i not in index for i in ids):raise ValueError('预览引用未知或过期单位ID')
    teams={index[i][0]['team'] for i in ids}
    if len(teams)!=1:raise ValueError('不能跨阵营合并或分配')
    units=[index[i][1] for i in ids]
    for u in units:
        from . import unit_participation
        row=unit_participation.unit_view(world,u)
        if row['pending'] or row['status'] in ('withdrawing','returning','staging'):
            raise ValueError('在途参与或尚未到场状态须先登记完整交接，不能丢弃原请求')
    policy=commands.state(session);organization=force_organization.state(session)
    world_version=commands.world_version(session)
    request={k:copy.deepcopy(args[k]) for k in ('kind','unit_ids','allocations','assumption') if k in args}
    op=missions.digest([world_version,policy['revision'],organization['revision'],request])[:32]
    quantum=combat_effects.reference(world).get('damage_quantum')
    precision={'damage_quantum':quantum}if quantum is not None else {}
    if kind=='split':
        if len(ids)!=1:raise ValueError('一次细分只选择一个当前单位')
        proposal=split_current(units[0],args.get('allocations'),assumption=assumption,operation_id=op,
            product_mode=session.get('product_mode','historical'),historical_snapshot=world.get('historical_initial'),**precision)
    else:
        if 'allocations' in args:raise ValueError('合并不接受重新填写分配数或库存')
        proposal=merge_current(units,assumption=assumption,operation_id=op,**precision)
    from . import formation_session
    prepared=formation_session.prepare(session,proposal,team=next(iter(teams)))
    token=missions.digest([world_version,policy['revision'],organization['revision'],proposal['proposal_hash']])
    if args.get('view_version') is not None and args['view_version']!=token:
        raise ValueError('转换前态或修订已变化，请重新预览')
    offset=args.get('offset',0);limit=args.get('limit',8)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=8:
        raise ValueError('转换预览分页须为非负offset及1至8项limit')
    return dict(proposal=proposal,prepared=prepared,request=request,world_version=world_version,
        view_version=token,command_revision=policy['revision'],organization_revision=organization['revision'],
        offset=offset,limit=limit)


def observation(session,args):
    value=preparation(session,args);proposal=value['proposal'];prepared=value['prepared']
    offset=value['offset'];limit=value['limit'];token=value['view_version'];request=value['request']
    rows=[]
    for u in proposal['after'][offset:offset+limit]:
        rows.append(dict(name=u['name'],proposed_calculation_id=u['calculation_unit_id'],historical_unit_id=u.get('historical_unit_id'),
            personnel=copy.deepcopy(u['personnel']),equipment=[{k:e[k] for k in ('category','committed','operational','damaged','destroyed','damage_load') if k in e} for e in u['equipment']],
            logistics=copy.deepcopy(u['logistics']),resource_scale=resource_scale(u),
            formation={k:u['formation'][k] for k in (*ABSOLUTE_STOCK,*FRACTIONS,*MAXIMUM,*MINIMUM,*motion_state.FIELDS) if k in u['formation']},
            position={k:u[k] for k in ('lat','lng')},source_status='仅建议执行身份，尚未进入战局或命令注册表'))
    next_offset=offset+len(rows) if offset+len(rows)<len(proposal['after']) else None
    return dict(ok=True,readonly=True,preview_only=True,runtime_admitted=False,kind=proposal['kind'],proposal_hash=proposal['proposal_hash'],
        world_version=value['world_version'],view_version=token,command_revision=value['command_revision'],organization_revision=value['organization_revision'],
        totals_before=proposal['totals_before'],totals_after=proposal['totals_after'],rows=rows,total_rows=len(proposal['after']),
        ownership=prepared['ownership'],continuity=prepared['continuity'],session_continuity=prepared['session_continuity'],
        offset=offset,limit=limit,next_args={**request,'offset':next_offset,'limit':limit,'view_version':token} if next_offset is not None else None,
        policies=proposal['policies'],scope=proposal['scope'],formal_commit_available=True,
        unimplemented_commit_contracts=['转换后跨阶段、新单位独立Native决策及开放分支身份继承',
            '非等价目标观察的有代价重组规则','正式分合兵前端操作验收','在途/整数余量债/跨根历史改编'])
