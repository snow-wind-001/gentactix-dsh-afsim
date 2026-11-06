"""Native shared-work inputs and receipts; complete-world admission stays closed.

The constant segment adapter and event-clock hooks reuse existing physical
stocks. The motion component accounts for productive work, fatigue and rations.
Mixed-root campaign works, persistent task/state transfer and admission remain
separate requirements; they are never inferred from a successful segment.
"""
import copy
import hashlib
import json

from gentactix import shared_fortification as work
from .afsim_literals import number

FIELDS=('elapsed_ms','waited_ms','available_ms','productive_ms','paid_work_numerator',
        'work_added','packets_reserved','materials_after','cap_excess_micro_work',
        'base_ticks','point_remainder','work_remainder','material_credit_work',
        'material_credit_fraction','wait_remaining_ms','current')

FUNCTIONS = '''script double GtxSFWGet(WsfPlatform p,string k)
 return p.AuxDataDouble("gfw_"+k);
end_script
script void GtxSFWPut(WsfPlatform p,string k,double v)
 p.SetAuxData("gfw_"+k,v);
end_script
script void GtxSharedFortificationWork(WsfPlatform p,double elapsed)
 double waited=Math.Min(elapsed,GtxSFWGet(p,"waiting"));
 double available=0; if (GtxSFWGet(p,"enabled")>0) { available=elapsed-waited; }
 double current=Math.Floor(Math.Max(0,p.AuxDataDouble("ca_live_strength_ratio")*GtxSFWGet(p,"committed"))+0.000001);
 double rate=GtxSFWGet(p,"rate")*current;
 double micro=(100000000-GtxSFWGet(p,"base_ticks"))*GtxSFWGet(p,"committed")-GtxSFWGet(p,"point_remainder");
 double capacity=Math.Max(0,Math.Ceil(micro/1000000)*3600000-GtxSFWGet(p,"work_remainder"));
 double requested=0;
 if (rate>0 && available>0) {
  if (available>=capacity/rate) { requested=capacity; } else { requested=rate*available; }
 }
 double reqWhole=Math.Floor(requested/3600000); double reqFraction=requested-reqWhole*3600000;
 double creditWhole=GtxSFWGet(p,"material_credit_work"); double creditFraction=GtxSFWGet(p,"material_credit_fraction");
 double needWhole=reqWhole-creditWhole; if (reqFraction>creditFraction) { needWhole=needWhole+1; }
 double packet=GtxSFWGet(p,"packet");
 double reserved=Math.Min(p.AuxDataDouble("ca_materials"),Math.Max(0,Math.Ceil(needWhole/packet)));
 double budgetWhole=creditWhole+reserved*packet; double paid=requested;
 if (budgetWhole<reqWhole || (budgetWhole==reqWhole && creditFraction<reqFraction)) { paid=budgetWhole*3600000+creditFraction; }
 double paidWhole=Math.Floor(paid/3600000); double paidFraction=paid-paidWhole*3600000;
 creditWhole=budgetWhole-paidWhole; creditFraction=creditFraction-paidFraction;
 if (creditFraction<0) { creditWhole=creditWhole-1; creditFraction=creditFraction+3600000; }
 double progress=GtxSFWGet(p,"work_remainder")+paid; double added=Math.Floor(progress/3600000);
 double pending=progress-added*3600000;
 double numerator=GtxSFWGet(p,"base_ticks")*GtxSFWGet(p,"committed")+GtxSFWGet(p,"point_remainder")+added*1000000;
 double capped=Math.Min(numerator,100000000*GtxSFWGet(p,"committed"));
 double value=Math.Floor(capped/GtxSFWGet(p,"committed")); double remainder=capped-value*GtxSFWGet(p,"committed");
 if (value>=100000000) { pending=0; }
 double productive=0; if (rate>0) { productive=paid/rate; }
 p.SetAuxData("ca_materials",p.AuxDataDouble("ca_materials")-reserved);
 GtxSFWPut(p,"elapsed_ms",elapsed); GtxSFWPut(p,"waited_ms",waited); GtxSFWPut(p,"available_ms",available);
 GtxSFWPut(p,"productive_ms",productive); GtxSFWPut(p,"paid_work_numerator",paid); GtxSFWPut(p,"work_added",added);
 GtxSFWPut(p,"packets_reserved",reserved); GtxSFWPut(p,"materials_after",p.AuxDataDouble("ca_materials"));
 GtxSFWPut(p,"cap_excess_micro_work",numerator-capped); GtxSFWPut(p,"base_ticks",value); GtxSFWPut(p,"point_remainder",remainder);
 GtxSFWPut(p,"work_remainder",pending); GtxSFWPut(p,"material_credit_work",creditWhole); GtxSFWPut(p,"material_credit_fraction",creditFraction);
 GtxSFWPut(p,"wait_remaining_ms",GtxSFWGet(p,"waiting")-waited); GtxSFWPut(p,"current",current);
end_script
'''


