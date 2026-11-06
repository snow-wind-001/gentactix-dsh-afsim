"""Shared fire-process expressions and model-reported evidence admission.

Expression rendering produces WSF source or readable model instructions. The
validator checks timing/resources. Necessary effect bounds are checked separately;
neither validator calculates or repairs the proposed outcome.
"""
import copy
import math
import re
import ast
import operator

VERSION = 'dsh-fire-estimate-1'
GROUND_FIRE = ('fire', 'bombard', 'suppress')
NATIVE_TIME_SCOPE = ('AFSIM持续火力回执active_fire_s是本轮新发射周期的覆盖指标，裁于轮末，'
                     '不含上轮周期尾段；跨轮相加是非可加的周期覆盖指标，不能据此认定实际接敌时长、'
                     '目标持续受火时长或火力积分，也不能由周期数补造首末发时刻。')
DENSITY_SCOPE = ('当前间瞄模型的目标密度在轮初取样，同根同坐标同展开面积共享密度；'
                 '轮内没有随损失重算。不同步长可能改变毁伤，完整世界的时间细分不变性尚未通过。')
LIVE_DENSITY_SCOPE = ('动态密度在每个原生10秒同批射击前采样现存人员，双方共用射击前采样；同阵营同根、'
                     '同当前坐标格与同展开面积共享密度，移动后重新分组。坐标格为floor(度×10^6+0.5)，'
                     '不是区域重叠或溅射；未入场贡献为0。DSH按同一先验估计，不冒称原生采样；完整世界时间收敛仍须验收。')


def density_configuration(world):
    from . import combat_effects
    spec=world.get('mission',{}).get('definition',{})
    if 'fire_dynamics' not in spec:return None
    combat_effects.validate_dynamics(spec['fire_dynamics'])
    return spec['fire_dynamics']


def density_scope(world):
    return LIVE_DENSITY_SCOPE if density_configuration(world) else DENSITY_SCOPE


def position_cell(value):
    """The explicit new density grid; never reuse positive-only GtxRound."""
    return math.floor(value*1000000+.5)
FORMULAS = {
    'indirect_power': '{shells}*1.5',
    'direct_base_power': '{attempts}*{hit_probability}*{range_effect}',
    'legacy_base_power': '12*{size_factor}',
    'armor_power': '{operational_armor}*1.5',
    'suppress_effect': '{damage}*0.35',
    'command_delay': 'round({command_base_s}+(100-{signal})*{command_signal_s}+{distance_to_depot_km}*{command_distance_s_per_km})',
    'direct_attempts': 'round({committed}*{engaged_fraction}*{rounds_per_min}*{direct_cycle_s}/60.0)',
    'range_effect': 'max({range_min_factor},min({range_max_factor},{reference_range_m}/max(1,{distance_m})))',
    'efficiency': '{live_strength_ratio}*max(0.1,1-{fatigue}/120)*max(0.1,1-{suppression}/120)*max(0.15,{intel_confidence}/100/(1+{intel_age_min}*{intel_age_decay}))',
    'direct_cover': '1.0/(1+{protection}+{entrenchment}/50)/sqrt({dispersion_km2})',
    'area_cover': 'min(1,{size_factor}*{strength_ratio})/(1+{protection}+{entrenchment}/50)/sqrt({dispersion_km2})',
    'suppression_gain': 'round({power}*(0.7+{kind}*1.2)*{efficiency})',
}


def expression(key, bindings=None, *, wsf=False):
    text=FORMULAS[key]
    names=set(re.findall(r'\{([a-z_][a-z0-9_]*)\}',text))
    text=text.format(**(bindings if bindings is not None else {k:k for k in names}))
    if wsf:
        text=re.sub(r'\b(max|min|sqrt|round)\(',lambda m:{'max':'Math.Max','min':'Math.Min','sqrt':'Math.Sqrt','round':'GtxRound'}[m[1]]+'(',text)
    return text


