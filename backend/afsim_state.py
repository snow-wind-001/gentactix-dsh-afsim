"""Bounded observations over application-owned world checkpoints, not chat history."""
import copy
import json
import math
from gentactix import commands, missions, history_replay, combat_effects, sim_clock, fire_process, resource_readiness, air_availability, campaign

_DETAIL_FIELDS=('personnel', 'equipment', 'formation', 'logistics', 'supply', 'morale',
                'attack_range', 'fire_sector', 'last_combat_effects')
_DETAIL_OPTIONAL_FIELDS=('formation_part','parameter_sources','historical_reference')


def source_queries(session):
    """Only defer texts already readable through the existing unit-detail tool."""
    from gentactix import observation_codec
    queries={}
    for identity,(_,unit) in commands.resolve_units(session).items():
        detail={key:unit[key] for key in _DETAIL_FIELDS+_DETAIL_OPTIONAL_FIELDS if key in unit}
        for text in observation_codec.source_texts(detail):
            queries.setdefault(text,dict(ids=[identity],limit=1,detail=True))
    return queries


def _selected(value, fields):
    """Project existing keys without turning absent/unknown evidence into zero."""
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    return {key: copy.deepcopy(value[key]) for key in fields if key in value}


def _equipment_observation(value):
    if not isinstance(value, list):
        return copy.deepcopy(value)
    return [_selected(row, ('category', 'name', 'committed', 'operational', 'damaged',
                           'destroyed', 'damage_load', 'calculation_source', 'carried_forward'))
            for row in value]


def _execution_observation(value):
    # Keep native measurements and their units; source paragraphs and debug
    # annotations stay in the checkpoint and are available through detail=True.
    return _selected(value, ('turn', 'action', 'source', 'fatigue', 'suppression', 'workforce_clock',
        'entrenchment', 'fuel_liters', 'spares', 'materials', 'shells', 'aa_rounds',
        'reload_remaining', 'reload_remaining_s', 'intel_age_min', 'intel_confidence',
        'signal', 'delay_s', 'shots', 'blocked', 'repaired', 'delivery_tons_milli',
        'distance_milli', 'ground_damage', 'ground_equipment', 'aa_spent',
        'transport_capacity_milli', 'command_done', 'fire_lat_micro', 'fire_lng_micro',
        'effective_protection_milli', 'received_fuel_liters', 'received_spares',
        'received_materials', 'received_shells', 'received_aa_rounds',
        'supply_receipt_revision', 'small_arms_rounds_estimate', 'fire_cycles',
        'active_fire_s', 'fire_stop_reason', 'combat_revision', 'continuous_motion'))


def operation_context(session):
    # Binding to the existing native bridge makes the detached copy once. This
    # data stays in the application, not in the model message.
    snapshot={key:session.get(key) for key in (
        'id', 'role_epoch', 'war_state', 'use_rag', 'scenario_input', 'battle_choice', 'history', 'trajectory',
        'simulation_mode', 'product_mode', 'time_step', 'turn_count', 'command_state', 'execution_backend','force_organization',
        'command_identity_origin','branch_origin')}
    snapshot['role_epoch']=session.get('role_epoch',0)
    return {'session':snapshot,'pre_adj':None}


def mission_context(world):
    from gentactix import sustainment, campaign_lifecycle
    mission = world.get('mission') or {}
    if not mission:
        return None
    definition = mission['definition']
    historical=definition.get('historical_calculation') or (definition.get('historical_synthetic') or {}).get('base')
    if historical:
        from gentactix.historical_operations import interaction_scope
        interaction=interaction_scope(historical['initial'])
    else:interaction=None
    profile = definition.get('combined_rules',{}).get('goal_profile',definition['profile'])
    dynamic = ['id', 'version', 'turn', 'status', 'progress', 'winner', 'reason', 'metrics']
    dynamic += {'rail': ['network'], 'underground': ['organization'], 'reception': ['accepted']}.get(profile, [])
    fields = ['profile', 'goal', 'objective', 'goal_radius_km', 'deadline_turn', 'required_turns',
              'rules', 'map_center', 'map_radius_km']
    if 'termination_mode' in definition:fields.append('termination_mode')
    if profile == 'reception': fields.append('ceasefire_turn')
    if profile in ('delay','breakout'): fields.append('exit')
    operational=definition.get('campaign_definition')
    plan=world.get('campaign_plan')
    plan_summary=({'campaign_objectives':{'version':plan['version'],'turn':plan['turn'],
        'total_nodes':len(plan['nodes']),'completed_nodes':sum(n['status']=='completed' for n in plan['nodes'].values()),
        'outcomes':copy.deepcopy(plan['outcomes']),'side_progress':copy.deepcopy(plan['side_progress']),
        'resolution':plan['resolution'],'read_tool':'get_campaign_objectives',
        'source':'host_goal_evaluator'}} if plan else {})
    phase_summary={}
    if campaign_lifecycle.definition(world):
        observed=campaign_lifecycle.observation(world,limit=1)
        phase_summary={'campaign_lifecycle':{**{key:observed[key] for key in ('version','turn','status','phase_index',
            'total','current_label','elapsed_seconds','minimum_remaining_seconds')},'read_tool':'get_campaign_lifecycle'}}
    return {**phase_summary,**plan_summary,**({'operational_process':{'objective':copy.deepcopy(operational['objective']),
        **({'objective_policy':operational['objective_policy'],'delay_goal':campaign.delay_assess(world),
            'spatial_metrics_note':'据点与阻援区域为参考态势，不作为迟滞夺控条件'} if operational.get('objective_policy') else {}),
        'surrender':copy.deepcopy(operational['surrender']),'current':copy.deepcopy(world['campaign']['objective']),
        'scope':'完整核心窗口的联合目标；入场、工事与受降参数是显式估计，不能称为原始史实命令或固定战果'}} if operational else {}),
            **({'historical_process_coverage':{
                'phase_id':historical['initial']['phase_id'],
                'local_goal_settled':mission.get('status')=='completed',
                'full_campaign_verified':False,'phase_transition_available':mission.get('status')=='completed' and not definition.get('historical_synthetic') and not plan,
                'continuity':copy.deepcopy(world.get('phase_handoff')),
                'transition_policy':{'mode':'validated_branch','same_frozen_profile_required':True,
                    'adjacent_clock_required':True,'automatic_replacements':False,
                    'carried_fields':['personnel','equipment','logistics','formation','sustainment','position','depots'],
                    'split_merge_requires_allocation_ledger':True},
                'scope':'仅冻结阶段的局部目标；结算不等于整场战役完成。连续阶段须使用已验证、时钟相接的续接入口；普通新建仍使用新初态。'}} if historical else {}),
            **({'interaction':interaction} if interaction else {}),**{key: copy.deepcopy(mission.get(key)) for key in dynamic},
            'objective_team':missions.objective_team(definition),
            'required_survivors':definition.get('combined_rules',{}).get('required_survivors',2),
            **{key: copy.deepcopy(definition.get(key)) for key in
                fields}, 'allowed_actions': missions.available_actions(world),
            **({'facilities':copy.deepcopy(world['combined_arms']['bridge']) if definition['combined_rules'].get('bridge_enabled',True) else None,
                'goal_profile':profile,'registered_model':definition['combined_rules']['version']}
               if world.get('combined_arms') else {}),
            'ledger': copy.deepcopy(mission.get('ledger', [])[:16]),
            'ledger_count': len(mission.get('ledger', [])),
            **({'supply_schedule':copy.deepcopy(definition['supply_schedule']),
                'supply_timing_scope':'固定累计时点的聚合服务；详时序按单位detail_query读取；不代表具名车队在途或历史标定。'} if definition.get('supply_schedule') else {}),
            'sustainment':sustainment.assess(world),
            **({'supply_accounting':{
                'ton_per_supply_unit':definition['combined_rules']['ton_per_supply_unit'],
                'cargo_mass_tons':copy.deepcopy(definition['combined_rules']['cargo_mass_tons']),
                **({'food_mass_share':definition['supply_distribution']['food_mass_share'],
                    'ammo_mass_share':1-definition['supply_distribution']['food_mass_share'],
                    'food_tons_per_work':definition['supply_distribution']['food_mass_share']*definition['combined_rules']['ton_per_supply_unit'],
                    'ammo_tons_per_work':(1-definition['supply_distribution']['food_mass_share'])*definition['combined_rules']['ton_per_supply_unit']}
                   if definition.get('supply_distribution') else {}),
                'budget_is_execution_trigger':False,
                'scope':'模型质量换算，未经历史运输标定；吨数=delivery*ton_per_supply_unit+各分类received*对应cargo_mass_tons。不是实际测重。'}}
                if world.get('combined_arms') else {}),
            **({'supply_stocks':[{'id':n['id'],'team':n['team'],'commodities':copy.deepcopy(n['commodities']),
                'mass_equivalent':n['stock']} for n in world['supply_nodes'][:16]],'supply_stock_count':len(world['supply_nodes'])}
                if definition.get('supply_distribution') else {}),
            'order_guidance': (missions.ORDER_GUIDANCE + 'AFSIM的air_support必须带敌方target_id，消耗独立航空油弹并由原生航路执行打击；旧无目标支援仅为补给干扰回放规则。目标标题中的到货影响是旧玩法；当前目标仍以控制目标区连续两轮判定，目标空袭只通过人员装备损失影响控制权，不自动削减全体补给。' if profile=='air' else missions.order_guidance(world))}


