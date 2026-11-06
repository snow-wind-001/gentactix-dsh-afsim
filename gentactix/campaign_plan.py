"""Versioned campaign goal DAG, evaluated on committed physical observations.

This module scores metadata; it never moves units, produces losses, transfers
supplies or executes orders. Holding time is conservatively sampled at turn
boundaries, not a claim of continuous observation inside an unsampled interval.
"""
import copy
import math
import re

VERSION = 'campaign-objectives-1'
MAX_NODES = 64
STATES = {'pending', 'waiting_phase', 'waiting_time', 'waiting_dependency', 'waiting_arrival', 'blocked', 'active', 'holding', 'completed'}
NODE_FIELDS = {'id', 'label', 'team', 'unit_ids', 'after', 'not_before_seconds', 'condition',
               'hold_seconds', 'latch', 'operation_ids', 'assumption'}


def definition(world):
    return world.get('mission', {}).get('definition', {}).get('campaign_plan')


def unit_key(unit):
    return unit.get('calculation_unit_id') or unit.get('historical_unit_id') or unit.get('exercise_unit_id')


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(label + '字段缺失或越界')


def _text(value, label, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(label + '须为非空有界文字')


def _number(value, minimum, maximum, label, integer=False):
    if (type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value)
            or not minimum <= value <= maximum):
        raise ValueError(label + '须为范围内有限数值')


def _ids(value, allowed, label, *, empty=False, maximum=MAX_NODES):
    if (not isinstance(value, list) or len(value) > maximum or not value and not empty
            or any(not isinstance(i, str) or i not in allowed for i in value)
            or len(set(value)) != len(value)):
        raise ValueError(label + '须引用不重复的已登记身份')


def _units(world):
    from . import missions
    result = {}
    for team, unit in missions.units(world):
        identity = unit_key(unit)
        if not isinstance(identity, str) or identity in result:
            raise ValueError('目标图需要唯一历史、计算或演习单位ID')
        result[identity] = team, unit
    return result


def active_teams(world):
    """Only a validated, frozen historical scope can declare a solo transfer.

    An empty roster or editable goal is never authority to hide an opponent.
    Formation reallocation uses the frozen initial roster for this check.
    """
    snapshot = world.get('historical_initial')
    if snapshot is None:
        return ['red', 'blue']
    from . import historical_initial as hi, historical_operations as ho
    scope = ho.interaction_scope(snapshot)
    if scope is None:
        return ['red', 'blue']
    hi.restore(snapshot)
    reference = world['mission']['definition']['initial_state'] if world.get('formation_registry') else world
    teams = scope['active_teams']
    if {team for team, _ in _units(reference).values()} != set(teams):
        raise ValueError('非接敌转移目标图的执行阵营须匹配冻结史料，不能隐藏在场对手')
    if any(team not in teams for team, _ in _units(world).values()):
        raise ValueError('非接敌转移不能加入声明范围外的执行阵营')
    return list(teams)


def _region(value, world, area):
    from . import missions
    _fields(value, {'center', 'radius_km'}, '目标图地域')
    _fields(value['center'], {'lat', 'lng'}, '目标图地域中心')
    _number(value['center']['lat'], -90, 90, '目标纬度')
    _number(value['center']['lng'], -180, 180, '目标经度')
    _number(value['radius_km'], .01, 20, '目标地域半径')
    if area is None:
        spec = world.get('mission', {}).get('definition', {})
        area = {'center': spec.get('map_center'), 'radius_km': spec.get('map_radius_km')}
    if not area.get('center') or missions.distance(area['center'], value['center']) + value['radius_km'] > area['radius_km'] + .001:
        raise ValueError('目标图地域超出计算战区')


def _order(config):
    rows = {n['id']: n for n in config['nodes']}; order = []; visiting = set(); visited = set()
    def visit(identity):
        if identity in visiting:
            raise ValueError('会战目标图依赖成环')
        if identity in visited:
            return
        visiting.add(identity)
        for parent in rows[identity]['after']['node_ids']:
            visit(parent)
        visiting.remove(identity); visited.add(identity); order.append(identity)
    for identity in rows:
        visit(identity)
    return order


