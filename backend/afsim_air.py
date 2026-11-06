"""Closed, aggregate teaching air packages; flight and effects execute in AFSIM.

These are explicit synthetic coefficients, not reconstructed aircraft inventories,
radar tracks, ballistic models or historical casualty estimates. No implicit pool
is created for a battle outside the two versioned air-support teaching missions.
"""
import copy
import hashlib
import math
from gentactix import missions, air_assets

VERSION = 'afsim-air-teaching-1'
CONFIG = {'missions': ['AJ18-local-v1', 'AJ19-local-v1'], 'aircraft': 8,
          'package': 2, 'ordnance': 24, 'fuel': 48, 'fuel_per_aircraft': 2,
          'preparation_s': 60, 'speed_mps': 120, 'altitude_m': 3000,
          'target_radius_km': .5, 'personnel_per_effective_aircraft': 8,
          'equipment_per_effective_aircraft': 1,
          'blue_aa_fraction': .5, 'red_aa_fraction': 0.0}
CONFIG_HASH = missions.digest(CONFIG)
ASSUMPTIONS = ('合成教学航空分队，非历史编制：红方初始8架、每任务2架；蓝方未配置航空兵力。'
               '入场点为局部地图边界，非历史机场；防空损失系数、战损及油弹单位均为教学假设；'
               '全知目标、无雷达探测/气象/DEM遮蔽模型，仅支持回合内完成并返场的任务。')


def state(world):
    from gentactix import combined_arms
    if air_assets.world_definition(world) is not None:
        if not combined_arms.is_combined(world):raise ValueError('具名航空资源须绑定分类防空与目标防护模型')
        return air_assets.world_state(world)
    if world.get('mission', {}).get('id') not in CONFIG['missions'] and not combined_arms.air_enabled(world):
        if world.get('air_operations'):
            raise ValueError('本想定未登记航空模型，不能迁入其他时代的航空兵力')
        return None
    saved = world.get('air_operations')
    if saved is None:
        saved = {'version': VERSION, 'config_hash': CONFIG_HASH, 'assumptions': ASSUMPTIONS,
                 'assets': {team: {'committed': CONFIG['aircraft'] if team == 'red' else 0,
                                  'ready': CONFIG['aircraft'] if team == 'red' else 0,
                                  'destroyed': 0, 'sorties': 0,
                                  'ordnance': CONFIG['ordnance'] if team == 'red' else 0,
                                  'fuel': CONFIG['fuel'] if team == 'red' else 0} for team in ('red', 'blue')},
                 'missions': [], 'recent_missions': [], 'last_turn': 0}
        if combined_arms.is_combined(world):
            saved['assumptions']+=' 本想定防空由实际分类装备、弹药、范围、高度、压制及损失余量计算；目标防护、工事和展开影响空袭效果。'
    if saved.get('version') != VERSION or saved.get('config_hash') != CONFIG_HASH:
        raise ValueError('航空模型参数或版本已改变，不能静默重算已有对局')
    for team in ('red', 'blue'):
        pool = saved['assets'][team]
        if any(type(pool.get(k)) is not int or pool[k] < 0 for k in
               ('committed', 'ready', 'destroyed', 'sorties', 'ordnance', 'fuel')):
            raise ValueError('航空兵力、油弹计数非法')
        initial = CONFIG['aircraft'] if team == 'red' else 0
        if pool['committed'] != initial or pool['ready'] + pool['destroyed'] != initial:
            raise ValueError('航空兵力账不守恒')
        if pool['ordnance'] > (CONFIG['ordnance'] if team == 'red' else 0) or pool['fuel'] > (CONFIG['fuel'] if team == 'red' else 0):
            raise ValueError('航空油弹库存超出初始投入')
    return copy.deepcopy(saved)


def _pool_models(world, baseline):
    definition=air_assets.world_definition(world)
    if definition is not None:
        return {identity:{'rules':p['rules'],'entry':p['entry'],'account':baseline['pools'][identity],
                          'team':p['team']} for identity,p in definition['pools'].items()}
    spec=world['mission']['definition'];center=spec['map_center']
    entry={'lat':center['lat']-spec['map_radius_km']/110.57,'lng':center['lng']}
    return {team:{'rules':CONFIG,'entry':entry,'account':baseline['assets'][team],'team':team}
            for team in ('red','blue')}


