"""Native telemetry for the explicit movement-feedback-1 calculation contract."""
import math

from gentactix import movement_feedback as mf, missions
from .afsim_literals import number


def ground_expression(world, entity, actor, route_expression):
    if not mf.configuration(world) or not entity.get('ferry_transport'):
        return route_expression
    path = entity.get('crossing_plan')
    if not path:
        return '0.0'
    points = (entity['origin'], path['entry'], path['exit'])
    coordinates = ','.join(number(p[k],precision=12) for p in points for k in ('lat','lng'))
    return f'GtxFerryGroundDistance({actor},{coordinates},{str(path["enter_required"]).lower()})'


def functions():
    return '''script double GtxFerryGroundDistance(WsfPlatform actor,double la,double lo,double ea,double eo,double xa,double xo,bool enterRequired)
 double approach=0; if (enterRequired) { approach=GtxDistance(la,lo,ea,eo); }
 if (actor.AuxDataDouble("ca_cross_left")>0) { return approach+GtxDistance(xa,xo,actor.Latitude(),actor.Longitude()); }
 if (!enterRequired) { return 0; }
 if (actor.AuxDataDouble("ca_cross_entered")>0 || actor.AuxDataString("ferry_boat")!="") { return approach; }
 return GtxDistance(la,lo,actor.Latitude(),actor.Longitude());
end_script
'''


def parse(text, model, scene):
    rows = {}
    for line in text.splitlines():
        if not line.startswith('GTXMOVEMENT|'):
            continue
        p = line.split('|')
        if not model.get('movement_feedback') or len(p)!=5 or p[1] not in scene['entities'] or p[1] in rows:
            raise ValueError('原生运动反馈缺项、重复、未知身份或版本未启用')
        values = list(map(float,p[2:]))
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError('原生运动反馈须为有限非负数')
        rows[p[1]] = dict(zip(('ground_km','route_km','pause_seconds'),values))
    if model.get('movement_feedback') and set(rows)!=set(scene['entities']):
        raise ValueError('原生运动反馈未覆盖全部当前实体')
    return rows


def apply(after, data, scene, model):
    if not model.get('movement_feedback'):
        return
    if model.get('continuous_motion'):
        from gentactix import motion_state
        rows=data.get('continuous_motion',{})
        if set(rows)!=set(scene['entities']):raise ValueError('整局连续机动回执缺少实体')
        current={u['name']:u for _,u in missions.units(after)}
        receipt=[]
        for identity,entry in scene['entities'].items():
            row=rows[identity];unit=current[entry['name']]
            if missions.distance(unit,row)>mf.POSITION_TOLERANCE_KM:
                raise ValueError('连续机动位置与原生地图观测不一致')
            motion_state.validate_unit(unit)
            if any(unit['formation'].get(k)!=v for k,v in row['formation'].items()):
                raise ValueError('连续机动状态未完整提交')
            receipt.append(dict(unit=unit['name'],ground_km=row['distance_micrometers']/1e9,
                waiting_ms=row['waiting_ms'],moving_ms=row['moving_ms'],rest_ms=row['rest_ms'],
                blocked_ms=row['blocked_ms'],fuel_spent_microliters=row['fuel_spent_microliters'],
                fatigue_ticks=row['fatigue_ticks'],status=row['formation']['motion_task']['status']))
        after['combined_arms']['movement_feedback']=dict(version=mf.CONTINUOUS_VERSION,
            source='afsim_native_estimate',turn=model['expected_turn'],units=receipt,
            scope=('Native连续机动隔离验证模式；实际计算回执，不代表完整历史会战验收'
                if mf.native_preview_enabled(after) else 'Native连续机动与整局回执绑定；保障及完整执行准入仍未验收'))
        return
    before = dict(mission={**after['mission'],'turn':model['expected_turn']-1},
        current_time=model['movement_start']['current_time'],
        simulation_clock=model['movement_start']['simulation_clock'],
        combined_arms=model['before_combined'],supply_nodes=model['supply_nodes'],
        **{team+'_units':[u for t,u in model['units'] if t==team] for team in ('red','blue')})
    if model.get('before_campaign') is not None:
        before['campaign'] = model['before_campaign']
    native = {scene['entities'][identity]['name']:row for identity,row in data['movement'].items()}
    receipt = mf.validate_transition(before,after,model['orders'],scene['seconds'],source='afsim_native_estimate',native=native)
    after['combined_arms']['movement_feedback'] = receipt
    for _,unit in missions.units(after):
        unit['formation']['last_execution'].update(movement_revision=1,
            ground_distance_milli=round(native[unit['name']]['ground_km']*1e6))
