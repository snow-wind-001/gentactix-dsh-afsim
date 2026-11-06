"""DSH supplies process effects; application guards identity, accounts and objectives."""
import copy
import json
import math

from gentactix import commands, missions, sim_clock, combat_effects, fire_control, resource_accounts,air_assets,air_model_receipts,crossings,fire_process,reporting,suppression_state
from . import harness_engine as h, campaign_model

COMMAND_VALIDATION_VERSION='dsh-command-effects-1'


def _source_fields(prior,update,label):
    for key in ('source','calculation_source'):
        if key in update and (key not in prior or update[key]!=prior[key]):
            raise ValueError(label+'不能改写来源标签')


def _validate_effects(before,after,checked,result,events):
    """Check declared effects against orders; never generate or repair effects."""
    old={u['name']:(team,u) for team,u in missions.units(before)}
    current={u['name']:u for _,u in missions.units(after)}
    for name,(team,prior) in old.items():
        following=current[name];order=checked.get(name,{'unit':name,'action':'hold'})
        actual=missions.distance(prior,following)
        if order['action']!='move':
            from gentactix import ferries
            boat=ferries.carrier(before,name)
            if boat and boat['phase'] in ('outbound','unloading'):continue
            if actual>.01:raise ValueError(name+'：结果违反非移动位置命令，整轮拒收，不自动拉回坐标')
            continue
        if crossings.get_model(before):
            from gentactix import crossing_network
            plan=crossing_network.plan(before,prior,order)
            if plan:
                travelled=crossings.path_position(prior,plan['waypoints'],following)
                from gentactix import ferries
                extra=missions.distance(plan['entry'],plan['exit']) if ferries.config(before) else 0
                if travelled is None or travelled>missions.move_budget(before,prior)+extra+.01:
                    raise ValueError(name+'：移动不在登记渡河通道或超过机动预算')
                continue
        budget=missions.move_budget(before,prior,order)
        if actual>budget+.001:raise ValueError(name+'：实际位移超过本轮机动预算')
        if commands.available(following):
            if missions.distance(following,order)>.01:
                raise ValueError(name+'：结果未执行本轮移动位置命令，不得替换目的地')
        elif actual+missions.distance(following,order)>missions.distance(prior,order)+.02:
            raise ValueError(name+'：失能后的部分机动不在已提交位置命令范围内')
    incoming=set()
    for event in after.get('engagements',[]):
        name=event.get('attacker');order=checked.get(name)
        if order is None or order['action'] not in ('fire','bombard','suppress','air_support'):
            raise ValueError('交战没有对应的射击命令：'+str(name))
        if event.get('weapon_action')!=order['action']:
            raise ValueError('交战武器类型与命令不一致：'+name+'；应为'+order['action'])
        if event.get('attacker_team')!=old[name][0]:raise ValueError('交战攻击方与命令单位阵营不一致')
        target=order.get('target')
        if target not in old or event.get('target',target)!=target:
            raise ValueError('交战目标与命令target不一致：'+name)
        point={'lat':event['lat'],'lng':event['lng']}
        if min(missions.distance(point,old[target][1]),missions.distance(point,current[target]))>.05:
            raise ValueError('交战目标坐标不在命令target本轮已知位置50米内：'+name)
        incoming.add(target)
    for name,(_,prior) in old.items():
        captured=after.get('campaign',{}).get('actors',{}).get(name,{}).get('captured_this_turn',0)
        if current[name]['personnel']['casualties']-prior['personnel']['casualties']>captured and name not in incoming:
            raise ValueError(name+'：新增战斗减员缺少已声明的对应来袭交战；非战斗减员须单列，不补造开火')
    decisions=result.get('decisions',[])
    if not isinstance(decisions,list):raise ValueError('公开决策必须为数组')
    seen=set()
    for decision in decisions:
        if not isinstance(decision,dict):raise ValueError('公开决策必须逐项为对象')
        name=decision.get('unit_name')
        if not isinstance(name,str) or name not in old or decision.get('team')!=old[name][0] or name in seen:
            raise ValueError('公开决策遗漏方别、引用未知单位或重复单位')
        seen.add(name)
        if decision.get('action')!=checked.get(name,{'action':'hold'})['action']:
            raise ValueError('公开决策与实际命令不一致：'+name)
    for event in events:
        if 'action' not in event:continue
        name=event.get('unit')
        if name not in old or event['action']!=checked.get(name,{'action':'hold'})['action']:
            raise ValueError('过程事件行动须对应具名单位的本轮命令')


def _merge(base, update):
    if not isinstance(update, dict):
        raise ValueError('状态更新必须为对象')
    result=copy.deepcopy(base)
    for key,value in update.items():
        result[key]=_merge(result[key],value) if isinstance(value,dict) and isinstance(result.get(key),dict) else copy.deepcopy(value)
    return result


