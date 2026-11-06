"""Versioned bounds for existing motion/fatigue rules; never update a world.

The native mover remains the executor. DSH must submit its own effects, checked
against the same initial limits and independently validated passage receipts.
"""
import math
import os

VERSION = 'movement-feedback-1'
CONTINUOUS_VERSION = 'movement-feedback-2'
POSITION_TOLERANCE_KM = .001  # Existing one-metre command representation tolerance.
TIME_TOLERANCE_S = 1         # Existing crossing-event clock tolerance.


def validate_config(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'assumption'}
            or value.get('version') not in (VERSION, CONTINUOUS_VERSION) or not isinstance(value.get('assumption'), str)
            or not value['assumption'].strip() or len(value['assumption']) > 4000):
        raise ValueError('运动反馈须显式填写movement-feedback-1或movement-feedback-2及非空估计依据')
    return True


def configuration(world):
    value = world.get('mission', {}).get('definition', {}).get('movement_feedback')
    if value is not None:
        validate_config(value)
    return value


def continuous(world):
    value = configuration(world)
    return value is not None and value['version'] == CONTINUOUS_VERSION


def native_preview_enabled(world):
    return continuous(world) and os.environ.get('GENTACTIX_NATIVE_CONTINUOUS_PREVIEW')=='1'


def require_executor(world,*,backend=None):
    """Keep a prepared precision contract out of legacy execution paths.

    Version 2 has a separately tested Native component. Do not remove this gate
    until model effects, logistics and whole-world submission are wired.
    """
    if continuous(world):
        if backend=='afsim' and native_preview_enabled(world):
            from . import missions,crossings
            from .unit_types import classify_unit
            from .config import is_naval
            spec=world.get('mission',{}).get('definition',{})
            if not all(spec.get(k) for k in ('support_dynamics','supply_distribution','supply_schedule')):
                raise ValueError('连续机动候选执行必须配置按时保障、分类粮弹和定时补给，不套用旧结算')
            if crossings.get_model(world):raise ValueError('连续机动与共享渡运通路尚未接通')
            if spec.get('air_definition') or any(is_naval(u.get('type','')) or
                    (classify_unit(u.get('type','')) or {}).get('id')=='aviation' for _,u in missions.units(world)):
                raise ValueError('连续机动候选仅验收地面部队；航空、海军及航空资源池须单独接通')
            return
        raise ValueError('连续机动版本的整局执行链尚未验收；不能套用旧版运动算法')


def _route(world, unit, target):
    from . import crossings, crossing_network
    return crossing_network.plan(world, unit, target) if target is not None and crossings.get_model(world) else None


def limits(world, unit, target=None):
    from . import missions, sim_clock, fire_process, campaign
    if configuration(world) is None:
        return None
    spec = world['mission']['definition']; f = unit['formation']
    seconds = sim_clock.duration_seconds(spec['time_step'])
    nominal = missions.move_budget(world, unit, target)
    delay = fire_process.delay_seconds(world, unit)
    strength = unit['personnel']['current']/unit['personnel']['committed']
    from . import suppression_state
    pause = max(delay+seconds*(f['fatigue']/200+suppression_state.value(unit)/250), seconds*(1-strength))
    usable = max(0, seconds-pause)
    if not unit['personnel']['current'] or campaign.release_seconds(world, unit) > 0:
        usable = 0
    fuel_bound = None
    if f.get('motorized', spec['combined_rules']['motorized']):
        rate = sum(e['operational']*{'armor':2,'transport':.1}.get(e['category'],0) for e in unit['equipment'])
        if rate > 0:
            fuel_bound = math.floor(f['fuel_liters'])/rate
    effective = nominal*usable/seconds
    if fuel_bound is not None:
        effective = min(effective, fuel_bound)
    return dict(nominal_km=nominal, command_delay_seconds=delay, pause_seconds=pause,
        usable_seconds=usable, effective_ground_km=effective, fuel_ground_km=fuel_bound,
        queued_path=bool(_route(world, unit, target)))


