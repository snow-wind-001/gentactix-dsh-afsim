"""Versioned sustainment inputs and read-only receipt checks; no state executor."""
import math

VERSION='time-sustainment-1'
PERSONNEL_VERSION='personnel-rations-1'
VERSIONS={VERSION,PERSONNEL_VERSION}
LEGACY_VERSION='legacy-noncombat-1'
LEGACY_PER_TURN=2
LEGACY_ROUND_EPSILON=1e-9
DEFERRED_SUPPORT_POLICY='deferred-support-exposure-1'
LIMITS={'food_work_per_hour':(0.001,100),'move_factor':(1,10),
        'shortage_fatigue_per_hour':(0,100),'recovery_hours_per_fed_hour':(0,10),
        'incapacity_after_hours':(1,8760),'incapacity_fraction_per_hour':(0,.1)}
RECEIPT_FIELDS=('demand','consumed','unmet','shortage_hours','noncombat_remainder','fatigue_floor','noncombat_delta')
PERSONNEL_LIMITS={**{k:v for k,v in LIMITS.items() if k!='food_work_per_hour'},
    'ration_kg_per_person_day':(.001,100),'food_kg_per_work':(.001,1e9),
    'carried_kg_per_committed_person':(.001,1000)}


def limits(version):
    if version==VERSION:return LIMITS
    if version==PERSONNEL_VERSION:return PERSONNEL_LIMITS
    raise ValueError('时间保障模型版本非法')


def number(value,low=0,high=1e12):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('时间保障参数／回执须为有界有限非负数')


def validate_config(cfg):
    if not isinstance(cfg,dict) or not isinstance(cfg.get('version'),str) or cfg['version'] not in VERSIONS:
        raise ValueError('时间保障模型版本或字段非法')
    fields=limits(cfg['version'])
    if set(cfg)!=set(fields)|{'version','assumption'}:raise ValueError('时间保障模型版本或字段非法')
    if not isinstance(cfg['assumption'],str) or not cfg['assumption'].strip() or len(cfg['assumption'])>4000:
        raise ValueError('时间保障参数必须说明估计依据与未标定边界')
    for key,(low,high) in fields.items():number(cfg[key],low,high)


def validate_binding(cfg,rules,split):
    """One food mass encoding, shared with the existing transport ledger."""
    validate_config(cfg)
    if cfg['version']!=PERSONNEL_VERSION:return
    from . import split_supply
    if not isinstance(rules,dict) or not isinstance(split,dict):raise ValueError('人员粮秣模型必须绑定分类粮弹及运输质量参数')
    split_supply.validate_config(split)
    amount=rules.get('ton_per_supply_unit');number(amount,.000000001)
    mass=amount*1000*split['food_mass_share']
    if not math.isclose(cfg['food_kg_per_work'],mass,rel_tol=0,abs_tol=1e-6):
        raise ValueError('粮食质量换算不一致：food_kg_per_work须等于运输吨/包×1000×粮食质量份额')


def food_capacity(cfg,unit):
    """Stored-work capacity; partition factors apply only to equivalent mass."""
    if not cfg or cfg['version']!=PERSONNEL_VERSION:return 100
    from . import formation_parts
    return unit['personnel']['committed']*cfg['carried_kg_per_committed_person']/cfg['food_kg_per_work']/formation_parts.scale(unit)


def food_mass(cfg,unit):
    from . import formation_parts
    if not cfg or cfg['version']!=PERSONNEL_VERSION:return None
    return unit['logistics']['food']*formation_parts.scale(unit)*cfg['food_kg_per_work']


class FoodLoadingError(ValueError):
    """A quoted input constraint, never a corrected stock or a state receipt."""
    def __init__(self,message,loading):
        self.food_loading=loading
        super().__init__(message+'：'+str(loading['unit'])+
            f'；food={loading["food_work"]}，容量={loading["capacity_work"]}工作量，'
            f'质量={loading["food_mass_kg"]}／{loading["capacity_kg"]}kg。'
            'food_kg_per_work已包含粮食质量份额，不能重复乘除food_mass_share。')