def validate_defensive_bindings(nodes):
    """Validate simultaneous opposing reach references, including unfilled templates.

    A defense reads only the opponent's physical reach condition, not their DAG
    progress. Restricting the target to reach also rules out recursive defenses.
    """
    index = {n['id']: n for n in nodes}
    for node in nodes:
        condition = node.get('condition')
        if not isinstance(condition, dict) or condition.get('kind') != 'defend':
            continue
        identity = condition.get('against_node')
        if not isinstance(identity, str) or identity == node['id'] or identity not in index:
            raise ValueError('防御目标须引用另一已登记的对抗突破目标')
        target = index[identity]
        if target['team'] == node['team'] or target.get('condition', {}).get('kind') != 'reach':
            raise ValueError('防御目标只能引用对方的reach突破条件，不能递归引用防御或控制目标')


def validate_config(value, world, *, area=None, termination_mode=None):
    _fields(value, {'version', 'nodes', 'outcomes', 'elimination_ends', 'assumption'}, '会战目标图')
    if value['version'] != VERSION:
        raise ValueError('会战目标图版本不支持')
    if termination_mode is None:
        termination_mode = world.get('mission', {}).get('definition', {}).get('termination_mode')
    if termination_mode != 'objectives':
        raise ValueError('新会战目标图须显式采用目标完成制；旧限时局不隐式升级')
    _text(value['assumption'], '目标图估计依据')
    if type(value['elimination_ends']) is not bool:
        raise ValueError('目标图全军失能终止策略须显式为布尔值')
    nodes = value['nodes']
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        raise ValueError('目标图须包含1至64个节点')
    reference=world['mission']['definition']['initial_state'] if world.get('formation_registry') else world
    identities = _units(reference); names = set(); teams = active_teams(world)
    for node in nodes:
        _fields(node, NODE_FIELDS, '目标图节点')
        identity = node['id']
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,79}', identity) or identity in names:
            raise ValueError('目标图节点ID须唯一且有界')
        names.add(identity)
        if node['team'] not in teams:
            raise ValueError('目标图节点阵营非法')
        _text(node['label'], '目标名称', 120); _text(node['assumption'], '目标估计依据')
        _ids(node['unit_ids'], identities, '目标承担单位', maximum=1024)
        if any(identities[i][0] != node['team'] for i in node['unit_ids']):
            raise ValueError('目标图不能将敌方部队作为己方承担单位')
        for key in ('not_before_seconds', 'hold_seconds'):
            _number(node[key], 0, 315360000, '目标时点/保持时长', integer=True)
        if type(node['latch']) is not bool:
            raise ValueError('目标达成锁存须显式为布尔值')
        _fields(node['after'], {'mode', 'node_ids'}, '目标依赖')
        if node['after']['mode'] not in ('all', 'any'):
            raise ValueError('目标依赖模式须为all或any')
        if not isinstance(node['operation_ids'], list) or len(node['operation_ids']) > 16:
            raise ValueError('目标来源关联须为有界事件列表')
        if any(not isinstance(i, str) for i in node['operation_ids']) or len(set(node['operation_ids'])) != len(node['operation_ids']):
            raise ValueError('目标来源事件ID须为不重复文字')
        from . import historical_links
        for op in node['operation_ids']:
            snapshot = world.get('historical_initial')
            if snapshot is None:
                raise ValueError('目标来源关联缺少冻结历史版本')
            historical_links.find(snapshot, op)
        condition = node['condition']
        if not isinstance(condition, dict) or condition.get('kind') not in ('control', 'reach', 'defend', 'preserve', 'resources', 'mission_metric'):
            raise ValueError('目标图条件类型未登记')
        kind = condition['kind']
        if kind in ('control', 'reach', 'defend'):
            _fields(condition, {'kind', 'region', 'minimum_personnel'}
                    | ({'against_node'} if kind == 'defend' else set()), '地域目标')
            _region(condition['region'], world, area)
            _number(condition['minimum_personnel'], 1, 100000000, '目标最少人员', integer=True)
        elif kind == 'preserve':
            _fields(condition, {'kind', 'minimum_fraction'}, '兵力保存目标')
            _number(condition['minimum_fraction'], .000001, 1, '兵力保存比例')
        elif kind == 'resources':
            _fields(condition, {'kind', 'minimum_food', 'minimum_ammo'}, '随队资源目标')
            for field in ('minimum_food', 'minimum_ammo'):
                _number(condition[field], 0, 100, '随队资源阈值')
        else:
            _fields(condition, {'kind', 'field', 'comparison', 'value'}, '既有状态目标')
            if condition['field'] not in ('network', 'organization', 'accepted'):
                raise ValueError('目标图只能读取已登记的交通、组织或接收状态')
            if condition['field'] == 'accepted':
                if condition['comparison'] != 'is_true' or condition['value'] is not True:
                    raise ValueError('接收目标须明确为is_true')
            else:
                if condition['comparison'] not in ('at_least', 'at_most'):
                    raise ValueError('状态比较只支持at_least或at_most')
                _number(condition['value'], 0, 100, '状态阈值')
    index = {n['id']: n for n in nodes}
    for node in nodes:
        after = node['after']
        _ids(after['node_ids'], names, '前置目标', empty=after['mode'] == 'all')
        if any(index[i]['team'] != node['team'] for i in after['node_ids']):
            raise ValueError('己方任务依赖不能冒用敌方目标完成状态')
    validate_defensive_bindings(nodes)
    _order(value)
    _fields(value['outcomes'], {'red', 'blue'}, '双方会战目标')
    for team, row in value['outcomes'].items():
        _fields(row, {'mode', 'node_ids'}, '阵营总目标')
        if row['mode'] not in ('all', 'any'):
            raise ValueError('阵营总目标模式非法')
        _ids(row['node_ids'], names, '阵营目标引用', empty=team not in teams)
        if team not in teams and row['node_ids']:
            raise ValueError('非接敌范围外一方不得配置虚构目标')
        if any(index[i]['team'] != team for i in row['node_ids']):
            raise ValueError('阵营总目标不能引用敌方目标')
    return copy.deepcopy(value)


