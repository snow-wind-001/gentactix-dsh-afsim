"""Publish sourced Xiangjiang process links, retaining old versions and defaults.

Run: python -m tools.upgrade_xiangjiang_campaign [--check]
This adds historical references, not a fabricated executable campaign window.
"""
import argparse
import copy
import json
from pathlib import Path

from gentactix import historical_initial as hi
from tools import render_long_march

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'LM01-xiangjiang'
VERSION = '1.2.0'
BATTLE = '红军长征-湘江战役-1934.11.25至1934.12.01'
GROUP = '全役部队与纵队参考（不等于同日全部投入）'
DATE_IDS = ['1934-11-25', '1934-11-26', '1934-11-27', '1934-11-28',
            '1934-11-29', '1934-11-30', '1934-12-01']
CANONICAL_IDS = [
    'LM01-Nov25-westward-order', 'LM01-Nov26-xinxu-order', 'LM01-Nov26-column-march',
    'LM01-Nov27-crossings', 'LM01-Nov27-column-march', 'LM01-Nov28-two-fronts',
    'LM01-Nov28-column-march', 'LM01-Nov29-xinxu-reinforcements', 'LM01-Nov29-guanghuapu',
    'LM01-Nov29-column-march', 'LM01-Nov30-xinxu-withdrawal', 'LM01-Nov30-guanghuapu-relief',
    'LM01-Nov30-regiment18', 'LM01-Dec1-urgent-order-context', 'LM01-Dec1-urgent-order-0330',
    'LM01-Dec1-main-crossing-reference',
]
SOURCE_MAP = {'S03': 'XJ_NJ2016', 'S04': 'XJ_XH2026', 'S26': 'XJ_PARTY_HISTORY',
              'S29': 'XJ_GX', 'S30': 'XJ_MEM', 'S31': 'XJ_FJ'}
RED34 = 'XJ_RED34_2022'
PLA = 'XJ_PLA2026'
RED34_URL = 'https://cpc.people.com.cn/n1/2022/1108/c443712-32561457.html'
PLA_URL = 'https://rmt-static-publish.81.cn/file/20260129/5b2fb5208e44186f0e61997f8a3bc52b.pdf'
UNIT_DETAILS = {
    'division1': ('脚山铺段：27日一个团、30日凌晨主力', '27日仅其一个未具名团见于脚山铺记述，30日凌晨主力赶到；不提前整师。'),
    'division2': ('脚山铺段：红二师5、6团与29日红四团', '脚山铺阻击方向，部分具名团可核；实际兵额和完整下级覆盖未知。'),
    'regiment4': ('脚山铺段：29日红二师第四团团长耿飚', '29日脚山铺方向坚守；不能把后述行动等同27日已在同一阵地。'),
    'regiment5': ('脚山铺首段：27日在该方向的第五团', '27日脚山铺先到部队之一，不从二师总数摊配本团人数。'),
    'regiment6': ('脚山铺首段：27日在该方向的第六团', '27日脚山铺先到部队之一，详细阵位和该团实有装备缺载。'),
    'division13': ('抢渡湘江段：五军团部和十三师天亮前过江', '12月1日天亮前涉渡的具名师；不代表第五军团全部或红34师已过江。'),
    'division34': ('尾声段：红五军团第三十四师', '后卫与接防任务有关，命令、到场、完成及突围分开；不强制单位按历史日期消失。'),
    'regiment100': ('红34师回顾：韩伟第100团及第1营身份', '红34师具名下级；只核身份，不将有异文的突围时间和人员故事转为精确战损。'),
    'regiment101': ('红34师回顾：第101、102团与师部', '红34师具名下级；回顾日期有待原始资料复核，不按回顾人数补全团实力。'),
    'regiment102': ('红34师回顾：第101、102团与师部', '红34师具名下级；不因列出三个团即宣称完整直属、支援和人员覆盖。'),
    'field_column1': ('抢渡湘江段：第一野战纵队30日清晨渡江、鲁塘', '11月30日清晨渡江，向鲁塘转移；混合机关及直属人员不作为等额步兵。'),
    'field_column2': ('抢渡湘江段：第二野战纵队30日黄昏渡江、洛江圩', '11月30日黄昏渡江，向洛江圩转移；不与第一纵队并为同刻、同路或同一人员统计列。'),
    'corps5_hq': ('抢渡湘江段：五军团部与十三师，34师另述', '仅军团部参考，不是全军团或额外步兵实体；后卫红34师不能随此判作过江。'),
}


