"""Explicit, uncalibrated window priors; never historical facts or an executor."""
import copy
import math
from . import historical_initial as hi, missions

VERSION='campaign-estimates-1'
CATEGORIES={'armor','artillery','air_defense','engineer','transport'}


def _text(value):return isinstance(value,str) and bool(value.strip())


def _fields(value,keys,label):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError('会战估计'+label+'字段非法')


def _number(value,lo,high,label,integer=False):
    if (type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not lo<=value<=high):
        raise ValueError('会战估计'+label+'超出声明范围')


def _point(value):
    _fields(value,{'lat','lng'},'坐标')
    _number(value['lat'],-90,90,'纬度');_number(value['lng'],-180,180,'经度')


def _range(value,label):
    _fields(value,{'minimum','maximum'},label)
    _number(value['minimum'],0,100000000,label,True)
    _number(value['maximum'],value['minimum'],100000000,label,True)


def validate_definition(cfg,window,snapshot,identities):
    _fields(cfg,{'version','historically_calibrated','assumption','area','actors','goal_template'}
            |{key for key in ('global_priors','goal_regions')if isinstance(cfg,dict)and key in cfg},'契约')
    if cfg['version']!=VERSION or cfg['historically_calibrated'] is not False or not _text(cfg['assumption']):
        raise ValueError('会战估计须明确未经历史标定的先验及其局限')
    area=cfg['area'];_fields(area,{'center','radius_km','assumption','evidence'},'工作区域')
    _point(area['center']);_number(area['radius_km'],1,2000,'工作区域半径')
    if not _text(area['assumption']):raise ValueError('会战估计区域须区别地名参考与部署')
    hi._evidence(area['evidence'],snapshot['definition']['sources'])
    if not isinstance(cfg['actors'],dict) or set(cfg['actors'])!=set(identities):
        raise ValueError('会战估计须覆盖本窗口全部候选身份')
    for identity,row in cfg['actors'].items():
        _fields(row,{'personnel','equipment','position','role','direct_range_m','assumption'}
                |({'input_prior'} if isinstance(row,dict) and 'input_prior' in row else set()),'单位')
        _range(row['personnel'],'人员');_range(row['direct_range_m'],'自卫直射范围')
        if row['personnel']['minimum']<1 or row['direct_range_m']['maximum']>3000:
            raise ValueError('会战估计须保留正人员与明确的直射上界，不混用远程火炮射程')
        if row['role'] not in ('infantry','support') or not _text(row['assumption']):raise ValueError('会战估计缺少兵种与范围说明')
        _fields(row['equipment'],CATEGORIES,'分类装备')
        for key,value in row['equipment'].items():_range(value,key)
        p=row['position'];_fields(p,{'center','radius_km','assumption'},'初始位置范围');_point(p['center'])
        _number(p['radius_km'],.1,200,'初始位置不确定范围')
        if not _text(p['assumption']) or missions.distance(p['center'],area['center'])+p['radius_km']>area['radius_km']:
            raise ValueError('会战估计初始位置范围超出声明工作区或没有精度说明')
        if 'input_prior' in row:
            from . import historical_operations
            _fields(row['input_prior'],historical_operations.ACTOR_FIELDS,'单位输入基线')
    if any('input_prior' in r for r in cfg['actors'].values()) and not all('input_prior' in r for r in cfg['actors'].values()):
        raise ValueError('会战估计单位输入基线须完整覆盖所选候选，不能隐式混入未填写单位')
    graph=cfg['goal_template'];_fields(graph,{'version','nodes','outcomes','elimination_ends','assumption'},'目标模板')
    from . import campaign_plan
    if graph['version']!=campaign_plan.VERSION or not isinstance(graph['nodes'],list) or not 1<=len(graph['nodes'])<=64:
        raise ValueError('会战估计目标模板非法')
    index={u['id']:u for u in snapshot['definition']['units']}
    operations={o['id'] for p in snapshot['definition']['phases'] for o in p.get('operations',[])}
    seen=set()
    for node in graph['nodes']:
        _fields(node,campaign_plan.NODE_FIELDS,'目标节点模板')
        if (not _text(node['id']) or node['id'] in seen or node['team'] not in ('red','blue')
                or not isinstance(node['unit_ids'],list) or not node['unit_ids']
                or len(set(node['unit_ids']))!=len(node['unit_ids'])
                or any(i not in identities or index[i]['team']!=node['team'] for i in node['unit_ids'])
                or any(i not in operations for i in node['operation_ids']) or not _text(node['assumption'])):
            raise ValueError('会战估计目标引用身份、阵营或来源非法')
        seen.add(node['id'])
    campaign_plan.validate_defensive_bindings(graph['nodes'])
    if {n['team'] for n in graph['nodes']}!={'red','blue'}:
        raise ValueError('会战估计须声明双方目标，不只给一方占点')
    if 'goal_regions' in cfg:
        regions=cfg['goal_regions'];regional={n['id']for n in graph['nodes']if 'region'in n['condition']}
        if not isinstance(regions,dict)or not regions or set(regions)-regional:
            raise ValueError('目标地域估计只能约束已登记的地域目标节点')
        for identity,row in regions.items():
            _fields(row,{'center','radius_km','assumption'},'目标地域估计：'+identity)
            _point(row['center']);_number(row['radius_km'],.1,200,'目标地域估计半径')
            if not _text(row['assumption'])or missions.distance(row['center'],area['center'])+row['radius_km']>area['radius_km']+.001:
                raise ValueError('目标地域估计超出声明工作区或缺少估计精度说明：'+identity)
    if 'global_priors' in cfg:
        priors=cfg['global_priors']
        _fields(priors,{'clock','area','rules','support','facility','goal','assumptions',
            'campaign_scope','campaign','support_dynamics','supply_distribution','campaign_plan'}
            |{key for key in ('movement_feedback','fire_accounting','fire_dynamics') if key in priors},'公共参数基线')
        if 'movement_feedback' in priors:
            from . import movement_feedback
            movement_feedback.validate_config(priors['movement_feedback'])
        if 'fire_accounting' in priors:
            from . import combat_effects
            combat_effects.validate_accounting(priors['fire_accounting'])
        if 'fire_dynamics' in priors:
            from . import combat_effects
            combat_effects.validate_dynamics(priors['fire_dynamics'])
        scope=priors['campaign_scope']
        if (not isinstance(scope,dict) or 'window' in scope or priors.get('actors') is not None
                or scope.get('planning_end')!=window['bounds']['end']
                or priors.get('clock',{}).get('start')!=window['bounds']['start']):
            raise ValueError('会战估计公共基线不能复制窗口快照、单位状态或改写时窗')
    return cfg


