"""Disjoint calculation parts of sourced formations; inputs and observations only.

Leaves reuse ordinary unit commands and native WSF effects. The parent is an
immutable accounting group, never an additional platform or combatant.
"""
import copy
import math
import re
import hashlib

from . import missions

VERSION = 'formation-partitions-1'
CAMPAIGN_VERSION = 'formation-partitions-2'
LIMITS={VERSION:(8,24),CAMPAIGN_VERSION:(32,256)}
RESOURCE_ACCOUNTING = ('food/ammo为本分队0–100归一化覆盖，delivery/food_spent/ammo_spent为父编组等效工作量；'
    'scale为分队初始人员占比（normalized_resource_scale/resource_scale），不是当前剩余人数比例。'
    'food_after=food_before+(delivery-food_spent)/scale，ammo_after=ammo_before+(delivery-ammo_spent)/scale。'
    '先按scale换算再对账；覆盖变化与等效消耗数值不同不是差额缺载，不能直接相减。'
    '父组覆盖=sum(分队覆盖×scale)；分类装备及绝对库存直接相加，不乘scale。')
RESOURCES = ('fuel_liters', 'spares', 'materials', 'shells', 'aa_rounds')
PART_FIELDS = {'id', 'label', 'personnel', 'position', 'equipment', 'resources',
               'dispersion_km2', 'assumption'}


def _integer(value, low=0):
    if type(value) is not int or not low <= value <= 10000000:
        raise ValueError('分队人员、装备与绝对库存须为有界非负整数')


def validate_inputs(snapshot, parameters, index, *, partial=False):
    config = parameters.get('partitions')
    if config is None:
        return
    if (not isinstance(config, dict) or set(config) != {'version', 'groups'}
            or config['version'] not in LIMITS or not isinstance(config['groups'], dict)
            or not set(config['groups']) <= set(parameters['actors'])):
        raise ValueError('分队配置必须绑定本阶段已选的历史父单位')
    area = parameters['area']
    max_parts,max_leaves=LIMITS[config['version']]
    for identity, group in config['groups'].items():
        if (not isinstance(group, dict) or set(group) != {'parts', 'assumption'}
                or not isinstance(group['assumption'], str) or not group['assumption'].strip()
                or not isinstance(group['parts'], list) or not 2 <= len(group['parts']) <= max_parts):
            raise ValueError(f'每个父单位须配置2至{max_parts}个互斥分队并说明估计依据')
        parent = parameters['actors'][identity]
        if partial and parent['personnel'] is None:
            continue  # Final validation still checks every allocation and total.
        ids = set()
        for part in group['parts']:
            if not isinstance(part, dict) or set(part) != PART_FIELDS:
                raise ValueError('分队字段不完整或含未知身份字段')
            if (not isinstance(part['id'], str) or not re.fullmatch('[a-z0-9_]{1,32}', part['id'])
                    or part['id'] in ids):
                raise ValueError('分队ID须为不重复的小写字母、数字或下划线')
            ids.add(part['id'])
            for key in ('label', 'assumption'):
                if not isinstance(part[key], str) or not part[key].strip() or len(part[key]) > (40 if key == 'label' else 2000):
                    raise ValueError('分队名称与估计依据须明确且有界')
            _integer(part['personnel'], 1)
            point = part['position']
            if (not isinstance(point, dict) or set(point) != {'lat', 'lng'}
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in point.values())
                    or abs(point['lat']) > 90 or abs(point['lng']) > 180
                    or missions.distance(point, area['center']) > area['radius_km']):
                raise ValueError('分队部署须为有效战区内的明确估计坐标')
            known = index[identity]['facts']['position']['value']
            if known and known['phase_id'] == snapshot['phase_id']:
                if known['kind'] == 'unit_position' and point != {k: known[k] for k in ('lat', 'lng')}:
                    raise ValueError('已知父单位位置不能由分队配置静默改写')
                if known['kind'] == 'deployment_area_reference' and missions.distance(point, known) > known['uncertainty_km']:
                    raise ValueError('分队部署超出父单位来源地域的不确定范围')
            for key, fields in (('equipment', parent['equipment']), ('resources', RESOURCES)):
                if not isinstance(part[key], dict) or set(part[key]) != set(fields):
                    raise ValueError('分队必须明确分配分类装备和五类绝对库存')
                for value in part[key].values():
                    _integer(value)
            value = part['dispersion_km2']
            if type(value) not in (int, float) or not math.isfinite(value) or not .001 <= value <= 10000:
                raise ValueError('分队展开面积须为明确的正值估计')
        if sum(p['personnel'] for p in group['parts']) != parent['personnel']:
            raise ValueError('分队人员合计不等于父单位投入，不能重复或遗漏人员')
        for key in parent['equipment']:
            if sum(p['equipment'][key] for p in group['parts']) != parent['equipment'][key]:
                raise ValueError('分队分类装备与父单位不守恒：' + key)
        for key in RESOURCES:
            if sum(p['resources'][key] for p in group['parts']) != parent['formation'][key]:
                raise ValueError('分队绝对库存与父单位不守恒：' + key)
    totals = {team: sum(len(config['groups'][i]['parts']) if i in config['groups'] else 1
                       for i in parameters['actors'] if index[i]['team'] == team) for team in ('red', 'blue')}
    if any(n > max_leaves for n in totals.values()):
        raise ValueError(f'当前划分版本每方最多{max_leaves}个独立分队；会战级容量须显式选择formation-partitions-2')


