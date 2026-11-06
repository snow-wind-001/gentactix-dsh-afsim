"""Compile timed, shared-capacity delivery into AFSIM; Python only checks logs."""
import copy
import math

from gentactix import missions, supply, supply_schedule as ss, formation_parts, support_dynamics as sd
from .afsim_literals import number as n


def get(p, key): return f'{p}.AuxDataDouble("sl_{key}")'
def put(p, key, value): return f'{p}.SetAuxData("sl_{key}",(double)({value}));'
def ca(p,key): return f'{p}.AuxDataDouble("ca_{key}")'
def caput(p,key,value): return f'{p}.SetAuxData("ca_{key}",(double)({value}));'


def physical(before):return ss.receipt_version(before)==ss.PHYSICAL_VERSION


def food(p,before):return f'GtxCNGet({p},"food")' if physical(before) else get(p,'food')


def nutrition(p,key,before):return f'GtxCNGet({p},"{key}")' if physical(before) else get(p,key)


def setup(before, identities):
    lines=[]
    for d,node in enumerate(before['supply_nodes']):
        for key in ('food','ammo'):lines.append(put('hub',f'node_{d}_{key}',n(node['commodities'][key])))
    for _,u in missions.units(before):
        p='WsfSimulation.FindPlatform("'+identities[u['name']]+'")';scale=formation_parts.scale(u)
        values={'food':u['logistics']['food']*scale,'food_received':0,'ammo_received':0,'last_s':0,
                'need':0,'used':0,'unmet':0,'nc':0,'debt':u['sustainment']['shortage_hours'],
                'remainder':u['sustainment']['noncombat_remainder'],'previous_ammo_spent':0,
                'cargo_tons':0,'capacity_tons':0,'connectivity':-1}
        values.update({'previous_'+k:u['formation'][k] for k in ss.CLASSIFIED})
        values.update({'received_'+k:0 for k in ss.CLASSIFIED})
        if physical(before):
            for k in ('food','last_s','need','used','unmet','nc','debt','remainder','previous_fuel_liters'):values.pop(k)
        for key,value in values.items():lines.append(put(p,key,n(value)))
    return lines


def _consume(before,u,p,*,probe=False):
    if physical(before):return [f' GtxCMSettle({p});']
    cfg=before['mission']['definition']['support_dynamics'];scale=formation_parts.scale(u)
    action=before['_schedule_orders'].get(u['name'],{}).get('action','hold')
    rate=sd.unit_demand(cfg,u,action,3600)
    if cfg['version']==sd.PERSONNEL_VERSION:
        per_person=cfg['ration_kg_per_person_day']/24/cfg['food_kg_per_work']*(cfg['move_factor'] if action=='move' else 1)
        rate_expression=f'Math.Max(0,{u["personnel"]["current"]}-{get(p,"nc")})*{n(per_person)}'
    else:rate_expression=n(rate)
    deferred=sd.deferred_support(u)
    return [f' double dt=Math.Max(0,TIME_NOW-{get(p,"last_s")});',
        f' double hours={"0" if deferred and probe else "dt/3600"}; if ({u["personnel"]["current"]}-{get(p,"nc")}<=0) {{ hours=0; }}',
        f' double need=hours*({rate_expression}); double used=Math.Min(need,{get(p,"food")});',
        ' double unfed=0; if (need>0) { unfed=hours*(1-used/need); }',
        f' double recovered=Math.Max(0,{get(p,"debt")}-Math.Max(0,hours-unfed)*{n(cfg["recovery_hours_per_fed_hour"])});',
        ' double debt=recovered+unfed;',
        f' double exposure=Math.Max(0,debt-{n(cfg["incapacity_after_hours"])})-Math.Max(0,recovered-{n(cfg["incapacity_after_hours"])});',
        f' double load={get(p,"remainder")}+exposure*{u["personnel"]["committed"]}*{n(cfg["incapacity_fraction_per_hour"])};',
        ' double whole=Math.Floor(load+0.000000001);',
        *([' if (exposure<=0) { whole=0; }'] if deferred else []),
        put(p,'remainder','Math.Max(0,load-whole)'),put(p,'debt','debt'),
        put(p,'nc',get(p,'nc')+f'+Math.Min(Math.Max(0,{u["personnel"]["current"]}-{get(p,"nc")}),whole)'),
        put(p,'food',get(p,'food')+'-used'),put(p,'last_s','TIME_NOW'),
        put(p,'need',get(p,'need')+'+need'),put(p,'used',get(p,'used')+'+used'),put(p,'unmet',get(p,'unmet')+'+need-used'),
        caput(p,'fatigue',f'Math.Max({ca(p,"fatigue")},Math.Floor(Math.Min(100,debt*{n(cfg["shortage_fatigue_per_hour"])})))')]


