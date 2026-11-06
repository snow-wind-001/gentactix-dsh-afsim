"""Frozen parallel passage inputs and read-only routing/receipt selection.

One declared river may have several independent sites. This module never moves
formations or allocates service. Queue work and actual positions belong to WSF.
"""
import copy
from . import crossings, missions

VERSION = 'formation-crossing-network-1'
FROZEN = ('id','name','lat','lng','capacity','crossing_model')
BASE = {'id','name','lat','lng','progress','integrity','materials','capacity','used','crossing_model'}


def enabled(world):
    return 'crossing_network' in world.get('combined_arms',{}).get('bridge',{})


def sites(world):
    bridge=world['combined_arms']['bridge']
    return [bridge]+bridge.get('crossing_network',{}).get('sites',[])


def by_id(world, identity):
    found=[s for s in sites(world) if s['id']==identity]
    if len(found)!=1:raise ValueError('渡运任务引用未知或重复设施')
    return found[0]


def validate(bridge, initial=None, area=None):
    net=bridge.get('crossing_network')
    if 'crossing_network' not in bridge:
        if initial and 'crossing_network' in initial:raise ValueError('不能删除冻结渡运网络')
        return
    crossings.fields(net,{'version','sites'},'多渡点网络')
    if net['version']!=VERSION or not isinstance(net['sites'],list) or not 1<=len(net['sites'])<=7:
        raise ValueError('多渡点网络版本非法或设施总数不在2至8内')
    all_sites=[bridge]+net['sites'];ids=[]
    for i,s in enumerate(all_sites):
        if not isinstance(s,dict) or not isinstance(s.get('crossing_model'),dict):
            raise ValueError('多渡点每个设施必须声明完整crossing_model，不能只增加展示点')
        if i:crossings.fields(s,BASE|({'crossing_receipt'} if 'crossing_receipt' in s else set()),'独立渡点')
        if not isinstance(s.get('id'),str) or not s['id'].strip() or not isinstance(s.get('name'),str) or not s['name'].strip():
            raise ValueError('渡点身份不能为空')
        ids.append(s['id']);crossings.point({k:s[k] for k in ('lat','lng')})
        for k in ('progress','integrity'):crossings.number(s[k],0,100,True)
        for k in ('materials','capacity','used'):crossings.number(s[k],0,1e7,True)
        crossings.validate_model(s['crossing_model'])
        if s['crossing_model']['barrier']!=bridge['crossing_model']['barrier']:
            raise ValueError('本版多渡点须共享同一有限河线；连续跨越多条河流须另建路线模型')
        if s['crossing_model'].get('ferry'):
            raise ValueError('多渡点尚未接入具名舟艇调度，不得降级为抽象吞吐')
        if area:
            points=[s]+list(s['crossing_model']['barrier'].values())+list(s['crossing_model']['banks'].values())
            if any(missions.distance(p,area['center'])>area['radius_km'] for p in points):
                raise ValueError('多渡点河线、设施或岸点超出计算范围')
    if len(set(ids))!=len(ids):raise ValueError('渡点ID重复')
    if initial is not None:
        frozen=[initial]+initial.get('crossing_network',{}).get('sites',[])
        if len(frozen)!=len(all_sites) or initial.get('crossing_network',{}).get('version')!=VERSION:
            raise ValueError('不能改写冻结渡点网络')
        if any(any(s.get(k)!=old.get(k) for k in FROZEN) for s,old in zip(all_sites,frozen)):
            raise ValueError('不能改写冻结渡点的身份、顺序、位置或能力')


def projected(world, site):
    """Read-only single-site view for existing guards, never a simulation world."""
    result=copy.deepcopy(world)
    result['combined_arms']['bridge']=copy.deepcopy(site)
    result['combined_arms']['bridge'].pop('crossing_network',None)
    return result