def validate_food_loading(cfg,unit):
    """Use the same frozen load equation for editable inputs and runtime state."""
    if not cfg or cfg['version']!=PERSONNEL_VERSION:return
    capacity=food_capacity(cfg,unit)
    from . import formation_parts
    loading=dict(unit=unit.get('calculation_unit_id',unit.get('historical_unit_id',unit.get('name','unit'))),
        committed=unit['personnel']['committed'],food_work=unit['logistics']['food'],
        food_mass_kg=food_mass(cfg,unit),capacity_work=capacity,
        capacity_kg=unit['personnel']['committed']*cfg['carried_kg_per_committed_person'],
        resource_scale=formation_parts.scale(unit),food_kg_per_work=cfg['food_kg_per_work'])
    if capacity>100+1e-6:
        raise FoodLoadingError('携行容量超过工作量编码上限；须显式提高粮食kg/工作量并同步运输换算，不截断库存',loading)
    if unit['logistics']['food']>capacity+1e-6:
        raise FoodLoadingError('随队粮食超过本单位冻结携行容量',loading)


def unit_demand(cfg,unit,action,seconds):
    from . import formation_parts
    return demand(cfg,action,seconds,formation_parts.scale(unit),personnel=unit['personnel']['current'])


def configuration(world):
    return world.get('mission',{}).get('definition',{}).get('support_dynamics')


def initial_state(cfg=None):
    return {'version':cfg['version'] if cfg else VERSION,'shortage_hours':0,'noncombat_remainder':0}


def deferred_support(unit):
    """Read the immutable formal conversion policy; never create a debt store."""
    metadata=unit.get('runtime_allocation')
    if metadata is None:return False
    if not isinstance(metadata,dict):raise ValueError('运行中分配元数据非法')
    if 'support_remainder_policy' not in metadata:return False
    from . import formation_conversion
    if (metadata['support_remainder_policy']!=DEFERRED_SUPPORT_POLICY
            or metadata.get('version')!=formation_conversion.VERSION
            or not isinstance(metadata.get('origins'),dict) or not metadata['origins']):
        raise ValueError('重编保障余量策略缺少有效版本或根账来源')
    if not unit.get('sustainment'):raise ValueError('重编保障余量策略缺少时间保障状态')
    return True


def validate_remainder(unit):
    value=unit['sustainment']['noncombat_remainder']
    deferred=deferred_support(unit)
    ceiling=unit['personnel']['committed'] if deferred else 1
    try:number(value)
    except ValueError as exc:raise ValueError('非战斗减员余量须为有界有限非负数') from exc
    if value>=ceiling:
        raise ValueError('已登记重编保障余量须小于投入人数' if deferred else '非战斗减员余量必须小于1')
    return deferred


def legacy_allowance(unit):
    """Read-only input also compiled by native WSF; not a per-hour rate."""
    from . import formation_parts
    return round(LEGACY_PER_TURN*formation_parts.scale(unit),12)


def legacy_quote(unit,food_after):
    from . import formation_parts
    fragment=formation_parts.is_fragment(unit)
    prior=unit['formation'].get('partition_noncombat_remainder',0) if fragment else 0
    number(prior,0,1);number(food_after,0,100)
    if prior>=1:raise ValueError('非战斗余量须小于1')
    if food_after>0:return dict(maximum=0,remainder=prior,starved=False)
    load=legacy_allowance(unit)+(round(prior,12) if fragment else 0)
    whole=math.floor(load+LEGACY_ROUND_EPSILON)
    return dict(maximum=min(unit['personnel']['current'],whole),remainder=max(0,round(load-whole,12)) if fragment else 0,starved=True)


