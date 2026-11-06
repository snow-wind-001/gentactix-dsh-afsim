"""Coarse battle-area validation, independent of terrain or force deployment.

An anchor is a locality reference, not a historical unit position. A generous
200 km allowance catches continent/coordinate-column errors without snapping a
unit to an invented historical deployment or rejecting an offshore support unit.
"""
from . import adjudicator, commands

MAX_ANCHOR_DISTANCE_KM = 200


def validate(world, available_nodes):
    if not available_nodes:
        return
    references = list(available_nodes.values())
    errors = []
    for team, unit in commands.iter_units(world):
        point = commands.known_position(unit)
        if point is None:
            continue  # Unknown remains unknown; the external loader reports it.
        coords = (point['lat'], point['lng'])
        if not -90 <= coords[0] <= 90 or not -180 <= coords[1] <= 180:
            errors.append(commands.name_of(unit) + '坐标超出经纬度范围')
            continue
        nearest = min(adjudicator.distance_km(coords, ref) for ref in references)
        if nearest > MAX_ANCHOR_DISTANCE_KM:
            errors.append(f"{team} {commands.name_of(unit)} [{coords[0]}, {coords[1]}] 距最近战区参考点{nearest:.0f}km")
    if errors:
        raise ValueError('战区坐标校验未通过：' + '；'.join(errors) +
                         '。未移动或纠正单位；请检查经纬度和所选局部战区，修正初态或新建战局。')
