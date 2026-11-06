"""Shared vector vocabulary and versioned map overlays, independent of combat state."""
import copy
import html
import json
import math
import os
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

from . import commands, unit_types, adjudicator
ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((Path(__file__).with_name('military_symbols.json')).read_text())
REFERENCE=json.loads((Path(__file__).with_name('military_symbol_reference.json')).read_text())
SYMBOLS={r['id']:r for r in DATA['symbols']}
VERSION='military-plotting-1'
MAX_ITEMS=80


class Conflict(ValueError):pass


def catalog(query='',limit=80):
    q=str(query).strip().casefold()
    rows=[copy.deepcopy(x) for x in DATA['symbols'] if not q or q in json.dumps(x,ensure_ascii=False).casefold()]
    return {**{k:copy.deepcopy(v) for k,v in DATA.items() if k!='symbols'},'symbols':rows[:max(1,min(80,int(limit)))],
            'limits':{'items':MAX_ITEMS,'vertices':32,'label':80},'scope':'地图表达层；标注不参与AFSIM战斗、通路、传感器或目标结算。'}


def symbol(identity):
    if not isinstance(identity,str) or identity not in SYMBOLS:raise ValueError('未知或未审核的应用军标ID')
    return SYMBOLS[identity]


def unit_symbol(unit):
    kind=str(unit.get('type') or unit.get('类型') or unit.get('兵种') or unit.get('unit_type') or '').lower()
    profile=unit_types.classify_unit(kind)
    ident=profile['id'] if isinstance(profile,dict) else None
    formation=unit.get('formation');role=formation.get('role') if isinstance(formation,dict) else None
    gear=unit.get('equipment');gear=gear if isinstance(gear,list) else []
    count={x.get('category'):x['operational'] for x in gear if isinstance(x,dict) and type(x.get('operational')) in (int,float) and math.isfinite(x['operational'])}
    if role=='support' and count.get('artillery',0)>0:return 'artillery'
    if role=='armor' and count.get('armor',0)>0:return 'armor'
    mapping=DATA['unit_profile_symbols']
    if ident in mapping:return mapping[ident]
    for words,value in [(('防空','anti-air','air defense'),'air-defense'),(('炮','artillery'),'artillery'),(('舰','船','naval','ship'),'naval'),
        (('航空','飞机','fighter','aircraft'),'aircraft'),(('骑兵','cavalry'),'cavalry'),(('坦克','装甲','tank','armor'),'armor'),
        (('步兵','陆战','infantry','marine'),'infantry')]:
        if any(k in kind for k in words):return value
    return 'unknown'


def svg(identity,team='neutral',inactive=False):
    item=symbol(identity);color={'red':'#ef8882','blue':'#8abcf3','neutral':'#e7d6a6'}.get(team,'#e7d6a6')
    path=html.escape(item['path'],quote=True)
    return (f'<svg class="military-symbol" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true">'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"/>'
        +('<path d="M4 4l16 16M20 4 4 20" fill="none" stroke="#d5dce0" stroke-width="1.7"/>' if inactive else '')+'</svg>')


def unit_html(unit,team,override=None):
    ident=override if override in SYMBOLS and SYMBOLS[override]['geometry']=='point' else unit_symbol(unit)
    from .personnel_projection import inactive as personnel_inactive
    inactive=personnel_inactive(unit)
    name=next((str(unit[k]) for k in ('name','名称','单位名称','部队名称','unit_name') if unit.get(k)), '未知单位')
    return f'<div class="military-unit {"unit-inactive" if inactive else "unit-active"}" style="position:relative;width:36px;height:36px;pointer-events:none;background:#0a1c2bf0;border-radius:5px">{svg(ident,team,inactive)}<span class="unit-name" style="position:absolute;top:39px;left:50%;transform:translateX(-50%);white-space:nowrap;pointer-events:none;color:#e6eff3;background:#0a1c2bef;padding:2px 5px;border-radius:3px;font-size:11px">{html.escape(name)}{" · 已失能" if inactive else ""}</span></div>'


def _empty():return {'version':VERSION,'revision':0,'items':[],'unit_symbols':{}}


