"""Freeze the Oct 6–10 admission contract; never fill numerical estimates."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi, campaign_windows as cw
from tools.upgrade_wanjialing import BATTLE

WINDOW='WJL-oct6-10'
VERSION='1.0.0'
PHASES=['oct6_orders','oct7_attack','oct8_counterattacks','oct9_final_orders','oct10_attacks']
CN=['division90','division159','division160','division161.wjl_part','division51','division58',
    'division60','division139','division141','division187','division_new15','division_new13',
    'division91','division_reserve6','artillery2.battalion3','artillery1.company6','division142.wjl_part']
JP=['division106','regiment149','uga_detachment','suzuki_detachment','saeda_detachment']


def build():
    s=hi.initial(BATTLE,PHASES[0],version='1.3.0')['historical_initial']
    d=s['definition'];index={u['id']:u for u in d['units']}
    selected=['ww2.cn.'+i for i in CN]+['ww2.jp.'+i for i in JP]
    operations={o['id']:o for p in d['phases'] for o in p.get('operations',[])}
    window_events={o['id'] for p in d['phases'] if p['id'] in PHASES for o in p.get('operations',[])}
    def ev(locator):return [{'source_id':'WJL_GUO','locator':locator,
        'note':'已核研究论文印刷页；其转引电报和日方原始档案尚未查阅。'}]
    rows={}
    for u in d['units']:
        identity=u['id'];related=[i for i,o in operations.items() if identity in o['unit_ids']]
        row={'representation':'actor' if identity in selected else 'covered_reference',
            'represented_by':None,'presence_basis':'window_reference',
            'extent':'本窗口所述投入范围；实到兵额、分类装备、阵位及开局状态缺载，不代表全建制满编。',
            'opening':'requires_explicit_estimate','operation_ids':related,
            'operational_reference':None,'evidence':copy.deepcopy(u['evidence'])}
        if u['role']=='command':
            row.update(representation='command_reference',presence_basis='not_applicable',
                extent='历史指挥参考；不生成另一份可交战兵力或重复计入下属资源。')
        elif identity=='ww2.cn.division61':
            row.update(representation='after_window',presence_basis='not_applicable',
                extent='仅核16日后退文字，番号异文待核；不据此投入6—10日窗口。')
        elif identity not in selected:
            # Exactly one display anchor; coverage() separately exposes every
            # selected descendant and the unknown remainder of each ancestor.
            def descendant(candidate):
                parent=index[candidate]['parent_id']
                while parent:
                    if parent==identity:return True
                    parent=index[parent]['parent_id']
                return False
            descendants=[i for i in selected if descendant(i)]
            row['represented_by']=descendants[0] if descendants else 'ww2.jp.division106'
            row['extent']='行政编制或有机下级参考，非额外计算兵力；已列下级不证明覆盖完整，未核余部另行登记。'
        elif any(i in window_events and operations[i]['kind'] in ('attack','combat','counterattack') for i in related):
            row['presence_basis']='reported_action'
        rows[identity]=row
    rows['ww2.jp.regiment123'].update(represented_by='ww2.jp.division106',
        extent='106师团计算聚合包含其有机123联队的本窗口投入部分；不再另建联队，不据“一部”补全整联队。')
    rows['ww2.jp.division106']['extent']='被围106师团在本窗口的原有投入部分，聚合含123联队；不含另列149联队和由补充人员组成的宇贺支队，不使用满编师团人数。'
    rows['ww2.jp.regiment149'].update(presence_basis='prior_reference',
        operational_reference='WJL-149-operational-command',
        extent='9月28日前后会合与临时指挥关系有据，结束日和6—10日连续在场未核；该窗口是否投入、到场时刻及兵额须显式估计，仍行政隶属101师团。')
    rows['ww2.cn.division142.wjl_part'].update(presence_basis='departure_only',
        extent='第142师欠一团；8日11时记载为出发，不是同时到前沿或接敌；不得将启程钟点直接设为首次开火钟点。')
    for identity in ('ww2.cn.division91','ww2.cn.division_reserve6'):
        rows[identity]['extent']='原文为各一部，自西侧攻击并有抽调阻援；不代表整个师全数投入或全师撤离内圈，数值须注明局部估计。'
    for identity in ('ww2.cn.division_new13','ww2.cn.division_new15','ww2.cn.division60'):
        rows[identity]['extent']='包围与外线阻援任务参考；抽调范围、到离场和分兵数量未载，不把全师同时放入内圈和外线。'
    rows['ww2.jp.uga_detachment']['extent']='由另拨106师团补充人员组成的外线支队；与被围师团原有人员分账，不按同一份人员重复计算。'
    rows['ww2.jp.saeda_detachment']['extent']='27师团留置支队的外线投入参考，不是整个27师团进入内圈；兵额和到场须估计。'
    def sector(identity,label,ids,events,pages):
        return dict(id=identity,label=label,position=None,unit_ids=ids,operation_ids=events,evidence=ev(pages))
    sectors=[
        sector('north','金娥殿—公母岭—石堡山北侧方向',
            ['ww2.cn.division159','ww2.cn.division160','ww2.cn.division161.wjl_part'],
            ['WJL-Oct6-redeployment','WJL-Oct7-shibao'],'印刷118—119页：66军移交阵地后集中及7日攻击'),
        sector('east','东侧包围与局部攻击方向',
            ['ww2.cn.division90','ww2.cn.division139','ww2.cn.division141','ww2.cn.division187'],
            ['WJL-Oct2-east-order','WJL-Oct7-eastern'],'印刷117—118页：东西分工和参加部队；具体阵位未核'),
        sector('south','白槎西北—长岭—张古山方向',
            ['ww2.cn.division51','ww2.cn.division58'],
            ['WJL-Oct6-redeployment','WJL-Oct8-zhanggu','WJL-Oct10-74'],'印刷118—120页：51、58师部署与争夺'),
        sector('west','杨家山—松熊及西侧方向',
            ['ww2.cn.division91','ww2.cn.division_reserve6','ww2.cn.division142.wjl_part'],
            ['WJL-Oct8-142-departure','WJL-Oct10-west'],'印刷118—120页：各一部、142师启程及10日攻击'),
        sector('relief','武永路—箬溪外线阻援方向',
            ['ww2.cn.division_new13','ww2.cn.division_new15','ww2.cn.division60',
             'ww2.cn.division91','ww2.cn.division_reserve6','ww2.jp.uga_detachment',
             'ww2.jp.suzuki_detachment','ww2.jp.saeda_detachment'],
            ['WJL-Oct6-relief-blocking'],'印刷119页：援军及阻援抽调，实际数量和到场缺载')]
    value=dict(format=cw.FORMAT,id=WINDOW,version=VERSION,label='万家岭：10月6—10日多军协同窗口（部署待估计）',
        battle=BATTLE,historical_initial={k:s[k] for k in ('profile_id','version','definition_hash')},
        start_phase_id=PHASES[0],phase_ids=PHASES,
        bounds=dict(start='1938-10-06T00:00:00',end='1938-10-11T00:00:00',kind='model_scope_limit',
            note='覆盖6—10日的模型日界，不是史实零点调令；开放模式按目标结束，可延伸，后续援军和史实结果不自动注入。'),
        units=rows,sectors=sectors,milestones=[dict(operation_id=o['id'],phase_id=p['id'],policy='reference_only')
            for p in d['phases'] if p['id'] in PHASES for o in p.get('operations',[])],
        limitations='窗口准入与史实参照，不是完整历史部署认证。逐单位兵力、装备、库存、补给线、精确阵位、临时配属有效期及支援可用量仍须补证或显式估计；原件和日军日志未核。22个计算身份是明确范围的建模候选，不是22个完整建制同时在场。')
    cw.validate_definition(value,s)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    value=build();path=cw.DATA_ROOT/WINDOW/(VERSION+'.json')
    if path.exists():
        if json.loads(path.read_text())!=value:raise SystemExit('Window differs; create a new version instead of overwriting')
        print('Wanjialing window matches; historical defaults unchanged')
    elif args.check:raise SystemExit('Window is missing')
    else:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        print('Created opt-in Wanjialing 6–10 window; numerical estimates remain null')


if __name__=='__main__':main()
