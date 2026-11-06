"""Compile independent food/ammo cargo into WSF and verify its receipts."""
import copy
import math
from gentactix import split_supply,formation_parts,support_dynamics as sd
from .afsim_literals import number as n


def initialize(nodes):
    return [f' double depot{d}_{key}={n(node["commodities"][key])};' for d,node in enumerate(nodes) for key in ('food','ammo')]


def plan(cfg,u,i,d,*,nutrition=None):
    weight=formation_parts.scale(u);share=cfg['food_mass_share']
    keys=[cfg['priority'],'ammo' if cfg['priority']=='food' else 'food']
    lines=[f' double foodDelivery{i}=0; double ammoDelivery{i}=0;',
           f' double cargoBudget{i}=Math.Min(supplyRate{i},Math.Max(0,capacity{i}/supplyTon{i}));']
    for key in keys:
        fraction=share if key=='food' else 1-share
        capacity=sd.food_capacity(nutrition,u) if key=='food' else 100
        lines.append(f' if (conn{i}==1 && {u["personnel"]["current"]}>0) {{ {key}Delivery{i}=Math.Min(supplyRate{i},Math.Min({n((capacity-u["logistics"][key])*weight)},Math.Min(depot{d}_{key},cargoBudget{i}/{n(fraction)}))); cargoBudget{i}=Math.Max(0,cargoBudget{i}-{key}Delivery{i}*{n(fraction)}); }}')
    lines.append(f' delivery{i}=foodDelivery{i}*{n(share)}+ammoDelivery{i}*{n(1-share)};')
    return lines


def commit(cfg,i,d,identity):
    share=cfg['food_mass_share']
    return [f' if (delivery{i}==0) {{ foodDelivery{i}=0; ammoDelivery{i}=0; }}',
            f' depot{d}_food=depot{d}_food-foodDelivery{i}; depot{d}_ammo=depot{d}_ammo-ammoDelivery{i};',
            f' depot{d}=depot{d}_food*{n(share)}+depot{d}_ammo*{n(1-share)};',
            f' writeln("GTXSPLIT|{identity}|",Format.Fixed(foodDelivery{i},12),"|",Format.Fixed(ammoDelivery{i},12));']


def finish(nodes):
    return [f' writeln("GTXSPLITNODE|{d}|",Format.Fixed(depot{d}_food,12),"|",Format.Fixed(depot{d}_ammo,12));' for d in range(len(nodes))]


def parse(text,model,scene,accounts,stocks):
    cfg=model.get('supply_distribution');units={};nodes={}
    for line in text.splitlines():
        parts=line.split('|')
        if parts[0] not in ('GTXSPLIT','GTXSPLITNODE'):continue
        if not cfg or len(parts)!=4:raise ValueError('分类粮弹原生回执非法')
        key=parts[1] if parts[0]=='GTXSPLIT' else int(parts[1]);target=units if parts[0]=='GTXSPLIT' else nodes
        if key in target:raise ValueError('分类粮弹原生回执重复')
        values=list(map(float,parts[2:]))
        if any(not math.isfinite(x) or x<0 for x in values):raise ValueError('分类粮弹原生数量非法')
        target[key]=dict(zip(('food','ammo'),values))
    if not cfg:return None
    prior_nodes=model['supply_nodes']
    if set(units)!=set(scene['entities']) or set(nodes)!=set(range(len(prior_nodes))):raise ValueError('缺少分类粮弹原生回执')
    old={u['name']:u for _,u in model['units']};draws={node['id']:{'food':0,'ammo':0} for node in prior_nodes}
    def same(a,b):
        if not math.isclose(a,b,rel_tol=0,abs_tol=1e-6):raise ValueError('分类粮弹原生收支不守恒')
    for identity,goods in units.items():
        prior=old[scene['entities'][identity]['name']];row=accounts[identity];scale=formation_parts.scale(prior)
        same(row['delivery'],split_supply.equivalent(cfg,**goods))
        for key,amount in goods.items():
            capacity=sd.food_capacity(model.get('support_dynamics'),prior) if key=='food' else 100
            if not model.get('supply_schedule') and amount>(capacity-prior['logistics'][key])*scale+1e-6:raise ValueError('分类粮弹原生到货超过容量')
            same(row[key],prior['logistics'][key]+(amount-row[key+'_spent'])/scale)
            draws[prior['supply_node_id']][key]+=amount
            row[key+'_received']=amount
    for index,node in enumerate(prior_nodes):
        for key in ('food','ammo'):same(nodes[index][key],node['commodities'][key]-draws[node['id']][key])
        same(stocks[index],split_supply.equivalent(cfg,**nodes[index]))
    return {'units':units,'nodes':nodes}


def apply(after,data,scene):
    if data is None:return
    for index,goods in data['nodes'].items():after['supply_nodes'][index]['commodities']=copy.deepcopy(goods)
    by_name={scene['entities'][identity]['name']:goods for identity,goods in data['units'].items()}
    for row in after['mission']['ledger']:
        row.update({key+'_received':amount for key,amount in by_name[row['unit']].items()})
        row['delivery_basis']='native_mass_equivalent_split_stock'
    split_supply.validate_state(after)
