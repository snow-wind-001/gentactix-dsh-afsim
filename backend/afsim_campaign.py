"""Optional operational processes compiled to WSF; Python only reads telemetry."""
import copy
import math
from gentactix import campaign,missions
from .afsim_literals import number as literal

REVISION=1
FORTIFICATION_REVISION=1

def n(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('战役过程需要有限数值')
    return literal(value,precision=15)

def get(p,key):return f'{p}.AuxDataDouble("ca_campaign_{key}")'
def put(p,key,value):return f'{p}.SetAuxData("ca_campaign_{key}",(double)({value}));'

def components(before,unit):
    return (before.get('campaign',{}).get('actors',{}).get(unit['name'],{}).get('fortification_components') or [])

def has_components(before):
    return any(row.get('fortification_components') for row in before.get('campaign',{}).get('actors',{}).values())

def _component(index,field):return f'component_{index}_{field}'

def setup_actor(before,unit,p,*,conceal=False):
    spec=campaign.definition(before)
    if spec is None:return []
    state=before['campaign']['actors'][unit['name']];key=campaign.source_actor_key(before,unit)
    fort=spec['fortifications'][key]
    from gentactix import formation_parts
    values={'active':int(state['active']),'release_s':campaign.release_seconds(before,unit),
        'integrity':state['fortification_integrity'],'fortified':int(fort['integrity']>0),
        'degradation':fort['degradation_per_shell'],'captured':0,'scale':formation_parts.scale(unit),
        'base_protection':min(1,state['base_protection']+(.25 if conceal else 0)),
        'base_entrenchment':state['base_entrenchment']}
    lines=[put(p,k,n(v)) for k,v in values.items()]
    parts=components(before,unit)
    if has_components(before):lines.append(put(p,'component_count',str(len(parts))))
    if parts:
        for index,part in enumerate(parts):
            lines += [put(p,_component(index,'base'),n(part['base_entrenchment'])),
                      put(p,_component(index,'integrity'),n(part['fortification_integrity']))]
        return lines+[f' GtxCampaignRefresh({p});']
    lines += [f' if ({get(p,"fortified")}>0) {{',
        f' {p}.SetAuxData("ca_protection",{get(p,"base_protection")}*(0.25+0.75*{get(p,"integrity")}/100));',
        f' {p}.SetAuxData("ca_entrenchment",{get(p,"base_entrenchment")}*(0.25+0.75*{get(p,"integrity")}/100));',' }']
    return lines

def functions(before=None):
    legacy='''script void GtxCampaignImpact(WsfPlatform target,double shells)
 if (shells<=0 || target.AuxDataDouble("ca_campaign_fortified")==0) { return; }
 double integrity=Math.Max(0,target.AuxDataDouble("ca_campaign_integrity")-shells*target.AuxDataDouble("ca_campaign_degradation"));
 target.SetAuxData("ca_campaign_integrity",integrity);
 double factor=0.25+0.75*integrity/100;
 target.SetAuxData("ca_protection",target.AuxDataDouble("ca_campaign_base_protection")*factor);
 target.SetAuxData("ca_entrenchment",target.AuxDataDouble("ca_campaign_base_entrenchment")*factor);
end_script
'''
    if not before or not has_components(before):return legacy
    maximum=max(len(row.get('fortification_components') or []) for row in before['campaign']['actors'].values())
    refresh=['script void GtxCampaignRefresh(WsfPlatform target)',
        ' double weakBase=100; double weakIntegrity=100; double weakEntrenchment=100;']
    impact=[' if ('+get('target','component_count')+'>0) {']
    for index in range(maximum):
        base=get('target',_component(index,'base'));integrity=get('target',_component(index,'integrity'))
        condition=' if ('+get('target','component_count')+'>'+str(index)+') {'
        refresh += [condition,f' weakBase=Math.Min(weakBase,{base}); weakIntegrity=Math.Min(weakIntegrity,{integrity});',
            f' weakEntrenchment=Math.Min(weakEntrenchment,{base}*(0.25+0.75*{integrity}/100));',' }']
        impact += [condition,put('target',_component(index,'integrity'),f'Math.Max(0,{integrity}-shells*'+get('target','degradation')+')'),' }']
    refresh += [put('target','base_entrenchment','weakBase'),put('target','integrity','weakIntegrity'),
        ' if ('+get('target','fortified')+'>0) {',
        ' target.SetAuxData("ca_protection",'+get('target','base_protection')+'*(0.25+0.75*weakIntegrity/100));',
        ' target.SetAuxData("ca_entrenchment",weakEntrenchment);',
        ' } else { target.SetAuxData("ca_protection",'+get('target','base_protection')+'); target.SetAuxData("ca_entrenchment",weakBase); }',
        'end_script']
    impact += [' GtxCampaignRefresh(target); return;',' }']
    marker=' double integrity=Math.Max(0,target.AuxDataDouble("ca_campaign_integrity")-shells*target.AuxDataDouble("ca_campaign_degradation"));'
    return '\n'.join(refresh)+'\n'+legacy.replace(marker,'\n'.join(impact)+'\n'+marker,1)


def fortify_components(before,unit,p,gain):
    lines=[' if ('+p+'.AuxDataDouble("ca_materials")>0) {']
    for index in range(len(components(before,unit))):
        key=_component(index,'base');lines.append(put(p,key,f'Math.Min(100,{get(p,key)}+{gain})'))
    return lines+[f' GtxCampaignRefresh({p});',f' {p}.SetAuxData("ca_materials",{p}.AuxDataDouble("ca_materials")-1);',' }']

def active_tick(p):
    return f' if (TIME_NOW>={get(p,"release_s")}) {{ {put(p,"active","1")} }}'

def capture_lines(before,actor,target,*,loss_load=None):
    rule=campaign.definition(before)['surrender']
    if loss_load is None:loss_load=f'{target}.AuxDataDouble("ca_pending_damage")+{target}.AuxDataDouble("ca_damage_remainder")'
    return [f' if ({get(target,"active")}>0 && {get(target,"captured")}==0 && {actor}.GroundRangeTo({target})<={n(rule["range_m"])} &&',
        f' ({target}.AuxDataDouble("ca_suppression")>={n(rule["suppression_threshold"])} ||',
        f' {target}.AuxDataDouble("ca_ammo_available")-{target}.AuxDataDouble("ca_ammo_spent")<={n(rule["ammo_threshold"])}*{get(target,"scale")})) {{',
        f' double toCapture=Math.Max(0,{target}.AuxDataDouble("ca_initial_current")-Math.Floor({loss_load})-{target}.AuxDataDouble("gtx_air_damage"));',
        put(target,'captured','toCapture'),
        f' }} else {{ {actor}.SetAuxData("ca_blocked",11.0); }}']

def finish_actor(identity,p,index,parts=None):
    if not parts:
        return [active_tick(p),
            f' writeln("GTXCAMPAIGN|{identity}|",(int){get(p,"active")},"|",(int)GtxRound({get(p,"integrity")}*1000000),"|",(int)captured{index},"|",(int){get(p,"base_entrenchment")});']
    lines=[active_tick(p),
        f' writeln("GTXCAMPAIGN|{identity}|",(int){get(p,"active")},"|",(int)GtxRound({get(p,"integrity")}*1000000),"|",(int)captured{index},"|",Format.Fixed({get(p,"base_entrenchment")},12));']
    for number in range(len(parts)):
        lines.append(f' writeln("GTXCAMPAIGNCOMP|{identity}|{number}|",Format.Fixed({get(p,_component(number,"base"))},12),"|",(int)GtxRound({get(p,_component(number,"integrity"))}*1000000));')
    return lines

def goal_lines(before,units,identities):
    spec=campaign.definition(before)
    if spec is None:return [],None
    owner=missions.objective_team(before['mission']['definition']);goal=spec['objective']
    lines=[' int campaignTownOwn=0; int campaignTownEnemy=0; double campaignForce=0;']
    count=len(goal['relief_regions'])
    for j in range(count):lines += [f' int campaignOwn{j}=0; int campaignEnemy{j}=0;']
    committed=sum(u['personnel']['committed'] for team,u in units if team==owner)
    threshold=before['mission']['definition']['combined_rules']['suppression_control_threshold']
    for i,(team,u) in enumerate(units):
        p=f'campaignUnit{i}';side='Own' if team==owner else 'Enemy'
        lines += [f' WsfPlatform {p}=WsfSimulation.FindPlatform("{identities[u["name"]]}");',active_tick(p)]
        if team==owner:lines.append(f' campaignForce=campaignForce+current{i};')
        lines.append(f' if (current{i}>0 && {get(p,"active")}>0) {{')
        for j,region in enumerate([goal['town']]+goal['relief_regions']):
            center=region['center'];counter='campaignTown'+side if j==0 else f'campaign{side}{j-1}'
            suppression=f'{p}.AuxDataDouble("ca_suppression")<{threshold}' if team==owner else 'true'
            lines += [f' if ({suppression} && GtxDistance({p}.Latitude(),{p}.Longitude(),{n(center["lat"])},{n(center["lng"])})<={n(region["radius_km"])}) {{ {counter}={counter}+1; }}']
        lines.append(' }')
    relief=' && '.join(f'campaignOwn{j}>0 && campaignEnemy{j}==0' for j in range(count)) if count else 'false'
    lines += [' bool campaignTown=campaignTownOwn>0 && campaignTownEnemy==0;',
        f' bool campaignRelief={relief};',
        f' bool campaignPreserved=campaignForce>={n(committed*goal["min_force_fraction"])};',
        ' writeln("GTXCAMPAIGNGOAL|",(int)campaignTown,"|",(int)campaignRelief,"|",(int)campaignPreserved);']
    if spec.get('objective_policy')==campaign.DEFENSIVE_DELAY:
        from gentactix import formation_parts
        mission=before['mission']['definition'];exit_=mission['exit']
        lines+=[' int delaySurvivors=0; int delayEnemyExit=0; double delayCommitted=0; double delayCurrent=0;']
        by_name={u['name']:i for i,(_,u) in enumerate(units)}
        for members in formation_parts.buckets(before,owner):
            alive=' || '.join(f'(current{by_name[u["name"]]}>0 && {get("campaignUnit"+str(by_name[u["name"]]),"active")}>0)' for u in members)
            lines.append(f' if ({alive}) {{ delaySurvivors=delaySurvivors+1; }}')
        for i,(team,u) in enumerate(units):
            p=f'campaignUnit{i}'
            if team==owner:
                lines.append(f' if ({get(p,"active")}>0) {{ delayCommitted=delayCommitted+{n(u["personnel"]["committed"])}; delayCurrent=delayCurrent+current{i}; }}')
            else:
                lines.append(f' if (current{i}>0 && {get(p,"active")}>0 && GtxDistance({p}.Latitude(),{p}.Longitude(),{n(exit_["lat"])},{n(exit_["lng"])})<=0.6) {{ delayEnemyExit=delayEnemyExit+1; }}')
        return lines,f'delaySurvivors>={mission["combined_rules"]["required_survivors"]} && delayEnemyExit==0 && delayCurrent>=delayCommitted*{n(goal["min_force_fraction"])}'
    return lines,'campaignTown && campaignRelief && campaignPreserved'

def parse(text,model,scene):
    expected=set(scene['entities']);actors={};goal=None;parts={}
    before=model.get('before_campaign',{}).get('actors',{})
    counts={i:len(before.get(row['name'],{}).get('fortification_components') or []) for i,row in scene['entities'].items()}
    revision=model.get('campaign_fortification_revision')
    if (any(counts.values()) and revision!=FORTIFICATION_REVISION
            or not any(counts.values()) and revision is not None):
        raise ValueError('工事侧面原生契约版本缺失或不匹配')
    for line in text.splitlines():
        fields=line.split('|')
        if fields[0]=='GTXCAMPAIGN':
            if len(fields)!=6 or fields[1] not in expected or fields[1] in actors:raise ValueError('战役部队原生回传缺项或重复')
            active,integrity,captured=map(int,fields[2:5])
            entrenchment=float(fields[5]) if counts[fields[1]] else int(fields[5])
            if active not in (0,1) or not 0<=integrity<=100000000 or captured<0 or not math.isfinite(entrenchment) or not 0<=entrenchment<=100:raise ValueError('战役部队原生回传越界')
            actors[fields[1]]={'active':bool(active),'fortification_integrity':integrity/1000000,
                'captured_this_turn':captured,'base_entrenchment':entrenchment}
        elif fields[0]=='GTXCAMPAIGNCOMP':
            if len(fields)!=5 or fields[1] not in expected:raise ValueError('工事侧面原生回传缺项或未知身份')
            identity=fields[1];index=int(fields[2]);base=float(fields[3]);integrity=int(fields[4])
            key=(identity,index)
            if (not 0<=index<counts[identity] or key in parts or not math.isfinite(base)
                    or not 0<=base<=100 or not 0<=integrity<=100000000):raise ValueError('工事侧面原生回传重复、缺项或越界')
            parts[key]=dict(base_entrenchment=base,fortification_integrity=integrity/1000000)
        elif fields[0]=='GTXCAMPAIGNGOAL':
            if len(fields)!=4 or goal is not None:raise ValueError('战役目标原生回传重复或非法')
            values=list(map(int,fields[1:]))
            if any(v not in (0,1) for v in values):raise ValueError('战役目标标志非法')
            goal=dict(zip(('town_control','relief_denied','force_preserved'),map(bool,values)))
    if set(actors)!=expected or goal is None:raise ValueError('完整战役缺少原生过程回执，不能按局部目标冒充完成')
    if set(parts)!={(identity,index) for identity,count in counts.items() for index in range(count)}:
        raise ValueError('工事侧面原生回传未覆盖全部已登记状态')
    for identity,count in counts.items():
        if not count:continue
        row=actors[identity];row['fortification_components']=[parts[identity,index] for index in range(count)]
        if (row['base_entrenchment']!=min(p['base_entrenchment'] for p in row['fortification_components'])
                or row['fortification_integrity']!=min(p['fortification_integrity'] for p in row['fortification_components'])):
            raise ValueError('工事侧面原生摘要与逐项状态不一致')
    return {'actors':actors,'objective':goal}

def apply(after,data,scene,model):
    state=copy.deepcopy(model['before_campaign']);state['turn']=model['expected_turn'];state['objective']=data['objective']
    for identity,row in data['actors'].items():state['actors'][scene['entities'][identity]['name']].update(row)
    state['execution_source']='afsim_native'
    after['campaign']=state