def bind(value, world, goal, area):
    return None if value is None else validate_config(value, world, area=area, termination_mode=goal.get('termination_mode'))


def validate_inputs(snapshot, parameters):
    """Validate global goal inputs before actor quantities/deployments exist.

    The identity-only context is not a simulated world. Reuse the same DAG,
    source, geometry and numerical contract as final binding, without inventing
    strengths to validate a public configuration stage.
    """
    value=parameters.get('campaign_plan')
    if value is None:return None
    from . import campaign_estimates
    source={u['id']:u for u in snapshot['definition']['units']}
    context={'historical_initial':snapshot,**{team+'_units':[
        {'historical_unit_id':identity} for parent in parameters['actors'] if source[parent]['team']==team
        for identity in campaign_estimates.goal_members(parameters,[parent])] for team in ('red','blue')}}
    return validate_config(value,context,area=parameters['area'],termination_mode=parameters['goal'].get('termination_mode'))


def transfer_template(snapshot, identities):
    """Unfilled transport goals over source identities, never a deployment."""
    from . import historical_operations as ho
    scope=ho.interaction_scope(snapshot)
    if not scope:raise ValueError('转移目标模板须有冻结的非接敌来源范围')
    team=scope['active_teams'][0]
    names={u['id']:u['name'] for u in snapshot['definition']['units']}
    note='待填写转移终点、保存与资源阈值的估计依据；不是史实逐军部署、损失或自动命令。'
    def node(identity,label,chosen,condition,after=(),latch=False):
        return dict(id=identity,label=label,team=team,unit_ids=list(chosen),after={'mode':'all','node_ids':list(after)},
            not_before_seconds=0,hold_seconds=0,latch=latch,condition=condition,operation_ids=[],assumption=note)
    nodes=[node('transfer-'+str(n+1),names[i]+'转移到达',[i],
        {'kind':'reach','region':{'center':{'lat':None,'lng':None},'radius_km':None},'minimum_personnel':None},latch=True)
        for n,i in enumerate(identities)]
    nodes.append(node('transfer-preserve','到达后保存投入兵力',identities,
        {'kind':'preserve','minimum_fraction':None},[n['id'] for n in nodes]))
    nodes.append(node('transfer-resources','到达后随队资源',identities,
        {'kind':'resources','minimum_food':None,'minimum_ammo':None},['transfer-preserve']))
    return dict(version=VERSION,nodes=nodes,
        outcomes={t:dict(mode='all',node_ids=['transfer-resources'] if t==team else []) for t in ('red','blue')},
        elimination_ends=True,assumption=note)


