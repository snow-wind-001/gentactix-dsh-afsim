"""WSF boat movers, boarding/landing callbacks and native receipt parser."""
import copy
import math

from gentactix import ferries, crossings, missions
from .afsim_literals import number as literal


def enabled(world):
    return ferries.config(world) is not None


def actor_callbacks():
    return [' script void GtxCrossService()', '  GtxFerryRequest(PLATFORM);', ' end_script',
            ' script void GtxCrossEnter()',
            '  PLATFORM.ExecuteAtTime(TIME_NOW+0.000001,"GtxCrossService");', ' end_script',
            ' script void GtxCrossExit()', ' end_script']


def sync_expression(p):
    return f' GtxFerrySync({p});'


def compile_boats(scene, world):
    from .afsim_world import _location
    model = crossings.get_model(world)
    values = ferries.config(world)
    current = ferries.state(world)
    identities = {e['name']: i for i, e in scene['entities'].items()}
    end = scene['seconds']
    lines = []
    lines += ['platform_type gtx_ferry_type WSF_PLATFORM', ' mover WSF_SURFACE_MOVER',
              '  update_interval 0.05 sec', '  at_end_of_path stop', ' end_mover',
              ' script void GtxFerryArrivalService()', '  GtxFerryArrive(PLATFORM);', ' end_script',
              ' script void GtxFerryArrival()',
              '  PLATFORM.ExecuteAtTime(TIME_NOW+0.000001,"GtxFerryArrivalService");', ' end_script', 'end_platform_type']
    setup = ['execute at_time 0.0002 sec absolute']
    for index, (spec, old) in enumerate(zip(values['boats'], current['boats'])):
        name = 'gtx_ferry_' + spec['id']
        phase = ferries.PHASES.index(old['phase'])
        lines += [f'platform {name} gtx_ferry_type', f' side {spec["team"]}',
                  ' route', f'  position {_location(old)}', f'  speed {spec["speed_mps"]} m/s',
                  ' end_route', 'end_platform']
        p = f'boat{index}'
        setup += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{name}");']
        fields = {'phase': phase, 'bank': int(old['bank']=='b'), 'from': int(old['from_bank']=='b'),
                  'ready': old['remaining_s'], 'trips': old['trips'], 'persons': old['manifest_personnel'],
                  'equipment': old['manifest_equipment_work'], 'unload_s': spec['unload_seconds'],
                  'speed': spec['speed_mps']}
        for key, value in fields.items():
            setup.append(f' {p}.SetAuxData("f_{key}",(double)({literal(value,precision=12)}));')
        passenger = identities.get(old['passenger'], '')
        setup += [f' {p}.SetAuxData("f_passenger","{passenger}");', f' {p}.SetAuxData("f_id","{spec["id"]}");']
        if passenger:
            setup += [f' WsfPlatform rider{index}=WsfSimulation.FindPlatform("{passenger}");',
                      f' rider{index}.SetAuxData("ferry_boat","{name}");', f' rider{index}.Pause({end+1});']
        if phase in (2, 4):
            target = ('b' if old['from_bank']=='a' else 'a') if phase == 2 else old['from_bank']
            point=model['banks'][target]
            setup += [f' if (!{p}.GoToPoint(WsfGeoPoint.Construct({point["lat"]},{point["lng"]},0),"GtxFerryArrival")) {{ writeln("GTXERROR|ferry_resume"); }}',f' {p}.GoToSpeed({spec["speed_mps"]},1.0,true);']
        else:setup.append(f' {p}.Pause({end+1});')
    for i, entity in scene['entities'].items():
        if entity.get('ferry_transport'):
            setup.append(f' WsfSimulation.FindPlatform("{i}").Pause({end+1});')
            # A queued mover must first reach the bank; only already reserved
            # passengers are paused for the complete leg at initialization.
            if not ferries.carrier(world, entity['name']):
                setup.append(f' WsfSimulation.FindPlatform("{i}").Unpause();')
                # Existing command/fatigue delay is installed at .0001.
                setup.append(f' WsfSimulation.FindPlatform("{i}").Pause(Math.Max(0.000201,WsfSimulation.FindPlatform("{i}").AuxDataDouble("ca_cross_ready_s")));')
    setup += ['end_execute']
    lines += setup
    return '\n'.join(lines)


