"""Publish a dated reference table without changing old deployments or defaults.

Run from the repository root: python -m tools.upgrade_long_march_strengths [--check]
No network, model calls, runtime configuration or existing games are accessed.
"""
import argparse
import copy
import json
from pathlib import Path

from gentactix import historical_initial as hi
from tools import render_long_march

ROOT=Path(__file__).resolve().parents[1]
BATTLE='红军长征-湘江战役-1934.11.25至1934.12.01'
PROFILE='LM01-xiangjiang'
VERSION='1.1.0'
PHASE='oct8_strength_reference'
SOURCE='XJ_OCT8_SH2026'
GROUP='出发前统计参考（1934年10月8日，非湘江部署）'
URL='https://www.ccphistory.org.cn/shds/dsxx/content/064b44dc-971a-4c00-a790-895b669edfbc.html'
IMAGE='https://cms.odb.sh.cn/shds/upload/16d48e93-9a6e-477d-bfaa-ec68bcdff85d.jpg'
IMAGE_SHA='6d39f46a072ed9b0f0eeea3bf753391d9308797499665424134a7575cd2efa94'
ROWS=[
    ('lm.red.corps1','红一军团','formation','军团',17280,2600,19880),
    ('lm.red.corps3','红三军团','formation','军团',15205,2600,17805),
    ('lm.red.corps5','红五军团','formation','军团',10868,1300,12168),
    ('lm.red.corps8','红八军团','formation','军团',9022,1900,10922),
    ('lm.red.corps9','红九军团','formation','军团',10238,1300,11538),
    ('lm.red.cmc_column1','军委纵队（1934年10月报列）','command','纵队参考',4693,None,4693),
    ('lm.red.cmc_column2','罗迈纵队（1934年10月报列）','command','纵队参考',9853,None,9853),
]
LIMITATION=('限1934-10-08的表列对象；不是1934年11月湘江开局人数，不证明拟补充已入队或部队空间到场，'
            '不向师团摊配，不作为战斗减员。公开重排表已核读，原件影印、单位注记与统计是否覆盖全部附属人员仍待复核。')


def evidence(locator):return [dict(source_id=SOURCE,locator=locator)]


def measurement(identity,units,statistic,number,population):
    return dict(id=identity,date=dict(label='1934-10-08',precision='day'),unit_ids=units,metric='personnel',
        quantity=dict(relation='eq',lower=number,upper=number,unit='persons'),statistic=statistic,
        population=population,evidence=evidence('图3《野战军人员武器弹药供给统计表》人员三行；'+population),
        limitations=LIMITATION+(' 含计划数与分项重叠，不可重复相加。'if statistic=='reported_strength_including_plan'else
            ' 拟补充不等于实际补入；无独立增补事件。'if statistic=='planned_replacement'else
            ' “现有”只描述统计日报列数，不代表后续日期实力。'))


def build():
    value=hi.definition(BATTLE,'1.0.0');value['version']=VERSION
    value['sources'][SOURCE]=dict(title='伟大的出发 永远的长征⑥：中共中央和中央红军主力集结于都（一）',
        url=URL,publisher='上海党史网，来源党史镜报，2026-10-13',evidence_kind='official_history',
        original_archive_examined=False,limitations=LIMITATION+' 图3为公开重排，不称原件影印。图像SHA-256='+IMAGE_SHA)
    old_phases=[p['id']for p in value['phases']]
    phase=dict(id=PHASE,label='1934年10月8日人员统计参考（非可执行部署）',
        date=dict(label='1934-10-08',precision='day',evidence=evidence('正文10月8日统计及图3题日期')),
        scope='出发前日期限定的人员测量；不新增湘江战斗单位、地理部署或可运行窗口。缺载阵位和后续实力保持未知。',
        evidence=evidence('正文10月8日统计与图3人员栏'),measurements=[])
    known={u['id']:u for u in value['units']}
    for identity,name,role,echelon,present,plan,total in ROWS:
        if identity not in known:
            unit=dict(id=identity,name=name,team='red',role=role,echelon=echelon,parent_id=None,
                evidence=evidence('图3该单位列名；仅核统计对象，未据表推定永久隶属和后期部署'),
                presence=[dict(phase_id=p,status='outside_scope',evidence=evidence(
                    '本条仅10月8日统计参考，不据表补入11月计算阶段；不等于该部历史上未参战'))for p in old_phases],
                facts={k:dict(value=None,evidence=[],scope='日期限定数值列于'+PHASE+'的measurements；本无日期字段保持未知，不移作11月实力或阵位。')for k in ('personnel','equipment','position')})
            if role=='formation':unit['children_coverage']=dict(status='unknown',scope='仅核统计列名，未核下级全覆盖或余部；不自动分摊兵额。',evidence=evidence('图3军团层级，不提供师团分项'))
            value['units'].append(unit);known[identity]=unit
        key=identity.rsplit('.',1)[1]
        phase['measurements'].append(measurement('XJ-M-oct8-'+key+'-existing',[identity],
            'reported_existing_strength',present,name+'的“现有”栏报列人数'))
        if plan is not None:
            phase['measurements'].append(measurement('XJ-M-oct8-'+key+'-planned',[identity],
                'planned_replacement',plan,name+'的“最后拟补充”栏计划人数'))
        phase['measurements'].append(measurement('XJ-M-oct8-'+key+'-including-plan',[identity],
            'reported_strength_including_plan',total,name+'的“小计”；含拟补充，与上述分项重叠'))
    all_ids=[r[0]for r in ROWS];planned_ids=[r[0]for r in ROWS if r[5] is not None]
    for statistic,ids,number,label in [
        ('reported_existing_strength',all_ids,77159,'表列七单位“现有”合计；与各单位分项重叠'),
        ('planned_replacement',planned_ids,9700,'表列有填数的五军团“最后拟补充”合计；与各单位计划分项重叠'),
        ('reported_strength_including_plan',all_ids,86859,'表列含拟补充总计；与各单位小计及现有、拟补充分项重叠')]:
        phase['measurements'].append(measurement('XJ-M-oct8-total-'+statistic,ids,statistic,number,label))
    for unit in value['units']:
        unit['presence'].append(dict(phase_id=PHASE,status='unverified'if unit['id']in all_ids or unit['id']=='lm.red.cmc'else'outside_scope',
            evidence=evidence('统计列名不等于地理到场；unverified表示未形成可执行部署，非否认报列身份。未列师团与对手不补造。')))
    value['phases'].append(phase)
    value['coverage']['notes'].append(
        '1.1.0新增10月8日七单位22条日期限定人员测量及六个参考身份。77159现有、9700拟补充、86859含计划总计分别保存。'
        '军委两纵队为混合机关与直属人员统计参考，不生成两支步兵；与后期军委纵队汇总身份的覆盖对应未核，不自动跨阶段合并。'
        '本新增参考不扩张旧11月局部或累计执行名单，不提升历史初态完整度。')
    hi.validate_definition(value)
    return value


