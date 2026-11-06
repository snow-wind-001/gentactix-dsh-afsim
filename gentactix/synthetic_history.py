"""Frozen historical initial inputs -> editable synthetic inputs; no transitions."""
import copy
from . import combined_arms, historical_operations, missions

FORMAT='historical-synthetic-1'
CAMPAIGN_REVISION='synthetic-campaign-1'


def _base(binding):
    return historical_operations.from_binding(binding)


def reference(binding):
    base=_base(binding);snapshot=binding['initial'];index={u['id']:u for u in snapshot['definition']['units']}
    rows=[]
    for team,unit in missions.units(base['initial_state']):
        fact=index[unit['historical_unit_id']]
        rows.append({'id':unit.get('calculation_unit_id',fact['id']),'team':team,'name':unit['name'],
            'context':f'所选阶段{snapshot["phase_id"]}的具名初态；计算值仍按原配置的事实/估计标识解释。',
            'sources':[copy.deepcopy(snapshot['definition']['sources'][e['source_id']]) for e in fact['evidence']],
            'source_locator':copy.deepcopy(fact['evidence']),'evidence_status':'frozen_historical_phase',
            'actual_personnel':None if unit.get('formation_part') else fact['facts']['personnel']['value'],
            'actual_equipment':None if unit.get('formation_part') else fact['facts']['equipment']['value'],
            'actual_tactical_position':None if unit.get('formation_part') else fact['facts']['position']['value'],
            **({'historical_unit_id':fact['id'],'formation_part':copy.deepcopy(unit['formation_part'])} if unit.get('formation_part') else {})})
    value={'version':FORMAT,'battle':base['battle'],'phase_id':snapshot['phase_id'],
        'historical_definition_hash':missions.digest(base),'units':rows,
        'scope':'默认使用同一份已验证具名历史计算初态；修改值及新增编组为合成演习假设，历史事实不改写。',
        'events':[],'unknowns':copy.deepcopy(snapshot['definition']['coverage'].get('notes',[]))}
    value['basis_hash']=missions.digest(value)
    return value


def seed(binding):
    base=_base(binding);basis=reference(binding)
    config=combined_arms.configuration_from_definition(base)
    for team in ('red','blue'):
        for unit,row in zip(base['initial_state'][team+'_units'],config['teams'][team]):
            row.update(basis_id=unit.get('calculation_unit_id',unit['historical_unit_id']),position={k:unit[k] for k in ('lat','lng')})
    config['historical_basis']={'battle':base['battle'],'basis_hash':basis['basis_hash']}
    return {'basis':basis,'configuration':config,'configuration_limits':combined_arms.configuration_limits(historical_baseline=True),'map_center':copy.deepcopy(base['map_center']),
        'map_radius_km':base['map_radius_km'],
        'estimates':'默认数值直接继承已验证历史配置；缺载估计仍是估计。编辑后另作合成演习假设，不改源历史初态。'}


def definition(binding,configuration,*,campaign_revision=CAMPAIGN_REVISION):
    base=_base(binding);basis=reference(binding)
    if not isinstance(configuration,dict) or not configuration.get('historical_basis'):
        raise ValueError('合成派生须保留同一历史初态来源绑定')
    spec=combined_arms.configure_definition(base,configuration,reference=basis,historical_baseline=True)
    if campaign_revision not in (None,CAMPAIGN_REVISION):
        raise ValueError('不支持的合成会战过程绑定版本')
    if 'campaign_definition' in base and campaign_revision is not None:
        from . import campaign
        campaign.rebind_exercise(spec,base)
    if base.get('campaign_plan'):
        from . import campaign_plan
        campaign_plan.rebind_exercise(spec,base)
    if base.get('campaign_lifecycle'):
        spec['campaign_lifecycle']=copy.deepcopy(base['campaign_lifecycle'])
    spec.pop('historical_calculation',None)
    frozen={'format':FORMAT,'base':copy.deepcopy(binding),'configuration':copy.deepcopy(configuration)}
    if 'campaign_definition' in base and campaign_revision is not None:
        frozen['campaign_revision']=campaign_revision
    spec['historical_synthetic']=frozen
    spec['id']='HS-'+missions.digest(frozen)[:20]
    spec['title']='史实初态派生合成演习 · '+base['battle']
    spec['initial_state']['source_note']=basis['scope']
    if spec['combined_rules']['required_survivors']!=base['combined_rules']['required_survivors']:
        params=copy.deepcopy(binding['parameters'])
        params['goal']['required_survivors']=spec['combined_rules']['required_survivors']
        spec['goal']=historical_operations.goal_text(params)
    return spec


def from_binding(binding):
    if (not isinstance(binding,dict) or set(binding)-{'format','base','configuration','campaign_revision'}
            or not {'format','base','configuration'}<=set(binding) or binding['format']!=FORMAT):
        raise ValueError('合成派生缺少完整冻结基线与编辑参数')
    return definition(binding['base'],binding['configuration'],campaign_revision=binding.get('campaign_revision'))
