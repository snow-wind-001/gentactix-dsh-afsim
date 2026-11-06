"""Add page-checked corrections and Oct 8–10 links without migrating old games."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gentactix import historical_initial as hi
from tools.upgrade_wanjialing import BATTLE, evidence


def build():
    d = hi.definition(BATTLE, '1.1.0'); d['version'] = '1.2.0'
    d['sources']['WJL_GUO']['limitations'] = (
        '2026-10-31逐页视觉核读PDF第8—10页（印刷118—120页）。'
        '论文转引档案7878033、7878201、7876278及回忆；未辨读馆藏原件。'
        '1.1.0误录炮4团6连，本版按118页改为炮1团6连。兵额和歼敌判断不作为逐单位数值事实。')
    d['coverage']['notes'] += [
        '1.2.0纠正炮兵第1团第6连身份；原1.1.0错误身份只保留于冻结旧版本，不建立两个番号的同一实体别名。',
        '第142师欠一团作为本战局投入部另列：8日11时是出击记录，不是首次接敌或抵达坐标。',
        '9日15时命令、18时完成准备及19时开始攻击分开；准备截止不等于已完成集结或攻占。',
        '10日各部行动不等于全歼106师团或全役结束；雷鸣鼓刘、箭炉苏、哔叽街、墩上郭等仍有残敌与继续抵抗的记述。',
        '新增8—10日内容仍是资料片段；未补齐完整每日部署、退场、后勤及日方联队序列，不自动成为持续会战计算基线。']
    phases = {p['id']: p for p in d['phases']}
    for identity, label, date in (
        ('oct9_final_orders', '10月9日总攻命令、准备与发起（资料片段）', '1938-10-09'),
        ('oct10_attacks', '10月10日多方向争夺与残敌抵抗（资料片段）', '1938-10-10'),
    ):
        ev = evidence('第120页：10月9—10日命令、总攻及继续抵抗；论文转引，原件未核')
        p = dict(id=identity, label=label, date={'label': date, 'precision': 'day', 'evidence': ev},
            scope='资料回溯片段；未核齐完整当日在场、阵位与到离过程，不作为单日完整计算初态。',
            evidence=ev, relations=[], operations=[])
        phases[identity] = p; d['phases'].append(p)
        for u in d['units']:
            u['presence'].append(dict(phase_id=identity, status='campaign_participant', evidence=copy.deepcopy(u['evidence'])))
    for u in d['units']:
        if u['id'] == 'ww2.cn.artillery4.company6':
            u.update(id='ww2.cn.artillery1.company6', name='炮兵第1团第6连',
                evidence=evidence('第118页参战部队段，视觉核读为炮一团六连；1.1.0炮4团为转录错误'))
            for row in u['presence']:
                row['evidence'] = copy.deepcopy(u['evidence'])
    parent = next(u for u in d['units'] if u['id'] == 'ww2.cn.division142')
    parent['children_coverage'] = dict(status='partial',
        scope='只列论文所记欠一团投入部；该团番号、人数及余部去向未核，不能视为全师完整覆盖。',
        evidence=evidence('第119—120页：142师欠一团出击及次日攻击'))
    part = copy.deepcopy(parent)
    part.pop('children_coverage')
    part.update(id='ww2.cn.division142.wjl_part', name='第142师万家岭投入部（欠一团）',
        echelon='师之一部', parent_id=parent['id'], evidence=copy.deepcopy(parent['children_coverage']['evidence']))
    for row in part['presence']:
        row.update(status='outside_scope' if row['phase_id'] == 'oct7_attack' else 'campaign_participant',
            evidence=copy.deepcopy(part['evidence']))
    d['units'].append(part)
    # Keep the old event key but remove the unrelated clock from its new-version account.
    hills = next(o for o in phases['oct8_counterattacks']['operations'] if o['id'] == 'WJL-Oct8-hills')
    hills.update(date={'label': '1938-10-08，当日', 'precision': 'day'},
        unit_ids=['ww2.cn.army66', 'ww2.cn.army4', 'ww2.jp.division106'],
        description='66军进占石堡山、老虎尖，并以一部与4军协力攻占狮子崖西北高地。142师欠一团出击另列，不将其钟点套用到其他军。',
        places=[p for p in hills['places'] if p['name'] in ('石堡山', '老虎尖', '狮子崖西北高地')],
        evidence=evidence('第119页：10月8日66军及4军协同攻击段'))

    def operation(phase_id, identity, kind, date, precision, ids, places, description, locator, limitations=''):
        ev = evidence(locator)
        phases[phase_id].setdefault('operations', []).append(dict(id=identity, kind=kind,
            date={'label': date, 'precision': precision}, unit_ids=ids,
            places=[{'name': name, 'position': None, 'evidence': copy.deepcopy(ev)} for name in places],
            description=description, evidence=ev,
            limitations=('论文转引，不等于已核原件；无配准战图、逐单位实到人数与库存。'
                '开放推演中是比较参考，不是强制发生事件。' + limitations)))

    operation('oct8_counterattacks', 'WJL-Oct8-142-departure', 'movement', '1938-10-08；11时出击（论文记述）', 'hour',
        [part['id']], ['城门山', '桶汉傅', '周家'],
        '第142师欠一团于11时由城门山出击，攻占桶汉傅、周家之线。出击与占领按原文顺序保留，不把整个过程压为11时一个瞬时事件。',
        '第119页：142师（欠一团）于11时由城门山出击段',
        '11时仅对应出击；首次接敌、攻占完成时间及行军路线未知，不能转成接敌时间约束。')
    operation('oct8_counterattacks', 'WJL-Oct8-japanese-situation', 'command', '1938-10-08，当日；电报时刻缺载', 'day',
        ['ww2.jp.division106'], ['万家岭'],
        '论文转引106师团参谋电报：入夜各方反复攻击、包围逐渐形成，部队行动和地形使进展受阻。此为该方态势报告，不能据此认定其已被歼灭。',
        '第119页末—120页首：樱井锭三报告，论文注《华中华南作战及对华战略之转变》第274页')
    operation('oct9_final_orders', 'WJL-Oct9-orders', 'command', '1938-10-09；15时（论文记述）', 'hour',
        ['ww2.cn.corps1', 'ww2.cn.army4', 'ww2.cn.army66', 'ww2.cn.army74'], ['箭炉苏', '万家岭', '田步苏', '雷鸣鼓刘', '杨家山北端无名村'],
        '薛岳考虑武永路援敌与德星线日军西进，命各攻击部队每师挑选奋勇队，安排18时完成准备、19时开始攻击。命令与实际执行分别记载。',
        '第120页：9日15时薛岳命令；论文引张秉均第322页')
    operation('oct9_final_orders', 'WJL-Oct9-preparation', 'command', '1938-10-09；命令要求18时完成准备', 'hour',
        ['ww2.cn.army4', 'ww2.cn.army66', 'ww2.cn.army74'], [],
        '总攻令规定18时完成攻击准备；这是计划截止时点，论文没有逐师报告其实际完成时间，不写成全部部队已按时准备完毕。',
        '第120页：命令中的十八时完成攻击准备',
        '计划时点不能用于证明实际到场或各师均已完成准备。')
    operation('oct9_final_orders', 'WJL-Oct9-fire', 'attack', '1938-10-09；19时（论文记述）', 'hour',
        ['ww2.cn.army4', 'ww2.cn.army66', 'ww2.cn.army74', 'ww2.jp.division106'],
        ['箭炉苏', '万家岭', '田步苏', '雷鸣鼓刘', '杨家山北端无名村'],
        '19时各攻击部队进入准备，伴随奋勇队推进；各守备部队压制当面之敌。这里只记录论文所述总攻，不把每支部队的起火和到达时间假定完全相同。',
        '第120页：晚19时各攻击部队准备就绪、随同奋勇队推进段')
    operation('oct10_attacks', 'WJL-Oct10-66', 'attack', '1938-10-09夜至10日3时（论文记述）', 'range',
        ['ww2.cn.army66', 'ww2.jp.division106'], ['万家岭', '田步苏', '石堡山'],
        '66军激战至10日3时攻克万家岭、田步苏；随后有敌残部西退，一部被石堡山守军截击。战果和残敌规模是论文叙述，不据此设定必然全歼。',
        '第120页：第66军激战至10日3时及残敌撤退段')
    operation('oct10_attacks', 'WJL-Oct10-4', 'attack', '1938-10-10，当日；具体时刻缺载', 'day',
        ['ww2.cn.army4'], ['大金山西南高地', '箭炉苏东端高地'],
        '4军攻占大金山西南及箭炉苏东端高地；没有据此补造下级团番号或精确占领时间。',
        '第120页：第四军攻占高地段')
    operation('oct10_attacks', 'WJL-Oct10-74', 'attack', '1938-10-10，拂晓前', 'period',
        ['ww2.cn.army74', 'ww2.jp.division106'], ['张古山最高点'],
        '74军在10日拂晓前攻占张古山最高点；与8日51师一度攻占又被夺回分开，不能把8—10日控制权写成从未变化。',
        '第120页：第74军10日拂晓前攻占段')
    operation('oct10_attacks', 'WJL-Oct10-west', 'attack', '1938-10-10，拂晓前', 'period',
        ['ww2.cn.division91', part['id']], ['杨家山东北无名村', '杨家山北端无名村', '松熊'],
        '91师与142师欠一团分别攻击杨家山东北和北端等地域；两个部队的不同方向不能合并为一个虚构联合作战实体。',
        '第120页：91师及142师（欠一团）拂晓前攻占段')
    operation('oct10_attacks', 'WJL-Oct10-residual', 'combat', '1938-10-10及其后；论文未给统一终止钟点', 'range',
        ['ww2.jp.division106', 'ww2.cn.corps1'], ['雷鸣鼓刘', '箭炉苏', '哔叽街', '墩上郭', '长岭', '张古山'],
        '10日攻占万家岭不等于全役结束或全歼106师团。论文明确仍有残敌据守、待援和反扑，并转引10日军委会电所述继续包围肃清。',
        '第120页末：对10日结束说的辨析；转引陈诚10月10日电，档案7876278',
        '后续终结、退出路线和损失边界尚未补齐；本资料集的最后一帧只表示当前整理完毕。')
    hi.validate_definition(d)
    return d


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    value = build(); path = ROOT / 'data/historical_initial/AJ07-wanjialing/1.2.0.json'
    if args.check:
        if not path.exists() or json.loads(path.read_text()) != value:
            raise SystemExit('Wanjialing 1.2.0 source snapshot differs')
        print('Wanjialing 1.2.0 additive snapshot matches builder')
    elif path.exists():
        if json.loads(path.read_text()) != value:
            raise SystemExit('Refusing to overwrite an existing different version')
        print('Wanjialing 1.2.0 already matches; unchanged')
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        print('Created Wanjialing 1.2.0; default and old versions unchanged')


if __name__ == '__main__':
    main()
