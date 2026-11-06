"""Closed native WSF aggregate combat/support model. No Python turn executor."""
import copy
import math
from gentactix import missions, combined_arms, combat_effects, sim_clock, resource_accounts, fire_process, supply
from .afsim_literals import number as literal

FIELDS=('fatigue','suppression','entrenchment','fuel_liters','spares','materials','shells','aa_rounds',
        'reload_remaining','intel_age_min','intel_confidence','signal','delay_s','shots','blocked','repaired',
        'delivery_tons_milli','distance_milli','ground_damage','ground_equipment','aa_spent','transport_capacity_milli','command_done',
        'fire_lat_micro','fire_lng_micro','effective_protection_milli')
FIRE_FIELDS=('cycles','active_s','reload_s','damage_load','fatality_load','stop_reason')
CASUALTY_FIELDS=('killed','wounded','missing','captured','unclassified_casualties')
DENSITY_FIELDS=('sample_s','lat_cell','lng_cell','own_current','eligible','footprint_committed','footprint_current')
SUPPLY_FIELDS=('fuel_liters','spares','materials','shells','aa_rounds')
SUPPLY_CONTROL_REVISION=2
COMMAND_CONTROL_REVISION=2
INTELLIGENCE_REVISION=1
FORMATION_FIRE_CONTROL_REVISION=2
LEGACY_SUPPORT_REVISION=1


def validate_motion_fuel_totals(model,scene,motion,pools,depot_spent):
    """Check total physical stock across units and depots; never allocate it."""
    from gentactix import motion_state
    if (set(motion)!=set(scene['entities']) or set(depot_spent)!={'red','blue'}
            or any(type(v) is not int or v<0 or v%motion_state.SCALE for v in depot_spent.values())):
        raise ValueError('连续机动仓库保障燃油回执缺项或非法')
    old={u['name']:u for _,u in model['units']};result={}
    for team in ('red','blue'):
        own=[i for i,e in scene['entities'].items() if e['team']==team]
        opening=model['before_combined']['depots'][team]['fuel_liters']*motion_state.SCALE
        opening+=sum(motion_state.fuel_load(old[scene['entities'][i]['name']]) for i in own)
        closing=pools[team]['fuel_liters']*motion_state.SCALE+sum(motion[i]['fuel_microliters'] for i in own)
        movement=sum(motion[i]['fuel_spent_microliters'] for i in own)
        support=sum(motion[i]['support_fuel_spent_microliters'] for i in own)
        if opening!=closing+movement+support+depot_spent[team]:
            raise ValueError('连续机动单位与仓库燃油总账不守恒：'+team)
        result[team]=dict(opening_microliters=opening,closing_microliters=closing,
            movement_spent_microliters=movement,unit_support_spent_microliters=support,
            depot_support_spent_microliters=depot_spent[team])
    return result


