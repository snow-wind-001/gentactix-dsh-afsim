"""Compile the project's versioned teaching equations into native WSF Script.

Only validated numeric inputs and hashed entity names enter this closed template.
Python decodes native telemetry; it does not compute the candidate turn here.
"""
import copy
import math

from gentactix import missions, supply, adjudicator, resource_accounts, formation_parts
from gentactix.unit_types import classify_unit
from . import afsim_air
from .afsim_literals import number as literal

VERSION = 'afsim-native-teaching-1'
UNIT_FIELDS = ('current', 'casualties', 'noncombat_losses', 'operational', 'destroyed',
               'food', 'ammo', 'hp100', 'supply', 'delivery', 'food_spent', 'ammo_spent', 'connectivity')
MISSION_FIELDS = ('turn', 'progress', 'network', 'organization', 'accepted', 'red_available',
                  'blue_available', 'red_in_goal', 'blue_in_goal', 'condition', 'terminal', 'success')

FUNCTIONS = '''
script double GtxDistance(double la, double lo, double lb, double lp)
 double x = (lp-lo)*111.32*Math.Cos((la+lb)/2.0);
 double y = (lb-la)*110.57;
 return Math.Sqrt(x*x+y*y);
end_script
script int GtxRound(double x)
 int n = (int)x;
 double f = x-n;
 if (f > 0.5 || (f == 0.5 && Math.Mod(n, 2) == 1)) { n = n+1; }
 return n;
end_script
script bool GtxBlocked(double la, double lo, double lb, double lp, double lt, double ln, double radius)
 double scale = 111.32*Math.Cos((la+lb)/2.0);
 double dx = (lp-lo)*scale;
 double dy = (lb-la)*110.57;
 double x = (ln-lo)*scale;
 double y = (lt-la)*110.57;
 double a = dx*dx+dy*dy;
 double c = x*x+y*y-radius*radius;
 if (c <= 0) { return true; }
 if (a <= 0.000000000001) { return false; }
 double b = -2*(dx*x+dy*y);
 double disc = b*b-4*a*c;
 if (disc < 0) { return false; }
 double t = (-b-Math.Sqrt(disc))/(2*a);
 return t >= 0 && t <= 1;
end_script
'''


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Native teaching model requires known finite numeric input')
    return literal(value,precision=15)