def validate_legacy_transition(before,after,proposal):
    import json
    from collections import Counter
    from . import missions,formation_parts
    old={u['name']:u for _,u in missions.units(before)};new={u['name']:u for _,u in missions.units(after)}
    quotes={name:legacy_quote(u,new[name]['logistics']['food']) for name,u in old.items()}
    starving={name for name,q in quotes.items() if q['starved'] and formation_parts.is_fragment(old[name])}
    changed={name for name in starving if not math.isclose(quotes[name]['remainder'],old[name]['formation'].get('partition_noncombat_remainder',0),rel_tol=0,abs_tol=1e-12)}
    accepted={}
    if proposal is None:
        if changed:raise ValueError('旧模型分队余量发生变化，须提交sustainment_ledger版本'+LEGACY_VERSION+'；所需单位：'+','.join(sorted(starving)))
    else:
        if (not isinstance(proposal,dict) or set(proposal)!={'version','units'} or proposal.get('version')!=LEGACY_VERSION
                or not isinstance(proposal.get('units'),list)):
            actual=dict(version=proposal.get('version'),fields=sorted(proposal)) if isinstance(proposal,dict) else type(proposal).__name__
            raise ValueError('旧模型保障回执版本／字段错误：提交'+json.dumps(actual,ensure_ascii=False)+
                '；应为version='+LEGACY_VERSION+'，仅含version、units，units须为数组。')
        rows=proposal['units']
        for i,row in enumerate(rows):
            if not isinstance(row,dict) or set(row)!={'unit','noncombat_remainder'} or not isinstance(row.get('unit'),str):
                actual=dict(unit=row.get('unit'),fields=sorted(row)) if isinstance(row,dict) else type(row).__name__
                wanted=quotes.get(row.get('unit')) if isinstance(row,dict) and isinstance(row.get('unit'),str) else None
                hint='；本轮应提交的小数余量='+str(wanted['remainder']) if wanted else ''
                raise ValueError(f'旧模型余量回执units[{i}]字段错误：提交'+json.dumps(actual,ensure_ascii=False)+
                    '；每行仅含unit、noncombat_remainder；noncombat_losses是人员累计损失，不能替代余量'+hint+'。')
        counts=Counter(row['unit'] for row in rows)
        if len(rows)!=len(starving) or set(counts)!=starving:
            differences={'缺少':sorted(starving-set(counts)),'多余':sorted(set(counts)-starving),
                '重复':sorted(name for name,count in counts.items() if count>1)}
            bounded={key:dict(count=len(names),units=names[:16]) for key,names in differences.items()}
            raise ValueError('旧模型余量回执须准确覆盖粮食归零分队：'+json.dumps(bounded,ensure_ascii=False)+
                '；不得用旧父级名替代当前分队名。')
        for row in rows:
            name=row['unit'];value=row['noncombat_remainder'];number(value,0,1)
            if value>=1 or not math.isclose(value,quotes[name]['remainder'],rel_tol=0,abs_tol=1e-12):
                raise ValueError(name+f'：非战斗余量提交{value}，应为{quotes[name]["remainder"]}；不由宿主补写')
            accepted[name]=value
    constraints=[]
    for name,u in old.items():
        delta=new[name]['personnel']['noncombat_losses']-u['personnel']['noncombat_losses'];q=quotes[name]
        if not 0<=delta<=q['maximum']:
            raise ValueError(name+f'：非战斗减员提交{delta}，旧模型上限{q["maximum"]}；粮食期末{new[name]["logistics"]["food"]}，'
                f'原编组预算为每回合{LEGACY_PER_TURN}×份额，不能虚构气候、疾病或改写战斗分类。')
        constraints.append(dict(unit=name,noncombat_delta=delta,noncombat_maximum=q['maximum'],starved=q['starved'],
            next_remainder=q['remainder'],remainder_submitted=name in accepted))
    return dict(version=LEGACY_VERSION,turn=after['mission']['turn'],source='host_legacy_support_constraint',
        accepted_remainders=accepted,units=constraints,calibration_proven=False,
        scope='旧模型每回合饥饿预算必要边界；不是每小时率或历史／气候标定；余量由模型显式提交')


