"""Compile Native motion and verify its receipts; never execute Python physics.

This component is tested independently while whole-world profile admission stays
closed. The same Native functions can be attached to the aggregate WSF model.
"""
import copy
import math
import re

from gentactix import missions, motion_state as state, movement_feedback, fire_process, sim_clock, suppression_state
from .afsim_literals import number

VERSION='afsim-continuous-motion-1'
STOP_RESERVE_M=movement_feedback.POSITION_TOLERANCE_KM*1000
STATUSES=('idle','waiting','moving','arrived','blocked')
INTEGER_FIELDS=('elapsed_ms','moving_ms','rest_ms','waiting_ms','blocked_ms','distance_micrometers',
                'fatigue_ticks','fuel_microliters','fuel_spent_microliters','mode',
                'wait_remaining_ms','feedback_remaining_ms','suppression_ticks')
REAL_FIELDS=('speed_mps','lat','lng')


def intent(unit,order,delay_ms):
    """Reuse command identity and unspent waiting; do not spend any time here."""
    if type(delay_ms) is not int or not 0<=delay_ms<=31*86400000:raise ValueError('通信等待毫秒非法')
    if order.get('action')!='move':
        return dict(version=state.TASK_VERSION,intent_id=None,target=None,status='idle',
            wait_remaining_ms=0,speed_mps=0,feedback_remaining_ms=0)
    target={k:order[k] for k in ('lat','lng')}
    identity=order.get('intent_id') or missions.digest([unit['name'],unit.get('calculation_unit_id'),
        unit.get('historical_unit_id'),target])[:32]
    previous=unit.get('formation',{}).get(state.TASK_FIELD)
    if previous:
        state.validate_task(previous)
        if previous['intent_id']==identity:
            if previous['target']!=target:raise ValueError('同一连续机动意图不能改写最终目标')
            return copy.deepcopy(previous)
    value=dict(version=state.TASK_VERSION,intent_id=identity,target=target,
        status='waiting' if delay_ms else 'moving',wait_remaining_ms=delay_ms,
        speed_mps=0,feedback_remaining_ms=0)
    state.validate_task(value)
    return value