def _units(session):
    if not session.get('war_state'):return []
    view=commands.view(session)
    pairs={(t,commands.name_of(u)):u for t,u in commands.iter_units(session['war_state'])}
    return [{k:copy.deepcopy(u.get(k)) for k in ('id','name','team','position','present')}|
            {'auto_symbol':unit_symbol(pairs.get((u['team'],u['name']),{}))} for u in view['units']]


def view(session):
    state=copy.deepcopy(session.get('plotting_state') or _empty())
    return {**state,'turn':session.get('turn_count',0),'world_version':commands.fingerprint(session.get('war_state')),
            'units':_units(session),'scope':'展示标注，不是作战命令；计划/假设标注不证明历史部署或实际控制。'}


def point(value):
    if not isinstance(value,dict) or set(value)!={'lat','lng'}:raise ValueError('坐标须为lat/lng')
    for key,bound in [('lat',90),('lng',180)]:
        n=value[key]
        if type(n) not in (int,float) or not math.isfinite(n) or not -bound<=n<=bound:raise ValueError('坐标须为有限WGS84经纬度')
    return {k:float(value[k]) for k in ('lat','lng')}


def validate_item(row,session):
    allowed={'id','symbol_id','label','team','status','points','source','visible','unit_id'}
    if not isinstance(row,dict) or set(row)-allowed:raise ValueError('标注字段非法；不能提交SVG或战局状态')
    if not re.fullmatch('[a-f0-9]{32}',str(row.get('id',''))):raise ValueError('标注ID非法')
    spec=symbol(row.get('symbol_id'))
    if row.get('team') not in ('red','blue','neutral') or row.get('status') not in ('planned','observed','assumed'):raise ValueError('阵营或标注依据非法')
    for key,limit in [('label',80),('source',300)]:
        if not isinstance(row.get(key,''),str) or len(row.get(key,''))>limit:raise ValueError('标注文字过长或非法')
    if row['status']=='observed' and not str(row.get('source','')).strip():raise ValueError('观察/史料标注须说明来源；未知不能当作已核实')
    coords=row.get('points')
    low,high={'point':(1,1),'line':(2,32),'area':(3,32)}[spec['geometry']]
    if not isinstance(coords,list) or not low<=len(coords)<=high:raise ValueError('标注顶点数不符合几何类型')
    coords=[point(p) for p in coords]
    if len({(p['lat'],p['lng']) for p in coords})!=len(coords):raise ValueError('标注顶点不能重复')
    if spec['geometry']=='area':
        twice_area=sum(a['lng']*b['lat']-b['lng']*a['lat'] for a,b in zip(coords,coords[1:]+coords[:1]))
        if abs(twice_area)<1e-12:raise ValueError('地域顶点不能共线或退化')
    area=((session.get('war_state') or {}).get('mission') or {}).get('definition',{})
    if area.get('map_center'):
        center=area['map_center'];radius=area['map_radius_km']
        if any(adjudicator.distance_km((p['lat'],p['lng']),(center['lat'],center['lng']))>radius for p in coords):raise ValueError('标注离开当前局部想定边界')
    if 'visible' in row and type(row['visible']) is not bool:raise ValueError('显示开关须为布尔值')
    if row.get('unit_id'):
        if spec['geometry']!='point' or row['unit_id'] not in {u['id'] for u in _units(session)}:raise ValueError('只能绑定已存在的单位；绑定符号须为点')
    return {**copy.deepcopy(row),'points':coords,'label':row.get('label','').strip(),'source':row.get('source','').strip(),'visible':row.get('visible',True)}


def validate_state(state,session):
    if not isinstance(state,dict) or set(state)!={'version','revision','items','unit_symbols'} or state['version']!=VERSION:raise ValueError('标图版本或字段非法')
    if type(state['revision']) is not int or state['revision']<0:raise ValueError('标图修订非法')
    items=state['items'];overrides=state['unit_symbols']
    if not isinstance(items,list) or len(items)>MAX_ITEMS:raise ValueError('标注数量超限')
    items=[validate_item(x,session) for x in items]
    if len({x['id'] for x in items})!=len(items):raise ValueError('标注ID重复')
    if not isinstance(overrides,dict) or len(overrides)>1000:raise ValueError('单位图例非法')
    known={u['id'] for u in _units(session)}
    if any(k not in known or v not in SYMBOLS or SYMBOLS[v]['geometry']!='point' for k,v in overrides.items()):raise ValueError('图例只能绑定现有单位与点符号')
    return {**copy.deepcopy(state),'items':items}