def functions(scene, world):
    from gentactix import movement_feedback
    end = scene['seconds']
    m = crossings.get_model(world)
    a, b = m['banks']['a'], m['banks']['b']
    common = f'''
script WsfGeoPoint GtxFerryPoint(double bank)
 if (bank==0) {{ return WsfGeoPoint.Construct({a['lat']},{a['lng']},0); }}
 return WsfGeoPoint.Construct({b['lat']},{b['lng']},0);
end_script
script void GtxFerryEvent(WsfPlatform boat,string phase,string passenger)
 writeln("GTXFERRYEVENT|",boat.AuxDataString("f_id"),"|",passenger,"|",phase,"|",Format.Fixed(TIME_NOW,6),"|",Format.Fixed(boat.Latitude(),10),"|",Format.Fixed(boat.Longitude(),10));
end_script
script void GtxFerrySync(WsfPlatform actor)
 string id=actor.AuxDataString("ferry_boat");
 if (id!="") {{ WsfPlatform boat=WsfSimulation.FindPlatform(id);
  if (boat.AuxDataDouble("f_phase")==2 || boat.AuxDataDouble("f_phase")==3) {{ actor.SetLocation(boat.Location()); }}
 }}
end_script
script void GtxFerryRequest(WsfPlatform actor)
 if (actor.AuxDataDouble("ca_cross_entered")>0) {{ return; }}
 actor.SetAuxData("ca_cross_entered",1.0); actor.SetAuxData("ca_cross_stage",1.0);
 actor.SetAuxData("ferry_arrival",TIME_NOW); GtxCrossEvent(actor,"entered"); actor.Pause({end+1});
end_script
script void GtxFerryArrive(WsfPlatform boat)
 double phase=boat.AuxDataDouble("f_phase");
 if (phase==2) {{
  boat.SetAuxData("f_bank",1-boat.AuxDataDouble("f_from"));
  boat.SetAuxData("f_phase",3.0);boat.SetAuxData("f_ready",TIME_NOW+boat.AuxDataDouble("f_unload_s"));
  boat.Pause({end+1});
  GtxFerrySync(WsfSimulation.FindPlatform(boat.AuxDataString("f_passenger")));
 }} else if (phase==4) {{
  boat.SetAuxData("f_bank",boat.AuxDataDouble("f_from"));boat.SetAuxData("f_phase",0.0);
  boat.Pause({end+1});
  GtxFerryEvent(boat,"returned","");
 }}
end_script
script void GtxFerryTick()
 WsfPlatform hub=WsfSimulation.FindPlatform("gtx_ca_hub");
'''
    lines = [common]
    units = missions.units(world)
    identities = {e['name']: i for i, e in scene['entities'].items()}
    budget = m['throughput_work_per_hour']*end/3600
    for index, spec in enumerate(ferries.config(world)['boats']):
        p = f'boat{index}'
        lines.append(f' WsfPlatform {p}=WsfSimulation.FindPlatform("gtx_ferry_{spec["id"]}");')
        lines += [f' if ({p}.AuxDataDouble("f_phase")==1) {{',
                  f' WsfPlatform rider=WsfSimulation.FindPlatform({p}.AuxDataString("f_passenger"));',
                  ' if (rider.AuxDataDouble("ca_cross_stage")==4) {',
                  f' GtxFerryEvent({p},"cancelled",rider.Name()); rider.SetAuxData("ferry_boat","");',
                  f' {p}.SetAuxData("f_phase",0.0); {p}.SetAuxData("f_passenger",""); {p}.SetAuxData("f_persons",0.0); {p}.SetAuxData("f_equipment",0.0);',
                  f' }} else if (TIME_NOW>={p}.AuxDataDouble("f_ready")) {{',
                  ' double need=Math.Max(0,rider.AuxDataDouble("ca_cross_required")-rider.AuxDataDouble("ca_cross_done"));',
                  f' if (hub.AuxDataDouble("ca_cross_work")+need<={literal(budget,precision=12)}) {{',
                  ' rider.SetAuxData("ca_cross_done",rider.AuxDataDouble("ca_cross_required"));',
                  ' rider.SetAuxData("ca_cross_work",need); rider.SetAuxData("ca_cross_stage",2.0);',
                  ' if (rider.AuxDataDouble("ca_cross_entered")==0) { GtxCrossEvent(rider,"entered"); rider.SetAuxData("ca_cross_entered",1.0); }',
                  ' hub.SetAuxData("ca_cross_work",hub.AuxDataDouble("ca_cross_work")+need);',
                  f' {p}.SetAuxData("f_phase",2.0); GtxFerryEvent({p},"boarded",rider.Name());',
                  f' {p}.Unpause();',
                  f' if (!{p}.GoToPoint(GtxFerryPoint(1-{p}.AuxDataDouble("f_from")),"GtxFerryArrival")) {{ writeln("GTXERROR|ferry_departure"); }}', f' {p}.GoToSpeed({spec["speed_mps"]},1.0,true);',
                  ' } } }']
        lines += [f' if ({p}.AuxDataDouble("f_phase")==3 && TIME_NOW>={p}.AuxDataDouble("f_ready")) {{',
                  f' WsfPlatform rider=WsfSimulation.FindPlatform({p}.AuxDataString("f_passenger"));',
                  f' rider.SetLocation({p}.Location()); rider.SetAuxData("ferry_boat","");',
                  ' rider.SetAuxData("ca_cross_left",1.0); rider.SetAuxData("ca_cross_stage",3.0);',
                  ' GtxCrossEvent(rider,"exited"); rider.Unpause();',
                  ' hub.SetAuxData("ca_used",hub.AuxDataDouble("ca_used")+1);',
                  f' GtxFerryEvent({p},"landed",rider.Name()); {p}.SetAuxData("f_trips",{p}.AuxDataDouble("f_trips")+1);',
                  f' {p}.SetAuxData("f_persons",0.0); {p}.SetAuxData("f_equipment",0.0); {p}.SetAuxData("f_passenger",""); {p}.SetAuxData("f_phase",4.0);',
                  f' {p}.Unpause();',
                  f' if (!{p}.GoToPoint(GtxFerryPoint({p}.AuxDataDouble("f_from")),"GtxFerryArrival")) {{ writeln("GTXERROR|ferry_return"); }}', f' {p}.GoToSpeed({spec["speed_mps"]},1.0,true);', ' }']
        lines += [f' if ({p}.AuxDataDouble("f_phase")==0) {{', ' double first=1000000000000.0; string selected="";']
        for team, unit in units:
            if team != spec['team'] or not ferries.can_board(world, unit, spec):
                continue
            identity = identities[unit['name']]
            entity = scene['entities'][identity]
            if not entity.get('crossing_plan'):
                continue
            from_bank = int(entity['crossing_plan']['task']['from_bank']=='b')
            lines += [f' WsfPlatform q_{identity}=WsfSimulation.FindPlatform("{identity}");',
                      f' if ({p}.AuxDataDouble("f_bank")=={from_bank} && q_{identity}.AuxDataDouble("ca_cross_entered")>0 && q_{identity}.AuxDataDouble("ca_cross_stage")==1 && q_{identity}.AuxDataString("ferry_boat")=="" && q_{identity}.AuxDataDouble("ca_live_strength_ratio")>0 && q_{identity}.AuxDataDouble("ferry_arrival")<first) {{',
                      f' first=q_{identity}.AuxDataDouble("ferry_arrival");selected="{identity}";', ' }']
        lines += [' if (selected!="") {', ' WsfPlatform rider=WsfSimulation.FindPlatform(selected);',
                  f' {p}.SetAuxData("f_phase",1.0); {p}.SetAuxData("f_from",{p}.AuxDataDouble("f_bank"));',
                  f' {p}.SetAuxData("f_ready",TIME_NOW+{spec["load_seconds"]}); {p}.SetAuxData("f_passenger",selected);',
                  f' {p}.SetAuxData("f_persons",rider.AuxDataDouble("ca_initial_current"));',
                  f' {p}.SetAuxData("f_equipment",rider.AuxDataDouble("ca_cross_required")-rider.AuxDataDouble("ca_initial_current"));',
                  f' rider.SetAuxData("ferry_boat","gtx_ferry_{spec["id"]}"); GtxFerryEvent({p},"loading",selected);', ' } else {', ' double other=-1;']
        for team, unit in units:
            entity=scene['entities'][identities[unit['name']]]
            if team!=spec['team'] or not ferries.can_board(world,unit,spec) or not entity.get('crossing_plan'):continue
            identity=identities[unit['name']];bank=int(entity['crossing_plan']['task']['from_bank']=='b')
            lines += [f' WsfPlatform remote_{identity}=WsfSimulation.FindPlatform("{identity}");',
                f' if ({p}.AuxDataDouble("f_bank")!={bank} && remote_{identity}.AuxDataDouble("ca_cross_entered")>0 && remote_{identity}.AuxDataDouble("ca_cross_stage")==1 && remote_{identity}.AuxDataString("ferry_boat")=="") {{ other={bank}; }}']
        lines += [f' if (other>=0) {{ {p}.SetAuxData("f_from",other); {p}.SetAuxData("f_phase",4.0);',
            f' GtxFerryEvent({p},"repositioning",""); {p}.Unpause();',
            f' if (!{p}.GoToPoint(GtxFerryPoint(other),"GtxFerryArrival")) {{ writeln("GTXERROR|ferry_reposition"); }}',
            f' {p}.GoToSpeed({spec["speed_mps"]},1.0,true);', ' } } }']
        lines += [f' if ({p}.AuxDataString("f_passenger")!="") {{ GtxFerrySync(WsfSimulation.FindPlatform({p}.AuxDataString("f_passenger"))); }}']
    lines += ['end_script', 'execute at_interval_of 1 sec', ' GtxFerryTick();', 'end_execute']
    script='\n'.join(lines)
    if movement_feedback.configuration(world):
        script=script.replace('GtxCrossEvent(rider,"exited"); rider.Unpause();',
            'GtxCrossEvent(rider,"exited"); rider.Unpause(); rider.Pause(Math.Max(TIME_NOW+0.000001,rider.AuxDataDouble("ca_cross_ready_s")));')
    return script


