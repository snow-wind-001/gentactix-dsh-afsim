"""Bounded ledger reduction of committed changes; never runs a simulation."""
import math
from gentactix import combat_effects


METRICS = {
    'personnel': ('committed','current','casualties','noncombat_losses','killed','wounded',
                  'captured','missing','unclassified_casualties'),
    'logistics': ('food','ammo'),
    'formation': ('shells','aa_rounds','fuel_liters','spares','materials'),
}
EQUIPMENT = ('committed','operational','damaged','destroyed')
TOTALS = ('fire_cycles','active_fire_s','shots','small_arms_rounds_estimate',
          'received_shells','received_aa_rounds','received_fuel_liters','received_spares',
          'received_materials','distance_milli','repaired','aa_spent','delivery_tons_milli',
          'ground_damage','ground_equipment')
WORKLOAD=('delivery','food_received','ammo_received','food_spent','ammo_spent')
DELIVERY_BASES=('native_gross_receipt','declared_gross_estimate',
                'native_mass_equivalent_split_stock','declared_mass_equivalent_split_stock')


def _number(value):
    return value if type(value) in (int,float) and math.isfinite(value) else None


def _metric(row,name,before,after):
    a,b=_number(before),_number(after)
    if name not in row['metrics']:
        row['metrics'][name]={'before':a,'after':b,'net_change':None,
            'unknown_endpoint_changes':int(a is None or b is None),'recorded_sequence_continuous':True}
    else:
        m=row['metrics'][name]
        if m['after'] is None or a is None or m['after']!=a:
            m['recorded_sequence_continuous']=False
        m['after']=b
        m['unknown_endpoint_changes']+=int(a is None or b is None)


def _counter(counts,value,limit):
    # Bound both string length and cardinality even for old/untrusted records.
    label=str(value)[:96] if value is not None else 'unknown'
    if label not in counts and len(counts)>=limit:label='other'
    counts[label]=counts.get(label,0)+1