def legacy_receipt_for_unit(world,name,turn):
    receipt=(world.get('dsh_execution') or {}).get('legacy_noncombat_constraint')
    if (not isinstance(receipt,dict) or receipt.get('version')!=LEGACY_VERSION
            or receipt.get('source')!='host_legacy_support_constraint' or receipt.get('turn')!=turn):return None
    rows=receipt.get('units')
    if not isinstance(rows,list):return None
    row=next((r for r in rows if isinstance(r,dict) and r.get('unit')==name),None)
    if row is None:return None
    from . import missions,formation_parts
    unit=next(u for _,u in missions.units(world) if u['name']==name)
    return dict(version=LEGACY_VERSION,source=receipt['source'],turn=turn,calibration_proven=False,
        **{k:row[k] for k in ('noncombat_delta','noncombat_maximum','starved','remainder_submitted')},
        remainder=unit['formation'].get('partition_noncombat_remainder') if formation_parts.is_fragment(unit) else None,
        scope='旧每回合保障必要边界；非每小时率、气候或历史标定')


def validate_state(world):
    from . import missions
    cfg=configuration(world)
    if cfg is not None:
        spec=world['mission']['definition']
        validate_binding(cfg,spec.get('combined_rules'),spec.get('supply_distribution'))
    for _,u in missions.units(world):
        state=u.get('sustainment')
        if cfg is None:
            if state is not None:raise ValueError('未启用时间保障模型却提交保障状态')
            continue
        if (not isinstance(state,dict) or set(state)-{'version','shortage_hours','noncombat_remainder','last_receipt'}
                or not {'version','shortage_hours','noncombat_remainder'}<=set(state)
                or state['version']!=cfg['version']):raise ValueError('单位缺少有效时间保障状态')
        validate_food_loading(cfg,u)
        number(state['shortage_hours']);validate_remainder(u)


def demand(cfg,action,seconds,scale=1,*,personnel=None):
    if cfg['version']==PERSONNEL_VERSION:
        if personnel is None:raise ValueError('人员粮秣需求必须明确当前人数，不能回退编组数')
        number(personnel)
        rate=cfg['ration_kg_per_person_day']*personnel/24/cfg['food_kg_per_work']
    else:rate=cfg['food_work_per_hour']*scale
    return rate*seconds/3600*(cfg['move_factor'] if action=='move' else 1)


def expected(cfg,unit,action,seconds,*,moving_seconds=None,working_seconds=None,work_factor=1):
    """Reference equation for validation only; never commits losses or stock."""
    from . import formation_parts
    validate_config(cfg);number(seconds,0,31536000)
    state=unit['sustainment'];alive=unit['personnel']['current']>0
    deferred=validate_remainder(unit)
    # Legacy loading has no physical movement interval. An explicit interval
    # remains elapsed time even below one second; arrivals can split a tick.
    if deferred and seconds==.001 and moving_seconds is None and working_seconds is None:seconds=0
    if working_seconds is None and work_factor!=1:raise ValueError('劳动耗粮系数需要明确的实际工作时长')
    if working_seconds is not None:
        number(working_seconds,0,seconds);number(work_factor,1,10)
        moving=seconds if moving_seconds is None and action=='move'else (moving_seconds or 0)
        number(moving,0,seconds)
        if moving+working_seconds>seconds+1e-9:raise ValueError('行军与劳动时间不能重叠')
    if moving_seconds is not None:
        number(moving_seconds,0,seconds)
        if action!='move' and moving_seconds:raise ValueError('非机动命令不能声明行军耗粮时段')
        effective=seconds+(cfg['move_factor']-1)*moving_seconds
        work=unit_demand(cfg,unit,'hold',effective) if alive else 0
    else:work=unit_demand(cfg,unit,action,seconds) if alive else 0
    if working_seconds is not None:
        effective=seconds+(cfg['move_factor']-1)*moving+(work_factor-1)*working_seconds
        work=unit_demand(cfg,unit,'hold',effective)if alive else 0
    consumed=min(work,unit['logistics']['food']*formation_parts.scale(unit))
    hours=seconds/3600 if alive else 0
    unfed=hours*(1-consumed/work) if work else 0
    recovered=max(0,state['shortage_hours']-(hours-unfed)*cfg['recovery_hours_per_fed_hour'])
    debt=recovered+unfed
    exposure=max(0,debt-cfg['incapacity_after_hours'])-max(0,recovered-cfg['incapacity_after_hours'])
    load=state['noncombat_remainder']+max(0,exposure)*unit['personnel']['committed']*cfg['incapacity_fraction_per_hour']
    whole=math.floor(load+1e-9)
    if deferred and exposure<=0:whole=0
    return dict(zip(RECEIPT_FIELDS,(work,consumed,work-consumed,debt,max(0,load-whole),
                    min(100,debt*cfg['shortage_fatigue_per_hour']),min(unit['personnel']['current'],whole))))


