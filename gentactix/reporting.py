"""Program-owned factual summaries and conservative public-narrative guards.

These checks cover known failure classes, not general natural-language truth.
Rejected prose stays in the audit record; the world and original model event do
not change. Supply is an index, committed is cumulative input, HP is not people.
"""
import math
import re
from . import sim_clock
from .supply import objects, index_value

UNSETTLED_GOALS=('目标由宿主在本轮结果校验后评分；正文只报告行动和直接观测，省略目标完成、未完成、尚未评分或下回合确认等结论。')
SETTLED_GOALS=('候选效果须先通过原生过程预览。允许引用成功预览的宿主目标与阶段结算；'
    '尚未采样不是条件不成立，当前条件、已完成里程碑和最终胜负分开。'
    '预览阶段只是候选，最终报告仅在成功提交后展示；公开正文描述本轮已发生效果，不叙述候选等待提交或其他内部提交过程。'
    '持续任务是否完成仍由宿主任务回执另判，不将候选成功等同任务完成。'
    '疲劳与人员保有率引用成功预览units中的fatigue、personnel_strength_pct；未列条目可用get_turn_preview分页读取，未读取则省略精确数值，不从旧HP反推人数。'
    '正文简洁使用中文，只述有记录的过程和变化；不重复内部字段、公式或全体坐标。'
    '未提供的距离、地名部署或状态变化不自行补算或补造。')

INSTRUCTION = """【战报事实约束】正文服从本回合结构化状态。current_time是唯一当前时刻；
personnel.current是现有人数，committed是累计投入而非核定编制，不据此称满编；HP不是人数。
supply是0—100补给指数，不是弹药发数、粮水库存或可开火次数；0不等于已证实弹尽。
engagements是本回合射击记录，不得同时称相关单位整轮停火。未建立完整事件检索时，
不得声称“今天第一次”“唯一变化”“历史最高”。包围采样比例不等于实际道路条数。
几何补给通断不等于实际运达或库存补充。复盘中旧战报是待核验叙述，当前结构化账本优先。
保留单位全名及“投入部、一部、欠一团”等限定，不得把部分投入单位汇称完整师。
目标使用界面具名目标和中文状态；物理条件成立不等于前置目标已完成，不泄漏目标ID或内部状态枚举。
"""+UNSETTLED_GOALS+"""
回合序号按本次给定T+编号，某单位首次执行一项任务不表示整个战局是首轮。
库存耗尽须写明单位全名和粮食或弹药工作量；不以“两军、双方、全军”代替单位范围。
“未耗尽”同样依据具名单位当前正库存；炮弹读取分类炮弹库存，不能从弹药工作量推算。
局部时段停火须写明单位全名及“本轮最后N小时/分钟”，并有本轮射击过程账；
DSH过程账是已校验的模型估计，不能称为AFSIM原生遥测。库存为零不能证明停止射击的具体时刻。
"""


def instruction(*,settlement_preview=False):
    return INSTRUCTION.replace(UNSETTLED_GOALS,SETTLED_GOALS) if settlement_preview else INSTRUCTION

_DIGITS = dict(zip('零一二三四五六七八九', range(10)), 两=2)


def _cn_number(text):
    if text.isdigit():
        return int(text)
    if '十' in text:
        a, b = text.split('十', 1)
        return (_DIGITS.get(a, 1) if a else 1) * 10 + _DIGITS.get(b, 0)
    return _DIGITS.get(text)


def _times(text):
    for match in re.finditer(r'(?<!\d)([0-2]?\d)[:：]([0-5]\d)(?!\d)', text):
        yield int(match[1]), int(match[2])
    # Bare “一点补给/三点建议” is not a clock. Require an explicit minute suffix.
    for match in re.finditer(r'([零一二两三四五六七八九十\d]{1,3})[点时](一刻|三刻|半|整|[零一二两三四五六七八九十\d]{1,3}分)', text):
        hour = _cn_number(match[1])
        suffix = match[2] or ''
        minute = {'一刻': 15, '三刻': 45, '半': 30, '整': 0, '': 0}.get(suffix)
        if minute is None:
            minute = _cn_number(suffix.rstrip('分'))
        if hour is not None and minute is not None and hour < 24 and minute < 60:
            yield hour, minute


def _turn_issues(text, turn):
    if turn is None:
        return []
    # Dates in parentheses separate “本回合” from its ordinal in real reports.
    compact = re.sub(r'[（(][^）)]*[）)]', '', text)
    ordinals = re.finditer(r'(?:本轮|本回合|本次推演|此次推演)[^。！？；;\n]{0,32}?'
        r'(?<!不)(?:是|为|属于)[^。！？；;\n]{0,16}?(首轮|第[零一二两三四五六七八九十\d]+轮)', compact)
    values = [1 if m[1] == '首轮' else _cn_number(m[1][1:-1]) for m in ordinals]
    values += [int(m[1]) for m in re.finditer(r'(?:本轮|本回合)\s*(?:序号(?:为|是)?|为|是)?\s*T\+(\d+)', compact)]
    denied_first = turn == 1 and re.search(r'(?:本轮|本回合|本次推演|此次推演)[^。！？；;\n]{0,48}'
        r'(?:不是|并非|非|不属于)(?:整个)?(?:战局|推演)?(?:的)?(?:首轮|第一轮)', compact)
    if denied_first or any(value is not None and value != turn for value in values):
        return [{'code': 'narrative_turn', 'message': f'正文当前回合序号与宿主T+{turn}不一致'}]
    return []