def artifacts():
    value=build()
    bindings_path=ROOT/'data/historical_objective_bindings.json'
    bindings=json.loads(bindings_path.read_text())
    previous=copy.deepcopy(bindings['profiles'][PROFILE]['1.0.0'])
    previous['initial_definition_hash']=hi.digest(value)
    bindings['profiles'][PROFILE][VERSION]=previous
    scenarios_path=ROOT/'data/long_march/scenarios.json';sources_path=ROOT/'data/long_march/sources.json'
    scenarios=json.loads(scenarios_path.read_text());sources=json.loads(sources_path.read_text())
    scenario=next(s for s in scenarios['scenarios']if s['id']=='LM01')
    if SOURCE not in scenario['sources']:scenario['sources'].append(SOURCE)
    scenario['forces']=[r for r in scenario['forces']if not(r.get('detail_group')==GROUP and SOURCE in r['sources'])]
    for _,name,_,_,present,plan,total in ROWS:
        description=(f'1934-10-08统计重排表列现有{present}人；'+
            (f'最后拟补充{plan}人；含计划小计{total}人。'if plan is not None else
             f'拟补充栏空白，保留缺载；小计{total}人，不另断言补充为0。')+
            '仅日期限定报告参考，非湘江开局、地理到场或师团兵额，不作为11月投入。')
        scenario['forces'].append(dict(side='红军',unit=name,description=description,detail_group=GROUP,
            sources=[SOURCE],evidence_status='published_account',source_locator={SOURCE:'图3人员栏：该单位列的现有、最后拟补充、小计；公开重排，非原件影印'}))
    metrics=[('10月8日报列现有人数',77159),('10月8日拟补充人数',9700),('10月8日含计划人数合计',86859)]
    scenario['figures']=[r for r in scenario['figures']if not(SOURCE in r['sources']and r['metric']in{m for m,_ in metrics})]
    for metric,number in metrics:
        scenario['figures'].append(dict(side='红军',metric=metric,value=number,qualifier='人',
            scope='1934-10-08公开统计表列七单位；含计划数与现有分项重叠，不是11月湘江开局',
            note=LIMITATION+' 77159+9700=86859是该表列关系，不证明计划已经落实。',sources=[SOURCE],
            evidence_status='published_account',source_locator={SOURCE:'图3人员栏合计列：现有／最后拟补充／小计'}))
    note='10月8日报列现有、最后拟补充与含计划小计分别保存；不将计划当到场，不与10月出发报道或11月战役实力混用。'
    if note not in scenario['uncertainties']:scenario['uncertainties'].append(note)
    scenario['checked']='2026-11-04'
    sources['sources'][SOURCE]=dict(title=value['sources'][SOURCE]['title'],publisher=value['sources'][SOURCE]['publisher'],url=URL,
        evidence_type='官方公开统计重排表（非档案原件影印）',supports='1934-10-08各列现有、拟补充和含计划小计；不证实11月实力或空间部署',
        accessed='2026-11-04',original_archive_examined=False,caveat=LIMITATION+' 图像：'+IMAGE+'；SHA-256='+IMAGE_SHA)
    return {hi.DATA_ROOT/PROFILE/(VERSION+'.json'):value,bindings_path:bindings,scenarios_path:scenarios,sources_path:sources}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    stale=[]
    for path,value in artifacts().items():
        text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
        if args.check:
            if not path.exists()or path.read_text()!=text:stale.append(str(path.relative_to(ROOT)))
        elif not path.exists()or path.read_text()!=text:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    if args.check:
        for path,text in render_long_march.render().items():
            if not path.exists()or path.read_bytes()!=text.encode():stale.append(str(path.relative_to(ROOT)))
    else:
        for path,text in render_long_march.render().items():
            if not path.exists()or path.read_bytes()!=text.encode():path.write_bytes(text.encode())
    if stale:raise SystemExit('Out of date: '+', '.join(stale))
    print('PASS dated Long March statistics '+('checked'if args.check else 'published')+'; old versions/defaults and event clocks retained')


if __name__=='__main__':main()