def ev(source, locator):
    return [dict(source_id=source, locator=locator)]


def inputs():
    scenarios = json.loads((ROOT / 'data/long_march/scenarios.json').read_text())
    sources = json.loads((ROOT / 'data/long_march/sources.json').read_text())
    scenario = next(s for s in scenarios['scenarios'] if s['id'] == 'LM01')
    if len(scenario['events']) != len(CANONICAL_IDS):
        raise ValueError('原湘江事件条目已变，须先复核对应，不能按位置静默错绑')
    return scenarios, sources, scenario


def operation(identity, kind, date, units, places, description, source, locator,
              limitations='', precision='day'):
    evidence = ev(source, locator)
    return dict(id=identity, kind=kind, date=dict(label=date, precision=precision), unit_ids=units,
        places=[dict(name=name, position=None, evidence=copy.deepcopy(evidence)) for name in places],
        description=description, evidence=evidence,
        limitations=limitations + ' 公开记述未核原始电令或逐单位实力；地名无据坐标保持空。关联不等于本局命令、实时到场、整建制投入或计算战果。')


def build():
    _, registry, scenario = inputs()
    d = hi.definition(BATTLE, '1.1.0'); d['version'] = VERSION
    for old_id in ('S03', 'S04', 'S26'):
        source = registry['sources'][old_id]
        d['sources'][SOURCE_MAP[old_id]] = dict(title=source['title'], url=source['url'],
            publisher=source['publisher'], evidence_kind='published_secondary', original_archive_examined=False,
            limitations='公开回顾／书籍公开章节，原档案未阅；保留既有事件精度与异文，不升级为逐小时部署或完整建制。')
    d['sources'][RED34] = dict(title='湘江战役34师幸存的3位开国将军', url=RED34_URL,
        publisher='中国共产党新闻网，2022-11-08', evidence_kind='published_secondary', original_archive_examined=False,
        limitations='公开回顾可核身份、上级和接防命令；突围日期与其他记述有待复核，不采作强制定时结局。原HTML按GB18030核读，非UTF-8乱码提取。')
    d['sources'][PLA] = dict(title='湘江战役重要研究成果报告', url=PLA_URL,
        publisher='褚银，解放军报2026-01-29第12版', evidence_kind='published_secondary', original_archive_examined=False,
        limitations='研究参与者介绍资料选编，非已阅全书或原始档案；可考部分损失、出发至战役后减员及阵亡不可混用。PDF原页已核看。')
    base_evidence = ev('XJ_GX', '脚山铺阻击与抢渡湘江分节；具体时段和下级覆盖按各事件')
    additions = [
        ('division1', '红一军团第1师', 'corps1', '师', 'formation', 'XJ_GX'),
        ('division2', '红一军团第2师', 'corps1', '师', 'formation', 'XJ_GX'),
        ('regiment4', '红一军团第2师第4团', 'division2', '团', 'formation', 'XJ_GX'),
        ('regiment5', '红一军团第2师第5团', 'division2', '团', 'formation', 'XJ_GX'),
        ('regiment6', '红一军团第2师第6团', 'division2', '团', 'formation', 'XJ_GX'),
        ('division13', '红五军团第13师', 'corps5', '师', 'formation', 'XJ_GX'),
        ('division34', '红五军团第34师', 'corps5', '师', 'formation', 'XJ_GX'),
        ('regiment100', '红五军团第34师第100团', 'division34', '团', 'formation', RED34),
        ('regiment101', '红五军团第34师第101团', 'division34', '团', 'formation', RED34),
        ('regiment102', '红五军团第34师第102团', 'division34', '团', 'formation', RED34),
        ('field_column1', '军委第一野战纵队（湘江渡江记述）', None, '纵队', 'command', 'XJ_GX'),
        ('field_column2', '军委第二野战纵队（湘江渡江记述）', None, '纵队', 'command', 'XJ_GX'),
        ('corps5_hq', '红五军团部（湘江后续渡江）', 'corps5', '军团部', 'command', 'XJ_GX'),
    ]
    for short, name, parent, echelon, role, source in additions:
        evidence = ev(source, UNIT_DETAILS[short][0])
        d['units'].append(dict(id='lm.red.' + short, name=name, team='red', role=role, echelon=echelon,
            parent_id='lm.red.' + parent if parent else None, evidence=evidence,
            presence=[dict(phase_id=p['id'], status='campaign_participant' if p['id']=='campaign_reference' else 'outside_scope',
                evidence=copy.deepcopy(evidence)) for p in d['phases']],
            facts={k:dict(value=None, evidence=[], scope='具名任务和地域不证明本阶段实际人数、分类装备或可配准阵位；保留未知。')
                   for k in ('personnel', 'equipment', 'position')}))
    units = {u['id']:u for u in d['units']}
    for identity in ('corps1', 'corps5', 'division2', 'division34'):
        evidence = ev(RED34, '仅核红34师所列第100、101、102团身份，未核完整直属覆盖') if identity=='division34' else copy.deepcopy(base_evidence)
        units['lm.red.' + identity]['children_coverage'] = dict(status='partial',
            scope='只列本次资料能关联的下级；一师未具名团、其他师和直属余部未核，不宣称完整覆盖或按满编补数。', evidence=evidence)
    for identity in ('corps1', 'corps5', 'corps8', 'corps9'):
        row = next(p for p in units['lm.red.' + identity]['presence'] if p['phase_id']=='campaign_reference')
        row.update(status='campaign_participant', evidence=copy.deepcopy(base_evidence))
    next(p for p in d['phases'] if p['id']=='campaign_reference')['scope'] = '三大阻击方向、渡场、纵队与后卫的累计参考；仍缺完整敌我序列、同日部署和余部，不能直接作为全会战开局。'

    bindings = [
        (['cmc','corps1','corps3','corps5','corps8','corps9'], ['湘江','全州','兴安'], 'command'),
        (['division5'], ['新圩'], 'command'),
        (['field_column1','field_column2'], ['永安关','桂岩'], 'movement'),
        (['corps1','corps3'], ['界首','屏山渡'], 'concentration'),
        (['field_column1','field_column2'], ['桂岩','文市'], 'movement'),
        (['regiment14','regiment15','cmc_artillery_battalion','regiment10'], ['新圩','光华铺'], 'combat'),
        (['field_column1','field_column2'], ['文市','石塘'], 'movement'),
        (['division5'], ['新圩'], 'concentration'),
        (['regiment10'], ['光华铺'], 'combat'),
        (['field_column1','field_column2'], ['石塘','界首'], 'movement'),
        (['division5'], ['新圩','界首'], 'withdrawal'),
        (['division4','division5'], ['光华铺','界首'], 'relief'),
        (['regiment18'], ['新圩','炮楼山','陈家背'], 'relief'),
        (['cmc'], ['湘江'], 'command'),
        (['cmc'], ['湘江'], 'command'),
        (['cmc','field_column1','field_column2'], ['湘江'], 'movement'),
    ]
    operations = []
    for identity, row, (short_ids, places, kind) in zip(CANONICAL_IDS, scenario['events'], bindings):
        refs = [dict(source_id=SOURCE_MAP[s], locator=row.get('source_locator', {}).get(s, '原事件出处')) for s in row['sources']]
        op = operation(identity, kind, row['date']+' '+row['time_label'], ['lm.red.'+i for i in short_ids], places,
            row['event'], refs[0]['source_id'], refs[0]['locator'],
            limitations='保持原时段及异文；同日未载先后不强排钟点，命令不证明执行。两方向事件的单位不表示全部同时位于每个地名。'
                + (' 纵队日行程是来源集体道路行程，不是两个纵队分别完成同样距离或逐小时速度。' if row.get('process_reference') else ''),
            precision={'日':'day','时段':'period','小时':'hour'}[row['precision']])
        op['evidence'] = refs
        for place in op['places']: place['evidence'] = copy.deepcopy(refs)
        if identity=='LM01-Nov28-two-fronts': op['unit_ids'].append('lm.gx.division44')
        if identity=='LM01-Nov29-xinxu-reinforcements': op['unit_ids'] += ['lm.gx.division24','lm.gx.division45']
        if identity=='LM01-Nov29-guanghuapu': op['unit_ids'].append('lm.gx.division43')
        operations.append(op)

    extras = [
        ('LM01-Nov27-jiaoshanpu-detachments','defense','1934-11-27',['lm.red.regiment5','lm.red.regiment6'],['脚山铺'],
         '已列红二师第5、6团在脚山铺方向；另有红一师一个团，番号未载。','XJ_GX','脚山铺首段：27日所在部队',
         '红一师一个团不等于全师主力已经到场；无名团不补编号。','day'),
        ('LM01-Nov28-guanghuapu-defense','defense','1934-11-28',['lm.red.regiment10'],['光华铺','界首'],
         '红10团前出光华铺布防，守护界首南面通道。','XJ_GX','光华铺段：28日接防与派出10团',
         '布防不等于当日已发生29日夜间主战斗。','day'),
        ('LM01-Nov29-jiaoshanpu-combat','defense','1934-11-29',['lm.red.division2','lm.red.regiment4','lm.red.regiment5','lm.red.regiment6'],['脚山铺','尖峰岭','黄帝岭'],
         '红二师在脚山铺方向阻击湘军，阵地向黄帝岭收缩。','XJ_GX','脚山铺段：29日猛攻、红四团坚守及退守',
         '同一师和下级是关联参考，不能重复计兵；湘军具体师团及逐时部署尚未入档。','day'),
        ('LM01-Nov30-division1-main-arrival','movement','1934-11-30 凌晨',['lm.red.division1'],['道县','脚山铺'],
         '红一师主力从道县方向赶到脚山铺。','XJ_GX','脚山铺段：30日凌晨主力赶到',
         '不证明11月27日整师已经到场，逐团抵达时间和路线未载。','period'),
        ('LM01-Nov30-column1-crossing','movement','1934-11-30 清晨',['lm.red.field_column1'],['界首渡口','鲁塘'],
         '军委第一野战纵队清晨经界首渡江，当天向鲁塘前进。','XJ_GX','抢渡湘江段：第一纵队29日晚抵界首以东、30日清晨过江',
         '不能把第二纵队黄昏过江提前到清晨；未证明与10月报列统计列的完整人员映射。','period'),
        ('LM01-Nov30-column2-crossing','movement','1934-11-30 黄昏',['lm.red.field_column2'],['月亮山','界首渡口','洛江圩'],
         '军委第二野战纵队上午抵界首以东，黄昏渡江，随后进入洛江圩方向。','XJ_GX','抢渡湘江段：第二纵队30日上午、黄昏及洛江圩',
         '不与第一纵队合并为同刻渡江；混合机关和直属人员不生成独立步兵，装载与运力仍未核。','period'),
        ('LM01-Nov30-rearguard-relief-order','command','1934-11-30 晨',['lm.red.division34'],['水车','枫树脚'],
         '公开回顾记红34师接到由水车向枫树脚接替红18团的命令。',RED34,'红34师回顾：30日晨接到接防命令',
         '命令不证明实际接防、完成或突围时间；该文后续日期异文不采为强制结局。','period'),
        ('LM01-Dec1-corps9-crossing','movement','1934-12-01 凌晨',['lm.red.corps9'],['凤凰嘴','咸水'],
         '红九军团从凤凰嘴涉渡，随后向咸水地域转移。','XJ_GX','抢渡湘江段：12月1日红九军团',
         '凌晨没有确证钟点，不与3时半电令强排先后；不证明全员无损通过。','period'),
        ('LM01-Dec1-corps5-crossing','movement','1934-12-01 天亮前',['lm.red.corps5_hq','lm.red.division13'],['凤凰嘴'],
         '红五军团部和红十三师掩护兄弟部队后从凤凰嘴涉渡。','XJ_GX','抢渡湘江段：五军团部和十三师天亮前过江',
         '军团部不是另一支等额步兵；不把红34师也判作已随同通过。','period'),
        ('LM01-Dec1-corps8-crossing','movement','1934-12-01 下午',['lm.red.corps8'],['凤凰嘴'],
         '红八军团至下午赶至凤凰嘴方向抢渡。','XJ_GX','抢渡湘江段：八军团12月1日下午过江',
         '不从出发兵额反推此时实力、死伤或逐时通过率。','period'),
        ('LM01-Dec1-jiaoshanpu-withdrawal','withdrawal','1934-12-01 下午',['lm.red.division1','lm.red.division2'],['白沙河','越城岭'],
         '一、二师掩护后边打边撤，进入越城岭方向。','XJ_GX','脚山铺段：12月1日白沙河防线及下午撤离',
         '任务完成是该公开记述，不强制开放推演胜负；未载具体钟点和逐团撤退路径。','period'),
    ]
    operations.extend(operation(*row) for row in extras)
    for date in DATE_IDS:
        rows = [o for o in operations if o['date']['label'].startswith(date)]
        # These are curated display constraints, not inferred exact timestamps.
        # Unknown/variant relations within each day remain explicitly unknown.
        known_order = {
            '1934-11-30': ['LM01-Nov30-division1-main-arrival', 'LM01-Nov30-rearguard-relief-order',
                'LM01-Nov30-column1-crossing', 'LM01-Nov30-regiment18',
                'LM01-Nov30-guanghuapu-relief', 'LM01-Nov30-xinxu-withdrawal', 'LM01-Nov30-column2-crossing'],
            '1934-12-01': ['LM01-Dec1-urgent-order-context', 'LM01-Dec1-urgent-order-0330',
                'LM01-Dec1-corps9-crossing', 'LM01-Dec1-corps5-crossing',
                'LM01-Dec1-corps8-crossing', 'LM01-Dec1-jiaoshanpu-withdrawal', 'LM01-Dec1-main-crossing-reference'],
        }.get(date)
        if known_order:
            rows.sort(key=lambda row: known_order.index(row['id']))
        evidence = copy.deepcopy(base_evidence)
        phase = dict(id='day_'+date.replace('-',''), label=date+'全役过程关联（非计算初态）',
            date=dict(label=date, precision='day', evidence=evidence),
            scope='多方向同日史料关联；时段可重叠或有异文，展示不等于其余事件确证先后。无同地部署、库存及完整敌我序列，不提供可执行窗口。',
            evidence=evidence, operations=rows, relations=[])
        mentioned = {i for row in rows for i in row['unit_ids']}
        for u in d['units']:
            if u['parent_id'] and (u['id'] in mentioned or u['parent_id'] in mentioned):
                phase['relations'].append(dict(id='LM01-'+date.replace('-','')+'-'+u['id'], kind='administrative',
                    parent_id=u['parent_id'], child_id=u['id'], scope='行政参考关系，不证明同时同地到场或完整下级覆盖。', evidence=copy.deepcopy(u['evidence'])))
        d['phases'].append(phase)

    reduction_units = ['lm.red.'+i for i in ('corps1','corps3','corps5','corps8','corps9','field_column1','field_column2')]
    measurements = []
    for identity, statistic, number, relation, ids, date, population in [
        ('partial-known','documented_partial_reduction',9400,'approx',reduction_units,'1934年湘江战役期间','研究能明确的部分减员，不是全役合计或阵亡数'),
        ('departure-after','reported_reduction',51400,'approx',reduction_units,'1934年10月出发至湘江战役后','出发至战役后的总体减员；关联对象不证明完整统计覆盖映射'),
        ('corps1','reported_reduction',6000,'gt',['lm.red.corps1'],'1934年湘江战役期间','红一军团损失，非脚山铺单点或逐师合计'),
    ]:
        measurements.append(dict(id='LM01-loss-'+identity, date=dict(label=date, precision='range'), unit_ids=ids,
            metric='personnel', quantity=dict(relation=relation,lower=number,upper=None if relation=='gt' else number,unit='persons'),
            statistic=statistic, population=population, evidence=ev(PLA,'第12版左侧褚银文章：明确损失约9400、出发至战役后约51400、红1军团6000余'),
            limitations='研究介绍而非原报告／档案已阅；可考部分、总体减员与阵亡不可通约，不能作为扣兵配额、初态或强制结局。含时段或总体重叠，不与分项重复相加。'))
    d['phases'].append(dict(id='loss_scope_reference',label='湘江相关减员口径参考（不作伤亡配额）',
        date=dict(label='1934年长征出发至湘江战役后，分项起算不同',precision='range',evidence=ev(PLA,'第12版损失研究介绍')),
        scope='日期及总体分项不同的公开研究统计，不是可执行部署、完整阵亡总数或裁决目标。',
        evidence=ev(PLA,'第12版损失研究介绍'),measurements=measurements))
    for u in d['units']:
        for phase in d['phases']:
            if any(p['phase_id']==phase['id'] for p in u['presence']): continue
            mentioned = any(u['id'] in row['unit_ids'] for row in phase.get('operations',[]))
            u['presence'].append(dict(phase_id=phase['id'],status='campaign_participant' if mentioned else 'unverified',
                evidence=copy.deepcopy(phase['evidence'])))
    d['coverage']['notes'] += [
        '1.2.0补充三方向、渡江纵队和后卫的逐日事件关联，仍缺完整湘军／中央军序列与逐单位部署，不提升完整度。',
        '27日脚山铺的红一师一个团未具名，30日凌晨才有一师主力赶到记述；不提前整师或造团号。',
        '11月两野战纵队分别清晨／黄昏渡江，与10月统计列映射未核；参考身份均不是等额步兵。',
        '约9400为能明确的部分减员，约51400为出发至战役后总体减员；不是整场阵亡配额。',
        '同日不同方向和未载内部时序不互相强排；各地方均无新增精确坐标，来源动作不自动变成本局任务。',
    ]
    hi.validate_definition(d)
    return d