def _input_hash(world):
    from . import campaign, missions
    from . import campaign_lifecycle,unit_participation
    # Only predicate inputs belong here. Receipt provenance/normalization may
    # be appended after scoring and is protected by its own domain guards.
    return missions.digest({'units': [(team, {'id':unit_key(u),'lat':float(u['lat']),'lng':float(u['lng']),
        'current':u['personnel']['current'],'committed':u['personnel']['committed'],
        'suppression':float(u.get('formation',{}).get('suppression',0)),
        'food':float(u['logistics']['food']),'ammo':float(u['logistics']['ammo']),
        'release_seconds':float(campaign.release_seconds(world,u)),
        **({'in_operation':unit_participation.in_operation(world,u)} if 'unit_participation' in world else {})}) for team, u in missions.units(world)],
        'turn': world['mission']['turn'], 'elapsed_seconds': world['simulation_clock']['elapsed_seconds'],
        'metrics': {k: world['mission'][k] for k in ('network', 'organization', 'accepted')},
        **({'lifecycle_sample_phase':campaign_lifecycle.sample_phase(world)} if campaign_lifecycle.definition(world) else {})})


def _seal(state):
    from . import missions
    state['state_hash'] = missions.digest({k: v for k, v in state.items() if k != 'state_hash'})


def initialize(world):
    config = definition(world)
    if config is None:
        return
    from . import missions
    validate_config(config, world)
    state = {'version': VERSION, 'source': 'host_goal_evaluator', 'plan_hash': missions.digest(config),
        'turn': 0, 'sample_at': 0, 'input_hash': _input_hash(world),
        'nodes': {n['id']: dict(status='pending', condition=False, held_seconds=0, satisfied_since=None,
            completed_at=None, reason='尚未产生第一轮物理观察', metrics={}) for n in config['nodes']},
        'outcomes': {'red': False, 'blue': False}, 'side_progress': {'red': 0, 'blue': 0},
        'resolution': 'active', 'last_changes': []}
    _seal(state); world['campaign_plan'] = state


def validate_state(world):
    config = definition(world); state = world.get('campaign_plan')
    if config is None:
        if state is not None:
            raise ValueError('本局未冻结目标图，不能注入完成状态')
        return
    from . import missions
    validate_config(config, world)
    _fields(state, {'version', 'source', 'plan_hash', 'turn', 'sample_at', 'input_hash', 'nodes', 'outcomes',
                    'side_progress', 'resolution', 'last_changes', 'state_hash'}, '目标图状态')
    checks={'版本/来源':state['version']==VERSION and state['source']=='host_goal_evaluator',
        '配置摘要':state['plan_hash']==missions.digest(config),'回合':state['turn']==world['mission']['turn'],
        '采样时钟':state['sample_at']==world['simulation_clock']['elapsed_seconds'],
        '目标输入摘要':state['input_hash']==_input_hash(world),
        '状态摘要':state['state_hash']==missions.digest({k:v for k,v in state.items() if k!='state_hash'})}
    if not all(checks.values()):
        raise ValueError('目标图状态与冻结定义、物理观察或回合不一致：'+','.join(k for k,v in checks.items() if not v))
    _fields(state['nodes'], {n['id'] for n in config['nodes']}, '目标图节点状态')
    for row in state['nodes'].values():
        _fields(row, {'status', 'condition', 'held_seconds', 'satisfied_since', 'completed_at', 'reason', 'metrics'}, '目标节点状态')
        if not isinstance(row['status'], str) or row['status'] not in STATES or type(row['condition']) is not bool:
            raise ValueError('目标节点状态非法')
        _number(row['held_seconds'], 0, state['sample_at'], '目标保持时长', integer=True)
        for field in ('satisfied_since', 'completed_at'):
            if row[field] is not None:
                _number(row[field], 0, state['sample_at'], '目标发生时点', integer=True)
    for field in ('outcomes', 'side_progress'):
        _fields(state[field], {'red', 'blue'}, '双方目标状态')
    if any(type(x) is not bool for x in state['outcomes'].values()):
        raise ValueError('双方目标判定须为布尔值')
    for value in state['side_progress'].values():
        _number(value, 0, state['turn'], '阵营连续达标回合', integer=True)
    for team in set(('red','blue'))-set(active_teams(world)):
        if state['outcomes'][team] or state['side_progress'][team] or state['resolution']==team:
            raise ValueError('非接敌范围外一方不能产生达标、进度或胜利')
    if state['resolution'] not in ('active', 'red', 'blue', 'draw') or not isinstance(state['last_changes'], list) or len(state['last_changes']) > 128:
        raise ValueError('目标图结算或变化列表非法')
    owner=missions.objective_team(world['mission']['definition'])
    expected_winner=state['resolution'] if state['resolution'] in ('red','blue') else None
    if (world['mission']['status'] != ('active' if state['resolution']=='active' else 'completed')
            or world['mission']['winner'] != expected_winner or world['mission']['progress'] != state['side_progress'][owner]):
        raise ValueError('任务总结果与目标图状态不一致')