def select(world, origin, target):
    # Stable minimum declared route length; no invented threat-aware routing.
    candidates=[]
    for index,site in enumerate(sites(world)):
        route=crossings.bank_route(origin,target,site['crossing_model'])
        if len(route)==1:continue
        path=[origin]+route
        candidates.append((sum(missions.distance(a,b) for a,b in zip(path,path[1:])),index,site))
    return min(candidates,key=lambda r:(r[0],r[1]))[2] if candidates else None


def plan(world, unit, order):
    if not enabled(world):return crossings.plan(world['combined_arms']['bridge'],unit,order)
    prior=unit.get('crossing')
    keep=prior and (prior['status']=='transit' or
        (prior['status']=='queued' and prior.get('intent_id')==order.get('intent_id')
         and missions.distance(prior['target'],order)<.000001))
    site=by_id(world,prior['site_id']) if keep else select(world,unit,order)
    if site is None:return None
    actor=copy.deepcopy(unit)
    if prior and prior['site_id']!=site['id']:actor.pop('crossing',None)
    return crossings.plan(site,actor,order)


def engineering_site(world, unit):
    return min(sites(world),key=lambda s:min(missions.distance(unit,p) for p in
        (list(s['crossing_model']['banks'].values()) if s.get('crossing_model') else [s])))


def observation(world):
    return {'version':VERSION,'scope':'同一河线的独立渡点；共用部队与仓库；输入约束不是执行回执',
        'route_policy':'最短登记通道距离；同距按冻结顺序；未完成的同一指令保持原渡点；不自动避开关闭或受威胁渡点',
        'sites':[{'site_id':s['id'],'name':s['name'],'progress':s['progress'],'integrity':s['integrity'],
                  **crossings.observation(projected(world,s))} for s in sites(world)]}


def validate_transition(before,after,updates,orders,seconds,result):
    """Reuse single-site guards on evidence views; never calculate a turn."""
    validate(after['combined_arms']['bridge'],before['combined_arms']['bridge'])
    previous={u['name']:u for _,u in missions.units(before)}
    following={u['name']:u for _,u in missions.units(after)}
    assignments={};engineering={}
    for o in orders:
        u=previous[o['unit']]
        route=plan(before,u,o) if o['action']=='move' else None
        task=route['task'] if route else u.get('crossing')
        if task:assignments[u['name']]=task['site_id']
        if o['action'] in ('build_bridge','demolish'):engineering[u['name']]=engineering_site(before,u)['id']
    for u in previous.values():
        if u.get('crossing'):assignments.setdefault(u['name'],u['crossing']['site_id'])
    if set(updates)-set(assignments):raise ValueError('没有登记任务的单位不得提交多渡点回执')
    raw=result.get('combined_arms',{}).get('bridge',{})
    raw_sites=[raw]+raw.get('crossing_network',{}).get('sites',[])
    nodes={n['id']:n for n in before['supply_nodes']}
    for index,site in enumerate(sites(before)):
        identity=site['id'];start=projected(before,site);end=projected(after,by_id(after,identity))
        for w in (start,end):
            for _,u in missions.units(w):
                if assignments.get(u['name'])!=identity or u.get('crossing',{}).get('site_id')!=identity:u.pop('crossing',None)
        selected=[]
        for o in orders:
            owner=engineering.get(o['unit']) if o['action'] in ('build_bridge','demolish') else assignments.get(o['unit'])
            selected.append(copy.deepcopy(o) if owner==identity else {'unit':o['unit'],'action':'hold'})
        output=copy.deepcopy(result)
        output['combined_arms']={'bridge':raw_sites[index] if index<len(raw_sites) else {}}
        for r in output['resource_ledger']['units']:
            u=previous[r['unit']];chosen=select(before,nodes[u['supply_node_id']],following[u['name']])
            if not chosen or chosen['id']!=identity:r.update(delivery=0,received={})
        crossings.validate_model_transition(start,end,{k:v for k,v in updates.items() if assignments[k]==identity},selected,seconds,output)
        by_id(after,identity)['crossing_receipt']=end['combined_arms']['bridge']['crossing_receipt']
        for _,u in missions.units(end):
            if assignments.get(u['name'])==identity and u.get('crossing'):following[u['name']]['crossing']=u['crossing']
