"""Compile native crossing arrival/queue callbacks and validate their receipts."""
import copy
from gentactix import crossings,missions
from .afsim_literals import number as literal


def model(world):return crossings.get_model(world)


def callbacks():
    return [' script void GtxCrossService()', '  GtxCrossRequest(PLATFORM);', ' end_script',
            ' script void GtxCrossEnter()',
            '  if (!PLATFORM.ExecuteAtTime(TIME_NOW+0.000001,"GtxCrossService")) { writeln("GTXERROR|crossing_service_schedule"); }', ' end_script',
            ' script void GtxCrossExit()', '  GtxCrossLeave(PLATFORM);', ' end_script']


def functions(scene,world):
    m=model(world);end=scene['seconds']
    a,b=({k:literal(v) for k,v in m['barrier'][side].items()} for side in ('a','b'))
    script=f'''
script bool GtxCrosses(double la,double lo,double lb,double lp)
 double x=({b['lng']}-{a['lng']})*(la-{a['lat']})-({b['lat']}-{a['lat']})*(lo-{a['lng']});
 double y=({b['lng']}-{a['lng']})*(lb-{a['lat']})-({b['lat']}-{a['lat']})*(lp-{a['lng']});
 double u=(lp-lo)*({a['lat']}-la)-(lb-la)*({a['lng']}-lo);
 double v=(lp-lo)*({b['lat']}-la)-(lb-la)*({b['lng']}-lo);
 return x*y<=0 && u*v<=0 && (x-y)*(x-y)>0.000000000000000000000001 && (u-v)*(u-v)>0.000000000000000000000001;
end_script
script void GtxCrossEvent(WsfPlatform actor,string phase)
 writeln("GTXCROSSEVENT|",actor.Name(),"|",phase,"|",(int)(TIME_NOW*1000),"|",(int)actor.Latitude(),"|",(int)((actor.Latitude()-(int)actor.Latitude())*100000000),"|",(int)actor.Longitude(),"|",(int)((actor.Longitude()-(int)actor.Longitude())*100000000));
end_script
script void GtxCrossRequest(WsfPlatform actor)
 if (actor.AuxDataDouble("ca_cross_entered")>0) {{ return; }}
 actor.SetAuxData("ca_cross_entered",1.0);
 GtxCrossEvent(actor,"entered");
 WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub");
 actor.SetAuxData("ca_cross_stage",1.0);
 if (hub.AuxDataDouble("ca_progress")<100 || hub.AuxDataDouble("ca_integrity")<50) {{
  actor.SetAuxData("ca_blocked",1.0); actor.Pause({end}+1); return;
 }}
 double start=Math.Max(Math.Max(TIME_NOW,actor.AuxDataDouble("ca_cross_ready_s")),hub.AuxDataDouble("ca_cross_busy_until"));
 double remaining=Math.Max(0,actor.AuxDataDouble("ca_cross_required")-actor.AuxDataDouble("ca_cross_done"));
 double rate={literal(m['throughput_work_per_hour']/3600,precision=12)};
 double finish=start+remaining/rate;
 double grant=Math.Max(0,Math.Min(remaining,({end}-start)*rate));
 actor.SetAuxData("ca_cross_done",Math.Min(actor.AuxDataDouble("ca_cross_required"),actor.AuxDataDouble("ca_cross_done")+grant));
 actor.SetAuxData("ca_cross_work",grant);
 hub.SetAuxData("ca_cross_work",hub.AuxDataDouble("ca_cross_work")+grant);
 hub.SetAuxData("ca_cross_busy_until",Math.Max(hub.AuxDataDouble("ca_cross_busy_until"),Math.Min({end},finish)));
 if (finish>{end}+0.000001) {{ actor.SetAuxData("ca_blocked",2.0); actor.Pause({end}+1); }}
 else {{ actor.SetAuxData("ca_cross_stage",2.0); actor.Pause(Math.Max(TIME_NOW+0.000001,finish)); }}
end_script
script void GtxCrossLeave(WsfPlatform actor)
 if (actor.AuxDataDouble("ca_cross_done")+0.000001<actor.AuxDataDouble("ca_cross_required")) {{ writeln("GTXERROR|crossing_without_service"); return; }}
 if (actor.AuxDataDouble("ca_cross_left")>0) {{ return; }}
 actor.SetAuxData("ca_cross_left",1.0); actor.SetAuxData("ca_cross_stage",3.0);
 WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub");hub.SetAuxData("ca_used",hub.AuxDataDouble("ca_used")+1);
 GtxCrossEvent(actor,"exited");
end_script
script double GtxCrossDistance(WsfPlatform actor,double la,double lo,double ea,double eo,double xa,double xo,bool enterRequired)
 if (!enterRequired) {{
  if (actor.AuxDataDouble("ca_cross_left")>0) {{ return GtxDistance(la,lo,xa,xo)+GtxDistance(xa,xo,actor.Latitude(),actor.Longitude()); }}
  return GtxDistance(la,lo,actor.Latitude(),actor.Longitude());
 }}
 if (actor.AuxDataDouble("ca_cross_left")>0) {{ return GtxDistance(la,lo,ea,eo)+GtxDistance(ea,eo,xa,xo)+GtxDistance(xa,xo,actor.Latitude(),actor.Longitude()); }}
 if (actor.AuxDataDouble("ca_cross_entered")>0) {{ return GtxDistance(la,lo,ea,eo)+GtxDistance(ea,eo,actor.Latitude(),actor.Longitude()); }}
 return GtxDistance(la,lo,actor.Latitude(),actor.Longitude());
end_script
'''
    from gentactix import crossing_network
    if crossing_network.enabled(world):
        from . import afsim_crossing_network
        script=afsim_crossing_network.functions(world,script)
    return script