def _named_goal_statements(clause, nodes):
    """Share a predicate only across an explicit list of registered goal names."""
    labels = sorted({node['label'] for node in nodes}, key=len, reverse=True)
    if not labels:
        return
    mentions = list(re.finditer('|'.join(map(re.escape, labels)), clause))
    groups = []
    for mention in mentions:
        if groups and re.fullmatch(r'[、，,及与和\s“”"\'（）()]*', clause[groups[-1][-1].end():mention.start()]):
            groups[-1].append(mention)
        else:
            groups.append([mention])
    for index, group in enumerate(groups):
        end = groups[index+1][0].start() if index+1 < len(groups) else len(clause)
        tail = clause[group[-1].end():end]
        for mention in group:
            for node in nodes:
                if node['label'] == mention[0]:
                    yield node, clause[:mention.start()], tail


def _goal_claim_conflict(tail, progress):
    """Distinguish sampling from milestone completion, with local negation.

    Sampling follows the same status contract as turn_settlement.build. A
    completed observation says nothing about whether its condition held.
    """
    sampled = progress['status'] not in ('pending', 'waiting_phase')
    denied = granted = False
    completion = re.compile(
        r'(?P<negative>尚未|仍未|还未|未能|未曾|未|没有|不是|并非)(?:被)?'
        r'(?:记为|登记为|标为|判为|认定为)?(?:已(?:经)?)?(?:完成|达成)'
        r'|(?:已(?:经)?|现已|成功)(?:经)?(?:完成|达成)'
        r'|完成(?=(?:了)?(?:本轮|本回合)?(?:采样|观察|评分|判定|确认))')
    for match in completion.finditer(tail):
        positive = match['negative'] is None
        observation = re.match(r'(?:了)?(?:本轮|本回合)?(?:采样|观察|评分|判定|确认)', tail[match.end():])
        if observation:
            if positive != sampled:
                return True
        elif positive:
            granted = True
        else:
            denied = True
    # Direct “已采样/尚未采样” lacks the completion verb above.
    for match in re.finditer(r'(?P<negative>尚未|仍未|还未|未曾|未|没有|未经)'
                            r'(?:经)?(?:采样|观察|评分|判定|确认)'
                            r'|(?:已经|现已|已)(?:采样|观察|评分|判定|确认)', tail):
        if (match['negative'] is None) != sampled:
            return True
    denied |= bool(re.search(r'(?:等待|待)[^。！？；;\n]{0,24}(?:确认|判定|采样|观察)', tail))
    return bool(progress['status'] == 'completed' and denied or progress['status'] != 'completed' and granted)


def _goal_verdict_issues(text, state, previous):
    """Check explicit named-goal claims, not unrestricted natural language.

    Prior-frame descriptions and conditional plans are not final verdicts.
    Predicate truth and completion are separate, including latched goals.
    """
    config = state.get('mission', {}).get('definition', {}).get('campaign_plan')
    if not config or not state.get('campaign_plan'):
        return []
    issues = []
    for clause in re.split(r'[。！？；;\n]', text):
        universal = re.search(r'(?:各(?:个|项|方向)?|全部|所有)(?:方向)?目标[^。！？；;\n]{0,10}'
            r'(?:尚未|还未|仍未|未曾|未经|没有)(?:经)?[^。！？；;\n]{0,12}(?:采样|观察|评分|判定|确认)', clause)
        if universal:
            prefix = clause[:universal.start()]
            prior = re.search(r'轮初|回合开始|行动前|上一轮(?:末)?|此前', prefix)
            nodes = ((previous or {}) if prior else state).get('campaign_plan', {}).get('nodes', {})
            if nodes and any(n['status'] not in ('pending','waiting_phase') for n in nodes.values()) and not re.search(r'如果|假如|倘若|一旦|若|未来|后续', prefix):
                issues.append({'code':'goal_verdict','message':'正文称各目标尚未观察评分，但对应时点宿主已评分'})
        for node, prefix, tail in _named_goal_statements(clause, config['nodes']):
            if re.search(r'如果|假如|倘若|一旦|若', prefix) or re.search(r'(?:完成|达成)(?:时|之前|以后|则)', tail):
                continue
            stamps = list(re.finditer(r'轮初|回合开始|行动前|上一轮(?:末)?|此前|轮末|本轮结束|推进后|到位后', prefix))
            prior = bool(stamps and re.fullmatch(r'轮初|回合开始|行动前|上一轮(?:末)?|此前', stamps[-1][0]))
            progress = (previous or {}).get('campaign_plan', {}).get('nodes', {}).get(node['id']) if prior else state['campaign_plan']['nodes'].get(node['id'])
            if not progress:
                continue
            predicate = re.search(r'(?:当前|物理|目标)?条件(?:已经|已|仍|尚|依然)?(不成立|未成立|未满足|未达成|成立|满足|达成)', tail)
            wrong_predicate = bool(predicate and (progress['status'] in ('pending','waiting_phase')
                or (predicate[1] in ('成立', '满足', '达成')) != progress['condition']))
            verdict = tail if not predicate else tail[:predicate.start()]+tail[predicate.end():]
            transition=re.compile(r'(?:状态)?(?:由|从)(尚未完成|尚未达成|未完成|未达成|已完成|已达成)(?:转为|变为|变成)(尚未完成|尚未达成|未完成|未达成|已完成|已达成)')
            for change in transition.finditer(verdict):
                earlier=(previous or {}).get('campaign_plan',{}).get('nodes',{}).get(node['id'])
                current=state['campaign_plan']['nodes'].get(node['id'])
                if (not earlier or not current or (earlier['status']=='completed')!=change[1].startswith('已')
                        or (current['status']=='completed')!=change[2].startswith('已')):
                    issues.append({'code':'goal_verdict','message':node['label']+'的正文状态转换与前后两帧不一致或缺少记录'})
            verdict=transition.sub('',verdict)
            if wrong_predicate or _goal_claim_conflict(verdict, progress):
                issues.append({'code': 'goal_verdict', 'message': node['label']+'的正文结论与对应时点的宿主目标评分不一致'})
    return issues