def n(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('模型参数必须为有限数')
    return literal(value,precision=12)


def get(p,key):return f'{p}.AuxDataDouble("ca_{key}")'


def put(p,key,value):return f'{p}.SetAuxData("ca_{key}",(double)({value}));'


def _damage_total(p,precise):
    if precise:return f'({get(p,"pending_damage_micro")}+{get(p,"damage_remainder_micro")})/1000000'
    return f'{get(p,"pending_damage")}+{get(p,"damage_remainder")}'


def _density_roots(world):
    from gentactix import formation_parts
    return {u['name']:f'{team}:{i}' for team in ('red','blue')for i,group in enumerate(formation_parts.buckets(world,team))for u in group}


def _density_sample_lines(before,units,prefix,operational):
    """Generate native observations/feedback, never execute a Python timestep."""
    from gentactix import formation_parts
    index={u['name']:i for i,(_,u) in enumerate(units)}
    roots={u['name']:group for team in ('red','blue')for group in formation_parts.buckets(before,team)for u in group}
    lines=[]
    for i,(_,u) in enumerate(units):
        p=prefix+str(i)
        eligible=f'({get(p,"campaign_active")}>0 || TIME_NOW>={get(p,"campaign_release_s")})' if operational else 'true'
        lines.extend([put(p,'density_sample_s','TIME_NOW'),put(p,'density_eligible',f'(int)({eligible})'),
            put(p,'density_lat_cell',f'Math.Floor({p}.Latitude()*1000000+0.5)'),
            put(p,'density_lng_cell',f'Math.Floor({p}.Longitude()*1000000+0.5)')])
    for i,(_,u) in enumerate(units):
        p=prefix+str(i);current=f'densityCurrent{i}';committed=f'densityCommitted{i}'
        lines.append(f' double {current}=0; double {committed}=0;')
        for other in roots[u['name']]:
            if other['formation']['dispersion_km2']!=u['formation']['dispersion_km2']:continue
            q=prefix+str(index[other['name']])
            same=f'{get(p,"density_lat_cell")}=={get(q,"density_lat_cell")} && {get(p,"density_lng_cell")}=={get(q,"density_lng_cell")}'
            lines += [f' if ({same}) {{ {committed}={committed}+{get(q,"committed")};',
                f' {current}={current}+{get(q,"density_own_current")}*{get(q,"density_eligible")}; }}']
        lines.extend([put(p,'density_committed',committed),put(p,'density_current',current),
            put(p,'area_size_factor',committed+'/3000'),put(p,'area_strength_ratio',current+'/'+committed)])
    return lines


def _validate_density(rows,model,scene,*,accounts=None):
    """Necessary same-batch/count consistency; not proof of historic effects."""
    dynamic='fire_dynamics' in model.get('combat_profile',{})
    if not dynamic:
        if rows:raise ValueError('旧火力版本不能提交动态密度回执')
        return
    expected=set(scene['entities'])
    if set(rows)!=expected:raise ValueError('动态密度回执缺失或身份不完整')
    units={u['name']:u for _,u in model['units']}
    root_ids=model.get('density_roots')
    if not isinstance(root_ids,dict)or set(root_ids)!=set(units):raise ValueError('动态密度缺少完整冻结根编组绑定')
    if not isinstance(accounts,dict)or set(accounts)!=expected:raise ValueError('动态密度缺少完整期末人员账')
    groups={};times=set()
    for identity,row in rows.items():
        if set(row)!=set(DENSITY_FIELDS):raise ValueError('动态密度回执字段非法')
        sample=row['sample_s']
        if type(sample)not in (int,float)or not math.isfinite(sample)or not 0<=sample<=scene['seconds']:
            raise ValueError('动态密度采样时点非法')
        if any(type(row[k])is not int for k in DENSITY_FIELDS[1:]):raise ValueError('动态密度人数与坐标格须为整数')
        u=units[scene['entities'][identity]['name']]
        if (not -90000000<=row['lat_cell']<=90000000 or not -180000000<=row['lng_cell']<=180000000
                or not 0<=row['own_current']<=u['personnel']['current'] or row['eligible']not in (0,1)
                or row['footprint_committed']<=0 or row['footprint_current']<0):
            raise ValueError('动态密度人数、可用状态或坐标格越界')
        name=u['name'];arrival=(model.get('density_arrivals')or {}).get(name)
        if model.get('campaign_revision')is not None and not isinstance(arrival,dict):
            raise ValueError('动态密度缺少冻结到场约束')
        eligible=int(arrival['active'] or sample>=arrival['release_s'])if arrival else 1
        if row['eligible']!=eligible:raise ValueError('动态密度可用状态与到场时点不一致')
        final=accounts[identity].get('current')
        if type(final)not in (int,float)or not math.isfinite(final)or final<0 or final>row['own_current']:
            raise ValueError('动态密度采样人数小于期末可用人数或缺少有效人员账')
        key=(root_ids[u['name']],row['lat_cell'],row['lng_cell'],u['formation']['dispersion_km2'])
        groups.setdefault(key,[]).append((u,row));times.add(sample)
    if len(times)!=1:raise ValueError('动态密度必须来自同一采样批次')
    for members in groups.values():
        committed=sum(u['personnel']['committed']for u,_ in members)
        current=sum(row['own_current']*row['eligible']for _,row in members)
        if any(row['footprint_committed']!=committed or row['footprint_current']!=current for _,row in members):
            raise ValueError('动态密度同根共享兵力不守恒')


def compile_model(scene,before,orders,functions,version,*,shared_work_controls=None):
    from . import afsim_air,afsim_crossing,afsim_ferries,afsim_campaign,afsim_sustainment,afsim_supply_schedule
    from gentactix import campaign,crossing_network
    from . import afsim_crossing_network
    combined_arms.validate(before)
    orders=list(missions.validate_orders(before,orders,before['mission']['definition']['time_step']).values())
    cfg=before['mission']['definition']['combined_rules'];bridge=before['combined_arms']['bridge'];seconds=scene['seconds']
    nutrition=before['mission']['definition'].get('support_dynamics')
    from gentactix import support_dynamics
    from gentactix import movement_feedback
    from . import afsim_movement
    movement=movement_feedback.configuration(before)
    split=before['mission']['definition'].get('supply_distribution')
    from gentactix import supply_schedule
    scheduled=supply_schedule.configuration(before)
    from . import afsim_split_supply
    crossing=afsim_crossing.model(before)
    multi=crossing_network.enabled(before)
    operational=campaign.definition(before) is not None
    units=missions.units(before);by_name={u['name']:(team,u) for team,u in units}
    from gentactix import formation_parts
    from . import afsim_formation_parts
    grouped=formation_parts.has_groups(before)
    salvo=fire_process.salvo_limits(before,orders)
    area=fire_process.area_factors(before)
    identities={v['name']:k for k,v in scene['entities'].items()};cmd={o['unit']:o for o in orders}
    air=afsim_air.compile_air(scene,before,orders)
    reference=combat_effects.reference(before)
    continuous=reference['version'] in ('aggregate-fire-cycles-2.2','aggregate-fire-cycles-2.3','aggregate-fire-cycles-2.4','aggregate-fire-cycles-2.5','aggregate-fire-cycles-2.6')
    carried='suppression_state' in reference
    dynamic='fire_dynamics' in reference
    precise='damage_quantum' in reference
    # Profile 2 remains closed at the public execution boundary. This shared
    # compiler binding is exercised against real Native receipts before its
    # logistics/DSH/queue lifecycle can be admitted as a complete world version.
    motion=None
    work_ids=set()
    if shared_work_controls is not None:
        from . import afsim_shared_fortification
        if not movement_feedback.continuous(before):raise ValueError('事件施工须绑定连续机动时钟')
        afsim_shared_fortification.bind_world(before,scene,orders,shared_work_controls)
        work_ids={c['entity_id']for c in shared_work_controls}
    if movement_feedback.continuous(before):
        from . import afsim_continuous_motion
        if not carried:raise ValueError('连续机动整局须绑定现有压制余量模型')
        motion=afsim_continuous_motion.compile_process(
            afsim_continuous_motion.inputs(before,orders,scene['entities']),seconds,shared=True,
            fuel_event_times=supply_schedule.event_times(before,seconds) if scheduled else None,
            **({'shared_work_controls':shared_work_controls}if shared_work_controls is not None else {}))
    nourishing=bool(motion and motion.get('nutrition_revision'))
    if nourishing and air['tasks']:
        raise ValueError('连续保障与航空伤亡时钟尚未接通，不能回退为周期末人数')
    digest=missions.digest({'before':before,'orders':orders,'version':version,'combat_reference':reference,
                            'supply_control_revision':SUPPLY_CONTROL_REVISION,'command_control_revision':COMMAND_CONTROL_REVISION,
                            'intelligence_revision':INTELLIGENCE_REVISION,
                            'formation_fire_control_revision':FORMATION_FIRE_CONTROL_REVISION,
                            'legacy_support_revision':LEGACY_SUPPORT_REVISION if nutrition is None else None,
                            'motion_revision':scene.get('motion_revision'),
                            **({'movement_feedback':movement} if movement else {}),
                            **({'shared_fortification_digest':motion['shared_fortification']['model']['binding_digest']}if work_ids else {}),
                            **({'strength_clock_revision':1} if nourishing else {})})
    if movement:functions+=afsim_movement.functions()
    if carried:
        from . import afsim_suppression
        functions+=afsim_suppression.functions(cfg['suppression_decay'])
    if nourishing:
        from . import afsim_strength_clock
        functions+=afsim_strength_clock.functions(_damage_total('a',precise),
            afsim_campaign.get('a','captured') if operational else '0')
    if motion:functions+=motion['functions']
    lines=[functions, 'platform gtx_ca_hub WSF_PLATFORM',f' position {abs(bridge["lat"]):.10f}{"n" if bridge["lat"]>=0 else "s"} {abs(bridge["lng"]):.10f}{"e" if bridge["lng"]>=0 else "w"}', 'end_platform']
    # Every persistent numerical field is explicitly loaded into native AuxData.
    setup=['execute at_time 0.0001 sec absolute',' WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub");']
    for key in ('progress','integrity','materials','capacity'):
        setup.append(put('hub',key,n(bridge[key])))
    setup.append(put('hub','used','0'))
    if crossing:
        setup += [put('hub','cross_work','0'),put('hub','cross_cargo_work','0'),put('hub','cross_busy_until','0')]
    if multi:
        declarations,initial=afsim_crossing_network.setup(before)
        lines+=declarations;setup+=initial
    for team,pool in before['combined_arms']['depots'].items():
        for key,value in pool.items():setup.append(put('hub',team+'_'+key,n(value)))
        if motion:setup.append(put('hub','fuel_depot_support_'+team,'0'))
    for key in ('network','organization','accepted'):
        setup.append(put('hub',key,str(int(before['mission'][key]))))
    for team in ('red','blue'):
        setup.append(put('hub','aa_carry_'+team,n(before['combined_arms'].get('aa_loss_remainder',{}).get(team,0))))
    for i,(team,u) in enumerate(units):
        p=f'p{i}';identity=identities[u['name']];f=u['formation'];action=cmd.get(u['name'],{}).get('action','hold')
        setup.append(f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");')
        fields={key:f.get(key,0) for key in FIELDS};fields.update(shots=0,blocked=0,repaired=0,ground_damage=0,ground_equipment=0,
            delivery_tons_milli=0,distance_milli=0,aa_spent=0,command_done=0)
        fields.update(protection=f['protection'],dispersion=f['dispersion_km2'],pending_damage=0,pending_stress=0,
            intel_observed_at_s=-60*f['intel_age_min'],
            intel_confidence_base=f['intel_confidence'],intel_confidence_at_s=0,
            pending_suppression=0,suppression_sample_at_s=0,ammo_spent=0,initial_lat=u['lat'],initial_lng=u['lng'],direct_range_m=combined_arms.weapon_limits(before,u)['fire']['max_range_m'],
            strength_ratio=u['personnel']['current']/u['personnel']['committed'],size_factor=u['personnel']['committed']/3000,
            initial_current=u['personnel']['current'],committed=u['personnel']['committed'],
            live_strength_ratio=u['personnel']['current']/u['personnel']['committed'],
            fire_cycles=0,active_fire_s=0,fire_stop_reason=0,
            salvo_limit=salvo[u['name']],
            area_size_factor=area[u['name']]['size_factor'],area_strength_ratio=area[u['name']]['strength_ratio'],
            small_arms_attempts=0,
            damage_remainder=f.get('combat_damage_remainder',0),fatality_remainder=f.get('fatality_remainder',0),
            ammo_available=u['logistics']['ammo']*formation_parts.scale(u),
            ammo_cycle=combat_effects.work_cost(reference,action if action in ('fire','bombard','suppress') else 'fire')*formation_parts.scale(u))
        if dynamic:fields['density_own_current']=u['personnel']['current']
        if carried:
            from gentactix import suppression_state
            fields.update(suppression_ticks=suppression_state.load(u),pending_suppression_ticks=0,suppression_sample_ms=0)
        if precise:
            fields.update(pending_damage_micro=0,damage_remainder_micro=math.floor(f.get('combat_damage_remainder',0)*1000000+.5))
        if action=='conceal':fields['protection']=min(1,fields['protection']+.25)
        if action=='move':fields['entrenchment']=0
        for key,value in fields.items():
            encoded=n(value)
            if carried and type(value) is int and abs(value)>2147483647:encoded+='.0'
            setup.append(put(p,key,encoded))
        if carried:setup.append(f' GtxSuppressionDecay({p},0);')
        setup += [f' {p}.SetAuxData("gtx_air_damage",0.0);',f' {p}.SetAuxData("gtx_air_equipment",0.0);']
        for e in u['equipment']:
            for key in ('operational','damaged','destroyed','damage_load'):
                setup.append(put(p,e['category']+'_'+key,n(e.get(key,0))))
        armor=next(e for e in u['equipment'] if e['category']=='armor')
        if armor['committed']:
            shield=f'{n(f["protection"])}*(0.3+0.7*{get(p,"armor_operational")}/{armor["committed"]})'+('+0.25' if action=='conceal' else '')
            setup.append(put(p,'protection','Math.Min(1,'+shield+')'))
        setup.append(put(p,'effective_protection_milli',f'GtxRound({get(p,"protection")}*1000)'))
        node=supply.bound_node(before,team,u)
        delay=fire_process.expression('command_delay',{'command_base_s':n(cfg['command_base_s']),
            'signal':get(p,'signal'),'command_signal_s':n(cfg['command_signal_s']),
            'distance_to_depot_km':f'GtxDistance({n(u["lat"])},{n(u["lng"])},{n(node["lat"])},{n(node["lng"])})',
            'command_distance_s_per_km':n(cfg['command_distance_s_per_km'])},wsf=True)
        if motion:
            delay=n(motion['controls'][identity]['task']['wait_remaining_ms']/1000
                    if action=='move' else fire_process.delay_seconds(before,u))
            if identity in work_ids:
                control=next(c for c in shared_work_controls if c['entity_id']==identity)
                state=control['state']
                delay=n((state['wait_remaining_ms']if state['intent_id']==control['intent_id']else control['command_delay_ms'])/1000)
        setup.append(put(p,'delay_s',delay))
        cooldown=f.get('reload_remaining_s',f['reload_remaining']*reference['artillery_cycle_s'])
        setup.append(put(p,'reload_initial_s',n(cooldown)))
        setup.append(put(p,'next_fire_s',f'Math.Max({get(p,"delay_s")},{n(cooldown)})'))
        if action=='move' and not motion:
            order=cmd[u['name']];target=order
            setup += [f' bool fuelLimited{i}=false;',
                f' double pause{i}=Math.Max({get(p,"delay_s")}+{seconds}*({get(p,"fatigue")}/200.0+{get(p,"suppression")}/250.0),{seconds}*(1-{get(p,"strength_ratio")}));']
            if cfg.get('bridge_enabled',True) and not crossing:
                setup += [f' bool cross{i}=({n(u["lng"])}-{n(bridge["lng"])})*({n(target["lng"])}-{n(bridge["lng"])})<0;',
                f' if (cross{i}) {{',
                f'  if ({get("hub","progress")}<100 || {get("hub","integrity")}<50) {{ {put(p,"blocked","1")} }}',
                f'  else if (!GtxBlocked({n(u["lat"])},{n(u["lng"])},{n(target["lat"])},{n(target["lng"])},{n(bridge["lat"])},{n(bridge["lng"])},{cfg["bridge_corridor_km"]})) {{ {put(p,"blocked","3")} }}',
                f'  else if ({get("hub","used")} >= {get("hub","capacity")}) {{ {put(p,"blocked","2")} }}',
                f'  else {{ {put("hub","used",get("hub","used")+"+1")} }}', ' }']
            if f.get('motorized',cfg['motorized']):
                rate=f'({get(p,"armor_operational")}*2+{get(p,"transport_operational")}*0.1)'
                need=f'GtxDistance({n(u["lat"])},{n(u["lng"])},{n(target["lat"])},{n(target["lng"])})*{rate}'
                crossing_plan=scene['entities'][identity].get('crossing_plan')
                if movement and scene['entities'][identity].get('ferry_transport'):
                    from gentactix import ferries
                    need=n(ferries.ground_distance(before,u,target))+f'*{rate}'
                elif crossing_plan:
                    points=[u]+crossing_plan['waypoints']
                    route='+'.join(f'GtxDistance({n(a["lat"])},{n(a["lng"])},{n(b["lat"])},{n(b["lng"])})' for a,b in zip(points,points[1:]))
                    need=f'({route})*{rate}'
                speed=missions.move_budget(before,u,target)*1000/sim_clock.duration_seconds(before['mission']['definition']['time_step'])
                setup += [f' double needed{i}={need};',
                    f' if ({get(p,"blocked")}==0 && needed{i}>{get(p,"fuel_liters")}) {{ fuelLimited{i}=true;',
                    f'  if ({get(p,"fuel_liters")}<=0) {{ pause{i}={seconds+1}; }}',
                    f'  else {{ double fuelSpeed{i}=Math.Min({n(speed)},{get(p,"fuel_liters")}*1000/{rate}/Math.Max(1,{seconds}-pause{i}));',
                    f'   if (!{p}.GoToSpeed(fuelSpeed{i},1000.0,true)) {{ writeln("GTXERROR|fuel_speed_control"); }}', '  }',' }']
            pause=f'Math.Max(TIME_NOW+0.000001,Math.Min({seconds+1},pause{i}))' if crossing else f'Math.Min({seconds+1},pause{i})'
            setup += [f' if ({get(p,"blocked")}>0) {{ pause{i}={seconds+1}; }}',
                f' {p}.Pause({pause});',
                f' if (fuelLimited{i} && {get(p,"blocked")}==0) {{ '+put(p,'blocked','10')+' }']
        if movement:
            pause_value=get(p,'delay_s') if motion and action=='move' else f'pause{i}' if action=='move' else '0.0'
            setup.append(f' {p}.SetAuxData("mf_pause",'+pause_value+');')
        if crossing:setup+=afsim_crossing.setup_actor(p,u,scene['entities'][identity],f'pause{i}' if action=='move' else None)
        if multi:setup+=afsim_crossing_network.actor_setup(before,u,scene['entities'][identity],p)
        if operational:setup+=afsim_campaign.setup_actor(before,u,p,conceal=action=='conceal')
    if dynamic:setup+=_density_sample_lines(before,units,'p',operational)
    if scheduled:setup+=afsim_supply_schedule.setup(before,identities)
    if motion:setup+=motion['setup_lines']
    if nourishing:
        setup += [afsim_strength_clock.refresh(f'WsfSimulation.FindPlatform("{identity}")')
                  for identity in identities.values()]
    setup.append('end_execute')
    lines += [afsim_campaign.functions(before) if operational else '',_functions(scene,before,reference),afsim_crossing.functions(scene,before) if crossing else '',
              afsim_ferries.functions(scene,before) if afsim_ferries.enabled(before) else '', '\n'.join(setup),air['script']]
    # The native scheduler delivers commands after modelled communication delay.
    tick=['execute at_interval_of 10 sec']
    if nourishing or work_ids:
        # Close the OLD availability interval before this staggered native
        # event samples losses or applies a simultaneous command/fire batch.
        tick += [f' GtxCMSettle(WsfSimulation.FindPlatform("{identity}"));'
                 for identity in identities.values()]
    # Sample all strengths before executing this tick's simultaneous fire.
    for i,(team,u) in enumerate(units):
        identity=identities[u['name']];p=f'live{i}'
        captured='-'+afsim_campaign.get(p,'captured') if operational else ''
        tick += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");',
            *([afsim_campaign.active_tick(p)] if operational else []),
            put(p,'live_strength_ratio',f'Math.Max(0,{get(p,"initial_current")}-Math.Floor({_damage_total(p,precise)})-{p}.AuxDataDouble("gtx_air_damage"){captured})/{get(p,"committed")}')]
        if nourishing:
            tick += [put(p,'combat_strength_ratio',get(p,'live_strength_ratio')),
                put(p,'live_strength_ratio',f'Math.Max(0,{get(p,"live_strength_ratio")}-{p}.AuxDataDouble("cn_nc")/Math.Max(1,{get(p,"committed")}))')]
        if dynamic:
            tick.append(put(p,'density_own_current',f'Math.Max(0,{get(p,"initial_current")}-Math.Floor({_damage_total(p,precise)})-{p}.AuxDataDouble("gtx_air_damage"){captured})'))
            if nourishing:tick.append(put(p,'density_own_current',f'Math.Max(0,{get(p,"density_own_current")}-{p}.AuxDataDouble("cn_nc"))'))
        if carried:
            tick.append(f' GtxSuppressionDecay({p},TIME_NOW);')
        elif continuous:
            # An interval event may also run at TIME_NOW=0. Charge only time
            # actually elapsed since the preceding sample, never a fixed bonus.
            tick += [put(p,'suppression',f'Math.Max(0,{get(p,"suppression")}-{n(cfg["suppression_decay"]/1800)}*Math.Max(0,TIME_NOW-{get(p,"suppression_sample_at_s")}))'),
                     put(p,'suppression_sample_at_s','TIME_NOW')]
        tick += [put(p,'intel_age_min',f'(TIME_NOW-{get(p,"intel_observed_at_s")})/60'),
            put(p,'intel_confidence',f'Math.Min({get(p,"intel_confidence_base")},Math.Max(10,{get(p,"intel_confidence_base")}-10.0*(TIME_NOW-{get(p,"intel_confidence_at_s")})/1800))')]
    if dynamic:tick+=_density_sample_lines(before,units,'live',operational)
    for i,(team,u) in enumerate(units):
        p=f'p{i}';identity=identities[u['name']];order=cmd.get(u['name'],{'action':'hold'});action=order['action']
        active=''
        if operational:
            active=f' && {afsim_campaign.get(p,"captured")}==0'
            if action not in campaign.WAITING_ACTIONS:active+=f' && {afsim_campaign.get(p,"active")}>0'
        tick += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");',
                 f' if ({get(p,"live_strength_ratio")}>0 && {get(p,"command_done")}==0 && TIME_NOW>={get(p,"delay_s")} && TIME_NOW<={seconds}{active}) {{',put(p,'command_done','1')]
        if scene['entities'][identity].get('cancel_crossing'):
            tick.append(f' if ({get(p,"cross_stage")}==1) {{ '+put(p,'cross_stage','4')+' }')
        if action=='recon':tick += [put(p,'intel_observed_at_s','TIME_NOW'),put(p,'intel_age_min','0'),
            put(p,'intel_confidence_base','100'),put(p,'intel_confidence_at_s','TIME_NOW'),put(p,'intel_confidence','100')]
        elif action=='restore_comms':tick += [put(p,'signal',f'Math.Min(100,{get(p,"signal")}+25)')]
        elif action=='sabotage':tick += [put('WsfSimulation.FindPlatform("gtx_ca_hub")','network','Math.Max(0,WsfSimulation.FindPlatform("gtx_ca_hub").AuxDataDouble("ca_network")-40)')]
        elif action=='repair':tick += [put('WsfSimulation.FindPlatform("gtx_ca_hub")','network','Math.Min(100,WsfSimulation.FindPlatform("gtx_ca_hub").AuxDataDouble("ca_network")+25)')]
        elif action=='accept':tick += [put('WsfSimulation.FindPlatform("gtx_ca_hub")','accepted','1')]
        elif action=='capture':
            target_id=identities[order['target']];target=f'captureTarget{i}'
            tick += [f' WsfPlatform {target}=WsfSimulation.FindPlatform("{target_id}");',*afsim_campaign.capture_lines(before,p,target,
                **({'loss_load':_damage_total(target,True)}if precise else {}))]
        elif action=='fortify' and identity not in work_ids:
            improved='Math.Min(100,'+get(p,'entrenchment')+'+'+str(cfg['fortify_gain'])+')'
            if operational and afsim_campaign.components(before,u):
                tick += afsim_campaign.fortify_components(before,u,p,cfg['fortify_gain'])
            elif operational:
                base=afsim_campaign.get(p,'base_entrenchment')
                tick += [' if ('+get(p,'materials')+'>0) { ',
                    afsim_campaign.put(p,'base_entrenchment',f'Math.Min(100,{base}+{cfg["fortify_gain"]})'),
                    put(p,'entrenchment',base),
                    f' if ({afsim_campaign.get(p,"fortified")}>0) {{ '+put(p,'entrenchment',base+f'*(0.25+0.75*{afsim_campaign.get(p,"integrity")}/100)')+' }',
                    put(p,'materials',get(p,'materials')+'-1'),' }']
            else:tick.append(' if ('+get(p,'materials')+'>0) { '+put(p,'entrenchment',improved)+put(p,'materials',get(p,'materials')+'-1')+' }')
        tick += [f' writeln("GTXCEVENT|{identity}|{action}|",Format.Fixed(TIME_NOW*1000,9),"|",(int){get(p,"blocked")});',' }']
        if action in ('fire','bombard','suppress'):
            target_id=identities[order['target']];kind={'fire':0,'bombard':1,'suppress':2}[action]
            cycle=reference['direct_cycle_s'] if action=='fire' else reference['artillery_cycle_s']*max(1,cfg['reload_turns'])
            tick += [f' if ({get(p,"command_done")}==1 && {get(p,"live_strength_ratio")}>0 && TIME_NOW>={get(p,"next_fire_s")} && TIME_NOW<{seconds}) {{',
                f' GtxCAFire({p},WsfSimulation.FindPlatform("{target_id}"),{kind});',
                f' if ({get(p,"fire_stop_reason")}==0) {{ '+put(p,'active_fire_s',get(p,'active_fire_s')+f'+Math.Min({cycle},{seconds}-TIME_NOW)')+' }',
                put(p,'next_fire_s',f'TIME_NOW+{cycle}'),' }']
    if continuous:
        for i,(_,u) in enumerate(units):
            p=f'post{i}';identity=identities[u['name']]
            tick.append(f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");')
            if carried:tick.append(f' GtxSuppressionCommit({p});')
            else:tick += [put(p,'suppression',f'Math.Min(100,{get(p,"suppression")}+{get(p,"pending_suppression")})'),
                         put(p,'pending_suppression','0')]
    if nourishing:
        tick += [afsim_strength_clock.refresh(f'WsfSimulation.FindPlatform("{identity}")')
                 for identity in identities.values()]
    tick.append('end_execute');lines.append('\n'.join(tick))
    if scheduled:lines.append(afsim_supply_schedule.compile_events(before,orders,identities,seconds))
    end=[f'execute at_time {seconds:.6f} sec absolute',f' writeln("GTXMODEL|{digest}");',
         ' WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub");']
    if motion:
        end += [f' GtxCMSettle(WsfSimulation.FindPlatform("{identity}"));' for identity in identities.values()]
    if scheduled:
        for d,node in enumerate(before['supply_nodes']):
            for key in ('food','ammo'):
                end.append(f' double depot{d}_{key}={afsim_supply_schedule.get("hub",f"node_{d}_{key}")};')
            end.append(f' double depot{d}=depot{d}_food*{n(split["food_mass_share"])}+depot{d}_ammo*{n(1-split["food_mass_share"])};')
    else:
        for d,node in enumerate(before['supply_nodes']):end.append(f' double depot{d}={n(node["stock"])};')
        if split:end+=afsim_split_supply.initialize(before['supply_nodes'])
    end += [' double redAvailable=0; double blueAvailable=0; int redInGoal=0; int blueInGoal=0; int redAlive=0; int blueAlive=0; int redAtExit=0; int blueAtExit=0;']
    if crossing or grouped:end += [' int redCrossed=0; int blueCrossed=0;']
    # Freeze combat availability before settlement mutates casualty remainders.
    # This is a turn-end route-control snapshot, before deliveries and starvation,
    # not a continuous convoy-interception simulation. Roster order must not
    # resurrect a combat-disabled roadblock by clearing its fractional carry.
    for i,(_,u) in enumerate(units):
        p=f'supplyUnit{i}'
        captured='-'+afsim_campaign.get(p,'captured') if operational else ''
        released=f' && TIME_NOW>={afsim_campaign.get(p,"release_s")}' if operational else ''
        if nourishing:captured+=f'-{p}.AuxDataDouble("cn_nc")'
        end += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identities[u["name"]]}");',
                f' bool controlsSupply{i}=({get(p,"initial_current")}-Math.Floor({_damage_total(p,precise)})-{p}.AuxDataDouble("gtx_air_damage"){captured}>0){released};']
    actor_ranges=[]
    for i,(team,u) in enumerate(units):
        actor_start=len(end)
        p=f'p{i}';identity=identities[u['name']];f=u['formation'];order=cmd.get(u['name'],{'action':'hold'});action=order['action']
        distance=afsim_crossing.travelled_expression(scene['entities'][identity],p) if scene['entities'][identity].get('crossing_plan') else f'GtxDistance({n(u["lat"])},{n(u["lng"])},{p}.Latitude(),{p}.Longitude())'
        end.append(f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");')
        if movement and scene['entities'][identity].get('ferry_transport'):
            # WSF interval callbacks may be staggered. Sample the passenger
            # from its actual boat at this endpoint before costs/telemetry,
            # just as the geographic observer does at the same instant.
            end.append(f' GtxFerrySync({p});')
        end += [f' double distance{i}={distance};',
                put(p,'distance_milli',f'GtxRound(distance{i}*1000000)')]
        travelled=f'distance{i}'
        if movement:
            expression=f'GtxCMGet({p},"distance")/1000000000' if motion else afsim_movement.ground_expression(before,scene['entities'][identity],p,travelled)
            end.append(f' double mfGround{i}={expression};')
            travelled=f'mfGround{i}'
            nominal=missions.move_budget(before,u,order if action=='move' else None)
            end.append(f' if ({travelled}>{n(nominal)}+0.001) {{ writeln("GTXERROR|combined_move_budget"); }}')
            end.append(f' writeln("GTXMOVEMENT|{identity}|",Format.Fixed({travelled},12),"|",Format.Fixed(distance{i},12),"|",Format.Fixed({p}.AuxDataDouble("mf_pause"),12));')
        else:end.append(f' if (distance{i}>{n(before["mission"]["definition"]["rules"]["move_km"])}+0.001) {{ writeln("GTXERROR|combined_move_budget"); }}')
        if action=='move' and not motion:
            end.append(put(p,'fatigue',f'Math.Min(100,{get(p,"fatigue")}+GtxRound({travelled}*{cfg["fatigue_move_gain"]}))'))
        elif action in ('hold','resupply','conceal') and not motion:
            recovery=n(cfg['fatigue_rest_recovery']*seconds/1800) if nutrition else str(cfg['fatigue_rest_recovery'])
            end.append(put(p,'fatigue',f'Math.Max(0,{get(p,"fatigue")}-{recovery})'))
        if not motion and f.get('motorized',cfg['motorized']):
            fuel_cost=f'{travelled}*({get(p,"armor_operational")}*2+{get(p,"transport_operational")}*0.1)'
            end.append(f' if ({fuel_cost}>{get(p,"fuel_liters")}+0.001) {{ writeln("GTXERROR|fuel_budget"); }}')
            end.append(put(p,'fuel_liters',f'Math.Max(0,{get(p,"fuel_liters")}-Math.Ceil({fuel_cost}))'))
        construction_start=len(end)
        if action=='build_bridge':
            if crossing:
                end += [f' if ({get(p,"command_done")}==1 && {get(p,"engineer_operational")}>0) {{',
                    f' double gain{i}=Math.Floor(Math.Min(Math.Max(100-{get("hub","progress")},100-{get("hub","integrity")}),Math.Min({crossing["build_progress_per_engineer_hour"]}*{get(p,"engineer_operational")}*{get(p,"strength_ratio")}*Math.Max(0,{seconds}-{get(p,"delay_s")})/3600,Math.Min({get(p,"materials")},{get("hub","materials")})*{cfg["build_gain"]}/{cfg["build_materials"]})));',
                    f' double cost{i}=Math.Ceil(gain{i}*{cfg["build_materials"]}/{cfg["build_gain"]});',
                    put(p,'materials',get(p,'materials')+f'-cost{i}'),put('hub','materials',get('hub','materials')+f'-cost{i}'),
                    put('hub','progress',f'Math.Min(100,{get("hub","progress")}+gain{i})'),put('hub','integrity',f'Math.Min(100,{get("hub","integrity")}+gain{i})'),' }']
            else:
                end += [f' if ({get(p,"command_done")}==1 && {get(p,"engineer_operational")}>0 && {get(p,"materials")}>={cfg["build_materials"]} && {get("hub","materials")}>={cfg["build_materials"]}) {{',
                    put(p,'materials',get(p,'materials')+f'-{cfg["build_materials"]}'),put('hub','materials',get('hub','materials')+f'-{cfg["build_materials"]}'),
                    put('hub','progress',f'Math.Min(100,{get("hub","progress")}+GtxRound({cfg["build_gain"]}*Math.Min(1,{get(p,"engineer_operational")}/6)*{get(p,"strength_ratio")}))'),put('hub','integrity',f'Math.Min(100,{get("hub","integrity")}+25)'),' }']
        if action=='demolish':end += [f' if ({get(p,"command_done")}==1) {{',put('hub','integrity',f'Math.Max(0,{get("hub","integrity")}-50)'),put(p,'materials',get(p,'materials')+'-4'),' }']
        if multi and action in ('build_bridge','demolish'):
            site=crossing_network.engineering_site(before,u)
            site_index=next(k for k,s in enumerate(crossing_network.sites(before)) if s['id']==site['id'])
            local='engineerHub'+str(i)
            new_lines=[line.replace('hub.',local+'.') for line in end[construction_start:]]
            if action=='build_bridge':
                new_lines=[line.replace(str(crossing['build_progress_per_engineer_hour'])+'*',str(site['crossing_model']['build_progress_per_engineer_hour'])+'*') for line in new_lines]
            end[construction_start:]=[f' WsfPlatform {local}=GtxCrossHub({site_index});']+new_lines
        if action=='repair_equipment':
            end.append(f' if ({get(p,"command_done")}==1) {{')
            end.append(f' double repair{i}=Math.Min({cfg["repair_limit"]},Math.Min({get(p,"spares")},Math.Max(1,Math.Floor({get(p,"engineer_operational")}/3))));')
            for e in u['equipment']:
                cat=e['category'];end += [f' double r{i}_{cat}=Math.Min(repair{i},{get(p,cat+"_damaged")});',
                    put(p,cat+'_operational',get(p,cat+'_operational')+f'+r{i}_{cat}'),put(p,cat+'_damaged',get(p,cat+'_damaged')+f'-r{i}_{cat}'),
                    put(p,'spares',get(p,'spares')+f'-r{i}_{cat}'),put(p,'repaired',get(p,'repaired')+f'+r{i}_{cat}'),f' repair{i}=repair{i}-r{i}_{cat};']
            end.append(' }')
        weight=formation_parts.scale(u)
        if scheduled:
            end+=afsim_supply_schedule.finish(before,u,orders,i,identity,p,seconds=seconds)
        else:
            # Convoy throughput, route control, bridge state and stocks constrain supply.
            node=supply.bound_node(before,team,u)
            node_index=before['supply_nodes'].index(node)
            end += [f' int conn{i}=1; double routeKm{i}=GtxDistance({n(node["lat"])},{n(node["lng"])},{p}.Latitude(),{p}.Longitude());']
            if multi:
                end+=afsim_crossing_network.supply_setup(before,p,i,node)
            elif crossing:
                from gentactix import crossings
                bank='a' if crossings.orientation(node,crossing['barrier']['a'],crossing['barrier']['b'])*crossings.orientation(crossing['banks']['a'],crossing['barrier']['a'],crossing['barrier']['b'])>=0 else 'b'
                entry=crossing['banks'][bank];exit=crossing['banks']['b' if bank=='a' else 'a']
                end += [f' bool supplyCross{i}=GtxCrosses({n(node["lat"])},{n(node["lng"])},{p}.Latitude(),{p}.Longitude());',
                        f' if (supplyCross{i}) {{ routeKm{i}=GtxDistance({n(node["lat"])},{n(node["lng"])},{n(entry["lat"])},{n(entry["lng"])})+GtxDistance({n(entry["lat"])},{n(entry["lng"])},{n(exit["lat"])},{n(exit["lng"])})+GtxDistance({n(exit["lat"])},{n(exit["lng"])},{p}.Latitude(),{p}.Longitude()); }}']
            for j,(enemy,other) in enumerate(units):
                if enemy==team or other['personnel']['current']<=0:continue
                enemy_id=identities[other['name']]
                end.append(f' WsfPlatform q{i}_{j}=WsfSimulation.FindPlatform("{enemy_id}");')
                blocked=f'GtxBlocked({n(node["lat"])},{n(node["lng"])},{p}.Latitude(),{p}.Longitude(),q{i}_{j}.Latitude(),q{i}_{j}.Longitude(),{n(other["ground_control_radius_km"])})'
                if multi:
                    blocked=afsim_crossing_network.blocked(i,j,node,other['ground_control_radius_km'])
                elif crossing:
                    corridor=' || '.join(f'GtxBlocked({n(a["lat"])},{n(a["lng"])},{n(b["lat"])},{n(b["lng"])},q{i}_{j}.Latitude(),q{i}_{j}.Longitude(),{n(other["ground_control_radius_km"])})' for a,b in ((node,entry),(entry,exit)))
                    corridor+=f' || GtxBlocked({n(exit["lat"])},{n(exit["lng"])},{p}.Latitude(),{p}.Longitude(),q{i}_{j}.Latitude(),q{i}_{j}.Longitude(),{n(other["ground_control_radius_km"])})'
                    blocked=f'((supplyCross{i} && ({corridor})) || (!supplyCross{i} && {blocked}))'
                end.append(f' if (controlsSupply{j} && ({blocked})) {{ conn{i}=0; }}')
            if crossing and not multi:
                end += [f' if (supplyCross{i} && ({bridge["progress"]}<100 || {bridge["integrity"]}<50)) {{ conn{i}=0; }}']
            elif not crossing and cfg.get('bridge_enabled',True):
                end += [f' bool supplyCross{i}=({n(node["lng"])}-{n(bridge["lng"])})*({p}.Longitude()-{n(bridge["lng"])})<0;',
                        f' if (supplyCross{i} && ({bridge["progress"]}<100 || {bridge["integrity"]}<50 || {get("hub","used")}>={get("hub","capacity")})) {{ conn{i}=0; }}']
            end += [f' double capacity{i}={get(p,"transport_operational")}*{cfg["transport_tons_per_truck"]}*{get(p,"strength_ratio")}*Math.Min(1,{cfg["convoy_km_per_turn"]}/Math.Max(0.1,routeKm{i}));']
            if multi:
                end += [f' if (supplyCross{i}) {{ capacity{i}=Math.Min(capacity{i},Math.Max(0,supplyBudget{i}*{seconds}/3600-{get("supplyHub"+str(i),"cross_work")}-{get("supplyHub"+str(i),"cross_cargo_work")})*{n(cfg["ton_per_supply_unit"])}/supplyWeight{i}); }}']
            elif crossing:
                end += [f' if (supplyCross{i}) {{ capacity{i}=Math.Min(capacity{i},Math.Max(0,{n(crossing["throughput_work_per_hour"]*seconds/3600)}-{get("hub","cross_work")}-{get("hub","cross_cargo_work")})*{n(cfg["ton_per_supply_unit"]/crossing["supply_work_per_unit"])}); }}']
                if crossing.get('ferry'):end.append(f' if (supplyCross{i}) {{ capacity{i}=0; }}')
            weight=formation_parts.scale(u)
            # Passive delivery remains available. Extra cargo requires an actually
            # delivered support command, including in the waiting area.
            end.append(f' double supplyRate{i}={n(2*weight)};')
            if action=='resupply':
                end.append(f' if ({get(p,"command_done")}==1) {{ supplyRate{i}={n(8*weight)}; }}')
            packages=f'capacity{i}/{cfg["ton_per_supply_unit"]}'
            if not formation_parts.is_fragment(u):packages=f'Math.Floor({packages})'
            end += [
                    put(p,'transport_capacity_milli',f'GtxRound(capacity{i}*1000)'),
                    f' double delivery{i}=0;']
            if split:
                end.append(f' double supplyTon{i}={n(cfg["ton_per_supply_unit"])};')
                end+=afsim_split_supply.plan(split,u,i,node_index,nutrition=nutrition)
            else:
                end.append(f' if (conn{i}==1) {{ delivery{i}=Math.Min(supplyRate{i},Math.Min(depot{node_index},{packages})); }}')
                end.append(f' delivery{i}=Math.Min(delivery{i},Math.Min(100-{u["logistics"]["food"]},100-{u["logistics"]["ammo"]})*{n(weight)});')
            if f.get('motorized',cfg['motorized']):
                end += [f' double convoyFuel{i}=Math.Ceil(routeKm{i}*2);']
                if action=='resupply':
                    end += [f' if ({get(p,"command_done")}==1 && delivery{i}>0 && {get(p,"fuel_liters")}<convoyFuel{i} && {get("hub",team+"_fuel_liters")}>=convoyFuel{i}) {{',
                            put('hub',team+'_fuel_liters',get('hub',team+'_fuel_liters')+f'-convoyFuel{i}'),
                            *([put('hub','fuel_depot_support_'+team,get('hub','fuel_depot_support_'+team)+f'+convoyFuel{i}*1000000')] if motion else []),
                            f' convoyFuel{i}=0;',' }']
                debit=f'GtxCMConsumeSupportFuel({p},convoyFuel{i});' if motion else put(p,'fuel_liters',get(p,'fuel_liters')+f'-convoyFuel{i}')
                end += [f' if ({get(p,"fuel_liters")}<convoyFuel{i}) {{ delivery{i}=0; }}',
                        f' if (delivery{i}>0) {{ {debit} }}']
            if not split:end.append(f' delivery{i}=Math.Min(delivery{i},Math.Min(100-{u["logistics"]["food"]},100-{u["logistics"]["ammo"]})*{n(weight)});')
            if cfg.get('bridge_enabled',True) and not crossing:
                end.append(f' if (supplyCross{i} && delivery{i}>0) {{ {put("hub","used",get("hub","used")+"+1")} }}')
            if split:end+=afsim_split_supply.commit(split,i,node_index,identity)
            else:end.append(f' depot{node_index}=depot{node_index}-delivery{i};')
            end.append(put(p,'delivery_tons_milli',f'GtxRound(delivery{i}*{cfg["ton_per_supply_unit"]}*1000)'))
            end.append(f' double cargoFree{i}=Math.Max(0,capacity{i}-delivery{i}*{cfg["ton_per_supply_unit"]});')
            transfers={'fuel_liters':100 if f.get('motorized',cfg['motorized']) else 0,'spares':1,'materials':1} if action=='resupply' else {}
            transfers.update(shells=cfg['shells_per_supply_unit'] if any(e['category']=='artillery' and e['committed'] for e in u['equipment']) else 0,
                             aa_rounds=cfg['aa_rounds_per_supply_unit'] if any(e['category']=='air_defense' and e['committed'] for e in u['equipment']) else 0)
            for key,amount in transfers.items():
                mass=cfg['cargo_mass_tons'][key]
                # Split food/ammo delivery is fractional even for whole formations.
                # Transfer discrete inventories atomically in whole units; truncating
                # each endpoint only at telemetry emission loses shells/spares.
                quantity=f'Math.Floor(delivery{i}*{amount})'
                if key in ('fuel_liters','spares','materials'):
                    quantity=f'({quantity})*{get(p,"command_done")}'
                credit=f'GtxCMReceiveFuel({p},transfer{i}_{key});' if motion and key=='fuel_liters' else put(p,key,get(p,key)+f'+transfer{i}_{key}')
                end += [f' double transfer{i}_{key}=Math.Min({get("hub",team+"_"+key)},Math.Min({quantity},Math.Floor(cargoFree{i}/{n(mass)})));',
                        f' cargoFree{i}=Math.Max(0,cargoFree{i}-transfer{i}_{key}*{n(mass)});',
                        put('hub',team+'_'+key,get('hub',team+'_'+key)+f'-transfer{i}_{key}'),credit]
            end.append(f' writeln("GTXCSUPPLY|{identity}|",'+',"|",'.join(f'(int)transfer{i}_{key}' if key in transfers else '0' for key in SUPPLY_FIELDS)+');')
            end.append(put(p,'delivery_tons_milli',f'GtxRound((capacity{i}-cargoFree{i})*1000)'))
            if multi:
                end.append(f' if (supplyCross{i}) {{ '+put('supplyHub'+str(i),'cross_cargo_work',get('supplyHub'+str(i),'cross_cargo_work')+f'+(capacity{i}-cargoFree{i})*supplyWeight{i}/{n(cfg["ton_per_supply_unit"])}')+' }')
            elif crossing:
                end.append(f' if (supplyCross{i}) {{ '+put('hub','cross_cargo_work',get('hub','cross_cargo_work')+f'+(capacity{i}-cargoFree{i})*{n(crossing["supply_work_per_unit"]/cfg["ton_per_supply_unit"])}')+' }')
            if nutrition:
                end += afsim_sustainment.finish(nutrition,u,action,seconds,i,identity,p,food_delivery=f'foodDelivery{i}' if split else f'delivery{i}',continuous=nourishing)
                if formation_parts.is_fragment(u):end.append(f' double ncCarry{i}={n(f.get("partition_noncombat_remainder",0))};')
            else:
                end += [
                    f' double food{i}=Math.Max(0,{u["logistics"]["food"]}+({"foodDelivery" if split else "delivery"}{i}-{n(resource_accounts.food_demand(action)*weight)})/{n(weight)});',
                    (f' double ncCarry{i}={n(f.get("partition_noncombat_remainder",0))}; double noncombat{i}=0; if (food{i}==0) {{ ncCarry{i}=ncCarry{i}+{n(support_dynamics.legacy_allowance(u))}; noncombat{i}=Math.Min(Math.Floor(ncCarry{i}+{n(support_dynamics.LEGACY_ROUND_EPSILON)}),{u["personnel"]["current"]}); ncCarry{i}=Math.Max(0,ncCarry{i}-Math.Floor(ncCarry{i}+{n(support_dynamics.LEGACY_ROUND_EPSILON)})); }}'
                     if formation_parts.is_fragment(u) else f' double noncombat{i}=0; if (food{i}==0) {{ noncombat{i}=Math.Min({n(support_dynamics.legacy_allowance(u))},{u["personnel"]["current"]}); }}')]
        ammo_value=f'Math.Max(0,{u["logistics"]["ammo"]}+({"ammoDelivery" if split else "delivery"}{i}-{get(p,"ammo_spent")})/{n(weight)})'
        if scheduled:ammo_value='Math.Min(100,'+ammo_value+')'
        end += [f' double ammo{i}={ammo_value};',f' double totalDamage{i}={_damage_total(p,precise)};',
                f' double ground{i}=Math.Min(Math.Floor(totalDamage{i}),{u["personnel"]["current"]}-noncombat{i});',
                f' double air{i}=Math.Min({p}.AuxDataDouble("gtx_air_damage"),{u["personnel"]["current"]}-noncombat{i}-ground{i});',
                f' double current{i}={u["personnel"]["current"]}-noncombat{i}-ground{i}-air{i};',
                put(p,'ground_damage',f'ground{i}'),
                put(p,'signal',f'Math.Max(0,{get(p,"signal")}-Math.Floor(ground{i}/50))')]
        if operational:
            end += [f' double captured{i}=Math.Min(current{i},{afsim_campaign.get(p,"captured")});',f' current{i}=current{i}-captured{i};']
        if not continuous:
            end.append(put(p,'suppression',f'Math.Min(100,Math.Max(0,{get(p,"suppression")}-{cfg["suppression_decay"]})+{get(p,"pending_suppression")})'))
        if carried:
            end.append(f' GtxSuppressionDecay({p},{n(seconds)});')
            end.append(afsim_suppression.receipt(p,identity))
        # Endpoints may fall between native ticks. Preserve exact elapsed age
        # rather than truncating a repeated floating-point accumulation.
        end.append(put(p,'intel_age_min',f'({seconds}-{get(p,"intel_observed_at_s")})/60'))
        end.append(put(p,'intel_confidence',f'Math.Min({get(p,"intel_confidence_base")},Math.Max(10,{get(p,"intel_confidence_base")}-10.0*({seconds}-{get(p,"intel_confidence_at_s")})/1800))'))
        end += [f' double reloadOut{i}=Math.Max(0,{get(p,"reload_initial_s")}-{seconds});',
                f' if ({get(p,"fire_cycles")}>0) {{ reloadOut{i}=Math.Max(0,{get(p,"next_fire_s")}-{seconds}); }}',
                put(p,'reload_remaining',f'(int)(reloadOut{i}>0)'),
                put(p,'damage_remainder',f'totalDamage{i}-Math.Floor(totalDamage{i})'),
                f' if (current{i}==0) {{ '+put(p,'damage_remainder','0')+' }']
        if precise:
            end += [put(p,'damage_remainder_micro',f'{get(p,"pending_damage_micro")}+{get(p,"damage_remainder_micro")}-Math.Floor(totalDamage{i})*1000000'),
                f' if (current{i}==0) {{ '+put(p,'damage_remainder_micro','0')+' }',
                put(p,'damage_remainder',get(p,'damage_remainder_micro')+'/1000000')]
        known={k:int(u['personnel'].get(k) or 0) for k in CASUALTY_FIELDS if k!='unclassified_casualties'}
        unknown=u['personnel']['casualties']-sum(known.values())
        end += [f' double fatalLoad{i}=(ground{i}+air{i})*{n(reference["fatality_share"])}+{get(p,"fatality_remainder")};',
                f' double newKilled{i}=Math.Min(ground{i}+air{i},Math.Floor(fatalLoad{i}));',
                put(p,'fatality_remainder',f'fatalLoad{i}-newKilled{i}')]
        captured=f'+captured{i}' if operational else ''
        counts=[f'{known["killed"]}+newKilled{i}',f'{known["wounded"]}+ground{i}+air{i}-newKilled{i}',str(known['missing']),str(known['captured'])+captured,str(unknown)]
        end.append(f' writeln("GTXCASUALTY|{identity}|",'+',"|",'.join(f'(int)({v})' for v in counts)+');')
        fire=[get(p,'fire_cycles'),get(p,'active_fire_s'),f'reloadOut{i}',
              get(p,'damage_remainder')+'*1000000',get(p,'fatality_remainder')+'*1000000',get(p,'fire_stop_reason')]
        if precise:fire[3]=get(p,'damage_remainder_micro')
        end.append(f' writeln("GTXFIRE|{identity}|",'+',"|",'.join(f'(int)({v})' for v in fire)+');')
        if reference.get('direct_fire'):
            count=get(p,'small_arms_attempts')
            end.append(f' writeln("GTXSMALL|{identity}|",(int)Math.Floor({count}/1000000),"|",(int)({count}-Math.Floor({count}/1000000)*1000000));')
        # Damage is applied separately to each equipment class. Fractional exposure
        # persists instead of being truncated to zero on every small engagement.
        end.append(f' double airGear{i}={p}.AuxDataDouble("gtx_air_equipment"); double airDestroyed{i}=0;')
        for k,e in enumerate(u['equipment']):
            cat=e['category'];hardness={'armor':.02,'artillery':.04,'air_defense':.03,'engineer':.02,'transport':.06}[cat]
            extra=(f'{get(p,cat+"_operational")}*ground{i}/{u["personnel"]["current"]}*{n(reference["equipment_casualty_multipliers"][cat])}'
                   if reference.get('equipment_casualty_multipliers') and u['personnel']['current']>0
                   else f'{get(p,"pending_stress")}*{hardness}/(1+{get(p,"entrenchment")}/50)')
            end += [f' double exposure{i}_{k}={get(p,cat+"_damage_load")}+{extra};',
                f' double hit{i}_{k}=Math.Min({get(p,cat+"_operational")},Math.Floor(exposure{i}_{k}));',
                f' double destroyed{i}_{k}=Math.Floor(hit{i}_{k}/2);',
                put(p,cat+'_operational',get(p,cat+'_operational')+f'-hit{i}_{k}'),
                put(p,cat+'_damaged',get(p,cat+'_damaged')+f'+hit{i}_{k}-destroyed{i}_{k}'),
                put(p,cat+'_destroyed',get(p,cat+'_destroyed')+f'+destroyed{i}_{k}'),
                put(p,cat+'_damage_load',f'exposure{i}_{k}-Math.Floor(exposure{i}_{k})'),
                put(p,'ground_equipment',get(p,'ground_equipment')+f'+hit{i}_{k}'),
                f' double ag{i}_{k}=Math.Min(airGear{i},{get(p,cat+"_operational")});',
                put(p,cat+'_operational',get(p,cat+'_operational')+f'-ag{i}_{k}'),put(p,cat+'_destroyed',get(p,cat+'_destroyed')+f'+ag{i}_{k}'),
                f' airGear{i}=airGear{i}-ag{i}_{k}; airDestroyed{i}=airDestroyed{i}+ag{i}_{k};',
                f' writeln("GTXCEQUIP|{identity}|{cat}|",(int){get(p,cat+"_operational")},"|",(int){get(p,cat+"_damaged")},"|",(int){get(p,cat+"_destroyed")},"|",(int)({get(p,cat+"_damage_load")}*1000000));']
        e0=u['equipment'][0]['category']
        vals=[f'(int)current{i}',f'(int)({u["personnel"]["casualties"]}+ground{i}+air{i}{captured})',f'(int)({u["personnel"]["noncombat_losses"]}+noncombat{i})',
              f'(int){get(p,e0+"_operational")}',f'(int){get(p,e0+"_destroyed")}',f'food{i}',f'ammo{i}',f'GtxRound(10000*current{i}/{u["personnel"]["committed"]})',
              f'Math.Min(food{i},ammo{i})',f'delivery{i}',f'Math.Min({n(resource_accounts.food_demand(action)*weight)},{n(u["logistics"]["food"]*weight)}+delivery{i})',get(p,'ammo_spent'),f'conn{i}']
        if nutrition:vals[10]=f'foodUsed{i}'
        elif split:vals[10]=f'Math.Min({n(resource_accounts.food_demand(action)*weight)},{n(u["logistics"]["food"]*weight)}+foodDelivery{i})'
        if grouped or nutrition or split:
            for slot in (5,6,8,9,10,11):vals[slot]=f'Format.Fixed({vals[slot]},12)'
        end.append(f' writeln("GTXEFFECT|{identity}|",'+',"|",'.join(vals)+');')
        if formation_parts.is_fragment(u):end.append(f' writeln("GTXPARTSTATE|{identity}|",Format.Fixed(ncCarry{i},12));')
        end.append(f' writeln("GTXATTRIBUTION|{identity}|",(int)(ground{i}{captured}),"|",(int)air{i},"|",(int)airDestroyed{i});')
        end.append(f' writeln("GTXCUNIT|{identity}|",'+',"|",'.join(
            f'Format.Fixed({get(p,k)},12)' if k in ('intel_age_min','intel_confidence') else
            f'(int)Math.Floor({get(p,"suppression_ticks")}/{suppression_state.SCALE}.0)' if k=='suppression' and carried else
            f'(int)Math.Floor({get(p,k)}+0.000001)' if k=='suppression' and continuous else f'(int){get(p,k)}' for k in FIELDS)+');')
        if dynamic:
            fields=('density_sample_s','density_lat_cell','density_lng_cell','density_own_current','density_eligible','density_committed','density_current')
            end.append(f' writeln("GTXDENSITY|{identity}|",'+',"|",'.join(
                f'Format.Fixed({get(p,k)},12)' if j==0 else f'(int){get(p,k)}'for j,k in enumerate(fields))+');')
        if operational:end+=afsim_campaign.finish_actor(identity,p,i,afsim_campaign.components(before,u))
        if crossing:end+=afsim_crossing.finish_actor(p,identity)
        spec=before['mission']['definition'];goal=spec['objective']
        goal_side = f' && {p}.Longitude()>{n(bridge["lng"])}' if cfg.get('bridge_enabled',True) and not crossing else ''
        if grouped:
            goal_test=f'{get(p,"suppression")}<{cfg["suppression_control_threshold"]} && GtxDistance({p}.Latitude(),{p}.Longitude(),{n(goal["lat"])},{n(goal["lng"])})<={spec["goal_radius_km"]}{goal_side}'
            exit_test=f'GtxDistance({p}.Latitude(),{p}.Longitude(),{n(spec["exit"]["lat"])},{n(spec["exit"]["lng"])})<=0.6'
            passed=f'{get(p,"cross_stage")}==3'
            positioned=formation_parts.prepositioned_route(before,u)
            if positioned:
                e,x=positioned['entry'],positioned['exit']
                passed+=f' || (GtxCrosses({p}.Latitude(),{p}.Longitude(),{n(e["lat"])},{n(e["lng"])}) && !GtxCrosses({p}.Latitude(),{p}.Longitude(),{n(x["lat"])},{n(x["lng"])}))'
            crossed_test=f'({passed}) && ({goal_test})' if crossing else 'false'
            end+=afsim_formation_parts.goal_flags(p,f'current{i}',goal_test,exit_test,crossed_test)
        end += [f' {team}Available={team}Available+current{i};',f' if (current{i}>0) {{',
            f' if ({get(p,"suppression")}<{cfg["suppression_control_threshold"]} && GtxDistance({p}.Latitude(),{p}.Longitude(),{n(goal["lat"])},{n(goal["lng"])})<={spec["goal_radius_km"]}{goal_side}) {{ {team}InGoal={team}InGoal+1; }}']
        end.append(f' if (GtxDistance({p}.Latitude(),{p}.Longitude(),{n(spec["exit"]["lat"])},{n(spec["exit"]["lng"])})<=0.6) {{ {team}AtExit={team}AtExit+1; }}')
        end.append(f' {team}Alive={team}Alive+1;')
        if crossing:
            end.append(f' if ({get(p,"cross_stage")}==3 && {get(p,"suppression")}<{cfg["suppression_control_threshold"]} && GtxDistance({p}.Latitude(),{p}.Longitude(),{n(goal["lat"])},{n(goal["lng"])})<={spec["goal_radius_km"]}) {{ {team}Crossed={team}Crossed+1; }}')
        end.append(' }')
        actor_ranges.append((actor_start,len(end)))
    m=before['mission'];spec=m['definition']
    end+=afsim_formation_parts.goal_counts(before,identities)
    profile=cfg['goal_profile']
    if profile=='underground':
        hidden=sum(any(cmd.get(u['name'],{}).get('action')=='conceal' for u in members) for members in formation_parts.buckets(before,'red'))
        end.append(put('hub','organization',f'Math.Max(0,Math.Min(100,{get("hub","organization")}-15+5*{hidden}))'))
    required = cfg.get('required_survivors', 2)
    owner=missions.objective_team(spec);opponent='blue' if owner=='red' else 'red'
    condition={'rail':get('hub','network')+'<=20','underground':get('hub','organization')+'>=50 && redAlive>0',
        'reception':get('hub','accepted')+'==1','delay':f'{owner}Alive>={required} && {opponent}AtExit==0','breakout':f'{owner}AtExit>={required}'}.get(profile,f'{owner}InGoal>0 && {opponent}InGoal==0')
    if profile=='crossing':
        if not crossing:raise ValueError('渡运目标缺少版本化渡河模型')
        condition=f'{owner}Crossed>={required} && {opponent}InGoal==0'
    if operational:
        goal_lines,condition=afsim_campaign.goal_lines(before,units,identities)
        end+=goal_lines
    from gentactix import mission_termination
    success,terminal=mission_termination.native_expressions(spec,owner,wait_until_deadline=bool(operational) or profile in ('delay','underground'))
    end += [f' int turn={m["turn"]+1}; int progress=0; bool condition={condition};',
            f' if (condition) {{ progress={m["progress"]+1}; }}',f' bool success={success};',
            f' bool terminal={terminal};',
            ' writeln("GTXMISSION|",turn,"|",progress,"|",(int)hub.AuxDataDouble("ca_network"),"|",(int)hub.AuxDataDouble("ca_organization"),"|",(int)hub.AuxDataDouble("ca_accepted"),"|",(int)redAvailable,"|",(int)blueAvailable,"|",redInGoal,"|",blueInGoal,"|",(int)condition,"|",(int)terminal,"|",(int)success);']
    for i in range(len(before['supply_nodes'])):
        value=f'Format.Fixed(depot{i},12)' if grouped or split else f'(int)depot{i}'
        end.append(f' writeln("GTXDEPOT|{i}|",{value});')
    if split:end+=afsim_split_supply.finish(before['supply_nodes'])
    for team,pool in before['combined_arms']['depots'].items():
        end.append(f' writeln("GTXCDEPOT|{team}|",'+',"|",'.join(f'(int){get("hub",team+"_"+k)}' for k in ('fuel_liters','spares','materials','shells','aa_rounds'))+');')
        if motion:end.append(f' writeln("GTXCDEPOTFUEL|{team}|",Format.Fixed({get("hub","fuel_depot_support_"+team)},0));')
    end.append(' writeln("GTXCFAC|",'+',"|",'.join(f'(int){get("hub",k)}' for k in ('progress','integrity','materials','used'))+',"|",(int)('+get('hub','aa_carry_red')+'*1000000),"|",(int)('+get('hub','aa_carry_blue')+'*1000000));')
    if crossing:end+=afsim_crossing.finish_capacity(scene,before)
    if multi:end+=afsim_crossing_network.finish(scene,before)
    if afsim_ferries.enabled(before):end+=afsim_ferries.finish(scene,before)
    end.append('end_execute')
    from . import afsim_script_layout
    layout=afsim_script_layout.lower_settlement(end[1:actor_ranges[0][0]],
        [end[a:b] for a,b in actor_ranges],end[actor_ranges[-1][1]:-1])
    settlement_layout=None
    if layout:
        declarations,body,settlement_layout=layout
        previous_digest=digest
        digest=missions.digest({'input_digest':digest,'settlement_layout':settlement_layout['version']})
        marker='GTXMODEL|'+previous_digest
        if sum(line.count(marker) for line in body)!=1:
            raise ValueError('大型结算缺少唯一输入指纹')
        body=[line.replace(marker,'GTXMODEL|'+digest) for line in body]
        lines.extend(declarations)
        end=[end[0],*body,end[-1]]
    if motion:end[-1:-1]=motion['receipt_lines']
    lines.append('\n'.join(end))
    return {'version':version,'combat_revision':reference['combat_revision'],'combat_profile':reference,'supply_receipt_revision':1,
        **({'strength_clock_revision':afsim_strength_clock.REVISION} if nourishing else {}),
        **({'settlement_layout':settlement_layout} if settlement_layout else {}),
        **({'density_roots':_density_roots(before),'density_arrivals':{
            u['name']:{'active':before['campaign']['actors'][u['name']]['active'],'release_s':campaign.release_seconds(before,u)}
            for _,u in units} if operational else {}} if dynamic else {}),
        'supply_control_revision':SUPPLY_CONTROL_REVISION,'command_control_revision':COMMAND_CONTROL_REVISION,
        'intelligence_revision':INTELLIGENCE_REVISION,
        'formation_fire_control_revision':FORMATION_FIRE_CONTROL_REVISION,'salvo_limits':salvo,
        **({'legacy_support_revision':LEGACY_SUPPORT_REVISION} if nutrition is None else {}),
        'input_digest':digest,'expected_turn':m['turn']+1,'script':'\n'.join(lines)+'\n',
        **({'continuous_motion':{k:v for k,v in motion.items() if k not in ('script','functions','setup_lines','receipt_lines')}} if motion else {}),
        **({'support_dynamics':copy.deepcopy(nutrition)} if nutrition else {}),
        **({'movement_feedback':copy.deepcopy(movement),'movement_start':{'current_time':before.get('current_time'),
            'simulation_clock':copy.deepcopy(before.get('simulation_clock'))}} if movement else {}),
        **({'supply_distribution':copy.deepcopy(split)} if split else {}),
        'supply_binding_revision':1,'supply_nodes':copy.deepcopy(before['supply_nodes']),
        **({'supply_schedule':copy.deepcopy(scheduled),'supply_schedule_inputs':supply_schedule.reference_inputs(before)} if scheduled else {}),
        'units':units,'orders':orders,'depots':len(before['supply_nodes']),'air':air,'combined':True,'before_combined':before['combined_arms'],
        **({'campaign_revision':afsim_campaign.REVISION,'before_campaign':copy.deepcopy(before['campaign'])} if operational else {}),
        **({'campaign_fortification_revision':afsim_campaign.FORTIFICATION_REVISION} if operational and afsim_campaign.has_components(before) else {}),
        **({'crossing_inputs':{'nodes':copy.deepcopy(before['supply_nodes']),'rules':copy.deepcopy(cfg)}} if crossing else {})}


def _functions(scene,before,reference):
    from . import afsim_terrain
    terrain_code = afsim_terrain.functions(before)
    terrain_guard = 'if (kind==0 && GtxTerrainBlocked(actor,target)) { GtxCAStopFire(actor,11); return; }' if terrain_code else ''
    cfg=before['mission']['definition']['combined_rules'];ids={v['name']:k for k,v in scene['entities'].items()}
    operational=before['mission']['definition'].get('campaign_definition') is not None
    guard=(' if (actor.AuxDataDouble("ca_campaign_active")==0 || target.AuxDataDouble("ca_campaign_active")==0 || '
           'actor.AuxDataDouble("ca_campaign_captured")>0 || target.AuxDataDouble("ca_campaign_captured")>0) '
           '{ GtxCAStopFire(actor,9); return; }') if operational else ''
    impact=' GtxCampaignImpact(target,shells);' if operational else ''
    direct=reference.get('direct_fire')
    setup='double attempts=0;'
    if direct:
        attempts=fire_process.expression('direct_attempts',{'committed':'actor.AuxDataDouble("ca_committed")',
            **{k:n(direct[k]) for k in ('engaged_fraction','rounds_per_min')},'direct_cycle_s':str(reference['direct_cycle_s'])},wsf=True)
        range_effect=fire_process.expression('range_effect',{
            **{k:n(direct[k]) for k in ('range_min_factor','range_max_factor','reference_range_m')},
            'distance_m':'actor.GroundRangeTo(target)'},wsf=True)
        direct_power=fire_process.expression('direct_base_power',{'attempts':'attempts','hit_probability':n(direct['hit_probability']),'range_effect':'rangeEffect'},wsf=True)
        setup+=f''' if (kind==0) {{
 attempts={attempts};
 double rangeEffect={range_effect};
 power={direct_power};
 }}'''
    cover='GtxCADirectCover(target)' if direct else 'GtxCAAirCover(target)'
    direct_cover=fire_process.expression('direct_cover',{'protection':'target.AuxDataDouble("ca_protection")',
        'entrenchment':'target.AuxDataDouble("ca_entrenchment")','dispersion_km2':'target.AuxDataDouble("ca_dispersion")'},wsf=True)
    area_cover=fire_process.expression('area_cover',{'protection':'target.AuxDataDouble("ca_protection")',
        'entrenchment':'target.AuxDataDouble("ca_entrenchment")','dispersion_km2':'target.AuxDataDouble("ca_dispersion")',
        'size_factor':'target.AuxDataDouble("ca_area_size_factor")','strength_ratio':'target.AuxDataDouble("ca_area_strength_ratio")'},wsf=True)
    efficiency=fire_process.expression('efficiency',{**{k:f'actor.AuxDataDouble("ca_{k}")' for k in (
        'live_strength_ratio','fatigue','suppression','intel_confidence','intel_age_min')},'intel_age_decay':n(cfg['intel_age_decay'])},wsf=True)
    suppression=fire_process.expression('suppression_gain',{'power':'power','kind':'kind','efficiency':'efficiency'},wsf=True)
    suppression_accumulation=f'target.SetAuxData("ca_pending_suppression",target.AuxDataDouble("ca_pending_suppression")+{suppression});'
    if 'suppression_state' in reference:
        from . import afsim_suppression
        suppression_accumulation=afsim_suppression.gain(suppression)
    legacy_power=fire_process.expression('legacy_base_power',{'size_factor':'actor.AuxDataDouble("ca_size_factor")'},wsf=True)
    armor_power=fire_process.expression('armor_power',{'operational_armor':'actor.AuxDataDouble("ca_armor_operational")'},wsf=True)
    indirect_power=fire_process.expression('indirect_power',{'shells':'shells'},wsf=True)
    suppress_effect=fire_process.expression('suppress_effect',{'damage':'damage'},wsf=True)
    damage_accumulation='target.SetAuxData("ca_pending_damage",target.AuxDataDouble("ca_pending_damage")+damage);'
    if 'damage_quantum'in reference:
        damage_accumulation=('double damageMicro=Math.Floor(damage*1000000+0.5);\n '
            'target.SetAuxData("ca_pending_damage_micro",target.AuxDataDouble("ca_pending_damage_micro")+damageMicro);\n '
            'target.SetAuxData("ca_pending_damage",target.AuxDataDouble("ca_pending_damage_micro")/1000000);')
    text=[terrain_code, f'''script double GtxCAAirCover(WsfPlatform target)
 return {area_cover};
end_script
script double GtxCADirectCover(WsfPlatform target)
 return {direct_cover};
end_script
script void GtxCAStopFire(WsfPlatform actor,int reason)
 actor.SetAuxData("ca_fire_stop_reason",(double)reason);
 if (actor.AuxDataDouble("ca_fire_cycles")==0) {{ actor.SetAuxData("ca_blocked",(double)reason); }}
end_script
script void GtxCAFire(WsfPlatform actor,WsfPlatform target,int kind)
 double range=actor.AuxDataDouble("ca_direct_range_m"); double power={legacy_power}; double shells=0;
 {setup}
 {guard}
 {terrain_guard}
 if (target.AuxDataDouble("ca_live_strength_ratio")<=0) {{ GtxCAStopFire(actor,9); return; }}
 if (actor.AuxDataDouble("ca_ammo_available")-actor.AuxDataDouble("ca_ammo_spent")<actor.AuxDataDouble("ca_ammo_cycle")) {{ GtxCAStopFire(actor,8); return; }}
 if (actor.AuxDataDouble("ca_armor_operational")>0) {{ power=power+{armor_power}; }}
 if (kind>0) {{
  range={cfg['artillery_range_m']};
  if (actor.AuxDataDouble("ca_salvo_limit")<1 && actor.AuxDataDouble("ca_artillery_operational")*{cfg['shells_per_gun']}>=1 && actor.AuxDataDouble("ca_shells")>=1) {{ GtxCAStopFire(actor,12); return; }}
  shells=Math.Min(actor.AuxDataDouble("ca_salvo_limit"),Math.Min(actor.AuxDataDouble("ca_artillery_operational")*{cfg['shells_per_gun']},actor.AuxDataDouble("ca_shells")));
  if (shells<1) {{ GtxCAStopFire(actor,6); return; }}
  power={indirect_power};
 }}
 if (actor.GroundRangeTo(target)>range) {{ GtxCAStopFire(actor,4); return; }}
 if (kind>0 && actor.GroundRangeTo(target)<{cfg['artillery_min_range_m']}) {{ GtxCAStopFire(actor,5); return; }}
 double efficiency={efficiency};
 double cover=GtxCAAirCover(target); if (kind==0) {{ cover={cover}; }}
 double damage=power*efficiency*cover;
 if (kind==2) {{ damage={suppress_effect}; }}
 actor.SetAuxData("ca_fire_stop_reason",0.0); actor.SetAuxData("ca_blocked",0.0);
 actor.SetAuxData("ca_shells",actor.AuxDataDouble("ca_shells")-shells);
 actor.SetAuxData("ca_ammo_spent",actor.AuxDataDouble("ca_ammo_spent")+actor.AuxDataDouble("ca_ammo_cycle"));
 actor.SetAuxData("ca_shots",actor.AuxDataDouble("ca_shots")+Math.Max(1,shells));
 actor.SetAuxData("ca_fire_cycles",actor.AuxDataDouble("ca_fire_cycles")+1);
 actor.SetAuxData("ca_small_arms_attempts",actor.AuxDataDouble("ca_small_arms_attempts")+GtxRound(attempts*efficiency));
 actor.SetAuxData("ca_fire_lat_micro",(double)((int)(target.Latitude()*1000000)));
 actor.SetAuxData("ca_fire_lng_micro",(double)((int)(target.Longitude()*1000000)));
 {impact}
 {damage_accumulation}
 target.SetAuxData("ca_pending_stress",target.AuxDataDouble("ca_pending_stress")+power*efficiency);
 {suppression_accumulation}
end_script
script double GtxCAAirDefense(WsfPlatform aircraft,string enemy,int package)
 WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub"); double exposure=0;
''']
    for i,(team,u) in enumerate(missions.units(before)):
        p=f'd{i}';text += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{ids[u["name"]]}");',
            f' if (enemy=="{team}" && {p}.GroundRangeTo(aircraft)<={cfg["aa_range_m"]} && aircraft.Altitude()<={cfg["aa_ceiling_m"]} && {get(p,"air_defense_operational")}>0 && {get(p,"aa_rounds")}>0) {{',
            f' double shots{i}=Math.Min({get(p,"aa_rounds")},{get(p,"air_defense_operational")}*5);',
            put(p,'aa_rounds',get(p,'aa_rounds')+f'-shots{i}'),put(p,'aa_spent',get(p,'aa_spent')+f'+shots{i}'),
            f' exposure=exposure+package*{cfg["aa_loss_coefficient"]}*(shots{i}/5)*{get(p,"strength_ratio")}*Math.Max(0,1-{get(p,"suppression")}/100)*Math.Max(0,1-{p}.GroundRangeTo(aircraft)/{cfg["aa_range_m"]});',' }']
    text += [' double carry=hub.AuxDataDouble("ca_aa_carry_"+enemy);',
             ' double lost=Math.Min(package,Math.Floor(carry+Math.Min(package,exposure)));',
             ' hub.SetAuxData("ca_aa_carry_"+enemy,carry+Math.Min(package,exposure)-lost);',' return lost;','end_script']
    return '\n'.join(text)