def _clock_context(session):
    world=session['war_state'];assessment=world.get('combat_assessment') or {}
    def known(value):
        return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
    elapsed=known((world.get('simulation_clock') or {}).get('elapsed_seconds'))
    turn=session.get('turn_count',0)
    last=known(assessment.get('elapsed_seconds')) if type(turn) is int and turn>0 and assessment.get('turn')==turn else None
    try:step=sim_clock.duration_seconds(session.get('time_step'))
    except ValueError:step=None
    return {'session_elapsed_seconds':elapsed,'last_turn_duration_seconds':last,'configured_step_seconds':step}


def observation(session, args=None):
    args = args or {}
    if not isinstance(args, dict) or type(args.get('detail', False)) is not bool:
        raise ValueError('detail须为布尔值；默认紧凑观测，true按单位读取完整字段')
    detail = args.get('detail', False)
    limit, offset = args.get('limit', 8), args.get('offset', 0)
    ids = args.get('ids') or []
    if type(limit) is not int or not 1 <= limit <= 16 or type(offset) is not int or offset < 0:
        raise ValueError('观察每页1–16个单位；分页位置须为非负整数')
    if not isinstance(ids, list) or len(ids) > 16 or any(not isinstance(identity, str) for identity in ids):
        raise ValueError('一次最多查询16个单位ID')
    readonly_history = bool(session['war_state'].get('history_replay'))
    cs = commands.state(session)
    pairs = commands.resolve_units(session, cs)
    # A source prompt names historical references, while the shared reader also
    # serves registered operational IDs. Resolve aliases only in readonly replay;
    # an open battle may have several calculation parts from the same reference.
    aliases = {unit['historical_unit_id']: identity for identity, (_, unit) in pairs.items()
               if readonly_history and unit.get('historical_unit_id')}
    resolved_ids = [identity if identity in pairs else aliases.get(identity, identity) for identity in ids]
    selected = [identity for identity in pairs if not ids or identity in resolved_ids]
    page = selected[offset:offset + limit]
    rows = []
    from gentactix import force_organization
    org=force_organization.state(session)
    group_by_leaf={k:g['id'] for g in org['groups'] for k in g['members']}
    chains=force_organization.command_chains(org)
    initial_units={u['name']:u for _,u in commands.iter_units(session['war_state'].get('mission',{}).get('definition',{}).get('initial_state',{}))}
    receipts={r.get('unit_id'):r for r in cs.get('receipts',[]) if r.get('turn')==session.get('turn_count')}
    for identity in page:
        entry, unit = pairs[identity]
        capability = commands.capabilities(session, unit, entry['team'])
        row = {'id': identity, 'team': entry['team'], 'name': entry['name'],
               'type': unit.get('type'), 'position': commands.known_position(unit),
               'available': False if readonly_history else commands.available(unit), 'hp': unit.get('hp'),
               'actions': [] if readonly_history else capability['actions'],
               'move_km': 0 if readonly_history else round(capability['move_km'], 4)}
        row['detail_query'] = {'ids': [identity], 'limit': 1, 'detail': True}
        from gentactix.personnel_projection import strength_pct
        strength=strength_pct(unit)
        if strength is not None:row['personnel_strength_pct']=strength
        if not readonly_history and 'air_pools' in capability:row['air_pools']=copy.deepcopy(capability['air_pools'])
        if not readonly_history and 'participation' in capability:row['participation']=copy.deepcopy(capability['participation'])
        if not readonly_history and 'arrival' in capability:
            row['arrival']=copy.deepcopy(capability['arrival'])
            row['operational_state']=copy.deepcopy(session['war_state']['campaign']['actors'][unit['name']])
            row['capture_range_m']=capability.get('capture_range_m')
        if not readonly_history and identity in receipts:
            receipt=receipts[identity]
            row['last_decision']={k:copy.deepcopy(receipt.get(k)) for k in ('turn','source','action','status','goal')}
            row['last_decision'].update({k:str(receipt.get(k) or '')[:400] for k in ('reason','rationale')})
            row['last_decision'].update(_selected(receipt, ('observation_version', 'before_logistics',
                'after_logistics', 'decision_context','task_context')))
            if receipt.get('operator_instruction'):
                row['last_decision']['operator_instruction'] = receipt['operator_instruction'][:4000 if detail else 600]
        if unit.get('name') in initial_units:
            row['configured_initial_position']=commands.known_position(initial_units[unit['name']])
            row['configured_initial_position_kind']='本局计算初态；缺载部署为模型估计，不是史实精确阵地'
        if unit.get('historical_unit_id'):
            row.update(historical_unit_id=unit.get('historical_unit_id'),
                       frame_evidence_status=unit.get('frame_evidence_status'))
        if session.get('force_organization') is not None:
            row['task_organization']={'revision':org['revision'],
                'leaf_key':force_organization.leaf_key(entry['team'],unit),
                'task_group_id':group_by_leaf.get(force_organization.leaf_key(entry['team'],unit)),
                'command_chain':chains.get(force_organization.leaf_key(entry['team'],unit),[])}
        if unit.get('formation_part'):
            from gentactix import formation_parts
            row.update(calculation_unit_id=unit['calculation_unit_id'],formation_part=_selected(unit['formation_part'],
                       ('version','group_id','part_id','numerator','denominator','parent_name')),
                       normalized_resource_scale=formation_parts.scale(unit))
        if unit.get('runtime_allocation'):
            from gentactix import formation_parts
            row.update(calculation_unit_id=unit['calculation_unit_id'],normalized_resource_scale=formation_parts.scale(unit),
                runtime_allocation=_selected(unit['runtime_allocation'],('version','operation_id','kind','origins')))
        row['attack_range_m'] = unit.get('attack_range')
        row['resources'] = {key: (unit.get('logistics') or {}).get(key) for key in ('food', 'ammo')}
        schedule=session['war_state'].get('supply_schedule') or {}
        if schedule.get('turn')==session.get('turn_count'):
            item=next((r for r in (schedule.get('ledger') or {}).get('units',[]) if r.get('unit')==unit['name']),None)
            if item:
                events=item['events']
                row['supply_schedule']={'version':schedule['version'],'source':schedule['source'],'turn':schedule['turn'],
                    'event_count':len(events),'delivery_times_s':[e['seconds'] for e in events if e['kind']=='delivery'],
                    'food_received':sum(e['food_received'] for e in events),'ammo_received':sum(e['ammo_received'] for e in events),
                    **({'events':copy.deepcopy(events)} if detail else {}),
                    'scope':'本轮内定时到货合计；无到货时点不在轮末额外配送。'}
                if schedule['version']=='scheduled-supply-2':
                    if item.get('nutrition_summary'):
                        row['supply_schedule']['nutrition_summary']=copy.deepcopy(item['nutrition_summary'])
                    fuel=item.get('fuel_timeline',{}).get('events',[])
                    if fuel:
                        row['supply_schedule']['fuel_flow']={'unit':'microliter',
                            'opening_microliters':fuel[0]['opening_microliters'],
                            **{k:sum(e[k] for e in fuel) for k in ('received_microliters','movement_spent_microliters','support_spent_microliters')},
                            'closing_microliters':fuel[-1]['closing_microliters']}
                        if detail:row['supply_schedule']['fuel_timeline']=copy.deepcopy(item['fuel_timeline'])
        if session['war_state'].get('mission'):
            from gentactix import supply
            node = supply.bound_node(session['war_state'], entry['team'], unit)
            row['supply_binding'] = {'node_id': node['id'], 'team': node['team'],
                'position': {'lat': node['lat'], 'lng': node['lng']}, 'stock': node['stock'],
                **({'commodities': copy.deepcopy(node['commodities'])} if 'commodities' in node else {}),
                'quantity_basis': 'normalized_work_units',
                **({'classified_stock_scope': 'team_pool'} if session['war_state'].get('combined_arms') else {})}
        if unit.get('sustainment'):row['sustainment']=copy.deepcopy(unit['sustainment'])
        row['personnel'] = {key:(unit.get('personnel') or {}).get(key)
                            for key in ('committed','current','casualties','noncombat_losses')}
        row['personnel'].update({key:unit['personnel'][key] for key in combat_effects.COUNT_FIELDS
                                 if key in (unit.get('personnel') or {})})
        if unit.get('historical_reference'):
            reference=unit['historical_reference']
            row['historical_reference']={'id':reference.get('id'),'name':reference.get('name'),
                'context':str(reference.get('context') or '')[:200]}
            row['count_basis']=str((unit.get('parameter_sources') or {}).get('personnel','演习估计或用户配置'))[:240]
        if session['war_state'].get('combined_arms'):
            if unit.get('crossing'):row['crossing']=copy.deepcopy(unit['crossing'])
            row['formation']={k:unit.get('formation',{}).get(k) for k in
                ('role','motorized','protection','dispersion_km2','fatigue','suppression','entrenchment','fuel_liters','spares','materials','shells','aa_rounds','reload_remaining','reload_remaining_s','signal','intel_age_min','intel_confidence')}
            row['formation']['last_execution']=_execution_observation(unit.get('formation',{}).get('last_execution'))
            if 'suppression_state' in combat_effects.reference(session['war_state']):
                from gentactix import suppression_state
                row['formation'][suppression_state.FIELD]=unit['formation'].get(suppression_state.FIELD,0)
                row['suppression_state']=copy.deepcopy(suppression_state.CONFIG)
            from gentactix import movement_feedback, motion_state
            if movement_feedback.continuous(session['war_state']):
                motion_state.validate_unit(unit)
                row['formation'].update({k:copy.deepcopy(unit['formation'][k])
                    for k in (*motion_state.FIELDS,motion_state.TASK_FIELD) if k in unit['formation']})
                row['motion_state']={'version':motion_state.VERSION,'units_per_point':motion_state.SCALE,
                    'microliters_per_liter':motion_state.SCALE,'clock_resolution_ms':1,
                    'feedback_cadence_ms':motion_state.CADENCE_MS}
            density=unit.get('formation',{}).get('last_density_sample')
            if (not session['war_state'].get('dsh_execution') and isinstance(density,dict)
                    and density.get('turn')==session['war_state'].get('mission',{}).get('turn') and density.get('source')=='afsim_native'
                    and density.get('version')==combat_effects.DENSITY_VERSION
                    and fire_process.density_configuration(session['war_state'])):
                row['formation']['last_density_sample']=copy.deepcopy(density)
            row['equipment']=_equipment_observation(unit.get('equipment'))
            row['weapon_limits_m']=copy.deepcopy(capability['weapon_limits_m'])
            row['weapon_ranges_m']={key:value['max_range_m'] for key,value in row['weapon_limits_m'].items()}
            row['weapon_warnings']=copy.deepcopy(capability['weapon_warnings'])
        assessment=session['war_state'].get('combat_assessment') or {}
        reviewed=next((r for r in assessment.get('units',[]) if r['name']==unit['name']),None)
        if reviewed:row['combat_assessment']=copy.deepcopy(reviewed)
        estimate=fire_process.receipt_for_unit(session['war_state'],unit['name'],session.get('turn_count',0))
        if estimate:row['model_fire_estimate']=estimate
        from gentactix import fire_effect_bounds
        constraint=fire_effect_bounds.receipt_for_unit(session['war_state'],unit['name'],session.get('turn_count',0))
        if constraint:row['effect_constraint']=constraint
        from gentactix import support_dynamics
        legacy_support=support_dynamics.legacy_receipt_for_unit(session['war_state'],unit['name'],session.get('turn_count',0))
        if legacy_support:row['legacy_support_constraint']=legacy_support
        if detail:
            row.update({key: copy.deepcopy(unit.get(key)) for key in _DETAIL_FIELDS})
            from gentactix import supply
            row['supply']=supply.index_value(unit)
            row.update({key:copy.deepcopy(unit[key]) for key in _DETAIL_OPTIONAL_FIELDS if key in unit})
            if not readonly_history and session['war_state'].get('combined_arms'):
                row['fire_resources']=resource_readiness.fire_budget(session['war_state'],unit)
        rows.append(row)
    mission = session['war_state'].get('mission') or {}
    from . import afsim_air
    air = afsim_air.state(session['war_state'])
    evidence = session['war_state'].get('afsim') or {}
    historical = session['war_state'].get('mission',{}).get('definition',{}).get('historical_calculation')
    derived=mission.get('definition',{}).get('historical_synthetic')
    verified = evidence.get('source') == 'dsh_native_mcp_controller' and evidence.get('status') == 'completed' and evidence.get('returncode') == 0
    clock = _clock_context(session)
    from gentactix import formation_parts
    roster_match=(evidence['roster_digest']==formation_parts.roster_digest(session['war_state'])) if evidence.get('roster_digest') else None
    return {**({'formation_groups':formation_parts.observation(session['war_state'])} if formation_parts.has_groups(session['war_state']) else {}),
            'source': 'committed_application_world', 'world_version': commands.world_version(session),
            'observation_detail': 'full_unit_detail' if detail else 'compact',
            'projection_note': '默认保留人员分类、装备数值、库存、当前命令回执与位置；省略来源长文不代表缺载。按单位detail_query或ids+detail=true读取完整单位字段。未知值不补0。人员保有率personnel_strength_pct为现有/累计投入的只读投影，不是核定编制满员率；HP仅保留旧兼容字段，不从中推算人数。',
            'turn': session.get('turn_count', 0), 'current_time': session['war_state'].get('current_time'),
            'elapsed_seconds':clock['session_elapsed_seconds'], **clock,
            'time_scope_note':'position为当前提交位置；configured_initial_position为本局初态。部署假设中的初始间距不能与机动后的当前间距直接比较；本轮无移动不代表此前未移动。',
            'native_fire_time_scope':fire_process.native_time_scope(),
            'event_time_semantics':{'combined_arms.events.seconds':'turn_offset_seconds',
                                    'elapsed_seconds':'session_cumulative_duration_seconds',
                                    'session_elapsed_seconds':'session_cumulative_duration_seconds',
                                    'last_turn_duration_seconds':'last_completed_turn_duration_seconds',
                                    'configured_step_seconds':'configured_step_duration_seconds',
                                    'combat_assessment.elapsed_seconds':'last_completed_turn_duration_seconds',
                                    'formation.last_execution.active_fire_s':'duration_seconds',
                                    'formation.last_execution.delay_s':'planned_communication_wait_seconds',
                                    'formation.last_execution.received_*':'end_of_turn_delivered_quantity',
                                    'model_fire_estimate.first_fire_s':'model_estimated_turn_offset_seconds_or_null_if_no_fire',
                                    'model_fire_estimate.last_fire_s':'model_estimated_turn_offset_seconds_or_null_if_no_fire',
                                    'model_fire_estimate.active_fire_s':'model_estimated_duration_seconds'},
            'time_step': session['time_step'], 'total_units': len(pairs), 'units': rows,
            'registered_list_complete':len(rows)==len(pairs),
            'next_offset': offset + limit if offset + limit < len(selected) else None,
            'unknown_ids': [identity for identity, resolved in zip(ids, resolved_ids) if resolved not in pairs],
            'objective': mission.get('definition', {}).get('goal'),
            'mission': mission_context(session['war_state']),
            **({'historical_synthetic':{'phase_id':derived['base']['initial']['phase_id'],
                'base_definition_hash':mission['definition'].get('base_definition_hash'),
                'base_actor_count':len(derived['base']['parameters']['actors']),
                'configured_actor_count':sum(len(rows) for rows in derived['configuration']['teams'].values()),
                'historical_outcome_required':False,
                'scope':'同一冻结历史初态派生的合成演习；改编人数、装备和新增编组为演习假设，来源单位不等于新增历史单位。'}} if derived else {}),
            **({'historical_calculation':{'profile_id':historical['initial']['profile_id'],
                'version':historical['initial']['version'],'phase_id':historical['initial']['phase_id'],
                'phase_label':next(p for p in historical['initial']['definition']['phases'] if p['id']==historical['initial']['phase_id'])['label'][:120],
                'phase_scope':next(p for p in historical['initial']['definition']['phases'] if p['id']==historical['initial']['phase_id'])['scope'][:500],
                'configured_start':historical['parameters']['clock']['start'],
                'execution_window':next(p for p in historical['initial']['definition']['phases'] if p['id']==historical['initial']['phase_id']).get('execution_window'),
                'actor_count':len(historical['parameters']['actors']),
                'parameter_kind':'model_estimate_where_facts_unknown','scope':'historical_identity_with_explicit_parameters',
                'limitations':historical['parameters']['assumptions'][:600]}} if historical else {}),
            'history_replay': (history_replay.observation(
                session['war_state'], limit=min(limit, 8), offset=offset) if readonly_history else None),
            'combined_arms':copy.deepcopy(session['war_state'].get('combined_arms')),
            'resource_readiness':resource_readiness.assess(session['war_state']),
            'terrain_model':copy.deepcopy(mission.get('definition',{}).get('terrain_model')),
            **({'operation_boundary':{'version':mission['definition']['operation_boundary']['version'],
                'center':copy.deepcopy(mission['definition']['operation_boundary']['center']),
                'radius_km':mission['definition']['operation_boundary']['radius_km'],
                'route_count':len(mission['definition']['operation_boundary']['routes']),
                'routes_query':{'detail':True,'limit':1,'offset':0},
                **({'routes':[copy.deepcopy(r) for r in mission['definition']['operation_boundary']['routes']
                    if r['team'] in {pairs[i][0]['team'] for i in page}],
                    'routes_scope':'所选单位阵营的登记通路'} if detail else {}),
                'scope':'作战区外仍在物理世界，保持实际位置、消耗与受击可能；只沿登记通路出入。'}}
                if mission.get('definition',{}).get('operation_boundary') else {}),
            **({'combat_reference':combat_effects.observation(session['war_state'])} if session['war_state'].get('combined_arms') and not readonly_history else {}),
            **({'combat_assessment':{k:copy.deepcopy(v) for k,v in session['war_state']['combat_assessment'].items() if k!='units'}}
               if session['war_state'].get('combat_assessment') and not readonly_history else {}),
            'air_operations': ({'version':air['version'], 'assets':air['assets'], 'assumptions':air['assumptions'],
                **({'pools':{i:{**copy.deepcopy(p),'entry':copy.deepcopy(mission['definition']['air_definition']['pools'][i]['entry']),
                    'rules':copy.deepcopy(mission['definition']['air_definition']['pools'][i]['rules']),
                    **({'availability':air_availability.observation(session['war_state'],mission['definition']['air_definition']['pools'][i])}
                       if 'availability' in mission['definition']['air_definition']['pools'][i] else {})}
                    for i,p in list(air['pools'].items())[offset:offset+limit]},
                    'pool_count':len(air['pools']),'pools_next_offset':offset+limit if offset+limit<len(air['pools']) else None}
                   if 'pools' in air else {}),
                'last_turn':air['last_turn'], 'missions':air['missions'][:6], 'mission_count':len(air['missions']),
                'recent_missions':air.get('recent_missions',[])[-6:], 'recent_missions_total':len(air.get('recent_missions',[]))} if air else None),
            'execution': {'verified': verified, 'receipt_scope':'last_completed_frame',
                'current_roster_match':roster_match,'current_unit_count':len(pairs),
                **{key: evidence.get(key) for key in
                ('source', 'phase', 'process_id', 'version', 'seconds', 'entity_count', 'scope', 'effects_source',
                 'historical_roster_count', 'geographic_reference_count', 'combat_entity_count', 'battlefield_initialized', 'motion_revision','combat_revision')}},
            'effects': {'motion': 'source_reference_frame_only' if readonly_history else 'not_yet_verified_for_current_roster' if roster_match is False else 'afsim_observed' if verified else 'not_yet_verified',
                'ledger': (evidence.get('effects_source') or missions.VERSION) if mission else 'not_modeled; existing_ledgers_preserved',
                'weapons': ('afsim_abstract_teaching_model' if str(evidence.get('effects_source','')).startswith('afsim-native-') else 'teaching_rules_only') if mission else 'not_modeled',
                'terrain_occlusion': 'explicit_finite_barriers; no_dem' if mission.get('definition',{}).get('terrain_model') else 'not_modeled',
                'visibility': 'historical_roster_reference; current_presence_unknown' if readonly_history else 'all_application_units_known; no_sensor_or_fog_model'},
            'rules': {'profile': mission.get('definition', {}).get('profile'),
                      'control_team': cs['control_team'], 'director': cs['director'], 'no_fire': cs['no_fire']}}