def compile_model(scene, before, orders, *, shared_work_controls=None):
    """A native, simultaneous teaching turn over the existing mission definition."""
    if not before.get('mission'):
        if shared_work_controls is not None:raise ValueError('共享施工预览需要明确世界定义')
        return None
    if before['mission']['definition'].get('combined_rules'):
        from . import afsim_combined
        return afsim_combined.compile_model(scene,before,orders,FUNCTIONS,VERSION,
            **({'shared_work_controls':shared_work_controls}if shared_work_controls is not None else {}))
    if shared_work_controls is not None:
        raise ValueError('共享施工预览需要完整聚合世界')
    commands = missions.validate_orders(before, orders, before['mission']['definition']['time_step'])
    mission = before['mission']; spec = mission['definition']
    air = afsim_air.compile_air(scene, before, list(commands.values()))
    input_digest=missions.digest({'units':missions.units(before),'nodes':before['supply_nodes'],
        'mission':mission,'orders':list(commands.values()), 'air_state': air['state'], 'supply_binding_revision':1})
    units = missions.units(before); indices = {unit['name']: i for i, (_, unit) in enumerate(units)}
    identities = {(value['team'], value['name']): key for key, value in scene['entities'].items()}
    depots = before['supply_nodes']
    lines = [FUNCTIONS, air['script'], f"execute at_time {scene['seconds']:.6f} sec absolute",f' writeln("GTXMODEL|{input_digest}");']
    for i, depot in enumerate(depots): lines.append(f" double depot{i} = {number(depot['stock'])};")
    for i,(team,u) in enumerate(units):
        identity = identities[(team,u['name'])]
        p=u['personnel']; e=u['equipment'][0]; log=u['logistics']
        values={'c':p['current'],'k':p['casualties'],'n':p['noncombat_losses'], 'e':e['operational'],
                'z':e['destroyed'],'f':log['food'],'a':log['ammo'],'d':0,'del':0,'fc':0,'ac':0,'conn':-1}
        lines.append(f' WsfPlatform p{i} = WsfSimulation.FindPlatform("{identity}");')
        for key,value in values.items(): lines.append(f' double {key}{i} = {number(value)};')
    # Supply connectivity is computed by WSF Script over resolved input polylines;
    # no Python adjudication verdict is handed to the native calculation.
    for i,(team,u) in enumerate(units):
        paths,_=supply.resolve_paths(before,team,u)
        if paths: lines.append(f' conn{i} = 0;')
        for path_index,path in enumerate(paths):
            blocked=f'blocked{i}_{path_index}'; lines.append(f' bool {blocked} = false;')
            for start,end in zip(path['coordinates'],path['coordinates'][1:]):
                for enemy_team,enemy in units:
                    profile=classify_unit(enemy.get('type','')) or {}
                    if enemy_team==team or enemy.get('hp',0)<=0 or profile.get('ground_control') is False: continue
                    radius=f"Math.Max({number(spec['geometry']['control_radius_km'])},{number(adjudicator.unit_attack_range_m(enemy))}*1.2/1000.0)"
                    args=','.join(number(v) for v in (*start,*end,enemy['lat'],enemy['lng']))
                    lines.append(f' {blocked} = {blocked} || GtxBlocked({args},{radius});')
            lines.append(f' if (!{blocked}) {{ conn{i} = 1; }}')
    lines += [f" double network={number(mission['network'])}; double organization={number(mission['organization'])};",
              f" int hidden=0; int accepted={int(bool(mission['accepted']))};"]
    for i,(team,u) in enumerate(units):
        action=commands.get(u['name'],{}).get('action','hold')
        if u['personnel']['current']<=0: continue
        pressure=any(old_team!=team and commands.get(old['name'],{}).get('action')=='air_support' and not commands.get(old['name'],{}).get('target') for old_team,old in units)
        rate=8 if action=='resupply' else 2
        # Rate and action are model inputs. Depletion, pressure and capacity are
        # evaluated inside AFSIM, including the previous network state.
        if pressure: rate//=2
        if spec['profile']=='rail' and team=='blue':
            lines.append(f" double rate{i}={rate}; if ({number(mission['network'])} <= 20) {{ rate{i}=0; }}")
            rate_expr=f'rate{i}'
        else: rate_expr=str(rate)
        depot=depots.index(supply.bound_node(before,team,u)); food_cost=resource_accounts.food_demand(action)
        ammo_cost=3 if action=='fire' or (action=='air_support' and not commands.get(u['name'],{}).get('target')) else 0
        lines += [f' if (conn{i} == 1 && depot{depot} > 0) {{',
                  f'  del{i} = Math.Min({rate_expr},Math.Min(depot{depot},Math.Min(100-f{i},100-a{i})));',
                  f'  depot{depot} = depot{depot}-del{i};', ' }',
                  f' fc{i} = Math.Min({food_cost},f{i}+del{i}); ac{i} = {ammo_cost};',
                  f' f{i} = Math.Max(0,f{i}+del{i}-{food_cost}); a{i} = Math.Max(0,a{i}+del{i}-{ammo_cost});',
                  f' if (f{i} == 0) {{ double starving{i} = Math.Min(2,c{i}); c{i}=c{i}-starving{i}; n{i}=n{i}+starving{i}; }}']
        if action=='fire':
            target=commands[u['name']]['target']; j=indices[target]
            victim=units[j][1]
            args=','.join(number(v) for v in (u['lat'],u['lng'],victim['lat'],victim['lng']))
            lines.append(f" if (GtxDistance({args})*1000>{number(u['attack_range'])}+1 || {number(u['logistics']['ammo'])}<3) {{ writeln(\"GTXERROR|fire_constraints\"); }}")
            cover=.4 if commands.get(target,{}).get('action')=='conceal' else spec['rules']['cover']
            lines.append(f" d{j} = d{j}+Math.Max(1,GtxRound({number(spec['rules']['damage'])}*{number(u['personnel']['current'])}/{number(u['personnel']['committed'])}*{number(cover)}));")
        elif action=='sabotage': lines.append(' network=network-40;')
        elif action=='repair': lines.append(' network=network+25;')
        elif action=='accept' and team=='red': lines.append(' accepted=1;')
        if action=='conceal' and team=='red': lines.append(' hidden=hidden+1;')
    lines += [' double redAvailable=0; double blueAvailable=0; int redAlive=0; int blueAlive=0;',
              ' int redInGoal=0; int blueInGoal=0; int redAtExit=0; int blueAtExit=0;']
    for i,(team,u) in enumerate(units):
        p=u['personnel']; identity=identities[(team,u['name'])]
        if commands.get(u['name'],{}).get('action')=='move':
            limit=spec['rules']['move_km']*(.5 if u['logistics']['food']<4 else 1)
            lines.append(f" if (GtxDistance({number(u['lat'])},{number(u['lng'])},p{i}.Latitude(),p{i}.Longitude())>{number(limit)}+0.001) {{ writeln(\"GTXERROR|move_budget\"); }}")
        lines += [f' double groundLoss{i} = Math.Min(d{i},c{i});']
        air_damage=f'p{i}.AuxDataDouble("gtx_air_damage")' if air['tasks'] else '0'
        air_equipment=f'p{i}.AuxDataDouble("gtx_air_equipment")' if air['tasks'] else '0'
        lines += [f' double airLoss{i} = Math.Min(c{i}-groundLoss{i},{air_damage});',
                  f' double loss{i} = groundLoss{i}+airLoss{i}; c{i}=c{i}-loss{i}; k{i}=k{i}+loss{i};',
                  f' double airEquipment{i}=Math.Min(Math.Max(0,e{i}-Math.Floor(groundLoss{i}/8)),{air_equipment});',
                  f' double destroyed{i} = Math.Min(e{i},Math.Floor(groundLoss{i}/8)+airEquipment{i}); e{i}=e{i}-destroyed{i}; z{i}=z{i}+destroyed{i};',
                  f" int hp{i} = GtxRound(10000*c{i}/{number(p['committed'])});",
                  f' if (c{i}>0) {{ {team}Available={team}Available+c{i}; {team}Alive={team}Alive+1;',
                  f"  if (GtxDistance(p{i}.Latitude(),p{i}.Longitude(),{number(spec['objective']['lat'])},{number(spec['objective']['lng'])}) <= {number(spec['goal_radius_km'])}) {{ {team}InGoal={team}InGoal+1; }}",
                  f"  if (GtxDistance(p{i}.Latitude(),p{i}.Longitude(),{number(spec['exit']['lat'])},{number(spec['exit']['lng'])}) <= 0.6) {{ {team}AtExit={team}AtExit+1; }}", ' }']
        output=[f'(int){key}{i}' for key in ('c','k','n','e','z')]+[f'f{i}',f'a{i}',f'hp{i}',f'Math.Min(f{i},a{i})',f'del{i}',f'fc{i}',f'ac{i}',f'conn{i}']
        lines.append(f' writeln("GTXEFFECT|{identity}|", '+', "|", '.join(output)+');')
        if air['tasks']:
            lines.append(f' writeln("GTXATTRIBUTION|{identity}|",(int)groundLoss{i},"|",(int)airLoss{i},"|",(int)airEquipment{i});')
    lines += [' network=Math.Max(0,Math.Min(100,network));',
              (' organization=Math.Max(0,Math.Min(100,organization-15+5*hidden));' if spec['profile']=='underground' else ''),
              f" int turn={mission['turn']}; turn=turn+1;"]
    owner=missions.objective_team(spec);opponent='blue' if owner=='red' else 'red'
    condition={'rail':'network<=20','underground':'organization>=50 && redAlive>0',
        'delay':f'{owner}Alive>=2 && {opponent}AtExit==0','breakout':f'{owner}AtExit>=2','reception':'accepted==1'}.get(spec['profile'],f'{owner}InGoal>0 && {opponent}InGoal==0')
    from gentactix import mission_termination
    success,terminal=mission_termination.native_expressions(spec,owner,wait_until_deadline=spec['profile'] in ('underground','delay'))
    lines += [f' bool condition={condition};', f" int progress=0; if (condition) {{ progress={mission['progress']}+1; }}",
              f' bool success={success};', f' bool terminal={terminal};',
              ' writeln("GTXMISSION|",turn,"|",progress,"|",network,"|",organization,"|",accepted,"|",(int)redAvailable,"|",(int)blueAvailable,"|",redInGoal,"|",blueInGoal,"|",(int)condition,"|",(int)terminal,"|",(int)success);']
    for i in range(len(depots)): lines.append(f' writeln("GTXDEPOT|{i}|",depot{i});')
    lines.append('end_execute')
    return {'version':VERSION,'input_digest':input_digest,'expected_turn':mission['turn']+1,
            'supply_binding_revision':1,'supply_nodes':copy.deepcopy(depots),
            'script':'\n'.join(lines)+'\n','units':units,'orders':list(commands.values()),'depots':len(depots),'air':air}