def command_budget(world, unit, target=None):
    """A passage command is a route request, not a promise of arrival.

    Retain its existing staged target envelope; final feedback additionally
    checks approach, queue/service, ground time and landing receipts. Ordinary
    direct motion uses the effective segment immediately.
    """
    from . import missions
    if continuous(world):
        # A persistent goal is a route request. Native motion will bound actual
        # travel; do not repeatedly shorten its goal or its communication wait.
        return missions.move_budget(world,unit,target)
    value = limits(world, unit, target)
    if value is None:
        return missions.move_budget(world, unit, target)
    if value['queued_path']:
        budget = value['nominal_km']
        if value['fuel_ground_km'] is not None:
            budget = min(budget, value['fuel_ground_km'])
        return budget
    return value['effective_ground_km']


def travel(world, unit, following, order):
    """Read route/ground distances from positions, without allocating service."""
    from . import missions, crossings, ferries
    path = _route(world, unit, order) if order['action'] == 'move' else None
    if path:
        route = crossings.path_position(unit, path['waypoints'], following)
        if route is None:
            raise ValueError(unit['name']+'：运动反馈位置偏离已登记通路')
        if ferries.config(world):
            approach = missions.distance(unit, path['entry']) if path['enter_required'] else 0
            afloat = missions.distance(path['entry'] if path['enter_required'] else unit, path['exit'])
            ground = min(route, approach)+max(0, route-approach-afloat)
            return dict(mode='ferry', route_km=route, ground_km=ground,
                        approach_km=min(route, approach), post_landing_km=max(0,route-approach-afloat), path=path)
        return dict(mode='passage', route_km=route, ground_km=route, path=path)
    distance = missions.distance(unit, following)
    if ferries.carrier(world, unit['name']):
        return dict(mode='carried', route_km=distance, ground_km=0, path=None)
    return dict(mode='ground', route_km=distance, ground_km=distance, path=None)


def fatigue_value(world, unit, action, ground_km, *, following=None):
    from . import sim_clock, support_dynamics
    cfg = world['mission']['definition']['combined_rules']; value = unit['formation']['fatigue']
    if action == 'move':
        # The actual native GtxRound uses ties-to-even, not floor(x+.5).
        value = min(100, value+round(ground_km*cfg['fatigue_move_gain']))
    elif action in ('hold', 'resupply', 'conceal'):
        seconds = sim_clock.duration_seconds(world['mission']['definition']['time_step'])
        recovery = cfg['fatigue_rest_recovery']*(seconds/1800 if support_dynamics.configuration(world) else 1)
        value = max(0, value-recovery)
    nutrition = support_dynamics.configuration(world)
    if nutrition:
        state = (following or unit)['sustainment']
        value = max(value, math.floor(min(100,state['shortage_hours']*nutrition['shortage_fatigue_per_hour'])))
    return value


