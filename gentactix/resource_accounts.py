"""Check model-proposed stock accounts; never execute transport or combat."""
import copy
import math

VERSION='dsh-resource-ledger-1'
CLASSIFIED=('fuel_liters','spares','materials','shells','aa_rounds')


def food_demand(action):
    """Existing per-action teaching work units, not kilograms or a daily ration."""
    return 4 if action=='move' else 2


def required_food(unit,action,seconds,food_received,*,nutrition=None,scheduled=None):
    """Same reference value for validation and read-only candidate diagnostics."""
    from . import formation_parts,support_dynamics
    if scheduled is not None:return scheduled['nutrition']['consumed']
    if nutrition:return support_dynamics.expected(nutrition,unit,action,seconds)['consumed']
    scale=formation_parts.scale(unit)
    return min(food_demand(action)*scale,unit['logistics']['food']*scale+food_received) if unit['personnel']['current']>0 else 0


def closing_stock(opening,received,spent,scale=1):
    """Reference balance only; never changes a stock or fills a proposal."""
    return opening+(received-spent)/scale


def _number(value,integer=False):
    try:valid=type(value) in ((int,) if integer else (int,float)) and math.isfinite(value) and value>=0
    except OverflowError:valid=False
    if not valid:raise ValueError('资源收支数量须为有限非负数，分类库存须为整数')
    return value


def _equal(actual,expected,label):
    _number(actual)
    if not math.isclose(actual,expected,rel_tol=0,abs_tol=1e-6):
        raise ValueError(label+'收支不守恒：期末='+str(actual)+'，应为='+str(expected)+'（期初+到货-消耗）')


