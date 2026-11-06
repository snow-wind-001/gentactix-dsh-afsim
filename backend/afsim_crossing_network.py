"""Independent native queues in one WSF world, with shared combat and depots."""
import copy
from gentactix import crossing_network as network, crossings, missions
from .afsim_literals import number as literal


def hub_id(index):
    return 'gtx_ca_hub' if index==0 else 'gtx_cross_site_'+str(index)


def setup(world):
    from .afsim_combined import put,n
    from .afsim_world import _location
    declarations=[];initial=[]
    for i,s in enumerate(network.sites(world)[1:],1):
        declarations += [f'platform {hub_id(i)} WSF_PLATFORM',f' position {_location(s)}','end_platform']
        p='netHub'+str(i)
        initial.append(f' WsfPlatform {p}=WsfSimulation.FindPlatform("{hub_id(i)}");')
        initial += [put(p,k,n(s[k])) for k in ('progress','integrity','materials','capacity')]
        initial += [put(p,k,'0') for k in ('used','cross_work','cross_cargo_work','cross_busy_until')]
    return declarations,initial


def functions(world, script):
    choices=[]
    for i in range(len(network.sites(world))):
        choices.append(f' if (index=={i}) {{ return WsfSimulation.FindPlatform("{hub_id(i)}"); }}')
    selector='\n'.join(['script WsfPlatform GtxCrossHub(int index)']+choices+[
        ' writeln("GTXERROR|unknown_crossing_site"); return WsfSimulation.FindPlatform("gtx_ca_hub");','end_script'])
    script=script.replace('WsfSimulation.FindPlatform("gtx_ca_hub")','GtxCrossHub((int)actor.AuxDataDouble("ca_cross_site"))')
    old=f"double rate={literal(crossings.get_model(world)['throughput_work_per_hour']/3600,precision=12)};"
    assert old in script
    return selector+'\n'+script.replace(old,'double rate=actor.AuxDataDouble("ca_cross_rate");')


def actor_setup(world, unit, entity, p):
    task=entity.get('crossing_plan',{}).get('task') or unit.get('crossing')
    index=next((i for i,s in enumerate(network.sites(world)) if task and s['id']==task['site_id']),0)
    rate=network.sites(world)[index]['crossing_model']['throughput_work_per_hour']/3600
    return [f' {p}.SetAuxData("ca_cross_site",(double){index});',f' {p}.SetAuxData("ca_cross_rate",(double){literal(rate,precision=12)});']


def supply_setup(world, p, i, node):
    """Select from actual native end positions; no Python position prediction."""
    from .afsim_combined import n
    lines=[f' int supplySite{i}=0;',f' double entryLat{i}=0; double entryLng{i}=0; double exitLat{i}=0; double exitLng{i}=0;',
           f' bool supplyCross{i}=GtxCrosses({n(node["lat"])},{n(node["lng"])},{p}.Latitude(),{p}.Longitude());',
           f' double supplyBudget{i}=0; double supplyWeight{i}=0; bool supplyOpen{i}=false;',
           f' if (supplyCross{i}) {{ routeKm{i}=1000000000.0;']
    for index,s in enumerate(network.sites(world)):
        model=s['crossing_model'];a,b=model['barrier'].values()
        bank='a' if crossings.orientation(node,a,b)*crossings.orientation(model['banks']['a'],a,b)>=0 else 'b'
        e,x=model['banks'][bank],model['banks']['b' if bank=='a' else 'a']
        distance=f'GtxDistance({n(node["lat"])},{n(node["lng"])},{n(e["lat"])},{n(e["lng"])})+GtxDistance({n(e["lat"])},{n(e["lng"])},{n(x["lat"])},{n(x["lng"])})+GtxDistance({n(x["lat"])},{n(x["lng"])},{p}.Latitude(),{p}.Longitude())'
        lines += [f' double candidate{i}_{index}={distance};',f' if (candidate{i}_{index}<routeKm{i}) {{',
                  f' routeKm{i}=candidate{i}_{index}; supplySite{i}={index};',
                  f' entryLat{i}={n(e["lat"])}; entryLng{i}={n(e["lng"])}; exitLat{i}={n(x["lat"])}; exitLng{i}={n(x["lng"])};',
                  f' supplyBudget{i}={n(model["throughput_work_per_hour"])}; supplyWeight{i}={n(model["supply_work_per_unit"])};',
                  f' supplyOpen{i}={str(s["progress"]>=100 and s["integrity"]>=50).lower()};',' }']
    lines += [' }',f' WsfPlatform supplyHub{i}=GtxCrossHub(supplySite{i});',
              f' if (supplyCross{i} && !supplyOpen{i}) {{ conn{i}=0; }}']
    return lines