def apply(before, result, time_step, *, require_fire_ledger=False,validator=None):
    from gentactix import movement_feedback
    movement_feedback.require_executor(before)
    allowed={'unit_updates','orders','engagements','supply_nodes','combined_arms','objective_state','report','source_note','decisions','resource_ledger','aviation','fire_ledger','campaign','sustainment_ledger','supply_schedule_ledger'}
    if not isinstance(result,dict):raise ValueError('DSH回合结果须为JSON对象')
    unknown=set(result)-allowed
    if unknown:
        raise ValueError('DSH未知顶层字段 '+json.dumps(sorted(str(k)[:120] for k in unknown)[:12],ensure_ascii=False)+
            '；crossing_receipt必须放在combined_arms.bridge.crossing_receipt，舟艇状态放在combined_arms.bridge.ferry_state；'
            '不使用bridge_changes别名，不提交规则或整份战局。允许顶层字段：'+','.join(sorted(allowed)))
    from gentactix import observation_codec
    note=result.get('source_note')
    if note!=before.get('source_note') and observation_codec.has_reference(note):
        raise ValueError('source_note含只读来源引用，不能写入战局；请省略或填写完整说明，宿主保留原来源')
    rows=result.get('unit_updates')
    original={u['name']:u for _,u in missions.units(before)}
    if not isinstance(rows,list) or len(rows)!=len(original) or any(not isinstance(r,dict) for r in rows):
        raise ValueError('DSH更新必须逐项覆盖全部编组，包括待命编组')
    if len({r.get('unit') for r in rows})!=len(rows) or {r.get('unit') for r in rows}!=set(original):
        raise ValueError('DSH更新遗漏、重复或引用未知编组')
    checked=missions.validate_orders(before,result.get('orders'),time_step,validator=validator)
    from gentactix import suppression_state
    carried='suppression_state' in combat_effects.reference(before)
    if any(commands.available(u) and name not in checked for name,u in original.items()):
        raise ValueError('双方可行动单位都需要明确命令，包括hold')
    candidate=copy.deepcopy(before)
    index={u['name']:u for _,u in missions.units(candidate)}
    allowed={'lat','lng','hp','personnel','equipment','logistics','formation','morale','supply','status','crossing','sustainment'}
    crossing_updates={}
    for row in rows:
        name=row['unit'];changes={k:v for k,v in row.items() if k!='unit'}
        if set(changes)-allowed:raise ValueError('不得改写单位身份、兵种、来源或性能')
        if 'sustainment' in changes:
            from gentactix import support_dynamics
            if (not support_dynamics.configuration(before) or not isinstance(changes['sustainment'],dict)
                    or set(changes['sustainment'])!={'version','shortage_hours','noncombat_remainder'}):
                raise ValueError('DSH保障更新必须使用已启用模型，且不得提交原生回执')
        if 'crossing' in changes:crossing_updates[name]=changes.pop('crossing')
        for key in ('personnel','logistics','formation'):
            if key in changes:
                if not isinstance(changes[key],dict):raise ValueError('单位'+key+'更新必须为对象')
                _source_fields(original[name].get(key,{}),changes[key],name+' '+key)
        if 'formation' in changes and (not isinstance(changes['formation'],dict) or
                set(changes['formation'])&{'last_execution','last_density_sample','combat_damage_remainder','fatality_remainder','partition_noncombat_remainder'}):
            raise ValueError('DSH不能提交或改写原生执行回执与内部毁伤余量')
        if carried and (not isinstance(changes.get('formation'),dict) or
                        not {'suppression',suppression_state.FIELD}<=set(changes['formation'])):
            raise ValueError(name+'：新规则必须明确提交压制整数及余量')
        if 'formation' in changes:
            if not carried and suppression_state.FIELD in changes['formation']:
                raise ValueError('旧规则不能注入连续压制余量')
            if 'dispersion_km2' in changes['formation'] and changes['formation']['dispersion_km2']!=original[name]['formation']['dispersion_km2']:
                raise ValueError('展开面积是当前模型的冻结足迹，须在想定或编组配置中明确调整，不能在结果中改写效能上界')
            if 'role' in changes['formation'] and changes['formation']['role']!=original[name].get('formation',{}).get('role'):
                raise ValueError('编组配置角色不能在回合中改写')
            registered={'reload_remaining_s'}|({suppression_state.FIELD} if carried else set())
            if set(changes['formation'])-set(original[name].get('formation',{}))-registered:
                raise ValueError('编组状态更新包含未登记字段')
        if 'equipment' in changes:
            supplied=changes['equipment'];categories={e['category']:i for i,e in enumerate(original[name]['equipment'])}
            if not isinstance(supplied,list) or any(not isinstance(e,dict) for e in supplied):raise ValueError('装备更新必须为分类数组')
            ids=[e.get('category') for e in supplied]
            if len(set(ids))!=len(ids) or any(c not in categories for c in ids):raise ValueError('装备分类重复或未知')
            canonical=copy.deepcopy(original[name]['equipment'])
            for entry in supplied:
                slot=categories[entry['category']];prior=canonical[slot]
                if 'damage_load' in entry:raise ValueError('DSH不能提交原生装备毁伤余量damage_load')
                _source_fields(prior,entry,name+' 装备')
                if set(entry)-set(prior) or any(entry[k]!=prior[k] for k in ('name','committed') if k in entry):raise ValueError('不能修改装备身份或投入基数')
                canonical[slot]=_merge(prior,entry)
            changes['equipment']=canonical
        index[name].update(_merge(index[name],changes))
        for key in ('committed','current','casualties','noncombat_losses'):
            count=index[name]['personnel'].get(key)
            if type(count) is not int or count<0:
                raise ValueError(name+'：personnel.'+key+'须为非负整数；casualties是合计数，killed/wounded等分类与其同级，不嵌套对象')
        if index[name]['personnel']['casualties']<original[name]['personnel']['casualties'] or index[name]['personnel']['noncombat_losses']<original[name]['personnel']['noncombat_losses']:
            raise ValueError('累计人员损失不能减少')
        combat_effects.validate_personnel(index[name]['personnel'],original[name]['personnel'])
        if any(index[name]['personnel'].get(k)!=original[name]['personnel'].get(k) for k in ('current','casualties','noncombat_losses',*combat_effects.COUNT_FIELDS)):
            index[name]['personnel']['calculation_source']='dsh_model_estimate'
        for current,old in zip(index[name]['equipment'],original[name]['equipment']):
            if any(type(current.get(k)) is not int or current[k]<0 for k in ('committed','operational','damaged','destroyed')):
                raise ValueError(name+'：装备计数须为非负整数，不嵌套统计对象')
            if current.get('destroyed',0)<old.get('destroyed',0):raise ValueError('累计装备毁损不能减少')
            if any(current.get(k)!=old.get(k) for k in ('operational','damaged','destroyed')):
                current['calculation_source']='dsh_model_estimate'
    for key in ('supply_nodes','engagements'):
        if key in result:candidate[key]=copy.deepcopy(result[key])
    if 'engagements' not in result:candidate['engagements']=[]
    if not isinstance(candidate['engagements'],list) or any(not isinstance(e,dict) for e in candidate['engagements']):
        raise ValueError('实际交战事件必须为对象数组')
    model_events=[]
    if 'combined_arms' in result:
        supplied=result['combined_arms']
        if not isinstance(supplied,dict):raise ValueError('多兵种更新必须为对象')
        for key,value in supplied.items():
            if key in ('bridge','depots','events'):continue
            if key not in candidate['combined_arms'] or value!=candidate['combined_arms'][key]:
                raise ValueError('不能改写多兵种模型身份或规则摘要')
        model_events=copy.deepcopy(supplied.get('events',[]))
        if not isinstance(model_events,list) or len(model_events)>256:raise ValueError('DSH事件列表非法')
        for event in model_events:
            if not isinstance(event,dict) or set(event)-{'unit','action','seconds','status_code','turn','type','description','model_estimate'}:
                raise ValueError('DSH事件字段非法')
            if 'unit' in event and event['unit'] not in original:raise ValueError('DSH事件引用未知编组')
            if 'action' in event and event['action'] not in missions.available_actions(before):raise ValueError('DSH事件行动非法')
            if 'seconds' in event and (type(event['seconds']) not in (int,float) or not math.isfinite(event['seconds']) or not 0<=event['seconds']<=sim_clock.duration_seconds(time_step)):
                raise ValueError('DSH事件时间超出本轮')
            if 'turn' in event and (type(event['turn']) is not int or event['turn']!=before['mission']['turn']+1):raise ValueError('DSH事件回合非法')
            if 'status_code' in event and (type(event['status_code']) is not int or not 0<=event['status_code']<=7):raise ValueError('DSH事件状态非法')
            if 'model_estimate' in event and event['model_estimate'] is not True:raise ValueError('DSH事件必须标为模型估计')
            for key,limit in (('type',80),('description',2000)):
                if key in event and (not isinstance(event[key],str) or not event[key].strip() or len(event[key])>limit):raise ValueError('DSH事件文字非法')
        candidate['combined_arms']=_merge(candidate['combined_arms'],{k:v for k,v in supplied.items() if k in ('bridge','depots')})
    if candidate.get('combined_arms'):candidate['combined_arms']['events']=[]
    objective=result.get('objective_state',{})
    aviation=air_model_receipts.validate(before,candidate,result.get('aviation'),list(checked.values()),sim_clock.duration_seconds(time_step))
    if aviation is not None:candidate['air_operations']=aviation
    if set(objective)-{'network','organization','accepted'}:raise ValueError('目标完成与胜负必须由程序判定')
    candidate['mission'].update(objective)
    m=candidate['mission'];m['turn']+=1;m['last_orders']=copy.deepcopy(list(checked.values()))
    from gentactix import supply_schedule
    scheduled=supply_schedule.validate_ledger(before,result.get('supply_schedule_ledger'),list(checked.values()),sim_clock.duration_seconds(time_step),after=candidate)
    m['ledger']=resource_accounts.validate_transition(before,candidate,result.get('resource_ledger'),list(checked.values()),seconds=sim_clock.duration_seconds(time_step),scheduled=scheduled)
    if scheduled is not None:
        candidate['supply_schedule']={'version':result['supply_schedule_ledger']['version'],'turn':m['turn'],'source':'dsh_model_estimate',
            'ledger':supply_schedule.compact_ledger(result['supply_schedule_ledger'],scheduled)}
    # Only display metadata derives from the checked model stock accounts.
    # Rejected stock balances are never repaired by this index calculation.
    from gentactix import supply
    for unit in index.values():
        unit['supply']=supply.index_value(unit)
    from gentactix import support_dynamics
    legacy_support=support_dynamics.validate_model_transition(before,candidate,result.get('sustainment_ledger'),list(checked.values()),sim_clock.duration_seconds(time_step),scheduled=scheduled)
    if result.get('sustainment_ledger') and support_dynamics.configuration(before):
        for row in result['sustainment_ledger']['units']:
            index[row['unit']]['sustainment']['last_receipt']={k:v for k,v in row.items() if k!='unit'}
            index[row['unit']]['sustainment']['last_receipt'].update(source='dsh_model_estimate',turn=m['turn'])
    if legacy_support is not None:
        for name,remainder in legacy_support['accepted_remainders'].items():
            index[name]['formation']['partition_noncombat_remainder']=remainder
    crossings.validate_model_transition(before,candidate,crossing_updates,list(checked.values()),sim_clock.duration_seconds(time_step),result)
    candidate.pop('afsim',None)
    candidate['combat_reference']=combat_effects.reference(before)
    candidate['dsh_execution']={'source':'dsh_native_runtime','effects_source':'dsh_model_estimate','model_skipped':False,'events':model_events,
                                'combat_profile':copy.deepcopy(candidate['combat_reference']),
                                'resource_ledger_version':result['resource_ledger']['version'],'command_validation_version':COMMAND_VALIDATION_VERSION}
    if legacy_support is not None:candidate['dsh_execution']['legacy_noncombat_constraint']=legacy_support
    candidate['current_time'],candidate['simulation_clock']=sim_clock.target(before,time_step)
    from gentactix import unit_participation
    unit_participation.advance(before,candidate,list(checked.values()),sim_clock.duration_seconds(time_step),source='dsh_model_estimate')
    campaign_model.validate(before,candidate,result.get('campaign'),checked)
    missions.evaluate(candidate)
    (validator or missions.validate)(candidate)
    fire_control.enforce(candidate,before)
    _validate_effects(before,candidate,checked,result,model_events)
    if carried:
        suppression_state.validate_model_transition(before,candidate,list(checked.values()),sim_clock.duration_seconds(time_step))
    ledger=fire_process.validate(before,candidate,result,sim_clock.duration_seconds(time_step),required=require_fire_ledger)
    if ledger is not None:candidate['dsh_execution']['fire_ledger']=ledger
    if require_fire_ledger or ledger is not None:
        from gentactix import fire_effect_bounds
        candidate['dsh_execution']['effect_admission']=fire_effect_bounds.validate(before,candidate,result,ledger)
    from gentactix import c2_observation
    candidate['dsh_execution']['intelligence']=c2_observation.validate_transition(
        before,candidate,list(checked.values()),model_events,sim_clock.duration_seconds(time_step),source='dsh_model_estimate',
        minimum_delays={name:fire_process.delay_seconds(before,unit) for name,unit in original.items()})
    from gentactix import movement_feedback
    movement = movement_feedback.validate_transition(before,candidate,list(checked.values()),
        sim_clock.duration_seconds(time_step),source='dsh_model_estimate')
    if movement is not None:candidate['dsh_execution']['movement']=movement
    candidate['combat_assessment']=combat_effects.assess_turn(before,candidate,sim_clock.duration_seconds(time_step),result.get('orders',[]),source='dsh_model_estimate')
    return candidate