def parse(text,model,scene,*,accounts=None):
    if model.get('continuous_motion',{}).get('shared_fortification'):
        raise ValueError('共享施工的正式状态、成对工事与分合兵/阶段续接尚未验收')
    depot_fuel={}
    rows={};gear={};facility=None;events=[];pools={};firing={};casualties={};small_arms={};received={};density={};suppression_rows={};expected=set(scene['entities'])
    for line in text.splitlines():
        p=line.split('|')
        if p[0]=='GTXSTRENGTH':
            if type(model.get('strength_clock_revision')) is not int or model['strength_clock_revision']!=1:
                raise ValueError('兵力时钟原生回执未绑定正确版本，不能忽略或降级')
        elif p[0]=='GTXCUNIT':
            if len(p)!=len(FIELDS)+2 or p[1] not in expected or p[1] in rows:raise ValueError('编组模型回传不完整或重复')
            values=[float(value) if key in ('intel_age_min','intel_confidence') else int(value) for key,value in zip(FIELDS,p[2:])]
            rows[p[1]]=dict(zip(FIELDS,values))
            if any(not math.isfinite(v) or v<0 for k,v in rows[p[1]].items() if k not in ('fire_lat_micro','fire_lng_micro')):raise ValueError('负数或非有限编组资源与状态')
        elif p[0]=='GTXCSUPPLY':
            if len(p)!=len(SUPPLY_FIELDS)+2 or p[1] not in expected or p[1] in received:
                raise ValueError('分类到货回传缺项或重复')
            values=list(map(int,p[2:]))
            if any(v<0 for v in values):raise ValueError('分类到货出现负数')
            received[p[1]]=dict(zip(SUPPLY_FIELDS,values))
        elif p[0]=='GTXCEQUIP':
            key=p[1]+'/'+p[2]
            if len(p)!=7 or p[1] not in expected or p[2] not in combined_arms.RULES['categories'] or key in gear:raise ValueError('分类装备回传不完整或重复')
            values=list(map(int,p[3:]));gear[key]=dict(zip(('operational','damaged','destroyed','load_million'),values))
            if any(v<0 for v in values):raise ValueError('分类装备出现负数')
        elif p[0]=='GTXCFAC':
            if facility is not None or len(p)!=7:raise ValueError('设施回传不完整或重复')
            facility=dict(zip(('progress','integrity','materials','used','aa_red','aa_blue'),map(int,p[1:])))
        elif p[0]=='GTXCDEPOT':
            if len(p)!=7 or p[1] not in ('red','blue') or p[1] in pools:raise ValueError('分类仓库回传缺项或重复')
            pools[p[1]]=dict(zip(('fuel_liters','spares','materials','shells','aa_rounds'),map(int,p[2:])))
            if any(v<0 for v in pools[p[1]].values()):raise ValueError('分类仓库库存负数')
        elif p[0]=='GTXCDEPOTFUEL':
            if (model.get('continuous_motion',{}).get('fuel_receipt_revision')!=2 or len(p)!=3
                    or p[1] not in ('red','blue') or p[1] in depot_fuel):
                raise ValueError('连续机动仓库燃油回执版本或身份非法')
            depot_fuel[p[1]]=int(p[2])
        elif p[0]=='GTXCEVENT':
            if len(p)!=5 or p[1] not in expected or p[2] not in missions.ACTIONS:raise ValueError('未知指挥执行事件')
            at=float(p[3])/1000
            if not math.isfinite(at) or not 0<=at<=scene['seconds']:raise ValueError('原生过程事件时点超出物理回合')
            events.append({'unit':scene['entities'][p[1]]['name'],'action':p[2],'seconds':at,'status_code':int(p[4])})
        elif p[0]=='GTXDENSITY':
            if len(p)!=len(DENSITY_FIELDS)+2 or p[1]not in expected or p[1]in density:
                raise ValueError('动态密度回执字段缺项、重复或身份不符')
            density[p[1]]=dict(zip(DENSITY_FIELDS,[float(p[2]),*map(int,p[3:])]))
        elif p[0]=='GTXSUPPRESSION':
            from . import afsim_suppression
            afsim_suppression.read_row(p,suppression_rows,scene)
        elif p[0] in ('GTXFIRE','GTXCASUALTY'):
            fields=FIRE_FIELDS if p[0]=='GTXFIRE' else CASUALTY_FIELDS
            destination=firing if p[0]=='GTXFIRE' else casualties
            if len(p)!=len(fields)+2 or p[1] not in expected or p[1] in destination:
                raise ValueError('火力周期或伤亡分类回传缺项、重复')
            values=list(map(int,p[2:]));destination[p[1]]=dict(zip(fields,values))
            if any(v<0 for v in values):raise ValueError('火力周期或伤亡分类出现负数')
        elif p[0]=='GTXSMALL':
            if len(p)!=4 or p[1] not in expected or p[1] in small_arms:raise ValueError('小武器射击估计回传缺项或重复')
            major,minor=map(int,p[2:])
            if major<0 or not 0<=minor<1000000:raise ValueError('小武器射击估计为非法计数')
            small_arms[p[1]]=major*1000000+minor
    if set(rows)!=expected or set(gear)!={i+'/'+c for i in expected for c in combined_arms.RULES['categories']} or facility is None or set(pools)!={'red','blue'}:raise ValueError('AFSIM多兵种回传缺项，原战局不提交')
    _validate_density(density,model,scene,accounts=accounts)
    from . import afsim_suppression
    afsim_suppression.validate_receipts(suppression_rows,model,scene,rows)
    if model.get('combat_revision') in (2,3,4,5):
        if set(firing)!=expected or set(casualties)!=expected:raise ValueError('持续火力或伤亡分类证据缺失，不能退回单次扣血')
        for identity,f in firing.items():
            if (f['active_s']>scene['seconds'] or f['cycles']>math.ceil(scene['seconds']/10)
                    or f['damage_load']>=1000000 or f['fatality_load']>=1000000
                    or bool(f['cycles'])!=bool(rows[identity]['shots'])):
                raise ValueError('火力周期时间、弹耗或毁伤余量不一致')
    if model.get('combat_profile',{}).get('direct_fire') and set(small_arms)!=expected:
        raise ValueError('缺少小武器射击估计回执，不能冒充新版直射模型')
    old={u['name']:u for _,u in model['units']}
    for identity in expected:
        previous=old[scene['entities'][identity]['name']]
        for e in previous['equipment']:
            actual=gear[identity+'/'+e['category']]
            if sum(actual[k] for k in ('operational','damaged','destroyed'))!=e['committed'] or actual['destroyed']<e['destroyed'] or not 0<=actual['load_million']<1000000:raise ValueError('原生分类装备账不守恒')
    if len({e['unit'] for e in events})!=len(events) or any(not 0<=e['seconds']<=scene['seconds'] for e in events):raise ValueError('指挥事件重复或时刻越界')
    for team in ('red','blue'):
        own=[(identity,old[entry['name']]) for identity,entry in scene['entities'].items() if entry['team']==team]
        for key in ('shells','aa_rounds','spares','fuel_liters','materials'):
            prior=model['before_combined']['depots'][team][key]+sum(u['formation'][key] for _,u in own)
            following=pools[team][key]+sum(rows[identity][key] for identity,_ in own)
            if following>prior:raise ValueError('分类物资凭空增加：'+key)
            spent=sum(rows[identity]['aa_spent'] if key=='aa_rounds' else rows[identity]['repaired'] if key=='spares' else rows[identity]['shots'] if next((e['action'] for e in events if e['unit']==u['name']),'hold') in ('bombard','suppress') else 0 for identity,u in own)
            if key in ('shells','aa_rounds','spares') and prior-following!=spent:raise ValueError('分类物资消耗不守恒：'+key)
    validate_supply_receipts(received,rows,pools,events,model,scene)
    from . import afsim_sustainment
    from . import afsim_supply_schedule
    schedule=afsim_supply_schedule.parse(text,model,scene) if model.get('supply_schedule') else None
    if schedule:
        if accounts is None or set(accounts)!=set(scene['entities']):raise ValueError('定时补给缺少单位总账')
        for identity,entry in scene['entities'].items():
            total=schedule['checked'][entry['name']];account=accounts[identity]
            for key,expected in [('food',total['food_after']),('ammo',total['ammo_after']),
                    ('food_received',total['food_received']),('ammo_received',total['ammo_received']),
                    ('delivery',total['delivery']),('food_spent',total['nutrition']['consumed']),('ammo_spent',total['ammo_spent'])]:
                if not math.isclose(account.get(key,-1),expected,rel_tol=0,abs_tol=1e-6):
                    raise ValueError('定时补给事件与单位总账不符：'+key)
            if received[identity]!=total['received']:raise ValueError('定时补给事件与分类到货不符')
    nutrition=afsim_sustainment.parse(text,model,scene,scheduled=schedule['checked'] if schedule else None)
    result={'nutrition':nutrition,'units':rows,'equipment':gear,'facility':facility,'events':events,'depots':pools,
            'firing':firing,'casualties':casualties,'small_arms':small_arms,'received':received}
    if model.get('strength_clock_revision') is not None:
        from . import afsim_strength_clock, afsim_motion_nutrition
        result['workforce_clock']=afsim_strength_clock.parse(text,model,scene,accounts,
            afsim_motion_nutrition.read_segments(text,model['continuous_motion']))
    if density:result['density']=density
    if suppression_rows:result['suppression_state']=suppression_rows
    from . import afsim_movement
    movement=afsim_movement.parse(text,model,scene)
    if model.get('movement_feedback'):result['movement']=movement
    if model.get('continuous_motion'):
        from . import afsim_continuous_motion
        motion=schedule.get('continuous_motion') if schedule else None
        if motion is None:motion=afsim_continuous_motion.parse(text,model['continuous_motion'])
        for identity,row in motion.items():
            for key in ('fatigue','fuel_liters'):
                if rows[identity][key]!=row['formation'][key]:
                    raise ValueError('连续机动与整局编组状态不一致：'+key)
            if abs(movement[identity]['ground_km']-row['distance_micrometers']/1e9)>1e-9:
                raise ValueError('连续机动路程与整局回执不一致')
            if model['continuous_motion'].get('fuel_receipt_revision')==2:
                from gentactix import motion_state
                if row['fuel_received_microliters']!=received[identity]['fuel_liters']*motion_state.SCALE:
                    raise ValueError('连续机动燃油到货与分类补给回执不一致')
            if model['continuous_motion'].get('nutrition_revision'):
                if (row['fatigue_flow']['food_floor_gained_ticks']!=nutrition[identity]['fatigue_floor_gain_ticks']
                        or row['moving_ms']!=nutrition[identity]['moving_ms']):
                    raise ValueError('分时营养与机动时间或疲劳下限收支不一致')
        result['continuous_motion']=motion
        if model['continuous_motion'].get('fuel_receipt_revision')==2:
            result['fuel_flow']=validate_motion_fuel_totals(model,scene,motion,pools,depot_fuel)
    if schedule:
        from gentactix import supply_schedule
        result['supply_schedule']=supply_schedule.compact_ledger(schedule['ledger'],schedule['checked'])
    if model.get('campaign_revision') is not None:
        from . import afsim_campaign
        if model['campaign_revision']!=afsim_campaign.REVISION:raise ValueError('战役原生过程版本不支持')
        result['campaign']=afsim_campaign.parse(text,model,scene)
    if 'crossing_model' in model['before_combined']['bridge']:
        from . import afsim_crossing
        before={'combined_arms':model['before_combined'],'mission':{'turn':model['expected_turn']-1},
                **{team+'_units':[u for t,u in model['units'] if t==team] for team in ('red','blue')}}
        result['crossing']=afsim_crossing.parse(text,scene,before)
        from . import afsim_ferries
        if afsim_ferries.enabled(before):result['ferry_state']=afsim_ferries.parse(text,scene,before)
    return result