def selection_groups(world,node,index=None):
    index=index or _units(world)
    if not world.get('formation_registry'):return [[index[i][1]] for i in node['unit_ids']]
    from . import formation_registry
    return [formation_registry.descendants(world,i,node['team']) for i in node['unit_ids']]


def _predicate(world, node, index):
    from . import campaign, missions,unit_participation,suppression_state
    groups=selection_groups(world,node,index)
    chosen=list({unit_key(u):u for group in groups for u in group}.values())
    alive = [u for u in chosen if u['personnel']['current'] > 0]
    ready = [u for u in alive if campaign.release_seconds(world, u) == 0 and unit_participation.in_operation(world,u)]
    condition = node['condition']; kind = condition['kind']
    if kind in ('control', 'reach', 'defend'):
        region = condition['region']
        threshold = world['mission']['definition'].get('combined_rules', {}).get('suppression_control_threshold', 100)
        own = sum(u['personnel']['current'] for u in ready
            if missions.distance(u, region['center']) <= region['radius_km']
            and (kind == 'reach' or suppression_state.value(u) < threshold))
        enemy = sum(u['personnel']['current'] for team, u in index.values()
            if team != node['team'] and u['personnel']['current'] > 0 and campaign.release_seconds(world, u) == 0
            and missions.distance(u, region['center']) <= region['radius_km'])
        result = own >= condition['minimum_personnel'] and (kind == 'reach' or enemy == 0)
        metrics = {'own_personnel_in_region': own, 'enemy_personnel_in_region': enemy}
        if kind == 'defend':
            target = next(n for n in definition(world)['nodes'] if n['id'] == condition['against_node'])
            breach, target_metrics, _, _ = _predicate(world, target, index)
            result = own >= condition['minimum_personnel'] and not breach
            metrics.update(against_node=target['id'], breakthrough=breach,
                enemy_personnel_in_core=target_metrics['own_personnel_in_region'],
                enemy_core_minimum_personnel=target['condition']['minimum_personnel'])
    elif kind == 'preserve':
        committed = sum(u['personnel']['committed'] for u in chosen)
        current = sum(u['personnel']['current'] for u in chosen)
        result = current >= committed * condition['minimum_fraction']
        metrics = {'current': current, 'committed': committed, 'fraction': current / committed if committed else 0}
    elif kind == 'resources':
        ready_ids={unit_key(u) for u in ready}
        ready_groups=sum(bool(live) and all(unit_key(u) in ready_ids for u in live)
            for live in ([u for u in group if u['personnel']['current']>0] for group in groups))
        result = ready_groups == len(groups) and all(u['logistics']['food'] >= condition['minimum_food']
            and u['logistics']['ammo'] >= condition['minimum_ammo'] for u in ready)
        metrics = {'ready_units': ready_groups, 'selected_units': len(groups),
            'minimum_food': min((u['logistics']['food'] for u in chosen), default=0),
            'minimum_ammo': min((u['logistics']['ammo'] for u in chosen), default=0)}
    else:
        value = world['mission'][condition['field']]
        compare = condition['comparison']
        result = value is True if compare == 'is_true' else value >= condition['value'] if compare == 'at_least' else value <= condition['value']
        metrics = {'field': condition['field'], 'value': value}
    reason = '' if result else '未达到冻结目标条件'
    status = 'active'
    if kind not in ('preserve', 'mission_metric') and not ready:
        rear=any(campaign.release_seconds(world,u)==0 and not unit_participation.in_operation(world,u) for u in alive)
        status = 'blocked' if rear else 'waiting_arrival' if alive else 'blocked'
        reason = '承担部队处于后方待命或重新投入途中' if rear else '承担部队尚未激活' if alive else '承担部队无可用人员'
    return bool(result), metrics, status, reason