def observation_view(before):
    """Existing physical projection, before reversible model-only source encoding."""
    from gentactix import formation_parts
    view=copy.deepcopy({k:v for k,v in before.items() if k not in ('mission','afsim','situation_report','dsh_execution','historical_initial','combat_reference','combat_assessment','campaign_plan','campaign_lifecycle','unit_participation','supply_schedule','formation_registry','formation_runtime')})
    if before.get('formation_registry'):
        view['formation_identity']=dict(revision=len(before['formation_registry']['transactions']),
            source='host_validated_registration',history_in_context=False)
    if view.get('air_operations'):
        # Committed task IDs/events are history, not this turn's proposal schema.
        # Full receipts remain in the host checkpoint and observation endpoints.
        view['air_operations']={k:v for k,v in view['air_operations'].items()
                                if k in ('version','assets','pools','last_turn','assumptions')}
    if crossings.get_model(before):
        from gentactix import crossing_network
        for site in crossing_network.sites(view):site.pop('crossing_receipt',None)
        view['crossing_constraints']=crossings.observation(before)
    for _,unit in missions.units(view):
        from gentactix.personnel_projection import strength_pct
        strength=strength_pct(unit)
        if strength is not None:unit['personnel_strength_pct']=strength
        if formation_parts.is_fragment(unit):unit['normalized_resource_scale']=formation_parts.scale(unit)
        unit.pop('runtime_allocation',None)
        if 'unit_participation' in before:
            from gentactix import unit_participation
            unit['operation_participation']=unit_participation.unit_view(before,unit)
        if unit.get('crossing'):
            unit['crossing']={k:v for k,v in unit['crossing'].items() if k not in ('events','last_work','turn','source')}
        for item in unit.get('equipment',[]):item.pop('damage_load',None)
        for key in ('last_execution','last_density_sample','combat_damage_remainder','fatality_remainder'):
            unit.get('formation',{}).pop(key,None)
    from gentactix import movement_feedback
    movement=movement_feedback.observation(before)
    if movement is not None:
        view['movement_constraints']=movement
        view.get('combined_arms',{}).pop('movement_feedback',None)
    return view