def _reservations(world, orders, baseline):
    if baseline is None:raise ValueError('当前想定没有登记航空兵力')
    models=_pool_models(world,baseline);definition=air_assets.world_definition(world)
    teams={u['name']:team for team,u in missions.units(world)};reserved={i:0 for i in models};selected=[]
    for order in orders:
        if order['action']!='air_support':
            if 'air_pool' in order:raise ValueError('只有航空任务可以指定航空资源池')
            continue
        if not order.get('target'):continue  # Legacy untargeted support does not launch aircraft.
        team=teams[order['unit']]
        if definition is not None:
            from gentactix import air_availability
            identity,pool_spec=air_assets.select(definition,baseline,team,order.get('air_pool'))
            air_availability.require(world,pool_spec)
        else:
            if 'air_pool' in order:raise ValueError('旧教学航空池不支持具名航空资源池')
            identity=team
        model=models[identity];cfg=model['rules'];pool=model['account']
        reserved[identity]+=cfg['package'];n=reserved[identity]
        if n>pool['ready'] or n>pool['ordnance'] or n*cfg['fuel_per_aircraft']>pool['fuel']:
            raise ValueError('整批航空命令超出该航空兵力或油弹；不能借用其他航空部队或地面库存')
        selected.append((order,identity,model))
    return selected,models