def initial_observation(session):
    # The first page used to contain only red units in larger scenarios. Keep
    # normal paging stable, but seed the planner with a bounded view of both sides.
    pairs = commands.resolve_units(session)
    ids = [identity for team in ('red', 'blue') for identity, (entry, _) in pairs.items()
           if entry['team'] == team]
    red = [i for i in ids if pairs[i][0]['team'] == 'red']
    blue = [i for i in ids if pairs[i][0]['team'] == 'blue']
    chosen = red[:4] + blue[:4]
    chosen += [i for i in ids if i not in chosen][:8-len(chosen)]
    value = observation(session, {'ids': chosen, 'limit': 8})
    value['next_offset'] = None
    value['registered_list_complete']=len(chosen)==len(pairs)
    value['paging_note'] = (f'本次已覆盖全部已登记单位条目（{len(pairs)}条）；不证明完整历史编制或传感器探测范围。' if value['registered_list_complete'] else
        f'初始观察优先覆盖双方，显示{len(chosen)}/{len(pairs)}条；完整登记名单须不带ids筛选从offset=0开始分页。')
    if len(pairs)>16 or session.get('force_organization'):
        from gentactix import force_organization
        structure=force_organization.view(session)
        value['force_organization']={'totals':structure['totals'],'node_count':len(structure['nodes']),
            'task_group_count':len(structure['groups']),'revision':structure['revision'],
            'scope':structure['scope'],'detail_tool':'get_force_organization',
            'paging':{'offset':0,'limit':12,'kind':'nodes'},
            'members_paging':{'offset':0,'limit':16,'kind':'members','revision':structure['revision']}}
    return value