def _receipt_start(before,u,p,*,consume=True,probe=False):
    lines=_consume(before,u,p,probe=probe) if consume else []
    lines += [f' double ammoUsed={ca(p,"ammo_spent")}-{get(p,"previous_ammo_spent")};',
              put(p,'previous_ammo_spent',ca(p,'ammo_spent'))]
    for key in ss.CLASSIFIED:
        if physical(before) and key=='fuel_liters':continue
        lines.append(f' double spent_{key}=Math.Max(0,{get(p,"previous_"+key)}-{ca(p,key)});')
    return lines


def _receipt_end(u,p,identity,kind,*,continuous=False):
    for_key=[]
    for key in ss.CLASSIFIED:
        if not continuous or key!='fuel_liters':for_key.append(put(p,'previous_'+key,ca(p,key)))
        for_key.append(put(p,'received_'+key,get(p,'received_'+key)+'+got_'+key))
    values=['Format.Fixed(TIME_NOW,9)','"'+kind+'"',f'(int){get(p,"connectivity")}',
            f'Format.Fixed({p}.Latitude(),12)',f'Format.Fixed({p}.Longitude(),12)',
            'Format.Fixed(foodGot,12)','Format.Fixed(ammoGot,12)','Format.Fixed(ammoUsed,12)']
    values += ['(int)got_'+k for k in ss.CLASSIFIED]+['(int)spent_'+k for k in ss.CLASSIFIED if not continuous or k!='fuel_liters']
    prefix='GTXSCHEDULE2' if continuous else 'GTXSCHEDULE'
    return for_key+[f' writeln("{prefix}|{identity}|",'+',"|",'.join(values)+');']