def setup_actor(p,unit,entity,pause=None):
    plan=entity.get('crossing_plan');task=plan['task'] if plan else unit.get('crossing')
    stage={'queued':1,'transit':2,'completed':3,'cancelled':4}.get(task['status'],0) if task else 0
    if plan and plan['enter_required']:stage=0
    values={'required':task['required_work'] if task else 0,'done':task['served_work'] if task else 0,
            'stage':stage,'entered':0,'left':0,'work':0}
    lines=[f' {p}.SetAuxData("ca_cross_{k}",(double)({literal(v,precision=12)}));' for k,v in values.items()]
    lines.append(f' {p}.SetAuxData("ca_cross_ready_s",(double)({pause or 0}));')
    return lines


def _parts(expression):
    return f'(int)({expression}),"|",GtxRound((({expression})-(int)({expression}))*1000000)'


def finish_actor(p,identity):
    return [f' writeln("GTXCROSS|{identity}|",'+',"|",'.join(_parts(f'{p}.AuxDataDouble("ca_cross_{k}")') for k in ('required','done','work'))+f',"|",(int){p}.AuxDataDouble("ca_cross_stage"));']


def finish_capacity(scene,world):
    budget=model(world)['throughput_work_per_hour']*scene['seconds']/3600
    work=_parts('hub.AuxDataDouble("ca_cross_work")')
    cargo=_parts('hub.AuxDataDouble("ca_cross_cargo_work")')
    return [f' writeln("GTXCROSSCAP|",{work},"|",{cargo},"|",{_parts(literal(budget))});']


def travelled_expression(entity,p):
    """Native distance over actual route progress; no crow-flight fuel shortcut."""
    origin=entity['origin'];plan=entity['crossing_plan'];entry,exit=plan['entry'],plan['exit']
    coordinates=','.join(literal(a[k]) for a in (origin,entry,exit) for k in ('lat','lng'))
    return f'GtxCrossDistance({p},{coordinates},{str(plan["enter_required"]).lower()})'