def check_context(session,request):
    state=session.get('plotting_state') or _empty()
    if request.get('turn')!=session.get('turn_count',0) or request.get('world_version')!=commands.fingerprint(session.get('war_state')) or request.get('revision')!=state['revision']:
        raise Conflict('战局或标图已改变，请刷新后再保存；旧草稿未覆盖新数据')


def replace(session,request):
    check_context(session,request)
    return validate_state({'version':VERSION,'revision':request['revision']+1,'items':request.get('items',[]),'unit_symbols':request.get('unit_symbols',{})},session)


def known_locations(session):
    result=[{'name':u['name'],'kind':'unit','team':u['team'],'position':u['position']} for u in _units(session) if u.get('position')]
    world=session.get('war_state') or {}
    for r in world.get('supply_nodes',[]):
        if 'lat' in r and 'lng' in r:result.append({'name':r.get('name',r.get('id','补给节点')),'kind':'supply','team':r.get('team','neutral'),'position':{'lat':r['lat'],'lng':r['lng']}})
    bridge=(world.get('combined_arms') or {}).get('bridge')
    if bridge:result.append({'name':bridge['name'],'kind':'bridge','team':'neutral','position':{'lat':bridge['lat'],'lng':bridge['lng']}})
    for r in (world.get('history_replay') or {}).get('geo_references',[]):
        result.append({'name':r['name'],'kind':'historical_place_reference','team':'neutral','position':{'lat':r['lat'],'lng':r['lng']}})
    return result[:64]


def known_points(session):
    return [r['position'] for r in known_locations(session)]


def bind_candidate(answer,session,selected):
    if not isinstance(answer,dict) or set(answer)-{'items','explanation'} or not isinstance(answer.get('items'),list) or not 1<=len(answer['items'])<=12:raise ValueError('只提交1至12项标注草稿，不输出战局状态')
    allowed=[point(p) for p in selected]+[point(p) for p in known_points(session)]
    items=[]
    for value in answer['items']:
        if not isinstance(value,dict) or 'id' in value:raise ValueError('模型只提交标注字段，ID由程序分配')
        row=validate_item({**value,'id':uuid.uuid4().hex},session)
        if any(not any(abs(p['lat']-a['lat'])<1e-8 and abs(p['lng']-a['lng'])<1e-8 for a in allowed) for p in row['points']):raise ValueError('只能使用地图选点或已知位置，不得编造经纬度')
        items.append(row)
    return {'items':items,'explanation':str(answer.get('explanation',''))[:1600]}


def reference_svg(identity):
    entry=next((x for x in REFERENCE if x['id']==identity),None)
    if not entry:raise ValueError('未知参考图ID')
    base=Path(os.environ.get('GENTACTIX_PROJECT_ROOT',str(ROOT)))/'data/military-symbols-v2'
    path=(base/entry['file']).resolve()
    if not path.is_relative_to((base/'icons').resolve()):raise ValueError('仅允许已索引独立图标')
    if not path.is_file():raise FileNotFoundError('本机未安装原书参考素材；应用重绘符号仍可使用')
    data=path.read_bytes()
    if len(data)>512000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('参考SVG超限或含外部实体')
    try:node=ET.fromstring(data)
    except ET.ParseError as exc:raise ValueError('参考SVG无法解析，请核对本地文件') from exc
    allowed={'svg','title','desc','metadata','g','path','ellipse','circle','rect','line','polyline','polygon'}
    if node.tag.split('}')[-1]!='svg':raise ValueError('参考文件不是SVG')
    for element in node.iter():
        if element.tag.split('}')[-1] not in allowed:raise ValueError('参考SVG含活动内容')
        for k,v in element.attrib.items():
            if k.lower().startswith('on') or 'href' in k.lower() or re.search(r'url\s*\(',v,re.I):raise ValueError('参考SVG含外部引用或事件')
    return data