def _combine(mode, values):
    return all(values) if mode == 'all' else any(values)


def evaluate(world):
    config = definition(world)
    if config is None:
        raise ValueError('本局没有会战目标图')
    from . import missions
    previous = world.get('campaign_plan')
    if previous is None:
        raise ValueError('目标图运行状态缺失，不能自动重置进度')
    mission = world['mission']; elapsed = world['simulation_clock']['elapsed_seconds']
    fingerprint = _input_hash(world)
    if previous['turn'] == mission['turn'] and previous['sample_at'] == elapsed:
        if previous['input_hash'] != fingerprint:
            raise ValueError('同回合物理观察已改变，不能重复结算目标图')
        validate_state(world)
        from . import campaign_lifecycle
        campaign_lifecycle.validate_state(world)
        return mission
    if previous['turn'] + 1 != mission['turn'] or elapsed <= previous['sample_at']:
        raise ValueError('目标图须逐轮随物理时钟连续推进')
    if previous['state_hash'] != missions.digest({k: v for k, v in previous.items() if k != 'state_hash'}):
        raise ValueError('上一轮目标图状态已改变，拒绝继续')
    state = copy.deepcopy(previous); state['last_changes'] = []; index = _units(world)
    nodes = {n['id']: n for n in config['nodes']}
    from . import campaign_lifecycle
    for identity in _order(config):
        node = nodes[identity]; old = previous['nodes'][identity]; row = state['nodes'][identity]
        if not campaign_lifecycle.goal_ready(world,identity):
            row.update(status='waiting_phase',condition=False,metrics={},held_seconds=0,satisfied_since=None,completed_at=None,
                reason='本轮物理观察尚未轮到该阶段；激活后的新回合才评分')
            if row['status']!=old['status']:
                state['last_changes'].append({'node_id':identity,'before':old['status'],'after':row['status'],'at_seconds':elapsed})
            continue
        truth, metrics, status, reason = _predicate(world, node, index)
        deps = _combine(node['after']['mode'], [state['nodes'][i]['status'] == 'completed' for i in node['after']['node_ids']])
        row.update(condition=truth, metrics=metrics)
        if node['latch'] and old['completed_at'] is not None:
            row.update(status='completed', reason='已完成里程碑；当前条件另列，不表示永久控制')
        elif elapsed < node['not_before_seconds']:
            row.update(status='waiting_time', held_seconds=0, satisfied_since=None, completed_at=None, reason='未到目标激活时点')
        elif not deps:
            row.update(status='waiting_dependency', held_seconds=0, satisfied_since=None, completed_at=None, reason='前置目标尚未达成')
        elif truth:
            # No retroactive credit: the first positive endpoint starts a hold.
            continuing = old['status'] in ('holding', 'completed') and old['condition']
            since = old['satisfied_since'] if continuing else elapsed
            held = elapsed - since
            complete = held >= node['hold_seconds']
            row.update(status='completed' if complete else 'holding', held_seconds=held, satisfied_since=since,
                completed_at=old['completed_at'] if complete and continuing and old['completed_at'] is not None else elapsed if complete else None,
                reason='目标条件满足' if complete else '按回合端点采样，保持时间尚不足')
        else:
            row.update(status=status, held_seconds=0, satisfied_since=None, completed_at=None, reason=reason)
        if row['status'] != old['status']:
            state['last_changes'].append({'node_id': identity, 'before': old['status'], 'after': row['status'], 'at_seconds': elapsed})
    lifecycle_done=campaign_lifecycle.evaluate(world,state['nodes'])
    teams = active_teams(world)
    for team, goal in config['outcomes'].items():
        result = team in teams and bool(goal['node_ids']) and _combine(goal['mode'], [state['nodes'][i]['status'] == 'completed' for i in goal['node_ids']])
        state['outcomes'][team] = result
        state['side_progress'][team] = previous['side_progress'][team] + 1 if result and lifecycle_done else 0
    achieved = {team: state['side_progress'][team] >= mission['definition']['required_turns'] for team in teams}
    alive = {team: any(t == team and u['personnel']['current'] > 0 for t, u in index.values()) for team in teams}
    winner = None; reason = ''; resolution = 'active'
    if config['elimination_ends'] and not all(alive.values()):
        if not any(alive.values()):
            resolution = 'draw'; reason = '转移部队均无可用人员，目标未达成' if len(teams)==1 else '双方均无可用人员'
        else:
            winner = 'red' if alive['red'] else 'blue'; resolution = winner
            reason = '按显式全军失能终止策略结算'
    elif len(teams)>1 and all(achieved.values()):
        resolution = 'draw'; reason = '双方目标同时达成，按冻结目标图判为平局'
    elif any(achieved.values()):
        winner = next(team for team in teams if achieved[team]); resolution = winner
        reason = ('红方' if winner == 'red' else '蓝方') + '目标图达成'
    state.update(turn=mission['turn'], sample_at=elapsed, input_hash=fingerprint, resolution=resolution)
    _seal(state); world['campaign_plan'] = state
    owner = missions.objective_team(mission['definition'])
    mission['progress'] = state['side_progress'][owner]
    spec = mission['definition']
    mission['metrics'] = {**mission.get('metrics', {}),
        **{team+'_available': sum(u['personnel']['current'] for t, u in index.values() if t == team) for team in ('red', 'blue')},
        **{team+'_in_goal': sum(u['personnel']['current'] > 0 and missions.distance(u, spec['objective']) <= spec['goal_radius_km']
            for t, u in index.values() if t == team) for team in ('red', 'blue')},
        'network': mission['network'], 'organization': mission['organization'], 'condition': state['outcomes'][owner] and lifecycle_done,
        'campaign_plan': {'red': state['outcomes']['red'], 'blue': state['outcomes']['blue'],
            'completed_nodes': sum(row['status'] == 'completed' for row in state['nodes'].values()), 'total_nodes': len(nodes),
            'source': 'host_goal_evaluator'}}
    mission.update(status='active' if resolution == 'active' else 'completed', winner=winner, reason=reason)
    campaign_lifecycle.settle(world)
    return mission