def compile_events(before,orders,identities,seconds):
    cfg=ss.configuration(before);rules=before['mission']['definition']['combined_rules'];split=before['mission']['definition']['supply_distribution']
    source={**before,'_schedule_orders':{o['unit']:o for o in orders}}
    lines=[]
    from . import afsim_campaign
    from gentactix import campaign
    for when,kind in ss.event_times(before,seconds):
        if kind!='delivery':continue
        lines += [f'execute at_time {when} sec absolute',' WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub");']
        for d,node in enumerate(before['supply_nodes']):
            lines.append(f' double budget{d}={n(cfg["warehouse_tons_per_hour"][node["id"]]*cfg["period_seconds"]/3600)};')
        # Resolve the whole preceding interval before examining any recipient or
        # enemy control. Otherwise a later-listed, now incapacitated enemy can
        # still block an earlier recipient at this same delivery instant.
        for _,u in missions.units(before):
            identity=identities[u['name']]
            lines += [' {',f' WsfPlatform sp=WsfSimulation.FindPlatform("{identity}");',
                      *_consume(source,u,'sp',probe=seconds<1),' }']
        for i,(team,u) in enumerate(missions.units(before)):
            p='sp';identity=identities[u['name']];scale=formation_parts.scale(u)
            node=supply.bound_node(before,team,u);d=before['supply_nodes'].index(node)
            action=source['_schedule_orders'].get(u['name'],{}).get('action','hold')
            lines += [' {',f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");',*_receipt_start(source,u,p,consume=False),
                f' double route=GtxDistance({n(node["lat"])},{n(node["lng"])},{p}.Latitude(),{p}.Longitude());',
                f' double rate={n(cfg["passive_work_per_hour"])};']
            if action=='resupply':lines.append(f' if ({ca(p,"command_done")}>0) {{ rate={n(cfg["resupply_work_per_hour"])}; }}')
            lines += [f' double work=rate*{n(cfg["period_seconds"]/3600*scale)};',
                f' double capacity={ca(p,"transport_operational")}*{n(rules["transport_tons_per_truck"])}*{ca(p,"live_strength_ratio" if physical(before) else "strength_ratio")}*{n(cfg["period_seconds"]/3600)}/({n(cfg["loading_hours"])}+2*route/{n(cfg["convoy_speed_kph"])});',
                f' double cargo=Math.Min(capacity,budget{d}); double initialCargo=cargo;',
                f' int conn=1; if ({ca(p,"live_strength_ratio")}<=0 || {u["personnel"]["current"]}-{nutrition(p,"nc",before)}<=0) {{ conn=0; }}']
            for j,(enemy,other) in enumerate(missions.units(before)):
                if enemy==team or other['ground_control_radius_km']<=0:continue
                q=f'q{j}';enemyid=identities[other['name']]
                active=f' && TIME_NOW>={afsim_campaign.get(q,"release_s")}' if campaign.definition(before) else ''
                lines += [f' WsfPlatform {q}=WsfSimulation.FindPlatform("{enemyid}");',
                    f' if ({ca(q,"live_strength_ratio")}>0 && {other["personnel"]["current"]}-{nutrition(q,"nc",before)}>0{active} && GtxBlocked({n(node["lat"])},{n(node["lng"])},{p}.Latitude(),{p}.Longitude(),{q}.Latitude(),{q}.Longitude(),{n(other["ground_control_radius_km"])})) {{ conn=0; }}']
            lines += [put(p,'connectivity','conn'),' if (conn==0) { cargo=0; }',
                      ' double foodGot=0; double ammoGot=0;']
            keys=[split['priority'],'ammo' if split['priority']=='food' else 'food']
            for key in keys:
                share=split['food_mass_share'] if key=='food' else 1-split['food_mass_share']
                available=food(p,before) if key=='food' else ca(p,'ammo_available')+'-'+ca(p,'ammo_spent')
                mass=share*rules['ton_per_supply_unit']
                variable='foodGot' if key=='food' else 'ammoGot'
                capacity=(sd.food_capacity(before['mission']['definition']['support_dynamics'],u) if key=='food' else 100)*scale
                lines += [f' {variable}=Math.Min(work,Math.Min(Math.Max(0,{n(capacity)}-({available})),Math.Min({get("hub",f"node_{d}_{key}")},cargo/{n(mass)})));',
                          f' cargo=Math.Max(0,cargo-{variable}*{n(mass)});',
                          put('hub',f'node_{d}_{key}',get('hub',f'node_{d}_{key}')+'-'+variable)]
            lines += [f' GtxCNReceiveFood({p},foodGot);' if physical(before) else put(p,'food',get(p,'food')+'+foodGot'),put(p,'food_received',get(p,'food_received')+'+foodGot'),
                      put(p,'ammo_received',get(p,'ammo_received')+'+ammoGot'),caput(p,'ammo_available',ca(p,'ammo_available')+'+ammoGot')]
            transfer={'fuel_liters':100 if u['formation'].get('motorized',rules['motorized']) else 0,'spares':1,'materials':1} if action=='resupply' else {}
            transfer.update(shells=rules['shells_per_supply_unit'] if any(e['category']=='artillery' and e['committed'] for e in u['equipment']) else 0,
                            aa_rounds=rules['aa_rounds_per_supply_unit'] if any(e['category']=='air_defense' and e['committed'] for e in u['equipment']) else 0)
            for key in ss.CLASSIFIED:
                amount=transfer.get(key,0)
                if key in ('fuel_liters','spares','materials'):factor='*'+ca(p,'command_done')
                else:factor=''
                mass=rules['cargo_mass_tons'][key]
                lines += [f' double got_{key}=Math.Min({ca("hub",team+"_"+key)},Math.Min(Math.Floor(work*{amount}{factor}),Math.Floor(cargo/{n(mass)})));',
                          f' cargo=Math.Max(0,cargo-got_{key}*{n(mass)});',
                          caput('hub',team+'_'+key,ca('hub',team+'_'+key)+'-got_'+key),
                          f' GtxCMReceiveFuel({p},got_{key});' if physical(before) and key=='fuel_liters' else caput(p,key,ca(p,key)+'+got_'+key)]
            lines += [f' budget{d}=Math.Max(0,budget{d}-(initialCargo-cargo));',
                      put(p,'cargo_tons',get(p,'cargo_tons')+'+initialCargo-cargo'),
                      put(p,'capacity_tons',get(p,'capacity_tons')+'+capacity'),
                      *_receipt_end(u,p,identity,'delivery',continuous=physical(before))]
            if physical(before):lines += [f' GtxCMFuelEvent({p},"delivery");',f' GtxCMUpdate({p},true,false);']
            lines.append(' }')
        lines.append('end_execute')
    return '\n'.join(lines)