def prompt(before,instruction='',briefing='',time_step=None,*,turn=None,settlement_preview=False,
           source_queries=None,world_version=None):
    from gentactix import movement_feedback
    movement_feedback.require_executor(before)
    from gentactix import support_dynamics,supply_schedule,observation_codec
    spec=before['mission']['definition'];time_step=time_step or spec['time_step']
    view=observation_codec.encode(observation_view(before),source_queries=source_queries,world_version=world_version)
    from gentactix import unit_participation
    from gentactix import movement_feedback
    food_instruction=unit_participation.instruction(before)+support_dynamics.instruction(before,sim_clock.duration_seconds(time_step))+movement_feedback.instruction(before)
    if not support_dynamics.configuration(before):
        food_instruction+='每个轮初有可用人员的单位，move需求4粮食工作量，其余行动需求2；food_spent取需求和轮初food+delivery的较小值。无可用人员时消耗与到货为0，不为缺粮自动编造死亡。'
    if supply_schedule.configuration(before):food_instruction=unit_participation.instruction(before)+supply_schedule.instruction(before,sim_clock.duration_seconds(time_step))
    from gentactix.personnel_projection import INSTRUCTION as personnel_instruction
    food_instruction+='\n'+personnel_instruction
    facets_shape=(',"fortification_components":[{"base_entrenchment":0,"fortification_integrity":0},{"base_entrenchment":0,"fortification_integrity":0}]'
        if any(r.get('fortification_components') for r in before.get('campaign',{}).get('actors',{}).values()) else '')
    process_shape=(',"campaign":{"actors":{"精确单位名":{"active":true,"fortification_integrity":0,"base_entrenchment":0,"captured_this_turn":0'+facets_shape+'}}}'
        if spec.get('campaign_definition') else '')
    message=('你是本回合唯一过程推演智能体，AFSIM关闭，所有运动、交战、人员装备损失与补给效果由你估计。'
        '不得声称调用AFSIM或确定性战斗算法。开放推演允许偏离历史结果。'
        '只输出JSON：{"unit_updates":[{"unit":"精确名称","lat":0,"lng":0,"personnel":{},"logistics":{},"formation":{}}],'
        '"orders":[{"unit":"精确名称","action":"fire","target":"敌方精确单位名"}],"engagements":[],"report":"本回合战报",'
        '"resource_ledger":{"version":"'+resource_accounts.VERSION+'","units":[{"unit":"精确名称","delivery":0,"food_spent":2,"ammo_spent":0,"supply_status":"未知","received":{},"spent":{}}]},'
        '"decisions":[{"team":"red|blue","unit_name":"精确名称","action":"hold","rationale":"公开依据"}]'+process_shape+'}。'
        '上述数值仅表示字段类型，实际值按当前态势和本轮命令确定。'
        'unit_updates、resource_ledger.units和decisions覆盖双方所有单位；未变化字段可省略，但情报时效随时间老化，收支账也不能省略。equipment可只提交变化分类，每项必须保留已知category，不改name或committed。'
        '原地待命仍须扣粮；凡收支导致粮弹余额变化，unit_updates必须提交对应期末logistics余额，不能仅填写消耗账而沿用旧库存。'
        'orders每个可行动单位一条明确命令。fire、bombard、suppress、air_support必须附target，值为当前可用敌方精确单位名字符串，不能省略或使用target_id。'
        '不能只提供交战动画代替命令目标。move附lat/lng；hold、resupply等不需要目标，不要照抄示例为所有单位开火。'
        'unit_updates的坐标必须执行本轮orders：非move保持原位；move选择本轮预算内可到达的终点，仍可行动时结果须在该终点10米内，不得替换目的地或只改坐标不改命令。失能可停在已提交路线内，不能借失能瞬移。'
        '实际交战必须由对应fire/bombard/suppress/air_support命令产生，weapon_action与命令action一致，攻击方匹配，target及目标坐标对应命令中的敌方单位已知起止位置50米内。没有命令的单位不得开火，不得换攻击对象。'
        '新增personnel.casualties必须有已声明且命令合法的对应来袭交战；没有交火不编造战斗损失，非战斗减员单列。允许已交火而未命中，不设置伤亡下限。'
        'decisions的team/unit_name/action必须与实际orders一致，不重复或编造单位；combined_arms.events若包含action也须提供unit并对应其实际命令。不得改写来源、编组role或原生内部余量。'
        '初始committed不得改变，人员committed=current+casualties+noncombat_losses；装备committed=operational+damaged+destroyed。'
        '人数与装备计数必须为整数。不要提交damage_load等AFSIM内部余量、formation.last_execution执行回执或last_density_sample原生采样；这些由宿主保留。'
        + (suppression_state.instruction() if 'suppression_state' in combat_effects.reference(before) else '') +
        '保留数量类型，累计损失不减，库存不得凭空补满。每个单位按supply_node_id绑定的本阵营仓库扣库，不按阵营首个仓库、最近仓库或总库存代替；同仓多单位到货须合计守恒。'
        '遵守人工优先、禁止射击和移动目的地；移动不能超限，原地射击不能任意移动。'
        + food_instruction +
        ('delivery是模型估计的本轮毛到货份数，每份同时带1粮食和1弹药工作量，不是库存净增加。resupply最多8份，其余最多2份，且不超过轮初粮弹各自到100的余量；未切断且有仓库库存才能到货，否则0。' if not spec.get('supply_distribution') else '') +
        'supply_status只能填未切断、已切断、未知，表示连通判断，不是是否安排运输。未补给时delivery填0；不得把未补给、未组织补给、DSH估计等写入supply_status，模型估计来源由程序另行标注。'
        + ('逐单位food_after=food_before+delivery-food_spent，ammo_after=ammo_before+delivery-ammo_spent；不能把待命当作不消耗粮食。提交supply_nodes的stock扣除同仓所有单位delivery合计，仓库不得凭空补货。' if not spec.get('supply_distribution') else '') +
        'received/spent是本单位分类物资的估计到货/消耗，允许fuel_liters、spares、materials、shells、aa_rounds，均非负整数，空对象明确表示五类全部0。分类期末=期初+received-spent；combined_arms.depots按同阵营received合计扣减。'
        + ('定时补给按各次到货前余额核对消耗；分类到货可独立于粮弹，但须计入同一批次吨位、共用仓库能力。实际交火仍申报ammo_spent。' if supply_schedule.configuration(before) else
           '分类到货须关联有效delivery批次。轮末到货不能支付本轮超过轮初库存的ammo或shells/aa_rounds/spares/materials消耗；'+
           ('分类炮弹计量中，炮击/压制的ammo_spent为0，必须提交实际shells消耗；直射仍须非零通用工作量。' if spec.get('fire_accounting') else '实际交火必须申报非零ammo_spent。')) +
        '仅本单位formation.motorized为true（本单位缺载时才沿用规则motorized）时，燃油spent至少覆盖实际公里数×(可用armor×2+可用transport×0.1)向上取整，不能只移动而不扣油。'
        '徒步单位不因move自动耗油；没有其他耗油活动或到货时fuel_liters保持原值，spent中的fuel_liters省略或填0。所有单位仍须逐项核对期末=期初+received-spent，不能只填spent却保留原库存。'
        '这些是现有教学模型的库存约束与估计收支，不是原生运输回执、真实吨数或历史消耗率；收支不成立会拒收候选，不由程序替你补算效果。'
        + ('预览或修订拒收时，先核对issues和calculation_diagnostics.mismatches的全部path/expected，合并需要的显式修订，包括保障回执／对应状态和装填秒数；这些是现有校验函数给出的条件计算事实，不是通过、执行或自动修补。改变行动、到货、位置等依赖后重新预览，不盲用旧数字。formation的fatigue/suppression/entrenchment/signal均为0至100整数，不将估计小数写入。' if settlement_preview else '') +
        'supply由宿主按校验后的min(food,ammo)派生，不必提交；它是指数，不是粮弹库存、可射击次数或线路通断。'
        '不提交mission、simulation_clock或规则定义。必要时可提交supply_nodes完整数组及combined_arms.bridge/depots变化。'
        'combined_arms.events若提供，属于DSH模型估计，使用{turn,type,description,model_estimate:true}，不得冒充原生回执。'
        '战报只覆盖本轮，不提前叙述未来；不自行宣布本轮目标状态，宿主将追加评分摘要。'
        '输入中的目标状态属于轮初，不得当成轮末结论。'+reporting.instruction(settlement_preview=settlement_preview)+'规则约束：'+missions.order_guidance(before)
        + '\n回合：'+time_step+'；结束时间：'+sim_clock.target(before,time_step)[0]
        + '\n本轮序号T+'+str(before['mission']['turn']+1 if turn is None else turn)+'；本次推演是整个战局的第'+str(before['mission']['turn']+1 if turn is None else turn)+'轮。单位任务执行次数另行记账。'
        + '\n目标：'+json.dumps({**{k:spec[k] for k in ('goal','objective','exit','goal_radius_km','deadline_turn','required_turns')},
            'objective_team':missions.objective_team(spec),'termination_mode':spec.get('termination_mode','deadline'),
            'goal_profile':spec.get('combined_rules',{}).get('goal_profile',spec['profile']),
            'turn':before['mission']['turn'],'progress':before['mission']['progress']},ensure_ascii=False)
        + '\n当前态势：'+json.dumps(view,ensure_ascii=False,
            **({'separators':(',',':')} if view.get('_provenance',{}).get('version')==observation_codec.DETAIL_VERSION else {}))
        +'\n史料：'+briefing+'\n全局指令：'+instruction)
    if spec.get('supply_distribution'):
        from gentactix import split_supply
        message=message.replace('"version":"'+resource_accounts.VERSION+'"','"version":"dsh-resource-ledger-2"').replace('"delivery":0,','"delivery":0,"food_received":0,"ammo_received":0,').replace('food+delivery','food+food_received')
        message+='\n'+split_supply.instruction(spec['supply_distribution'],scheduled=bool(supply_schedule.configuration(before)))
    from gentactix import campaign_plan, campaign_lifecycle, c2_observation
    return message+observation_codec.instruction(view)+c2_observation.instruction(sim_clock.duration_seconds(time_step))+campaign_model.instruction(before)+campaign_plan.instruction(before)+campaign_lifecycle.instruction(before)+air_model_receipts.instruction(before)+fire_process.instruction(before)+'\n历史战损参照（不是必达结局）：'+json.dumps(combat_effects.observation(before),ensure_ascii=False)+\
        '\n持续交战按实际接敌时间、武器发射周期、兵力、掩护和资源估计，不把数小时简化为一轮固定扣血。伤亡合计不是阵亡；可用killed/wounded/missing/captured/unclassified_casualties分类，分类合计须等于casualties。未知旧损失保留未分类；非战斗减员单列。'+\
        '\n千人以上部队持续激烈交战却只减员几人时，必须重新核查接敌时段、投入兵力、火力和掩护，并说明低损失的具体原因；不得复制上一轮固定损失。历史资料的死伤不等于阵亡，不把整场损失摊成小时指标。'+\
        '\n每条实际交战严格使用{"attacker":"精确单位名称","attacker_team":"red或blue","attacker_pos":[起点纬度,起点经度],"lat":目标纬度,"lng":目标经度,"weapon_action":"fire或bombard或suppress或air_support","description":"本轮实际过程"}。起点须为本轮已知单位位置，目标坐标来自态势；weapon_action区分炮击与直射，必须遵守对应射程/最小射程。未实际交火不编造事件。combined_arms.events中的seconds为回合开始后的发生时点，不是持续时长。'