def parse(text,scene,before):
    from gentactix import crossing_network
    if crossing_network.enabled(before):
        from . import afsim_crossing_network
        return afsim_crossing_network.parse(text,scene,before)
    from . import afsim_world
    positions=afsim_world.parse_observations(text,scene)
    m=model(before);rows={};events={i:[] for i in scene['entities']};capacity=None
    def val(a,b):return int(a)+int(b)/1e6
    for line in text.splitlines():
        p=line.split('|')
        if p[0]=='GTXCROSS':
            if len(p)!=9 or p[1] not in events or p[1] in rows:raise ValueError('渡运回执缺项、重复或未知编组')
            rows[p[1]]={'required_work':val(*p[2:4]),'served_work':val(*p[4:6]),'last_work':val(*p[6:8]),'stage':int(p[8])}
        elif p[0]=='GTXCROSSCAP':
            if len(p)!=7 or capacity is not None:raise ValueError('渡运容量回传缺项或重复')
            capacity={'used_work':val(*p[1:3]),'cargo_work':val(*p[3:5]),'budget_work':val(*p[5:7])}
        elif p[0]=='GTXCROSSEVENT':
            if len(p)!=8 or p[1] not in events:raise ValueError('渡运事件未知或缺项')
            events[p[1]].append({'phase':p[2],'seconds':int(p[3])/1000,'lat':int(p[4])+int(p[5])/1e8,'lng':int(p[6])+int(p[7])/1e8})
    if set(rows)!=set(scene['entities']) or capacity is None:raise ValueError('原生渡运证据不完整，原世界不提交')
    budget=m['throughput_work_per_hour']*scene['seconds']/3600
    if abs(capacity['budget_work']-budget)>.002 or min(capacity['used_work'],capacity['cargo_work'])<-.001 or capacity['used_work']+capacity['cargo_work']>budget+.002:
        raise ValueError('渡运容量超出冻结吞吐或时间预算')
    site=before['combined_arms']['bridge'];old={u['name']:u for _,u in missions.units(before)};tasks={}
    for identity,row in rows.items():
        entity=scene['entities'][identity];unit=old[entity['name']];plan=entity.get('crossing_plan')
        prior=plan['task'] if plan else unit.get('crossing')
        if not prior:
            if any(row.values()) or events[identity]:raise ValueError('没有渡运任务却回传渡河工作量')
            continue
        if (abs(row['required_work']-prior['required_work'])>.002 or not -.001<=row['served_work']<=row['required_work']+.002
                or abs(row['served_work']-prior['served_work']-row['last_work'])>.002 or row['last_work']<0 or row['stage'] not in (0,1,2,3,4)):
            raise ValueError('渡运任务负载、进度或增量不守恒')
        ev=events[identity]
        delivered=any(line.startswith('GTXCEVENT|'+identity+'|') for line in text.splitlines())
        cancelled='cancel_crossing' in entity and entity['cancel_crossing']==prior.get('intent_id') and prior['status']=='queued' and delivered
        if row['stage']==4 and (prior.get('version')!=crossings.BOUND_TASK_VERSION or not(cancelled or prior['status']=='cancelled') or row['last_work'] or ev):
            raise ValueError('撤销回执缺少绑定指令，或撤销后仍消耗容量')
        if cancelled and row['stage']!=4:raise ValueError('原生结果未执行已确认的渡运撤销')
        if any(e['phase'] not in ('entered','exited') or not 0<=e['seconds']<=scene['seconds'] for e in ev) or len(ev)>2:
            raise ValueError('渡运事件时间或阶段非法')
        if [e['phase'] for e in ev] not in ([],['entered'],['entered','exited'],['exited']):raise ValueError('渡运事件顺序非法')
        if any(a['seconds']>b['seconds'] for a,b in zip(ev,ev[1:])):raise ValueError('渡运事件时间倒流')
        for event in ev:
            bank=prior['from_bank'] if event['phase']=='entered' else ('b' if prior['from_bank']=='a' else 'a')
            if missions.distance(event,m['banks'][bank])>.02:raise ValueError('渡运事件未到达登记两岸点')
        if row['last_work']>0 and not any(e['phase']=='entered' for e in ev):raise ValueError('未抵达渡运入口却消耗容量')
        if plan and row['stage']==3 and not any(e['phase']=='exited' for e in ev):raise ValueError('未到达出口不得认定整建制通过')
        if plan:
            pose=positions[identity]
            if row['stage'] in (0,1) and crossings.path_position(unit,[plan['entry']],pose) is None:
                raise ValueError('未完成服务的编组位置已越过入口')
            if row['stage']==2 and crossings.path_position(plan['entry'],[plan['exit']],pose) is None:
                raise ValueError('通过中位置不在两岸通道')
            if row['stage']==3 and crossings.path_position(plan['exit'],[prior['target']],pose) is None:
                raise ValueError('完成渡运的位置未进入出口侧路线')
        task={**copy.deepcopy(prior),**{k:row[k] for k in ('served_work','last_work')},'status':{0:'queued',1:'queued',2:'transit',3:'completed',4:'cancelled'}[row['stage']],
              'turn':before['mission']['turn']+1,'source':'afsim_native_estimate','events':ev}
        if abs(task['served_work']-task['required_work'])<.002:task['served_work']=task['required_work']
        crossings.validate_task(site,task);tasks[identity]=task
    if abs(sum(row['last_work'] for row in rows.values())-capacity['used_work'])>.003:
        raise ValueError('逐编组渡运工作量与设施总账不一致')
    return {'tasks':tasks,'capacity':capacity}


def validate_cargo(text,telemetry,model,scene):
    if 'crossing_network' in model['before_combined']['bridge']:
        from . import afsim_crossing_network
        return afsim_crossing_network.validate_cargo(text,telemetry,model,scene)
    from . import afsim_world
    inputs=model['crossing_inputs'];combined=telemetry['combined_arms']
    before={'combined_arms':model['before_combined'],'supply_nodes':inputs['nodes'],
            'mission':{'definition':{'combined_rules':inputs['rules']}},
            **{t+'_units':[u for team,u in model['units'] if team==t] for t in ('red','blue')}}
    positions=afsim_world.parse_observations(text,scene);after=copy.deepcopy(before);new={u['name']:u for _,u in missions.units(after)}
    rows=[]
    for identity,entity in scene['entities'].items():
        new[entity['name']].update(positions[identity])
        rows.append({'unit':entity['name'],'delivery':telemetry['units'][identity]['delivery'],'received':combined['received'][identity]})
    actual=crossings.cargo_work(before,after,{'resource_ledger':{'units':rows}},scene['seconds'])
    if abs(actual-combined['crossing']['capacity']['cargo_work'])>.003:raise ValueError('原生物资渡运容量与粮弹及分类到货不一致')