def finish(before,u,orders,i,identity,p,*,seconds=None):
    source={**before,'_schedule_orders':{o['unit']:o for o in orders}}
    cfg=before['mission']['definition']['support_dynamics'];split=before['mission']['definition']['supply_distribution'];scale=formation_parts.scale(u)
    lines=[' {',*_receipt_start(source,u,p,probe=seconds is not None and seconds<1),' double foodGot=0; double ammoGot=0;']
    lines += [f' double got_{k}=0;' for k in ss.CLASSIFIED]
    food_value=f'{food(p,before)}/{n(scale)}' if physical(before) else f'Math.Min(100,Math.Max(0,{get(p,"food")}/{n(scale)}))'
    lines += [*_receipt_end(u,p,identity,'settlement',continuous=physical(before)),' }',
        f' double foodDelivery{i}={get(p,"food_received")}; double ammoDelivery{i}={get(p,"ammo_received")};',
        f' double delivery{i}=foodDelivery{i}*{n(split["food_mass_share"])}+ammoDelivery{i}*{n(1-split["food_mass_share"])};',
        f' double food{i}={food_value}; double foodUsed{i}={nutrition(p,"used",before)}; double noncombat{i}={nutrition(p,"nc",before)};',
        f' int conn{i}=(int){get(p,"connectivity")};',
        caput(p,'transport_capacity_milli',f'GtxRound({get(p,"capacity_tons")}*1000)'),
        caput(p,'delivery_tons_milli',f'GtxRound({get(p,"cargo_tons")}*1000)'),
        f' writeln("GTXSPLIT|{identity}|",Format.Fixed(foodDelivery{i},12),"|",Format.Fixed(ammoDelivery{i},12));',
        f' writeln("GTXCSUPPLY|{identity}|",'+',"|",'.join(f'(int){get(p,"received_"+k)}' for k in ss.CLASSIFIED)+');']
    values=[nutrition(p,k,before) for k in ('need','used','unmet','debt','remainder')]+[
            f'Math.Min(100,{nutrition(p,"debt",before)}*{n(cfg["shortage_fatigue_per_hour"])})',nutrition(p,'nc',before)]
    lines += [f' writeln("GTXNUTRITION|{identity}|",'+',"|",'.join(f'Format.Fixed({v},12)' for v in values)+');']
    if formation_parts.is_fragment(u):lines.append(f' double ncCarry{i}={n(u["formation"].get("partition_noncombat_remainder",0))};')
    return lines


def parse(text,model,scene):
    before=model['supply_schedule_inputs'];units={e['name']:[] for e in scene['entities'].values()}
    continuous=physical(before);prefix='GTXSCHEDULE2|' if continuous else 'GTXSCHEDULE|'
    if continuous and model.get('continuous_motion',{}).get('nutrition_schedule_revision')!='native-scheduled-nutrition-1':
        raise ValueError('定时补给须绑定连续营养回执版本')
    for line in text.splitlines():
        if not line.startswith(('GTXSCHEDULE|','GTXSCHEDULE2|')):continue
        if not line.startswith(prefix):raise ValueError('定时补给原生回执版本不匹配')
        p=line.split('|')
        size=19 if continuous else 20
        if len(p)!=size or p[1] not in scene['entities']:raise ValueError('定时补给原生回执身份或字段非法')
        numbers=[float(p[k]) for k in range(4,size)]
        if any(not math.isfinite(v) for v in numbers):raise ValueError('定时补给原生回执非有限数')
        conn=int(p[4])
        if conn not in (-1,0,1):raise ValueError('定时补给原生连通状态非法')
        spent_keys=tuple(k for k in ss.CLASSIFIED if not continuous or k!='fuel_liters')
        received=dict(zip(ss.CLASSIFIED,map(float,p[10:15])));spent=dict(zip(spent_keys,map(float,p[15:size])))
        for values in (received,spent):
            if any(v!=int(v) or v<0 for v in values.values()):raise ValueError('定时补给原生分类数值非法')
        when=float(p[2]);when=int(when) if when.is_integer() else when
        row={'seconds':when,'kind':p[3],'supply_status':{1:'未切断',0:'已切断',-1:'未知'}[conn],
             'position':{'lat':float(p[5]),'lng':float(p[6])},'food_received':float(p[7]),'ammo_received':float(p[8]),
             'ammo_spent':float(p[9]),'received':{k:int(v) for k,v in received.items()},'spent':{k:int(v) for k,v in spent.items()}}
        units[scene['entities'][p[1]]['name']].append(row)
    ledger={'version':ss.receipt_version(before),'units':[{'unit':name,'events':rows} for name,rows in units.items()]}
    motion=None
    if continuous:
        from . import afsim_continuous_motion,afsim_motion_nutrition
        motion=afsim_continuous_motion.parse(text,model['continuous_motion'])
        segments=afsim_motion_nutrition.read_segments(text,model['continuous_motion'])
        for identity,e in scene['entities'].items():
            item=next(r for r in ledger['units'] if r['unit']==e['name'])
            item['nutrition_segments']=segments[identity]
            item['fuel_timeline']={k:copy.deepcopy(motion[identity]['fuel_timeline'][k]) for k in ('version','unit','events')}
    work_activity=None
    if model.get('continuous_motion',{}).get('work_support_revision'):
        work_cfg={c['entity_id']:c['configuration']for c in model['continuous_motion']['shared_fortification']['model']['controls']}
        work_activity={scene['entities'][identity]['name']:{'configuration':cfg,
            'intervals':motion[identity]['shared_fortification']['intervals']}for identity,cfg in work_cfg.items()}
    checked=ss.validate_ledger(before,ledger,model['orders'],scene['seconds'],
        **({'work_activity':work_activity}if work_activity else {}))
    return {'ledger':ledger,'checked':checked,**({'continuous_motion':motion} if continuous else {})}