def configuration(window):
    return window['definition'].get('parameter_estimates') if window else None


def goal_members(params,identities):
    groups=(params.get('partitions') or {}).get('groups',{})
    return [identity+'::'+part['id'] if part else identity for identity in identities
            for part in (groups[identity]['parts'] if identity in groups else [None])]


def prepare(result,window,termination_mode):
    cfg=configuration(window)
    if not cfg:return
    from . import support_dynamics
    result['support_dynamics']={'version':support_dynamics.VERSION,**{k:None for k in support_dynamics.LIMITS},
        'assumption':'待声明按时间耗粮与缺粮后果的计算先验；不是按人数或重量标定的口粮。'}
    if 'global_priors' in cfg:
        for key,value in cfg['global_priors'].items():
            if key=='campaign_scope':result[key].update(copy.deepcopy(value))
            else:result[key]=copy.deepcopy(value)
        mode=termination_mode or result['goal'].get('termination_mode','objectives')
        if mode!='objectives':result.pop('campaign_plan',None)
        result['goal']['termination_mode']=mode
        for identity,prior in cfg['actors'].items():
            if 'input_prior' in prior:result['actors'][identity]=copy.deepcopy(prior['input_prior'])
        return
    if termination_mode=='objectives':result['campaign_plan']=copy.deepcopy(cfg['goal_template'])