def _direction_count_issues(text, state):
    """A named goal list can be counted; sampled bearings cannot count roads."""
    nodes = state.get('mission', {}).get('definition', {}).get('campaign_plan', {}).get('nodes', [])
    spans = [(m.start(), m.end()) for node in nodes for m in re.finditer(re.escape(node['label']), text)]
    names = {}
    for node in nodes:
        names.setdefault(node['label'], set()).add(node['id'])
        # Only a region goal supplies a geographic direction alias; e.g. a
        # preserve goal mentioning “两方向” does not add a third direction.
        if node.get('condition', {}).get('region') and '方向' in node['label']:
            alias = node['label'].split('方向', 1)[0]
            if alias:
                names.setdefault(alias, set()).add(node['id'])
    unique = {name: next(iter(ids)) for name, ids in names.items() if len(ids) == 1}
    token = '(?:'+'|'.join(map(re.escape, sorted(unique, key=len, reverse=True)))+')' if unique else None
    pattern = r'([零一二两三四五六七八九十\d]+)个方向|退路只剩[一二两三四五六七八九十\d]+条'
    for match in re.finditer(pattern, text):
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            continue
        if token and match[1] and re.match(r'(?:的)?(?:前置)?目标', text[match.end():]):
            # Require the actual named list immediately before the number.
            # Merely adding “目标” to an unsupported road claim is insufficient.
            mention = re.search(r'(?:^|[：:，,；;。！？\n“”"\s]|因|由|在|针对|包括|红方|蓝方)'
                                r'(?P<names>'+token+r'(?:\s*[、与及和]\s*'+token+r')*)\s*$', text[:match.start()])
            if mention:
                ids = {unique[m[0]] for m in re.finditer(token, mention['names'])}
                if len(ids) == _cn_number(match[1]):
                    continue
        return [dict(code='direction_count', message='采样方向比例不能转换为实际道路条数；目标方向数量须对应具名目标')]
    return []


def _zero_ammunition_issues(text, state):
    # “无弹药消耗” describes expenditure, not ammunition availability. It is
    # accepted only against known receipts, never inferred from supply or HP.
    ledger = objects(state.get('mission', {}).get('ledger'))
    units = [u for team in ('red', 'blue') for u in objects(state.get(team+'_units'))]
    firing = {e.get('attacker') for e in objects(state.get('engagements'))}
    for unit in units:
        receipt = unit.get('formation', {}).get('last_execution') or {}
        if receipt.get('shots', 0) or receipt.get('aa_spent', 0):
            firing.add(unit.get('name'))
    for clause in re.split(r'[。！？；;\n]', text):
        if not re.search(r'无弹药(?:消耗|耗用|支出)', clause):
            continue
        names = {u['name'] for u in units if u.get('name') and u['name'] in clause}
        if not names:
            teams = ('red',) if '红方' in clause and '蓝方' not in clause else ('blue',) if '蓝方' in clause and '红方' not in clause else ('red','blue')
            names = {u['name'] for team in teams for u in objects(state.get(team+'_units')) if u.get('name')}
        rows = [r for r in ledger if r.get('unit') in names]
        if (not names or {r.get('unit') for r in rows} != names or names & firing
                or any(r.get('ammo_spent') != 0 or any((r.get('spent') or {}).get(k,0) != 0 for k in ('shells','aa_rounds')) for r in rows)):
            return [{'code':'inventory_claim','message':'无弹药消耗须有对应单位的零耗用回执，不能与本轮射击或分类弹药消耗矛盾'}]
    return []


def _resource_claim_issues(text,state,previous):
    from . import turn_settlement
    basis=turn_settlement.build(state,previous);issues=[]
    for clause in re.split(r'[。！？；;\n]',text):
        if re.search(r'如果|假如|一旦|若|上一轮|此前|历史上',clause):continue
        names={u['name'] for u in basis['units'] if u.get('name') and u['name'] in clause}
        teams=('red',) if '红方' in clause and '蓝方' not in clause else ('blue',) if '蓝方' in clause and '红方' not in clause else ('red','blue')
        rows=[u for u in basis['units'] if (u['name'] in names if names else u['team'] in teams)]
        if re.search(r'补给指数\s*(?:保持|维持)?\s*(?:不变|未变)',clause):
            if not rows or any(r['supply_index_before'] is None or r['supply_index_after'] is None
                    or abs(r['supply_index_before']-r['supply_index_after'])>1e-6 for r in rows):
                issues.append(dict(code='supply_index_claim',message='补给指数不变的正文与粮弹库存派生的本步指数不一致或缺少记录'))
        zero=re.search(r'(?:无|没有(?:发生)?|未发生)物资(?:消耗|耗用|支出)',clause)
        # A nearby warehouse balance does not scope a later, unqualified denial
        # of all spending. Only an attached subject makes this a warehouse claim.
        warehouse_only=bool(zero and re.search(r'(?:仓库|后方库|补给节点)(?:本轮|本回合)?(?:内|端|中)?\s*$',clause[:zero.start()]))
        if zero and not warehouse_only:
            fields=[u[k] for u in rows for k in ('food_spent','ammo_spent')]+[v for u in rows for v in u['classified_spent'].values()]
            if not rows or any(v is None or v!=0 for v in fields):
                issues.append(dict(code='inventory_claim',message='无物资消耗须有对应范围完整零耗用回执，不能否定已知扣粮或分类消耗'))
        equal=re.search(r'粮弹[^。！？；;\n]{0,24}?(?:各|均)[^。！？；;\n]{0,6}?(?:扣减|消耗|耗用|支出)\s*([零一二两三四五六七八九十\d.]+)',clause)
        if equal:
            try:amount=float(equal[1]) if re.fullmatch(r'\d+(?:\.\d+)?',equal[1]) else _cn_number(equal[1])
            except ValueError:amount=None
            if amount is None:continue
            per_unit=bool(names or re.search(r'各单位|各部队|每(?:个)?单位|每(?:支)?部队',clause)) and not re.search(r'合计|总计',clause)
            checks=rows if per_unit else [dict(food_spent=turn_settlement.total([r['food_spent'] for r in rows]),ammo_spent=turn_settlement.total([r['ammo_spent'] for r in rows]))]
            if not rows or any(r[k] is None or abs(r[k]-amount)>1e-6 for r in checks for k in ('food_spent','ammo_spent')):
                issues.append(dict(code='inventory_claim',message='粮弹同量消耗的正文与对应范围分类毛收支不一致；库存净变化不能替代耗用'))
    return issues