def changes(session, args=None):
    args = {} if args is None else args
    if not isinstance(args,dict) or set(args)-{'limit','since_turn','through_turn','offset','view_version','mode'}:
        raise ValueError('状态变化查询参数非法')
    current=session.get('turn_count',0)
    mode=args.get('mode','changes')
    limit=args.get('limit',8);since=args.get('since_turn',0 if mode=='aggregate' else max(0,current-1))
    through=args.get('through_turn',current);offset=args.get('offset',0)
    if (type(limit) is not int or not 1<=limit<=16 or type(since) is not int or since<0
            or type(through) is not int or not 0<=through<=current or type(offset) is not int or offset<0):
        raise ValueError('状态变化查询范围非法')
    if mode not in ('changes','aggregate') or mode=='aggregate' and since>through:
        raise ValueError('变化模式或聚合轮次范围非法')
    expected=args.get('view_version')
    if offset and expected is None:raise ValueError('状态变化翻页必须沿用第一页的view_version版本与查询范围')
    query={'since_turn':since,'through_turn':through}
    if mode=='aggregate':query['mode']=mode
    records=[r for r in reversed(session.get('trajectory') or []) if since<r.get('turn',0)<=through]
    world_version=commands.world_version(session)
    version=commands.fingerprint([world_version,query,
        [(r.get('id'),r.get('turn'),r.get('epoch'),r.get('changes',[])) for r in records]])
    if expected is not None and expected!=version:
        raise ValueError('状态变化查询版本或范围已改变，请从offset=0重新读取，不能拼接不同版本的页面')
    if mode=='aggregate':
        from . import afsim_summary
        result=afsim_summary.summarize(records,query,offset,limit)
        next_offset=offset+len(result['units']) if offset+len(result['units'])<result['total_units'] else None
        return {'source':'committed_trajectory',**result,'world_version':world_version,'view_version':version,
            'window':{'since_turn_exclusive':since,'through_turn_inclusive':through,
                'first_requested_turn':since+1 if since<through else None,
                'includes_first_turn':since==0 and through>=1,'full_session':since==0 and through==current},
            'query':query,'offset':offset,'limit':limit,'limit_reached':next_offset is not None,'next_offset':next_offset,
            'next_args':{**query,'offset':next_offset,'limit':limit,'view_version':version} if next_offset is not None else None}
    items=[(r['turn'],c) for r in records for c in r.get('changes',[])]
    rows = []
    for turn,change in items[offset:offset+limit]:
        encoded = json.dumps(change, ensure_ascii=False)
        value = copy.deepcopy(change) if len(encoded) <= 1000 else {
            'summary_only': True, 'team': change.get('team'), 'name': change.get('name'),
            **{key: copy.deepcopy(change.get(key)) for key in ('moved_km','before_position','after_position')},
            'changed_fields': list(change.get('fields', {}))}
        if value.get('summary_only'):
            priorities={'logistics':('ammo','food'),'formation':('shells','aa_rounds','fuel_liters'),
                        'personnel':('current','casualties','killed','wounded','captured','missing','noncombat_losses')}
            numeric={}
            for field,keys in priorities.items():
                delta=change.get('fields',{}).get(field,{})
                for key in keys:
                    pair={side:(delta.get(side) or {}).get(key) for side in ('before','after')}
                    pair={side:v if type(v) in (int,float) and math.isfinite(v) else None for side,v in pair.items()}
                    if any(v is not None for v in pair.values()):
                        numeric[field+'.'+key]=pair
            value['numeric_deltas']=numeric
            value['numeric_fields_scope']='known_personnel_and_stock_fields_only'
            # Bounded projections preserve evidence needed for per-turn fire /
            # delivery analysis without sending formations, sources or worlds.
            receipt=(change.get('fields',{}).get('formation',{}).get('after') or {}).get('last_execution')
            if isinstance(receipt,dict) and type(receipt.get('turn')) is int and receipt['turn']==turn:
                selected={}
                for key in ('turn','fire_cycles','active_fire_s','fire_stop_reason','shots','small_arms_rounds_estimate',
                            'blocked','command_done','distance_milli','delay_s',
                            'received_shells','received_aa_rounds','received_fuel_liters','received_spares',
                            'received_materials','supply_receipt_revision'):
                    v=receipt.get(key)
                    if type(v) in (int,float) and math.isfinite(v):selected[key]=v
                for key in ('action','source'):
                    if isinstance(receipt.get(key),str):selected[key]=receipt[key][:96]
                value['execution_receipt']=selected
        rows.append({'turn':turn,'change':value})
    next_offset=offset+len(rows) if offset+len(rows)<len(items) else None
    next_args={**query,'offset':next_offset,'limit':limit,'view_version':version} if next_offset is not None else None
    return {'source':'committed_trajectory','changes':rows,'limit_reached':next_offset is not None,
            'world_version':world_version,'view_version':version,'query':query,
            'offset':offset,'limit':limit,'total_changes':len(items),'next_offset':next_offset,'next_args':next_args,
            'summary_semantics':'summary_only为选定字段投影，省略字段不代表原轨迹缺载。numeric_deltas保留已知端点，null端点未知，不补0也不计算差值；execution_receipt只保留对应轮的选定原始回执字段，明确0与缺载分开。distance_milli为毫米，moved_km为千米，delay_s为联络等待秒数。'}