def expand(world, parameters):
    """Compile a frozen initial allocation; never split a running world."""
    config = parameters.get('partitions')
    if not config or not config['groups']:
        return
    groups = []
    for team in ('red', 'blue'):
        leaves = []
        for unit in world[team + '_units']:
            identity = unit['historical_unit_id']
            group = config['groups'].get(identity)
            if group is None:
                leaves.append(unit)
                continue
            names = []
            for part in group['parts']:
                leaf = copy.deepcopy(unit)
                leaf.update(name=unit['name'] + ' · ' + part['label'] + '（计算分队）',
                            calculation_unit_id=identity + '::' + part['id'], **part['position'])
                leaf['formation_part'] = {'version': config['version'], 'group_id': identity, 'part_id': part['id'],
                    'numerator': part['personnel'], 'denominator': unit['personnel']['committed'],
                    'parent_name': unit['name'], 'assumption': part['assumption']}
                note = group['assumption'] + '；' + part['assumption']
                leaf['personnel'].update(committed=part['personnel'], current=part['personnel'], source=note)
                for item in leaf['equipment']:
                    item.update(committed=part['equipment'][item['category']], operational=part['equipment'][item['category']], source=note)
                leaf['formation'].update(part['resources'], dispersion_km2=part['dispersion_km2'], source=note)
                leaf['formation']['partition_noncombat_remainder'] = 0
                for key in ('personnel', 'equipment', 'position', 'logistics'):
                    leaf['parameter_sources'][key] = {'kind': 'partition_input', 'note': note,
                        'scope': '同一历史父单位的互斥计算划分；粮弹为归一化覆盖，总账按人员占比折合，不是新增史实番号'}
                names.append(leaf['name'])
                leaves.append(leaf)
            groups.append({'id': identity, 'historical_unit_id': identity, 'name': unit['name'], 'team': team,
                'committed': unit['personnel']['committed'],
                'equipment': {e['category']: e['committed'] for e in unit['equipment']},
                'resources': {k: unit['formation'][k] for k in RESOURCES},
                'members': names, 'assumption': group['assumption']})
        world[team + '_units'] = leaves
    world['formation_groups'] = {'version': config['version'], 'groups': groups}


def scale(unit):
    if unit.get('runtime_allocation') is not None:
        from . import formation_conversion
        return formation_conversion.resource_scale(unit)
    part = unit.get('formation_part')
    return part['numerator'] / part['denominator'] if part else 1


def is_fragment(unit):
    return bool(unit.get('formation_part') or unit.get('runtime_allocation'))


def has_groups(world):
    return bool(world.get('formation_groups') or world.get('formation_registry'))


def rebind_exercise(world, baseline):
    """Freeze an explicitly edited exercise allocation, leaving source facts alone."""
    groups = []
    for original in baseline['formation_groups']['groups']:
        members = [u for _, u in missions.units(world) if u.get('formation_part', {}).get('group_id') == original['id']]
        if not members:
            continue
        group = copy.deepcopy(original)
        total = sum(u['personnel']['committed'] for u in members)
        for unit in members:
            part = unit['formation_part']
            if unit['name'] not in original['members']:
                if '计算分队' not in unit['name']:
                    unit['name'] += '（计算分队）'
                part['part_id'] += '_' + hashlib.sha256(unit['name'].encode()).hexdigest()[:8]
                unit['calculation_unit_id'] = original['id'] + '::' + part['part_id']
            part.update(numerator=unit['personnel']['committed'], denominator=total)
        group.update(committed=total, members=[u['name'] for u in members],
                     equipment={category: sum(e['committed'] for u in members for e in u['equipment'] if e['category'] == category)
                                for category in original['equipment']},
                     resources={k: sum(u['formation'][k] for u in members) for k in RESOURCES})
        if group != original:
            group['assumption'] = '用户显式编辑的合成分队配置；原历史事实和共同基线保留'
        groups.append(group)
    if groups:
        world['formation_groups'] = {'version': baseline['formation_groups']['version'], 'groups': groups}
    else:
        world.pop('formation_groups', None)