def summarize(records,query,offset,limit):
    ordered=sorted(records,key=lambda r:r['turn'])
    turns=[r['turn'] for r in ordered]
    if len(turns)!=len(set(turns)):
        raise ValueError('聚合范围有重复轮次，不能重复累加；请读取变化明细核对')
    groups={};duration=0;duration_count=0;total_changes=0
    for record in ordered:
        turn=record['turn'];clock=record.get('clock') or {}
        world=record.get('after') or {};mission=world.get('mission') or {};ledger={}
        if type(mission.get('turn')) is int and mission['turn']==turn:
            for item in mission.get('ledger',[]):
                if not isinstance(item,dict) or not isinstance(item.get('unit'),str):
                    raise ValueError('聚合资源账缺少单位名称，请读取明细核对')
                if item['unit'] in ledger:raise ValueError('同一轮资源账有重复单位，不能重复累加')
                ledger[item['unit']]=item
        minutes=_number(clock.get('actual_minutes'))
        if clock.get('status')=='verified' and minutes is not None and minutes>=0:
            duration+=minutes*60;duration_count+=1
        seen=set()
        for change in record.get('changes',[]):
            name=change.get('name');team=change.get('team')
            if not isinstance(name,str) or not isinstance(team,str):
                raise ValueError('聚合变化缺少方别或名称，请读取明细核对')
            key=(team,name)
            if key in seen:raise ValueError('同一轮有重复的同方同名变化，不能重复累加；请读取明细核对')
            seen.add(key);total_changes+=1
            if key not in groups:
                groups[key]={'team':team[:32],'name':name[:160],
                    **({'name_truncated':True} if len(name)>160 else {}),
                    'first_change_turn':turn,'last_change_turn':turn,'change_count':0,'metrics':{},
                    'logistics_workload':{'missing_or_stale_ledgers':0,'source_counts':{},'basis_counts':{},'totals':{
                        field:{'known_sum':None,'known_receipts':0,'missing_receipts':0} for field in WORKLOAD}},
                    'execution':{'valid_receipts':0,'missing_or_stale_receipts':0,'action_counts':{},
                        'source_counts':{},'blocked_counts':{},'fire_stop_counts':{},'totals':{
                            field:{'known_sum':None,'known_receipts':0,'missing_receipts':0} for field in (*TOTALS,'artillery_shells_fired')}}}
            row=groups[key];row['last_change_turn']=turn;row['change_count']+=1
            work=row['logistics_workload'];item=ledger.get(name)
            if item is None:work['missing_or_stale_ledgers']+=1
            else:
                source=item.get('source')
                basis=item.get('delivery_basis')
                if basis is None:
                    native_source=(world.get('afsim') or {}).get('effects_source')
                    legacy_native=native_source=='afsim-native-teaching-1'
                    basis='legacy_net_estimate' if source=='dsh_model_estimate' else 'native_gross_receipt' if legacy_native else 'unknown'
                    if source is None and legacy_native:source=native_source
                _counter(work['source_counts'],source,8);_counter(work['basis_counts'],basis,8)
                for field in WORKLOAD:
                    value=_number(item.get(field))
                    if value is None or value<0 or field in ('delivery','food_received','ammo_received') and basis not in DELIVERY_BASES:continue
                    total=work['totals'][field]
                    total['known_sum']=(total['known_sum'] or 0)+value;total['known_receipts']+=1
            fields=change.get('fields') or {}
            for family,keys in METRICS.items():
                delta=fields.get(family) or {}
                a=delta.get('before') or {};b=delta.get('after') or {}
                if not isinstance(a,dict) or not isinstance(b,dict):continue
                for field in keys:
                    if field in a or field in b:_metric(row,family+'.'+field,a.get(field),b.get(field))
            equipment=fields.get('equipment') or {}
            sides=[]
            for side in ('before','after'):
                values=equipment.get(side) or []
                if not isinstance(values,list):raise ValueError('装备变化结构非法，请读取明细核对')
                by_category={}
                for e in values:
                    if not isinstance(e,dict):
                        raise ValueError('装备变化缺少分类，请读取明细核对')
                    category=e.get('category')
                    if category is None and isinstance(e.get('name'),str):category='unclassified:'+e['name']
                    if not isinstance(category,str):raise ValueError('装备变化缺少分类，请读取明细核对')
                    if category in by_category:raise ValueError('装备变化有重复分类，请读取明细核对')
                    by_category[category]=e
                sides.append(by_category)
            categories=set(sides[0])|set(sides[1])
            if len(categories)>8 or any(len(c)>64 for c in categories):
                raise ValueError('装备分类超过聚合范围，请读取明细核对')
            for category in sorted(categories):
                a,b=(side.get(category,{}) for side in sides)
                for field in EQUIPMENT:
                    if field in a or field in b:
                        _metric(row,'equipment.'+category+'.'+field,a.get(field),b.get(field))
            after=(fields.get('formation') or {}).get('after') or {}
            receipt=after.get('last_execution') if isinstance(after,dict) else None
            execution=row['execution']
            if not isinstance(receipt,dict) or type(receipt.get('turn')) is not int or receipt['turn']!=turn:
                execution['missing_or_stale_receipts']+=1;continue
            execution['valid_receipts']+=1
            _counter(execution['action_counts'],receipt.get('action'),24)
            _counter(execution['source_counts'],receipt.get('source'),8)
            for field,target in (('blocked','blocked_counts'),('fire_stop_reason','fire_stop_counts')):
                value=_number(receipt.get(field))
                _counter(execution[target],value,24)
            for field in TOTALS:
                value=_number(receipt.get(field))
                if value is None or value<0:continue
                total=execution['totals'][field]
                total['known_sum']=(total['known_sum'] or 0)+value;total['known_receipts']+=1
            raw_shots=_number(receipt.get('shots'));action=receipt.get('action')
            if raw_shots is not None and raw_shots>=0 and (raw_shots==0 or action in ('fire','bombard','suppress')):
                value=raw_shots if action in ('bombard','suppress') else 0
                total=execution['totals']['artillery_shells_fired']
                total['known_sum']=(total['known_sum'] or 0)+value;total['known_receipts']+=1
    for row in groups.values():
        for metric in row['metrics'].values():
            if metric['before'] is not None and metric['after'] is not None:
                metric['net_change']=metric['after']-metric['before']
        for total in row['execution']['totals'].values():
            total['missing_receipts']=row['change_count']-total['known_receipts']
        for total in row['logistics_workload']['totals'].values():
            total['missing_receipts']=row['change_count']-total['known_receipts']
    rows=list(groups.values());requested=query['through_turn']-query['since_turn']
    return {'mode':'aggregate','units':rows[offset:offset+limit],'total_units':len(rows),
        'fire_stop_reasons':{str(k):v for k,v in combat_effects.FIRE_STOPS.items()},
        'total_changes':total_changes,'coverage':{'requested_turns':requested,'recorded_turns':len(turns),
            'all_requested_turns_recorded':requested==len(turns),
            'missing_turn_count':requested-len(turns),'known_duration_seconds':duration if duration_count else None,
            'known_duration_turns':duration_count,'unknown_duration_turns':len(turns)-duration_count},
        'summary_semantics':
            '按已提交轨迹的方别+名称分组，只列发生过变化的单位，不是完整登记名单；每页最多16单位。'
            'since_turn为排除下界、through_turn为包含上界；例如since_turn=1不统计第1轮。全局累计须自since_turn=0读取，window.full_session=false的求和只属于局部窗口。'
            'full_session仅表示查询范围；coverage.all_requested_turns_recorded=false时，known_sum是已记录轮次小计，不能声称完整累计。每字段仍须检查missing_receipts，不补缺轮。'
            'metrics.before/after是该字段首/末变化的已知端点，net_change仅为端点差，不是消耗或因果贡献；null保持未知。'
            '装备可用、待修和毁损分账，维修不算新增毁损；unclassified:名称保留旧未分类装备，不猜兵器类别。缺轮次及字段端点不连续分别标记。'
            'execution.totals.known_sum仅累计对应轮有效回执的已知值，missing_receipts是本单位变化记录中缺载数，不补0。'
            'logistics_workload单列已提交每轮资源账的delivery毛到货与food_spent/ammo_spent消耗，保留来源/口径和缺账数；旧DSH净增加量不累计为毛到货，不能按当前一轮费用乘轮数替代全程账。'
            'split_stock口径的delivery是运输质量当量，粮食与弹药到货分别读取food_received/ammo_received；不能把质量当量当作任一类到货。旧包回执未记录分类字段时保持缺载，不补造。'
            'active_fire_s是本单位自身有效火力秒数，不是目标承受火力时长；跨单位相加不能当作战役历时。'
            'fire_stop_counts须结合fire_stop_reasons读取后台模型停止条件；未列代码保持未知，不猜含义。'
            'shots是原始混合计数：fire记周期、bombard/suppress记炮弹，不能当作总弹数。artillery_shells_fired仅统计间瞄炮弹，直射尝试看small_arms_rounds_estimate；received_*是轮末到货，不能用净库存变化代替。'
            'distance_milli是毫米，delivery_tons_milli是千分之一吨。'
            'coverage时长仅取verified程序时钟；聚合不是反事实或因果证明。要核对逐轮依据，请用mode=changes及同一时间范围分页。'}