def validate_supply_receipts(received,rows,pools,events,model,scene):
    """Reconcile native evidence only; do not calculate or apply deliveries."""
    if model.get('supply_receipt_revision') is None and not received:return
    if model.get('supply_receipt_revision') not in (None,1):raise ValueError('分类到货回执版本不支持')
    if set(received)!=set(scene['entities']):raise ValueError('分类到货证据缺项，不能当作零到货')
    old={u['name']:u for _,u in model['units']}
    actions={e['unit']:e['action'] for e in events}
    for identity,receipt in received.items():
        if set(receipt)!=set(SUPPLY_FIELDS) or any(type(v) is not int or v<0 for v in receipt.values()):
            raise ValueError('分类到货证据非法')
        u=old[scene['entities'][identity]['name']];f=u['formation'];r=rows[identity]
        spent={'shells':r['shots'] if actions.get(u['name']) in ('bombard','suppress') else 0,
               'aa_rounds':r['aa_spent'],'spares':r['repaired']}
        for key in spent:
            if f[key]+receipt[key]-spent[key]!=r[key]:raise ValueError('分类到货与单位库存不守恒：'+key)
    for team in ('red','blue'):
        for key in SUPPLY_FIELDS:
            delivered=sum(received[i][key] for i,e in scene['entities'].items() if e['team']==team)
            depot_delta=model['before_combined']['depots'][team][key]-pools[team][key]
            if delivered>depot_delta or key in ('shells','aa_rounds','spares') and delivered!=depot_delta:
                raise ValueError('分类到货与仓库库存不守恒：'+key)