def functions():
    return FUNCTIONS


def _guard(platform,control):
    committed=control['state']['committed']
    current=f'Math.Floor(Math.Max(0,{platform}.AuxDataDouble("ca_live_strength_ratio")*{committed}.0)+0.000001)'
    return (f'{platform}.AuxDataDouble("ca_committed")!={committed}.0 || '
            f'{platform}.AuxDataDouble("ca_materials")!={control["materials"]}.0 || '
            f'{current}!={control["current"]}.0')


def compile_component(controls,elapsed_ms):
    """Return hooks over the existing ca_materials; never seed another stock."""
    from gentactix import fortification_work as legacy
    legacy._integer(elapsed_ms,0,work.MAX_ELAPSED_MS,'共享施工区间跨度')
    if not isinstance(controls,list)or not 1<=len(controls)<=512:
        raise ValueError('共享施工需要1至512个明确实体')
    ids=set();roots={};packets=set()
    for control in controls:
        work.validate_control(control)
        identity=control['entity_id'];state=control['state']
        if identity in ids:raise ValueError('共享施工实体重复')
        ids.add(identity);packets.add(control['configuration']['material_work_units_per_packet'])
        root=roots.setdefault(state['root_id'],{'committed':state['root_committed'],'used':0})
        if root['committed']!=state['root_committed']:raise ValueError('共享施工根人数不一致')
        root['used']+=state['committed']
        if root['used']>root['committed']:raise ValueError('共享施工根份额重叠或超出容量')
    if len(packets)!=1:raise ValueError('同一共享物料库的包工作容量须一致')
    model=dict(version=work.VERSION,controls=copy.deepcopy(controls),elapsed_ms=elapsed_ms,
               scope='constant_existing_materials_and_workforce_segment')
    model['binding_digest']=hashlib.sha256(json.dumps(model,ensure_ascii=False,sort_keys=True,
        allow_nan=False,separators=(',',':')).encode()).hexdigest()
    setup=[];finish=[]
    for index,control in enumerate(controls):
        platform='shared'+str(index);state=control['state'];cfg=control['configuration']
        waiting=(state['wait_remaining_ms']if state['intent_id']==control['intent_id']
                 else control['command_delay_ms'])if control['fortify']else 0
        values={k:v for k,v in state.items()if type(v)is int}
        values.update(waiting=waiting,enabled=int(control['fortify']),
                      rate=cfg['gain_points_per_worker_hour'],packet=cfg['material_work_units_per_packet'])
        prefix=[' {',f' WsfPlatform {platform}=WsfSimulation.FindPlatform("{control["entity_id"]}");',
                f' if ({_guard(platform,control)}) {{ writeln("GTXERROR|shared_work_binding_changed"); }} else {{']
        setup+=prefix+[f' GtxSFWPut({platform},"{key}",{number(value)});'for key,value in values.items()]+[' }',' }']
        finish+=prefix+[f' GtxSharedFortificationWork({platform},{elapsed_ms}.0);']
        fields=',"|",'.join(f'Format.Fixed(GtxSFWGet({platform},"{key}"),{12 if key=="productive_ms"else 0})'for key in FIELDS)
        finish+=[f' writeln("GTXSFW|{control["entity_id"]}|",{fields});',' }',' }']
    finish.append(f' writeln("GTXSFWMETA|{model["binding_digest"]}");')
    return dict(functions=functions(),setup_lines=setup,receipt_lines=finish,model=model)