def planning_prompt(session, prepared, instruction='', briefing='', *, covered_names=(), native_submit=False):
    from gentactix import campaign_lifecycle
    # Neither history/trajectory nor the immutable mission definition is serialized.
    initial = initial_observation(session)
    pairs = commands.resolve_units(session, prepared['state'] if 'registry' in prepared['state'] else None)
    covered = {item['command']['unit_id'] for item in prepared['manual']} | {item['unit_id'] for item in prepared['blocked']}
    required = [{'id': identity, 'team': entry['team'], 'name': entry['name']}
                for identity, (entry, unit) in pairs.items()
                if identity not in covered and entry['name'] not in covered_names and commands.available(unit)]
    from . import unit_order_submission
    output_contract = (unit_order_submission.PLANNER_INSTRUCTION if native_submit else
            '只返回JSON：{"orders":[{"unit_id":"已观察ID","action":"hold|move|fire|...",'
            '"duration":"next","destination":{"lat":0,"lng":0},"target_id":"已观察敌方ID",'
            '"rationale":"简短依据","expected_effect":"预期"}]}；不用的字段省略。\n')
    return ('你是GenTactix的DSH决策控制端；AFSIM执行运动，应用保存权威战局和账本。\n'
            '本轮只提交结构化行动，不生成或重写战场状态、人员装备账、地形和完整历史。'
            '需要更多单位时，使用get_afsim_observation分页或按ID读取；'
            '大兵团使用get_force_organization核对历史上级、各方向投入汇总和临时任务群；'
            '单世界阶段可用get_campaign_lifecycle分页读取，未来阶段目标尚未评分；阶段不重置部队与资源。'
            '已确认的持续任务可用get_force_tasks分页核对承担者、前置、权限和回执；其观察是最近已提交状态。'
            '本轮已准备的任务命令与等待待命属于已确认控制，不可另行覆盖；只为required_units规划。'
            '指挥机关和父编组不重复参战；kind=members可读当前command_chain，历史隶属不等于当前临时指挥权；命令仍提交required_units中的执行叶子ID。'
            '最近变化用get_afsim_changes；多轮人员装备与火力/到货累计优先mode=aggregate，逐轮证据用mode=changes。'
            '有next_args时照其参数继续翻页，不能把第一页当作全部。查询版本改变时重新从0读取。史料用retrieve_history。'
            '不确定命令是否符合资源、距离或施工条件时，提交前调用evaluate_action，args为{"orders":[候选命令]}；该工具只校验输入，不预报战果。'
            '只能使用单位actions中的行动和move_km预算；禁止射击等全局限制优先。'
            'move的duration=next要求目的地在本轮预算内；远处目标可明确用duration=until_arrived，宿主只提交本轮预算内路段，并不保证本轮到达。'
            '人工已确认命令不可覆盖。你同时负责双方未被人工或单位Agent覆盖的可行动单位；'
            'required_units是必须覆盖的双方名单，不是只控制红方。守备不动也必须提交hold及依据；'
            '不得因第一页只显示部分单位而遗漏蓝方或后续单位，遗漏将拒收并反馈重试。'
            '根据射程、任务和停火条件决定是否交战；不能为了显示战斗强行攻击，也不能无依据让整方永久待命。'
            'weapon_limits_m分别说明直射fire、间瞄bombard/suppress的最小/最大范围；仅列配发武器，当前是否可用仍以actions和资源为准。'
            'weapon_warnings指出保留的旧输入疑点，不得把它称为已核历史性能；可通过evaluate_action校验命令。'
            'combined_arms.events[].seconds是本回合开始后的执行时点，不是持续时长；delay_s为计划通信等待。'
            + fire_process.NATIVE_TIME_SCOPE + fire_process.density_scope(session['war_state']) +
            'session_elapsed_seconds及旧elapsed_seconds表示全局累计历时，last_turn_duration_seconds才是最近已完成一轮的历时；configured_step_seconds是配置步长，不得把累计时间当单轮时间。'
            'last_execution.received_*是本轮分类到货总量；未启用supply_schedule时在轮末到货，启用时须按单位定时时序核对。不能把净库存差当作发射量；旧回执缺字段时保持未知。'
            '决策理由是公开摘要，实际结果以后续执行回执为准。\n'
            '单位participation是宿主当前参与状态；后方待命或返场中不能进攻，仍保留实际位置与全部资源且可被打击。'
            '明确退出当前作战或重新投入时，move+until_arrived可附participation="withdraw"或"reenter"；普通机动不附此字段，最终目的地由宿主保留。\n'
            '航空资源见air_operations.pools（可按pools_next_offset翻页）及单位air_pools；availability.status为pending/expired时不得出动，完好数不代表已到场。多池时air_support须附本方可用air_pool的id，不得跨池借用。\n'
            + output_contract
            + json.dumps({'scenario_excerpt': session.get('scenario_input', '')[:1200],
                'simulation_mode': session.get('simulation_mode', 'open'), 'observation': initial,
                'required_units': required,
                'manual_orders': [x['command']['unit_id'] for x in prepared['manual']],
                'blocked_units': [x['unit_id'] for x in prepared['blocked']],
                'intent': prepared['state'].get('intent', ''), 'instruction': instruction},
                ensure_ascii=False, separators=(',', ':'))
            + ('\n本轮资料与规则：\n' + briefing if briefing else '')
            + campaign_lifecycle.instruction(session['war_state']))


