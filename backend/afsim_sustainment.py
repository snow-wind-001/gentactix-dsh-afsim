"""Native WSF time-based sustenance and strictly checked return receipts."""
import copy
import math
from gentactix import support_dynamics as sd, formation_parts
from .afsim_literals import number as n


def finish(cfg,u,action,seconds,i,identity,p,*,food_delivery=None,continuous=False):
    food_delivery=food_delivery or f'delivery{i}'
    scale=formation_parts.scale(u);s=u['sustainment'];alive=u['personnel']['current']>0
    if continuous:
        values=[f'GtxCNGet({p},"{k}")' for k in ('need','used','unmet','debt','remainder','floor','nc')]
        return [f' double foodUsed{i}=GtxCNGet({p},"used"); double noncombat{i}=GtxCNGet({p},"nc");',
            f' double food{i}=(GtxCNGet({p},"food")+{food_delivery})/{n(scale)};',
            f' writeln("GTXNUTRITION|{identity}|",'+',"|",'.join(f'Format.Fixed({v},12)' for v in values)+');']
    deferred=sd.deferred_support(u)
    if deferred and seconds==.001:seconds=0
    work=sd.unit_demand(cfg,u,action,seconds) if alive else 0
    hours=seconds/3600 if alive else 0
    lines=[f' double foodNeed{i}={n(work)};',
        f' double foodUsed{i}=Math.Min(foodNeed{i},{n(u["logistics"]["food"]*scale)});',
        f' double unfed{i}=0; if (foodNeed{i}>0) {{ unfed{i}={n(hours)}*(1-foodUsed{i}/foodNeed{i}); }}',
        f' double foodRecovered{i}=Math.Max(0,{n(s["shortage_hours"])}-({n(hours)}-unfed{i})*{n(cfg["recovery_hours_per_fed_hour"])});',
        f' double foodDebt{i}=foodRecovered{i}+unfed{i};',
        f' double foodExposure{i}=Math.Max(0,foodDebt{i}-{n(cfg["incapacity_after_hours"])})-Math.Max(0,foodRecovered{i}-{n(cfg["incapacity_after_hours"])});',
        f' double foodLoad{i}={n(s["noncombat_remainder"])}+foodExposure{i}*{u["personnel"]["committed"]}*{n(cfg["incapacity_fraction_per_hour"])};',
        f' double foodWhole{i}=Math.Floor(foodLoad{i}+0.000000001);',
        *([f' if (foodExposure{i}<=0) {{ foodWhole{i}=0; }}'] if deferred else []),
        f' double foodCarry{i}=Math.Max(0,foodLoad{i}-foodWhole{i});',
        f' double noncombat{i}=Math.Min({u["personnel"]["current"]},foodWhole{i});',
        f' double foodFloor{i}=Math.Min(100,foodDebt{i}*{n(cfg["shortage_fatigue_per_hour"])});',
        f' {p}.SetAuxData("ca_fatigue",Math.Max({p}.AuxDataDouble("ca_fatigue"),Math.Floor(foodFloor{i})));',
        f' double food{i}=({n(u["logistics"]["food"]*scale)}-foodUsed{i}+{food_delivery})/{n(scale)};']
    vals=[f'foodNeed{i}',f'foodUsed{i}',f'foodNeed{i}-foodUsed{i}',f'foodDebt{i}',f'foodCarry{i}',f'foodFloor{i}',f'noncombat{i}']
    lines.append(f' writeln("GTXNUTRITION|{identity}|",'+',"|",'.join(f'Format.Fixed({v},12)' for v in vals)+');')
    return lines


def parse(text,model,scene,*,scheduled=None):
    cfg=model.get('support_dynamics');rows={}
    for line in text.splitlines():
        if not line.startswith('GTXNUTRITION|'):continue
        parts=line.split('|')
        if not cfg or len(parts)!=len(sd.RECEIPT_FIELDS)+2 or parts[1] not in scene['entities'] or parts[1] in rows:
            raise ValueError('时间保障原生回执重复、未知或缺项')
        rows[parts[1]]=dict(zip(sd.RECEIPT_FIELDS,map(float,parts[2:])))
    if cfg:
        if set(rows)!=set(scene['entities']):raise ValueError('缺少时间保障原生回执')
        if model.get('continuous_motion',{}).get('nutrition_revision'):
            from . import afsim_motion_nutrition
            intervals=({identity:scheduled[e['name']]['nutrition'] for identity,e in scene['entities'].items()}
                if model['continuous_motion'].get('nutrition_schedule_revision') and scheduled is not None
                else afsim_motion_nutrition.parse(text,model['continuous_motion']))
            for identity,row in rows.items():
                for key,value in row.items():
                    if not math.isclose(value,intervals[identity][key],rel_tol=0,abs_tol=1e-6):
                        raise ValueError('分时营养与最终保障回执不一致：'+key)
            return intervals
        old={u['name']:u for _,u in model['units']};actions={o['unit']:o['action'] for o in model['orders']}
        for identity,row in rows.items():
            name=scene['entities'][identity]['name']
            if scheduled is None:
                sd.validate_receipt(cfg,old[name],actions.get(name,'hold'),scene['seconds'],row)
            else:
                wanted=scheduled[name]['nutrition']
                for key,value in row.items():
                    sd.number(value)
                    if not math.isclose(value,wanted[key],rel_tol=0,abs_tol=1e-6):
                        raise ValueError('定时补给与原生时间保障回执不符：'+key)
    return rows


def apply(after,data,scene,model,accounts):
    if not model.get('support_dynamics'):return
    old={u['name']:u for _,u in model['units']}
    for u in after['red_units']+after['blue_units']:
        identity=next(k for k,e in scene['entities'].items() if e['name']==u['name']);row=data[identity]
        account=accounts[identity];prior=old[u['name']]
        food=prior['logistics']['food']+(account.get('food_received',account['delivery'])-row['consumed'])/formation_parts.scale(prior)
        if (not math.isclose(account['food_spent'],row['consumed'],rel_tol=0,abs_tol=1e-6)
                or not math.isclose(u['logistics']['food'],food,rel_tol=0,abs_tol=1e-6)):
            raise ValueError('原生粮秣账与时间保障回执不一致')
        if u['personnel']['noncombat_losses']-old[u['name']]['personnel']['noncombat_losses']!=row['noncombat_delta']:
            raise ValueError('原生人员账与时间保障回执不一致')
        if u['formation']['fatigue']+1e-6<int(row['fatigue_floor']):raise ValueError('原生疲劳低于缺粮约束')
        u['sustainment']={'version':model['support_dynamics']['version'],**{k:row[k] for k in ('shortage_hours','noncombat_remainder')},
            'last_receipt':{**copy.deepcopy(row),'source':'afsim_native_estimate','turn':model['expected_turn']}}