def validate(world):
    original = world['mission']['definition']['initial_state']
    if world.get('formation_groups') != original.get('formation_groups'):
        raise ValueError('计算父单位分组与冻结初态不一致')
    from . import formation_registry
    baseline = {u['name']: u for _, u in formation_registry.reference(world)}
    for _, unit in missions.units(world):
        initial = baseline.get(unit['name'], {})
        if any(unit.get(k) != initial.get(k) for k in ('formation_part', 'calculation_unit_id')):
            raise ValueError('计算分队身份、归属或库存比重被改写')
        if unit.get('formation_part'):
            carry = unit['formation'].get('partition_noncombat_remainder', 0)
            if type(carry) not in (int, float) or not math.isfinite(carry) or not 0 <= carry < 1:
                raise ValueError('计算分队非战斗减员余量非法')
    config = world.get('formation_groups')
    if not config:
        if any(u.get('formation_part') for _, u in missions.units(world)):
            raise ValueError('分队缺少冻结父单位总账')
        return
    if config['version'] not in LIMITS:
        raise ValueError('计算分队版本不支持')
    if world.get('formation_registry'):
        # The frozen group is an accounting reference; executable descendants
        # are re-derived from immutable origins rather than rewriting that pin.
        for group in effective_groups(world):
            members=[u for team,u in missions.units(world) if team==group['team'] and u['name'] in group['members']]
            if sum(u['personnel']['committed'] for u in members)!=group['committed']:
                raise ValueError('重编后的计算父单位投入总账不守恒')
            for category,count in group['equipment'].items():
                if sum(e['committed'] for u in members for e in u['equipment'] if e['category']==category)!=count:
                    raise ValueError('重编后的计算父单位装备总账不守恒')
        return
    index = {u['name']: (team, u) for team, u in missions.units(world)}
    seen = set()
    for group in config['groups']:
        members = [index[name] for name in group['members'] if name in index]
        if len(members) != len(group['members']) or len(set(group['members'])) != len(members):
            raise ValueError('计算分队名单缺失或重复')
        for team, unit in members:
            part = unit.get('formation_part', {})
            if (unit['name'] in seen or team != group['team'] or part.get('group_id') != group['id']
                    or part.get('numerator') != unit['personnel']['committed']
                    or part.get('denominator') != group['committed']):
                raise ValueError('计算分队不属于该父单位或重复累计')
            seen.add(unit['name'])
        if sum(u['personnel']['committed'] for _, u in members) != group['committed']:
            raise ValueError('计算父单位人员投入总账不守恒')
        for category, committed in group['equipment'].items():
            if sum(e['committed'] for _, u in members for e in u['equipment'] if e['category'] == category) != committed:
                raise ValueError('计算父单位装备投入总账不守恒')
    if seen != {u['name'] for _, u in missions.units(world) if u.get('formation_part')}:
        raise ValueError('存在未登记的计算分队')


def effective_groups(world):
    groups=copy.deepcopy(world.get('formation_groups',{}).get('groups',[]))
    if not world.get('formation_registry'):return groups
    from . import formation_registry
    for group in groups:
        group['members']=[u['name'] for team,u in missions.units(world) if team==group['team'] and
            any(origin.get('formation_part',{}).get('group_id')==group['id']
                for origin in formation_registry.origin_templates(world,u,team))]
    for team in ('red','blue'):
        for members in buckets(world,team):
            if not any(u.get('runtime_allocation') for u in members):continue
            origin=formation_registry.origin_templates(world,members[0],team)[0]
            if origin.get('formation_part'):continue
            groups.append(dict(id='runtime-root:'+formation_registry.key(team,origin),name=origin['name'],team=team,
                members=[u['name'] for u in members],equipment={e['category']:e['committed'] for e in origin['equipment']}))
    return groups