def apply(after,telemetry,scene,model):
    if model.get('combat_profile'):after['combat_reference']=copy.deepcopy(model['combat_profile'])
    data=telemetry['combined_arms'];old=model['before_combined'];state=copy.deepcopy(old)
    if model.get('campaign_revision') is not None:
        from . import afsim_campaign
        afsim_campaign.apply(after,data['campaign'],scene,model)
    f=data['facility'];state['bridge'].update({k:f[k] for k in ('progress','integrity','materials','used')})
    state['aa_loss_remainder']={'red':f['aa_red']/1e6,'blue':f['aa_blue']/1e6};state['events']=data['events']
    state['turn']=model['expected_turn'];after['combined_arms']=state
    state['depots']=copy.deepcopy(data['depots'])
    if data.get('fuel_flow'):
        state['fuel_flow']={'version':'native-physical-fuel-flow-1','turn':model['expected_turn'],
            'source':'afsim_native_estimate','unit':'microliter','teams':copy.deepcopy(data['fuel_flow'])}
    if data.get('supply_schedule'):
        after['supply_schedule']={'version':data['supply_schedule']['version'],'turn':model['expected_turn'],
            'source':'afsim_native_estimate','ledger':copy.deepcopy(data['supply_schedule'])}
    index={u['name']:u for _,u in missions.units(after)}
    if data.get('ferry_state'):state['bridge']['ferry_state']=copy.deepcopy(data['ferry_state'])
    if data.get('crossing'):
        state['bridge']['crossing_receipt']={**copy.deepcopy(data['crossing']['capacity']),'turn':model['expected_turn'],
            'source':'afsim_native_estimate','scope':'整建制渡运工作量；不是已过河个人数或微观桥头战斗'}
        for identity,task in data['crossing']['tasks'].items():index[scene['entities'][identity]['name']]['crossing']=copy.deepcopy(task)
        for site,receipt in zip(state['bridge'].get('crossing_network',{}).get('sites',[]),data['crossing'].get('sites',[])[1:]):
            site.update(receipt['facility'])
            site['crossing_receipt']={**copy.deepcopy(receipt['capacity']),'turn':model['expected_turn'],
                'source':'afsim_native_estimate','scope':'独立渡点容量；共用全场部队和库存'}
    for identity,row in data['units'].items():
        u=index[scene['entities'][identity]['name']];formation=u['formation']
        formation.update({k:row[k] for k in FIELDS if k in formation})
        formation['last_execution']={**row,'source':combined_arms.VERSION,'turn':model['expected_turn']}
        if identity in data.get('workforce_clock',{}):
            formation['last_execution']['workforce_clock']=copy.deepcopy(data['workforce_clock'][identity])
        if identity in data.get('continuous_motion',{}):
            from . import afsim_continuous_motion
            motion=data['continuous_motion'][identity]
            formation.update(copy.deepcopy(motion['formation']))
            formation['last_execution']['continuous_motion']={
                **{k:v for k,v in motion.items() if k!='formation'},
                'version':afsim_continuous_motion.VERSION,'turn':model['expected_turn'],
                'source':'afsim_native_estimate','fuel_unit':'microliter'}
        formation['last_execution']['action']=next((e['action'] for e in data['events'] if e['unit']==u['name']),'未交付')
        if identity in data.get('suppression_state',{}):
            from gentactix import suppression_state
            formation[suppression_state.FIELD]=data['suppression_state'][identity]['carry_ticks']
            formation['last_execution']['suppression_state_version']=suppression_state.VERSION
        if identity in data.get('density',{}):
            formation['last_density_sample']={**data['density'][identity],
                'version':combat_effects.DENSITY_VERSION,'source':'afsim_native','turn':model['expected_turn']}
        if identity in data.get('received',{}):
            formation['last_execution'].update({'received_'+key:value for key,value in data['received'][identity].items()})
            formation['last_execution']['supply_receipt_revision']=model.get('supply_receipt_revision',1)
        if identity in data.get('small_arms',{}):
            formation['last_execution']['small_arms_rounds_estimate']=data['small_arms'][identity]
        if identity in data.get('firing',{}):
            fire=data['firing'][identity]
            formation.update(reload_remaining_s=fire['reload_s'],combat_damage_remainder=fire['damage_load']/1e6,
                             fatality_remainder=fire['fatality_load']/1e6)
            formation['last_execution'].update(fire_cycles=fire['cycles'],active_fire_s=fire['active_s'],
                fire_stop_reason=fire['stop_reason'],combat_revision=model['combat_revision'])
            prior=next(v['personnel'] for _,v in model['units'] if v['name']==u['name'])
            u['personnel'].update(data['casualties'][identity],
                breakdown_source=('持续火力与受降模型估计；伤亡按显式比例分类，被俘另按实际受降回执，既有未分类减员保留' if model.get('campaign_revision') else
                    '持续火力模型估计；新伤亡按显式比例分类，既有未分类减员保留；失踪/被俘未新增生成'))
            combat_effects.validate_personnel(u['personnel'],prior)
        for e in u['equipment']:
            r=data['equipment'][identity+'/'+e['category']]
            e.update({k:r[k] for k in ('operational','damaged','destroyed')});e['damage_load']=r['load_million']/1e6;e['calculation_source']=combined_arms.VERSION
    # Create only actually fired events, with resolved engine coordinates. The
    # requesting ground weapon's declared range still passes normal geometry QA.
    after['engagements']=[]
    for order in model['orders']:
        if order['action'] not in ('fire','bombard','suppress'):continue
        u=index[order['unit']];row=u['formation']['last_execution']
        if not row['shots']:continue
        t=index[order['target']]
        after['engagements'].append({'attacker':u['name'],'attacker_team':next(team for team,x in missions.units(after) if x['name']==u['name']),
            'attacker_pos':[u['lat'],u['lng']],'lat':row['fire_lat_micro']/1e6,'lng':row['fire_lng_micro']/1e6,'weapon_action':order['action'],
            'description':'AFSIM团级教学火力；实际弹耗及压制见分类模型账，非历史武器效能标定'})
    from . import afsim_sustainment
    afsim_sustainment.apply(after,data['nutrition'],scene,model,telemetry['units'])
    from . import afsim_movement
    afsim_movement.apply(after,data,scene,model)
    combined_arms.validate(after)
    if model.get('intelligence_revision'):
        from gentactix import c2_observation
        prior={team+'_units':[u for t,u in model['units'] if t==team] for team in ('red','blue')}
        prior['combined_arms']=model['before_combined']
        state['intelligence']=c2_observation.validate_transition(prior,after,model['orders'],data['events'],
            scene['seconds'],source='afsim_native_estimate',minimum_delays={
                scene['entities'][identity]['name']:row['delay_s'] for identity,row in data['units'].items()})