def formula_value(key, **bindings):
    """Evaluate only authored arithmetic expressions with finite numeric inputs.

    Used for necessary input ceilings, never a timestep or casualty executor.
    Names/functions come from FORMULAS; no model-provided expression is executed.
    """
    try:valid=all(type(v) in (int,float) and math.isfinite(v) for v in bindings.values())
    except OverflowError:valid=False
    if not valid:
        raise ValueError('火力公式参数须为有限数值')
    functions={'min':min,'max':max,'sqrt':math.sqrt,'round':lambda x:math.floor(x+.5)}
    operations={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return node.value
        if isinstance(node,ast.Name) and node.id in bindings:return bindings[node.id]
        if isinstance(node,ast.BinOp) and type(node.op) in operations:return operations[type(node.op)](visit(node.left),visit(node.right))
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in functions and not node.keywords:
            return functions[node.func.id](*(visit(arg) for arg in node.args))
        raise ValueError('火力公式含未支持的表达式或缺少数值参数')
    value=visit(ast.parse(expression(key),mode='eval').body)
    if not math.isfinite(value):raise ValueError('火力公式结果须为有限数')
    return value


def delay_seconds(world, unit):
    """Read-only lower bound from registered inputs, not a command executor."""
    from . import missions
    cfg=world['mission']['definition']['combined_rules']
    node=next(n for n in world['supply_nodes'] if n['id']==unit['supply_node_id'])
    value=cfg['command_base_s']+(100-unit['formation']['signal'])*cfg['command_signal_s']+missions.distance(unit,node)*cfg['command_distance_s_per_km']
    # The explicit motion contract shares native GtxRound's even ties. Keep
    # legacy snapshots' half-up input ceiling unchanged.
    from . import movement_feedback
    if movement_feedback.configuration(world) is not None:
        return round(value)
    return math.floor(value+.5)


def salvo_limits(world, orders):
    """Compile integer per-cycle quotas, never combat effects or spent shells.

    A root's max_salvo is shared by its active bombard/suppress descendants.
    Quotas follow operational gun capacity; native execution still checks live
    guns, stocks, timing and target conditions. Unused quotas are not reassigned
    within a frame. A singleton retains the existing full max_salvo ceiling.
    """
    from . import missions, formation_parts
    from .formation_conversion import _apportion
    cfg=world['mission']['definition']['combined_rules']
    selected={r['unit'] for r in orders if r.get('action') in ('bombard','suppress')}
    limits={u['name']:0 for _,u in missions.units(world)}
    for team in ('red','blue'):
        for group in formation_parts.buckets(world,team):
            active=[u for u in group if u['name'] in selected and u['personnel']['current']>0]
            if not active:continue
            if len(group)==1:
                limits[active[0]['name']]=math.floor(cfg['max_salvo']);continue
            capacity=[math.floor(next((e['operational'] for e in u['equipment'] if e['category']=='artillery'),0)*cfg['shells_per_gun']) for u in active]
            quotas=_apportion(min(math.floor(cfg['max_salvo']),sum(capacity)),capacity)
            limits.update((u['name'],q) for u,q in zip(active,quotas))
    return limits


def area_factors(world, *, ceiling=False):
    """Density inputs for exclusive leaves sharing an identical footprint.

    A bookkeeping split alone does not disperse troops. Different coordinates
    or declared areas remain separate footprints; this is not a splash model.
    """
    from . import formation_parts
    dynamic=density_configuration(world) is not None
    result={}
    for team in ('red','blue'):
        for root in formation_parts.buckets(world,team):
            footprints={}
            for u in root:
                position=(position_cell(u['lat']),position_cell(u['lng'])) if dynamic else (u['lat'],u['lng'])
                key=None if ceiling and dynamic else (*position,u['formation']['dispersion_km2'])
                footprints.setdefault(key,[]).append(u)
            for members in footprints.values():
                committed=sum(u['personnel']['committed'] for u in members)
                current=sum(u['personnel']['current'] for u in members)
                value=dict(size_factor=committed/3000,strength_ratio=current/committed)
                result.update((u['name'],value.copy()) for u in members)
    return result


def reload_seconds(unit, reference):
    """Read the canonical clock; legacy counts apply only without seconds."""
    formation=unit['formation']
    return formation.get('reload_remaining_s',formation['reload_remaining']*reference['artillery_cycle_s'])


def cycle_period(world,action,reference):
    if action not in GROUND_FIRE:raise ValueError('地面火力周期须对应fire/bombard/suppress')
    return reference['direct_cycle_s'] if action=='fire' else reference['artillery_cycle_s']*max(1,world['mission']['definition']['combined_rules']['reload_turns'])


def native_time_scope():
    """Describe an existing counter; never reconstruct absent time evidence."""
    return {'metric':'new_cycle_window_coverage_seconds', 'unit':'seconds',
            'includes_prior_turn_tail':False, 'additive_across_partitions':False,
            'description':NATIVE_TIME_SCOPE}


def _cycle_count(unit,row,seconds,reference):
    cycles=row['fire_cycles']
    if type(cycles) is not int or not 0<=cycles<=seconds//min(reference['direct_cycle_s'],reference['artillery_cycle_s'])+1:
        raise ValueError(unit['name']+'：fire_ledger周期超过本轮时间窗口')
    return cycles


def reload_after(world,unit,seconds,*,row=None,reference=None):
    """Read-only strict clock reference; does not prove a valid firing process.

    Passive clocks retain their previous precision. A ground-fire receipt uses
    native integer-second truncation, including a declared zero-shot receipt.
    Its other time, target, loss and ammunition guards remain mandatory.
    """
    if reference is None:
        from . import combat_effects
        reference=combat_effects.reference(world)
    _number(seconds,'seconds');initial=reload_seconds(unit,reference);_number(initial,'reload_initial_s')
    if row is None:return max(0,initial-seconds)
    cycles=_cycle_count(unit,row,seconds,reference)
    period=cycle_period(world,row['action'],reference)
    if cycles:
        _number(row['last_fire_s'],'last_fire_s')
        if row['last_fire_s']>=seconds:raise ValueError(unit['name']+'：末发时刻不在本轮窗口内')
    elif row.get('first_fire_s') is not None or row.get('last_fire_s') is not None or row.get('active_fire_s')!=0:
        raise ValueError(unit['name']+'：零射击周期不能声明发射时刻或有效火力')
    return math.floor(max(0,(row['last_fire_s']+period if cycles else initial)-seconds)+1e-6)


def quiet_suppression_after(world,unit,seconds,*,reference=None):
    """Read-only configured decay, applicable only without incoming fire.

    This is a candidate constraint, not a physical update or a prediction of
    received suppression. Legacy aggregate profiles keep their existing scope.
    """
    if reference is None:
        from . import combat_effects
        reference=combat_effects.reference(world)
    cfg=world['mission']['definition'].get('combined_rules')
    if not cfg or reference['version'] not in ('aggregate-fire-cycles-2.2','aggregate-fire-cycles-2.3','aggregate-fire-cycles-2.4','aggregate-fire-cycles-2.5','aggregate-fire-cycles-2.6'):
        return None
    _number(seconds,'seconds')
    if 'suppression_state' in reference:
        from . import suppression_state
        return suppression_state.quiet_load(unit,cfg['suppression_decay'],seconds)//suppression_state.SCALE
    return math.floor(max(0,unit['formation']['suppression']-cfg['suppression_decay']*seconds/1800)+1e-6)


def observation(world):
    from . import combat_effects, missions, formation_parts,sim_clock
    cfg=world['mission']['definition'].get('combined_rules')
    if not cfg:return None
    ref=combat_effects.reference(world)
    area=area_factors(world)
    return {'version':VERSION, 'scope':'共同聚合模型先验与估计回执约束，不是历史标定或AFSIM遥测',
        'profile_hash':ref['definition_hash'],
        'parameters':{k:copy.deepcopy(cfg[k]) for k in ('command_base_s','command_signal_s','command_distance_s_per_km',
            'intel_age_decay','suppression_decay','reload_turns','max_salvo','shells_per_gun')},
        'fire_profile':{k:copy.deepcopy(ref.get(k)) for k in ('direct_fire','direct_cycle_s','artillery_cycle_s','ammo_per_cycle','fatality_share')}
            |({'fire_dynamics':copy.deepcopy(ref['fire_dynamics'])} if 'fire_dynamics' in ref else {})
            |({'damage_quantum':ref['damage_quantum']} if 'damage_quantum'in ref else {}),
        **({'fire_accounting':copy.deepcopy(ref['fire_accounting']),
            'work_cost_by_action':{a:combat_effects.work_cost(ref,a)for a in GROUND_FIRE}} if 'fire_accounting' in ref else {}),
        'formulas':{k:expression(k) for k in FORMULAS},
        'feedback':{'native_tick_s':10,'intel_age_gain_per_second':1/60,
            'native_fire_time_scope':native_time_scope(),
            'indirect_density_sampling':'live_shared_footprint' if density_configuration(world) else 'turn_start_shared_footprint',
            'partition_invariance_verified':False,
            'density_scope':density_scope(world),
            'shared_salvo':'max_salvo按原始父编组每周期共享，只在本轮bombard/suppress成员间按可用火炮容量分配整数额度；hold不占额度，零额度记root_salvo_limit。实际炮弹数仍受库存与可用火炮约束，轮内未用额度不重分配。',
            'intel_confidence_loss_per_1800s':10,'intel_confidence_floor':10,
            'suppression_decay_per_1800s':cfg['suppression_decay'],
            'quiet_suppression':'连续火力模型中，未被本轮火力命令指向的单位期末suppression=floor(max(0,轮初suppression-suppression_decay*本轮秒数/1800)+1e-6)；按配置恢复，不猜受击方过程。',
            'damage':'直射power=direct_attempts * hit_probability * range_effect + operational_armor * 1.5，再乘每周期efficiency和目标direct_cover；炮击power=实际炮弹数*1.5，改乘area_cover，suppress再乘0.35。',
            **({'damage_accumulation':'本快照damage_quantum=1e-6；每次地面毁伤先floor(damage*10^6+0.5)为整数微量，再累计，携带余量也须为整数微量。宿主只验输入与回执，不替模型计算战果。'}if 'damage_quantum'in ref else {}),
            'variables':'committed为原投入，live_strength_ratio为本时段可用/原投入，不在attempts再次乘可用人数；area_cover采用每单位area_factors的size_factor和strength_ratio，同根、同坐标、同展开面积的互斥分队共享物理密度，异地或异面积分别计算；这不是邻近目标溅射。kind为fire:0,bombard:1,suppress:2。',
            'continuous':'每个周期先用本周期可用人数、压制、疲劳与情报计算；双方同批射击后更新压制与可用人数。不能用轮初效率乘整轮。',
            'timing':'首发须等联络延迟和上一轮剩余装填；周期为direct_cycle_s或artillery_cycle_s*max(1,reload_turns)。最后一次须早于轮末；native_tick_s只说明原生调度粒度，不把估计钟点当原生时刻。',
            'reload_clock':'装填按整轮秒数流逝，与命令延迟、入场时间、可用状态无关。无地面射击或实际零发时，期末秒数=max(0,reload_initial_s-本轮秒数)；有发射时=max(0,last_fire_s+对应周期-本轮秒数)。期末截去不足1秒部分，与原生回执整数精度一致。若轮初仍有装填，unit_updates须显式提交formation.reload_remaining_s，即使期末为0；hold也不能沿用旧值。reload_remaining旧字段是周期计数，只有缺少_s才乘artillery_cycle_s换算，不能当秒。'},
        'units':[{'unit':u['name'],'delay_s':delay_seconds(world,u),
            'reload_initial_s':reload_seconds(u,ref),
            **({'quiet_suppression_end_if_not_targeted':quiet_suppression_after(world,u,sim_clock.duration_seconds(world['mission']['definition']['time_step']),reference=ref)}
               if u['formation']['suppression']>0 else {}),
            'resource_scale':formation_parts.scale(u),'area_factors':area[u['name']]} for _,u in missions.units(world)]}


def receipt_for_unit(world, name, turn):
    """Bounded committed evidence for the existing read-only observation tool."""
    ledger=(world.get('dsh_execution') or {}).get('fire_ledger')
    if not isinstance(ledger,dict) or ledger.get('version')!=VERSION or ledger.get('source')!='dsh_model_estimate' or ledger.get('turn')!=turn:
        return None
    rows=ledger.get('units')
    if not isinstance(rows,list):return None
    row=next((r for r in rows if isinstance(r,dict) and r.get('unit')==name),None)
    if row is None:return None
    fields=('unit','action','target','delay_s','first_fire_s','last_fire_s','fire_cycles',
            'active_fire_s','reload_remaining_s','stop_reason')
    return {**{k:copy.deepcopy(row[k]) for k in fields if k in row},
            'source':'dsh_model_estimate','version':VERSION,'turn':turn,
            'assumptions':str(row.get('assumptions') or '')[:400],
            'scope':'模型声明的射击过程估计；不是AFSIM原生遥测，缺载记录不补算。'}


def _number(value, label):
    try:valid=type(value) in (int,float) and math.isfinite(value) and value>=0
    except OverflowError:valid=False
    if not valid:
        raise ValueError('fire_ledger '+label+'须为有限非负数')


def validate(before, after, result, seconds, *, required=False):
    from . import combat_effects, missions, formation_parts
    orders={r['unit']:r for r in result.get('orders',[]) if r.get('action') in GROUND_FIRE}
    # The native end-of-frame clock runs for every formation, even staging or
    # disabled actors. Validate model proposals; never fill or repair them.
    ref=combat_effects.reference(before)
    updates={r['unit']:r for r in result['unit_updates']}
    targeted={r.get('target') for r in result.get('orders',[]) if r.get('action') in (*GROUND_FIRE,'air_support')}
    if before['mission']['definition'].get('combined_rules'):
        following={u['name']:u for _,u in missions.units(after)}
        for _,unit in missions.units(before):
            name=unit['name']
            expected_suppression=quiet_suppression_after(before,unit,seconds,reference=ref)
            if name not in targeted and expected_suppression is not None:
                initial_suppression=unit['formation']['suppression'];submitted_suppression=following[name]['formation']['suppression']
                explicit_suppression='suppression' in updates[name].get('formation',{})
                if (submitted_suppression!=expected_suppression
                        or initial_suppression!=expected_suppression and not explicit_suppression):
                    raise ValueError(name+f'：压制轮初={initial_suppression:g}，本轮={seconds:g}秒，无来袭命令的期末须={expected_suppression:g}，提交={submitted_suppression:g}；'
                        '须显式提交formation.suppression，不自动保留或代填；有来袭时另按火力过程估计')
            if name in orders:continue
            initial=reload_seconds(unit,ref)
            expected=reload_after(before,unit,seconds,reference=ref)
            submitted=reload_seconds(following[name],ref)
            explicit='reload_remaining_s' in updates[name].get('formation',{})
            if submitted!=expected or (initial>0 and not explicit):
                raise ValueError(name+f'：装填倒计时轮初={initial:g}秒，本轮={seconds:g}秒，期末须={expected:g}秒，提交={submitted:g}秒；'
                    '须在unit_updates.formation显式提交reload_remaining_s，不自动补算或保留旧值')
    proposal=result.get('fire_ledger')
    if proposal is None:
        if required and orders:raise ValueError('实际地面射击必须提交fire_ledger估计过程账，不自动补造火力时长')
        return None
    if (not isinstance(proposal,dict) or set(proposal)!={'version','units'} or proposal['version']!=VERSION
            or not isinstance(proposal['units'],list)):
        raise ValueError('fire_ledger版本或字段非法')
    rows=proposal['units'];fields={'unit','action','target','delay_s','first_fire_s','last_fire_s','fire_cycles',
        'active_fire_s','reload_remaining_s','stop_reason','assumptions'}
    for position,row in enumerate(rows):
        if not isinstance(row,dict):raise ValueError(f'fire_ledger第{position+1}项须为完整估计过程对象')
        if set(row)!=fields:
            missing=','.join(sorted(fields-set(row))) or '无'
            extra=','.join(sorted(str(k)[:80] for k in set(row)-fields)[:5]) or '无'
            raise ValueError(f'fire_ledger第{position+1}项缺少字段：{missing}；多余字段：{extra}；'
                'action须填写对应orders的fire/bombard/suppress，不能省略；不提交原生last_execution')
        if not isinstance(row['unit'],str):raise ValueError(f'fire_ledger第{position+1}项unit须为精确单位名称')
    if len(rows)!=len(orders) or len({r['unit'] for r in rows})!=len(rows) or {r['unit'] for r in rows}!=set(orders):
        raise ValueError('fire_ledger须准确覆盖本轮地面射击命令，不得漏项、重复或给hold编造火力')
    cfg=before['mission']['definition']['combined_rules']
    units={u['name']:u for _,u in missions.units(before)}
    accounts={r['unit']:r for r in result['resource_ledger']['units']}
    receivers=set()
    stops={'none','ammo','range','too_close','no_shells','target_unavailable','actor_unavailable','uncertain','command_pending','reload_pending','terrain_blocked','root_salvo_limit'}
    limits=salvo_limits(before,result['orders'])
    for row in rows:
        name=row['unit'];order=orders[name];unit=units[name];cycles=row['fire_cycles']
        if row['action']!=order['action'] or row['target']!=order['target']:
            raise ValueError(name+'：fire_ledger行动/目标与实际命令不一致')
        _cycle_count(unit,row,seconds,ref)
        if not isinstance(row['stop_reason'],str) or row['stop_reason'] not in stops:
            raise ValueError(name+'：fire_ledger周期或停止原因非法')
        if row['stop_reason']=='root_salvo_limit' and (row['action']=='fire' or limits[name]>0 or cycles):
            raise ValueError(name+'：父级齐射额度仍可用，不能虚构预算耗尽')
        if row['stop_reason']=='terrain_blocked':
            from . import terrain_process
            old_target=units[order['target']]
            new_units={u['name']:u for _,u in missions.units(after)}
            if (row['action']!='fire' or not any(terrain_process.blocked(before,a,b,'direct_fire') for a,b in
                    ((unit,old_target),(new_units[name],new_units[order['target']])))):
                raise ValueError(name+'：未登记相应地形遮挡，不能虚构停火原因')
        if not isinstance(row['assumptions'],str) or not row['assumptions'].strip():
            raise ValueError(name+'：须说明过程估计依据和未确定因素')
        for k in ('delay_s','active_fire_s','reload_remaining_s'):_number(row[k],k)
        delay=delay_seconds(before,unit)
        if abs(row['delay_s']-delay)>1:
            raise ValueError(name+f'：联络延迟须采用当前配置约{delay}秒，不能省略等待')
        period=cycle_period(before,row['action'],ref)
        initial=reload_seconds(unit,ref)
        if cycles:
            for k in ('first_fire_s','last_fire_s'):_number(row[k],k)
            first,last=row['first_fire_s'],row['last_fire_s']
            if (first+1e-6<max(delay,initial) or last>=seconds or last+1e-6<first+(cycles-1)*period
                    or not 0<row['active_fire_s']<=min(cycles*period,seconds-first)+1e-6):
                raise ValueError(name+'：射击时间/周期超出联络、装填或本轮窗口，不能把整轮历时当有效火力')
            if not any(e.get('attacker')==name and e.get('weapon_action')==row['action'] for e in result.get('engagements',[])):
                raise ValueError(name+'：有射击周期却缺实际交战记录')
            receivers.add(order['target'])
        elif (row['first_fire_s'] is not None or row['last_fire_s'] is not None or row['active_fire_s']!=0
              or row['stop_reason']=='none' or any(e.get('attacker')==name for e in result.get('engagements',[]))):
            raise ValueError(name+'：零射击周期不能声明发射时刻、有效火力或实际交战')
        if row['stop_reason'] in ('command_pending','reload_pending'):
            wait=delay if row['stop_reason']=='command_pending' else initial
            if cycles or wait+10<seconds:raise ValueError(name+'：等待原因与本轮延迟/装填窗口不一致')
        # Native telemetry truncates the subsecond remainder. The ledger must
        # follow its own last shot, rather than agreeing with a second stale field.
        expected=reload_after(before,unit,seconds,row=row,reference=ref)
        if not math.isclose(row['reload_remaining_s'],expected,rel_tol=0,abs_tol=1e-6):
            raise ValueError(name+f'：期末装填须={expected}秒，提交={row["reload_remaining_s"]:g}秒；'
                '有发射按末发时刻+对应周期-本轮秒数，无发射按轮初装填-本轮秒数，不自动纠正')
        cost=cycles*combat_effects.work_cost(ref,row['action'])*formation_parts.scale(unit)
        if not math.isclose(accounts[name]['ammo_spent'],cost,rel_tol=0,abs_tol=1e-6):
            raise ValueError(name+f'：射击周期与弹药账不符，应为{cost:g}等效工作量')
        shells=accounts[name]['spent'].get('shells',0)
        guns=next((e['operational'] for e in unit['equipment'] if e['category']=='artillery'),0)
        cap=min(limits[name],guns*cfg['shells_per_gun'])
        if (row['action']=='fire' and shells) or (row['action']!='fire' and not cycles<=shells<=cycles*cap):
            raise ValueError(name+'：炮弹账须匹配实际炮击周期与可用火炮，直射不能冒用间瞄弹耗')
        state=updates[name].get('formation',{})
        if not {'suppression','intel_age_min','intel_confidence','reload_remaining_s'}<=set(state):
            raise ValueError(name+'：射击后的压制、情报和装填估计状态须明确提交，不能静默保留轮初状态')
        if not math.isclose(state['reload_remaining_s'],row['reload_remaining_s'],rel_tol=0,abs_tol=1e-6):
            raise ValueError(name+'：装填估计状态与fire_ledger不一致')
    for name in receivers:
        if 'suppression' not in updates[name].get('formation',{}):
            raise ValueError(name+'：承受火力后的压制估计须明确提交；没有伤亡不等于没有压制')
    return {**copy.deepcopy(proposal),'source':'dsh_model_estimate','turn':before['mission']['turn']+1,
            'scope':'模型声明的过程与收支通过校验，不是原生遥测或历史效能校准'}


def instruction(world):
    basis=observation(world)
    if basis is None:return ''
    import json
    return ('\n共享火力过程先验：'+json.dumps(basis,ensure_ascii=False)+
        '\n地面fire/bombard/suppress必须提交fire_ledger={"version":"'+VERSION+'","units":[{"unit":"精确名称","action":"fire","target":"敌方精确名",'
        '"delay_s":0,"first_fire_s":null,"last_fire_s":null,"fire_cycles":0,'
        '"active_fire_s":0,"reload_remaining_s":0,"stop_reason":"uncertain",'
        '"assumptions":"估计依据与停止原因"}]}。示例仅为字段形状，不能照抄0；delay_s采用本局给定值，发射时刻以回合开始为0。'
        'stop_reason只选none/ammo/range/too_close/no_shells/target_unavailable/actor_unavailable/uncertain/command_pending/reload_pending/terrain_blocked/root_salvo_limit之一；command_pending和reload_pending只用于全轮未发射且仍在等待的情况。'
        '无地面射击命令时可省略，不能给hold添加射击；air_support仍用独立aviation协议。'
        '装填倒计时不能随省略fire_ledger而省略更新：所有编组按整轮经过秒数递减，待入场或失能也一样。'
        '无发射期末reload_remaining_s=max(0,reload_initial_s-本轮秒数)，有发射为max(0,last_fire_s+周期-本轮秒数)，截去不足1秒部分。'
        '轮初装填>0时，unit_updates.formation必须显式填reload_remaining_s，含归零；旧reload_remaining是周期数，仅无_s时乘artillery_cycle_s，不是秒。'
        '连续火力模型中，未被本轮火力命令指向的单位必须按整轮秒数恢复压制：suppression=floor(max(0,轮初suppression-suppression_decay*本轮秒数/1800)+1e-6)。'
        '结果改变时须在unit_updates.formation显式提交suppression，包括hold和move；不能因无交火而一直保留65等旧值，也不能跳过恢复到0。受击单位仍按实际过程估计，不套无来袭公式。'
        '每个周期都更新可用人数、压制及情报后再估计下一周期，不能按轮初效率一次乘完整历时。'
        '首发>=max(delay_s,reload_initial_s)，末发<本轮秒数，末发-首发>=(fire_cycles-1)*周期；'
        'active_fire_s<=min(fire_cycles*周期,本轮秒数-首发)。例如等待150秒的15分钟轮，120秒周期最多7次，不是8次。'
        '弹药ammo_spent=fire_cycles*按动作work_cost_by_action*resource_scale，与resource_ledger一致；未声明动作成本时沿用ammo_per_cycle。'
        'classified-indirect-1中fire消耗通用轻武器弹药，bombard/suppress只扣实际分类炮弹，不额外扣通用工作量；炮弹不能零消耗。分类炮弹按真实周期填写。'
        '宿主对共同聚合模型执行必要效能上界：按已申报周期与炮弹合并同目标所有来袭，效率上限1、忽略防护；suppress只用bombard的0.35。'
        '目标新增casualties扣除已经独立核验的航空效应与受降后，不得超过地面火力上界及轮初小数余量；不能以更改展开面积、虚构油弹或套用史料总数提高效能。'
        '必要上界不是预计伤亡，不设伤亡下限；通过也不是历史标定。'
        'unit_updates中射击方显式填写formation.suppression/intel_age_min/intel_confidence/reload_remaining_s；被射击方显式填写suppression，即使估计为0也说明依据。'
        '该账只声明估计，不提交last_execution或AFSIM内部余量，不要求必有伤亡，不按历史总数摊派。')