def _phase_verdict_issues(text,state,previous):
    from . import turn_settlement
    basis=turn_settlement.build(state,previous);phase=basis['phase']
    if not phase:return []
    issues=[]
    scored=any(r['changed'] and r['status'] not in ('pending','waiting_phase') for r in basis['goals'])
    for clause in re.split(r'[。！？；;\n]',text):
        if re.search(r'如果|假如|一旦|若|上一轮|此前|轮初|本轮起始|本轮观察|行动前',clause):continue
        no_change=re.search(r'(?:本轮|本回合)[^。！？；;\n]{0,8}(?:无|没有)(?:阶段|评分|目标)?状态变化',clause)
        if (no_change and phase['changes']) or (scored and re.search(r'(?:未激活|没有激活)评分节点',clause)):
            issues.append(dict(code='phase_verdict',message='正文否定本轮阶段或评分变化，但宿主已有相应结算'))
        for row in state['mission']['definition']['campaign_lifecycle']['phases']:
            if row['label']!=phase['after_label'] and re.search(r'(?:当前处于|目前处于|现处于|已进入)\s*'+re.escape(row['label']),clause):
                issues.append(dict(code='phase_verdict',message='正文当前阶段与宿主轮末阶段不一致；本轮观察阶段须另行说明'))
    return issues


def _commit_claim_issues(text):
    for clause in re.split(r'[。！？；;\n]',text):
        claim=re.search(r'(?:本轮|本回合|命令(?:与|和)持续任务)[^。！？；;\n]{0,16}(?:仍待|尚待|等待)[^。！？；;\n]{0,8}原子提交',clause)
        if claim and not re.search(r'如果|假如|若|后续|未来|下一轮',clause[:claim.start()]):
            return [dict(code='commit_claim',message='公开战报仅在成功提交后展示，不能仍称本轮效果等待提交；候选工具状态另存审计')]
    return []


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _claim_subject(prefix, state):
    """Resolve an attached list of exact unit names, never narrative pronouns.

    A unit mentioned as a target or in a prior sentence cannot silently become
    the subject. Unknown/duplicate names and partial formation aliases fail
    closed. This is a bounded language pattern, not general coreference.
    """
    units = [u for team in ('red', 'blue') for u in objects(state.get(team+'_units'))]
    names = [u['name'] for u in units if isinstance(u.get('name'), str) and u['name']]
    if not names:
        return []
    token = '(?:'+'|'.join(map(re.escape, sorted(set(names), key=len, reverse=True)))+')'
    clause = re.split(r'[。！？；;\n]', prefix)[-1]
    subject = re.search(r'(?:^|[，,：:]\s*)(?P<names>'+token+r'(?:\s*[、与及和]\s*'+token+r')*)'
                        r'(?:的|本轮|本回合|当前|现有|轮末|随队|自身|均|各|仍|已|在|\s)*$', clause)
    if subject is None:
        return []
    selected = {m[0] for m in re.finditer(token, subject['names'])}
    return [u for u in units if u.get('name') in selected] if all(names.count(n) == 1 for n in selected) else []


def _supported_empty_stock(text, match, state, previous=None):
    # Zero-valued food/ammo are work budgets. They do not prove zero shells,
    # drinking water, ability to fire, capacity, or an entire army's inventory.
    pattern = r'(弹药|粮食|炮弹)(?:工作量|库存|余额)?(?:已|已经|仍|均|都|现已)?(?:归零|耗尽|打光)'
    # The broad screening match may start at a prior resource, e.g. ammo28→5,
    # shells→0. Check the terminal proposition and its bounded subject instead
    # of requiring the entire screening span to be one stock proposition.
    for claim in re.finditer(pattern, text):
        if not match.start() <= claim.start() < claim.end() == match.end():
            continue
        units = _inventory_subject(text, claim.start(), state, previous)
        return bool(units) and all(_finite_number(_stock_value(u, claim[1]))
                                  and _stock_value(u, claim[1]) == 0 for u in units)
    return False


def _stock_value(unit, resource):
    field, key = ('formation', 'shells') if resource == '炮弹' else ('logistics', {'弹药':'ammo', '粮食':'food'}[resource])
    values = unit.get(field)
    return values.get(key) if isinstance(values, dict) else None