def analysis_prompt(session, question, recent_messages=()):
    from gentactix import formation_parts, campaign_plan, movement_feedback
    partition_instruction = ('\n分队资源口径：' + formation_parts.RESOURCE_ACCOUNTING
                             if formation_parts.has_groups(session['war_state']) else '')
    return ('你是GenTactix的只读战局分析员。以本次已提交观察为准；'
            + campaign_plan.defensive_instruction(session['war_state']) +
            movement_feedback.causal_instruction(session['war_state']) +
            'session_elapsed_seconds及旧elapsed_seconds是全局累计历时；last_turn_duration_seconds是最近已完成一轮的历时，configured_step_seconds是配置步长。不能把累计四小时称为某一轮四小时，不能用配置步长补猜缺载的实际回执。'
            'combined_arms.events[].seconds是回合内发生时点，不能称为耗时。库存、实际发射量与到货须分账核对。'
            + fire_process.NATIVE_TIME_SCOPE + fire_process.density_scope(session['war_state']) +
            'model_fire_estimate是当前已提交的DSH射击估计，不是AFSIM遥测；first_fire_s/last_fire_s为本轮发生时点，active_fire_s才是估计时长。缺载或过期时不补造；累计工具缺少原生回执不能改称DSH未射击。'
            'received_*表示本轮分类到货合计；旧规则仅轮末到货，新supply_schedule按固定时点到货并可供后续时段使用，按单位detail_query查看时序。射击停止后再到货可使最终库存非零。缺回执保持未知，不猜测已收到或未收到。'
            '移动回执blocked=10表示燃油限制机动，命令接收不等于到达目的地；move_km是几何上限，不保证资源足够。distance_milli为毫米，moved_km为千米，不混用单位。'
            '按需调用get_afsim_observation分页/按ID核对。查询累计人员装备、库存、火力和到货时，优先get_afsim_changes(mode=aggregate)。累计模式默认自首轮起；从开局到当前应传since_turn=0或省略，不是1。'
            'since_turn为排除下界，through_turn为包含上界；第M至N轮传since_turn=M-1、through_turn=N。window.full_session=false只是局部窗口，不能把其火力求和称为全局累计；沿next_args读完不等于包含首轮。'
            '聚合只列有变化的单位；完整登记名单仍用observation。known_sum只累计已知回执，missing_receipts非零时不得称为完整总量；端点net_change不是实际消耗。'
            '自身active_fire_s不等于目标承受火力时长。装备待修与毁损分开，净库存不等于发射。需要逐轮依据、聚合缺载或不连续时再用mode=changes读取指定范围。'
            '聚合artillery_shells_fired是间瞄炮弹；原始shots混有直射周期，不能当作统一弹数。小武器射击尝试看small_arms_rounds_estimate，仍是模型估计。'
            '兵种以各单位观察的type和formation.role为准；共享fire动作或ammo工作量不代表属于同一兵种，不能把装甲单位统称为步兵。'
            '两种模式均沿next_args读完；版本改变须从0重读，不混页。retrieve_history核对史料。'
            'summary_only是字段投影，不能将压缩省略说成原始回执缺载；逐轮fire_cycles、active_fire_s、received_*优先查execution_receipt，分项已知端点查numeric_deltas，null端点不补0。'
            '先回答问题并给出简短公开分析，不输出内部推理，不下令、不改主战局。'
            '明确区分AFSIM实际运动、教学规则消耗、尚未建模效果与历史参考；'
            '不得把全局可见单位当作雷达侦测。AFSIM原生教学模型可产生抽象伤亡和库存数据，'
            '不能冒充已标定的真实武器、弹道、命中概率或地形遮挡。'
            '历史统计窗口或投入不同，不得据此断言本局伤亡偏低或先验系数本身偏低/偏高。条件限制可说明计算机制；因果归因须有相同初态的单因素只读对照或同窗口证据，否则明确为待验证假设。'
            '以effects.ledger/weapons及execution.effects_source区分后台原生模型与旧版Python教学结果，不串用来源。'
            '累计粮弹工作量从完整范围聚合的logistics_workload读取，毛到货delivery和消耗food_spent/ammo_spent分开；库存净变化不是消耗，不能把本轮费用乘轮数冒充累计。'
            '按每轮delivery_basis区分补给口径：mass_equivalent_split_stock的delivery仅为运输质量当量，粮食、弹药到货分别看food_received/ammo_received；满弹仍可单独补粮。'
            '旧包口径native_gross_receipt/declared_gross_estimate每份同时带1粮食和1弹药工作量，不能把这条规则套给分类库存；跨版本分别核对。'
            'sustainment是只读预算，不是AFSIM自动补给触发条件。行动原因须查用户命令或决策记录，不得从预算高低编造触发机制。'
            'last_decision的before_logistics、observation_version和decision_context属于下令前；after_logistics和当前sustainment属于执行后。剩余回合减少会改变预算，不能将前后预算不同直接判为错误。旧回执缺decision_context时保留未知，不用当前状态反推旧预算。'
            '轨迹缺少首轮决策只表示该轮记录未提供，不能推断AFSIM没有执行；执行证据须读取对应原生回执。'
            'decision_context为程序冻结数字，rationale是模型文字，二者矛盾时指出rationale错误，不能用旧文字覆盖程序数字。单单位预算=unit_hold_food_per_round*remaining_turns；团队预算看team_hold_food_budget，不把单单位与团队混比。'
            'operator_instruction是本轮用户自然语言指令；source=model_batch表示模型提交动作，不表示没有用户指示。未载指令不能推断用户未指示。'
            'aggregate.window.full_session只说明查询范围覆盖全局；coverage.missing_turn_count大于0时，known_sum只是已记录轮次的小计，不能称为本局完整累计。时间单位取configured_step_seconds，禁止凭空写24小时账本。人员current与casualties严格分列，零伤亡不等于人员为零。'
            'mission.supply_accounting提供模型吨数换算：delivery*ton_per_supply_unit加各分类到货*对应cargo_mass_tons；与delivery_tons_milli/1000核对，并保留取整误差。这是模型估计吨数，不是历史测重；缺参数才保留未知，不把已公开换算说成无法换算。'
            '分类配送的粮食模型吨数=food_received*food_tons_per_work，弹药模型吨数=ammo_received*ammo_tons_per_work；不得把food_received直接乘整个包的吨数，也不能再把分类量与delivery重复相加。'
            '燃油净减可能含机动、运补等用途，缺少分项回执时不得将全部净减少归因于移动。'
            '不得依据旧对话代替当前时刻和位置。未检索到或未知的数据明确保留未知。' + partition_instruction + '\n'
            + json.dumps({'observation': initial_observation(session),
                'recent_changes': changes(session),
                'program_facts': analysis_facts(session),
                'recent_dialogue': [{'role': str(m.get('role')), 'content': str(m.get('content') or '')[:700]}
                                    for m in list(recent_messages)[-4:]],
                'question': question}, ensure_ascii=False, separators=(',', ':')))