def validate_receipt(cfg,prior,action,seconds,row):
    if not isinstance(row,dict) or set(row)!=set(RECEIPT_FIELDS):raise ValueError('时间保障回执字段缺失或未知')
    wanted=expected(cfg,prior,action,seconds)
    for key in RECEIPT_FIELDS:
        number(row[key])
        if not math.isclose(row[key],wanted[key],rel_tol=0,abs_tol=1e-6):
            raise ValueError('时间保障回执不一致：'+key)
    return row


def validate_model_transition(before,after,proposal,orders,seconds,*,scheduled=None):
    from . import missions
    cfg=configuration(before)
    if cfg is None:
        return validate_legacy_transition(before,after,proposal)
    if (not isinstance(proposal,dict) or set(proposal)!={'version','units'} or proposal['version']!=cfg['version']
            or not isinstance(proposal['units'],list)):raise ValueError('DSH必须提交时间保障sustainment_ledger')
    old={u['name']:u for _,u in missions.units(before)};new={u['name']:u for _,u in missions.units(after)}
    rows=proposal['units']
    if (len(rows)!=len(old) or any(not isinstance(r,dict) or set(r)!={'unit',*RECEIPT_FIELDS} or not isinstance(r['unit'],str) for r in rows)
            or {r['unit'] for r in rows}!=set(old)):raise ValueError('时间保障回执必须覆盖全部单位且不重复')
    actions={o['unit']:o['action'] for o in orders}
    for row in rows:
        name=row['unit'];receipt={k:row[k] for k in RECEIPT_FIELDS}
        if scheduled is None:
            validate_receipt(cfg,old[name],actions.get(name,'hold'),seconds,receipt)
        else:
            for key,value in receipt.items():
                number(value)
                if not math.isclose(value,scheduled[name]['nutrition'][key],rel_tol=0,abs_tol=1e-6):
                    raise ValueError('定时补给与时间保障回执不符：'+key)
        state=new[name].get('sustainment',{})
        if any(not math.isclose(state.get(k,-1),receipt[k],abs_tol=1e-6,rel_tol=0) for k in ('shortage_hours','noncombat_remainder')):
            raise ValueError('DSH保障状态与回执不一致')
        if new[name]['personnel']['noncombat_losses']-old[name]['personnel']['noncombat_losses']!=receipt['noncombat_delta']:
            raise ValueError('DSH非战斗减员与时间保障回执不一致')
        if new[name]['formation']['fatigue']+1e-6<math.floor(receipt['fatigue_floor']):
            raise ValueError('DSH疲劳低于缺粮累积约束')


def deferred_instruction(world):
    from . import missions
    units=[u['name'] for _,u in missions.units(world) if deferred_support(u)]
    if not units:return ''
    import json
    return ('\n正式重编保障余量策略'+DEFERRED_SUPPORT_POLICY+'适用单位='+json.dumps(units,ensure_ascii=False)+'。'
        '这些单位的noncombat_remainder可因合并合法大于等于1，是唯一的既有估计负荷，不是新增阵亡。'
        '仅在至少1秒的物理时段内出现新的有效失能暴露（exposure>0）时，才按累计负荷取整并扣可用人数；'
        '满粮、无新暴露、无人或0.001秒装载探针均令whole=0，保留原待结算余量，不得借合并或经过时间制造减员。'
        '每段结算后只带剩余负荷，后续同秒settlement不得重复消耗；不得改写runtime_allocation来源策略。')


