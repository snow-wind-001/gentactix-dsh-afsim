"""Opt-in Wuhan defensive goals; preserve old source, actor and region pins."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gentactix import campaign_windows as windows, historical_initial as history

WINDOW = 'WH-northern-sep17-18'
VERSION = '1.2.0'
NOTE = ('1.2.0显式防御判据：本方部署区允许接敌，以就绪兵力门槛及对方既有reach核心未被突破计时；'
        '敌方达到核心人数门槛即打断，不等其保持或激活时间。地域、人数、时长仍是估计，'
        '不是新发现的史实阵位、历史撤退命令或确定战果；不补造援军与后勤。')


def build():
    value = copy.deepcopy(windows.load(WINDOW, '1.1.0'))
    value['version'] = VERSION
    value['label'] = '武汉北线17—18日：双轴防御与突破（估计配置）'
    value['limitations'] += ' ' + NOTE
    estimates = value['parameter_estimates']
    estimates['assumption'] += ' ' + NOTE
    graph = estimates['goal_template']
    graph['assumption'] += ' ' + NOTE
    targets = {'red_mountain': 'blue_mountain', 'red_plain': 'blue_plain'}
    for node in graph['nodes']:
        if node['id'] in targets:
            node['condition'].update(kind='defend', against_node=targets[node['id']])
            node['assumption'] += ' ' + NOTE
    snapshot = history.initial(value['battle'], value['start_phase_id'],
                               version=value['historical_initial']['version'])['historical_initial']
    windows.validate_definition(value, snapshot)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check the new version without writing')
    args = parser.parse_args()
    value = build()
    target = windows.DATA_ROOT / WINDOW / (VERSION + '.json')
    if target.exists():
        if json.loads(target.read_text()) != value:
            raise SystemExit('已有窗口与生成器不一致；不覆盖已发布版本：' + str(target))
    elif args.check:
        raise SystemExit('新窗口尚未生成：' + str(target))
    else:
        with target.open('x') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(('CHECK ' if args.check else 'READY ') + WINDOW + '@' + VERSION)


if __name__ == '__main__':
    main()
