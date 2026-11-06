"""Frozen operation-zone geometry within the existing physical world.

Straight spherical corridors constrain transitions; this module neither moves
platforms nor settles resources. Outside the operation is still inside the world.
"""
import math
import re
from . import missions, terrain_process

VERSION = 'operation-boundary-1'
ARRIVAL_KM = .01


def configuration(world):
    return world.get('mission', {}).get('definition', {}).get('operation_boundary')


def inside(config, point):
    return missions.distance(config['center'], point) <= config['radius_km'] + 1e-6


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('作战区及出入通路须说明来源或估计依据')


def validate(config, area, *, actors=(), plan=None):
    if (not isinstance(config, dict) or set(config) != {'version','center','radius_km','routes','assumption'}
            or config['version'] != VERSION or not isinstance(plan,dict)):
        raise ValueError('作战区边界须绑定明确版本、几何、通路及会战目标图')
    terrain_process._point(config['center']);_text(config['assumption'])
    radius=config['radius_km']
    if (type(radius) not in (int,float) or not math.isfinite(radius) or radius < .05
            or missions.distance(config['center'],area['center']) + radius >= area['radius_km']):
        raise ValueError('作战区域须明确小于并完全位于仿真世界范围内')
    if not isinstance(config['routes'],list) or not 1 <= len(config['routes']) <= 64:
        raise ValueError('须登记1至64条明确出入通路，不能仅修改场外标签')
    ids=set()
    for route in config['routes']:
        if not isinstance(route,dict) or set(route)!={'id','team','inside','outside','corridor_km','assumption'}:
            raise ValueError('出入通路字段不完整或越界')
        if (not isinstance(route['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,79}',route['id'])
                or route['id'] in ids or route['team'] not in ('red','blue')):
            raise ValueError('出入通路身份须唯一且绑定阵营')
        ids.add(route['id']);_text(route['assumption'])
        width=route['corridor_km']
        if type(width) not in (int,float) or not math.isfinite(width) or not .001 <= width <= 2:
            raise ValueError('出入通路半宽须为0.001至2公里的明确估计')
        for key in ('inside','outside'):
            terrain_process._point(route[key])
            if missions.distance(route[key],area['center'])+width > area['radius_km']:
                raise ValueError('通路及其半宽须位于仿真世界内')
        if not inside(config,route['inside']) or inside(config,route['outside']):
            raise ValueError('出入通路须连接作战区内点与作战区外点')
        if missions.distance(route['inside'],route['outside']) < 2*ARRIVAL_KM:
            raise ValueError('通路长度不能小于到达容差，不能原地切换参与状态')
    for actor in actors:
        if not isinstance(actor,dict):raise ValueError('作战区单位参数须为对象')
        point=actor.get('position')
        if point is not None and not inside(config,point):
            raise ValueError('本版开局单位须位于作战区内；后续场外来援须另登记过程')
    # A spatial objective outside this zone needs an explicit exit objective type.
    # Do not accept an unreachable graph whose ready-unit filter excludes exits.
    if not isinstance(plan.get('nodes'),list):raise ValueError('作战区须绑定明确目标节点数组')
    for node in plan['nodes']:
        if not isinstance(node,dict):raise ValueError('作战区目标节点须为对象')
        region=node.get('condition',{}).get('region')
        if region and missions.distance(region['center'],config['center'])+region['radius_km'] > radius:
            raise ValueError('本版空间目标须在作战区内；区外突围目标需先扩展目标类型')


def _bearing(a,b):
    lat1,lat2=math.radians(a['lat']),math.radians(b['lat']);dl=math.radians(b['lng']-a['lng'])
    return math.atan2(math.sin(dl)*math.cos(lat2),math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dl))


def corridor_distance(point,route):
    """Distance to the finite short great-circle arc, in host spherical km."""
    a,b=route['inside'],route['outside'];radius=6371.0
    delta=missions.distance(a,point)/radius;heading=_bearing(a,point)-_bearing(a,b)
    along=math.atan2(math.sin(delta)*math.cos(heading),math.cos(delta))*radius
    if along < 0:return missions.distance(a,point)
    if along > missions.distance(a,b):return missions.distance(b,point)
    return abs(math.asin(max(-1,min(1,math.sin(delta)*math.sin(heading)))))*radius


def route_for(world, team, origin, request):
    config=configuration(world)
    if not config:return None
    endpoint='outside' if request['kind']=='withdraw' else 'inside'
    rows=[r for r in config['routes'] if r['team']==team
          and missions.distance(r[endpoint],request['destination']) <= ARRIVAL_KM
          and corridor_distance(origin,r) <= r['corridor_km'] + 1e-6]
    if len(rows)!=1:raise ValueError('退出／重返须使用本方唯一已登记通路；请先机动至通路区内点')
    return rows[0]


def check_order(world, unit, team, order):
    config=configuration(world)
    if not config:return
    origin={k:unit[k] for k in ('lat','lng')}
    if not inside(config,origin) and order['action'] in ('fire','bombard','suppress','capture','air_support','sabotage','accept'):
        raise ValueError('部队已在作战区外，须沿登记通路实际返回后再执行进攻行动')
    if order['action']!='move':return
    point={k:order.get(k) for k in ('lat','lng')};terrain_process._point(point)
    request=order.get('participation')
    if request:
        target_inside=inside(config,request['destination'])
        # Legacy rear-reserve operations wholly within the zone retain semantics.
        if inside(config,origin) and target_inside:return
        if request['kind']=='withdraw' and target_inside or request['kind']=='reenter' and not target_inside:
            raise ValueError('出入意图与作战区内外目的地不一致')
        route=route_for(world,team,origin,request)
        if corridor_distance(point,route)>route['corridor_km']+1e-6:
            raise ValueError('本轮实际机动段偏离登记出入通路')
    elif (inside(config,origin)!=inside(config,point) or not inside(config,origin)
            and corridor_distance(config['center'],{'inside':origin,'outside':point}) < config['radius_km']):
        raise ValueError('跨作战区边界须明确退出或重返意图，不能普通移动后只改标签')


def validate_motion(before, after, orders):
    """Reject unsupported observations; never repair a backend's coordinates."""
    if not configuration(before):return
    checked={o['unit']:o for o in orders};previous={u['name']:(team,u) for team,u in missions.units(before)}
    for _,unit in missions.units(after):
        team,old=previous[unit['name']]
        if missions.distance(old,unit)<1e-7:continue
        order=checked.get(unit['name'])
        if not order or order['action']!='move':raise ValueError('执行后端不能无移动命令越界或改变实际位置')
        check_order(before,old,team,{**order,'lat':unit['lat'],'lng':unit['lng']})
        if order.get('participation') and order['participation']['kind']=='withdraw' and inside(configuration(before),order['participation']['destination']):
            if not inside(configuration(before),unit):raise ValueError('后方待命命令不能产生场外坐标')


def observation(world):
    config=configuration(world)
    if not config:return None
    return dict(version=VERSION,center=config['center'],radius_km=config['radius_km'],routes=config['routes'],
        scope='估计作战区与直线出入通路；场外仍在同一物理世界，保留真实位置、资源和受击可能；无DEM、道路容量或退役归档。')


def choices(world,unit,team):
    config=configuration(world)
    if not config:return []
    return [dict(id=r['id'],inside=r['inside'],outside=r['outside'],
        on_corridor=corridor_distance(unit,r)<=r['corridor_km']+1e-6) for r in config['routes'] if r['team']==team]