def validate_transition(before, after, orders, seconds, *, source, native=None):
    from . import missions, ferries, crossing_network
    if configuration(before) is None:
        return None
    require_executor(before)
    checked = {o['unit']:o for o in orders}; current = {u['name']:u for _,u in missions.units(after)}
    rows = []
    for _, unit in missions.units(before):
        name = unit['name']; following = current[name]; order = checked.get(name, dict(unit=name,action='hold'))
        measured = travel(before,unit,following,order); bound = limits(before,unit,order if order['action']=='move' else None)
        ground = measured['ground_km']; speed = bound['nominal_km']/seconds
        if order['action']=='move':
            if ground > bound['effective_ground_km']+POSITION_TOLERANCE_KM:
                raise ValueError(name+f'：实际陆地位移{ground:.6f} km超过有效机动预算{bound["effective_ground_km"]:.6f} km（含通信、疲劳、压制、兵力和燃油）')
            if measured['mode']=='passage':
                task = following.get('crossing') or {}; path = measured['path']
                site = crossing_network.by_id(before,path['task']['site_id'])
                service = task.get('last_work',0)*3600/site['crossing_model']['throughput_work_per_hour']
                if ground/max(speed,1e-12)+service+bound['pause_seconds'] > seconds+TIME_TOLERANCE_S:
                    raise ValueError(name+'：机动等待、通路行军及渡运服务合计超出本轮时长')
                entered = next((e for e in task.get('events',[]) if e['phase']=='entered'),None)
                approach = missions.distance(unit,path['entry']) if path['enter_required'] else 0
                # Entered records arrival at the bank, not the start of service.
                # An actor already there can queue at t=0; the joint service
                # budget above still includes its command/fatigue pause.
                if entered and approach>POSITION_TOLERANCE_KM and entered['seconds']+TIME_TOLERANCE_S < bound['pause_seconds']+approach/max(speed,1e-12):
                    raise ValueError(name+'：抵达渡运入口早于通信／疲劳等待及接近时间')
            elif measured['mode']=='ferry':
                events = after['combined_arms']['bridge']['ferry_state']['events']
                landed = next((e for e in events if e['unit']==name and e['phase']=='landed'),None)
                task = following.get('crossing') or {}
                entered = next((e for e in task.get('events',[]) if e['phase']=='entered'),None)
                if not ferries.carrier(before,name) and entered:
                    earliest = bound['pause_seconds']+measured['approach_km']/max(speed,1e-12)
                    if measured['approach_km']>POSITION_TOLERANCE_KM and entered['seconds']+TIME_TOLERANCE_S < earliest:
                        raise ValueError(name+'：登船接近早于机动等待和行军允许时点')
                if measured['post_landing_km'] > POSITION_TOLERANCE_KM:
                    if not landed or max(landed['seconds'],bound['pause_seconds'])+measured['post_landing_km']/max(speed,1e-12)>seconds+TIME_TOLERANCE_S:
                        raise ValueError(name+'：登岸后陆地机动缺少足够剩余时间')
        if native is not None:
            receipt = native[name]
            if abs(receipt['ground_km']-ground) > .000003 or abs(receipt['route_km']-measured['route_km']) > .000003:
                raise ValueError(name+f'：原生运动路程与坐标／通路回执不一致；mode={measured["mode"]}，'
                    f'原生ground={receipt["ground_km"]:.12g}/route={receipt["route_km"]:.12g} km，'
                    f'坐标ground={ground:.12g}/route={measured["route_km"]:.12g} km')
            ground = receipt['ground_km']
        expected = fatigue_value(before,unit,order['action'],ground,following=following)
        if not math.isclose(following['formation']['fatigue'],expected,rel_tol=0,abs_tol=1e-6):
            raise ValueError(name+f'：疲劳应为{expected:.12g}，实际{following["formation"]["fatigue"]:.12g}；按实际陆地公里、原生偶数舍入及休整／缺粮下限提交，不自动代填')
        rows.append(dict(unit=name,mode=measured['mode'],ground_km=ground,route_km=measured['route_km'],
                         pause_seconds=bound['pause_seconds'],fatigue_expected=expected))
    return dict(version=VERSION,source=source,turn=after['mission']['turn'],units=rows,
                scope='命令时间、位移与疲劳必要约束；不是历史效能标定或新的状态执行器')


def causal_instruction(world):
    if configuration(world) is None:return ''
    if continuous(world):
        if native_preview_enabled(world):
            return '原生连续机动处于隔离验证模式；仅凭同轮原生回执说明过程，历史效能未标定。DSH独立过程估计暂不接受此版本。'
        return '连续机动已建立精度及继承合同，整局物理执行尚未验收；不能从准备状态宣称已执行、已到达或完成疲劳归因。'
    return ('轮初疲劳影响等待；等待还受压制、通信和有效兵力约束。'
        '当前疲劳按实际陆地里程、休整和缺粮下限核对，等待不作为疲劳增量；'
        '不能从等待长反推当前疲劳的原因，缺少同轮前态或运动回执时归因保持未知。')