def advance(session,prepared,observer,*,instruction='',briefing='',native_orders=(),cancel_check=None,role_id=None,fixed_orders=None,adjudication=None,world_validator=None):
    from gentactix import movement_feedback
    before=session['war_state']
    movement_feedback.require_executor(before)
    from . import turn_preview
    native_preview=session.get('agent_mode')=='native' and h.NATIVE_RUNTIME
    if native_preview and observer is None:observer=h.RunObserver('DSH原生过程与结算')
    preview_context=(turn_preview.context(session,prepared,native_orders=native_orders,fixed_orders=fixed_orders,
        operation_id=observer.operation_id,world_validator=world_validator) if native_preview else None)
    source_options={}
    if native_preview:
        from . import afsim_state
        source_options=dict(source_queries=afsim_state.source_queries(session),world_version=commands.world_version(session))
    message=prompt(before,instruction,briefing,session['time_step'],turn=session.get('turn_count',before['mission']['turn'])+1,
                   settlement_preview=native_preview,**source_options)
    if prepared:message+='\n'+commands.instruction(prepared,native_orders)
    from gentactix import formation_parts
    if formation_parts.has_groups(before):
        from gentactix import formation_parts
        from gentactix import support_dynamics
        cfg=support_dynamics.configuration(before)
        food_scale=('人员粮秣需求按当前人数计算，不再乘scale；库存与回执仍按既定scale编码。' if cfg and cfg['version']==support_dynamics.PERSONNEL_VERSION else
                    '已启用时间保障，使用前述每小时需求公式乘scale；不要使用旧每回合2/4。' if cfg else
                    '行动粮耗需求为原2或4乘scale；')
        message+=('\n计算分队共享父单位总账，不能把拆分当作增加兵力或库存。分队food/ammo仍为0至100归一化保障覆盖；'
                  'resource_ledger里的delivery/food_spent/ammo_spent为父编组等效工作量，scale=numerator/denominator。'
                  +food_scale+'可用粮弹等效量=logistics值乘scale。'
                  +('期末food=期初food+(food_received-food_spent)/scale，ammo使用ammo_received；delivery仅质量当量。' if before['mission']['definition'].get('supply_distribution') else '期末food=期初food+(delivery-food_spent)/scale，ammo同理；到货上限和库存余量也乘scale。')+
                  '分类装备、燃油、炮弹等是实际分配整数，不乘scale。不得改分队身份、比例、总账或原生partition_noncombat_remainder。'
                  '程序目标按原父单位去重；突围和渡运须该父单位所有仍可行动分队均满足，不把两个分队算成两个父单位。'
                  '\n只读分队总账：'+json.dumps(formation_parts.observation(before),ensure_ascii=False))
    from gentactix import ferries
    if ferries.config(before):
        message+=('\n舟艇采用formation-ferry-1；不要按桥梁施工进度禁止舟艇，也不能直接走过河。'
            '每艘只可乘载一个容量允许的互斥计算分队；主队超过seats或装备容量不能登船。'
            '提交完整combined_arms.bridge.ferry_state，字段保持当前结构；boats含id/lat/lng/bank/from_bank/phase/remaining_s/passenger/manifest_personnel/manifest_equipment_work/trips。'
            'phase为idle/loading/outbound/unloading/returning；passenger用精确单位名或null，不新增人或船。'
            'combined_arms.bridge.ferry_state.events每项为{boat_id,unit:精确单位名或null,phase:loading/boarded/landed/returned/cancelled/repositioning,seconds:本轮发生秒数,lat,lng}。'
            'unit_updates[].crossing.events是另一个列表，只允许{phase:entered或exited,seconds,lat,lng}，不能放boarded或landed。'
            '层级必须是：顶层combined_arms对象内的bridge对象，同时含ferry_state和crossing_receipt；这两个对象不在unit_updates内，也不在顶层。'
            '每个单位自身的crossing对象只放在对应unit_updates项内；它的岸点events与bridge.ferry_state的舟艇events分别填写。'
            '先到入口再装载；load_seconds后boarded，按speed_mps实际航行，卸载unload_seconds后landed，此后空艇returning再returned。'
            '跨轮保留船位、乘客、剩余装卸秒数及trips；未到出口并完成卸载，crossing.status不能completed。'
            'trips表示累计完成登岸航次：仅landed后加1；loading、boarded和outbound期间不增加。'
            'from_bank为该次原始出发岸/空艇返航目标，landed后仍保留，不能改成出口岸；bank表示最近靠泊岸，到岸后才变为出口岸，returned后变回原岸。'
            'landed和单位exited都指完成卸载，时刻至少为当前船位到出口的航行时间加unload_seconds；到岸但尚未卸载时用unloading。'
            'remaining_s仅为loading或unloading的剩余等待秒数；idle、outbound、returning时必须0，不能填剩余航行时间。'
            'repositioning只用于空艇受对岸请求调岸，unit必须null；载客outbound连续航行不需要额外舟艇事件。'
            'boarded占用本编组剩余required_work，单位crossing.last_work等于该量并进入transit；登岸才completed。'
            '装载/登船事件在入口，登岸在出口，返航在原岸；船与已登船乘客位置一致。'
            '已登船后的hold只停止地面自主动作，舟艇继续到岸，不能瞬移或返还已耗容量。'
            '本版没有仓库跨河货运、沉船、波浪水流及船上射击，不编造。所有数值为DSH估计，不冒称AFSIM原生回执。')
    if adjudication is not None:message+='\n已启用的几何约束：'+json.dumps(adjudication,ensure_ascii=False)
    if fixed_orders is not None:message+='\n本分支全部命令已固定，不得另行规划：'+json.dumps(fixed_orders,ensure_ascii=False)
    if native_preview:
        message=message.replace('只输出JSON：','候选效果字段示例（传给原生预览工具，不是最终答复）：',1)
        message=message.replace(',"report":"本回合战报"','',1)+turn_preview.INSTRUCTION
    for attempt in range(2):
        if cancel_check and cancel_check():raise RuntimeError('已取消过程推演，候选未提交')
        try:
            result=h.get_ai_response(message,role_id=role_id,observer=observer,cancel_check=cancel_check,
                **({'native_context':preview_context} if native_preview else {}))
        except h.JSONOutputError as exc:
            if (cancel_check and cancel_check()) or (observer is not None and observer.cancel_requested):
                raise RuntimeError('已取消过程推演，不再恢复最终JSON，候选未提交') from exc
            if attempt:raise ValueError('DSH最终JSON恢复后仍失败，本回合未提交、未推进：'+str(exc)) from exc
            message=h.json_recovery_prompt(message,exc,observer,cancel_check=cancel_check)
            if native_preview:
                hint=turn_preview.recovery_hint(observer,preview_context)
                message+=('\n本操作最近一次经核验的成功预览（只读且未提交）：'+json.dumps(hint,ensure_ascii=False)+
                    '\n优先依据该结算调用submit_turn_report提交完整战报候选；若改变效果，须先重新preview_turn_effects，不得沿用旧指纹。'
                    if hint else '\n本操作没有可复用的成功预览；必须先调用preview_turn_effects并成功，再调用submit_turn_report提交完整战报。')
            continue
        try:
            if cancel_check and cancel_check():raise RuntimeError('已取消过程推演，候选未提交')
            proof=None
            if native_preview:result,proof=turn_preview.resolve(result,observer,preview_context)
            orders=copy.deepcopy(fixed_orders) if fixed_orders is not None else result.get('orders')
            if not proof and fixed_orders is None and isinstance(orders,list):
                orders=[{k:v for k,v in o.items() if k not in ('intent_id','cancel_crossing')} if isinstance(o,dict) else o for o in orders]
            if prepared and not proof:
                overridden={o['unit'] for o in native_orders}
                orders=commands.merge_proposal(session,prepared,[o for o in (orders or []) if o.get('unit') not in overridden]+list(native_orders))
            checked=missions.validate_orders(before,orders,session['time_step'],validator=world_validator)
            if any(u['name'] not in checked for _,u in missions.units(before) if commands.available(u)):
                raise ValueError('双方可行动单位都需要明确命令，包括hold')
            result['orders']=orders
            after=apply(before,result,session['time_step'],require_fire_ledger=True,validator=world_validator)
            if proof:
                from gentactix import turn_settlement
                summary_version=proof.get('settlement_version',turn_settlement.LEGACY_VERSION)
                if (missions.digest(after)!=proof['after_hash'] or missions.digest(reporting.turn_settlement_summary(after,before,version=summary_version))!=proof['settlement_hash']):
                    raise ValueError('最终效果与成功预览的轮末世界或结算摘要不一致，未提交')
            if prepared:commands.verify_open(session,prepared,after,native_orders)
            if fixed_orders is not None:
                prior={u['name']:u for _,u in missions.units(before)};following={u['name']:u for _,u in missions.units(after)}
                for order in orders:
                    expected=order if order['action']=='move' else prior[order['unit']]
                    if commands.available(following[order['unit']]) and missions.distance(following[order['unit']],expected)>.01:
                        boat=ferries.carrier(before,order['unit'])
                        if order['action']=='hold' and boat and boat['phase'] in ('outbound','unloading'):continue
                        if crossings.pending_move(before,prior[order['unit']],following[order['unit']],order):continue
                        raise ValueError('DSH分支没有执行固定位置命令：'+order['unit'])
            return {**result,**({'report_preview':proof} if proof else {}),'report':str(result.get('report') or '')+'\n'+combat_effects.loss_summary(before,after)+' '+combat_effects.review_summary(after['combat_assessment']),
                    'updated_state':after,'source_note':'DSH独立推演；运动、交战、战损与补给为模型估计，程序仅校验与判定目标。'},orders,message
        except (ValueError,KeyError,TypeError) as exc:
            if attempt:raise ValueError('DSH候选校验重试后仍失败：'+str(exc)) from exc
            message+='\n候选未提交，请完整重发并修正：'+str(exc)
            if crossings.get_model(before):
                # Retry sessions may be fresh; show the typed draft explicitly,
                # without any reasoning, reports, full history or state repair.
                rows=result.get('unit_updates');model=result.get('combined_arms')
                draft={'unit_updates':[{k:copy.deepcopy(v) for k,v in u.items() if k in ('unit','lat','lng','crossing','logistics')}
                                       for u in (rows if isinstance(rows,list) else []) if isinstance(u,dict)],
                       'resource_ledger':result.get('resource_ledger'),
                       'orders':[{k:copy.deepcopy(v) for k,v in o.items() if k not in ('intent_id','cancel_crossing')}
                                 for o in (result.get('orders') if isinstance(result.get('orders'),list) else []) if isinstance(o,dict)],
                       **({'combined_arms':{'bridge':copy.deepcopy(model['bridge'])}} if isinstance(model,dict) and isinstance(model.get('bridge'),dict) else {})}
                encoded=json.dumps(draft,ensure_ascii=False)
                if len(encoded)<=32000:
                    message+='\n上次候选（未执行的模型草稿，非新态势）：'+encoded+'\n纠正上述校验错误，并保持其余正确的收支和几何关系；重新核对粮食移动扣4、待命扣2与期末库存。不输出或假定宿主已自动修复。'


