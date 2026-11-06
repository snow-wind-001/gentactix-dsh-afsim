"""Compile Native cadence-based food use and validate public interval receipts."""
import copy

from gentactix import formation_parts, support_dynamics as sd, sustainment_intervals as si
from .afsim_literals import number

VERSION='native-motion-nutrition-1'
SCHEDULE_VERSION='native-scheduled-nutrition-1'
FIELDS=si.FIELDS
INTEGERS=si.INTEGERS


def inputs(world,unit):
    cfg=sd.configuration(world)
    if cfg is None:return None
    sd.validate_config(cfg)
    return {'config':copy.deepcopy(cfg),'unit':copy.deepcopy({k:unit[k] for k in
        ('name','personnel','logistics','sustainment','formation_part','runtime_allocation') if k in unit}),
        'resource_scale':formation_parts.scale(unit),'deferred':sd.deferred_support(unit)}


def functions(*,load_probe=False,work=False):
    probe_guard=' if (GtxCNGet(a,"deferred")>0) { hours=0; active=0; }\n' if load_probe else ''
    code='''script double GtxCNGet(WsfPlatform a,string k)
 return a.AuxDataDouble("cn_"+k);
end_script
script void GtxCNPut(WsfPlatform a,string k,double v)
 a.SetAuxData("cn_"+k,v);
end_script
script void GtxCMNourish(WsfPlatform a,double dt,bool moving)
 if (dt<=0) { return; }
 double start=a.AuxDataDouble("cm_last_ms"); double end=start+dt;
 double people=Math.Floor(Math.Max(0,a.AuxDataDouble("ca_combat_strength_ratio")*GtxCNGet(a,"committed")-GtxCNGet(a,"nc"))+0.000001);
 double hours=dt/3600000; if (people<=0) { hours=0; }
 double active=0; if (moving) { active=dt; }
'''+probe_guard+''' double rate=GtxCNGet(a,"base_rate");
 if (GtxCNGet(a,"personnel_mode")>0) { rate=rate*people; }
 double need=rate*(hours+active/3600000*(GtxCNGet(a,"move_factor")-1));
 if (people<=0) { need=0; }
 double used=Math.Min(need,GtxCNGet(a,"food")); double unfed=0;
 if (need>0) { unfed=hours*(1-used/need); }
 double recovered=Math.Max(0,GtxCNGet(a,"debt")-(hours-unfed)*GtxCNGet(a,"recovery"));
 double debt=recovered+unfed;
 double exposure=Math.Max(0,debt-GtxCNGet(a,"incapacity_after"))-Math.Max(0,recovered-GtxCNGet(a,"incapacity_after"));
 double load=GtxCNGet(a,"remainder")+Math.Max(0,exposure)*GtxCNGet(a,"committed")*GtxCNGet(a,"incapacity_fraction");
 double whole=Math.Floor(load+0.000000001);
 if (GtxCNGet(a,"deferred")>0 && exposure<=0) { whole=0; }
 double lost=Math.Min(people,whole); double carry=Math.Max(0,load-whole);
 double floor=Math.Min(100,debt*GtxCNGet(a,"floor_rate"));
 double gain=Math.Max(0,Math.Floor(floor*1000000+0.5)-a.AuxDataDouble("cm_fatigue"));
 a.SetAuxData("cm_fatigue",a.AuxDataDouble("cm_fatigue")+gain);
 a.SetAuxData("ca_fatigue",Math.Floor(a.AuxDataDouble("cm_fatigue")/1000000));
 GtxCNPut(a,"floor_gain",GtxCNGet(a,"floor_gain")+gain);
 GtxCNPut(a,"food",GtxCNGet(a,"food")-used); GtxCNPut(a,"debt",debt); GtxCNPut(a,"remainder",carry);
 GtxCNPut(a,"nc",GtxCNGet(a,"nc")+lost);
 GtxCNPut(a,"need",GtxCNGet(a,"need")+need); GtxCNPut(a,"used",GtxCNGet(a,"used")+used);
 GtxCNPut(a,"unmet",GtxCNGet(a,"unmet")+need-used); GtxCNPut(a,"floor",floor);
 a.SetAuxData("ca_live_strength_ratio",Math.Max(0,a.AuxDataDouble("ca_combat_strength_ratio")-GtxCNGet(a,"nc")/GtxCNGet(a,"committed")));
 writeln("GTXCNSEG|",a.AuxDataString("cm_identity"),"|",Format.Fixed(start,0),"|",Format.Fixed(end,0),"|",Format.Fixed(active,0),"|",Format.Fixed(people,0),"|",Format.Fixed(need,12),"|",Format.Fixed(used,12),"|",Format.Fixed(debt,12),"|",Format.Fixed(carry,12),"|",Format.Fixed(floor,12),"|",Format.Fixed(lost,0),"|",Format.Fixed(gain,0));
end_script
'''
    if work:
        original=' double need=rate*(hours+active/3600000*(GtxCNGet(a,"move_factor")-1));'
        changed=' double workms=0; double factor=1;\n'
        changed+=' if (a.AuxDataDouble("gfw_event_initialized")>0) { workms=a.AuxDataDouble("gfw_productive_ms"); factor=a.AuxDataDouble("gfw_food_factor"); }\n'
        changed+=' if (active+workms>dt+0.000001) { writeln("GTXERROR|work_move_time_overlap"); }\n'
        changed+=' double need=rate*(hours+active/3600000*(GtxCNGet(a,"move_factor")-1)+workms/3600000*(factor-1));'
        assert original in code
        code=code.replace(original,changed,1)
    return code