def parse(text,model):
    """Decode public Native rows and apply the shared read-only contract."""
    expected=compile_component(model['controls'],model['elapsed_ms'])['model']
    if expected!=model:raise ValueError('共享施工输入与冻结绑定不一致')
    if any(line.lstrip().startswith(('***** ERROR:','***** FATAL:','GTXERROR|'))for line in text.splitlines()):
        raise ValueError('Native共享施工报告错误')
    controls={c['entity_id']:c for c in model['controls']};rows={};meta=[]
    for line in text.splitlines():
        if line.startswith('GTXSFWMETA|'):meta.append(line)
        elif line.startswith('GTXSFW|'):
            parts=line.split('|')
            if len(parts)!=len(FIELDS)+2 or parts[1]not in controls or parts[1]in rows:
                raise ValueError('共享施工回执身份、数量或字段非法')
            try:
                values={k:float(v)if k=='productive_ms'else int(v)for k,v in zip(FIELDS,parts[2:])}
            except ValueError as exc:raise ValueError('共享施工回执数值非法')from exc
            control=controls[parts[1]]
            if values.pop('current')!=control['current']or values['elapsed_ms']!=model['elapsed_ms']:
                raise ValueError('共享施工实际人数或区间不一致')
            after=copy.deepcopy(control['state'])
            after.update({k:values.pop(k)for k in ('base_ticks','point_remainder','work_remainder',
                'material_credit_work','material_credit_fraction','wait_remaining_ms')})
            after['intent_id']=control['intent_id']
            row=dict(version=work.RECEIPT_VERSION,entity_id=parts[1],**values,after=after)
            work.check_segment(control,row);rows[parts[1]]=row
    if set(rows)!=set(controls)or meta!=['GTXSFWMETA|'+model['binding_digest']]:
        raise ValueError('共享施工回执或绑定凭证不完整')
    return rows


EVENT_VERSION='afsim-shared-fortification-events-1'


def site_identity(lat,lng):
    """Identity of one fixed work site, never a portable unit attribute."""
    from gentactix import missions
    return missions.digest(['fortification-site-1',float(lat),float(lng)])


def bind_world(before,scene,orders,controls):
    """Bind preview work to real single-root actors and current physical state.

    Heterogeneous paired campaign works and support costs remain unadmitted;
    refusing them avoids inventing a root or applying an average project.
    """
    from gentactix import missions,formation_registry,fire_process
    if before.get('campaign'):
        raise ValueError('共享施工的成对战役工事、保障与续接尚未验收')
    formation_registry.validate(before)
    checked=missions.validate_orders(before,orders,before['mission']['definition']['time_step'])
    all_units={u['name']:(team,u)for team,u in missions.units(before)}
    if not isinstance(controls,list)or not controls:raise ValueError('共享施工预览需要明确实体')
    sites={}
    for c in controls:
        work.validate_control(c)
        e=scene['entities'].get(c['entity_id'])
        if not e or e['name']not in all_units:raise ValueError('共享施工实体不在当前战局')
        team,u=all_units[e['name']];roots=formation_registry.origin_templates(before,u,team)
        if len(roots)!=1:raise ValueError('共享施工不得将多个历史根合成伪根')
        root=roots[0];s=c['state'];order=checked.get(u['name'],{})
        if (order.get('action')!='fortify' or not c['fortify']
                or c['current']!=u['personnel']['current']
                or c['materials']!=u['formation']['materials']
                or s['committed']!=u['personnel']['committed']
                or s['root_id']!=formation_registry.key(team,root)
                or s['root_committed']!=root['personnel']['committed']
                or s['site_id']!=site_identity(u['lat'],u['lng'])
                or s['base_ticks']//work.SCALE!=u['formation']['entrenchment']
                or c['command_delay_ms']!=round(fire_process.delay_seconds(before,u)*1000)):
            raise ValueError('共享施工须绑定实际根、地点、工事、材料、人数及指挥等待')
        sites[c['entity_id']]={k:u[k]for k in ('lat','lng')}
    return sites