def _comparison_session(session,record):
    """Expose only recorded decision-before facts to a fresh Native estimate.

    The factual result remains available to the host comparator, never to the
    model's domain tools. Current queues, task execution and group history may
    have changed after the selected decision and cannot supply missing history.
    """
    past=copy.deepcopy([r for r in session.get('trajectory',[]) if r['turn']<record['turn']
        and r.get('epoch',0)==record.get('epoch',0)])
    fields=('id','scenario_input','battle_choice','use_rag','product_mode','simulation_mode',
            'agent_mode','execution_backend','mission_id','command_identity_origin')
    branch={k:copy.deepcopy(session[k]) for k in fields if k in session}
    branch.update(war_state=copy.deepcopy(record['before']),time_step=record['time_step'],
        turn_count=record['turn']-1,role_epoch=record.get('epoch',0),trajectory=past,
        history=[r.get('report','') for r in past])
    policy=record.get('command_context',{}).get('policies',{})
    cs=commands.state(branch)
    cs.update({k:copy.deepcopy(policy[k]) for k in ('revision','control_team','director','no_fire','intent') if k in policy})
    cs['task_plans']=copy.deepcopy(record.get('force_task_plans',{}))
    branch['command_state']=cs
    if record.get('force_organization') is not None:
        branch['force_organization']=copy.deepcopy(record['force_organization'])
        # These snapshots recorded groups, not the event log. Never fill the
        # missing log with events from the current live organization.
        branch['force_organization'].setdefault('events',[])
    return branch


