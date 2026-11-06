"""Explicit user numerical inputs for scenario drafts, never a live executor."""
import copy
import math

VERSION = 'fixed-scenario-input-1'
MAX_FIXED_INPUTS = 8192
ROOTS = {'area', 'actors', 'rules', 'support', 'goal', 'facility', 'aviation',
         'support_dynamics', 'supply_distribution', 'supply_schedule', 'campaign', 'terrain_model'}
LABELS = {
    'area':'战区', 'rules':'作战规则', 'support':'保障库存', 'goal':'战役目标', 'facility':'渡运设施',
    'aviation':'航空', 'initial':'初始资源','entry':'入场点','committed':'投入飞机（架）',
    'ordnance':'航空弹药工作量','fuel':'航空燃油工作量',
    'support_dynamics':'按时耗粮', 'supply_distribution':'粮弹分类',
    'supply_schedule':'定时补给', 'campaign':'会战过程', 'terrain_model':'地形',
    'center':'中心', 'position':'部署', 'objective':'目标点', 'exit':'退出点', 'equipment':'装备',
    'logistics':'随队库存', 'formation':'编组状态', 'warehouse_tons_per_hour':'仓库装卸能力',
    'cargo_mass_tons':'分类物资质量（模型吨/单位）',
    'red':'红方', 'blue':'蓝方', 'red-historical-supply':'红方仓库', 'blue-historical-supply':'蓝方仓库',
    'lat':'纬度', 'lng':'经度', 'personnel':'人员数量', 'radius_km':'半径（公里）', 'terrain_factor':'地形系数',
    'armor':'装甲车辆', 'artillery':'火炮', 'air_defense':'防空火器', 'engineer':'工兵作业组', 'transport':'运输单元',
    'speed':'速度（公里/小时）', 'attack_range_m':'攻击距离（米）', 'ground_control_radius_km':'地控半径（公里）',
    'food':'粮食工作量', 'ammo':'弹药工作量', 'stock':'归一库存', 'hp':'兵力状态', 'morale':'士气',
    'fatigue':'疲劳', 'suppression':'压制', 'entrenchment':'工事', 'signal':'通信',
    'intel_confidence':'情报置信度', 'intel_age_min':'情报时龄（分钟）', 'dispersion_km2':'展开面积（平方公里）',
    'protection':'防护', 'shells':'炮弹', 'aa_rounds':'防空弹药', 'fuel_liters':'燃油（升）', 'spares':'备件', 'materials':'工程材料',
    'deadline_turn':'参考截止轮数', 'required_turns':'持续轮数', 'required_survivors':'存续编组门槛',
    'convoy_km_per_turn':'补给周转距离（公里/轮）',
    'period_seconds':'配送周期（秒）', 'passive_work_per_hour':'普通保障（工作量/小时）',
    'resupply_work_per_hour':'主动补给（工作量/小时）', 'convoy_speed_kph':'运输周转速度（公里/小时）',
    'loading_hours':'装卸时间（小时）', 'food_work_per_hour':'待命耗粮（工作量/小时）', 'move_factor':'机动耗粮倍数',
    'ration_kg_per_person_day':'每人每日粮食（kg）','food_kg_per_work':'粮食质量（kg/工作量）',
    'carried_kg_per_committed_person':'按投入人数登记的携行容量（kg/人）',
    'shortage_fatigue_per_hour':'缺粮疲劳系数', 'recovery_hours_per_fed_hour':'供粮恢复系数',
    'incapacity_after_hours':'失能起算时长（小时）', 'incapacity_fraction_per_hour':'小时失能比例',
    'food_mass_share':'粮食货重占比', 'food_priority':'粮食优先系数', 'ammo_priority':'弹药优先系数',
}
NUMERIC_NULLS = set(LABELS) - ROOTS - {'center','position','objective','exit','equipment','logistics','formation',
    'warehouse_tons_per_hour','cargo_mass_tons','red','blue','red-historical-supply','blue-historical-supply'}
FORMATION_INTEGERS = {'fatigue','suppression','entrenchment','signal','shells','aa_rounds',
                      'fuel_liters','spares','materials','reload_remaining'}


def _integer(path):
    """Use domain meaning, never the spelling of the current numerical prior."""
    root=path[0]
    if root=='rules':
        from . import combined_arms
        return len(path)==2 and (path[-1]=='required_survivors' or type(combined_arms.RULES.get(path[-1])) is int)
    if root=='actors':
        return (len(path)==3 and path[-1]=='personnel' or len(path)==4 and
                (path[2]=='equipment' or path[2]=='formation' and path[-1] in FORMATION_INTEGERS))
    if root=='support':return len(path)==4 and path[2]=='inventory'
    if root=='goal':return path[-1] in {'deadline_turn','required_turns','required_survivors'}
    if root=='supply_schedule':return path[-1]=='period_seconds'
    if root=='aviation':return path[-1] in {'committed','ordnance','fuel','package','fuel_per_aircraft',
                                           'personnel_per_effective_aircraft','equipment_per_effective_aircraft'}
    return False


