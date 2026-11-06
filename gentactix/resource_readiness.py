"""Read-only upper bounds on carried resources, never historical calibration."""
import math
from . import missions, combat_effects, support_dynamics, sim_clock, mission_termination


def fire_budget(world, unit, *, reference=None):
    """Read-only stock equivalents, never a firing schedule or effect executor.

    Work and classified shells are independent existing model constraints. A
    full-salvo equivalent assumes the current gun capacity and the unsplit root
    ceiling; it is not a cycle ceiling when guns/quotas change or a partial salvo
    fires. Future receipts, command timing and target availability are excluded.
    """
    cfg=world.get('mission',{}).get('definition',{}).get('combined_rules')
    if not cfg:return None
    from . import formation_parts, supply_schedule
    ref=reference if reference is not None else combat_effects.reference(world)
    def known(value):
        return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
    scale=formation_parts.scale(unit)
    work=known((unit.get('logistics') or {}).get('ammo'))
    cost=combat_effects.work_cost(ref,'fire')*scale
    indirect_cost=combat_effects.work_cost(ref,'bombard')
    indirect=None
    guns=next((e for e in unit.get('equipment',[]) if e.get('category')=='artillery'),None)
    if guns and guns.get('committed',0)>0:
        operational=known(guns.get('operational'));shells=known((unit.get('formation') or {}).get('shells'))
        cap=math.floor(min(cfg['max_salvo'],operational*cfg['shells_per_gun'])) if operational is not None else None
        full=math.floor(shells/cap) if shells is not None and cap else 0 if cap==0 and shells is not None else None
        remaining=shells-full*cap if full is not None else None
        indirect={'operational_guns':operational,'shells':shells,'shells_per_cycle_ceiling':cap,
            'full_salvos_at_ceiling':full,'remaining_shells':remaining,
            'partial_salvo_possible':bool(cap and remaining is not None and remaining>0),
            'shared_quota_included':False}
        if 'fire_accounting' in ref:indirect['generic_work_per_cycle']=indirect_cost*scale
    frozen=bool(world.get('combat_reference') or world.get('afsim',{}).get('combat_profile')
                or world.get('dsh_execution',{}).get('combat_profile'))
    return {'version':'fire-resource-budget-1','source':'configured_model_inputs',
        'profile_hash':ref['definition_hash'],'profile_source':'frozen_checkpoint' if frozen else 'registered_model_profile',
        'stock_snapshot':{'turn':world['mission'].get('turn'),'current_time':world.get('current_time'),
            'timing':'committed_state_after_turn','applies_to':'next_order_from_current_state',
            'settled_deliveries_already_included':True},
        'resource_scale':scale,
        'ammo_work':{'on_hand':work*scale if work is not None else None,'per_cycle':cost,
            'cycles_from_on_hand':math.floor(work/combat_effects.work_cost(ref,'fire')+1e-9) if work is not None else None,
            **({'applies_to':['fire']} if 'fire_accounting' in ref else {})},
        'indirect':indirect,
        'delivery_timing':'within_turn_events' if supply_schedule.configuration(world) else 'turn_end_only',
        'future_delivery_included':False,'is_readiness_or_effect_prediction':False,
        'scope':'当前余额为已提交快照，已包含截至本时点结算的到货；用于从当前状态发出的下一次命令，不是上一轮期初。'
            +('通用工作量只约束fire直射，炮击／压制仅扣分类炮弹，不额外扣直射工作量；不互相兑换。' if 'fire_accounting' in ref else '弹药工作量与分类炮弹为独立约束，不互相兑换；')+
            '仅按当前库存计算，不含未来到货。'
            '旧补给在轮末到货，下轮才可射击；定时到货可供到货后使用，不能据轮初预算断言整轮不能开火。'
            '完整齐射当量按当前火炮及本单位上限，不含同根分队共享额度；不足一次完整齐射的余弹仍可部分发射。'
            '实际还受人员、通信、装填、目标、距离、地形和时间约束；不是历史弹药标定或效果预测。'}


def assess(world):
    spec = world.get('mission', {}).get('definition', {}) if world else {}
    if not spec.get('combined_rules'):
        return None
    ref = combat_effects.reference(world)
    rules = spec['combined_rules']
    seconds = sim_clock.duration_seconds(spec['time_step'])
    remaining_hours = mission_termination.planning_turns(spec,world['mission']['turn']) * seconds / 3600
    cfg = support_dynamics.configuration(world)
    rows = []
    for team, unit in missions.units(world):
        warnings = []
        budget=fire_budget(world,unit,reference=ref)
        cycles=budget['ammo_work']['cycles_from_on_hand']
        fire_minutes = cycles * ref['direct_cycle_s'] / 60
        indirect=budget['indirect']
        salvo=indirect['shells_per_cycle_ceiling'] if indirect else 0
        shell_cycles=math.ceil(indirect['shells']/salvo) if salvo else 0
        from . import fire_process
        artillery_cycles=shell_cycles if combat_effects.work_cost(ref,'bombard')==0 else min(cycles,shell_cycles)
        artillery_minutes=artillery_cycles*fire_process.cycle_period(world,'bombard',ref)/60
        from . import formation_parts
        hourly=support_dynamics.unit_demand(cfg,unit,'hold',3600) if cfg else 0
        hold = unit['logistics']['food']*formation_parts.scale(unit)/hourly if hourly else None
        move = hold / cfg['move_factor'] if cfg and hold is not None else None
        if unit['personnel']['current'] <= 0:
            fire_minutes = artillery_minutes = 0
            hold = move = 0
            warnings.append('unit_unavailable')
        if cfg is None: warnings.append('time_food_model_missing')
        elif hold < remaining_hours: warnings.append('carried_food_shorter_than_remaining_window')
        if fire_minutes < seconds / 60: warnings.append('fire_budget_shorter_than_one_turn')
        rows.append({'team': team, 'unit': unit['name'], 'food_hold_hours': hold, 'food_move_hours': move,
                     'fire_work_minutes': fire_minutes, 'artillery_minutes': artillery_minutes,
                     'warnings': warnings,
                     **({'food_on_hand_kg':support_dynamics.food_mass(cfg,unit),
                         'food_capacity_kg':support_dynamics.food_capacity(cfg,unit)*formation_parts.scale(unit)*cfg['food_kg_per_work'],
                         'ration_kg_per_person_day':cfg['ration_kg_per_person_day']} if cfg and cfg['version']==support_dynamics.PERSONNEL_VERSION else {})})
    return {'version': 'carried-resource-budget-1', 'remaining_hours': remaining_hours, 'units': rows,
            **({'horizon_kind':'rolling_plan'} if mission_termination.objective_driven(spec) else {}),
            'historical_calibration': 'pending',
            'scope': '随队库存的理论上限，未计后续配送；不承诺持续接敌。炮弹与弹药工作量共同限制炮击，工作量不是实弹发数。'}