def compare(session,record,orders,observer):
    orders=crossings.comparison_orders(record,orders)
    before=record['before'];requested={o['unit']:o for o in orders}
    fixed=[requested.get(u['name'],{'unit':u['name'],'action':'hold'}) for _,u in missions.units(before) if commands.available(u)]
    branch=_comparison_session(session,record)
    result,_,_=advance(branch,None,observer,fixed_orders=fixed,cancel_check=lambda:bool(session.get('cancel_requested')))
    value=missions.compare_states(before,record['after'],result['updated_state'],fixed)
    value.update(mode='dsh_model_intervention',source='dsh_native_runtime',effects_source='dsh_model_estimate',runs=observer.runs,
        context_boundary=dict(source_trace_id=record['id'],visible_through_turn=record['turn']-1,
            visible_trace_count=len(branch['trajectory']),
            organization_snapshot_present=record.get('force_organization') is not None,
            recorded_task_plan_count=len(record.get('force_task_plans',{})),
            native_memory='fresh_session; original_private_memory_not_resumed'),
        limitations=['DSH单次估计有随机性，未控制模型随机性，不构成确定因果效应。',
            '只提供决策前公开轨迹和该轮登记的组织/任务子集；缺载信息不从终局补齐。原SDK私有记忆未续接。'],
        scope='同一决策前状态及公开前缀的新DSH会话单次命令干预；模型估计有随机性，不构成确定因果结论；不写回主战局。')
    return value