def artifacts():
    d=build(); scenarios, registry, scenario=inputs()
    bindings_path=ROOT/'data/historical_objective_bindings.json'; bindings=json.loads(bindings_path.read_text())
    row=copy.deepcopy(bindings['profiles'][PROFILE]['1.1.0']);row['initial_definition_hash']=hi.digest(d)
    bindings['profiles'][PROFILE][VERSION]=row
    for event,key in zip(scenario['events'],CANONICAL_IDS):event['event_key']=key
    oct_group='出发前统计参考（1934年10月8日，非湘江部署）'
    old_oct=[r for r in scenario['forces'] if r.get('detail_group')==oct_group]
    scenario['forces']=[r for r in scenario['forces'] if r.get('detail_group') not in (GROUP,oct_group)]
    for u in d['units']:
        short=u['id'].removeprefix('lm.red.')
        if short not in UNIT_DETAILS:
            continue
        source=RED34 if short in {'regiment100','regiment101','regiment102'} else 'S29'
        scenario['forces'].append(dict(side='红军',unit=u['name'],description=UNIT_DETAILS[short][1]+' 无日期人数、装备及阵位保持未知。',detail_group=GROUP,
            sources=[source],evidence_status='published_account',source_locator={source:UNIT_DETAILS[short][0]}))
    scenario['forces'] += old_oct
    figures=[('能够明确的部分减员（研究介绍）',9400,'人（约）','湘江战役期间能考部分，不是全役阵亡'),
             ('出发至战役后总体减员（研究介绍）',51400,'人（约）','1934年10月出发至湘江战役后，非单次战斗阵亡'),
             ('红一军团损失（研究介绍）',6000,'余人','湘江战役期间该军团，非脚山铺单点')]
    metrics={r[0] for r in figures};oct_figures=[r for r in scenario['figures'] if 'XJ_OCT8_SH2026' in r['sources']]
    scenario['figures']=[r for r in scenario['figures'] if r['metric'] not in metrics and r not in oct_figures]
    for metric,number,qualifier,scope in figures:
        scenario['figures'].append(dict(side='红军',metric=metric,value=number,qualifier=qualifier,scope=scope,
            note='公开研究介绍，未阅原报告／档案；部分减员、总体减员、伤亡与阵亡不通约，不作为扣兵配额或开局人数。',sources=[PLA],
            evidence_status='published_account',source_locator={PLA:'第12版褚银文章损失研究段'}))
    scenario['figures'] += oct_figures
    for source in (RED34,PLA):
        item=d['sources'][source]
        registry['sources'][source]=dict(title=item['title'],publisher=item['publisher'],url=item['url'],
            evidence_type='公开回顾／研究参与者书评，非档案原页',supports='具名单位、任务与减员统计口径；不证明完整部署',accessed='2026-11-04',
            original_archive_examined=False,caveat=item['limitations'])
        if source not in scenario['sources']:scenario['sources'].append(source)
    note='1.2.0新增逐日单位地域关联及分时纵队，事件正文与原精度保留；可考部分与总体减员不能改作整场阵亡。'
    if note not in scenario['uncertainties']:scenario['uncertainties'].append(note)
    return {hi.DATA_ROOT/PROFILE/(VERSION+'.json'):d,bindings_path:bindings,
            ROOT/'data/long_march/scenarios.json':scenarios,ROOT/'data/long_march/sources.json':registry}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    stale=[]
    for path,value in artifacts().items():
        text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
        if args.check:
            if not path.exists() or path.read_text()!=text:stale.append(str(path.relative_to(ROOT)))
        elif not path.exists() or path.read_text()!=text:
            if path==hi.DATA_ROOT/PROFILE/(VERSION+'.json') and path.exists():
                raise ValueError('已发布初态不可覆盖，须另建版本：'+str(path))
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    for path,text in render_long_march.render().items():
        if args.check:
            if not path.exists() or path.read_bytes()!=text.encode():stale.append(str(path.relative_to(ROOT)))
        elif not path.exists() or path.read_bytes()!=text.encode():path.write_bytes(text.encode())
    if stale:raise SystemExit('Out of date: '+', '.join(stale))
    print('PASS Xiangjiang source process '+('checked' if args.check else 'published')+'; no invented executable window')


if __name__=='__main__':main()
