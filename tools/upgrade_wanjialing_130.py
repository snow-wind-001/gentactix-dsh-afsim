"""Extend sourced directions and post-Oct10 continuity; never promote defaults."""
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
    d = hi.definition(BATTLE, '1.2.0'); d['version'] = '1.3.0'
    d['sources']['WJL_GUO']['limitations'] += (
        '2026-11-01增核印刷116—121页；行政隶属、临时指挥、调令、实际接触和撤退分列。'
        '仍是研究论文及其转引，未核日本联队日志或中国电报原件。')
    d['coverage']['notes'] += [
        '1.3.0补9月28日配属、10月2日东西方向命令、阻援抽调和12—17日后续。旧版及默认入口不变。',
        '日军149联队属101师团，曾受106师团统一指挥；123联队属106师团。仅列已核下级，不声称两师团完整覆盖。',
        '宇贺、铃木、佐枝支队作为外线援敌参考，不能合并成被围106师团或把27师团全体放入内圈。',
        '调令不能证明同时到场；阻援抽调不证明全师撤出；资料后续阶段均未开放为完整可计算部署。',
        '12日重新部署和17日总撤退是来源参照，不在开放模式按日历强制清场、恢复兵力或结束战局。']
    phases = {p['id']:p for p in d['phases']}
    new = [
        ('sep28_isolation', '9月28日前后：日方临时配属与联络受阻', '1938-09-28前后', 'range', '116—117'),
        ('oct2_encirclement', '10月2日：东西两方向包围命令', '1938-10-02', 'day', '117'),
        ('oct12_redeployment', '10月12日：外线压力与转守部署', '1938-10-12', 'day', '121'),
        ('oct17_withdrawal', '10月16—17日：后退与撤离接触', '1938-10-16至1938-10-17', 'range', '121'),
    ]
    for identity, label, date, precision, page in new:
        ev = evidence('印刷第'+page+'页；论文转引，未核作战原件')
        phases[identity] = dict(id=identity, label=label,
            date=dict(label=date, precision=precision, evidence=copy.deepcopy(ev)),
            scope='来源事件和方向参考；未核全部实到、逐单位部署及资源，不作为完整会战计算初态。',
            evidence=ev, operations=[], relations=[])
        for u in d['units']:
            u['presence'].append(dict(phase_id=identity,status='campaign_participant',evidence=copy.deepcopy(u['evidence'])))
    sequence = ['campaign_reference','sep28_isolation','oct2_encirclement','oct6_orders','oct7_attack',
                'oct8_counterattacks','oct9_final_orders','oct10_attacks','oct12_redeployment','oct17_withdrawal']
    d['phases'] = [phases[i] for i in sequence]
    facts = copy.deepcopy(d['units'][0]['facts'])
    def unit(identity, name, echelon, parent, locator, team='blue'):
        ev = evidence(locator)
        value = dict(id=identity,name=name,team=team,role='formation',echelon=echelon,parent_id=parent,
            evidence=ev,facts=copy.deepcopy(facts),presence=[dict(phase_id=p['id'],
                status='outside_scope' if p['id']=='oct7_attack' else 'campaign_participant',
                evidence=copy.deepcopy(ev)) for p in d['phases']])
        for field in value['facts'].values():
            field.update(value=None,evidence=[],scope='此条只核身份、任务或配属；人数、装备及阵位缺载。7日局部计算排除不等于史实未参战。')
        d['units'].append(value)
        return value
    unit('ww2.jp.division101','日军第101师团','师团','ww2.jp.army11','第116页：149联队行政归属；不代表整个101师团在万家岭内圈')
    unit('ww2.jp.regiment149','日军步兵第149联队','联队','ww2.jp.division101','第116页：101师团149联队与106师团会合并受其统一指挥')
    unit('ww2.jp.regiment123','日军步兵第123联队','联队','ww2.jp.division106','第117页：106师团123联队一部在白水街方向；实际投入一部，不补全全联队')
    unit('ww2.jp.uga_detachment','日军宇贺支队','支队',None,'第119页：临时组成的外线援敌；其补充兵数与被围师团原有人员不能重复计入')
    unit('ww2.jp.suzuki_detachment','日军铃木支队','支队',None,'第119、121页：外线援敌与17日取得联系；原行政序列未据此确定')
    unit('ww2.jp.saeda_detachment','日军佐枝支队','支队','ww2.jp.division27','第119页：27师团留置支队；不是27师团全体重回万家岭')
    unit('ww2.cn.division61','第61师（16日后退记录）','师',None,
        '第121页16日后退原文为六一师，前述阻援为六十师；不将两番号自动合并，隶属及番号异文待原件复核',team='red')
    for u in d['units']:
        if u['id'] in ('ww2.jp.division101','ww2.jp.division106','ww2.jp.division27'):
            u['children_coverage'] = dict(status='partial',scope='仅列本版核得的联队或留置支队；其他下级、直属和实到范围未核，不能以已列下级替代全师团。',evidence=copy.deepcopy(u['evidence']))

    def event(phase_id, identity, kind, date, precision, ids, places, text, locator, limit):
        ev = evidence(locator)
        phases[phase_id]['operations'].append(dict(id=identity,kind=kind,date=dict(label=date,precision=precision),
            unit_ids=ids,places=[dict(name=n,position=None,evidence=copy.deepcopy(ev)) for n in places],
            description=text,evidence=ev,limitations='论文记述或转引，未核原件；缺载坐标与数值保持未知。'+limit))
    event('sep28_isolation','WJL-Sep28-149-attachment','concentration','1938-09-28前后；会合时刻未载','range',
        ['ww2.jp.division106','ww2.jp.regiment149'],['万家岭'],
        '149联队与106师团会合后接受其统一指挥；原属101师团，行政隶属不因此改变。',
        '第116页：28日进抵及149联队会合段','这是时段配属参考，不证明后来每一天的到场状态。')
    phases['sep28_isolation']['relations'].append(dict(id='WJL-149-operational-command',kind='operational_command',
        parent_id='ww2.jp.division106',child_id='ww2.jp.regiment149',
        scope='论文所记会合后的临时统一指挥；结束日期未知，不外推成全役或永久行政关系。',
        evidence=evidence('第116页：101师团149联队会合后受106师团长统一指挥')))
    event('sep28_isolation','WJL-Sep28-western-contact','combat','1938-09-28前后；确切日时未载','range',
        ['ww2.cn.division91','ww2.cn.division_reserve6','ww2.jp.regiment123'],['白水街','小坳'],
        '123联队一部向白水街方向突围受阻，西侧由91师、预6师方向部队攻击。',
        '第117页上段：123联队一部及91师、预6师','不把一部交战扩大为整联队已全数参战或被歼。')
    event('oct2_encirclement','WJL-Oct2-east-order','command','1938-10-02；钟点未载','day',
        ['ww2.cn.corps1','ww2.cn.army4','ww2.cn.army74','ww2.cn.division187','ww2.cn.division139'],
        ['南浔线','德星线','万家岭东侧'],
        '薛岳安排4军、74军、187师和139师由东半面包围。',
        '第117页：10月2日东西两路包围命令','下令、启程、到场、展开与首次接敌分别核定；本条不能证明全部同时到场。')
    event('oct2_encirclement','WJL-Oct2-west-order','command','1938-10-02；钟点未载','day',
        ['ww2.cn.corps1','ww2.cn.division_new13','ww2.cn.division_new15','ww2.cn.division91',
         'ww2.cn.division142','ww2.cn.division60','ww2.cn.division_reserve6'],
        ['瑞武线','万家岭西侧'],
        '西半面包围任务交新13师、新15师、91师、142师、60师和预6师。',
        '第117页：10月2日瑞武线方向命令','任务分工不是已核部署；不能由此补造各师到场钟点、实到兵额或精确阵位。')
    event('oct6_orders','WJL-Oct6-relief-blocking','interception','1938-10月上旬、6日前后；抽调钟点未载','range',
        ['ww2.cn.corps1','ww2.cn.division_new13','ww2.cn.division_new15','ww2.cn.division60',
         'ww2.cn.division91','ww2.cn.division_reserve6','ww2.jp.division27','ww2.jp.uga_detachment',
         'ww2.jp.suzuki_detachment','ww2.jp.saeda_detachment'],['武永路','箬溪'],
        '外线援敌推进，第一兵团从包围方向抽调新13、15、60、91和预6师等阻援；各师实际投入范围未载。',
        '第119页上段：宇贺、铃木、佐枝支队及抽调阻援','不改变各师行政归属；不据此认定全师均已撤离内圈。佐枝支队属于27师团留置力量，不能当作全师团同时援入。')
    event('oct12_redeployment','WJL-Oct12-redeployment','command','1938-10-12；钟点未载','day',
        ['ww2.cn.corps1','ww2.cn.army4','ww2.cn.army66','ww2.cn.army74','ww2.cn.division187',
         'ww2.cn.division91','ww2.cn.division_new13','ww2.cn.division60','ww2.cn.division_reserve6','ww2.cn.division142'],
        ['永丰桥','实山','长岭','张古山','杨家岭'],
        '外线压力上升后，4军与66军的一旅转守新线，74军等仍守部分包围线并继续攻击。',
        '第121页：12日转守部署；论文转引12日电（7876278）','命令与实际交接完成时间分开；该段师旅番号与既列编制须再核原件，本版不据此扩展师旅身份或把全66军都标作退场。')
    event('oct17_withdrawal','WJL-Oct16-retrograde','withdrawal','1938-10-16；钟点未载','day',
        ['ww2.cn.division_reserve6','ww2.cn.division61','ww2.cn.corps1'],['甘木关'],
        '外线援敌抵近后，论文记预6师与61师后退；与前述60师阻援记录分列。',
        '第121页：16日后退及17日电引述','61师依论文原字记录，番号异文和隶属待原件复核，不自动改为60师。只记录来源顺序，不强制开放推演照日期撤退；不得以新初态补满损失。')
    event('oct17_withdrawal','WJL-Oct17-withdrawal','withdrawal','1938-10-17；钟点未载','day',
        ['ww2.cn.corps1','ww2.cn.army4','ww2.cn.army66','ww2.jp.division106','ww2.jp.suzuki_detachment'],
        ['永丰桥','实山','郭背山'],
        '论文将中方总撤退、106师团残部与铃木支队取得联系记在17日；仍为残部，不是恢复全师团。',
        '第121页：17日撤退及日本战史引述','不强制开放推演终止或撤离；确切退场钟点、路线、各部余量和重返过程未核。')
    hi.validate_definition(d)
    return d


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--check',action='store_true'); args=p.parse_args()
    value=build(); path=ROOT/'data/historical_initial/AJ07-wanjialing/1.3.0.json'
    if args.check:
        if not path.exists() or json.loads(path.read_text())!=value:raise SystemExit('Wanjialing 1.3.0 source snapshot differs')
        print('Wanjialing 1.3.0 matches page-reviewed builder')
    elif path.exists():
        if json.loads(path.read_text())!=value:raise SystemExit('Refusing to overwrite an existing different version')
        print('Wanjialing 1.3.0 already matches; unchanged')
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        print('Created Wanjialing 1.3.0; old versions and default unchanged')


if __name__=='__main__':main()
