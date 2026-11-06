"""Add a source-pinned right-column transfer window; preserve published versions."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gentactix import historical_initial as hi, campaign_windows as cw

BATTLE = '红军长征-懋功会师与雪山草地转移-1935.06.12至1935.09.12'
PHASE = 'right_column_grassland'
WINDOW = 'LM06-right-column-aug21-27'


def evidence(source, locator):
    return [{'source_id':source, 'locator':locator}]


def build():
    value = hi.definition(BATTLE, '1.0.0')
    value['version'] = '1.1.0'
    value['coverage']['notes'] += [
        '1.1.0补充右路军四个军的行政来源、临时指挥参考和出发/抵达集体节点；不登记无法核定的师团下级、左路军同期部署或全方面军人数。',
        '8月27日抵达巴西是右路军集体记述，不是四军逐一到达的精确时刻。8月29日包座战斗在本窗口之外；不移用该网页有争议的后续战果。',
        '方面军与右路军为指挥参考，不生成步兵实体。已列四军不能代表右路军全部机关、红军大学及军委纵队人员。']
    ev = evidence('PLAN', '1935年8月3日夏洮计划，右路军组成及两方面军的行政来源')
    phases = {p['id']:p for p in value['phases']}
    phase = phases[PHASE]
    phase.update(label='右路军穿越草地至巴西', scope='只计算右路军四个军的非接敌转移；机关和其他部队不作虚构战斗实体。毛儿盖—巴西为来源方向，湿地可通行路线及逐军实到未知。')
    phase['date']['label'] = '1935年8月21日至27日'
    phase['execution_window'].update(end='1935-08-28T00:00', note='8月21—27日来源过程的计算范围；零时和末日边界为离散化估计，不是逐军出发/抵达钟点。开放模式按目标可延伸，不能据此补造包座敌军或战果。')
    armies = [u['id'] for u in value['units']]
    for u in value['units']:
        u['parent_id'] = 'mg.red.front1' if u['id'] in ('mg.red.army1','mg.red.army3') else 'mg.red.front4'
    for identity, name in [('mg.red.front1','红一方面军指挥参考'), ('mg.red.front4','红四方面军指挥参考'), ('mg.red.right_column','右路军临时指挥参考')]:
        value['units'].append(dict(id=identity, name=name, team='red', role='command', echelon='方面军' if 'front' in identity else '路军',
            parent_id=None, evidence=copy.deepcopy(ev),
            presence=[dict(phase_id=p['id'], status='campaign_participant', evidence=copy.deepcopy(ev)) for p in value['phases']],
            facts={k:dict(value=None, evidence=copy.deepcopy(ev), scope='仅指挥层级参考，人数、装备、机关所在地未核定；不转换为战斗部队。') for k in ('personnel','equipment','position')},
            children_coverage=dict(status='partial', scope='仅列本窗口可核身份，不表示完整方面军或右路军的下级覆盖。', evidence=copy.deepcopy(ev))))
    phase['relations'] = [dict(id='LM06-right-command-'+str(n+1), kind='operational_command', parent_id='mg.red.right_column',
        child_id=identity, scope='夏洮计划的临时右路军指挥，不改变两方面军行政隶属；不自动创建本局任务群或命令。', evidence=copy.deepcopy(ev)) for n,identity in enumerate(armies)]
    phases['campaign_reference']['operations'] = [dict(id='LM06-Aug3-right-plan', kind='command', date=dict(label='1935-08-03',precision='day'),
        unit_ids=armies+['mg.red.right_column'], places=[], description='夏洮计划规定右路军由两方面军所列四个军等组成，向北经草地行动。',
        evidence=copy.deepcopy(ev), limitations='计划编组不能证明当日各军全部到场；机关、大学和纵队未量化，不拆出虚构师团。')]
    def movement(identity, date, places, description, locator):
        refs=evidence('CROSS',locator)
        return dict(id=identity, kind='movement', date=dict(label=date,precision='day'), unit_ids=armies+['mg.red.right_column'],
            places=[dict(name=p,position=None,evidence=copy.deepcopy(refs)) for p in places], description=description, evidence=refs,
            limitations='集体方向与日级节点；不证明各军同时过同一点、逐时行军路线或具体损失。位置、人数和库存仍须独立估计。')
    phase['operations'] = [
        movement('LM06-Aug21-depart','1935-08-21',['毛儿盖','草地'],'右路军从毛儿盖方向出发进入草地。','8月21日自毛儿盖出发进入草地段'),
        movement('LM06-Aug27-baxi','1935-08-27',['草地','巴西'],'右路军走出草地到达巴西方向，等待左路军。','8月27日走出草地到达巴西段；不采用次段包座战果')]
    hi.validate_definition(value)
    return value


def window(source):
    phase = next(p for p in source['phases'] if p['id']==PHASE)
    operations = [o['id'] for o in phase['operations']]
    armies = [u['id'] for u in source['units'] if u['role']=='formation']
    value = dict(format=cw.FORMAT, id=WINDOW, version='1.0.0', label='长征右路军：8月21—27日四军草地转移', battle=BATTLE,
        historical_initial=dict(profile_id=source['id'],version=source['version'],definition_hash=hi.digest(source)),
        start_phase_id=PHASE, phase_ids=[PHASE],
        bounds={k:copy.deepcopy(phase['execution_window'][k]) for k in ('start','end','kind','note')},
        units={}, sectors=[dict(id='right-column-route',label='毛儿盖—草地—巴西方向参考',position=None,unit_ids=armies,
            operation_ids=operations,evidence=copy.deepcopy(phase['evidence']))],
        milestones=[dict(operation_id=o,phase_id=PHASE,policy='reference_only') for o in operations],
        limitations='仅四军转移计算窗口，非整个长征或完整右路军编制；不生成蓝方敌军。人数、装备、出发位置、路线、实到时点、补给与保存阈值均未逐军标定，须显式估计。历史节点是资料参考，开放推演不强迫按日期移动；回溯资料亦不把估计路线冒称史实。')
    for u in source['units']:
        actor=u['id'] in armies
        value['units'][u['id']]=dict(representation='actor' if actor else 'command_reference',represented_by=None,
            presence_basis='window_reference' if actor else 'not_applicable',
            extent='只计算该军所声明投入载荷；未核下级与余部，不能宣称完整军实力。' if actor else '指挥参考，不投入人员、库存或单独步兵实体。',
            opening='requires_explicit_estimate',operation_ids=operations if actor or u['id']=='mg.red.right_column' else [],
            operational_reference=next((r['id'] for r in phase['relations'] if r['child_id']==u['id']),None),evidence=copy.deepcopy(u['evidence']))
    return value


def objective_binding(source):
    """Pin this new window's endpoint, without revising earlier version pins."""
    path=ROOT/'data/historical_objective_bindings.json'
    row=copy.deepcopy(json.loads(path.read_text())['profiles'][source['id']]['1.0.0'])
    row['initial_definition_hash']=hi.digest(source)
    item=row['phases'][PHASE];guide=item['guidance']
    guide['objective_label']='右路军穿越草地至巴西转移目标'
    guide['scope_note']='8月21日毛儿盖出发至8月27日抵达巴西的集体转移节点；不是四军逐一实到或钟点记录。人数、装备、路线、保障与完成阈值须另作显式估计。'
    guide['evidence']=evidence('CROSS','8月21日自毛儿盖出发、8月27日抵达巴西段；不采用后段包座战果')
    item['source_hashes']={e['source_id']:hi.digest(source['sources'][e['source_id']]) for e in guide['evidence']}
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    source=build();value=window(source)
    cw.validate_definition(value,hi._materialize(source,PHASE)['historical_initial'])
    for path,item in {hi.DATA_ROOT/'LM06-maogong/1.1.0.json':source,cw.DATA_ROOT/WINDOW/'1.0.0.json':value}.items():
        if path.exists():
            if json.loads(path.read_text())!=item:raise SystemExit('Published version differs; create a new version: '+str(path))
        elif args.check:raise SystemExit('Missing version: '+str(path))
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n')
    path=ROOT/'data/historical_objective_bindings.json';bindings=json.loads(path.read_text())
    wanted=objective_binding(source);actual=bindings['profiles'][source['id']].get(source['version'])
    if args.check:
        if actual!=wanted:raise SystemExit('New source objective guidance differs: '+source['id']+'/'+source['version'])
    elif actual is None:
        bindings['profiles'][source['id']][source['version']]=wanted
        path.write_text(json.dumps(bindings,ensure_ascii=False,indent=2)+'\n')
    elif actual!=wanted:
        raise SystemExit('Existing pin differs; review explicitly instead of overwriting: '+source['id']+'/'+source['version'])
    print('LM06 right-column source and window match; old versions and defaults unchanged')


if __name__=='__main__':main()