def observation(world, *, kind='nodes', node_id=None, offset=0, limit=8, view_version=None):
    config = definition(world)
    if config is None:
        return {'ok': False, 'error': '当前冻结想定未配置会战目标图'}
    validate_state(world)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError('目标图查询须为有效分页，每页1至16项')
    state = world['campaign_plan']
    if offset and view_version is None:
        raise ValueError('目标图翻页须沿用第一页view_version；不能拼接不同回合观察')
    if view_version is not None and view_version != state['state_hash']:
        raise ValueError('目标图观察已变化，请从第一页重新读取')
    if kind not in ('nodes', 'members'):
        raise ValueError('目标图查询类型须为nodes或members')
    node = next((n for n in config['nodes'] if n['id'] == node_id), None)
    if node_id is not None and node is None:
        raise ValueError('目标图没有所选节点')
    if kind == 'members':
        if node is None:
            raise ValueError('查询目标承担单位须指定node_id')
        index = _units(world)
        members=[dict(unit_id=unit_key(u),team=node['team'],name=u['name'],
            **({'selection_unit_id':identity} if world.get('formation_registry') else {}))
            for identity,group in zip(node['unit_ids'],selection_groups(world,node,index)) for u in group]
        total=len(members);rows=members[offset:offset+limit]
    else:
        selected = [node] if node is not None else config['nodes']; total = len(selected)
        rows = [{**{k: copy.deepcopy(v) for k, v in row.items() if k != 'unit_ids'},
            'unit_count': len(row['unit_ids']), 'unit_sample': row['unit_ids'][:8],
            **({'active_entity_count':len({unit_key(u) for group in selection_groups(world,row) for u in group}),
                'unit_count_scope':'冻结承担身份数；active_entity_count为当前互斥执行实体数'}
                if world.get('formation_registry') else {}),
            'member_args': {'kind': 'members', 'node_id': row['id'], 'limit': 16, 'view_version': state['state_hash']},
            'state': copy.deepcopy(state['nodes'][row['id']])} for row in selected[offset:offset + limit]]
    return {'ok': True, 'readonly': True, 'version': VERSION, 'turn': state['turn'],
        'plan_hash':state['plan_hash'],'view_version':state['state_hash'],
        'sample_at':state['sample_at'],'required_turns':world['mission']['definition']['required_turns'],
        'mission_status':world['mission']['status'],'winner':world['mission']['winner'],
        'outcomes_scope':'当前采样条件；仍须满足required_turns连续回合。resolution才是程序全局结算。',
        'scope': '宿主对物理观察的目标评分；不是历史事实、交战执行器或自动下令器。保持时间仅按回合端点采样。',
        'active_teams': active_teams(world),
        'outcomes': copy.deepcopy(state['outcomes']), 'side_progress': copy.deepcopy(state['side_progress']),
        'resolution': state['resolution'], 'total': total, 'offset': offset, kind: rows,
        'next_args': {'kind': kind, **({'node_id': node_id} if node_id else {}), 'offset': offset + limit,
            'limit': limit, 'view_version': state['state_hash']} if offset + limit < total else None}