class FixedParameterConflict(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('已固定参数冲突：' + '；'.join('.'.join(r['path']) +
            f' 需要{r["expected"]}，收到{r["actual"]}' for r in conflicts[:8]))


def fields(template, actors=()):
    """Catalogue numeric mapping leaves only; list structure/identities are excluded."""
    index = {u['id']:u for u in actors}
    result = []
    def walk(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key,str):walk(child,path+[key])
        elif type(value) in (int,float) or value is None and (path[-1] in NUMERIC_NULLS or
                len(path)==4 and path[0]=='aviation' and path[2]=='initial' and path[-1] in {'committed','ordnance','fuel'} or
                path[:2]==['supply_schedule','warehouse_tons_per_hour']):
            if path[0]=='actors':
                actor=index.get(path[1],{})
                group=(LABELS.get(actor.get('team'),'单位')+' · '+actor.get('name',path[1]))
                names=path[2:]
            else:group=LABELS.get(path[0],path[0]);names=path[1:]
            result.append({'path':path,'group':group,'label':group+' · '+' · '.join(LABELS.get(k,k) for k in names),
                'value':value,'integer':_integer(path),'required_models':[]})
    for key in template:
        if key in ROOTS:walk(template[key],[key])
    return result


def _rows(values):
    if not isinstance(values,list) or len(values)>MAX_FIXED_INPUTS:raise ValueError(f'固定参数必须为最多{MAX_FIXED_INPUTS}项的数值列表')
    result=[];seen=set()
    for row in values:
        if not isinstance(row,dict) or set(row)!={'path','value'}:raise ValueError('固定参数只填写path和value')
        path=row['path'];number=row['value']
        if (not isinstance(path,list) or not 2<=len(path)<=12 or
                any(not isinstance(k,str) or not k or len(k)>160 for k in path)):
            raise ValueError('固定参数路径不合法')
        if tuple(path) in seen:raise ValueError('固定参数路径重复')
        if type(number) not in (int,float) or abs(number)>1e15 or not math.isfinite(number):
            raise ValueError('固定参数必须为有限数值，不能是布尔值或文本')
        seen.add(tuple(path));result.append({'path':list(path),'value':number})
    return result


def prepare(basis, values):
    """Seed declared constraints BEFORE model work, atomically; never repair output."""
    rows=_rows(values)
    available={tuple(r['path']):r for r in fields(basis['configuration_template'],basis.get('actors',[]))}
    template=copy.deepcopy(basis['configuration_template'])
    for row in rows:
        path=row['path'];field=available.get(tuple(path))
        if field is None:raise ValueError('固定参数字段不属于当前数值模板；需先启用相关模型：'+'.'.join(path))
        if field['integer'] and row['value']!=int(row['value']):raise ValueError('固定参数须为整数：'+field['label'])
        if field['integer']:row['value']=int(row['value'])  # Normalize user input before model work, never its output.
        node=template
        for key in path[:-1]:node=node[key]
        node[path[-1]]=row['value']
    # Only commit after the whole supplied list has been checked.
    basis['configuration_template']=template
    basis['fixed_parameters']={'version':VERSION,'values':copy.deepcopy(rows)}


def validate(configuration, contract):
    if not contract:return
    if not isinstance(contract,dict) or set(contract)!={'version','values'} or contract['version']!=VERSION:
        raise ValueError('固定参数契约版本或字段非法')
    rows=_rows(contract['values']);conflicts=[]
    for row in rows:
        node=configuration
        try:
            for key in row['path']:node=node[key]
        except (KeyError,TypeError):node='missing'
        if type(node) not in (int,float) or node!=row['value']:
            conflicts.append({'path':copy.deepcopy(row['path']),'expected':row['value'],'actual':node})
    if conflicts:raise FixedParameterConflict(conflicts)


def view(contract, actor_ids=(), *, final=False):
    if not contract:return {'version':VERSION,'values':[],'total':0}
    rows=contract['values']
    visible=[r for r in rows if r['path'][0]!='actors' or not final and r['path'][1] in actor_ids]
    return {'version':VERSION,'values':copy.deepcopy(visible),'total':len(rows),
            'instruction':'这些值由用户明确固定，属于建模输入，不是史实断言；不能改写。冲突须报告，不要静默换值。'}