def compile_events(controls,elapsed_ms,sites):
    """Attach work to the existing motion settlement clock, not a new scheduler."""
    import math
    checked=compile_component(controls,elapsed_ms)
    ids={c['entity_id']for c in controls}
    if not isinstance(sites,dict)or set(sites)!=ids:raise ValueError('共享施工地点必须覆盖全部实体')
    for c in controls:
        p=sites[c['entity_id']]
        if (not isinstance(p,dict)or set(p)!={'lat','lng'}or any(type(p[k])not in (int,float)
                or not math.isfinite(p[k])or abs(p[k])>limit for k,limit in [('lat',90),('lng',180)])
                or c['state']['site_id']!=site_identity(p['lat'],p['lng'])):
            raise ValueError('共享施工地点与冻结site身份不一致')
    model=dict(version=EVENT_VERSION,controls=copy.deepcopy(controls),elapsed_ms=elapsed_ms,
        sites=copy.deepcopy(sites),scope='event_bound_work_preview_without_support_or_world_admission')
    model['binding_digest']=hashlib.sha256(json.dumps(model,ensure_ascii=False,sort_keys=True,
        allow_nan=False,separators=(',',':')).encode()).hexdigest()
    setup=list(checked['setup_lines']);finish=[]
    for index,c in enumerate(controls):
        p='gfwEvent'+str(index);identity=c['entity_id'];point=sites[identity]
        setup += [' {',f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");',
            f' {p}.SetAuxData("gfw_event_identity","{identity}");',
            f' GtxSFWPut({p},"site_lat",{number(point["lat"])});',
            f' GtxSFWPut({p},"site_lng",{number(point["lng"])});',
            f' GtxSFWPut({p},"last_ms",0.0);',f' GtxSFWPut({p},"event_initialized",1.0);',' }']
        finish += [' {',f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identity}");',
            f' GtxSharedFortificationSettle({p});',
            f' writeln("GTXSFWEND|{identity}|",Format.Fixed({p}.AuxDataDouble("ca_materials"),0),"|",Format.Fixed(Math.Floor(Math.Max(0,{p}.AuxDataDouble("ca_live_strength_ratio")*GtxSFWGet({p},"committed"))+0.000001),0));',' }']
    finish.append(f' writeln("GTXSFWEVENTMETA|{model["binding_digest"]}");')
    fields=',"|",'.join(f'Format.Fixed(GtxSFWGet(p,"{key}"),{12 if key=="productive_ms"else 0})'for key in FIELDS)
    extra='''script void GtxSharedFortificationSettle(WsfPlatform p)
 if (GtxSFWGet(p,"event_initialized")<1) { return; }
 double ms=Math.Floor(TIME_NOW*1000+0.5); double start=GtxSFWGet(p,"last_ms");
 double dt=ms-start; if (dt<=0) { return; }
 WsfGeoPoint site=WsfGeoPoint.Construct(GtxSFWGet(p,"site_lat"),GtxSFWGet(p,"site_lng"),0);
 WsfGeoPoint here=WsfGeoPoint.Construct(p.Latitude(),p.Longitude(),0);
 if (site.GroundRangeTo(here)>1) { writeln("GTXERROR|shared_work_site_changed"); return; }
 double stock=p.AuxDataDouble("ca_materials");
 if (p.AuxDataDouble("ca_committed")!=GtxSFWGet(p,"committed")) { writeln("GTXERROR|shared_work_commitment_changed"); return; }
 GtxSharedFortificationWork(p,dt);
 GtxSFWPut(p,"waiting",GtxSFWGet(p,"wait_remaining_ms"));
 GtxSFWPut(p,"last_ms",ms);
 p.SetAuxData("ca_entrenchment",Math.Floor(GtxSFWGet(p,"base_ticks")/1000000));
 writeln("GTXSFWSEG|",p.AuxDataString("gfw_event_identity"),"|",Format.Fixed(start,0),"|",Format.Fixed(ms,0),"|",Format.Fixed(stock,0),"|",'''+fields+''');
end_script
'''
    return dict(functions=functions()+extra,setup_lines=setup,receipt_lines=finish,model=model)