def parse(text, model, scene):
    """Validate complete native telemetry before constructing any state patch."""
    expected=set(scene['entities']); rows={}; depots={}; goal=None; fingerprints=[]; attribution={}
    for line in text.splitlines():
        if line.startswith('GTXERROR|'):
            raise ValueError('AFSIM原生约束拒收：'+line.split('|')[1])
        elif line.startswith('GTXMODEL|'):
            fingerprints.append(line.split('|')[1])
        elif line.startswith('GTXATTRIBUTION|'):
            parts=line.split('|')
            if len(parts)!=5 or parts[1] not in expected or parts[1] in attribution: raise ValueError('Native effect attribution incomplete or duplicated')
            values=list(map(int,parts[2:]))
            if any(v<0 for v in values): raise ValueError('Negative native effect attribution')
            attribution[parts[1]]=dict(zip(('ground_casualties','air_casualties','air_equipment_destroyed'),values))
        elif line.startswith('GTXEFFECT|'):
            parts=line.split('|'); identity=parts[1]
            if identity not in expected or identity in rows or len(parts)!=len(UNIT_FIELDS)+2: raise ValueError('Native unit telemetry mismatch')
            values=[float(x) for x in parts[2:]]
            if any(not math.isfinite(x) for x in values): raise ValueError('Non-finite native ledger')
            rows[identity]=dict(zip(UNIT_FIELDS,values))
        elif line.startswith('GTXDEPOT|'):
            parts=line.split('|'); index=int(parts[1])
            if index in depots: raise ValueError('Duplicate native depot')
            depots[index]=float(parts[2])
        elif line.startswith('GTXMISSION|'):
            if goal is not None: raise ValueError('Duplicate native objective result')
            values=[float(x) for x in line.split('|')[1:]]
            if len(values)!=len(MISSION_FIELDS) or any(not math.isfinite(x) for x in values): raise ValueError('Native objective telemetry mismatch')
            goal=dict(zip(MISSION_FIELDS,values))
    if set(rows)!=expected or set(depots)!=set(range(model['depots'])) or goal is None:
        raise ValueError('Incomplete native rules result; world unchanged')
    if fingerprints!=[model['input_digest']] or goal['turn']!=model['expected_turn']:
        raise ValueError('Native result belongs to a different input or turn')
    if any(not math.isfinite(value) or value<0 for value in depots.values()): raise ValueError('Invalid native depot stock')
    for row in rows.values():
        if any(value<0 for key,value in row.items() if key!='connectivity') or row['connectivity'] not in (-1,0,1):
            raise ValueError('Invalid native unit quantities')
        if any(row[key] != int(row[key]) for key in ('current','casualties','noncombat_losses','operational','destroyed')):
            raise ValueError('Non-integral native personnel or equipment count')
    validate_supply_draws(model, scene, rows, depots)
    if any(goal[key] not in (0,1) for key in ('condition','accepted','terminal','success')):
        raise ValueError('Invalid native objective flags')
    if model['air']['tasks'] or model.get('combined'):
        if set(attribution)!=expected: raise ValueError('Missing native air/ground attribution')
        previous={(team,u['name']):u for team,u in model['units']}
        for identity,counts in attribution.items():
            entry=scene['entities'][identity]; old=previous[(entry['team'],entry['name'])]; row=rows[identity]
            if counts['ground_casualties']+counts['air_casualties'] != row['casualties']-old['personnel']['casualties'] or (not model.get('combined') and counts['air_equipment_destroyed']>row['destroyed']-old['equipment'][0]['destroyed']):
                raise ValueError('Native effect attribution does not balance actual losses')
    air_operations=afsim_air.decode(text,model['air'],scene['seconds'])
    if air_operations:
        identities={v['name']:k for k,v in scene['entities'].items()}
        for task in air_operations['missions']:
            task['target_turn_effects']={'basis':'shared_target_turn_totals; do_not_sum_between_tasks',
                **attribution[identities[task['target']]]}
        air_operations['recent_missions']=(model['air']['state'].get('recent_missions',[])+copy.deepcopy(air_operations['missions']))[-16:]
    result={'version':VERSION,'input_digest':model['input_digest'],'units':rows,'depots':depots,'mission':goal,
            'air_operations':air_operations,'attribution':attribution}
    if model.get('combined'):
        from . import afsim_split_supply
        result['split_supply']=afsim_split_supply.parse(text,model,scene,rows,depots)
        from . import afsim_combined
        result['combined_arms']=afsim_combined.parse(text,model,scene,accounts=rows)
        from . import afsim_formation_parts
        result['partition_state']=afsim_formation_parts.parse(text,model,scene)
        if model.get('crossing_inputs'):
            from . import afsim_crossing
            afsim_crossing.validate_cargo(text,result,model,scene)
    return result


