"""Explicit four-army calculation loads; not reconstructed historical strengths."""
import copy

from gentactix import historical_initial as hi, historical_operations as ho
from tools.qa.historical_crossing_fixture import inputs as crossing_inputs

BATTLE = '红军长征-懋功会师与雪山草地转移-1935.06.12至1935.09.12'
PHASE = 'right_column_grassland'
NOTE = '转移合同QA估计：每军3000人、位置、库存与目标仅作计算载荷；不是历史实到、完整编制或草地效能标定。'


def inputs():
    snapshot = hi.initial(BATTLE, PHASE, version='1.0.0')['historical_initial']
    params = ho.configuration_template(snapshot)
    _, prototype = crossing_inputs()
    center = {'lat': 33.35, 'lng': 103.1}
    for key in ('rules', 'support', 'facility', 'goal'):
        params[key] = copy.deepcopy(prototype[key])
    params['rules'].update(goal_profile='breakout', bridge_enabled=False, required_survivors=4)
    params['facility'].pop('crossing_model', None)
    params['facility'].update(**center, name='QA计算汇总点（不是史实设施）', capacity=0, used=0)
    params['clock'].update(start='1935-08-21T00:00', time_step='30分钟', assumption=NOTE)
    params['area'].update(center=center, radius_km=30, terrain_factor=1.5, assumption=NOTE)
    actor = next(iter(prototype['actors'].values()))
    for n, identity in enumerate(params['actors']):
        row = copy.deepcopy(actor)
        row.update(personnel=3000, position={'lat': 33.34+n*.01, 'lng': 103.09}, assumption=NOTE)
        row['equipment'] = {k: 0 for k in row['equipment']}
        row['formation'].update(motorized=False, fuel_liters=0, spares=0, materials=0, shells=0, aa_rounds=0)
        params['actors'][identity] = row
    for row in params['support'].values():
        row.update(position=dict(center), stock=0, inventory={k: 0 for k in row['inventory']}, assumption=NOTE)
    params['goal'].update(profile='breakout', objective=dict(center), exit=dict(center), radius_km=.1,
        termination_mode='objectives', required_survivors=4, required_turns=2, description=NOTE, assumption=NOTE)
    nodes = []
    for n, identity in enumerate(params['actors']):
        nodes.append(dict(id='reach'+str(n), label='第'+str(n+1)+'路转移', team='red', unit_ids=[identity],
            after={'mode':'all','node_ids':[]}, not_before_seconds=0, hold_seconds=0, latch=True,
            operation_ids=[], assumption=NOTE, condition={'kind':'reach','region':{
                'center':{'lat':33.34+n*.01,'lng':103.11},'radius_km':.1},'minimum_personnel':1000}))
    nodes.append(dict(id='preserve', label='全部方向完成并保存兵力', team='red', unit_ids=list(params['actors']),
        after={'mode':'all','node_ids':[n['id'] for n in nodes]}, not_before_seconds=0, hold_seconds=0,
        latch=False, operation_ids=[], assumption=NOTE, condition={'kind':'preserve','minimum_fraction':.7}))
    params['campaign_plan'] = dict(version='campaign-objectives-1', nodes=nodes,
        outcomes={'red':{'mode':'all','node_ids':['preserve']},'blue':{'mode':'all','node_ids':[]}},
        elimination_ends=True, assumption=NOTE)
    params['assumptions'] = NOTE
    return snapshot, params


def step(before, reached=(), *, destroy=False):
    from gentactix import campaign, missions, sim_clock
    after = copy.deepcopy(before)
    nodes = after['mission']['definition']['campaign_plan']['nodes']
    targets = {n['unit_ids'][0]:n['condition']['region']['center'] for n in nodes if n['id'] in reached}
    for _, row in missions.units(after):
        if row['historical_unit_id'] in targets:
            row.update(targets[row['historical_unit_id']])
        if destroy:
            row['personnel'].update(current=0, casualties=row['personnel']['committed'])
    after['current_time'], after['simulation_clock'] = sim_clock.target(before, '30分钟')
    after['mission']['turn'] += 1
    if campaign.definition(after): after['campaign']['turn'] = after['mission']['turn']
    missions.evaluate(after)
    return after


def campaign_inputs():
    from gentactix import campaign_windows as cw
    from tools.upgrade_long_march_transfer import WINDOW
    snapshot = hi.initial(BATTLE, PHASE, version='1.1.0')['historical_initial']
    params = ho.configuration_template(snapshot,'campaign',window=cw.pin(WINDOW),termination_mode='objectives')
    _, base = inputs()
    for key in ('area','rules','support','facility','goal','actors','assumptions'):
        params[key] = copy.deepcopy(base[key])
    params['campaign_scope']['assumption']=NOTE
    for identity in params['actors']:
        params['campaign']['arrivals'][identity].update(not_before=params['clock']['start'],assumption=NOTE)
        params['campaign']['fortifications'][identity].update(integrity=0,degradation_per_shell=0,assumption=NOTE)
    params['campaign']['objective'].update(min_force_fraction=.7,assumption=NOTE)
    params['campaign']['surrender'].update(enabled=False,range_m=1,suppression_threshold=100,ammo_threshold=0,assumption=NOTE)
    params['campaign']['assumption']=NOTE
    params['clock']['assumption']=NOTE
    for n,row in enumerate(params['campaign_plan']['nodes']):
        row['assumption']=NOTE
        if row['condition']['kind']=='reach':
            row['condition'].update(region={'center':{'lat':33.34+n*.01,'lng':103.11},'radius_km':.1},minimum_personnel=1000)
        elif row['condition']['kind']=='preserve':row['condition']['minimum_fraction']=.7
        else:row['condition'].update(minimum_food=5,minimum_ammo=0)
    params['campaign_plan']['assumption']=NOTE
    return snapshot,params
