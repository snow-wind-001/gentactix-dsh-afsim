"""Page-reviewed statistical scopes, separate from opening force estimates."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,campaign_windows as cw
from tools.upgrade_wanjialing import BATTLE,evidence
from tools import pin_historical_objectives


def build():
    d=hi.definition(BATTLE,'1.3.0');d['version']='1.4.0'
    d['sources']['WJL_GUO']['limitations']+=(
        '2026-11-02视觉复核印刷119—120页的数值及统计对象；这些是论文转述而非本轮查得馆藏原件。'
        '2700人是编成基干补充人数；每师200—500人为选拔命令；敌群、残部与马匹不得换作全师现员、阵亡或车辆。')
    d['coverage']['notes']+=[
        '1.4.0增加6条分阶段数值资料；不是逐单位开局实力表，不修改原facts空值、旧版本或默认入口。',
        '明确数只表示来源这样报数；超过某数、区间和约数分列，不人为取中值或伪造精确误差。',
        '数值资料通过已有retrieve_history(kind=measurements)分页读取；不自动覆盖本局人员、装备、库存或裁决。']
    phases={p['id']:p for p in d['phases']}
    def row(phase,identity,date,precision,units,metric,relation,lower,upper,statistic,population,page,limitations):
        units_by_metric={'personnel':'persons','horses':'horses'}
        phases[phase].setdefault('measurements',[]).append(dict(id=identity,date=dict(label=date,precision=precision),
            unit_ids=units,metric=metric,quantity=dict(relation=relation,lower=lower,upper=upper,unit=units_by_metric[metric]),
            statistic=statistic,population=population,evidence=evidence(page),
            limitations='研究论文记述／转引，未核原始报表。'+limitations))
    row('oct6_orders','WJL-M-uga-replacements','10月上旬、6日前后，编成确日未载','range',
        ['ww2.jp.uga_detachment'],'personnel','eq',2700,2700,'replacement_basis',
        '宇贺支队以新拨106师团补充人员为基干的编成人数，不是全支队实力或被围106师团现员。',
        '印刷119页首段，补充基干与外线援军',
        '未载支队全部附属人员、到场时间与后续损失；不能将2700人重复加到被围部队。')
    row('oct7_attack','WJL-M-liujialing-contact','1938-10-07 7时','hour',
        ['ww2.cn.army4','ww2.jp.division106'],'personnel','gt',300,None,'reported_enemy_group',
        '第4军游击部队在刘家岭遭遇的一批敌军，不是日军整师团人数或被歼数。',
        '印刷119页第三期总攻段，7时遭遇',
        '具体联队、后续去向和伤亡未据本句核定。')
    row('oct8_counterattacks','WJL-M-zhanggu-counterattack','1938-10-08天明后','period',
        ['ww2.cn.division51','ww2.jp.division106'],'personnel','gt',1000,None,'reported_enemy_group',
        '飞机支援下反攻张古山最高点的一批敌军，不是全役日军总数或日军死亡。',
        '印刷119页末段，拂晓后张古山反攻',
        '天明后不是确证钟点；本句不载具体联队、损失与飞机数量。')
    row('oct9_final_orders','WJL-M-assault-party-order','1938-10-09 15时下令；18时准备、19时攻击','hour',
        ['ww2.cn.corps1'],'personnel','range',200,500,'ordered_detachment',
        '参加攻击各师拟选的奋勇队人数，统计分母为每师，不是全师兵额或战死人数。',
        '印刷120页，15时命令每师选拔奋勇队',
        '命令不证明各师已实际选足、同时到场或每队都执行成功；不得对全部参战师机械求和。')
    row('oct10_attacks','WJL-M-retreating-personnel','1938-10-10 3时攻占以后，退却确时未载','period',
        ['ww2.cn.army66','ww2.jp.division106'],'personnel','gt',1000,None,'reported_retreat_group',
        '万家岭、田步苏方向被击退后北退的一批残部，不是全师团残存总数或死亡总数。',
        '印刷120页，66军克复后的北退残部',
        '另有其他地域残敌；不能从该群体人数反推全师团战损或宣布战役结束。')
    row('oct10_attacks','WJL-M-retreating-horses','1938-10-10 3时攻占以后，退却确时未载','period',
        ['ww2.cn.army66','ww2.jp.division106'],'horses','gt',300,None,'reported_retreat_group',
        '上述北退群体伴随的马匹，不是运输车辆、全部师团辎重或缴获数量。',
        '印刷120页，残部与马匹北退同句',
        '没有载重、用途、存活与缴获明细，不换算为卡车或标准补给吨位。')
    units={u['id']:u for u in d['units']}
    for parent in ('ww2.cn.army4','ww2.cn.army66','ww2.cn.army74','ww2.cn.army32'):
        children=[u for u in d['units'] if u['parent_id']==parent]
        if children:
            units[parent]['children_coverage']=dict(status='partial',
                scope='只列本版有来源的下级与投入部；未核机关直属、缺载下级及全部实到，不能用已列下级替代全军。',
                evidence=evidence('印刷118—119页参战部队与分方向投入；只证明所列身份，不证明完整编制'))
    hi.validate_definition(d)
    return d


def window(definition):
    d=copy.deepcopy(cw.load('WJL-oct6-10','1.3.0'));d.update(version='1.4.0',label='万家岭：10月6—10日地面会战 · 分口径数值参照')
    d['historical_initial']=dict(profile_id=definition['id'],version=definition['version'],definition_hash=hi.digest(definition))
    d['limitations']+=' 1.4.0绑定阶段数值资料；沿用1.3.0显式估计基线，不将2700等来源数值当作开局事实，也不宣称历史标定。'
    snapshot=hi._materialize(definition,'oct6_orders')['historical_initial'];cw.validate_definition(d,snapshot)
    return d


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    definition=build();values={hi.DATA_ROOT/'AJ07-wanjialing/1.4.0.json':definition,cw.DATA_ROOT/'WJL-oct6-10/1.4.0.json':window(definition)}
    for path,value in values.items():
        if path.exists():
            if json.loads(path.read_text())!=value:raise SystemExit('Existing version differs; create a new version: '+str(path))
        elif args.check:raise SystemExit('Version missing: '+str(path))
        else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    pin_historical_objectives.main()
    print('Wanjialing1.4.0 scoped quantities, bound window and objective pin match; default/old versions unchanged')


if __name__=='__main__':main()