def inputs(before,orders,entities):
    if not movement_feedback.continuous(before):raise ValueError('原生连续机动组件须显式绑定新版本')
    missions.validate(before)
    units={u['name']:u for _,u in missions.units(before)}
    if (not isinstance(entities,dict) or len(entities)!=len(units)
            or any(not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',k) for k in entities)
            or {v.get('name') for v in entities.values()}!=set(units)):
        raise ValueError('连续机动编译必须绑定全部唯一原生实体身份')
    spec=before['mission']['definition'];checked=missions.validate_orders(before,orders,spec['time_step'])
    cfg=spec['combined_rules'];result={}
    from gentactix import crossings,ferries
    if crossings.get_model(before) or ferries.config(before):
        raise ValueError('连续机动与共享渡运的组件交接尚未接通，不能套用直达运动')
    for identity,entity in entities.items():
        u=units[entity['name']];order=checked.get(u['name'],dict(unit=u['name'],action='hold'))
        f=u['formation'];task=intent(u,order,round(fire_process.delay_seconds(before,u)*1000))
        result[identity]=dict(name=u['name'],origin={k:u[k] for k in ('lat','lng')},
            target=copy.deepcopy(task['target'] or {k:u[k] for k in ('lat','lng')}),task=task,
            formation={k:f[k] for k in ('fatigue','fuel_liters',*state.FIELDS)},
            nominal_speed_mps=missions.move_budget(before,u,task['target'])*1000/sim_clock.duration_seconds(spec['time_step']),
            fuel_liters_per_km=(sum(e['operational']*{'armor':2,'transport':.1}.get(e['category'],0)
                for e in u['equipment']) if f.get('motorized',cfg['motorized']) else 0),
            fatigue_points_per_km=cfg['fatigue_move_gain'],rest_points_per_second=cfg['fatigue_rest_recovery']/1800,
            rest_enabled=order['action'] in ('hold','resupply','conceal'),
            strength=u['personnel']['current']/u['personnel']['committed'],
            suppression_ticks=suppression_state.load(u) if suppression_state.FIELD in f else round(f['suppression']*suppression_state.SCALE),
            suppression_decay=cfg['suppression_decay'])
        from . import afsim_motion_nutrition
        nutrition=afsim_motion_nutrition.inputs(before,u)
        if nutrition is not None:result[identity]['nutrition']=nutrition
    return result


def check_fuel(before,after,spent_microliters,*,received_microliters=0):
    state.validate_fuel_flow(before,after,received_microliters=received_microliters,
                             spent_microliters=spent_microliters)


def callbacks(*,timed=False):
    lines=[' script void GtxCMTick()', '  GtxCMStep(PLATFORM);', ' end_script',
            ' script void GtxCMArrived()',
            '  PLATFORM.ExecuteAtTime(TIME_NOW+0.000001,"GtxCMArrivalSettle");',' end_script',
            ' script void GtxCMArrivalSettle()', '  GtxCMSettle(PLATFORM);',
            '  PLATFORM.SetAuxData("cm_mode",3.0);',
            '  PLATFORM.SetAuxData("cm_speed",0.0);',' end_script']
    if timed:lines+=[' script void GtxCMWake()', '  GtxCMUpdate(PLATFORM,true,false);',' end_script']
    return lines


def support_functions(*,timed=False):
    """Share existing Native convoy charges and resupply credits in one stock."""
    code='''script void GtxCMConsumeSupportFuel(WsfPlatform a,double liters)
 GtxCMSettle(a);
 double cost=liters*1000000;
 if (liters<0 || Math.Floor(liters)!=liters || cost>GtxCMGet(a,"fuel")) {
  writeln("GTXERROR|continuous_support_fuel_budget"); return;
 }
 GtxCMPut(a,"fuel",GtxCMGet(a,"fuel")-cost);
 GtxCMPut(a,"support_spent",GtxCMGet(a,"support_spent")+cost);
 a.SetAuxData("ca_fuel_liters",Math.Floor(GtxCMGet(a,"fuel")/1000000));
end_script
script void GtxCMReceiveFuel(WsfPlatform a,double liters)
 GtxCMSettle(a);
 double credit=liters*1000000;
 if (liters<0 || Math.Floor(liters)!=liters || GtxCMGet(a,"fuel")+credit>10000000999999.0) {
  writeln("GTXERROR|continuous_received_fuel_budget"); return;
 }
 GtxCMPut(a,"fuel",GtxCMGet(a,"fuel")+credit);
 GtxCMPut(a,"received",GtxCMGet(a,"received")+credit);
 a.SetAuxData("ca_fuel_liters",Math.Floor(GtxCMGet(a,"fuel")/1000000));
end_script
'''
    if timed:code+='''script void GtxCMFuelEvent(WsfPlatform a,string kind)
 GtxCMSettle(a);
 double opening=GtxCMGet(a,"journal_opening");
 double received=GtxCMGet(a,"received")-GtxCMGet(a,"journal_received");
 double movement=GtxCMGet(a,"spent")-GtxCMGet(a,"journal_spent");
 double support=GtxCMGet(a,"support_spent")-GtxCMGet(a,"journal_support");
 double closing=GtxCMGet(a,"fuel");
 if (movement+support>opening || opening+received-movement-support!=closing) {
  writeln("GTXERROR|continuous_timed_fuel_balance");
 }
 writeln("GTXCMTIMEDFUEL|",a.AuxDataString("cm_fuel_identity"),"|",Format.Fixed(TIME_NOW,9),"|",kind,"|",Format.Fixed(opening,0),"|",Format.Fixed(received,0),"|",Format.Fixed(movement,0),"|",Format.Fixed(support,0),"|",Format.Fixed(closing,0));
 GtxCMPut(a,"journal_opening",closing); GtxCMPut(a,"journal_received",GtxCMGet(a,"received"));
 GtxCMPut(a,"journal_spent",GtxCMGet(a,"spent")); GtxCMPut(a,"journal_support",GtxCMGet(a,"support_spent"));
end_script
'''
    return code



WORK_SUPPORT_VERSION='native-work-support-1'
WORK_FIELDS=('start_ms','end_ms','fatigue_before_ticks','waited_ms','productive_ms',
    'idle_after_ms','wait_recovered_ticks','work_gained_ticks','idle_recovered_ticks','fatigue_after_ticks')


def _work_support_functions():
    return '''script void GtxCMWorkSupport(WsfPlatform a,double dt)
 if (a.AuxDataDouble("gfw_event_initialized")<1) { return; }
 double start=GtxCMGet(a,"last_ms"); double before=GtxCMGet(a,"fatigue");
 double waited=a.AuxDataDouble("gfw_waited_ms");
 double active=a.AuxDataDouble("gfw_productive_ms");
 double idle=Math.Max(0,dt-waited-active);
 if (waited+active>dt+0.000001 || GtxCMGet(a,"moving_order")>0 || GtxCMGet(a,"rest_enabled")>0) { writeln("GTXERROR|work_support_time_overlap"); return; }
 double pre=Math.Min(before,Math.Floor(waited*GtxCMGet(a,"rest_rate")*1000+0.5));
 double fatigue=before-pre;
 double gain=Math.Min(100000000-fatigue,Math.Floor(active*a.AuxDataDouble("gfw_fatigue_rate")*1000000/3600000+0.5));
 fatigue=fatigue+gain;
 double post=Math.Min(fatigue,Math.Floor(idle*GtxCMGet(a,"rest_rate")*1000+0.5));
 fatigue=fatigue-post;
 GtxCMPut(a,"fatigue",fatigue);
 a.SetAuxData("ca_fatigue",Math.Floor(fatigue/1000000));
 writeln("GTXCMWORK|",a.AuxDataString("gfw_event_identity"),"|",Format.Fixed(start,0),"|",Format.Fixed(start+dt,0),"|",Format.Fixed(before,0),"|",Format.Fixed(waited,0),"|",Format.Fixed(active,12),"|",Format.Fixed(idle,12),"|",Format.Fixed(pre,0),"|",Format.Fixed(gain,0),"|",Format.Fixed(post,0),"|",Format.Fixed(fatigue,0));
end_script
'''


def functions(*,nutrition=False,timed=False,shared_work=False):
    # All distances, time occupation, costs and speed feedback execute in WSF.
    code='''script double GtxCMGet(WsfPlatform a,string k)
 return a.AuxDataDouble("cm_"+k);
end_script
script void GtxCMPut(WsfPlatform a,string k,double v)
 a.SetAuxData("cm_"+k,v);
end_script
script void GtxCMSettle(WsfPlatform a)
 if (GtxCMGet(a,"initialized")<1) { return; }
 double ms=Math.Floor(TIME_NOW*1000+0.5);
 double dt=Math.Max(0,ms-GtxCMGet(a,"last_ms"));
 if (dt<=0) { return; }
 double mode=GtxCMGet(a,"mode");
 double lat=a.Latitude(); double lon=a.Longitude();
 if (mode==2) {
  WsfGeoPoint old=WsfGeoPoint.Construct(GtxCMGet(a,"lat"),GtxCMGet(a,"lng"),0);
  WsfGeoPoint current=WsfGeoPoint.Construct(lat,lon,0);
  double km=old.GroundRangeTo(current)/1000;
  double spent=Math.Floor(km*GtxCMGet(a,"fuel_rate")*1000000+0.5);
  if (spent>GtxCMGet(a,"fuel")) { writeln("GTXERROR|continuous_fuel_overdraw"); }
  GtxCMPut(a,"fuel",GtxCMGet(a,"fuel")-spent);
  GtxCMPut(a,"spent",GtxCMGet(a,"spent")+spent);
  GtxCMPut(a,"fatigue",Math.Min(100000000,GtxCMGet(a,"fatigue")+Math.Floor(km*GtxCMGet(a,"fatigue_gain")*1000000+0.5)));
  GtxCMPut(a,"distance",GtxCMGet(a,"distance")+km*1000000000);
  GtxCMPut(a,"moving_ms",GtxCMGet(a,"moving_ms")+dt);
  if (GtxCMGet(a,"fuel_rate")>0 && GtxCMGet(a,"fuel")<=GtxCMGet(a,"fuel_rate")*1000*GtxCMGet(a,"stop_reserve_m")) {
   GtxCMPut(a,"mode",4.0); GtxCMPut(a,"speed",0.0);
   a.GoToSpeed(0.0,1000000.0,true);
  }
 } else if (mode==1) { GtxCMPut(a,"waiting_ms",GtxCMGet(a,"waiting_ms")+dt); }
 else if (mode==3 || mode==4 || (mode==0 && GtxCMGet(a,"rest_enabled")>0)) {
  GtxCMPut(a,"fatigue",Math.Max(0,GtxCMGet(a,"fatigue")-Math.Floor(dt*GtxCMGet(a,"rest_rate")*1000+0.5)));
  GtxCMPut(a,"rest_ms",GtxCMGet(a,"rest_ms")+dt);
 } else { GtxCMPut(a,"blocked_ms",GtxCMGet(a,"blocked_ms")+dt); }
 GtxCMPut(a,"lat",lat); GtxCMPut(a,"lng",lon); GtxCMPut(a,"last_ms",ms);
 GtxSuppressionDecay(a,TIME_NOW);
 a.SetAuxData("ca_fatigue",Math.Floor(GtxCMGet(a,"fatigue")/1000000));
 a.SetAuxData("ca_fuel_liters",Math.Floor(GtxCMGet(a,"fuel")/1000000));
end_script
script void GtxCMStep(WsfPlatform a)
 if (GtxCMGet(a,"initialized")<1) { return; }
 GtxCMSettle(a);
 double now=TIME_NOW; double due=GtxCMGet(a,"due");
 double mode=GtxCMGet(a,"mode"); double speed=GtxCMGet(a,"speed");
 bool refresh=now+0.000000001>=due;
 if (refresh) { due=due+10; GtxCMPut(a,"due",due); }
 if (GtxCMGet(a,"moving_order")<1) { mode=0; speed=0; }
 else if (now<GtxCMGet(a,"ready")) { mode=1; speed=0; }
 else if (GtxCMGet(a,"goal_met")>0) { mode=3; speed=0; }
 else if (mode!=3 && (refresh || mode==1)) {
  double factor=Math.Max(0,Math.Min(a.AuxDataDouble("ca_live_strength_ratio"),1-GtxCMGet(a,"fatigue")/200000000-a.AuxDataDouble("ca_suppression")/250));
  speed=GtxCMGet(a,"nominal")*factor;
  if (GtxCMGet(a,"fuel_rate")>0) {
   double available=Math.Max(0,GtxCMGet(a,"fuel")/1000000/GtxCMGet(a,"fuel_rate")*1000-GtxCMGet(a,"stop_reserve_m"));
   speed=Math.Min(speed,available/Math.Max(0.001,due-now));
   if (available<=0) { speed=0; }
  }
  mode=2; if (speed<=0) { mode=4; }
 }
 if (mode==3) { speed=0; }
 GtxCMPut(a,"mode",mode); GtxCMPut(a,"speed",speed);
 if (GtxCMGet(a,"mover_required")>0 && mode!=3) {
  if (!a.GoToSpeed(speed,1000000.0,true)) { writeln("GTXERROR|continuous_speed_control"); }
 }
 double next=due;
 if (mode==1) { next=Math.Min(next,GtxCMGet(a,"ready")); }
 if (next<=GtxCMGet(a,"end") && next>now) { a.ExecuteAtTime(next,"GtxCMTick"); }
end_script
'''
    if shared_work:
        code=code.replace('script void GtxCMSettle(WsfPlatform a)',_work_support_functions()+'script void GtxCMSettle(WsfPlatform a)',1)
        code=code.replace(' double mode=GtxCMGet(a,"mode");',
            ' GtxSharedFortificationSettle(a);\n GtxCMWorkSupport(a,dt);\n double mode=GtxCMGet(a,"mode");',1)
    if nutrition:
        code=code.replace('  GtxCMPut(a,"fatigue",Math.Min(100000000,GtxCMGet(a,"fatigue")+Math.Floor(km*GtxCMGet(a,"fatigue_gain")*1000000+0.5)));',
            '  double gained=Math.Min(100000000-GtxCMGet(a,"fatigue"),Math.Floor(km*GtxCMGet(a,"fatigue_gain")*1000000+0.5));\n'
            '  GtxCMPut(a,"fatigue",GtxCMGet(a,"fatigue")+gained); GtxCMPut(a,"fatigue_gained",GtxCMGet(a,"fatigue_gained")+gained);')
        code=code.replace('  GtxCMPut(a,"fatigue",Math.Max(0,GtxCMGet(a,"fatigue")-Math.Floor(dt*GtxCMGet(a,"rest_rate")*1000+0.5)));',
            '  double restored=Math.Min(GtxCMGet(a,"fatigue"),Math.Floor(dt*GtxCMGet(a,"rest_rate")*1000+0.5));\n'
            '  GtxCMPut(a,"fatigue",GtxCMGet(a,"fatigue")-restored); GtxCMPut(a,"fatigue_restored",GtxCMGet(a,"fatigue_restored")+restored);')
        code=code.replace(' GtxCMPut(a,"lat",lat);',' GtxCMNourish(a,dt,mode==2);\n GtxCMPut(a,"lat",lat);')
    if timed:
        code=code.replace('script void GtxCMStep(WsfPlatform a)',
                          'script void GtxCMUpdate(WsfPlatform a,bool force,bool schedule)')
        code=code.replace('(refresh || mode==1)', '(force || refresh || mode==1)')
        code=code.replace('if (next<=GtxCMGet(a,"end") && next>now)',
                          'if (schedule && next<=GtxCMGet(a,"end") && next>now)')
        code+='''script void GtxCMStep(WsfPlatform a)
 GtxCMUpdate(a,false,true);
end_script
'''
    return code


def compile_process(controls,seconds,*,shared=False,fuel_event_times=None,shared_work_controls=None):
    """A reusable Native section; caller supplies normal mover platforms."""
    probe=type(seconds) is float and seconds==.001
    if not probe and (type(seconds) is not int or not 0<seconds<=31*86400):raise ValueError('连续机动组件时长非法')
    if not isinstance(controls,dict) or not controls:raise ValueError('连续机动缺少编译输入')
    for c in controls.values():
        for k in ['nominal_speed_mps','fuel_liters_per_km','fatigue_points_per_km','rest_points_per_second','suppression_decay','strength']:
            v=c.get(k)
            if type(v) not in (int,float) or not math.isfinite(v) or v<0 or (k=='strength' and v>1):
                raise ValueError('连续机动物理参数须为明确有限非负数：'+k)
        if type(c.get('rest_enabled')) is not bool:raise ValueError('连续机动休整标记非法')
        ticks=c.get('suppression_ticks')
        if type(ticks) is not int or not 0<=ticks<=100*suppression_state.SCALE:raise ValueError('连续机动压制载荷非法')
        for field in ['origin','target']:
            p=c[field]
            if (not isinstance(p,dict) or set(p)!={'lat','lng'} or any(type(p[k]) not in (int,float)
                or not math.isfinite(p[k]) or abs(p[k])>limit for k,limit in [('lat',90),('lng',180)])):
                raise ValueError('连续机动组件坐标非法')
    rates={r['suppression_decay'] for r in controls.values()}
    if len(rates)!=1:raise ValueError('同场连续机动须使用同一已冻结压制衰减')
    from . import afsim_suppression
    from . import afsim_motion_nutrition
    from gentactix import timed_fuel
    timed=fuel_event_times is not None
    if timed:
        if not shared:raise ValueError('定时燃油须绑定共享库存与总账')
        fuel_event_times=timed_fuel.validate_times(fuel_event_times,seconds)
    nourishment=all('nutrition' in c for c in controls.values())
    if any('nutrition' in c for c in controls.values()) and (not nourishment or not shared):
        raise ValueError('分时营养须完整绑定共享聚合实体')
    load_probe=probe and nourishment and any(c['nutrition']['deferred'] for c in controls.values())
    work=None
    if shared_work_controls is not None:
        from . import afsim_shared_fortification
        if not shared or probe or not isinstance(shared_work_controls,list)or not shared_work_controls:
            raise ValueError('事件施工必须绑定正常时长的共享聚合世界')
        if not nourishment:raise ValueError('施工劳动必须同时绑定现有分时营养')
        ids={c['entity_id']for c in shared_work_controls}
        if not ids<=set(controls)or any(controls[i]['task']['intent_id']is not None or controls[i]['rest_enabled']for i in ids):
            raise ValueError('固定地点施工不能同时携带机动意图或未知实体')
        work=afsim_shared_fortification.compile_events(shared_work_controls,round(seconds*1000),
            {i:controls[i]['origin']for i in ids})
    token=missions.digest(dict(version=VERSION,controls=controls,seconds=seconds,cadence_ms=state.CADENCE_MS,
                              stop_reserve_m=STOP_RESERVE_M,**({'shared':True,'fuel_receipt_revision':2} if shared else {}),
                              **({'nutrition_revision':afsim_motion_nutrition.VERSION} if nourishment else {}),
                              **({'nutrition_load_probe':True} if load_probe else {}),
                              **({'nutrition_schedule_revision':afsim_motion_nutrition.SCHEDULE_VERSION} if nourishment and timed else {}),
                              **({'timed_fuel_revision':timed_fuel.VERSION,'fuel_event_times':fuel_event_times} if timed else {}),
                              **({'shared_fortification_digest':work['model']['binding_digest'],'work_support_revision':WORK_SUPPORT_VERSION}if work else {})))
    native_functions=(work['functions']if work else '')+(afsim_motion_nutrition.functions(load_probe=load_probe,work=work is not None) if nourishment else '')+functions(nutrition=nourishment,timed=timed,shared_work=work is not None)
    native_functions=native_functions+support_functions(timed=timed) if shared else afsim_suppression.functions(next(iter(rates)))+'\n'+native_functions
    if nourishment and timed:native_functions+=afsim_motion_nutrition.delivery_functions()
    text=[]
    for i,(identity,c) in enumerate(controls.items()):
        if re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',identity) is None:raise ValueError('原生实体标识非法')
        state.validate_unit({'formation':c['formation']});state.validate_task(c['task'])
        p='cm'+str(i);task=c['task'];moving=task['intent_id'] is not None
        values=dict(initialized=1,last_ms=0,lat=c['origin']['lat'],lng=c['origin']['lng'],
            moving_order=int(moving),mode=STATUSES.index(task['status']),speed=task['speed_mps'],
            goal_met=int(task['status']=='arrived'),mover_required=int(moving and task['status']!='arrived'),
            ready=task['wait_remaining_ms']/1000,due=task['feedback_remaining_ms']/1000,end=seconds,
            nominal=c['nominal_speed_mps'],fuel_rate=c['fuel_liters_per_km'],fatigue_gain=c['fatigue_points_per_km'],
            stop_reserve_m=STOP_RESERVE_M,
            rest_rate=c['rest_points_per_second'],rest_enabled=int(c['rest_enabled']),
            fatigue=state.fatigue_load({'formation':c['formation']}),fuel=state.fuel_load({'formation':c['formation']}),
            moving_ms=0,rest_ms=0,waiting_ms=0,blocked_ms=0,distance=0,spent=0)
        if shared:values.update(support_spent=0,received=0)
        if timed:values.update(journal_opening=state.fuel_load({'formation':c['formation']}),
                               journal_received=0,journal_spent=0,journal_support=0)
        if nourishment:values.update(fatigue_gained=0,fatigue_restored=0)
        text.append(f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");')
        for key,value in values.items():
            text.append(f' GtxCMPut({p},"{key}",{number(value)}.0);' if type(value) is int
                        else f' GtxCMPut({p},"{key}",{number(value)});')
        if not shared:
            text += [f' {p}.SetAuxData("ca_suppression_ticks",{c["suppression_ticks"]}.0);',
                     f' {p}.SetAuxData("ca_suppression_sample_ms",0.0);',
                     f' {p}.SetAuxData("ca_live_strength_ratio",{number(c["strength"])});']
        if moving:
            target=c['target']
            goal=f'WsfGeoPoint.Construct({number(target["lat"])},{number(target["lng"])},0)'
            text.append(f' WsfGeoPoint goal{i}={goal}; WsfGeoPoint origin{i}=WsfGeoPoint.Construct({p}.Latitude(),{p}.Longitude(),0);')
            if task['status']=='arrived':
                text.append(f' if (origin{i}.GroundRangeTo(goal{i})>1) {{ writeln("GTXERROR|continuous_arrival_origin"); }}')
            else:
                text += [f' if (origin{i}.GroundRangeTo(goal{i})<={number(STOP_RESERVE_M)}) {{ GtxCMPut({p},"goal_met",1.0); GtxCMPut({p},"mover_required",0.0); }}',
                    f' else if (!{p}.GoToPoint(goal{i},"GtxCMArrived")) {{ writeln("GTXERROR|continuous_target"); }}']
        if nourishment:text+=afsim_motion_nutrition.setup(p,identity,c['nutrition'],scheduled=timed)
        if timed:text.append(f' {p}.SetAuxData("cm_fuel_identity","{identity}");')
        text.append(f' GtxCMStep({p});')
    work_setup=[]
    if work:
        for index,c in enumerate(shared_work_controls):
            p='cw'+str(index)
            work_setup+=[' {',f' WsfPlatform {p}=WsfSimulation.FindPlatform("{c["entity_id"]}");',
                f' GtxSFWPut({p},"fatigue_rate",{number(c["configuration"]["fatigue_per_work_hour"])});',
                f' GtxSFWPut({p},"food_factor",{number(c["configuration"]["activity_food_factor"])});',' }']
    setup_lines=(work['setup_lines']if work else [])+work_setup+text
    text=[f' writeln("GTXCMODEL|{token}");']
    for i,(identity,c) in enumerate(controls.items()):
        p='cm'+str(i);text += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");',f' GtxCMSettle({p});']
        values=[f'{round(seconds*1000)}.0',*[f'GtxCMGet({p},"{k}")' for k in ['moving_ms','rest_ms','waiting_ms','blocked_ms']],
            f'Math.Floor(GtxCMGet({p},"distance")+0.5)',f'GtxCMGet({p},"fatigue")',f'GtxCMGet({p},"fuel")',
            f'GtxCMGet({p},"spent")',f'GtxCMGet({p},"mode")',
            f'Math.Max(0,Math.Floor((GtxCMGet({p},"ready")-TIME_NOW)*1000+0.5))',
            f'Math.Max(0,Math.Floor((GtxCMGet({p},"due")-TIME_NOW)*1000+0.5))',
            f'{p}.AuxDataDouble("ca_suppression_ticks")']
        values=[f'Format.Fixed({v},0)' for v in values]+[f'Format.Fixed({v},12)' for v in
            [f'GtxCMGet({p},"speed")',f'{p}.Latitude()',f'{p}.Longitude()']]
        text.append(f' writeln("GTXCMOTION|{identity}|",'+',"|",'.join(values)+');')
        text.append(f' writeln("GTXCMKINEMATIC|{identity}|",Format.Fixed({p}.GroundSpeed(),12));')
        if shared:text.append(f' writeln("GTXCMSUPPORT|{identity}|",Format.Fixed(GtxCMGet({p},"support_spent"),0));')
        if shared:text.append(f' writeln("GTXCMRECEIVED|{identity}|",Format.Fixed(GtxCMGet({p},"received"),0));')
        if nourishment:text.append(f' writeln("GTXCMFATIGUE|{identity}|",Format.Fixed(GtxCMGet({p},"fatigue_gained"),0),"|",Format.Fixed(GtxCMGet({p},"fatigue_restored"),0),"|",Format.Fixed(GtxCNGet({p},"floor_gain"),0));')
        if timed:text.append(f' GtxCMFuelEvent({p},"settlement");')
    receipt_lines=text+(work['receipt_lines']if work else [])
    text=[native_functions,'execute at_time 0.000001 sec absolute',*setup_lines,
          'end_execute',f'execute at_time {seconds} sec absolute',*receipt_lines,'end_execute']
    return {'version':VERSION,'token':token,'controls':copy.deepcopy(controls),'seconds':seconds,
            'script':'\n'.join(text)+'\n','functions':native_functions,
            'setup_lines':setup_lines,'receipt_lines':receipt_lines,**({'shared':True,'fuel_receipt_revision':2} if shared else {}),
            **({'nutrition_revision':afsim_motion_nutrition.VERSION} if nourishment else {}),
            **({'nutrition_load_probe':True} if load_probe else {}),
            **({'nutrition_schedule_revision':afsim_motion_nutrition.SCHEDULE_VERSION} if nourishment and timed else {}),
            **({'timed_fuel_revision':timed_fuel.VERSION,'fuel_event_times':fuel_event_times} if timed else {}),
            **({'shared_fortification':work,'work_support_revision':WORK_SUPPORT_VERSION}if work else {})}



def check_work_support(text,model,work_rows):
    """Read-only work/rest fatigue accounting, bound to paid Native intervals."""
    from . import afsim_motion_nutrition
    expected_ids={c['entity_id']for c in model['shared_fortification']['model']['controls']}
    if model.get('work_support_revision')!=WORK_SUPPORT_VERSION or set(work_rows)!=expected_ids:
        raise ValueError('劳动保障回执版本或实体集合不一致')
    cfgs={c['entity_id']:c['configuration']for c in model['shared_fortification']['model']['controls']}
    logs={i:[]for i in expected_ids};cn=afsim_motion_nutrition.read_segments(text,model)
    for line in text.splitlines():
        if not line.startswith('GTXCMWORK|'):continue
        p=line.split('|')
        if len(p)!=len(WORK_FIELDS)+2 or p[1]not in logs:raise ValueError('劳动疲劳回执实体或字段非法')
        try:row={k:float(v)if k in ('productive_ms','idle_after_ms')else int(v)for k,v in zip(WORK_FIELDS,p[2:])}
        except ValueError as exc:raise ValueError('劳动疲劳回执数量非法')from exc
        if any(not math.isfinite(v)or v<0 for v in row.values()):raise ValueError('劳动疲劳回执数量超出范围')
        logs[p[1]].append(row)
    result={}
    for identity,items in logs.items():
        controls=model['controls'][identity];cfg=cfgs[identity];intervals=work_rows[identity]['intervals'];nutrition=cn[identity]
        if len(items)!=len(intervals)or len(items)!=len(nutrition):raise ValueError('劳动、疲劳与口粮时段不完整')
        fatigue=state.fatigue_load({'formation':controls['formation']})
        total=dict(work_gained_ticks=0,work_rest_recovered_ticks=0,productive_ms=0.0,work_idle_ms=0.0)
        rate=controls['rest_points_per_second']*1000
        for r,w,n in zip(items,intervals,nutrition):
            start=w['start_ms'];stop=w['end_ms'];receipt=w['receipt'];active=receipt['productive_ms'];waited=receipt['waited_ms'];idle=max(0,stop-start-waited-active)
            if (r['start_ms']!=start or r['end_ms']!=stop or n['start_ms']!=start or n['end_ms']!=stop
                    or n['people']!=w['current']or r['fatigue_before_ticks']!=fatigue or r['waited_ms']!=waited
                    or abs(r['productive_ms']-active)>.000001 or abs(r['idle_after_ms']-idle)>.000001):
                raise ValueError('劳动疲劳未绑定实际施工与营养时段')
            pre=min(fatigue,math.floor(waited*rate+.5));middle=fatigue-pre
            gain=min(100*state.SCALE-middle,math.floor(active*cfg['fatigue_per_work_hour']*state.SCALE/3600000+.5))
            middle+=gain;post=min(middle,math.floor(idle*rate+.5));closing=middle-post
            if (r['wait_recovered_ticks']!=pre or r['work_gained_ticks']!=gain
                    or r['idle_recovered_ticks']!=post or r['fatigue_after_ticks']!=closing):
                raise ValueError('等待休整、实际劳动或停工休整的疲劳账不一致')
            floor=n['fatigue_floor_gain_ticks']
            if floor<0 or floor!=int(floor)or closing+floor>100*state.SCALE:raise ValueError('劳动疲劳与缺粮下限不一致')
            fatigue=closing+int(floor)
            total['work_gained_ticks']+=gain;total['work_rest_recovered_ticks']+=pre+post
            total['productive_ms']+=active;total['work_idle_ms']+=waited+idle
        total['fatigue_after_ticks']=fatigue;total['interval_count']=len(items);result[identity]=total
    return result


def parse(text,model,*,shared_work_material_events=None):
    if not model.get('shared_fortification')and any(line.startswith(('GTXSFWSEG|','GTXSFWEND|','GTXSFWEVENTMETA|'))for line in text.splitlines()):
        raise ValueError('共享施工事件回执没有绑定对应模型版本')
    tokens=[line for line in text.splitlines() if line.startswith('GTXCMODEL|')]
    if tokens!=['GTXCMODEL|'+model['token']]:raise ValueError('连续机动编译输入回执不一致')
    if any(line.startswith('GTXERROR|') for line in text.splitlines()):raise ValueError('连续机动原生过程报告错误，不能接收候选')
    work_rows={};work_flows={}
    if model.get('shared_fortification'):
        from . import afsim_shared_fortification
        work_rows=afsim_shared_fortification.parse_events(text,model['shared_fortification']['model'],material_events=shared_work_material_events)
    if model.get('work_support_revision'):
        work_flows=check_work_support(text,model,work_rows)
    elif any(line.startswith('GTXCMWORK|')for line in text.splitlines()):
        raise ValueError('劳动疲劳回执没有绑定对应模型版本')
    fatigue_flows={}
    for line in text.splitlines():
        if not line.startswith('GTXCMFATIGUE|'):continue
        p=line.split('|')
        if not model.get('nutrition_revision') or len(p)!=5 or p[1] not in model['controls'] or p[1] in fatigue_flows:
            raise ValueError('分时疲劳收支回执非法')
        values=list(map(int,p[2:]))
        if any(v<0 for v in values):raise ValueError('分时疲劳收支须为非负整数微点')
        fatigue_flows[p[1]]=dict(zip(('movement_gained_ticks','rest_recovered_ticks','food_floor_gained_ticks'),values))
    if model.get('nutrition_revision') and set(fatigue_flows)!=set(model['controls']):
        raise ValueError('分时疲劳回执未覆盖全部实体')
    support={}
    for line in text.splitlines():
        if not line.startswith('GTXCMSUPPORT|'):continue
        p=line.split('|')
        if not model.get('shared') or len(p)!=3 or p[1] not in model['controls'] or p[1] in support:
            raise ValueError('连续机动保障燃油回执版本、身份或数量非法')
        try:value=int(p[2])
        except ValueError as exc:raise ValueError('连续机动保障燃油须为整数微升') from exc
        if value<0 or value%state.SCALE:raise ValueError('现有车队耗油须为非负整升的微升载荷')
        support[p[1]]=value
    if model.get('shared') and set(support)!=set(model['controls']):
        raise ValueError('连续机动保障燃油回执不完整')
    revision=model.get('fuel_receipt_revision',1)
    if type(revision) is not int or revision not in (1,2) or revision==2 and not model.get('shared'):
        raise ValueError('连续机动到货计量回执版本非法')
    received={}
    for line in text.splitlines():
        if not line.startswith('GTXCMRECEIVED|'):continue
        p=line.split('|')
        if revision!=2 or len(p)!=3 or p[1] not in model['controls'] or p[1] in received:
            raise ValueError('连续机动到货燃油回执版本、身份或数量非法')
        try:value=int(p[2])
        except ValueError as exc:raise ValueError('连续机动到货燃油须为整数微升') from exc
        if value<0 or value%state.SCALE:raise ValueError('现有整升补给须为非负整升的微升载荷')
        received[p[1]]=value
    if revision==2 and set(received)!=set(model['controls']):
        raise ValueError('连续机动到货燃油回执不完整')
    from gentactix import timed_fuel
    timed=model.get('timed_fuel_revision')
    if timed is not None and (timed!=timed_fuel.VERSION or revision!=2):
        raise ValueError('定时燃油回执版本须绑定共享微升库存')
    fuel_events={identity:[] for identity in model['controls']}
    for line in text.splitlines():
        if not line.startswith('GTXCMTIMEDFUEL|'):continue
        p=line.split('|')
        if not timed or len(p)!=9 or p[1] not in fuel_events:
            raise ValueError('定时燃油原生回执身份或字段非法')
        try:
            row=dict(seconds=float(p[2]),kind=p[3],**dict(zip(timed_fuel.FIELDS,map(int,p[4:]))))
        except (ValueError,OverflowError) as exc:raise ValueError('定时燃油原生数量格式非法') from exc
        if row['received_microliters']%state.SCALE:
            raise ValueError('当前原生定时到货必须保持整升补给的微升载荷')
        fuel_events[p[1]].append(row)
    velocities={}
    for line in text.splitlines():
        if not line.startswith('GTXCMKINEMATIC|'):continue
        p=line.split('|')
        if len(p)!=3 or p[1] not in model['controls'] or p[1] in velocities:raise ValueError('连续机动原生速度回执缺项或身份非法')
        try:v=float(p[2])
        except ValueError as exc:raise ValueError('连续机动原生速度格式非法') from exc
        if not math.isfinite(v) or not 0<=v<=10000:raise ValueError('连续机动原生速度越界')
        velocities[p[1]]=v
    if set(velocities)!=set(model['controls']):raise ValueError('连续机动缺少完整原生速度回执')
    rows={};fields=(*INTEGER_FIELDS,*REAL_FIELDS)
    for line in text.splitlines():
        if not line.startswith('GTXCMOTION|'):continue
        p=line.split('|')
        if len(p)!=len(fields)+2 or p[1] not in model['controls'] or p[1] in rows:
            raise ValueError('连续机动回执缺项、重复或身份非法')
        try:r=dict(zip(fields,[*map(int,p[2:2+len(INTEGER_FIELDS)]),*map(float,p[2+len(INTEGER_FIELDS):])]))
        except (ValueError,OverflowError) as exc:raise ValueError('连续机动回执数量格式非法') from exc
        if any(not math.isfinite(v) or v<0 for k,v in r.items() if k not in ('lat','lng')):
            raise ValueError('连续机动回执须为有限非负数')
        if (r['elapsed_ms']!=model['seconds']*1000 or sum(r[k] for k in ['moving_ms','rest_ms','waiting_ms','blocked_ms'])!=r['elapsed_ms']
                or not 0<=r['mode']<len(STATUSES) or abs(r['lat'])>90 or abs(r['lng'])>180):
            raise ValueError('连续机动时长分类、状态或位置不一致')
        if not math.isfinite(r['lat']) or not math.isfinite(r['lng']):raise ValueError('连续机动位置不是有限数')
        c=model['controls'][p[1]];task=copy.deepcopy(c['task'])
        task.update(status=STATUSES[r['mode']],wait_remaining_ms=r['wait_remaining_ms'],
                    speed_mps=velocities[p[1]] if STATUSES[r['mode']]=='moving' else 0,
                    feedback_remaining_ms=r['feedback_remaining_ms'])
        r['actual_speed_mps']=velocities[p[1]]
        state.validate_task(task)
        fatigue,carry=divmod(r['fatigue_ticks'],state.SCALE);fuel,credit=divmod(r['fuel_microliters'],state.SCALE)
        formation=dict(fatigue=fatigue,fatigue_carry_ticks=carry,fuel_liters=fuel,
            fuel_credit_microliters=credit,motion_task=task)
        other=support.get(p[1],0)
        arrival=received.get(p[1],0)
        check_fuel({'formation':c['formation']},{'formation':formation},r['fuel_spent_microliters']+other,
                   received_microliters=arrival)
        if model.get('shared'):r['support_fuel_spent_microliters']=other
        if revision==2:r['fuel_received_microliters']=arrival
        if timed:
            timeline=timed_fuel.validate(state.fuel_load({'formation':c['formation']}),
                {'version':timed,'unit':'microliter','events':fuel_events[p[1]]},model['fuel_event_times'])
            for key,wanted in [('closing_microliters',r['fuel_microliters']),('received_microliters',arrival),
                               ('movement_spent_microliters',r['fuel_spent_microliters']),('support_spent_microliters',other)]:
                if timeline[key]!=wanted:raise ValueError('定时燃油与累计物理回执不一致：'+key)
            r['fuel_timeline']=timeline
        # Each nonzero Native settlement rounds at most half one micro unit.
        # The bound is derived from cadence + wake/arrival/endpoint, not fitted
        # to a result. This checker never fills or rounds proposed state.
        extra_settlements=sum(kind=='delivery' for _,kind in model['fuel_event_times']) if timed else 0
        quantization=(math.ceil(model['seconds']*1000/state.CADENCE_MS)+4+extra_settlements)/2+1
        km=r['distance_micrometers']/1e9
        if abs(r['fuel_spent_microliters']-km*c['fuel_liters_per_km']*state.SCALE)>quantization+1:
            raise ValueError('实际路程与燃油微升消耗不一致')
        if model.get('nutrition_revision'):
            flow=copy.deepcopy(fatigue_flows[p[1]])
            if p[1]in work_flows:
                flow.update({k:work_flows[p[1]][k]for k in ('work_gained_ticks','work_rest_recovered_ticks')})
                r['work_support']=copy.deepcopy(work_flows[p[1]])
            expected=state.fatigue_load({'formation':c['formation']})+flow['movement_gained_ticks']+flow['food_floor_gained_ticks']-flow['rest_recovered_ticks']+flow.get('work_gained_ticks',0)-flow.get('work_rest_recovered_ticks',0)
            if r['fatigue_ticks']!=expected:raise ValueError('分时疲劳微点收支不守恒')
            if (flow['movement_gained_ticks']>km*c['fatigue_points_per_km']*state.SCALE+quantization+1
                    or flow['rest_recovered_ticks']>r['rest_ms']*c['rest_points_per_second']*1000+quantization+1):
                raise ValueError('疲劳增减超过实际机动与休整上界')
            r['fatigue_flow']=flow
        else:
            expected=max(0,min(100*state.SCALE,state.fatigue_load({'formation':c['formation']})
                +km*c['fatigue_points_per_km']*state.SCALE)-r['rest_ms']*c['rest_points_per_second']*1000)
            if abs(r['fatigue_ticks']-expected)>quantization+1:
                raise ValueError('实际行军及休整时段与疲劳余量不一致')
        max_speed=max(c['nominal_speed_mps'],c['task']['speed_mps'])
        if km*1000>max_speed*r['moving_ms']/1000+.001:
            raise ValueError('原生行军路程超过实际运动时间与速度上界')
        if r['wait_remaining_ms']!=max(0,c['task']['wait_remaining_ms']-r['elapsed_ms']):
            raise ValueError('连续机动通信等待重复或丢失')
        r.update(formation=formation);rows[p[1]]=r
    if set(rows)!=set(model['controls']):raise ValueError('连续机动回执未覆盖全部实体')
    if model.get('shared_fortification'):
        from . import afsim_shared_fortification
        for identity,row in work_rows.items():rows[identity]['shared_fortification']=row
    elif shared_work_material_events is not None:
        raise ValueError('未绑定事件施工，不能提交施工材料到货')
    return rows