def analysis_facts(session):
    world = session['war_state']; evidence = world.get('afsim') or {}
    if world.get('history_replay'):
        return (f"【来源帧 · {world.get('current_time', '时间未知')}】\n"
                f"参战参考{sum(len(world.get(t+'_units', [])) for t in ('red','blue'))}条；"
                f"原生地名参考实体{evidence.get('geographic_reference_count', evidence.get('entity_count', '未知'))}个。"
                '这是来源与身份回放，不是部队运动或交战计算；本帧实到、位置和损耗未载时保持未知。')
    estimated=bool(world.get('dsh_execution'))
    lines = [f"【程序事实 · T+{session.get('turn_count', 0)} · {world.get('current_time', '时间未知')}】",
             '本次为DSH模型估计；以下读取已提交账，位移、交战和过程数值不是AFSIM原生遥测。' if estimated else
             f"本次已提交外部回传实体：{evidence.get('entity_count', '未知')}。位移由程序根据回传坐标计算。"]
    clock=_clock_context(session)
    definition=world.get('mission',{}).get('definition',{})
    graph = definition.get('campaign_plan') or {}
    node_labels = {n['id']: n['label'] for n in graph.get('nodes', [])}
    for node in graph.get('nodes', []):
        if node['condition']['kind'] != 'defend':
            continue
        metrics = (world.get('campaign_plan') or {}).get('nodes', {}).get(node['id'], {}).get('metrics', {})
        if not metrics:
            lines.append(f'程序防御目标「{node["label"]}」：防御目标尚未采样，部署区及核心人数保持未知，不补为0。')
            continue
        core = node_labels[node['condition']['against_node']]
        lines.append(f'程序防御目标「{node["label"]}」：部署区己方{metrics["own_personnel_in_region"]:g}人，'
            f'门槛{node["condition"]["minimum_personnel"]:g}人；部署区敌军{metrics["enemy_personnel_in_region"]:g}人。'
            f'「{core}」突破核心敌军{metrics["enemy_personnel_in_core"]:g}人，'
            f'门槛{metrics["enemy_core_minimum_personnel"]:g}人；当前核心突破判定为{"是" if metrics["breakthrough"] else "否"}。'
            '达到门槛即中断本方保持，不等待对方保持计时；部署区有敌不等于核心被突破。')
    if definition.get('historical_calculation') or definition.get('historical_synthetic'):
        lines.append('过程范围：当前仅计算冻结的历史阶段，局部目标结算不等于整场战役完成。阶段续接须核对同版本身份、相接时钟和连续账；普通新建另一阶段仍会使用新初态。')
        if world.get('phase_handoff'):
            lines.append('本阶段来自连续前态：'+str(world['phase_handoff']['source_hash'])+'；兵力、装备和库存继承已提交结果，不代表全战役历史效能通过。')
    def minutes(key):
        value=clock[key]
        return '未知' if value is None else f'{value/60:g}分钟'
    lines.append('时间口径：本局累计'+minutes('session_elapsed_seconds')+'；最近已完成一轮'
                 +minutes('last_turn_duration_seconds')+'；配置步长'+minutes('configured_step_seconds')+'。累计历时不能当作单轮历时或有效火力时长。')
    latest = next((r for r in reversed(session.get('trajectory') or []) if r.get('turn') == session.get('turn_count',0) and r.get('turn',0)>0), None)
    if latest is not None:
        moved = [c for c in latest.get('changes',[]) if isinstance(c.get('moved_km'),(int,float)) and c['moved_km']>0]
        lines.append(f"记录到{len(moved)}个单位产生位移：" + ('；'.join(f"{c['name']} {c['moved_km']} km" for c in moved[:8]) or '无正位移记录') + '。')
    from gentactix import movement_feedback
    lines.extend(movement_feedback.analysis_facts(world,latest))
    mission = world.get('mission')
    combined=world.get('combined_arms')
    latest_receipts = [r for r in (session.get('command_state') or {}).get('receipts', [])
                       if r.get('turn') == session.get('turn_count')]
    for r in latest_receipts[:16]:
        context = r.get('decision_context')
        if isinstance(context, dict) and all(k in context for k in
                ('remaining_turns', 'unit_hold_food_per_round', 'unit_hold_food_budget', 'turn')):
            lines.append(f"{r.get('unit_name','单位')}下令前单单位待命预算："
                f"{context['remaining_turns']}轮 × {context['unit_hold_food_per_round']} = "
                f"{context['unit_hold_food_budget']}粮食工作量（下令前T+{context['turn']}）；"
                f"该方合计{context.get('team_hold_food_budget','未载')}。这些是程序冻结值，模型理由与之冲突时以本条为准。")
    if any(r.get('operator_instruction') for r in latest_receipts):
        lines.append('本轮有用户自然语言指令记录；model_batch表示模型提交动作，不能据此宣称没有用户指示。')
    if combined:
        b=combined['bridge']
        origin='DSH聚合模型估计' if estimated else '团级原生模型'
        from gentactix import crossing_network
        for site in crossing_network.sites(world):
            if site.get('crossing_model'):
                receipt=site.get('crossing_receipt',{})
                flow=f"本轮编组工作量{receipt.get('used_work','未回传')}、货运工作量{receipt.get('cargo_work','未回传')}、容量预算{receipt.get('budget_work','未回传')}"
            else:flow=f"通行{site['used']}/{site['capacity']}"
            lines.append(f"{origin}：{site['name']}施工{site['progress']}%、完整度{site['integrity']}%、{flow}；地图为全知教学视图，指挥情报有独立时效，不能当作真实传感器态势。")
        for _,u in missions.units(world):
            f=u['formation'];r={} if estimated else f.get('last_execution',{})
            from gentactix import motion_state
            fuel=f['fuel_liters'];fatigue=f['fatigue']
            if motion_state.present(u):
                fuel=f'{motion_state.fuel_value(u):.6f}'.rstrip('0').rstrip('.')
                fatigue=f'{motion_state.fatigue_value(u):.6f}'.rstrip('0').rstrip('.')
            summary=f"{u['name']}：疲劳{fatigue}、压制{f['suppression']}、炮弹{f['shells']}、防空弹药{f['aa_rounds']}、油料{fuel}升；"
            if estimated:
                receipt=fire_process.receipt_for_unit(world,u['name'],session.get('turn_count',0))
                lines.append(summary+(f"DSH本轮射击估计{receipt['fire_cycles']}周期、联络等待{receipt['delay_s']}秒、有效火力{receipt['active_fire_s']}秒、停止原因{receipt['stop_reason']}。" if receipt else '无本轮射击过程估计，不推断实际火力时长。'))
            else:
                lines.append(summary+f"本轮联络等待{r.get('delay_s','尚未执行')}秒、执行状态码{r.get('blocked','未回传')}、修复{r.get('repaired','未回传')}件。")
            if 'received_shells' in r:
                timing='定时时点合计' if world['mission']['definition'].get('supply_schedule') else '轮末入账'
                lines.append(f"{u['name']}本轮分类到货（{timing}）：炮弹到货{r['received_shells']}发、防空弹药{r.get('received_aa_rounds','未回传')}发、燃油{r.get('received_fuel_liters','未回传')}升、备件{r.get('received_spares','未回传')}件、施工耗材{r.get('received_materials','未回传')}包。")
    air = world.get('air_operations')
    if air:
        lines.append('航空账（独立于地面弹药）：'+json.dumps(air['assets'],ensure_ascii=False))
        lines.append(f"本轮航空任务{len(air.get('missions',[]))}项；下列为带回合号的近期记录，不可当成本轮新增。")
        for task in air.get('recent_missions',air.get('missions',[]))[-6:]:
            lines.append(f"T+{task['turn']} 航空任务 {task['requester']}→{task['target']}：{task['outcome']}，出动{task['package']}架，损失{task['aircraft_lost']}架；期望人员减员{task['personnel_effect']}；该目标当轮实际归因合计{json.dumps(task.get('target_turn_effects'),ensure_ascii=False)}（同一目标同轮合计不可跨任务相加）。")
    if mission:
        ledger = mission.get('ledger', [])
        origin='DSH模型估计' if estimated else 'AFSIM后台教学模型' if str(evidence.get('effects_source','')).startswith('afsim-native-') else '教学规则'
        lines.append(origin+'当轮账：粮食消耗' + str(sum(r.get('food_spent',0) for r in ledger)) +
            '，弹药消耗' + str(sum(r.get('ammo_spent',0) for r in ledger)) +
            ('，粮食到货'+str(sum(r.get('food_received',0) for r in ledger))+'，弹药到货'+str(sum(r.get('ammo_received',0) for r in ledger))+'，运输质量当量' if mission['definition'].get('supply_distribution') else '，补给到货') +
            str(sum(r.get('delivery',0) for r in ledger)) + '（教学工作单位；无净变化不代表没有消耗）。')
        lines.append(f"当前规则类型：{mission['definition']['profile']}；允许动作：{', '.join(missions.available_actions(world))}。" +
            f"目标：{mission['definition']['goal']}；程序状态：{mission['status']}；进度：{mission['progress']}。")
    else:
        lines.append('本场景未建模武器战损与资源收支，已有账本保留；不能从无记录推断没有消耗。')
    return '\n'.join(lines)