def analysis_facts(world, frame=None):
    """Read existing verified motion receipts; no new dynamics or state edits."""
    from . import missions
    if configuration(world) is None:return []
    receipt=((world.get('dsh_execution') or {}).get('movement') if world.get('dsh_execution')
             else (world.get('combined_arms') or {}).get('movement_feedback'))
    unknown='疲劳归因缺少同轮前态或运动回执；当前值保留，不能从等待推断其成因。'
    if (not isinstance(frame,dict) or not isinstance(frame.get('before'),dict)
            or not isinstance(receipt,dict) or receipt.get('version')!=VERSION
            or receipt.get('turn')!=world['mission']['turn'] or frame.get('turn')!=receipt.get('turn')
            or not isinstance(receipt.get('units'),list)):
        return [causal_instruction(world),unknown]
    source=receipt.get('source')
    if source not in ('dsh_model_estimate','afsim_native_estimate'):
        return [causal_instruction(world),unknown]
    origin='DSH模型估计' if source=='dsh_model_estimate' else 'AFSIM教学模型'
    prior={u['name']:u for _,u in missions.units(frame['before'])}
    entries={};duplicates=set()
    for row in receipt['units']:
        if not isinstance(row,dict) or not isinstance(row.get('unit'),str):continue
        name=row['unit']
        if name in entries:duplicates.add(name)
        entries[name]=row
    lines=[causal_instruction(world)]
    for _,unit in missions.units(world):
        name=unit['name'];old=prior.get(name);row=entries.get(name)
        if old is None or row is None or name in duplicates:
            lines.append(name+'：'+unknown);continue
        values=(old.get('formation',{}).get('fatigue'),unit['formation'].get('fatigue'),
                row.get('ground_km'),row.get('pause_seconds'),row.get('fatigue_expected'))
        try:known=all(type(v)in(int,float) and math.isfinite(v) for v in values)
        except OverflowError:known=False
        if not known:
            lines.append(name+'：'+unknown);continue
        before,current,ground,pause,expected=values
        if (old.get('historical_unit_id')!=unit.get('historical_unit_id')
                or not math.isclose(current,expected,rel_tol=0,abs_tol=1e-6)):
            lines.append(name+'：疲劳归因前态／当前值与运动回执不一致，不能认证成因。');continue
        lines.append(f'{name}疲劳已核对（{origin}）：轮初疲劳{before:g}→当前{current:g}；'
            f'本轮陆地里程{ground:g}km，轮初约束等待{pause:g}秒，疲劳规则核验值{expected:g}。'
            '等待不作为疲劳增量；这是教学规则关系，不是历史或生理效能标定。')
    return lines


def observation(world):
    from . import missions
    if configuration(world) is None:
        return None
    if continuous(world):
        from . import motion_state
        rows=[]
        for _,u in missions.units(world):
            motion_state.validate_unit(u)
            rows.append(dict(unit=u['name'],**{k:u['formation'][k] for k in
                ('fatigue','fuel_liters',motion_state.FATIGUE_FIELD,motion_state.FUEL_FIELD)}))
        return dict(version=CONTINUOUS_VERSION,execution_ready=False,units=rows,
            **({'native_preview_enabled':True} if native_preview_enabled(world) else {}),
            scope=causal_instruction(world))
    return dict(version=VERSION,units=[dict(unit=u['name'],**limits(world,u)) for _,u in missions.units(world)],
        scope='effective_ground_km只限制自主陆地机动；渡运请求还须通过排队、服务、船速和登岸回执，不能宣称到达')


def instruction(world):
    if configuration(world) is None:
        return ''
    if continuous(world):
        return '\n【movement-feedback-2准备态】'+causal_instruction(world)+'单位精度和任务可只读查询；当前不接受推演执行。'
    require_executor(world)
    return ('\n【movement-feedback-1】'+causal_instruction(world)+'移动必须遵守movement_constraints的有效陆地预算，名义预算不是实际能力。'
        '等待秒数=max(通信延迟+回合秒数*(轮初fatigue/200+suppression/250),回合秒数*(1-current/committed))。'
        '普通陆地机动预算=名义预算*max(0,1-等待秒数/回合秒数)，并受缺油／未到场约束。'
        '每个单位必须提交formation.fatigue：move为min(100,旧疲劳+round(实际陆地公里*fatigue_move_gain))，'
        'round按最接近整数、恰好一半取偶数；hold/resupply/conceal为max(0,旧疲劳-fatigue_rest_recovery)，'
        '有time-sustainment-1时休整量再乘回合秒数/1800；其余行动保持旧值。'
        '最终疲劳还须不低于已验证缺粮债的floor(min(100,shortage_hours*shortage_fatigue_per_hour))，不是再次相加。'
        '桥梁走完整通路并扣等待与服务时间；舟艇载运不消耗乘客陆地公里、行军疲劳或地面行驶油，登岸后再计算，不能将船载位移套陆地上限。'
        '模型自行给出变化值，宿主只校验、拒收，不生成或修补状态。')