def instruction(world,seconds):
    import json
    cfg=configuration(world)
    if cfg is None:
        from . import missions,formation_parts
        inputs=[dict(unit=u['name'],per_turn_allowance=legacy_allowance(u),
            prior_remainder=u['formation'].get('partition_noncombat_remainder',0),if_food_ends_zero=legacy_quote(u,0))
            for _,u in missions.units(world) if formation_parts.is_fragment(u)]
        return ('\n旧模型非战斗约束：期末food>0时本轮新增noncombat_losses必须0；food=0时上限为min(可用人数,floor(2×resource_scale+旧余量+1e-9))。'
            '这是旧每回合预算，不是每小时率，不是冻伤或疾病史实。不得用非战斗分类规避战斗效能校验。'
            '分队粮食归零时，余量按上述负荷减floor(负荷+1e-9)并以12位小数保留，若发生变化须显式提交'
            'sustainment_ledger={"version":"'+LEGACY_VERSION+'","units":[{"unit":"粮食归零分队精确名","noncombat_remainder":0.5}]}，'
            '每行仅有unit和noncombat_remainder两字段；noncombat_losses是人员累计损失，不能放进此回执。'
            '准确覆盖所有粮食归零分队。没有新余量则可省略；不能在formation中直接提交partition_noncombat_remainder。'
            '余量是潜在失能负荷的小数，不强制按上限减员；已知粮弹账、人员变化和分队份额仍须守恒。条件预算='+json.dumps(inputs,ensure_ascii=False))
    formula=('需求=轮初可用人数×ration_kg_per_person_day×小时数/24/food_kg_per_work，不再乘编组份额；'
        'food质量=food×编组份额×food_kg_per_work（kg），这是现有库存的唯一质量编码，不另写food_kg。'
        '容量=初始committed×carried_kg_per_committed_person/food_kg_per_work/份额；战损后原库存与冻结容量不自动消失。'
        '每段按段初人数计需求，战斗减员影响下一回合需求；不是逐人实时进食模型。' if cfg['version']==PERSONNEL_VERSION else
        '粮食为归一化工作量：需求=food_work_per_hour×小时数×编组份额；')
    return ('\n启用时间保障模型 '+json.dumps(cfg,ensure_ascii=False)+'。本轮秒数='+str(seconds)+'。'+formula+
        'move另乘move_factor；消耗=min(需求,轮初food×份额)。轮末delivery不能回溯支付本轮缺粮。'
        '未供粮时长=小时数×(1-消耗/需求)，已供粮时长=小时数-未供粮时长；先耗随队粮再短缺，缺粮债=max(0,旧shortage_hours-已供粮时长×recovery_hours_per_fed_hour)+未供粮时长。'
        '供粮后债=max(0,旧债-已供粮时长×recovery_hours_per_fed_hour)；暴露增量=max(0,新债-incapacity_after_hours)-max(0,供粮后债-incapacity_after_hours)；失能负荷=旧noncombat_remainder+暴露增量×初始committed×incapacity_fraction_per_hour；非战斗新增=min(可用人数,floor(负荷+1e-9))，余量=max(0,负荷-floor(负荷+1e-9))。'
        '疲劳不低于floor(min(100,新债×shortage_fatigue_per_hour))。这是估计的非战斗失能，不记为阵亡；本版未另建气候疾病模型。无可用人员时需求、经过小时均为0，保留债和余量。'
        'unit_updates逐单位提交sustainment={version,shortage_hours,noncombat_remainder}及相符人员、库存和疲劳变化；另提交sustainment_ledger={version:"'+cfg['version']+'",units:[{unit,...字段}]}，逐单位字段为'+','.join(RECEIPT_FIELDS)+
        '；unmet=需求-消耗。没有回执或不守恒即拒收，不由应用补写结果。'+deferred_instruction(world))