def compile_air(scene, world, orders):
    """Validate reservations, then generate WSF aircraft/routes/callbacks."""
    baseline = state(world)
    targeted = [o for o in orders if o['action'] == 'air_support' and o.get('target')]
    if not targeted:
        return {'state': baseline, 'tasks': [], 'script': ''}
    if baseline is None:
        raise ValueError('当前想定没有登记航空兵力')
    selected,pool_models=_reservations(world,orders,baseline)
    units = {u['name']: (team, u) for team, u in missions.units(world)}
    identities = {(v['team'], v['name']): k for k, v in scene['entities'].items()}
    spec = world['mission']['definition']; turn = world['mission']['turn'] + 1
    script = ['execute at_time 0.001 sec absolute']
    for identity in scene['entities']:
        script += [f' WsfSimulation.FindPlatform("{identity}").SetAuxData("gtx_air_damage",0.0);',
                   f' WsfSimulation.FindPlatform("{identity}").SetAuxData("gtx_air_equipment",0.0);']
    script.append('end_execute'); tasks = []
    for order,pool_id,pool_model in selected:
        cfg=pool_model['rules'];entry=pool_model['entry']
        team, requester = units[order['unit']]; enemy, target = units[order['target']]
        if team == enemy or target['personnel']['current'] <= 0:
            raise ValueError('航空打击目标无效')
        travel = missions.distance(entry, target) * 1000 / cfg['speed_mps']
        if air_assets.world_definition(world) is not None:
            from gentactix import air_availability
            pool_spec=air_assets.world_definition(world)['pools'][pool_id]
            air_availability.require(world,pool_spec,cfg['preparation_s']+2*travel+120)
        if cfg['preparation_s'] + 2 * travel + 120 >= scene['seconds']:
            raise ValueError('当前回合不足以完成航空出动和返场，请使用更长回合的想定')
        identity = 'a' + hashlib.sha256(f'{turn}:{team}:{requester["name"]}:{target["name"]}'.encode()).hexdigest()[:20]
        target_id = identities[(enemy, target['name'])]
        cover = .4 if any(o['unit'] == target['name'] and o['action'] == 'conceal' for o in orders) else spec['rules']['cover']
        aa = CONFIG[enemy + '_aa_fraction']
        combined=bool(world.get('combined_arms'))
        task = {'id': identity, 'team': team, 'requester': requester['name'], 'target': target['name'],
                'turn': turn, 'package': cfg['package'], 'entry': copy.deepcopy(entry),
                'aim': {'lat': target['lat'], 'lng': target['lng']},
                'altitude_m': cfg['altitude_m'], 'source': baseline['version'],
                **({'pool_id':pool_id} if 'pools' in baseline else {})}
        tasks.append(task)
        def event(phase):
            # Split coordinates avoid ostream's six-significant-digit truncation.
            return [f' writeln("GTXAIREVENT|{identity}|{phase}|",(int)(TIME_NOW*1000),"|",(int)PLATFORM.Latitude(),"|",(int)((PLATFORM.Latitude()-(int)PLATFORM.Latitude())*100000000),"|",(int)PLATFORM.Longitude(),"|",(int)((PLATFORM.Longitude()-(int)PLATFORM.Longitude())*100000000));']
        script += [f'platform_type {identity}_type WSF_PLATFORM', ' mover WSF_AIR_MOVER',
                   '  update_interval 1 sec', '  at_end_of_path stop', ' end_mover',
                   ' on_initialize', '  PLATFORM.SetAuxData("lost",0.0);',
                   '  PLATFORM.SetAuxData("hit",0.0);', '  PLATFORM.SetAuxData("damage",0.0);',
                   '  PLATFORM.SetAuxData("equipment",0.0);', ' end_on_initialize',
                   ' execute at_time 0.01 sec relative'] + event('launch') + [' end_execute',
                   ' script void GtxStrike()', f' WsfPlatform target=WsfSimulation.FindPlatform("{target_id}");',
                   f' if (GtxDistance(target.Latitude(),target.Longitude(),{target["lat"]:.10f},{target["lng"]:.10f}) <= {cfg["target_radius_km"]}) {{',
                   (f'  double lost=GtxCAAirDefense(PLATFORM,"{enemy}",{cfg["package"]});' if combined else f'  double lost=Math.Floor({cfg["package"]}*{aa}+0.5);'),
                   '  PLATFORM.SetAuxData("lost",lost);', '  PLATFORM.SetAuxData("hit",1.0);',
                   f'  double damage=Math.Floor(({cfg["package"]}-lost)*{cfg["personnel_per_effective_aircraft"]}*'+('GtxCAAirCover(target)' if combined else str(cover))+'+0.5);',
                   f'  double equipment=Math.Floor(({cfg["package"]}-lost)*{cfg["equipment_per_effective_aircraft"]});',
                   '  PLATFORM.SetAuxData("damage",damage);', '  PLATFORM.SetAuxData("equipment",equipment);',
                   '  target.SetAuxData("gtx_air_damage",target.AuxDataDouble("gtx_air_damage")+damage);',
                   '  target.SetAuxData("gtx_air_equipment",target.AuxDataDouble("gtx_air_equipment")+equipment);']
        script += event('air_defense') + event('strike') + [' } else {'] + event('abort_target_moved') + [' }', ' end_script', ' script void GtxReturn()']
        script += event('returned') + [
            f' writeln("GTXAIRRESULT|{identity}|",(int)PLATFORM.AuxDataDouble("lost"),"|",(int)PLATFORM.AuxDataDouble("hit"),"|",(int)PLATFORM.AuxDataDouble("damage"),"|",(int)PLATFORM.AuxDataDouble("equipment"));',
            ' end_script', 'end_platform_type', f'platform {identity} {identity}_type',
            f' creation_time {cfg["preparation_s"]} sec', f' side {team}', ' route',
            f'  position {_location(entry)} altitude {cfg["altitude_m"]} m msl speed {cfg["speed_mps"]} m/s',
            f'  position {_location(target)} execute GtxStrike',
            f'  position {_location(entry)} execute GtxReturn', ' end_route', 'end_platform']
    script.append(f'execute at_time {scene["seconds"]:.6f} sec absolute')
    for pool_id,pool_model in pool_models.items():
        cfg=pool_model['rules'];pool=pool_model['account']
        own=[t for t in tasks if t.get('pool_id',t['team'])==pool_id]
        lost='+'.join(f'WsfSimulation.FindPlatform("{t["id"]}").AuxDataDouble("lost")' for t in own) or '0'
        hits='+'.join(f'WsfSimulation.FindPlatform("{t["id"]}").AuxDataDouble("hit")*{cfg["package"]}' for t in own) or '0'
        script.append(f' writeln("GTXAIRPOOL|{pool_id}|",(int)({pool["ready"]}-({lost})),"|",(int)({pool["destroyed"]}+({lost})),"|",{pool["sorties"]+len(own)*cfg["package"]},"|",(int)({pool["ordnance"]}-({hits})),"|",{pool["fuel"]-len(own)*cfg["package"]*cfg["fuel_per_aircraft"]});')
    script.append('end_execute')
    return {'state': baseline, 'tasks': tasks, 'script': '\n'.join(script) + '\n',
            **({'availability_clock':{'simulation_clock':copy.deepcopy(world.get('simulation_clock')),
                                      'current_time':world.get('current_time')}}
               if any('availability' in p for p in (air_assets.world_definition(world) or {}).get('pools',{}).values()) else {}),
            **({'definition':copy.deepcopy(air_assets.world_definition(world))} if 'pools' in baseline else {})}


def validate_reservations(world, orders):
    """Input validation only; the aircraft inventory is settled by native WSF."""
    targeted=[o for o in orders if o['action']=='air_support' and o.get('target')]
    if not targeted:return
    baseline=state(world)
    if baseline is None:raise ValueError('当前想定没有登记航空兵力')
    _reservations(world,orders,baseline)


def _location(point):
    return f'{abs(point["lat"]):.10f}{"n" if point["lat"]>=0 else "s"} {abs(point["lng"]):.10f}{"e" if point["lng"]>=0 else "w"}'


