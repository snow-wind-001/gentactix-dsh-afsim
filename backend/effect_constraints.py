"""Conditional calculation facts from existing guards, never effect generation.

Returned paths belong to this exact candidate. These facts do not certify its
orders, losses, supply, fire, terrain or resulting world; full preview is still
mandatory. No patch, repaired candidate, ledger or next world is produced.
"""
import copy
import math
from collections import Counter

from gentactix import commands,missions,formation_parts,movement_feedback,resource_accounts
from gentactix import sim_clock,split_supply,support_dynamics,supply_schedule,crossings,ferries,fire_process,combat_effects
from .extensions import canonical_numbers

VERSION='candidate-calculation-facts-1'


def _finite(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False


def diagnose(ctx,raw):
    from . import dsh_simulation,turn_preview
    raw=canonical_numbers(copy.deepcopy(raw));s=ctx['session'];world=s['war_state']
    out=dict(version=VERSION,readonly=True,complete_validation=False,
        operation_id=ctx['turn_preview']['operation_id'],before_hash=missions.digest(world),
        candidate_hash=missions.digest(raw),mismatches=[],unavailable=[],
        scope='仅当前候选及其行动、到货、位置依赖下的精确计算事实；不是自动修订、成功预览或执行结果。改变依赖后须重新预览。')

    def missing(unit,reason):out['unavailable'].append(dict(unit=unit,reason=str(reason)))
    def indexed(rows,key,label):
        if not isinstance(rows,list):missing(None,label+'须为数组');return {}
        counts=Counter(r.get(key) for r in rows if isinstance(r,dict) and isinstance(r.get(key),str))
        result={}
        for i,r in enumerate(rows):
            if not isinstance(r,dict) or not isinstance(r.get(key),str):missing(None,label+'缺少精确单位名');continue
            if counts[r[key]]!=1:missing(r[key],label+'单位重复，不能确定字段路径');continue
            result[r[key]]=(i,r)
        return result
    def mismatch(name,path,actual,expected,*,present=True,basis,required=False):
        if type(expected) not in (int,float,str) or isinstance(expected,float) and not math.isfinite(expected):
            missing(name,'该字段计算结果不可表示为有限JSON数值');return
        numeric=type(actual) in (int,float) and type(expected) in (int,float)
        equal=(_finite(actual) and math.isclose(actual,expected,rel_tol=0,abs_tol=1e-6)) if numeric else type(actual) is type(expected) and actual==expected
        if not equal or required and not present:
            out['mismatches'].append(dict(unit=name,path=path,expected=expected,present=present,
                actual=actual if type(actual) in (str,bool,type(None)) or _finite(actual) else None,basis=basis))
    try:orders=turn_preview.resolved_orders(ctx,raw)
    except (ValueError,KeyError,TypeError) as exc:missing(None,'行动尚未通过现有命令校验：'+str(exc));return out
    by_order={o['unit']:o for o in orders};updates=indexed(raw.get('unit_updates'),'unit','unit_updates')
    accounts=indexed((raw.get('resource_ledger') or {}).get('units') if isinstance(raw.get('resource_ledger'),dict) else None,'unit','resource_ledger.units')
    decisions=indexed(raw.get('decisions',[]),'unit_name','decisions')
    seconds=sim_clock.duration_seconds(s['time_step']);nutrition=support_dynamics.configuration(world)
    support={}
    if nutrition:
        proposal=raw.get('sustainment_ledger')
        if not isinstance(proposal,dict) or proposal.get('version')!=nutrition['version']:
            missing(None,'缺少受支持的时间保障回执；不猜测账目行位置')
        else:support=indexed(proposal.get('units'),'unit','sustainment_ledger.units')
    fire={};ground=any(o['action'] in fire_process.GROUND_FIRE for o in orders)
    proposal=raw.get('fire_ledger')
    if ground or proposal is not None:
        if not isinstance(proposal,dict) or proposal.get('version')!=fire_process.VERSION:
            missing(None,'地面火力账缺失或版本未知；不能补造射击时刻')
        else:fire=indexed(proposal.get('units'),'unit','fire_ledger.units')
    split=split_supply.configuration(world);scheduled=None;valid_schedule=True
    if supply_schedule.configuration(world):
        out['scope']+=' constraints为当前声明时点／位置下的必要条件和上限，不是必须到货量或修订；仍须完整预览。'
        try:
            out['constraints'],unknown=supply_schedule.candidate_limits(world,raw.get('supply_schedule_ledger'),orders,seconds)
            out['unavailable'].extend(unknown)
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            out['constraints']=[];missing(None,'定时补给必要界尚不可读取：'+str(exc))
        try:scheduled=supply_schedule.validate_ledger(world,raw.get('supply_schedule_ledger'),orders,seconds)
        except (ValueError,KeyError,TypeError) as exc:missing(None,'定时补给账未通过，不能退回旧粮耗：'+str(exc));valid_schedule=False
    fire_reference=combat_effects.reference(world) if world['mission']['definition'].get('combined_rules') else None
    for _,unit in missions.units(world):
        name=unit['name'];order=by_order.get(name,dict(unit=name,action='hold'));action=order['action']
        if name in decisions:
            i,row=decisions[name]
            mismatch(name,f'/decisions/{i}/action',row.get('action'),action,present='action' in row,basis='resolved_command')
        if name not in updates:missing(name,'没有唯一的单位更新行');continue
        i,update=updates[name];base=f'/unit_updates/{i}'
        try:following=dsh_simulation._merge(unit,{k:v for k,v in update.items() if k!='unit'})
        except (ValueError,KeyError,TypeError) as exc:missing(name,'更新行尚不可读取：'+str(exc));continue
        nutrition_ready=not nutrition or valid_schedule
        if nutrition and valid_schedule:
            try:
                wanted=(scheduled[name]['nutrition'] if scheduled is not None else support_dynamics.expected(nutrition,unit,action,seconds))
                if name in support:
                    j,row=support[name]
                    for key in support_dynamics.RECEIPT_FIELDS:
                        mismatch(name,f'/sustainment_ledger/units/{j}/'+key,row.get(key),wanted[key],
                            present=key in row,basis='validated_scheduled_nutrition' if scheduled is not None else 'support_dynamics.expected')
                else:missing(name,'没有唯一时间保障回执行')
                changes=update.get('sustainment',{});state=following.get('sustainment',{})
                if not isinstance(changes,dict) or not isinstance(state,dict):raise ValueError('sustainment不是对象')
                for key in ('shortage_hours','noncombat_remainder'):
                    actual=state.get(key)
                    if not _finite(actual) or not math.isclose(actual,wanted[key],rel_tol=0,abs_tol=1e-6):nutrition_ready=False
                    mismatch(name,base+'/sustainment/'+key,actual,wanted[key],present=key in changes,basis='reference_nutrition_state')
                changes=update.get('personnel',{})
                if not isinstance(changes,dict):raise ValueError('personnel不是对象')
                mismatch(name,base+'/personnel/noncombat_losses',following['personnel'].get('noncombat_losses'),
                    unit['personnel']['noncombat_losses']+wanted['noncombat_delta'],present='noncombat_losses' in changes,
                    basis='reference_nutrition_noncombat_delta')
            except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
                nutrition_ready=False;missing(name,'保障依赖尚不可计算：'+str(exc))
        if name in accounts and valid_schedule:
            j,row=accounts[name];path=f'/resource_ledger/units/{j}'
            try:
                delivery=resource_accounts._number(row['delivery']);spent=resource_accounts._number(row['ammo_spent'])
                received={k:resource_accounts._number(row[k+'_received']) if split else delivery for k in ('food','ammo')}
                required=resource_accounts.required_food(unit,action,seconds,received['food'],nutrition=nutrition,
                    scheduled=scheduled[name] if scheduled is not None else None)
                mismatch(name,path+'/food_spent',row.get('food_spent'),required,present='food_spent' in row,basis='required_food')
                scale=formation_parts.scale(unit)
                for key,cost in [('food',required),('ammo',spent)]:
                    expected=resource_accounts.closing_stock(unit['logistics'][key],received[key],cost,scale)
                    changes=update.get('logistics',{})
                    if not isinstance(changes,dict):raise ValueError('logistics不是对象')
                    mismatch(name,base+'/logistics/'+key,following['logistics'].get(key),expected,
                        present=key in changes,basis='closing_stock; food_uses_required_food; delivery_and_ammo_spent_are_candidate_dependencies')
            except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:missing(name,'资源依赖尚不可计算：'+str(exc))
        elif name not in accounts:missing(name,'没有唯一资源收支行')
        if world['mission']['definition'].get('combined_rules'):
            try:
                row=None;j=None
                if action in fire_process.GROUND_FIRE:
                    if name not in fire:raise ValueError('没有唯一对应的地面火力回执')
                    j,row=fire[name]
                    if row.get('action')!=action or row.get('target')!=order.get('target'):raise ValueError('火力回执行动／目标与解析后命令不一致')
                expected=fire_process.reload_after(world,unit,seconds,row=row,reference=fire_reference)
                if row is not None:
                    mismatch(name,f'/fire_ledger/units/{j}/reload_remaining_s',row.get('reload_remaining_s'),expected,
                        present='reload_remaining_s' in row,basis='reload_after; declared_cycle_and_last_fire_dependencies')
                changes=update.get('formation',{})
                if not isinstance(changes,dict):raise ValueError('formation不是对象')
                initial=fire_process.reload_seconds(unit,fire_reference)
                actual=fire_process.reload_seconds(following,fire_reference)
                mismatch(name,base+'/formation/reload_remaining_s',actual,expected,present='reload_remaining_s' in changes,
                    required=row is not None or initial>0,basis='reload_after; firing_or_passive_clock')
            except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:missing(name,'装填依赖尚不可计算：'+str(exc))
        position_ok=True
        try:
            # A route service or carried passenger needs its existing receipts;
            # do not pretend it must reach the direct ground destination.
            routed=action=='move' and crossings.get_model(world)
            if routed:
                from gentactix import crossing_network
                routed=bool(crossing_network.plan(world,unit,order))
            carried=ferries.carrier(world,name)
            target=(order if action=='move' and commands.available(following) else unit if action!='move' and not carried else None)
            if target is not None and not routed and missions.distance(following,target)>.01:
                position_ok=False
                for key in ('lat','lng'):
                    mismatch(name,base+'/'+key,following.get(key),target[key],present=key in update,basis='resolved_position_command')
            if movement_feedback.configuration(world):
                if not position_ok:missing(name,'先满足位置命令，再按新位置核对疲劳');continue
                if not nutrition_ready:missing(name,'先满足保障状态，再核对缺粮疲劳下限');continue
                if not isinstance(following.get('formation'),dict):raise ValueError('formation不是对象')
                measured=movement_feedback.travel(world,unit,following,order)
                expected=movement_feedback.fatigue_value(world,unit,action,measured['ground_km'],following=following)
                if type(expected) is float and expected.is_integer():expected=int(expected)
                changes=update.get('formation',{})
                if not isinstance(changes,dict):raise ValueError('formation不是对象')
                mismatch(name,base+'/formation/fatigue',following['formation'].get('fatigue'),expected,
                    present='fatigue' in changes,basis='fatigue_value; current_candidate_position_and_shortage_debt')
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:missing(name,'运动依赖尚不可计算：'+str(exc))
    out['mismatch_count']=len(out['mismatches']);out['unavailable_count']=len(out['unavailable'])
    if 'constraints' in out:out['constraint_count']=len(out['constraints'])
    return out