def _numeric_inventory_subject(prefix, state, previous):
    """Carry an exact subject through comma-separated, verified stock facts.

    No free prose, targets, aliases, sentence crossing or unverified temporal
    transition may establish the subject. Work budgets and shells stay typed.
    """
    parts = re.split(r'[，,]', re.split(r'[。！？；;\n]', prefix)[-1])
    if len(parts) < 2 or not re.fullmatch(r'\s*(?:随队|自身|轮末|当前|现有)?\s*', parts[-1]):
        return []
    number = r'\d+(?:\.\d+)?'
    pattern = (r'(?P<resource>炮弹|弹药|粮食)(?:工作量|库存|余额|余量|数量)?'
               r'(?:(?:为|剩余|结余)(?P<now>'+number+r')|由(?P<before>'+number+r')'
               r'(?P<direction>降至|升至)(?P<after>'+number+r'))$')
    units = []
    for index, part in enumerate(parts[:-1]):
        fact = re.search(pattern, part.strip())
        if fact is None:
            return []
        subject = part.strip()[:fact.start()]
        if index == 0:
            units = _claim_subject(subject, state)
            if not units:
                return []
        elif not re.fullmatch(r'(?:随队|自身|轮末|当前|现有)?', subject):
            return []
        current = float(fact['now'] if fact['now'] is not None else fact['after'])
        if not _finite_number(current) or not all(
                _finite_number(_stock_value(u, fact['resource']))
                and math.isclose(_stock_value(u, fact['resource']), current, rel_tol=0, abs_tol=1e-6)
                for u in units):
            return []
        if fact['before'] is not None:
            old = float(fact['before'])
            if (not _finite_number(old) or fact['direction'] == '降至' and old < current
                    or fact['direction'] == '升至' and old > current):
                return []
            for unit in units:
                prior = _claim_subject(unit['name'], previous or {})
                if (len(prior) != 1 or not _finite_number(_stock_value(prior[0], fact['resource']))
                        or not math.isclose(_stock_value(prior[0], fact['resource']), old,
                                            rel_tol=0, abs_tol=1e-6)):
                    return []
    return units


def _inventory_subject(text, start, state, previous=None):
    """Exact subjects, or a single actor in the current Markdown bullet.

    Verified inline numeric facts may carry a subject across commas. In a
    Markdown bullet only empty continuations and matching 该营/该连/该部 refer
    to its actor. Targets and other units cannot become its stock source.
    """
    prefix = text[:start]
    units = _claim_subject(prefix, state)
    if units:
        return units
    units = _numeric_inventory_subject(prefix, state, previous)
    if units:
        return units
    boundaries = list(re.finditer(r'(?m)^[ \t]*(?:[-*]\s+|#{1,6}\s+)', prefix))
    if not boundaries:
        return []
    block = prefix[boundaries[-1].start():]
    heading = re.match(r'[ \t]*[-*]\s+([^：:\n]{1,180})[：:]', block)
    if heading is None:
        return []
    label = heading[1].strip()
    units = _claim_subject(label, state)
    if not units:
        pairs = [(_claim_subject(label[:i], state), _claim_subject(label[i+1:], state))
                 for i, char in enumerate(label) if char == '对']
        pairs = [(a, b) for a, b in pairs if a and b]
        if len(pairs) != 1:
            return []
        units = pairs[0][0]
    body = block[heading.end():]
    if re.search(r'上一轮|上回合|昨日|历史|下一轮|下轮|预计|预估|如果|假如|若', body):
        return []
    for team in ('red', 'blue'):
        if any(u not in units and u.get('name') and u['name'] in body for u in objects(state.get(team+'_units'))):
            return []
    tail = re.split(r'[。！？；;\n]', body)[-1].strip()
    if re.search(r'[，,]', tail):
        clauses = re.split(r'[，,]', tail)
        previous, tail = clauses[-2].strip(), clauses[-1].strip()
        numeric_fact = (r'(?:轮末)?剩余装填时间为\d+(?:\.\d+)?(?:秒)?|'
                        r'(?:炮弹|弹药|粮食)(?:工作量|库存)?(?:剩余|结余|为)\d+(?:\.\d+)?(?:发)?')
        if not re.fullmatch(numeric_fact, previous):
            return []
    if tail:
        pronoun = re.fullmatch(r'该(营|连|部)(?:的)?', tail)
        if (not pronoun or len(units) != 1
                or pronoun[1] != '部' and not units[0]['name'].endswith(pronoun[1])):
            return []
    return units


def _supported_remaining_stock(text, match, state):
    resource = r'(?:炮弹|弹药|粮食)(?:工作量|库存|余额|余量|数量)?'
    pattern = r'(?P<resources>'+resource+r'(?:\s*[与和及、]\s*'+resource+r')*)(?:均|都|仍|尚)?(?:未|没有|尚未)(?:耗尽|归零|打光)'
    for claim in re.finditer(pattern, text):
        if not claim.start() <= match.start() < match.end() <= claim.end():
            continue
        units = _inventory_subject(text, claim.start(), state)
        resources = re.findall(r'炮弹|弹药|粮食', claim['resources'])
        return bool(units) and all(_finite_number(_stock_value(u, key)) and _stock_value(u, key) > 0
                                   for u in units for key in resources)
    return False