def decode(text, model, seconds):
    """Decode native events only. Never synthesize arrival or missing flight data."""
    tasks = {t['id']: {**copy.deepcopy(t), 'events': []} for t in model['tasks']}
    explicit=model.get('definition')
    if explicit is not None:air_assets.validate_state(explicit,model['state'])
    accounts=model['state'].get('pools',model['state']['assets']) if model['state'] else {}
    def rules(task):
        return explicit['pools'][task['pool_id']]['rules'] if explicit is not None else CONFIG
    results = {}; pools={}
    for line in text.splitlines():
        if line.startswith('GTXAIRPOOL|'):
            p=line.split('|')
            if len(p)!=7 or p[1] not in accounts or p[1] in pools: raise ValueError('航空库存回传不完整或重复')
            pools[p[1]]=dict(zip(('ready','destroyed','sorties','ordnance','fuel'),map(int,p[2:])))
            continue
        if not line.startswith(('GTXAIREVENT|', 'GTXAIRRESULT|')): continue
        p = line.split('|'); identity = p[1]
        if identity not in tasks: raise ValueError('未知航空任务回传')
        if p[0] == 'GTXAIREVENT':
            if len(p) != 8: raise ValueError('航空事件字段不完整')
            event = {'phase': p[2], 'seconds': int(p[3])/1000,
                     'lat': int(p[4])+int(p[5])/1e8, 'lng': int(p[6])+int(p[7])/1e8}
            if not 0 <= event['seconds'] <= seconds or not -90 <= event['lat'] <= 90 or not -180 <= event['lng'] <= 180:
                raise ValueError('航空事件时间或位置非法')
            tasks[identity]['events'].append(event)
        else:
            if len(p) != 6 or identity in results: raise ValueError('航空战果缺项或重复')
            cfg=rules(tasks[identity]);package=tasks[identity]['package']
            lost, hit, damage, equipment = map(int, p[2:])
            if not 0 <= lost <= package or hit not in (0,1) or not 0 <= damage <= (package-lost)*cfg['personnel_per_effective_aircraft'] or not 0 <= equipment <= (package-lost)*cfg['equipment_per_effective_aircraft']:
                raise ValueError('航空战果超出模型预算')
            if not hit and (lost or damage or equipment): raise ValueError('中止任务不得产生战果')
            results[identity] = {'aircraft_lost': lost, 'hit': bool(hit), 'personnel_effect': damage, 'equipment_effect': equipment}
    if set(results) != set(tasks): raise ValueError('航空任务未完成返场，原战局不提交')
    value = copy.deepcopy(model['state'])
    if value is None: return None
    expected=copy.deepcopy(accounts)
    for identity, task in tasks.items():
        result = results[identity]; events = task['events']
        phases = ['launch','air_defense','strike','returned'] if result['hit'] else ['launch','abort_target_moved','returned']
        if [e['phase'] for e in events] != phases or any(a['seconds'] > b['seconds'] for a,b in zip(events,events[1:])):
            raise ValueError('航空任务阶段或时间顺序不完整')
        for event in events:
            point=task['entry'] if event['phase'] in ('launch','returned') else task['aim']
            if missions.distance(event,point)>.1:
                raise ValueError('航空任务未到达登记航路点，不能虚构打击或返场')
        if explicit is not None and 'availability' in explicit['pools'][task['pool_id']]:
            from gentactix import air_availability
            air_availability.require(model.get('availability_clock',{}),explicit['pools'][task['pool_id']],events[-1]['seconds'])
        pool = expected[task.get('pool_id',task['team'])]; package = task['package'];cfg=rules(task)
        pool['ready'] -= result['aircraft_lost']; pool['destroyed'] += result['aircraft_lost']; pool['sorties'] += package
        pool['ordnance'] -= package if result['hit'] else 0
        pool['fuel'] -= package*cfg['fuel_per_aircraft']
        task.update(**result, status='returned', outcome='strike' if result['hit'] else 'aborted',
                    ordnance_spent=package if result['hit'] else 0, fuel_spent=package*cfg['fuel_per_aircraft'],
                    effect_basis='AFSIM教学期望效果；实际减员受目标剩余人员装备上限约束')
    if tasks:
        if set(pools)!=set(expected): raise ValueError('AFSIM未回传航空库存')
        for team,pool in pools.items():
            if pool!={k:expected[team][k] for k in pool}: raise ValueError('航空库存与原生任务记录不守恒')
            value['pools' if explicit is not None else 'assets'][team].update(pool)
        if explicit is not None:value['assets']=air_assets.aggregate(value['pools'])
    value['missions'] = list(tasks.values()); value['last_turn'] = next(iter(tasks.values()))['turn'] if tasks else value['last_turn']
    if explicit is not None:air_assets.validate_state(explicit,value)
    return value