def defensive_instruction(world):
    config = definition(world)
    return ('defend的region是本方就绪兵力的防御部署区，允许前沿接敌；against_node引用对方reach的突破核心和人数门槛。'
        '对方满足核心物理条件即打断防守保持，不等待对方目标激活、依赖、锁存或保持时长；敌人撤出后重新计时。'
        'enemy_personnel_in_region是本方部署区内敌军，enemy_personnel_in_core是指定突破核心内敌军，两者不能互换；核心为0不表示部署区没有敌军。'
        '对方保持时长决定其reach目标何时完成，不是defend首次中断的前提。'
        if config and any(n['condition']['kind'] == 'defend' for n in config['nodes']) else '')


def instruction(world):
    if definition(world) is None:
        return ''
    import json
    defensive = defensive_instruction(world)
    return ('\n【会战目标图】胜负只由宿主对轮末物理观察评分；原据点标志不是全局完成条件。'
        '方向可并行、可依赖；latch是已完成里程碑，当前控制另看condition。'
        '保持时长从首次满足的回合端点起保守计时，不追补此前整轮。'
        '目标图不自动下令，必须给所有可行动单位明确命令或待命依据。'
        '不得返回campaign_plan、胜负或完成进度；只提交合法物理估计及账目。'
        '可调用get_campaign_objectives按next_args读完节点，member_args读取承担单位，不能只看第一页。'
        +defensive+'当前有界目标观察：'+json.dumps(observation(world, limit=4), ensure_ascii=False))


def rebind_exercise(spec, baseline):
    """Rebind explicit exercise identities; refuse removal of an entire goal's force."""
    config = baseline.get('campaign_plan')
    if config is None:
        return
    from . import missions
    mapping = {}
    for team, unit in missions.units(spec['initial_state']):
        origin = unit.get('historical_reference', {}).get('id')
        if origin is None:
            raise ValueError('合成目标图单位缺少冻结基础身份')
        identity = unit_key(unit)
        if identity is None:
            identity = 'exercise.' + missions.digest({'team': team, 'name': unit['name'], 'basis_id': origin})[:24]
            unit['exercise_unit_id'] = identity
        mapping.setdefault(origin, []).append(identity)
    value = copy.deepcopy(config)
    for node in value['nodes']:
        ids = list(dict.fromkeys(identity for old in node['unit_ids'] for identity in mapping.get(old, [])))
        if not ids:
            raise ValueError('删除了目标“'+node['label']+'”的全部承担单位；须先明确重配目标，不能静默宣告完成')
        node['unit_ids'] = ids
        node['assumption'] += '；合成改编按基础身份映射实际编组，不是历史增援。'
    value['assumption'] += '；合成改编沿用目标，并显式重绑定当前单位。'
    spec['campaign_plan'] = value
