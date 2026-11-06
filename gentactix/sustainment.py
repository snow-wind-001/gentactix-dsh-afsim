"""Read-only stock feasibility under the frozen per-round supply model.

This is an optimistic bound, not a transport executor, loss forecast or automatic
inventory correction. It deliberately reports the legacy package limitations.
"""
from . import campaign,formation_parts,missions,resource_accounts,support_dynamics,sim_clock,split_supply,mission_termination


def hold_demand(world, equivalents, *, personnel=None):
    nutrition = support_dynamics.configuration(world)
    return (support_dynamics.demand(nutrition, 'hold',
                sim_clock.duration_seconds(world['mission']['definition']['time_step']), equivalents,personnel=personnel)
            if nutrition else resource_accounts.food_demand('hold') * equivalents)


def decision_context(world, unit):
    """Freeze the input-time bound, never reconstruct it from a later world."""
    if not world.get('combined_arms') or not world.get('mission'):
        return None
    remaining = mission_termination.planning_turns(world['mission']['definition'],world['mission']['turn'])
    demand = hold_demand(world, formation_parts.scale(unit),personnel=unit['personnel']['current'])
    return {'turn': world['mission']['turn'], 'time': world.get('current_time'),
            'remaining_turns': remaining, 'unit_hold_food_per_round': demand,
            'unit_hold_food_budget': remaining*demand,
            'scope': '下令前冻结的单单位待命耗粮预算，不是到货保证或自动补给触发条件。'}


def assess(world):
    if not world or not world.get('combined_arms') or not world.get('mission'):
        return None
    mission=world['mission'];definition=mission['definition']
    nutrition=support_dynamics.configuration(world)
    split=split_supply.configuration(world)
    remaining=mission_termination.planning_turns(definition,mission['turn'])
    teams={}
    for team in ('red','blue'):
        units=[u for side,u in missions.units(world) if side==team and u['personnel']['current']>0]
        equivalent=sum(formation_parts.scale(u) for u in units)
        on_hand=sum(u['logistics']['food']*formation_parts.scale(u) for u in units)
        stock=sum(n['stock'] for n in world['supply_nodes'] if n['team']==team)
        food_stock=sum(n['commodities']['food'] for n in world['supply_nodes'] if n['team']==team) if split else stock
        demand=hold_demand(world,equivalent,personnel=sum(u['personnel']['current'] for u in units))
        need=remaining*demand
        mass=(nutrition['food_kg_per_work'] if nutrition and nutrition['version']==support_dynamics.PERSONNEL_VERSION else None)
        teams[team]={'available_units':len(units),'parent_equivalents':equivalent,
            'waiting_count':sum(campaign.release_seconds(world,u)>0 for u in units),
            'on_hand_food':on_hand,'warehouse_packages':stock,'food_per_hold_round':demand,
            'minimum_hold_food':need,'optimistic_food_shortfall':max(0,need-on_hand-food_stock),
            'max_covered_hold_rounds':(on_hand+food_stock)/demand if demand else None,
            **({'warehouse_food':food_stock,'warehouse_ammo':sum(n['commodities']['ammo'] for n in world['supply_nodes'] if n['team']==team)} if split else {}),
            'zero_food_count':sum(u['logistics']['food']==0 for u in units),
            'full_ammo_blocks_food_count':0 if split else sum(u['logistics']['ammo']==100 and u['logistics']['food']<100 for u in units),
            **({'max_shortage_hours':max((u['sustainment']['shortage_hours'] for u in units),default=0),
                'last_noncombat_losses':sum(u['sustainment'].get('last_receipt',{}).get('noncombat_delta',0) for u in units)} if nutrition else {}),
            **({'on_hand_food_kg':on_hand*mass,'warehouse_food_kg':food_stock*mass,
                'minimum_hold_food_kg':need*mass,'food_per_hold_round_kg':demand*mass,
                'optimistic_food_shortfall_kg':max(0,need-on_hand-food_stock)*mass} if mass is not None else {})}
    return {'version':'sustainment-bound-1','source':'read_only_frozen_rule_bound','remaining_turns':remaining,
        **({'dynamics':dict(nutrition)} if nutrition else {}),
        **({'supply_distribution':dict(split)} if split else {}),
        'step':definition['time_step'],'teams':teams,
        **({'horizon_kind':'rolling_plan','planning_note':'按目标完成；remaining_turns是滚动规划轮数，不是自动结束倒计时。'} if mission_termination.objective_driven(definition) else {}),
        'scope':'保持当前可用编组、剩余回合全部待命的理想库存上界；忽略运输、截断和分配限制，不保证实际到货。'
            +('当前按经过小时耗粮，累计缺粮时长与非战斗失能均使用显式估计；不是历史或生理效能标定。' if nutrition else
              '当前为每回合工作量，不是口粮重量或自然日消耗；等待阶段仍扣粮。')+
            ('粮弹分别扣仓、共用运输载重；warehouse_packages仅为质量当量，粮秣覆盖按warehouse_food计算。' if split else '粮弹绑定补给包同时补1粮/1弹，满弹可能阻止补粮；移动比待命耗粮更多。')+
            '短缺提示不自动补库存、减兵或判定胜负，不能据此推定历史饥饿伤亡。'}
