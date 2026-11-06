"""Register the sourced Oct6 15:00 command opening without migrating old pins."""
import argparse
import copy
from datetime import datetime
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gentactix import historical_initial as hi, campaign_windows as cw
from gentactix import initial_command as ic, sim_clock
from tools.upgrade_wanjialing import BATTLE

INITIAL_VERSION = '1.7.0'
WINDOW = 'WJL-oct6pm-10'
WINDOW_VERSION = '1.0.0'
START = '1938-10-06T15:00:00'
NOTE = ('采用研究论文转引的6日15时命令作为计算开局指挥；不声称各级同刻收到命令、'
        '部队全部到齐或已经完成任务。人员、装备、部署和库存仍须独立估计；'
        '7日161师投入部关系不提前移用，后续不按史实日期自动转隶。')


def build_source():
    value = hi.definition(BATTLE, '1.6.0')
    value['version'] = INITIAL_VERSION
    phase = next(p for p in value['phases'] if p['id'] == 'oct6_orders')
    if phase.get('relations'):
        raise ValueError('Expected the unchanged1.6 source phase without opening links')
    phase['relations'] = [dict(
        id='WJL-Oct6-pm-command-' + army,
        kind='operational_command', parent_id='ww2.cn.corps1', child_id='ww2.cn.' + army,
        scope=NOTE,
        evidence=[dict(source_id='WJL_GUO', locator=(
            '印刷119页：6日13时薛岳下反攻令；吴奇伟副兵团长15时于白槎指挥所'
            '对66、4、74军下达任务。论文转引张秉均前引书第320页，未核原始军令。'))])
        for army in ('army66', 'army4', 'army74')]
    value['coverage']['notes'].append('1.7.0仅补6日15时三军作战指挥来源；' + NOTE)
    hi.validate_definition(value)
    return value


def build_window(source):
    value = copy.deepcopy(cw.load('WJL-oct6-10', '1.7.0'))
    value.update(id=WINDOW, version=WINDOW_VERSION,
        label='万家岭：6日15时—10日多军协同 · 来源指挥开局')
    snapshot = hi._materialize(source, 'oct6_orders')['historical_initial']
    value['historical_initial'] = {k:snapshot[k] for k in ('profile_id','version','definition_hash')}
    value['bounds'].update(start=START, note=NOTE)
    relations = ic.relations(snapshot)
    value['opening_command'] = dict(version=ic.WINDOW_DECLARATION_VERSION,
        phase_id='oct6_orders', relation_ids=[r['id'] for r in relations],
        scope=NOTE, evidence=copy.deepcopy(relations[0]['evidence']))
    for row in relations:
        value['units'][row['child_id']]['operational_reference'] = row['id']
    prior = value['parameter_estimates']['global_priors']
    prior['clock'].update(start=START, assumption=NOTE)
    prior['campaign_scope']['assumption'] += ' ' + NOTE
    for row in prior['campaign']['arrivals'].values():
        if datetime.fromisoformat(row['not_before']) < datetime.fromisoformat(START):
            row.update(not_before=START, assumption=row['assumption'] +
                ' 本项为新窗口开局可受令的计算估计，不代表史实到场发生在15时；'
                '不补写开局前行军、耗粮或接令过程。')
    prior['goal']['deadline_turn'] = math.ceil(
        (datetime.fromisoformat(value['bounds']['end']) - datetime.fromisoformat(START)).total_seconds()
        / sim_clock.duration_seconds(prior['clock']['time_step']))
    value['limitations'] += ' 本版仅增加15时指挥开局，沿用明确估计的资源和部署，未新增历史兵额或效能标定。'
    cw.validate_definition(value, snapshot)
    return value


def objective_binding(source, pins):
    """Keep prior phase guidance, and pin the newly reviewed opening task."""
    value = copy.deepcopy(pins['profiles']['AJ07-wanjialing']['1.6.0'])
    value['initial_definition_hash'] = hi.digest(source)
    guidance = dict(team='red', profile='assault',
        objective_label='第66军突击、第4军侧翼掩护、第74军北攻的多军协同任务',
        scope_note=('采用6日15时指挥所所下任务作为分方向目标参考；命令不等于已执行或已经攻占。'
                    '具体目标地域、到场、库存及程序阈值仍须显式估计，不使用全军人数代替所列下级，'
                    '不把7日161师投入部的配属提前套入开局。'),
        not_covered=['完整军建制及未知余部', '逐军接令和实到时刻、精确阵位',
                     '后续历史任务自动执行或历史战果必达', '完整会战历史效能标定'],
        evidence=[dict(source_id='WJL_GUO',
            locator='印刷119页：6日13时反攻令及15时吴奇伟对66、4、74军的任务；论文转引张秉均第320页。')])
    value['phases']['oct6_orders'] = dict(guidance=guidance,
        source_hashes={'WJL_GUO':hi.digest(source['sources']['WJL_GUO'])})
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = build_source()
    values = {hi.DATA_ROOT/'AJ07-wanjialing'/(INITIAL_VERSION+'.json'):source,
              cw.DATA_ROOT/WINDOW/(WINDOW_VERSION+'.json'):build_window(source)}
    for path, value in values.items():
        if path.exists():
            if json.loads(path.read_text()) != value:
                raise SystemExit('Immutable version differs; create a new version: '+str(path))
        elif args.check:
            raise SystemExit('Registered source/window missing: '+str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    path = ROOT/'data/historical_objective_bindings.json'
    pins = json.loads(path.read_text())
    binding = objective_binding(source, pins)
    versions = pins['profiles']['AJ07-wanjialing']
    if INITIAL_VERSION in versions:
        if versions[INITIAL_VERSION] != binding:
            raise SystemExit('Immutable objective binding differs; create a new version')
    elif args.check:
        raise SystemExit('Opening objective version binding missing')
    else:
        versions[INITIAL_VERSION] = binding
        path.write_text(json.dumps(pins, ensure_ascii=False, indent=2)+'\n')
    print('Wanjialing1.7 source and15h command window match; old versions/defaults unchanged')


if __name__ == '__main__':
    main()
