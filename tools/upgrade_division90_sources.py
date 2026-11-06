"""Bind page-reviewed partial actions to new source/window versions only."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,campaign_windows as cw
from tools.upgrade_northern_campaign import WJL,WH

SOURCE='WU1940_90'
DIV90='ww2.cn.division90';DIV58='ww2.cn.division58'
URL='https://commons.wikimedia.org/wiki/File:NLC416-11jh001474-29114_薛伯陵將軍指揮之德安萬家嶺大捷回憶.pdf'
LIMIT=('吴逸志1940年同期编述的单一来源；不是亲阅作战命令簿或馆方认证原始字节。'
       '只关联所述局部部队，未核完整番号、实到人数、装备、库存和配准坐标。'
       '来源时刻不是本局强制执行时刻；占领结果不自动写入开放推演。')


def evidence(page):
    return [dict(source_id=SOURCE,locator=f'印本{page}页（PDF{int(page)+29}页）；第4军第90师战斗经过，逐页视读')]


def source():
    return dict(title='吴逸志编述：《薛伯陵將軍指揮之德安萬家嶺大捷回憶》（1940年11月）',url=URL,
                publisher='中兴书店；国家图书馆扫描的公开镜像',evidence_kind='published_memoir',
                original_archive_examined=False,
                limitations='已视读封面、印本37—39页及相邻页；PDF为无文本层扫描，目录月份不作战事日期。'
                +LIMIT+' 10月下旬德安老虎山详报属于另一窗口，不据近似地名混入本批事件。')


def events(prefix):
    def event(suffix,kind,date,precision,places,description,page,*,supported=False):
        e=evidence(page)
        scopes={DIV90:dict(extent='elements',scope='第90师章节所记的团、营或一部；全番号和规模未齐，不代表全师同步行动。',evidence=copy.deepcopy(e))}
        if supported:
            scopes[DIV58]=dict(extent='reference',scope='被支援的邻接第58师方向，仅作任务对象关联；本句没有列出全师投入或全师接防。',evidence=copy.deepcopy(e))
        return dict(id=f'{prefix}-WU1940-{suffix}',kind=kind,date=dict(label=date,precision=precision),
                    unit_ids=list(scopes),unit_scopes=scopes,
                    places=[dict(name=name,position=None,evidence=copy.deepcopy(e))for name in places],
                    description=description,evidence=e,limitations=LIMIT)
    return [
        event('Oct1-order','command','1938-10-01，05时','hour',['肉身观','狮子崖'],
              '第90师章节记抽调张团及吴团杨营分别承担正面与侧击任务；这是局部分队的调令，不是整师重新部署。','38'),
        event('Oct1-attack','attack','1938-10-01，06时开始','hour',['肉身观','狮子崖'],
              '上述局部攻击于06时开始；调令与实际攻击时点分别登记，不把05时视为已经攻占。','38'),
        event('Oct1-control','combat','1938-10-01，17时','hour',['肉身观','狮子崖'],
              '来源报告17时取得肉身观、狮子崖一带阵地；未给配准范围，不等同全战场控制或永久占领。','38'),
        event('Oct3-attack','attack','1938-10-03，08时','hour',['大金山','面前山','杨家坂'],
              '章团一部由大金山方向攻击；姓氏团称呼保留原文，不与张团自动合并或猜成完整番号。','38'),
        event('Oct3-control','combat','1938-10-03，15时','hour',['杨家坂','万家岭北端高地'],
              '来源报告下午取得杨家坂及万家岭北端高地；只记本次结果，后续控制权仍可变化。','39'),
        event('Oct4-attack','combat','1938-10-04，07时起','hour',['杨家坂东端高地'],
              '敌方向杨家坂东端高地继续攻击，第90师章团相关部队抵抗；没有从敌情叙述反推参战总数。','39'),
        event('Oct4-reinforcement','combat','1938-10-04，13时','hour',['杨家坂东端高地'],
              '来源记敌方投入增援后继续攻击；所记增援身份与规模未逐队核定，不物化为新部队或自动补兵。','39'),
        event('Oct4-control','combat','1938-10-04，16时','hour',['杨家坂东端高地','万家岭北端高地'],
              '相关高地在本方部队伤亡增大后失守；不将前日占领当作永恒控制，不补造伤亡人数。','39'),
        event('Oct6-defense','defense','1938-10-06，04时至19时','period',['狮子崖'],
              '来源记当地持续阻击并击退攻击；此区间与当日其他指挥动作可重叠，不拆成虚构逐小时战果。','39'),
        event('Oct6-support','relief','1938-10-06，20时','hour',['第58师方向'],
              '敌方转向邻接第58师方向后，张团黄营参与支援；不是整个第90师改隶、集体移动或额外增兵。','39',supported=True),
    ]


def documentary_phase(identity,label,date,operations):
    e=evidence('38')+evidence('39')
    return dict(id=identity,label=label,date=dict(label=date,precision='day',evidence=copy.deepcopy(e)),
                scope='单份同期编述的局部分队过程；上级关联不证明整师到场、完整序列或可计算部署。',
                evidence=e,operations=copy.deepcopy(operations),relations=[])


def build_wanjialing():
    d=hi.definition(WJL,'1.5.0');d['version']='1.6.0';d['sources'][SOURCE]=source();d['event_order']='dated-events-1'
    ops=events('WJL');added=[]
    for phase_id,day in [('oct1_div90_local','Oct1'),('oct3_div90_local','Oct3'),('oct4_div90_local','Oct4')]:
        day_number={'Oct1':'01','Oct3':'03','Oct4':'04'}[day]
        added.append(documentary_phase(phase_id,f'10月{int(day_number)}日第90师局部任务（同期编述）',
                                      f'1938-10-{day_number}',[o for o in ops if f'-{day}-'in o['id']]))
    by_id={p['id']:p for p in added};ordered=[]
    for p in d['phases']:
        if p['id']=='oct2_encirclement':ordered.append(by_id['oct1_div90_local'])
        if p['id']=='oct6_orders':ordered.extend([by_id['oct3_div90_local'],by_id['oct4_div90_local']])
        if p['id']=='oct6_orders':
            p['operations'].insert(0,copy.deepcopy(next(o for o in ops if o['id'].endswith('Oct6-defense'))))
            p['operations'].append(copy.deepcopy(next(o for o in ops if o['id'].endswith('Oct6-support'))))
        ordered.append(p)
    d['phases']=ordered
    for u in d['units']:
        for p in added:
            u['presence'].append(dict(phase_id=p['id'],status='unverified',evidence=copy.deepcopy(p['evidence'])))
    d['coverage']['notes'].append('1.6.0接入同期编述10条局部分队事件和逐单位投入范围；未知整师到场、兵额装备及坐标不升级，旧版与默认不变。')
    hi.validate_definition(d);return d


def build_wuhan():
    d=hi.definition(WH,'1.2.0');d['version']='1.3.0';d['sources'][SOURCE]=source();d['event_order']='dated-events-1'
    p=documentary_phase('oct1_6_div90_local','南线第90师10月1—6日局部行动（同期编述）','1938-10-01至1938-10-06',events('WH'))
    p['date']['precision']='range'
    p['scope']+=' 只补南线来源片段，不代表整个武汉会战；不改变现有北线窗口的部署或估计。'
    d['phases'].append(p)
    for u in d['units']:u['presence'].append(dict(phase_id=p['id'],status='unverified',evidence=copy.deepcopy(p['evidence'])))
    d['coverage']['notes'].append('1.3.0增加有页码的南线局部任务及部分投入提示；不同日期与方向不合并成同一开局，不补造新番号或数值。')
    hi.validate_definition(d);return d


def build_wanjialing_window(definition):
    d=copy.deepcopy(cw.load('WJL-oct6-10','1.6.0'));d['version']='1.7.0'
    d['label']='万家岭：10月6—10日地面会战 · 局部分队来源范围'
    d['historical_initial']=dict(profile_id=definition['id'],version=definition['version'],definition_hash=hi.digest(definition))
    for op in events('WJL'):
        if '-Oct6-'not in op['id']:continue
        d['milestones'].append(dict(operation_id=op['id'],phase_id='oct6_orders',policy='reference_only'))
        for identity in op['unit_ids']:
            row=d['units'][identity];row['operation_ids'].append(op['id'])
            row['evidence']+=copy.deepcopy(op['evidence']);row['presence_basis']='reported_action'
    d['units'][DIV90]['extent']+=' 10月6日新增来源只涉及局部阻击与张团黄营支援，不能作为整师同步行动的证明。'
    d['units'][DIV58]['extent']+=' 新增支援记录中的第58师只是所援方向关联，不证明全师接防。'
    d['limitations']+=' 1.7.0仅更新来源绑定与局部事件范围；原估计、目标和物理规则保持；不强制历史结果或移动全师。'
    cw.validate_definition(d,hi._materialize(definition,'oct6_orders')['historical_initial']);return d


def build_wuhan_window(definition):
    d=copy.deepcopy(cw.load('WH-northern-sep17-18','1.2.0'));d['version']='1.3.0'
    d['historical_initial']=dict(profile_id=definition['id'],version=definition['version'],definition_hash=hi.digest(definition))
    d['label']+=' · 南北来源分窗'
    d['limitations']+=' 1.3.0只绑定增补南线来源的档案，北线执行名单、数值、目标及任务范围均不改变；不将10月南线片段加入9月北线初态。'
    cw.validate_definition(d,hi._materialize(definition,d['start_phase_id'])['historical_initial']);return d


def outputs():
    a,b=build_wanjialing(),build_wuhan()
    values={hi.DATA_ROOT/'AJ07-wanjialing/1.6.0.json':a,hi.DATA_ROOT/'AJ06-wuhan/1.3.0.json':b,
            cw.DATA_ROOT/'WJL-oct6-10/1.7.0.json':build_wanjialing_window(a),
            cw.DATA_ROOT/'WH-northern-sep17-18/1.3.0.json':build_wuhan_window(b)}
    path=ROOT/'data/historical_objective_bindings.json';pins=json.loads(path.read_text())
    for d,base in [(a,'1.5.0'),(b,'1.2.0')]:
        versions=pins['profiles'][d['id']];binding=copy.deepcopy(versions[base]);binding['initial_definition_hash']=hi.digest(d)
        for row in binding['phases'].values():
            if 'guidance'in row:row['source_hashes']={i:hi.digest(d['sources'][i])for i in row['source_hashes']}
        if d['version']in versions and versions[d['version']]!=binding:raise ValueError('Existing objective pin differs; do not overwrite')
        versions[d['version']]=binding
    values[path]=pins;return values


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    for path,value in outputs().items():
        if path.exists()and json.loads(path.read_text())==value:continue
        if args.check:raise SystemExit('Source output differs or missing: '+str(path))
        if path.exists()and path.name!='historical_objective_bindings.json':raise SystemExit('Do not overwrite an existing source version: '+str(path))
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print('Division90 partial actions and version-bound Wanjialing/Wuhan windows match; defaults/old versions/numeric estimates unchanged')


if __name__=='__main__':main()