def delivery_functions():
    return '''script void GtxCNReceiveFood(WsfPlatform a,double amount)
 GtxCMSettle(a);
 if (amount<0 || GtxCNGet(a,"food")+amount>GtxCNGet(a,"capacity")+0.000001) {
  writeln("GTXERROR|continuous_food_capacity"); return;
 }
 GtxCNPut(a,"food",GtxCNGet(a,"food")+amount);
end_script
'''


def setup(actor,identity,data,*,scheduled=False):
    cfg=data['config'];u=data['unit'];scale=data['resource_scale'];people=cfg['version']==sd.PERSONNEL_VERSION
    rate=cfg['ration_kg_per_person_day']/24/cfg['food_kg_per_work'] if people else cfg['food_work_per_hour']*scale
    values=dict(food=u['logistics']['food']*scale,debt=u['sustainment']['shortage_hours'],
        remainder=u['sustainment']['noncombat_remainder'],committed=u['personnel']['committed'],
        base_rate=rate,personnel_mode=int(people),move_factor=cfg['move_factor'],recovery=cfg['recovery_hours_per_fed_hour'],
        incapacity_after=cfg['incapacity_after_hours'],incapacity_fraction=cfg['incapacity_fraction_per_hour'],
        floor_rate=cfg['shortage_fatigue_per_hour'],deferred=int(data['deferred']),nc=0,need=0,used=0,unmet=0,floor=0,floor_gain=0)
    if scheduled:values['capacity']=sd.food_capacity(cfg,u)*scale
    return [f' {actor}.SetAuxData("cm_identity","{identity}");',
        f' {actor}.SetAuxData("ca_combat_strength_ratio",{actor}.AuxDataDouble("ca_live_strength_ratio"));',
        *[f' GtxCNPut({actor},"{k}",{number(v)});' for k,v in values.items()]]


def read_segments(text,model):
    """Decode public records; the shared read-only contract checks arithmetic."""
    if model.get('nutrition_revision')!=VERSION:raise ValueError('机动营养回执版本非法')
    controls=model['controls'];rows={i:[] for i in controls}
    for line in text.splitlines():
        if not line.startswith('GTXCNSEG|'):continue
        p=line.split('|')
        if len(p)!=len(FIELDS)+2 or p[1] not in rows:raise ValueError('机动营养回执字段或身份非法')
        try:r=dict(zip(FIELDS,map(float,p[2:])))
        except ValueError as exc:raise ValueError('机动营养回执须为有限数量') from exc
        rows[p[1]].append(r)
    return rows


def parse(text,model,*,delivery_events=None,shared_work_material_events=None):
    rows=read_segments(text,model)
    if delivery_events is not None and (not isinstance(delivery_events,dict)
            or set(delivery_events)!=set(rows)):
        raise ValueError('机动营养到货回执必须完整匹配执行身份')
    work_rows={};work_cfg={}
    if model.get('work_support_revision'):
        from . import afsim_shared_fortification,afsim_continuous_motion
        if model['work_support_revision']!=afsim_continuous_motion.WORK_SUPPORT_VERSION:
            raise ValueError('劳动营养版本不匹配')
        shared=model['shared_fortification']['model']
        work_rows=afsim_shared_fortification.parse_events(text,shared,material_events=shared_work_material_events)
        work_cfg={c['entity_id']:c['configuration']for c in shared['controls']}
    result={}
    for identity,segments in rows.items():
        data=model['controls'][identity]['nutrition']
        events=None if delivery_events is None else delivery_events[identity]
        result[identity]=si.validate(data['config'],data['unit'],model['seconds'],segments,
            events=events,load_probe=model.get('nutrition_load_probe',False),
            **({'work_activity':{'configuration':work_cfg[identity],'intervals':work_rows[identity]['intervals']}}if identity in work_rows else {}))['summary']
    return result