def validate_supply_draws(model, scene, rows, stocks):
    """Check per-depot native transfers, without allocating or executing supply."""
    revision = model.get('supply_binding_revision')
    if revision is None:
        return  # Old retained native artifacts did not contain this evidence.
    if revision != 1:
        raise ValueError('补给仓库绑定回执版本不支持')
    nodes = model['supply_nodes']
    draws = {n['id']: 0.0 for n in nodes}
    if len(draws) != len(nodes):
        raise ValueError('补给仓库绑定身份重复')
    old = {(team, u['name']): u for team, u in model['units']}
    for identity, row in rows.items():
        entry = scene['entities'][identity]
        unit = old[(entry['team'], entry['name'])]
        node = supply.bound_node({'supply_nodes': nodes}, entry['team'], unit)
        draws[node['id']] += row['delivery']
    for index, node in enumerate(nodes):
        expected = node['stock'] - draws[node['id']]
        if not math.isclose(stocks[index], expected, rel_tol=0, abs_tol=1e-6):
            raise ValueError('补给仓库 ' + node['id'] + ' 原生到货与扣库不守恒')


def apply_telemetry(telemetry, model, scene, observed):
    """Decode engine output; no Python damage/supply/objective executor is used."""
    if telemetry.get('version')!=VERSION or telemetry.get('input_digest')!=model['input_digest']:
        raise ValueError('Native rules version or input mismatch')
    rows,depots,goal=telemetry['units'],telemetry['depots'],telemetry['mission']
    after=copy.deepcopy(observed); index={(t,u['name']):u for t,u in missions.units(after)}; ledger=[]
    if telemetry.get('air_operations') is not None:
        after['air_operations']=copy.deepcopy(telemetry['air_operations'])
    for identity,row in rows.items():
        entity=scene['entities'][identity]; u=index[(entity['team'],entity['name'])]
        u['personnel'].update({key:int(row[key]) for key in ('current','casualties','noncombat_losses')})
        u['personnel']['calculation_source']=VERSION
        counts=telemetry.get('attribution',{}).get(identity)
        if counts and any(counts.values()):
            u['last_combat_effects']={'turn':int(goal['turn']),'source':VERSION,**counts}
        u['equipment'][0].update({key:int(row[key]) for key in ('operational','destroyed')})
        u['equipment'][0]['calculation_source']=VERSION
        u['logistics'].update(food=row['food'],ammo=row['ammo']); u['hp']=row['hp100']/100; u['supply']=row['supply']
        if next(unit for _,unit in model['units'] if unit['name']==u['name'])['personnel']['current']>0:
            action=next((o['action'] for o in model['orders'] if o['unit']==u['name']),'hold')
            ledger.append({'unit':u['name'],'action':action,'supply_status':{1:'未切断',0:'已切断',-1:'未知'}[row['connectivity']],
                'source_node_id':u['supply_node_id'],
                **{key:row[key] for key in ('delivery','food_spent','ammo_spent')},'food_after':row['food'],'ammo_after':row['ammo'],
                'source':VERSION,'delivery_basis':'native_gross_receipt',
                **({'normalized_resource_scale':formation_parts.scale(u)} if formation_parts.is_fragment(u) else {})})
    for i,stock in depots.items():
        after['supply_nodes'][int(i)]['stock']=stock
        after['supply_nodes'][int(i)]['calculation_source']=VERSION
    mission=after['mission']
    for key in ('turn','progress','network','organization'): mission[key]=int(goal[key])
    mission['accepted']=bool(goal['accepted']); mission['ledger']=ledger; mission['last_orders']=copy.deepcopy(model['orders'])
    mission['metrics']={key:int(goal[key]) for key in ('red_available','blue_available','red_in_goal','blue_in_goal','network','organization')}
    mission['metrics']['condition']=bool(goal['condition'])
    owner=missions.objective_team(mission['definition']);opponent='blue' if owner=='red' else 'red'
    if goal['terminal']:
        mission.update(status='completed',winner=missions.goal_winner(after,goal['success']),
            reason='程序目标达成' if goal['success'] else ('红方' if owner=='red' else '蓝方')+'无可用人员' if goal[owner+'_available']==0 else '截止回合目标未达成')
    after['engagements']=[]
    previous={u['name']:(team,u) for team,u in model['units']}
    for order in model['orders']:
        if order['action']=='fire':
            team,attacker=previous[order['unit']]; _,victim=previous[order['target']]
            after['engagements'].append({'attacker':order['unit'],'attacker_team':team,'attacker_pos':[attacker['lat'],attacker['lng']],
                'lat':victim['lat'],'lng':victim['lng'],'type':'AFSIM教学规则交战','description':'AFSIM后台执行固定教学模型，非历史杀伤率标定'})
    # Air tasks have their own validated native route/events. Do not mislabel a
    # ground requester's gun range/orientation as the aircraft's strike geometry.
    if model.get('combined'):
        from . import afsim_combined
        afsim_combined.apply(after,telemetry,scene,model)
        from . import afsim_formation_parts
        afsim_formation_parts.apply(after,telemetry.get('partition_state',{}),scene)
        from . import afsim_split_supply
        afsim_split_supply.apply(after,telemetry.get('split_supply'),scene)
    return after


def decode(text, model, scene, observed):
    return apply_telemetry(parse(text,model,scene),model,scene,observed)