def parse_events(text,model,*,material_events=None):
    """Validate chronological work, external deliveries and final shared stock.

    Supplied material events must come from independently validated logistics
    receipts. They are not guessed from the work actor's own stock declaration.
    """
    expected=compile_events(model['controls'],model['elapsed_ms'],model['sites'])['model']
    if expected!=model:raise ValueError('共享施工事件绑定被修改')
    if any(line.lstrip().startswith(('***** ERROR:','***** FATAL:','GTXERROR|'))for line in text.splitlines()):
        raise ValueError('Native共享施工事件报告错误')
    controls={c['entity_id']:copy.deepcopy(c)for c in model['controls']}
    events={i:[]for i in controls}
    if material_events is not None:
        if not isinstance(material_events,dict)or set(material_events)!=set(controls):
            raise ValueError('施工材料到货事件须完整匹配实体')
        events=copy.deepcopy(material_events)
    for identity,rows in events.items():
        previous=-1
        if not isinstance(rows,list):raise ValueError('施工材料到货事件须为列表')
        for row in rows:
            if (not isinstance(row,dict)or set(row)!={'at_ms','received'}or type(row['at_ms'])is not int
                    or not previous<=row['at_ms']<=model['elapsed_ms']or row['at_ms']<0
                    or type(row['received'])is not int or not 0<row['received']<=10000000):
                raise ValueError('施工材料到货事件时间或数量非法')
            previous=row['at_ms']
    result={i:dict(after=copy.deepcopy(c['state']),materials_after=c['materials'],current=c['current'],
        elapsed_ms=0,productive_ms=0.0,paid_work_numerator=0,work_added=0,packets_reserved=0,
        cap_excess_micro_work=0,intervals=[])for i,c in controls.items()}
    end={};meta=[];indexes={i:0 for i in controls}
    def arrivals(identity,ms):
        rows=events[identity];index=indexes[identity];got=0
        while index<len(rows)and rows[index]['at_ms']==ms:
            got+=rows[index]['received'];index+=1
        indexes[identity]=index
        return got
    for line in text.splitlines():
        if line.startswith('GTXSFWEVENTMETA|'):meta.append(line)
        elif line.startswith('GTXSFWEND|'):
            p=line.split('|')
            if len(p)!=4 or p[1]not in controls or p[1]in end:raise ValueError('施工末态回执身份或数量非法')
            try:end[p[1]]=tuple(map(int,p[2:]))
            except ValueError as exc:raise ValueError('施工末态回执须为整数')from exc
        elif line.startswith('GTXSFWSEG|'):
            p=line.split('|')
            if len(p)!=len(FIELDS)+5 or p[1]not in controls:raise ValueError('施工事件回执身份或字段非法')
            identity=p[1];c=controls[identity];summary=result[identity]
            try:
                start,stop,stock=map(int,p[2:5]);values={k:float(v)if k=='productive_ms'else int(v)for k,v in zip(FIELDS,p[5:])}
            except ValueError as exc:raise ValueError('施工事件回执数量非法')from exc
            if (start!=summary['elapsed_ms']or not start<stop<=model['elapsed_ms']
                    or values['elapsed_ms']!=stop-start or not 0<=values['current']<=c['current']):
                raise ValueError('施工时间不连续或可用人数非法')
            got=arrivals(identity,start)
            if stock!=c['materials']+got:raise ValueError('施工不得使用尚未到货或未被物流凭证证明的材料')
            if indexes[identity]<len(events[identity])and events[identity][indexes[identity]]['at_ms']<stop:
                raise ValueError('施工区间跨越了实际到货事件')
            c['materials']=stock;c['current']=values.pop('current')
            after=copy.deepcopy(c['state']);after.update({k:values.pop(k)for k in ('base_ticks','point_remainder',
                'work_remainder','material_credit_work','material_credit_fraction','wait_remaining_ms')})
            after['intent_id']=c['intent_id']
            row=dict(version=work.RECEIPT_VERSION,entity_id=identity,**values,after=after)
            work.check_segment(c,row)
            summary['intervals'].append(dict(start_ms=start,end_ms=stop,materials_before=stock,current=c['current'],receipt=row))
            summary.update(after=copy.deepcopy(after),materials_after=row['materials_after'],current=c['current'],elapsed_ms=stop)
            for key in ('productive_ms','paid_work_numerator','work_added','packets_reserved','cap_excess_micro_work'):summary[key]+=row[key]
            c['state']=after;c['materials']=row['materials_after']
    if meta!=['GTXSFWEVENTMETA|'+model['binding_digest']]or set(end)!=set(controls):
        raise ValueError('施工事件末态或冻结凭证不完整')
    for identity,c in controls.items():
        summary=result[identity];got=arrivals(identity,model['elapsed_ms'])
        if (summary['elapsed_ms']!=model['elapsed_ms']or indexes[identity]!=len(events[identity])
                or end[identity][0]!=c['materials']+got or not 0<=end[identity][1]<=c['current']):
            raise ValueError('施工事件未覆盖完整时长、到货或末态库存')
        summary['materials_after']=end[identity][0];summary['current']=end[identity][1]
    return result