def buckets(world, team):
    result = {}
    for side, unit in missions.units(world):
        if side != team:
            continue
        part = unit.get('formation_part')
        if world.get('formation_registry'):
            from . import formation_registry
            origins=formation_registry.origin_templates(world,unit,side)
            keys={('group',u['formation_part']['group_id']) if u.get('formation_part') else ('unit',u['name']) for u in origins}
            if len(keys)!=1:raise ValueError('跨父级合编尚无独立目标计数契约')
            key=next(iter(keys))
        else:key = ('group', part['group_id']) if part else ('unit', unit['name'])
        result.setdefault(key, []).append(unit)
    return list(result.values())


def roster_digest(world):
    """Identity-only signature of the frame's actual executable roster."""
    return missions.digest(sorted((team,u['name'],str(u.get('calculation_unit_id') or u.get('historical_unit_id') or ''))
        for team,u in missions.units(world)))


def count(world, team, predicate, *, whole=False):
    """Read-only goal counting: one sourced parent, rather than one per fragment."""
    result = 0
    for members in buckets(world, team):
        alive = [u for u in members if u['personnel']['current'] > 0]
        result += bool(alive) and (all(predicate(u) for u in alive) if whole else any(predicate(u) for u in alive))
    return result


def prepositioned_route(world, unit):
    """A declared initial part already across need not cross back to prove arrival."""
    origin=unit
    if unit.get('runtime_allocation'):
        from . import formation_registry
        origins=formation_registry.origin_templates(world,unit)
        if len(origins)!=1:raise ValueError('跨根预置渡口资格尚未定义')
        origin=origins[0]
    if not origin.get('formation_part'):
        return None
    from . import crossings
    model = crossings.get_model(world)
    if not model:
        return None
    goal = world['mission']['definition']['objective']
    a, b = model['barrier']['a'], model['barrier']['b']
    sign = crossings.orientation(goal, a, b)
    if not sign:
        return None
    exit_bank = next((p for p in model['banks'].values() if crossings.orientation(p, a, b) * sign > 0), None)
    entry_bank = next((p for p in model['banks'].values() if crossings.orientation(p, a, b) * sign < 0), None)
    initial = next(u for _, u in missions.units(world['mission']['definition']['initial_state']) if u['name'] == origin['name'])
    if entry_bank and exit_bank and crossings.intersects(initial, entry_bank, model) and not crossings.intersects(initial, exit_bank, model):
        return {'entry': entry_bank, 'exit': exit_bank}
    return None


def prepositioned(world, unit):
    route = prepositioned_route(world, unit)
    if route is None:
        return False
    from . import crossings
    model = crossings.get_model(world)
    return crossings.intersects(unit, route['entry'], model) and not crossings.intersects(unit, route['exit'], model)


def observation(world):
    groups = []
    index = {u['name']: u for _, u in missions.units(world)}
    for group in effective_groups(world):
        members = [index[name] for name in group['members']]
        from . import motion_state
        precision=motion_state.summary(members)
        resources={k:sum(u['formation'][k] for u in members) for k in RESOURCES}
        if precision:resources['fuel_liters']=precision['fuel_microliters']//motion_state.SCALE
        groups.append({'id': group['id'], 'name': group['name'], 'team': group['team'],
            'personnel': {k: sum(u['personnel'][k] for u in members)
                          for k in ('committed', 'current', 'casualties', 'noncombat_losses')},
            'equipment': {category: {k: sum(e[k] for u in members for e in u['equipment'] if e['category'] == category)
                                    for k in ('committed', 'operational', 'damaged', 'destroyed')}
                          for category in group['equipment']},
            'resources': resources,
            **({'motion_precision':precision} if precision else {}),
            'normalized_stock_equivalent': {k: sum(u['logistics'][k] * scale(u) for u in members) for k in ('food', 'ammo')},
            'parts': [{'name': u['name'], 'calculation_unit_id': u['calculation_unit_id'],
                       'lat': u['lat'], 'lng': u['lng'], 'current': u['personnel']['current'],
                       'resource_scale': scale(u)} for u in members]})
    return {'version': world.get('formation_groups',{}).get('version',VERSION), 'groups': groups, 'resource_accounting': RESOURCE_ACCOUNTING,
            'scope': '同一历史父单位的互斥计算分队；总账只累计叶单位，粮弹按初始人员占比折合'}
