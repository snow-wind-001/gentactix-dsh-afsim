"""Historical loss references and validated native firing inputs, not an executor."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
COMBAT_REVISION = 2
ACCOUNTING_VERSION = 'classified-indirect-1'
CLASSIFIED_PROFILE = 'aggregate-fire-cycles-2.4'
CLASSIFIED_REVISION = 3
DENSITY_VERSION = 'live-footprint-density-1'
DYNAMIC_PROFILE = 'aggregate-fire-cycles-2.5'
DYNAMIC_REVISION = 4
CONTINUOUS_DENSITY_VERSION = 'live-footprint-density-2'
CONTINUOUS_PROFILE = 'aggregate-fire-cycles-2.6'
CONTINUOUS_REVISION = 5
PROFILE = {
    'version': 'aggregate-fire-cycles-2.3', 'combat_revision': COMBAT_REVISION,
    'direct_cycle_s': 120, 'artillery_cycle_s': 120, 'ammo_per_cycle': 1,
    'fatality_share': .25,
    'direct_fire': {'engaged_fraction':.15,'rounds_per_min':6,'hit_probability':.01,
                    'reference_range_m':300,'range_min_factor':.25,'range_max_factor':4},
    'equipment_casualty_multipliers': {'armor':.5,'artillery':1.5,'air_defense':1.2,'engineer':.75,'transport':2.0},
    'scope': '持续火力与守恒模型；周期和死伤比例为显式建模先验，非逐兵器或逐战役实测标定',
    'assumptions': [
        '每120秒代表一次分队火力周期；炮弹逐发计数、工作量与库存共同限制，通信延迟后才执行。',
        '步兵直射以投入人数×前沿射手比例0.15×每分钟6发×周期时间估计射击尝试，基础有效概率0.01；300米为距离参照，修正限0.25—4，均为待标定先验，不是历史武器实测。',
        '直射按瞄准射击估计，不再按目标总人数/3000二次缩小；掩护、展开、射程、压制和情报仍约束效果。小武器发射量是估计，库存仍按弹药工作量约束，未建立逐口径实弹账。',
        '压制恢复和情报时效按原生时间连续更新；重新下令仍有通信等待，改变回合步长不应重置交火效能。',
        '阵亡比例0.25是伤亡分类假设，不是本场战役已知分项；其余新伤亡为负伤，既有未分类损失不改写。',
        '装备按可用数量、人员损失比例与分类易损系数估计；系数是聚合假设，未模拟穿甲弹道或历史分项损失。',
        '只在有效射程、资源足够且部队仍可用时积累效果；总历时不等于全程交火时间。',
        '历史战役总量只作范围和量级参照，不换算成每回合必扣人数，也不混用阵亡、伤亡与毙伤俘。'],
    'sources': [
        {'title':'FM 8-55 (1994), 3-10', 'url':'https://www.globalsecurity.org/military/library/policy/army/fm/8-55/fm8-55.pdf',
         'scope':'美国陆军原文镜像；层级、接敌比例、火力、机动、地形对伤亡率的影响，不提供本模型120秒或0.25参数'},
        {'title':'台儿庄作战炮弹消耗叙述', 'url':'https://www.yantian.gov.cn/ytdayszxxw/lsjt/content/post_11737199.html',
         'scope':'盐田区档案馆公开叙述：3月24—28日前后日军每日约一二千至六七千发；战场累计，不能套给每个单位'},
        {'title':'台儿庄，红血洗过的战场', 'url':'https://cpc.people.com.cn/BIG5/n1/2018/1219/c421684-30476925.html',
         'scope':'新华社2018年报道：第31师原8000余、死伤近3000；具体阶段窗口未充分限定，不是逐小时伤亡标准'}]
}
COUNT_FIELDS = ('killed','wounded','missing','captured','unclassified_casualties')
FIRE_STOPS = {0:'未因约束停止',4:'目标超出武器射程',5:'目标低于最小射程',
              6:'炮弹不足',8:'弹药工作量不足',9:'目标已失能',11:'登记地形遮挡直射'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def benchmark(battle):
    for folder in ('anti_japanese_war','long_march'):
        data = json.loads((ROOT/'data'/folder/'scenarios.json').read_text())
        row = next((r for r in data['scenarios'] if r['name'] == battle), None)
        if row is None: continue
        sources = json.loads((ROOT/'data'/folder/'sources.json').read_text())['sources']
        figures = []
        for item in row['figures']:
            if not re.search('伤亡|阵亡|牺牲|捐躯|减员|死伤|毙|俘|歼敌|歼灭|失踪|损失|遇难|战前兵力|战后兵力|出发兵力|参战人数',item['metric']): continue
            value = copy.deepcopy(item)
            value['sources'] = [{**copy.deepcopy(sources[s]), 'id':s} for s in item['sources'] if s in sources]
            figures.append(value)
        return {'battle':battle,'status':'published_references' if figures else 'unknown',
                'scope':row['scope'],'figures':figures,'force_historical_outcome':False,
                'limitations':'各行统计范围和争议分别保留；不能把战后减战前当成阵亡，也不把战果报告当对方自报。'}
    path = ROOT/'corpus'/(battle+'.md')
    if path.is_file():
        text = path.read_text(); section = re.search(r'## (?:伤亡[^\n]*|战果[^\n]*)\n(.*?)(?=\n## |\Z)',text,re.S)
        links = [{'title':title,'url':url,'scope':'本地史料卡所引公开资料，具体口径见原段落'}
                 for title,url in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)',text)]
        figures = [{'side':'见原文','metric':'史料伤亡／减员叙述','value':None,'scope':battle,
                    'note':section[1][:2500] if section else '未取得同窗口伤亡分项；保持未知',
                    'sources':links[:8], 'evidence_status':'published_reference_with_scope_limits'}]
        return {'battle':battle,'status':'narrative_reference','scope':'不自动拆解缺载人数或合并统计范围',
                'figures':figures,'force_historical_outcome':False}
    return {'battle':battle,'status':'unknown','scope':'缺同窗口统计','figures':[], 'force_historical_outcome':False}


def validate_accounting(value):
    if (not isinstance(value,dict) or set(value)!={'version','assumption'}
            or value['version']!=ACCOUNTING_VERSION or not isinstance(value['assumption'],str)
            or not value['assumption'].strip() or len(value['assumption'])>4000):
        raise ValueError('分类炮弹计量配置须声明classified-indirect-1及明确的估计依据')
    return True


def work_cost(profile, action):
    """One frozen action-cost interpretation for gates, WSF and model ledgers."""
    if action not in ('fire','bombard','suppress'):raise ValueError('弹耗成本须指定地面射击动作')
    if profile.get('version') in (CLASSIFIED_PROFILE,DYNAMIC_PROFILE,CONTINUOUS_PROFILE) and 'fire_accounting' in profile:
        validate_accounting(profile.get('fire_accounting'))
        if action in ('bombard','suppress'):return 0
    return profile['ammo_per_cycle']


def validate_dynamics(value):
    if (not isinstance(value,dict) or set(value)!={'version','assumption'}
            or value['version']not in (DENSITY_VERSION,CONTINUOUS_DENSITY_VERSION) or not isinstance(value['assumption'],str)
            or not value['assumption'].strip() or len(value['assumption'])>4000):
        raise ValueError('动态密度火力过程须声明live-footprint-density-1/2及明确的估计依据')
    return True


def validate_profile(profile):
    optional={'equipment_casualty_multipliers','direct_fire','fire_accounting','fire_dynamics','damage_quantum','suppression_state'}
    required = set(PROFILE)-optional|{'benchmark','definition_hash'}
    classified=isinstance(profile,dict) and profile.get('version')==CLASSIFIED_PROFILE
    carried=isinstance(profile,dict) and profile.get('version')==CONTINUOUS_PROFILE
    dynamic=isinstance(profile,dict) and profile.get('version')in (DYNAMIC_PROFILE,CONTINUOUS_PROFILE)
    if (not isinstance(profile,dict) or set(profile)-required-optional or required-set(profile)
            or profile.get('combat_revision')!=(CONTINUOUS_REVISION if carried else DYNAMIC_REVISION if dynamic else CLASSIFIED_REVISION if classified else COMBAT_REVISION)
            or dynamic!=('fire_dynamics' in profile)
            or not dynamic and classified!=('fire_accounting' in profile)):
        raise ValueError('火力参照版本或结构非法')
    if 'fire_accounting' in profile:validate_accounting(profile['fire_accounting'])
    if dynamic:validate_dynamics(profile['fire_dynamics'])
    if carried!=('suppression_state' in profile):raise ValueError('连续压制组件与火力版本不一致')
    if dynamic and carried!=(profile['fire_dynamics']['version']==CONTINUOUS_DENSITY_VERSION):raise ValueError('动态密度选择与冻结火力版本不一致')
    if carried:
        from . import suppression_state
        suppression_state.validate_config(profile['suppression_state'])
    if 'damage_quantum'in profile and (not dynamic or type(profile['damage_quantum'])not in (int,float)or profile['damage_quantum']!=.000001):
        raise ValueError('整数毁伤载荷精度须为动态密度模型的1e-6人员单位')
    if profile.get('version') in ('aggregate-fire-cycles-2.3',CLASSIFIED_PROFILE,DYNAMIC_PROFILE,CONTINUOUS_PROFILE) and 'direct_fire' not in profile:raise ValueError('直射模型缺少射手与距离先验')
    if 'direct_fire' in profile:
        values=profile['direct_fire']
        if (not isinstance(values,dict) or set(values)!=set(PROFILE['direct_fire']) or
                any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values.values()) or
                not values['engaged_fraction']<=1 or not values['hit_probability']<=1 or
                not values['rounds_per_min']<=100 or not values['reference_range_m']<=10000 or
                not values['range_min_factor']<=values['range_max_factor']<=10):
            raise ValueError('射手、射速、有效概率或距离先验非法')
    if 'equipment_casualty_multipliers' in profile:
        values=profile['equipment_casualty_multipliers']
        if not isinstance(values,dict) or set(values)!=set(PROFILE['equipment_casualty_multipliers']) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=10 for v in values.values()):
            raise ValueError('分类装备损失比例先验非法')
    for key in ('direct_cycle_s','artillery_cycle_s'):
        if type(profile[key]) is not int or not 10 <= profile[key] <= 3600: raise ValueError('火力周期非法')
    if (type(profile['ammo_per_cycle']) not in (int,float) or not math.isfinite(profile['ammo_per_cycle'])
            or not 0 < profile['ammo_per_cycle'] <= 100): raise ValueError('弹药工作量非法')
    if type(profile['fatality_share']) not in (int,float) or not 0 <= profile['fatality_share'] <= 1:
        raise ValueError('死伤分类先验非法')
    if digest({k:v for k,v in profile.items() if k!='definition_hash'}) != profile['definition_hash']:
        raise ValueError('火力参照快照被改写')
    return True


def _accounting_profile(value, accounting, dynamics=None):
    value=copy.deepcopy(value)
    was_dynamic='fire_dynamics'in value
    if accounting:
        validate_accounting(accounting)
        value.update(version=CLASSIFIED_PROFILE,combat_revision=CLASSIFIED_REVISION,
                     fire_accounting=copy.deepcopy(accounting))
        value['assumptions'][0]='直射消耗通用轻武器弹药工作量；炮击／压制仅扣分类炮弹，不额外扣直射工作量。人员、火炮、时间与目标仍约束开火。'
    else:
        value.update(version=PROFILE['version'],combat_revision=COMBAT_REVISION)
        value.pop('fire_accounting',None)
        value['assumptions'][0]=PROFILE['assumptions'][0]
    value['assumptions']=[s for s in value['assumptions']if not s.startswith('classified-indirect-1是显式聚合计量假设')]
    if accounting:value['assumptions'].append('classified-indirect-1是显式聚合计量假设，不是口径、炮班操作或历史弹耗标定；分类炮弹质量按既有物资账另核。')
    value.pop('fire_dynamics',None)
    value.pop('suppression_state',None)
    value['assumptions']=[s for s in value['assumptions']if not s.startswith('fixed-time-suppression-1：')]
    value['assumptions']=[s for s in value['assumptions']if not s.startswith(DENSITY_VERSION+'：')]
    if dynamics:
        validate_dynamics(dynamics)
        value.update(version=DYNAMIC_PROFILE,combat_revision=DYNAMIC_REVISION,fire_dynamics=copy.deepcopy(dynamics))
        if dynamics['version']==CONTINUOUS_DENSITY_VERSION:
            from . import suppression_state
            value.update(version=CONTINUOUS_PROFILE,combat_revision=CONTINUOUS_REVISION,
                         suppression_state=copy.deepcopy(suppression_state.CONFIG))
            value['assumptions'].append('fixed-time-suppression-1：压制每次来袭量化到1e-6点，按1ms时钟衰减并携带整数余量；轮末补足未采样时段。不是完整机动、装备或保障时间收敛认证。')
        value['assumptions'].append(DENSITY_VERSION+'：同批射击前以现存人员更新同根、同坐标格及同展开面积的共享密度；坐标格为floor(度×10^6+0.5)，不是区域重叠或溅射。无新增伤亡系数，历史效能与完整时间收敛仍需验证。')
        if not was_dynamic:
            value['damage_quantum']=.000001
            value['assumptions'].append('integer-damage-load-1：每次地面毁伤按1e-6人员单位四舍五入为整数微量，再累计和携带；不是每轮截断浮点余量。参数冻结在本快照，旧无此字段的动态快照继续按原浮点解释。')
    else:
        value.pop('damage_quantum',None)
        value['assumptions']=[s for s in value['assumptions']if not s.startswith('integer-damage-load-1：')]
    return value


def configuration_reference(world, previous):
    """Explicit new-draft selection; preserve other frozen physical parameters."""
    if world['mission']['turn']!=0 or world.get('afsim')or world.get('dsh_execution'):
        raise ValueError('弹药计量只能在新建未执行配置中选择；不能迁移已运行战局')
    validate_profile(previous)
    spec=world['mission']['definition'];accounting=spec.get('fire_accounting')
    dynamics=spec.get('fire_dynamics')
    if 'fire_accounting'in spec:validate_accounting(accounting)
    if 'fire_dynamics'in spec:validate_dynamics(dynamics)
    if previous.get('fire_accounting')==accounting and previous.get('fire_dynamics')==dynamics:return copy.deepcopy(previous)
    value=_accounting_profile(previous,accounting,dynamics)
    value.pop('definition_hash')
    value['definition_hash']=digest(value)
    validate_profile(value)
    return value


def reference(world):
    spec=world.get('mission',{}).get('definition',{})
    accounting=spec.get('fire_accounting')
    dynamics=spec.get('fire_dynamics')
    if 'fire_accounting' in spec:validate_accounting(accounting)
    if 'fire_dynamics' in spec:validate_dynamics(dynamics)
    frozen = world.get('combat_reference') or world.get('afsim',{}).get('combat_profile') or world.get('dsh_execution',{}).get('combat_profile')
    if frozen:
        validate_profile(frozen)
        if frozen.get('fire_accounting')!=accounting:
            raise ValueError('冻结火力参照与当前弹药计量不一致；须显式新建配置，不能重解释旧库存')
        if frozen.get('fire_dynamics')!=dynamics:
            raise ValueError('冻结火力过程与当前动态密度配置不一致；须显式新建配置，不能迁移已运行战局')
        return copy.deepcopy(frozen)
    battle = world.get('mission',{}).get('definition',{}).get('battle','')
    value = {**copy.deepcopy(PROFILE), 'benchmark':benchmark(battle)}
    if accounting or dynamics:
        value=_accounting_profile(value,accounting,dynamics)
    if '徐州' in battle or '台儿庄' in battle:
        value['assumptions'][4] = '阵亡比例0.25是伤亡分类假设，不是台儿庄已知分项；其余新伤亡为负伤，既有未分类损失不改写。'
        value['benchmark']['local_reference'] = '第31师约8000余、死伤近3000，仅作城镇激战量级参照；不指定本局必达损失。'
        value['benchmark']['unit_references'] = [{
            'historical_unit_id':'ww2.cn.division31','name':'第31师','metric':'killed_and_wounded',
            'committed_approx':8000,'casualties_approx':3000,'qualifier':'8000余、近3000',
            'duration_hours':None,'hourly_rate_available':False,
            'scope':'台儿庄城内防御叙述；并非每个局部推演阶段的同窗口统计',
            'note':'原报道未限定该师损失的精确起止；不按历时线性摊派，不等同于阵亡或整场双方伤亡。',
            'source':copy.deepcopy(PROFILE['sources'][2])}]
    elif battle=='抗美援朝-第一次战役-1950.10.25至1950.11.05':
        source={'title':'两水洞遭遇战（解放军报，2020-11-22）',
                'url':'https://www.mod.gov.cn/gfbw/gfjy_index/js_214151/4874430.html',
                'scope':'国防部转载军史：全程战果分列毙325、俘161；其他公开报道有480余、484等异文，不当作同口径精确总数'}
        value['sources']=[value['sources'][0],source]
        value['benchmark']['unit_references']=[{
            'historical_unit_id':'kw.rok.regiment2.battalion3','name':'韩国第2团加强第3营',
            'metric':'reported_killed_and_captured','committed_approx':None,'casualties_approx':None,
            'reported_killed':325,'reported_captured':161,
            'metric_summary':'中方报告毙325、俘161；另有480余、484等异文，统计范围待核，不能相加称为战死或开局人数。',
            'duration_hours':None,'hourly_rate_available':False,
            'scope':'1950年10月25日两水洞全程报告，不是12时前开局片段的同窗口损失',
            'note':'公开叙述的主力交火、歼灭残部和阻援有不同耗时；被俘与阵亡分列，未知开局人数保持未知，不换算逐小时扣兵配额。',
            'source':copy.deepcopy(source)}]
    else:
        value['sources'] = value['sources'][:1]
    for filename in ('korean_loss_references.json', 'long_march/loss_references.json'):
        local = json.loads((ROOT/'data'/filename).read_text())['battles'].get(battle)
        if local:
            value['benchmark']['unit_references'] = copy.deepcopy(local)
            # New worlds freeze the selected reference. Older snapshots never
            # inherit new reports, casualty quotas or parent-unit losses.
            value['sources'].extend(copy.deepcopy(r['source']) for r in local)
    value['definition_hash'] = digest(value)
    return value


def observation(world):
    value = reference(world); b = value['benchmark']
    return {k:copy.deepcopy(value[k]) for k in ('version','combat_revision','direct_cycle_s','artillery_cycle_s','ammo_per_cycle','fatality_share','scope')} | {
        **({'fire_dynamics':copy.deepcopy(value['fire_dynamics'])} if 'fire_dynamics' in value else {}),
        **({'damage_quantum':value['damage_quantum']} if 'damage_quantum'in value else {}),
        **({'fire_accounting':copy.deepcopy(value['fire_accounting']),
            'work_cost_by_action':{a:work_cost(value,a)for a in ('fire','bombard','suppress')}} if 'fire_accounting' in value else {}),
        'assumptions':value['assumptions'], 'reference_battle':b['battle'], 'reference_status':b['status'],
        'figures':[{k:r.get(k) for k in ('side','metric','value','qualifier','scope','note')} for r in b['figures'][:4]],
        'local_reference':b.get('local_reference'),
        'unit_references':copy.deepcopy(b.get('unit_references',[])),
        'fire_stop_reasons':{str(k):v for k,v in FIRE_STOPS.items()},
        'direct_fire':copy.deepcopy(value.get('direct_fire')),
        'reference_sources':[{k:s.get(k) for k in ('title','url','scope')} for s in value['sources'][:3]],
        'force_historical_outcome':False,'definition_hash':value['definition_hash']}


def validate_personnel(personnel, prior=None):
    if prior and any(type(prior.get(k)) is int and type(personnel.get(k)) is not int for k in COUNT_FIELDS):
        raise ValueError('已知累计伤亡分类不能丢失或变为未知')
    known = [k for k in COUNT_FIELDS if personnel.get(k) is not None]
    if any(type(personnel[k]) is not int or personnel[k]<0 for k in known):
        raise ValueError('伤亡分类须为非负整数，未知不得伪装成0')
    total = sum(personnel[k] for k in known)
    if total > personnel['casualties'] or len(known)==len(COUNT_FIELDS) and total!=personnel['casualties']:
        raise ValueError('伤亡分类与战斗减员不守恒')
    if prior and any(personnel.get(k,0)<prior[k] for k in known if type(prior.get(k)) is int):
        raise ValueError('累计伤亡分类不能减少或自动改写旧损失')
    if prior:
        def unclassified(p):return p['casualties']-sum(p.get(k) or 0 for k in COUNT_FIELDS[:-1])
        if unclassified(personnel)<unclassified(prior):
            raise ValueError('旧未分类伤亡不能自动改写为阵亡、负伤、失踪或被俘')
    return True


def _classified_count(personnel, key):
    value = personnel.get(key)
    if type(value) is int:
        return value
    # A checked zero aggregate proves all components zero. Nonzero old
    # aggregates with missing breakdowns remain unknown, never backfilled.
    return 0 if personnel.get('casualties') == 0 else None


def _count_delta(prior, current, key):
    a, b = _classified_count(prior, key), _classified_count(current, key)
    return b-a if a is not None and b is not None and b>=a else None


def loss_summary(before,after):
    """Format checked ledgers; no inferred deaths from an aggregate casualty count."""
    rows=[]
    for side,label in (('red','红方'),('blue','蓝方')):
        current_units=[u for u in after.get(side+'_units',[]) if u.get('personnel')]
        current=[u['personnel'] for u in current_units]
        old={u['name']:u['personnel'] for u in before.get(side+'_units',[]) if u.get('personnel')}
        prior=[u['personnel'] for u in before.get(side+'_units',[]) if u.get('personnel')]
        if not current:continue
        total=sum(p['casualties'] for p in current)
        delta=total-sum(p['casualties'] for p in prior)
        committed=sum(p['committed'] for p in current)
        def classified(key):
            values=[_classified_count(p,key) for p in current]
            return str(sum(values))+'人' if all(v is not None for v in values) else '未分类'
        def changed(key):
            values=[_count_delta(old.get(u['name'],{}),u['personnel'],key) for u in current_units]
            return str(sum(values))+'人' if all(v is not None for v in values) else '未分类'
        rows.append(f'{label}本轮战斗减员{delta}人，累计{total}人（投入人员的{100*total/committed:.2f}%），'
            f'本轮阵亡估计{changed("killed")}、本轮负伤估计{changed("wounded")}、本轮被俘{changed("captured")}、本轮失踪{changed("missing")}；'
            f'累计阵亡估计{classified("killed")}、累计负伤估计{classified("wounded")}、累计被俘{classified("captured")}、累计失踪{classified("missing")}；'
            f'累计非战斗减员{sum(p["noncombat_losses"] for p in current)}人')
    return '人员账：'+'；'.join(rows)+'。伤亡估计与历史记载分列，战斗减员不能全部称为战死。' if rows else ''


def assess_turn(before, after, seconds, orders, *, source):
    """Review committed evidence; never apply losses or infer a historical quota.

    Incoming time is the longest firing duration among an actor's attackers in
    each turn, a conservative exposure indicator, not the sum of overlapping
    attackers and not a claim that every soldier was exposed for that duration.
    """
    profile=reference(after);turn=after['mission']['turn']
    previous=before.get('combat_assessment') or {}
    continuous=(previous.get('source')==source and previous.get('turn')==before['mission']['turn']
                and previous.get('profile_hash')==profile['definition_hash'])
    tracked={r['name']:r for r in previous.get('units',[])} if continuous else {}
    old={u['name']:u for team in ('red','blue') for u in before.get(team+'_units',[])}
    units={u['name']:u for team in ('red','blue') for u in after.get(team+'_units',[])}
    incoming={name:[] for name in units};outgoing={};missing=set();unknown_targets=set();interrupted={}
    native=source=='afsim_native'
    for order in orders:
        name=order.get('unit')
        if name not in units or order.get('action') not in ('fire','bombard','suppress'):continue
        r=units[name].get('formation',{}).get('last_execution') or {}
        valid=(native and r.get('turn')==turn and r.get('action')==order['action']
               and type(r.get('fire_cycles')) is int and r['fire_cycles']>=0
               and type(r.get('active_fire_s')) in (int,float) and 0<=r['active_fire_s']<=seconds)
        captured=_count_delta(old.get(name,{}).get('personnel',{}),units[name].get('personnel',{}),'captured')
        capture_receipt=(after.get('campaign') or {}).get('actors',{}).get(name,{}).get('captured_this_turn')
        if (native and captured is not None and captured>0 and capture_receipt==captured
                and units[name].get('personnel',{}).get('current')==0
                and r.get('turn')==turn and r.get('action')=='未交付'
                and r.get('command_done')==0 and r.get('fire_cycles')==0 and r.get('active_fire_s')==0):
            # Native zero-fire receipt plus conserved capture counters proves
            # interruption; missing/stale/contradictory telemetry still fails.
            valid=True;interrupted[name]='captured_before_execution'
        if not valid:
            if native:
                missing.add(name)
                if order.get('target') in incoming:unknown_targets.add(order['target'])
            continue
        outgoing[name]=r
        if order.get('target') in incoming and r['fire_cycles']>0:
            incoming[order['target']].append(r['active_fire_s'])
    refs={r['historical_unit_id']:r for r in profile['benchmark'].get('unit_references',[])}
    rows=[]
    for team in ('red','blue'):
        for u in after.get(team+'_units',[]):
            name=u['name'];p=u.get('personnel') or {};prior=old.get(name,{}).get('personnel') or {}
            delta=p.get('casualties',0)-prior.get('casualties',0);last=tracked.get(name,{})
            exposure=max(incoming[name],default=0) if native and name not in unknown_targets else None
            tracked_exposure=last.get('tracked_incoming_max_fire_s',0)+(exposure or 0)
            tracked_losses=last.get('tracked_casualties',0)+delta
            issues=[]
            # Diagnostic thresholds, NOT historically calibrated casualty rates.
            if (native and tracked_exposure>=7200 and p.get('committed',0)>=1000
                    and tracked_losses<=max(5,p['committed']*.001)):
                issues.append('sustained_fire_low_attrition')
            if name in missing:issues.append('fire_receipt_missing')
            r=outgoing.get(name,{})
            killed=_count_delta(prior,p,'killed')
            row={'name':name,'team':team,'committed':p.get('committed'), 'current':p.get('current'),
                 'turn_casualties':delta,'turn_killed':killed,
                 **{'turn_'+key:_count_delta(prior,p,key) for key in ('wounded','captured','missing','unclassified_casualties')},
                 'order_interruption':interrupted.get(name),
                 'turn_casualty_pct':round(100*delta/p['committed'],4) if p.get('committed') else None,
                 'incoming_max_fire_s':exposure,'outgoing_fire_s':r.get('active_fire_s'),
                 'fire_cycles':r.get('fire_cycles'),'stop_reason':FIRE_STOPS.get(r.get('fire_stop_reason')),
                 'tracked_incoming_max_fire_s':tracked_exposure,'tracked_casualties':tracked_losses,
                 'tracked_fire_time_complete':exposure is not None and last.get('tracked_fire_time_complete',True),
                 'issues':issues}
            if u.get('historical_unit_id') in refs:
                row['historical_reference']=copy.deepcopy(refs[u['historical_unit_id']])
                row['historical_comparison']='context_only_window_or_strength_differs'
            rows.append(row)
    return {'version':'combat-review-1','turn':turn,'source':source,'elapsed_seconds':seconds,
            'profile_hash':profile['definition_hash'],'tracked_from_turn':previous['tracked_from_turn'] if continuous else turn,
            'status':'review_required' if any(r['issues'] for r in rows) else 'calibration_pending',
            'historical_fit_verified':False,'units':rows,
            'note':'来袭方本轮新发射周期裁于轮末，不含上轮周期尾段；按轮取最长来袭记录后求和是非可加的周期覆盖指标，不等于实际接敌或持续受火时长。'
                   '千人以上编组承受累计两小时火力而减员不超过5人或投入人数0.1%时提示复核；阈值仅用于排错，不是历史伤亡下限。'
                   '原生回执缺载或DSH估计时接敌时长保持未知；跨引擎或参照版本更改重新计数。'}


def review_summary(assessment):
    rows=[r for r in assessment['units'] if r['issues']]
    if not rows:return '战损效能：历史同窗口标定待完成；战斗减员与阵亡分列。'
    labels={'sustained_fire_low_attrition':'持续火力下低减员，需检查接敌、掩护、弹耗及效能参数',
            'fire_receipt_missing':'缺本轮火力回执，不能认定持续交火'}
    return '战损效能待复核：'+'；'.join(r['name']+'：'+'、'.join(labels[i] for i in r['issues']) for r in rows[:3])+'。'