def validate_transition(before,after,proposal,orders,*,seconds=None,scheduled=None):
    """Return a checked, explicitly estimated gross ledger without changing state.

    Delivery is a legacy package or the configured split-stock mass equivalent. Empty
    classified maps explicitly declare zero for every category. Model effects
    stay model proposals; rejected balances are never silently repaired.
    """
    from . import missions,support_dynamics,sim_clock,split_supply,supply
    nutrition=support_dynamics.configuration(before)
    split=split_supply.configuration(before)
    if seconds is None:seconds=sim_clock.duration_seconds(before['mission']['definition']['time_step'])
    if (not isinstance(proposal,dict) or set(proposal)!={'version','units'} or proposal['version']!=('dsh-resource-ledger-2' if split else VERSION)
            or not isinstance(proposal['units'],list)):
        raise ValueError('DSH必须提交resource_ledger收支账及正确版本')
    old={u['name']:(team,u) for team,u in missions.units(before)}
    new={u['name']:u for _,u in missions.units(after)}
    rows=proposal['units']
    if (len(rows)!=len(old) or any(not isinstance(r,dict) or not isinstance(r.get('unit'),str) for r in rows)
            or len({r['unit'] for r in rows})!=len(rows) or {r['unit'] for r in rows}!=set(old)):
        raise ValueError('资源收支必须逐项覆盖双方全部单位，不得漏项、重复或引用未知单位')
    nodes={n['id']:n for n in before['supply_nodes']}
    draws={identity:0 for identity in nodes}
    commodity_draws={identity:{'food':0,'ammo':0} for identity in nodes}
    classified={team:{key:0 for key in CLASSIFIED} for team in ('red','blue')}
    actions={r['unit']:r['action'] for r in orders}
    checked={}
    combined=bool(before.get('combined_arms'))
    for row in rows:
        if set(row)!=({'unit','delivery','food_spent','ammo_spent','supply_status','received','spent'}|({'food_received','ammo_received'} if split else set())):
            raise ValueError('资源收支字段缺失或未知；不得提交原生执行回执')
        name=row['unit'];team,prior=old[name];current=new[name];action=actions.get(name,'hold')
        from . import formation_parts
        scale=formation_parts.scale(prior)
        for key in ('delivery','food_spent','ammo_spent'):_number(row[key])
        delivery=row['delivery'];alive=prior['personnel']['current']>0
        if row['supply_status'] not in ('未切断','已切断','未知'):
            raise ValueError('资源收支supply_status只能填未切断、已切断、未知；不要填写未补给或模型估计前缀')
        capacity=(8 if action=='resupply' else 2)*scale if scheduled is None else float('inf')
        if not split:capacity=min(capacity,(100-prior['logistics']['food'])*scale,(100-prior['logistics']['ammo'])*scale)
        if delivery>capacity+1e-6 or delivery and (not alive or scheduled is None and row['supply_status']!='未切断'):
            raise ValueError(name+'：到货超过行动/库存容量，或断线、未知、无可用人员却宣称到货')
        node=supply.bound_node(before,team,prior)
        draws[node['id']]+=delivery
        arrivals={key:row[key+'_received'] if split else delivery for key in ('food','ammo')}
        if split:
            for key,amount in arrivals.items():
                _number(amount)
                maximum=support_dynamics.food_capacity(nutrition,prior) if key=='food' else 100
                if scheduled is None and amount>min(capacity,(maximum-prior['logistics'][key])*scale)+1e-6:
                    raise ValueError(name+'：分类粮弹到货超过本类容量')
                commodity_draws[node['id']][key]+=amount
            _equal(delivery,split_supply.equivalent(split,**arrivals),'分类粮弹到货质量当量')
        required=required_food(prior,action,seconds,arrivals['food'],nutrition=nutrition,
                               scheduled=scheduled[name] if scheduled is not None else None)
        if not math.isclose(row['food_spent'],required,rel_tol=0,abs_tol=1e-6):
            raise ValueError(name+'：粮食消耗须为本行动工作量与可用库存的较小值：'+str(required))
        if scheduled is None and row['ammo_spent']>prior['logistics']['ammo']*scale+1e-6:
            raise ValueError(name+'：轮初弹药不足，轮末到货不能支付本轮射击')
        for key,cost in (('food','food_spent'),('ammo','ammo_spent')):
            _equal(current['logistics'][key],closing_stock(prior['logistics'][key],arrivals[key],row[cost],scale),name+' '+key+' ')
        separate_air=bool(before.get('mission',{}).get('definition',{}).get('air_definition'))
        if any(e.get('attacker')==name and not (separate_air and e.get('weapon_action')=='air_support')
               for e in after.get('engagements',[])) and row['ammo_spent']==0:
            from . import combat_effects
            classified_indirect=(action in ('bombard','suppress') and
                combat_effects.work_cost(combat_effects.reference(before),action)==0)
            spent=row.get('spent')
            if not classified_indirect or not isinstance(spent,dict) or type(spent.get('shells'))is not int or spent['shells']<=0:
                raise ValueError(name+'：已声明实际交火却没有对应弹药消耗')
        for field in ('received','spent'):
            values=row[field]
            if not isinstance(values,dict) or set(values)-set(CLASSIFIED) or not combined and values:
                raise ValueError('资源收支分类未知或当前模型未登记')
            for amount in values.values():_number(amount,integer=True)
        received={k:row['received'].get(k,0) for k in CLASSIFIED} if combined else {}
        spent={k:row['spent'].get(k,0) for k in CLASSIFIED} if combined else {}
        if combined:
            for key in CLASSIFIED:
                if scheduled is None and received[key] and (not delivery or row['supply_status']!='未切断'):
                    raise ValueError(name+'：分类到货须关联有效补给批次')
                if scheduled is None and key!='fuel_liters' and spent[key]>prior['formation'][key]:
                    raise ValueError(name+'：轮初 '+key+' 不足，轮末到货不能用于本轮行动')
                _equal(current['formation'][key],prior['formation'][key]+received[key]-spent[key],name+' '+key+' ')
                classified[team][key]+=received[key]
            cfg=before['mission']['definition']['combined_rules']
            if split and scheduled is None:
                trucks=sum(e['operational'] for e in prior['equipment'] if e['category']=='transport')
                ratio=prior['personnel']['current']/prior['personnel']['committed']
                route=missions.distance(node,current)
                capacity_tons=trucks*cfg['transport_tons_per_truck']*ratio*min(1,cfg['convoy_km_per_turn']/max(.1,route))
                mass=delivery*cfg['ton_per_supply_unit']+sum(received[k]*cfg['cargo_mass_tons'][k] for k in CLASSIFIED)
                if mass>capacity_tons+1e-6:raise ValueError(name+'：分类粮弹及其他物资合计超过运输载重上界')
            if prior['formation'].get('motorized',cfg['motorized']):
                kilometers=missions.distance(prior,current)
                from . import movement_feedback
                if movement_feedback.configuration(before):
                    order=next((o for o in orders if o['unit']==name),dict(unit=name,action='hold'))
                    kilometers=movement_feedback.travel(before,prior,current,order)['ground_km']
                from . import crossings
                if not movement_feedback.configuration(before) and crossings.get_model(before) and action=='move':
                    from . import crossing_network
                    route=crossing_network.plan(before,prior,next(o for o in orders if o['unit']==name))
                    if route:
                        travelled=crossings.path_position(prior,route['waypoints'],current)
                        if travelled is None:raise ValueError('机动燃油核对失败：位置不在渡运通道')
                        kilometers=travelled
                equipment={e['category']:e['operational'] for e in prior['equipment']}
                # Feasibility bound from the existing WSF fuel expression. It
                # does not move a unit, pick a route or debit its fuel.
                minimum=math.ceil(max(0,kilometers*(equipment.get('armor',0)*2+equipment.get('transport',0)*.1)-1e-9))
                if spent['fuel_liters']<minimum:
                    raise ValueError(name+'：实际机动的燃油消耗至少为'+str(minimum)+'升')
        if scheduled is not None:
            timing=scheduled[name]
            for key in ('delivery','ammo_spent','food_received','ammo_received'):
                _equal(row[key],timing[key],name+' 定时补给 '+key+' ')
            for field,values in (('received',received),('spent',spent)):
                for key in CLASSIFIED:_equal(values.get(key,0),timing[field][key],name+' 定时补给 '+field+' '+key+' ')
        checked[name]={'unit':name,'action':action,'supply_status':'DSH估计：'+row['supply_status'],
            'source_node_id':node['id'],
            'delivery':delivery,'food_spent':row['food_spent'],'ammo_spent':row['ammo_spent'],
            **({key+'_received':value for key,value in arrivals.items()} if split else {}),
            'food_after':current['logistics']['food'],'ammo_after':current['logistics']['ammo'],
            'received':received,'spent':spent,'source':'dsh_model_estimate',
            'delivery_basis':'declared_mass_equivalent_split_stock' if split else 'declared_gross_estimate',
            **({'normalized_resource_scale':scale} if formation_parts.is_fragment(prior) else {})}
    after_nodes={n['id']:n for n in after['supply_nodes']}
    if set(after_nodes)!=set(nodes):raise ValueError('资源收支仓库丢失或增加')
    for identity,node in nodes.items():
        if after_nodes[identity]['team']!=node['team']:raise ValueError('资源收支仓库阵营不能改变')
        _equal(after_nodes[identity]['stock'],node['stock']-draws[identity],'仓库 '+identity+' ')
        if split:
            goods=after_nodes[identity].get('commodities',{})
            if set(goods)!={'food','ammo'}:raise ValueError('分类粮弹仓库缺项')
            for key in goods:_equal(goods[key],node['commodities'][key]-commodity_draws[identity][key],'分类粮弹仓库 '+key)
    split_supply.validate_state(after)
    if combined:
        for team in ('red','blue'):
            for key in CLASSIFIED:
                _equal(after['combined_arms']['depots'][team][key],
                    before['combined_arms']['depots'][team][key]-classified[team][key],'分类仓库 '+team+' '+key+' ')
    return [copy.deepcopy(checked[name]) for name in old]