def _supported_final_stop(text, match, state, previous):
    """A last-shot estimate can support silence in a named final interval.

    Reuse admitted DSH receipts with their current-turn/source binding. Active
    firing duration is not a last-shot time. Native telemetry without shot
    timestamps cannot acquire a fabricated timestamp through this exception.
    """
    from . import fire_process
    prefix = text[:match.start()]
    window = re.search(r'(?:在)?(?:本轮|本回合)最后(?:约)?'
                       r'([零一二两三四五六七八九十\d]+(?:\.\d+)?)(?:个)?(小时|分钟|秒)(?:内|均|已|一直|保持|\s)*$', prefix)
    if window is None or match[0] != '停火':
        return False
    units = _claim_subject(prefix[:window.start()], state)
    start = sim_clock.parse_timestamp((previous or {}).get('current_time'))
    end = sim_clock.parse_timestamp(state.get('current_time'))
    turn = state.get('mission', {}).get('turn')
    if not units or not start or not end or type(turn) is not int:
        return False
    amount = float(window[1]) if re.fullmatch(r'\d+(?:\.\d+)?', window[1]) else _cn_number(window[1])
    seconds = (end-start).total_seconds()
    if amount is None or not 0 < amount*{'小时':3600, '分钟':60, '秒':1}[window[2]] < seconds:
        return False
    silent_from = seconds - amount*{'小时':3600, '分钟':60, '秒':1}[window[2]]
    for unit in units:
        receipt = fire_process.receipt_for_unit(state, unit['name'], turn)
        if (not receipt or receipt.get('action') not in fire_process.GROUND_FIRE
                or type(receipt.get('fire_cycles')) is not int or receipt['fire_cycles'] <= 0
                or not _finite_number(receipt.get('first_fire_s'))
                or not _finite_number(receipt.get('last_fire_s'))
                or not 0 <= receipt['first_fire_s'] <= receipt['last_fire_s'] < silent_from
                or receipt.get('stop_reason') not in ('ammo', 'range', 'too_close', 'no_shells',
                    'target_unavailable', 'actor_unavailable', 'terrain_blocked')):
            return False
        events = [e for e in objects(state.get('engagements')) if e.get('attacker') == unit['name']]
        if not events or any(e.get('weapon_action') != receipt['action'] for e in events):
            return False
    return True


def _fatigue_claim_issues(text,state):
    """Exact current subjects and parenthesized fatigue lists, not general NLP."""
    issues=[]
    def check(subject,value,quote):
        for unit in _claim_subject(subject,state):
            formation=unit.get('formation');actual=formation.get('fatigue') if isinstance(formation,dict) else None
            if not _finite_number(actual) or not math.isclose(float(value),actual,rel_tol=0,abs_tol=1e-6):
                issues.append(dict(code='fatigue_value',quote=quote[:180],
                    message=unit['name']+'疲劳叙述与权威状态不符；实际='+str(actual)))
    for match in re.finditer(r'疲劳(?:指数)?(?:为|是|升至|降至|达到|变为|保持在|[:：])\s*(\d+(?:\.\d+)?)',text):
        check(text[:match.start()],match[1],match[0])
    for intro in re.finditer(r'疲劳[^。！？；;\n]{0,40}?[（(]',text):
        prefix=re.split(r'[。！？；;\n]',text[:intro.start()])[-1]
        if re.search(r'轮初|上轮|上回合|上一|昨日|明日|下轮|下一|预估|预计|历史|史料',prefix):continue
        depth=1;end=intro.end()
        while end<len(text) and depth:
            if text[end] in '（(':depth+=1
            elif text[end] in '）)':depth-=1
            end+=1
        if depth:continue
        for entry in re.split(r'[，,；;]',text[intro.end():end-1]):
            value=re.fullmatch(r'(.+?)(?:疲劳(?:指数)?)?(?:升至|降至|为|达到|变为|保持在)?\s*(\d+(?:\.\d+)?)\s*',entry.strip())
            if value:check(value[1],value[2],entry)
    return issues


