"""Necessary bounds on submitted effects under the shared aggregate model.

No timestep, state update, inferred casualty quota or repair is performed here.
Efficiency=1 and zero protection/entrenchment deliberately overestimate possible
ground damage. Passing this check proves a necessary bound, not model calibration.
The caller must first validate orders, fire/resources, aviation and campaign data.
"""
import math

from . import combat_effects,fire_process,missions

VERSION='closed-fire-effect-bound-1'
PROFILES={'aggregate-fire-cycles-2','aggregate-fire-cycles-2.1','aggregate-fire-cycles-2.2','aggregate-fire-cycles-2.3','aggregate-fire-cycles-2.4','aggregate-fire-cycles-2.5','aggregate-fire-cycles-2.6'}


def receipt_for_unit(world,name,turn):
    receipt=(world.get('dsh_execution') or {}).get('effect_admission')
    if (not isinstance(receipt,dict) or receipt.get('version')!=VERSION or receipt.get('source')!='host_parameter_constraint'
            or receipt.get('turn')!=turn):return None
    row=next((r for r in receipt.get('units',[]) if r.get('unit')==name),None)
    if row is None:return None
    return dict(version=VERSION,source=receipt['source'],turn=turn,calibration_proven=False,
        **{k:row[k] for k in ('ground_casualties','ground_maximum','air_casualties','captured')},
        scope='仅通过必要的保守上界；不是预计伤亡、历史标定或原生执行证明')


def validate(before,after,result,ledger):
    ref=combat_effects.reference(before)
    orders={r['unit']:r for r in result['orders']}
    rows=(ledger or {}).get('units',[])
    if rows and ref['version'] not in PROFILES:
        raise ValueError('效能上界未支持火力模型版本'+str(ref['version'])+'；须先注册对应裁判规则，不能默认为已验证')
    old={u['name']:u for _,u in missions.units(before)};new={u['name']:u for _,u in missions.units(after)}
    accounts={r['unit']:r for r in result['resource_ledger']['units']}
    # A moving same-root part can join the target footprint within the frame.
    # The necessary upper bound therefore includes the entire living root for
    # the new rule, never just its turn-start coincident members.
    area=fire_process.area_factors(before,ceiling=True);contributions={}
    for row in rows:
        order=orders[row['unit']];actor=old[row['unit']];target=old[order['target']];cycles=row['fire_cycles']
        kind=order['action'];power=0
        if kind in ('bombard','suppress'):
            shells=accounts[row['unit']]['spent'].get('shells',0)
            power=fire_process.formula_value('indirect_power',shells=shells)
        else:
            direct=ref.get('direct_fire')
            if direct:
                attempts=fire_process.formula_value('direct_attempts',committed=actor['personnel']['committed'],
                    engaged_fraction=direct['engaged_fraction'],rounds_per_min=direct['rounds_per_min'],direct_cycle_s=ref['direct_cycle_s'])
                power=fire_process.formula_value('direct_base_power',attempts=attempts,hit_probability=direct['hit_probability'],range_effect=direct['range_max_factor'])
            else:power=fire_process.formula_value('legacy_base_power',size_factor=actor['personnel']['committed']/3000)
            armor=next((e['operational'] for e in actor['equipment'] if e['category']=='armor'),0)
            power=(power+fire_process.formula_value('armor_power',operational_armor=armor))*cycles
        cover_key='direct_cover' if kind=='fire' and ref.get('direct_fire') else 'area_cover'
        cover=fire_process.formula_value(cover_key,protection=0,entrenchment=0,
            dispersion_km2=target['formation']['dispersion_km2'],**area[target['name']])
        ceiling=power*cover
        if kind=='suppress':ceiling=fire_process.formula_value('suppress_effect',damage=ceiling)
        if 'damage_quantum'in ref:ceiling+=cycles*ref['damage_quantum']/2
        contributions.setdefault(target['name'],[]).append(dict(unit=actor['name'],action=kind,
            fire_cycles=cycles,shells=accounts[row['unit']]['spent'].get('shells',0),ceiling=ceiling))
    # These envelopes have already passed the separate aviation/campaign checks.
    # Aggregate each flight's own contribution, never repeated target summaries.
    air=after.get('air_operations') or {};air_effects={};turn=after['mission']['turn']
    if air.get('last_turn')==turn:
        for task in air.get('missions',[]):
            if task.get('turn')==turn and task.get('source')=='dsh_model_estimate' and task.get('status')=='returned':
                air_effects[task['target']]=air_effects.get(task['target'],0)+task['personnel_effect']
    campaign=after.get('campaign') or {}
    actors=campaign.get('actors',{}) if campaign.get('turn')==turn and campaign.get('execution_source')=='dsh_model_estimate' else {}
    units=[]
    for name,unit in old.items():
        delta=new[name]['personnel']['casualties']-unit['personnel']['casualties']
        captured=actors.get(name,{}).get('captured_this_turn',0);aerial=air_effects.get(name,0)
        ground=delta-captured-aerial;parts=contributions.get(name,[])
        carry=unit['formation'].get('combat_damage_remainder',0) if parts else 0
        ceiling=math.fsum(r['ceiling'] for r in parts)
        maximum=math.floor(ceiling+carry+1e-7)
        if ground<0 or ground>maximum:
            raise ValueError(name+f'：效能超过当前模型上界；新增战斗减员{delta}－已核航空{aerial}－本轮受降{captured}＝地面{ground}，'
                f'按已申报火力、效率取1且不计防护的地面上界{maximum}（含既有余量{carry:g}，炮弹合计{sum(r["shells"] for r in parts)}）。'
                '请修正候选战损及过程账；不能补造炮弹、航空或受降，不按史料总数摊派。')
        units.append(dict(unit=name,ground_casualties=ground,ground_maximum=maximum,continuous_ceiling=ceiling,
            carried_fraction=carry,air_casualties=aerial,captured=captured,contributions=parts))
    return dict(version=VERSION,source='host_parameter_constraint',turn=after['mission']['turn'],profile_hash=ref['definition_hash'],
        calibration_proven=False,units=units,scope='必要的保守效能上界；不是伤亡预测、历史标定或AFSIM执行证明，不设伤亡下限')
