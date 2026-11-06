"""Explicit goal-graph QA over six sourced identities, not historical geography."""
import copy
from gentactix import historical_initial as hi, historical_operations as ho
from tools.qa.initial_command_fixture import inputs as source_inputs
from tools.upgrade_wanjialing import BATTLE

NOTE = '软件目标图QA估计；计算地域、阈值和时点未经史实标定，不是历史命令或战果。'


def inputs():
    _, parameters = source_inputs()
    snapshot = hi.initial(BATTLE, 'oct7_attack', version='1.2.0')['historical_initial']
    center = parameters['area']['center']
    north = dict(lat=center['lat'] + .006, lng=center['lng'] + .005)
    south = dict(lat=center['lat'] - .006, lng=center['lng'] + .005)
    red = [i for i in parameters['actors'] if i.startswith('ww2.cn.')]
    def node(identity, label, team, units, condition, after=(), operation_ids=()):
        return dict(id=identity, label=label, team=team, unit_ids=units,
            after={'mode': 'all', 'node_ids': list(after)}, not_before_seconds=0,
            condition=condition, hold_seconds=0, latch=False,
            operation_ids=list(operation_ids), assumption=NOTE)
    nodes = [
        node('north', '北侧方向控制', 'red', ['ww2.cn.division159'],
            dict(kind='control', region={'center': north, 'radius_km': .1}, minimum_personnel=1),
            operation_ids=['WJL-Oct7-shibao']),
        node('south', '南侧方向控制', 'red', ['ww2.cn.division51'],
            dict(kind='control', region={'center': south, 'radius_km': .1}, minimum_personnel=1),
            operation_ids=['WJL-Oct7-changling']),
        node('preserve', '两方向达成后保持投入兵力', 'red', red,
            dict(kind='preserve', minimum_fraction=.5), after=['north', 'south']),
        node('blue_exit', '蓝方到达估计突围地域', 'blue', ['ww2.jp.division106'],
            dict(kind='reach', region={'center': dict(lat=center['lat'], lng=center['lng'] - .008), 'radius_km': .1}, minimum_personnel=1)),
    ]
    parameters['campaign_plan'] = dict(version='campaign-objectives-1', nodes=nodes,
        outcomes={team: dict(mode='all', node_ids=[goal]) for team, goal in [('red', 'preserve'), ('blue', 'blue_exit')]},
        elimination_ends=True, assumption=NOTE)
    parameters['goal'].update(required_turns=1, deadline_turn=2)
    return snapshot, parameters


def world():
    return ho.initial(*inputs())


def session():
    return dict(id='campaign-plan-qa', turn_count=0, role_epoch=0, product_mode='historical',
        simulation_mode='open', execution_backend='afsim', time_step='30分钟', war_state=world())