def inspect(text, state, previous=None, *, review=False, turn=None):
    issues = []
    # Do not claim exhaustive semantic verification; deny unsupported quantities.
    patterns = (
        ('strength_claim', r'满编|全员健在|毫发无损|快没人|没有能走路的人', '编制/行动能力断言缺少对应账本；以现有人数为准'),
        ('history_superlative', r'(?:今天|今日|本日|有史以来).{0,8}(?:第一次|首次|最高)|唯一.{0,4}变化', '首次/唯一/最高断言未经完整历史检索'),
        ('inventory_claim', r'(?:弹药|粮食|粮弹|坑道储备|囤弹|库存).{0,16}?(?:归零|降到个位|耗尽|已满|打光|最高|够一次)|炮弹[^。！？；;\n]{0,16}?(?:归零|耗尽|打光)|弹尽粮绝|满供|无弹(?!药(?:消耗|耗用|支出))|开火权', '补给指数不能代替弹药、粮水、库存、运达量或开火权限'),
        ('geometry_claim', r'几何内核.{0,24}(?:给出|写死|证明)|(?:内核|系统)(?:已)?(?:计算|算出).{0,12}(?:弹药|运量|视线|命中|杀伤)', '模型对内核能力的转述未经验证；以程序几何摘要为准'),
        ('fire_denial', r'停火|不打(?:[，。；、]|$)|不能打枪|整轮(?:都|均)?(?:没有|未|无)(?:开火|射击)', '停火断言需事件级时间范围，不能与本轮射击记录混用'),
    )
    for code, pattern, message in patterns:
        matches=list(re.finditer(pattern,text))
        if code=='strength_claim':
            # Preserve explicit denials such as the actual model's “不据此称满编”.
            # Check each occurrence: a denial cannot license a later assertion.
            denial=r'(?:不|不能|不应|不宜|不得|不可|并非|而非|不是|未)(?:据此|以此|因此)?(?:称(?:为)?|认定(?:为)?|视为|等于|代表|说明|表示)?(?:核定)?\s*$'
            matches=[m for m in matches if not re.search(denial,text[max(0,m.start()-32):m.start()])]
        elif code == 'inventory_claim':
            matches = [m for m in matches if not (_supported_empty_stock(text, m, state, previous)
                                                  or _supported_remaining_stock(text, m, state))]
        elif code == 'fire_denial':
            matches = [m for m in matches if not _supported_final_stop(text, m, state, previous)]
        if matches and (code != 'fire_denial' or objects(state.get('engagements'))):
            issue = {'code': code, 'message': message}
            if code == 'inventory_claim':
                match = matches[0]
                prefix = re.split(r'[。！？；;\n]', text[:match.start()])[-1][-80:]
                issue['quote'] = (prefix + match[0])[-180:]
            issues.append(issue)
    issues += _direction_count_issues(text, state)
    if not review:
        issues += _turn_issues(text, turn)
        issues += _goal_verdict_issues(text, state, previous)
        issues += _zero_ammunition_issues(text, state)
        issues += _resource_claim_issues(text,state,previous)
        issues += _fatigue_claim_issues(text,state)
        issues += _phase_verdict_issues(text,state,previous)
        issues += _commit_claim_issues(text)
        # Deny a known aggregate-scope failure, not arbitrary historical prose.
        for match in re.finditer(r'(?:(红方|蓝方)(?:的)?)?([零一二两三四五六七八九十\d]{1,3})个(?:步兵)?师', text):
            count = _cn_number(match[2])
            teams = ('red',) if match[1] == '红方' else ('blue',) if match[1] == '蓝方' else ('red', 'blue')
            for team in teams:
                divisions = [u for u in objects(state.get(team+'_units')) if '师' in str(u.get('name', ''))]
                if count and count == len(divisions) and any(re.search(r'投入部|一部|部分|欠', str(u.get('name', ''))) for u in divisions):
                    issues.append({'code': 'partial_formation_scope', 'message': '实际师级身份含部分投入，不能将该集合汇称完整师'})
                    break
        config = state.get('mission', {}).get('definition', {}).get('campaign_plan')
        if config:
            from .campaign_plan import STATES
            internal = [n['id'] for n in config['nodes'] if n['id'] != n['label']]
            internal += sorted(STATES)
            if any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(word)+r'(?![A-Za-z0-9_])', text) for word in internal):
                issues.append({'code': 'internal_goal_label', 'message': '战报须使用具名目标与中文状态，原始内部字段保留在审计中'})
    end = sim_clock.parse_timestamp(state.get('current_time'))
    start = sim_clock.parse_timestamp((previous or {}).get('current_time')) or end
    if end and not review:
        for match in re.finditer(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?', text):
            stamp = sim_clock.parse_timestamp(match[0])
            if stamp is not None and not start <= stamp <= end:
                issues.append({'code': 'narrative_clock', 'message': '正文日期时刻不在本回合时间窗'})
        for hour, minute in _times(text):
            minute_of_day = hour * 60 + minute
            if end.date() == start.date():
                valid = start.hour * 60 + start.minute <= minute_of_day <= end.hour * 60 + end.minute
            else:
                valid = True  # Multi-day prose needs date-aware semantic review, not guessing a day.
            if not valid:
                issues.append({'code': 'narrative_clock', 'message': f'正文时刻{hour:02}:{minute:02}不在本回合时间窗'})
    return issues


def _value(value):
    return str(value) if value is not None else '未记录'


def facts(state, previous=None, adjudication=None):
    from .personnel_projection import strength_pct
    old = {(t, u.get('name')): u for t in ('red', 'blue') for u in objects((previous or {}).get(t + '_units'))}
    geometry = {(r.get('team'), r.get('name')): r for r in objects((adjudication or {}).get('units'))}
    lines = ['**状态核对摘要（程序生成）**', '']
    for team in ('red', 'blue'):
        for u in objects(state.get(team + '_units')):
            p = u.get('personnel') if isinstance(u.get('personnel'), dict) else {}
            prior = old.get((team, u.get('name')), {}).get('personnel') or {}
            current, prior_count = p.get('current'), prior.get('current')
            change = f'{current - prior_count:+g}' if all(isinstance(v, (int, float)) for v in (current, prior_count)) else '未记录'
            current_index=index_value(u);prior_index=index_value(old.get((team,u.get('name')),{}))
            index_change=f'{current_index-prior_index:+g}' if current_index is not None and prior_index is not None else '未记录'
            name = str(u.get('name') or '未命名').replace('|', '／').replace('\n', ' ')
            strength=strength_pct(u)
            indicator=(f'人员保有率{strength:g}%（现有/累计投入，非编制满员率）' if strength is not None else f'HP {_value(u.get("hp"))}')
            lines.append(f"- **{name}**：现有/累计投入 {_value(current)}/{_value(p.get('committed'))}人；"
                         f"累计战斗/非战斗减员 {_value(p.get('casualties'))}/{_value(p.get('noncombat_losses'))}人；"
                         f"本步人数变化 {change}。{indicator}，补给指数 {_value(current_index)}（本步{index_change}）。")
            formation=u.get('formation');fatigue=formation.get('fatigue') if isinstance(formation,dict) else None
            if _finite_number(fatigue):lines.append(f'  权威状态：疲劳{fatigue:g}（0—100模型指数）。')
            logistics = u.get('logistics') or {}
            if any(_finite_number(logistics.get(k)) for k in ('food', 'ammo')):
                balances = {k: logistics[k] if _finite_number(logistics.get(k)) else None for k in ('food', 'ammo')}
                lines.append(f"  随队库存（模型工作量）：粮食{_value(balances['food'])}、弹药{_value(balances['ammo'])}；不等同实物发数或全部分类物资。")
            from . import fire_process
            receipt = fire_process.receipt_for_unit(state, u.get('name'), state.get('mission', {}).get('turn'))
            if receipt:
                lines.append(f"  DSH过程估计，非AFSIM遥测：本轮{_value(receipt.get('fire_cycles'))}个地面火力周期；"
                    f"首发{_value(receipt.get('first_fire_s'))}秒、末发{_value(receipt.get('last_fire_s'))}秒（相对轮初）；"
                    f"停止原因{dict(ammo='弹药工作量不足', no_shells='炮弹不足', range='射程外', too_close='过近', none='未记录提前停止').get(receipt.get('stop_reason'), '其他已登记原因')}。")
            if 'unit_participation' in state:
                from . import unit_participation
                row=unit_participation.unit_view(state,u,team)
                lines.append(f"  当前参与：{row['label']}；保留实际位置与资源账，后方待命仍可受攻击。")
    config = state.get('mission', {}).get('definition', {}).get('campaign_plan')
    if config and state.get('campaign_plan'):
        lines += ['', '**会战目标（宿主评分）**', '']
        for node in config['nodes'][:8]:
            progress = state['campaign_plan']['nodes'][node['id']]
            predicate = '尚未采样' if progress['status'] in ('pending','waiting_phase') else '成立' if progress['condition'] else '不成立'
            lines.append(f"- {node['label']}：当前条件{predicate}；{progress['reason']}。")
        if len(config['nodes']) > 8:
            lines.append('此摘要仅列前8项目标；完整进度见目标面板或分页查询。')
    firing = sorted({str(e.get('attacker')) for e in objects(state.get('engagements')) if e.get('attacker')})
    lines += ['', f"本轮记录交战{len(objects(state.get('engagements')))}次；攻击单位：{'、'.join(firing) or '无记录'}。"]
    if geometry:
        lines.append('几何补给连通：' + '；'.join(f"{name} {r.get('supply', '未知')}"
                    for (_, name), r in geometry.items()) + '。')
    from . import turn_settlement
    basis=turn_settlement.build(state,previous)
    for team in basis['resource_teams']:
        if not team['unit_count']:continue
        label='红方' if team['team']=='red' else '蓝方'
        lines.append(f"{label}本轮毛收支：粮食消耗{_value(team['food_spent'])}、弹药消耗{_value(team['ammo_spent'])}；"
            f"粮食到货{_value(team['food_received'])}、弹药到货{_value(team['ammo_received'])}（模型工作量；已记账{team['receipt_units']}/{team['unit_count']}执行单位）。")
        cost=team['classified_spent']
        lines.append(f"{label}分类耗用：炮弹{_value(cost['shells'])}发、防空弹药{_value(cost['aa_rounds'])}发、"
            f"燃油{_value(cost['fuel_liters'])}升、备件{_value(cost['spares'])}件、施工耗材{_value(cost['materials'])}包。")
    phase=basis['phase']
    if phase:
        lines+=['','**阶段结算（宿主）**','',f"本轮观察阶段：{phase['observed_label'] or '初态未采样'}；轮末阶段：{phase['after_label']}。"]
        for change in phase['changes']:lines.append(f"- {change['label']}：{'完成' if change['status']=='completed' else '进入'}，累计{change['at_seconds']}秒。")
    lines.append('人数按战局账本；累计投入不是核定编制。HP与补给为指数，不能换算人数或弹药库存；几何连通不表示实际运达。')
    return '\n'.join(lines)


def render(text, state, previous=None, *, turn=None, adjudication=None, review=False):
    raw = str(text or '')
    body = re.sub(r'^\s*【T\+\d+[^】]*】\s*', '', raw)
    issues = inspect(body, state, previous, review=review, turn=turn)
    label = re.match(r'^\s*【T\+(\d+)\s*\|\s*([^】]+)】', raw)
    if label and turn is not None and (int(label[1]) != turn or label[2].strip() != state.get('current_time')):
        issues.append({'code': 'report_header', 'message': '模型标题回合/时刻错误，已由程序时钟重建'})
    retained = body
    if issues:
        if review:
            # Keep recommendations, but remove whole conflicting sentences rather
            # than guess names/pronouns and replace numbers inside the model's prose.
            sentences = re.split(r'(?<=[。！？\n])', body)
            retained = ''.join(s for s in sentences if not inspect(s, state, previous, review=True)).strip()
        else:
            retained = ''
    heading = (f"【T+{turn} | {state.get('current_time', '时间未记录')}】" if turn is not None
               else f"【状态时点 | {state.get('current_time', '时间未记录')}】")
    parts = [heading]
    if issues:
        parts.append('原模型文字触发事实校验，冲突内容未作为战报事实展示；原文与校验原因已留在审计记录。')
    if retained:
        label = '教学规则结算（参数未史实标定）' if state.get('mission') and not review else '模型解读（仍需核验）'
        if state.get('mission') and not review:
            definition=state['mission']['definition']
            if definition.get('historical_synthetic'):label='合成演习结算（估计参数未标定）'
            elif definition.get('historical_calculation'):label='历史部队模型计算（估计参数未标定）'
        parts.append('**' + label + '**\n\n' + retained)
    parts.append(facts(state, previous, adjudication))
    return '\n\n'.join(parts), {'version': 1, 'status': 'fallback' if issues else 'screened',
                                'issues': issues, 'original_text': raw,
                                'settlement': turn_settlement_summary(state,previous),
                                'scope': '已知错误模式筛查；非通用语义证明'}


def turn_settlement_summary(state,previous=None,*,version=None):
    from . import turn_settlement
    return turn_settlement.projection(turn_settlement.build(state,previous,version=version))


def initial_status(state):
    definition=state.get('mission',{}).get('definition',{})
    if definition.get('historical_calculation') or definition.get('historical_synthetic'):
        return '所选局部阶段初态已载入；身份与来源保留，缺载数值按已确认的计算参数运行。'
    return '各单位已进入战斗位置，战役即将打响。'
