"""Explicit finite barriers and straight road corridors; no implicit DEM/LOS."""
import math
from . import missions

VERSION = 'local-terrain-1'


def configuration(world):
    return world.get('mission', {}).get('definition', {}).get('terrain_model')


def _point(p):
    if (not isinstance(p, dict) or set(p) != {'lat', 'lng'}
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in p.values())
            or abs(p['lat']) > 90 or abs(p['lng']) > 180):
        raise ValueError('地形坐标须为有限lat/lng')


def validate(cfg, area):
    if (not isinstance(cfg, dict) or set(cfg) != {'version', 'assumption', 'barriers', 'roads'}
            or cfg['version'] != VERSION or not isinstance(cfg['assumption'], str) or not cfg['assumption'].strip()):
        raise ValueError('地形模型须登记版本、来源与估计范围')
    ids = set()
    for kind, fields in (('barriers', {'id', 'a', 'b', 'blocks', 'source'}),
                         ('roads', {'id', 'a', 'b', 'width_m', 'speed_factor', 'source'})):
        if not isinstance(cfg[kind], list) or len(cfg[kind]) > 64:
            raise ValueError('地形每类最多64项')
        for row in cfg[kind]:
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError('地形字段非法')
            if (not isinstance(row['id'], str) or not row['id'] or row['id'] in ids
                    or not isinstance(row['source'], str) or not row['source'].strip()):
                raise ValueError('地形须有不重复身份和来源/估计说明')
            ids.add(row['id'])
            for p in (row['a'], row['b']):
                _point(p)
                if missions.distance(p, area['center']) > area['radius_km']:
                    raise ValueError('地形线端点超出计算区域')
            if missions.distance(row['a'], row['b']) < .001:
                raise ValueError('地形线端点不能重合')
            if kind == 'barriers':
                blocks = row['blocks']
                if not isinstance(blocks, list) or not blocks or len(set(blocks)) != len(blocks) or set(blocks) - {'movement', 'direct_fire'}:
                    raise ValueError('地形障碍只能显式声明阻断移动或直射')
            else:
                for k, low, high in (('width_m', 1, 1000), ('speed_factor', .1, 3)):
                    if type(row[k]) not in (int, float) or not math.isfinite(row[k]) or not low <= row[k] <= high:
                        raise ValueError('道路宽度或速度系数超限')


def _cross(a, b, c):
    return (b['lng']-a['lng'])*(c['lat']-a['lat'])-(b['lat']-a['lat'])*(c['lng']-a['lng'])


def intersects(a, b, c, d):
    if (max(a['lat'], b['lat']) < min(c['lat'], d['lat']) or max(c['lat'], d['lat']) < min(a['lat'], b['lat'])
            or max(a['lng'], b['lng']) < min(c['lng'], d['lng']) or max(c['lng'], d['lng']) < min(a['lng'], b['lng'])):
        return False
    return _cross(a,b,c)*_cross(a,b,d) <= 0 and _cross(c,d,a)*_cross(c,d,b) <= 0


def blocked(world, a, b, kind):
    cfg = configuration(world)
    return bool(cfg and any(kind in r['blocks'] and intersects(a,b,r['a'],r['b']) for r in cfg['barriers']))


def road_factor(world, origin, destination):
    cfg = configuration(world)
    if not cfg or destination is None: return 1
    # Both endpoints must lie on one straight registered road corridor. Curved
    # routes need separate orders; no off-road shortcut inherits road speed.
    for r in cfg['roads']:
        a, b = r['a'], r['b']
        factor = math.cos(math.radians(a['lat']))
        dx,dy = (b['lng']-a['lng'])*factor*111, (b['lat']-a['lat'])*111
        def distance(p):
            px,py = (p['lng']-a['lng'])*factor*111, (p['lat']-a['lat'])*111
            t = max(0,min(1,(px*dx+py*dy)/(dx*dx+dy*dy)))
            return math.hypot(px-t*dx,py-t*dy)
        if all(distance(p) <= r['width_m']/2000 for p in (origin,destination)):
            return r['speed_factor']
    return 1


def check_order(world, order):
    if not configuration(world):return
    index = {u['name']:u for _,u in missions.units(world)}
    unit = index.get(order.get('unit'))
    if not unit:return
    kind = 'movement' if order['action'] == 'move' else 'direct_fire' if order['action'] == 'fire' else None
    target = order if kind == 'movement' else index.get(order.get('target'))
    if kind == 'movement': _point({k:order.get(k) for k in ('lat','lng')})
    if kind and target and blocked(world,unit,target,kind):
        raise ValueError('登记地形阻断该移动/直射路径，请选择通路或改用间接火力')