def blocked(i,j,node,radius):
    from .afsim_combined import n
    nodes=[(n(node['lat']),n(node['lng'])),(f'entryLat{i}',f'entryLng{i}'),(f'exitLat{i}',f'exitLng{i}'),(f'p{i}.Latitude()',f'p{i}.Longitude()')]
    segments=' || '.join(f'GtxBlocked({a},{b},{c},{d},q{i}_{j}.Latitude(),q{i}_{j}.Longitude(),{n(radius)})'
                        for (a,b),(c,d) in zip(nodes,nodes[1:]))
    direct=f'GtxBlocked({nodes[0][0]},{nodes[0][1]},p{i}.Latitude(),p{i}.Longitude(),q{i}_{j}.Latitude(),q{i}_{j}.Longitude(),{n(radius)})'
    return f'((supplyCross{i} && ({segments})) || (!supplyCross{i} && {direct}))'


def finish(scene,world):
    from . import afsim_crossing
    lines=[]
    for i,s in enumerate(network.sites(world)[1:],1):
        p='netFinish'+str(i)
        lines += [f' WsfPlatform {p}=GtxCrossHub({i});']
        lines += [line.replace('GTXCROSSCAP|',f'GTXNETCAP|{i}|').replace('hub.',p+'.')
                  for line in afsim_crossing.finish_capacity(scene,network.projected(world,s))]
        lines += [f' writeln("GTXNETFAC|{i}|",'+',"|",'.join(f'(int){p}.AuxDataDouble("ca_{k}")' for k in ('progress','integrity','materials','used'))+');']
    return lines


def parse(text,scene,before):
    from . import afsim_crossing
    sites=network.sites(before);caps={};facilities={};assigned={}
    old={u['name']:u for _,u in missions.units(before)}
    for identity,entity in scene['entities'].items():
        task=entity.get('crossing_plan',{}).get('task') or old[entity['name']].get('crossing')
        assigned[identity]=next((i for i,s in enumerate(sites) if task and s['id']==task['site_id']),0)
    for line in text.splitlines():
        p=line.split('|')
        if p[0] not in ('GTXNETCAP','GTXNETFAC'):continue
        i=int(p[1]);target=caps if p[0]=='GTXNETCAP' else facilities
        if i not in range(1,len(sites)) or i in target:raise ValueError('多渡点原生回执未知或重复')
        if p[0]=='GTXNETCAP':
            if len(p)!=8:raise ValueError('多渡点容量回执缺项')
            target[i]='GTXCROSSCAP|'+'|'.join(p[2:])
        else:
            if len(p)!=6:raise ValueError('多渡点设施回执缺项')
            target[i]=dict(zip(('progress','integrity','materials','used'),map(int,p[2:])))
    if set(caps)!=set(range(1,len(sites))) or set(facilities)!=set(caps):raise ValueError('多渡点原生证据不完整')
    results=[]
    for i,s in enumerate(sites):
        subset={k:v for k,v in scene['entities'].items() if assigned[k]==i};lines=[]
        for line in text.splitlines():
            p=line.split('|')
            if p[0].startswith('GTXNET'):continue
            if p[0] in ('GTXPOS','GTXCROSS','GTXCROSSEVENT','GTXCEVENT') and (len(p)<2 or p[1] not in subset):
                if len(p)>1 and p[1] not in scene['entities']:raise ValueError('渡运回执含未知实体')
                continue
            if p[0]=='GTXCROSSCAP' and i:continue
            lines.append(line)
        if i:lines.append(caps[i])
        result=afsim_crossing.parse('\n'.join(lines),{**scene,'entities':subset},network.projected(before,s))
        result['site_id']=s['id']
        if i:result['facility']=facilities[i]
        results.append(result)
    return {'tasks':{k:v for r in results for k,v in r['tasks'].items()},'capacity':results[0]['capacity'],'sites':results}


def validate_cargo(text,telemetry,model,scene):
    from . import afsim_world
    inputs=model['crossing_inputs']
    before={'combined_arms':model['before_combined'],'supply_nodes':inputs['nodes'],
            'mission':{'definition':{'combined_rules':inputs['rules']}},
            **{t+'_units':[u for team,u in model['units'] if team==t] for t in ('red','blue')}}
    positions=afsim_world.parse_observations(text,scene);after=copy.deepcopy(before)
    old={u['name']:u for _,u in missions.units(before)};new={u['name']:u for _,u in missions.units(after)}
    grouped={s['id']:[] for s in network.sites(before)}
    for identity,e in scene['entities'].items():
        name=e['name'];new[name].update(positions[identity]);u=old[name]
        node=next(n for n in before['supply_nodes'] if n['id']==u['supply_node_id'])
        s=network.select(before,node,new[name])
        if s:grouped[s['id']].append({'unit':name,'delivery':telemetry['units'][identity]['delivery'],
                                   'received':telemetry['combined_arms']['received'][identity]})
    for site,receipt in zip(network.sites(before),telemetry['combined_arms']['crossing']['sites']):
        actual=crossings.cargo_work(network.projected(before,site),after,{'resource_ledger':{'units':grouped[site['id']]}},scene['seconds'])
        if abs(actual-receipt['capacity']['cargo_work'])>.003:raise ValueError('各渡点货运与实际分类到货不守恒')