def finish(scene, world):
    lines = []
    for index, spec in enumerate(ferries.config(world)['boats']):
        p = f'fb{index}'
        lines += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("gtx_ferry_{spec["id"]}");',
                  f' double wait{index}=0; if ({p}.AuxDataDouble("f_phase")==1 || {p}.AuxDataDouble("f_phase")==3) {{ wait{index}=Math.Max(0,{p}.AuxDataDouble("f_ready")-TIME_NOW); }}',
                  f' writeln("GTXFERRY|{spec["id"]}|",Format.Fixed({p}.Latitude(),10),"|",Format.Fixed({p}.Longitude(),10),"|",(int){p}.AuxDataDouble("f_phase"),"|",(int){p}.AuxDataDouble("f_bank"),"|",(int){p}.AuxDataDouble("f_from"),"|",Format.Fixed(wait{index},6),"|",{p}.AuxDataString("f_passenger"),"|",(int){p}.AuxDataDouble("f_persons"),"|",Format.Fixed({p}.AuxDataDouble("f_equipment"),6),"|",(int){p}.AuxDataDouble("f_trips"));']
    return lines


def parse(text, scene, before):
    ids = {spec['id'] for spec in ferries.config(before)['boats']}
    rows, events = {}, []
    for line in text.splitlines():
        p = line.split('|')
        if p[0] == 'GTXFERRY':
            if len(p)!=12 or p[1] not in ids or p[1] in rows:
                raise ValueError('舟艇原生回执缺项、未知或重复')
            phase, bank, origin = map(int, p[4:7])
            if phase not in range(5) or bank not in (0,1) or origin not in (0,1):
                raise ValueError('舟艇原生阶段非法')
            rider = scene['entities'].get(p[8])
            if p[8] and rider is None:
                raise ValueError('舟艇回传了未知乘客')
            rows[p[1]] = {'id':p[1], 'lat':float(p[2]), 'lng':float(p[3]), 'phase':ferries.PHASES[phase],
                'bank':'ab'[bank], 'from_bank':'ab'[origin], 'remaining_s':float(p[7]),
                'passenger':rider['name'] if rider else None, 'manifest_personnel':int(p[9]),
                'manifest_equipment_work':float(p[10]), 'trips':int(p[11])}
        elif p[0]=='GTXFERRYEVENT':
            if len(p)!=7 or p[1] not in ids or (p[2] and p[2] not in scene['entities']):
                raise ValueError('舟艇原生事件身份非法')
            events.append({'boat_id':p[1], 'unit':scene['entities'][p[2]]['name'] if p[2] else None,
                'phase':p[3], 'seconds':float(p[4]), 'lat':float(p[5]), 'lng':float(p[6])})
    if set(rows)!=ids:
        raise ValueError('缺少实际舟艇状态，拒绝提交')
    return {'version':ferries.VERSION, 'turn':before['mission']['turn']+1, 'source':'afsim_native_estimate',
            'boats':[rows[s['id']] for s in ferries.config(before)['boats']], 'events':events}
