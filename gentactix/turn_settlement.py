"""Read committed/candidate accounts into a report basis; never execute effects."""
import copy
import math
from .supply import objects,index_value

VERSION='turn-settlement-3'
LEGACY_VERSION='turn-settlement-2'
CLASSIFIED=('fuel_liters','spares','materials','shells','aa_rounds')


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:return None
    return int(value) if type(value) is float and value.is_integer() else value


def total(values):
    return None if any(number(v) is None for v in values) else number(sum(values))


def build(state,previous=None,*,version=None):
    version=version or VERSION
    if version not in (VERSION,LEGACY_VERSION):raise ValueError('未支持的结算摘要版本')
    old={(t,u.get('name')):u for t in ('red','blue') for u in objects((previous or {}).get(t+'_units'))}
    ledger=objects(state.get('mission',{}).get('ledger'));rows=[];teams=[]
    orders={r.get('unit'):r for r in objects(state.get('mission',{}).get('last_orders'))}
    turn=state.get('mission',{}).get('turn')
    for team in ('red','blue'):
        own=[]
        for unit in objects(state.get(team+'_units')):
            name=unit.get('name');prior=old.get((team,name),{});matches=[r for r in ledger if r.get('unit')==name]
            receipt=matches[0] if len(matches)==1 else {};f=unit.get('formation');f=f if isinstance(f,dict) else {};native=f.get('last_execution') or {}
            native=native if isinstance(native,dict) else {}
            prior_formation=prior.get('formation');prior_formation=prior_formation if isinstance(prior_formation,dict) else {}
            row=dict(team=team,name=name,receipt_known=bool(receipt),source=receipt.get('source','未标注'),
                action=orders.get(name,{}).get('action',receipt.get('action','未记录')),
                food_before=number((prior.get('logistics') or {}).get('food')),ammo_before=number((prior.get('logistics') or {}).get('ammo')),
                food_after=number((unit.get('logistics') or {}).get('food')),ammo_after=number((unit.get('logistics') or {}).get('ammo')),
                food_spent=number(receipt.get('food_spent')),ammo_spent=number(receipt.get('ammo_spent')),
                food_received=number(receipt.get('food_received',receipt.get('delivery'))),
                ammo_received=number(receipt.get('ammo_received',receipt.get('delivery'))),classified_spent={})
            row.update(supply_index_before=number(index_value(prior)),supply_index_after=number(index_value(unit)))
            if 'unit_participation' in state:
                from . import unit_participation
                current=unit_participation.unit_view(state,unit,team)
                earlier=unit_participation.unit_view(previous,prior,team) if previous and prior else None
                row['participation']=dict(before=earlier['status'] if earlier else None,after=current['status'],
                    label=current['label'],targetable=current['targetable'],controls_objectives=current['controls_objectives'],
                    pending=copy.deepcopy(current['pending']),scope=current['scope'])
            p=unit.get('personnel') or {};a=prior.get('personnel') or {}
            def change(key):
                old=number(a.get(key));new=number(p.get(key))
                return new-old if old is not None and new is not None else None
            row['personnel']=dict(before_current=number(a.get('current')),current=number(p.get('current')),
                committed=number(p.get('committed')),battle_losses=change('casualties'),noncombat_losses=change('noncombat_losses'))
            from .personnel_projection import strength_pct
            if version!=LEGACY_VERSION:row.update(personnel_strength_pct=number(strength_pct(unit)),fatigue=number(f.get('fatigue')))
            for key in CLASSIFIED:
                spent=receipt.get('spent')
                if isinstance(spent,dict):value=number(spent.get(key,0))
                elif native.get('turn')==turn and native.get('supply_receipt_revision'):
                    a=number(prior_formation.get(key));b=number(f.get(key));received=number(native.get('received_'+key))
                    value=number(a+received-b) if None not in (a,b,received) else None
                else:value=None
                row['classified_spent'][key]=value
            row['receipt_known']=all(row[k] is not None for k in ('food_spent','ammo_spent','food_received','ammo_received'))
            own.append(row);rows.append(row)
        teams.append(dict(team=team,unit_count=len(own),receipt_units=sum(r['receipt_known'] for r in own),
            **{k:total([r[k] for r in own]) for k in ('food_spent','ammo_spent','food_received','ammo_received')},
            classified_spent={k:total([r['classified_spent'][k] for r in own]) for k in CLASSIFIED}))
    definition=state.get('mission',{}).get('definition',{});goals=[]
    config=definition.get('campaign_lifecycle');life=state.get('campaign_lifecycle')
    owners={i:p for p in (config or {}).get('phases',[]) for i in p.get('goal_ids',[])}
    for node in definition.get('campaign_plan',{}).get('nodes',[]):
        value=state.get('campaign_plan',{}).get('nodes',{}).get(node['id'])
        if value is None:continue
        prior=(previous or {}).get('campaign_plan',{}).get('nodes',{}).get(node['id'])
        changed=prior is not None and any(prior.get(k)!=value.get(k) for k in ('status','condition','completed_at'))
        sampled=value['status'] not in ('pending','waiting_phase')
        goals.append(dict(id=node['id'],label=node['label'],status=value['status'],
            condition=value.get('condition') if sampled else None,condition_sampled=sampled,
            phase_at_end=(dict(id=owners[node['id']]['id'],label=owners[node['id']]['label'],
                status=(life or {}).get('phases',{}).get(owners[node['id']]['id'],{}).get('status')) if node['id'] in owners else None),
            reason=value.get('reason',''),changed=changed,before_status=prior.get('status') if prior else None))
    phase=None
    if config and life:
        phases=config['phases'];prior=(previous or {}).get('campaign_lifecycle')
        labels={r['id']:r['label'] for r in phases}
        phase=dict(observed_label=phases[life['last_sample_phase']]['label'] if turn else None,
            before_label=phases[prior['phase_index']]['label'] if prior else None,
            after_label=phases[life['phase_index']]['label'],status=life['status'],
            changes=[dict(label=labels[r['phase_id']],status=r['status'],at_seconds=r['at_seconds']) for r in life.get('last_changes',[])])
    return dict(version=version,turn=turn,current_time=state.get('current_time'),resource_teams=teams,units=rows,goals=goals,phase=phase,
        scope='当前执行单位的本轮已知毛收支与宿主评分；未知不补0，工作量不换算吨数，候选预览不等于执行')


def projection(value):
    result=copy.deepcopy(value);result['total_units']=len(result['units']);result['units']=result['units'][:16]
    result['unlisted_units']=result['total_units']-len(result['units'])
    result['total_goals']=len(result['goals']);result['goals']=result['goals'][:64]
    result['unlisted_goals']=result['total_goals']-len(result['goals'])
    for row in result['goals']:row['reason']=row['reason'][:200]
    return result
