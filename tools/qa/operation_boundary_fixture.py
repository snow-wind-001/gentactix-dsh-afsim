"""Six sourced identities; all boundary/route geometry is explicit software QA."""
import copy
from tools.qa.campaign_plan_fixture import inputs as base_inputs, NOTE


def inputs():
    source, p = base_inputs()
    center = p['area']['center']
    origin = p['actors']['ww2.cn.division159']['position']
    outside = dict(lat=origin['lat'] + .012, lng=origin['lng'])
    p['operation_boundary'] = dict(version='operation-boundary-1', center=copy.deepcopy(center),
        radius_km=1.0, assumption=NOTE, routes=[dict(id='red-north', team='red',
            inside=copy.deepcopy(origin), outside=outside, corridor_km=.08, assumption=NOTE)])
    p['goal'].update(deadline_turn=200, termination_mode='objectives')
    return source, p