def validate_parameters(snapshot,params,actor_ids=None):
    window=(params.get('campaign_scope') or {}).get('window')
    cfg=configuration(window)
    if not cfg:return
    if 'movement_feedback' in cfg.get('global_priors',{}):
        from . import movement_feedback
        movement_feedback.validate_config(params.get('movement_feedback'))
    if not params.get('support_dynamics') or not params.get('supply_distribution'):
        raise ValueError('会战估计窗口须显式填写按时间保障及分类粮弹，不能回退每回合补给包')
    area=params['area'];_point(area['center'])
    _number(area['radius_km'],.1,cfg['area']['radius_km'],'战区半径')
    if missions.distance(area['center'],cfg['area']['center'])+area['radius_km']>cfg['area']['radius_km']+.001:
        raise ValueError('会战估计工作区超出所选窗口，不能把局部场景放到其他地点')
    for identity in (list(params['actors']) if actor_ids is None else actor_ids):
        actor=params['actors'][identity];prior=cfg['actors'][identity]
        for label,value,bound in [('人员',actor['personnel'],prior['personnel']),
            ('直射范围',actor['attack_range_m'],prior['direct_range_m'])]:
            _number(value,bound['minimum'],bound['maximum'],identity+label,label=='人员')
        for key,bound in prior['equipment'].items():
            _number(actor['equipment'][key],bound['minimum'],bound['maximum'],identity+key,True)
        _point(actor['position'])
        if missions.distance(actor['position'],prior['position']['center'])>prior['position']['radius_km']:
            raise ValueError('会战估计初始部署超出本单位声明范围：'+identity)
        for part in (params.get('partitions') or {}).get('groups',{}).get(identity,{}).get('parts',[]):
            if missions.distance(part['position'],prior['position']['center'])>prior['position']['radius_km']:
                raise ValueError('会战估计计算分队初始部署超出其父级声明范围：'+identity)
        if actor['formation']['role']!=prior['role']:
            raise ValueError('会战估计兵种角色不符：'+identity)
    if params.get('goal',{}).get('termination_mode')=='objectives':
        actual=params.get('campaign_plan');wanted=cfg['goal_template']
        if not isinstance(actual,dict) or actual.get('outcomes')!=wanted['outcomes']:
            raise ValueError('会战估计目标完成制须保留双方目标图')
        nodes=actual.get('nodes')
        if not isinstance(nodes,list) or {n.get('id') for n in nodes}!={n['id'] for n in wanted['nodes']}:
            raise ValueError('会战估计目标图方向缺失或被替换')
        index={n['id']:n for n in nodes}
        for prior in wanted['nodes']:
            node=index[prior['id']]
            if (any(node.get(k)!=prior[k] for k in ('team','after','operation_ids','latch'))
                    or node.get('unit_ids')!=goal_members(params,prior['unit_ids'])
                    or node.get('condition',{}).get('kind')!=prior['condition']['kind']
                    or node.get('condition',{}).get('against_node')!=prior['condition'].get('against_node')):
                raise ValueError('会战估计目标承担者、依赖或来源被改写：'+prior['id'])
            bounds=cfg.get('goal_regions',{}).get(prior['id'])
            if bounds:
                region=node['condition']['region'];_point(region['center'])
                _number(region['radius_km'],.01,200,'目标地域半径：'+prior['id'])
                if missions.distance(region['center'],bounds['center'])+region['radius_km']>bounds['radius_km']+.001:
                    raise ValueError('目标地域超出本方向声明的估计范围：'+prior['id']+
                        '；目标中心及整个半径须位于该节点goal_regions内，不能仅满足全战区包络。')
        from . import campaign_plan
        campaign_plan.validate_inputs(snapshot,params)
