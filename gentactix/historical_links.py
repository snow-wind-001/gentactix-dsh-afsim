"""Versioned phase evidence links; neither commands nor synthesized deployments."""
import copy
import math

KINDS={'concentration','attack','defense','relief','withdrawal','interception','counterattack','movement','combat','command'}
RELATIONS={'administrative','operational_command','support'}
SCOPE='固定版本的史料任务/配属与地名关联；不是本局已执行命令、实时情报或推算战果。缺载坐标和兵额保持未知。'
MEASUREMENT_SCOPE='固定版本的阶段数值资料，不是本局当前人员、装备、库存或损失。须按统计对象与数量关系解读；缺载不等于零，不自动用于初态或裁决。'
MEASUREMENT_UNITS={'personnel':'persons','horses':'horses','artillery':'guns','small_arms':'weapons',
                   'ammunition':'rounds','food':'kg','fuel':'liters','distance':'km','duration':'hours'}
MEASUREMENT_STATISTICS={'replacement_basis','ordered_detachment','reported_enemy_group','reported_retreat_group',
                        'reported_strength','reported_equipment','reported_stock','reported_casualties',
                        'reported_existing_strength','planned_replacement','reported_strength_including_plan',
                        'documented_partial_reduction','reported_reduction'}
MEASUREMENT_STATISTIC_NOTES={
    'reported_existing_strength':'来源在该统计日和范围报列的现有人数；不是本局当前人员或后续日期的开局人数。',
    'planned_replacement':'来源拟补充人数；不证明已经补入，不能自行转成人员增补事件或库存。',
    'reported_strength_including_plan':'含拟补充的小计或合计；与现有和计划分项重叠，不能再次相加。',
    'documented_partial_reduction':'来源能明确的部分减员；不是全部损失、精确阵亡或完整总数的上限，不用作扣兵配额。',
    'reported_reduction':'来源在所列期间与总体的减员；分类和范围以来源为准，不等于阵亡或本局战斗伤亡，不与重叠分项再相加。',
}


def _measurements(rows,sources,units,identities):
    """Preserve the denominator and report precision; never materialize a count."""
    from .historical_initial import _fields,_text,_identity,_evidence
    if not isinstance(rows,list) or len(rows)>128:raise ValueError('阶段数值资料须为有界列表')
    for row in rows:
        _fields(row,{'id','date','unit_ids','metric','quantity','statistic','population','evidence','limitations'},'阶段数值资料字段非法')
        if not _identity(row['id']) or row['id'] in identities:raise ValueError('数值资料ID须全档唯一')
        identities.add(row['id'])
        if (not isinstance(row['unit_ids'],list) or not row['unit_ids'] or len(row['unit_ids'])>32
                or any(not isinstance(i,str) or i not in units for i in row['unit_ids'])
                or len(set(row['unit_ids']))!=len(row['unit_ids'])):
            raise ValueError('数值资料须关联不重复的已登记单位')
        _fields(row['date'],{'label','precision'},'数值资料日期非法')
        if not _text(row['date']['label']) or row['date']['precision'] not in ('hour','day','period','range'):
            raise ValueError('数值资料须保留原有日期精度')
        metric=row['metric'];statistic=row['statistic']
        if not isinstance(metric,str) or metric not in MEASUREMENT_UNITS or not isinstance(statistic,str) or statistic not in MEASUREMENT_STATISTICS:
            raise ValueError('数值资料指标或统计口径未登记')
        if statistic in ('replacement_basis','ordered_detachment','reported_enemy_group','reported_strength','reported_casualties',
                         *MEASUREMENT_STATISTIC_NOTES) and metric!='personnel':
            raise ValueError('人员统计口径不能换算为装备或库存')
        if ((statistic=='reported_equipment' and metric not in ('horses','artillery','small_arms'))
                or (statistic=='reported_stock' and metric not in ('ammunition','food','fuel'))
                or (statistic=='reported_retreat_group' and metric not in ('personnel','horses'))):
            raise ValueError('装备、库存和退却群体须保留相符的指标类别')
        for field in ('population','limitations'):
            if not _text(row[field]) or len(row[field])>2000:raise ValueError('数值资料统计对象及限制须明确、有界')
        _evidence(row['evidence'],sources)
        q=row['quantity'];_fields(q,{'relation','lower','upper','unit'},'数值资料数量关系非法')
        if q['relation'] not in ('eq','approx','gt','range') or q['unit']!=MEASUREMENT_UNITS[metric]:
            raise ValueError('数值资料须区分明确数、约数、超过与区间，并保留指标单位')
        for value in (q['lower'],*([q['upper']] if q['upper'] is not None else [])):
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e12:
                raise ValueError('数值资料数量须为有限非负数')
            if metric in ('personnel','horses','artillery','small_arms','ammunition') and type(value) is not int:
                raise ValueError('人员与分类装备计数须为整数')
        if ((q['relation']=='gt' and q['upper'] is not None)
                or (q['relation'] in ('eq','approx') and q['upper']!=q['lower'])
                or (q['relation']=='range' and (q['upper'] is None or q['upper']<q['lower']))):
            raise ValueError('数值资料上下界与数量关系不一致；约数不伪造误差范围')


def validate(definition):
    from .historical_initial import _fields,_text,_identity,_evidence
    sources=definition['sources'];units={u['id']:u for u in definition['units']};events=set()
    for phase in definition['phases']:
        operations=phase.get('operations',[]);relations=phase.get('relations',[])
        if not isinstance(operations,list) or len(operations)>128 or not isinstance(relations,list) or len(relations)>256:
            raise ValueError('阶段史料事件/关系须为有界列表')
        for op in operations:
            fields={'id','kind','date','unit_ids','places','description','evidence','limitations'}
            if isinstance(op,dict) and 'unit_scopes' in op:fields.add('unit_scopes')
            _fields(op,fields,'阶段史料事件字段非法')
            if not _identity(op['id']) or op['id'] in events or not isinstance(op['kind'],str) or op['kind'] not in KINDS:
                raise ValueError('史料事件ID须全档唯一，类型须已登记')
            events.add(op['id'])
            _fields(op['date'],{'label','precision'},'史料事件日期非法')
            if not _text(op['date']['label']) or not isinstance(op['date']['precision'],str) or op['date']['precision'] not in ('hour','day','period','range'):
                raise ValueError('史料事件须保留钟点、日、时段或范围精度')
            if (not isinstance(op['unit_ids'],list) or not op['unit_ids'] or len(op['unit_ids'])>32
                    or any(not isinstance(i,str) or i not in units for i in op['unit_ids'])
                    or len(set(op['unit_ids']))!=len(op['unit_ids'])):
                raise ValueError('史料事件须关联不重复的已登记单位')
            for key in ('description','limitations'):
                if not _text(op[key]):raise ValueError('史料事件描述及核验限制不可为空')
            _evidence(op['evidence'],sources)
            if 'unit_scopes' in op:
                scopes=op['unit_scopes']
                if not isinstance(scopes,dict) or set(scopes)!=set(op['unit_ids']):
                    raise ValueError('事件投入范围须逐项覆盖且仅覆盖关联单位')
                for scope in scopes.values():
                    _fields(scope,{'extent','scope','evidence'},'事件单位投入范围字段非法')
                    if (not isinstance(scope['extent'],str) or scope['extent'] not in ('whole','elements','reference')
                            or not _text(scope['scope']) or len(scope['scope'])>2000):
                        raise ValueError('事件须区分全建制、部分投入及仅关联参考并说明范围')
                    _evidence(scope['evidence'],sources)
            if not isinstance(op['places'],list) or len(op['places'])>16:raise ValueError('史料事件地名须为有界列表')
            for place in op['places']:
                _fields(place,{'name','position','evidence'},'史料事件地名字段非法')
                if not _text(place['name']):raise ValueError('史料地名不可为空')
                _evidence(place['evidence'],sources);p=place['position']
                if p is not None:
                    _fields(p,{'kind','lat','lng','uncertainty_km','note'},'地名位置须声明坐标性质与误差')
                    if (p['kind'] not in ('place_reference','deployment_area_reference') or not _text(p['note'])
                            or any(type(p[k]) not in (int,float) or not math.isfinite(p[k]) for k in ('lat','lng','uncertainty_km'))
                            or not -90<=p['lat']<=90 or not -180<=p['lng']<=180 or not 0<=p['uncertainty_km']<=2000):
                        raise ValueError('史料地名坐标或精度非法')
        ids=set();parents={kind:{} for kind in RELATIONS}
        for rel in relations:
            _fields(rel,{'id','kind','parent_id','child_id','scope','evidence'},'阶段史料关系字段非法')
            if (not _identity(rel['id']) or rel['id'] in ids or not isinstance(rel['kind'],str) or rel['kind'] not in RELATIONS
                    or any(not isinstance(rel[k],str) or rel[k] not in units for k in ('parent_id','child_id'))
                    or rel['parent_id']==rel['child_id'] or not _text(rel['scope'])):
                raise ValueError('阶段史料关系身份或范围非法')
            if units[rel['parent_id']]['team']!=units[rel['child_id']]['team']:raise ValueError('史料指挥/支援关系不能跨对战阵营')
            ids.add(rel['id']);_evidence(rel['evidence'],sources)
            if rel['kind']!='support' and rel['child_id'] in parents[rel['kind']]:
                raise ValueError('同阶段同类主指挥关系不能重复；争议须在范围中说明')
            parents[rel['kind']].setdefault(rel['child_id'],[]).append(rel['parent_id'])
        for tree in parents.values():
            def visit(node,path):
                if node in path:raise ValueError('阶段史料关系成环')
                for parent in tree.get(node,[]):visit(parent,path|{node})
            for node in tree:visit(node,set())
        _measurements(phase.get('measurements',[]),sources,units,events)


def find(snapshot,operation_id):
    for phase in snapshot['definition']['phases']:
        for op in phase.get('operations',[]):
            if op['id']==operation_id:return phase,op
    raise ValueError('固定历史版本没有此事件关联：'+str(operation_id))


def bind_events(pack,initial):
    if initial is None:return
    known={op['id']:p['id'] for p in initial['definition']['phases'] for op in p.get('operations',[])}
    seen=set()
    for event in pack['events']:
        key=event.get('event_key')
        if key in known:
            if key in seen:raise ValueError('同一史料事件不能绑定多个回放帧')
            seen.add(key);event['historical_binding']={'operation_id':key,'phase_id':known[key]}


def frame_binding(initial,event):
    binding=event.get('historical_binding')
    if binding is None:return None
    if (not initial or not isinstance(binding,dict) or set(binding)!={'operation_id','phase_id'}
            or event.get('event_key')!=binding['operation_id']):raise ValueError('回放事件历史关联非法')
    phase,op=find(initial,binding['operation_id'])
    if phase['id']!=binding['phase_id']:raise ValueError('回放事件阶段关联不一致')
    ids=set(op['unit_ids']);units=initial['definition']['units']
    return {'phase_id':phase['id'],**copy.deepcopy(op),
        'units':[{k:u[k] for k in ('id','name','team')} for u in units if u['id'] in ids],
        'relations':[copy.deepcopy(r) for r in phase.get('relations',[]) if r['parent_id'] in ids or r['child_id'] in ids]}


def observation(session,args):
    from . import historical_initial as hi
    fields={'kind','query','phase_id','unit_id','offset','limit','definition_hash'}
    if not isinstance(args,dict) or set(args)-fields:raise ValueError('史料事件检索字段非法')
    kind=args.get('kind','operations')
    if kind not in ('operations','relations','measurements'):raise ValueError('史料关联检索类型非法')
    snapshot=session.get('war_state',{}).get('historical_initial')
    if snapshot is None:return {'ok':False,'error':'当前战局未冻结逐阶段历史编制，无法读取事件关联'}
    hi.restore(snapshot)
    if args.get('definition_hash') and args['definition_hash']!=snapshot['definition_hash']:
        raise ValueError('史料版本已变化，请重新读取第一页')
    current=(session.get('war_state',{}).get('history_replay',{}).get('source_operation') or {}).get('phase_id',snapshot['phase_id'])
    phase_id=args.get('phase_id',current)
    phase=next((p for p in snapshot['definition']['phases'] if p['id']==phase_id),None)
    if not phase:raise ValueError('固定历史版本没有所选阶段')
    offset=args.get('offset',0);limit=args.get('limit',4)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=8:
        raise ValueError('史料关联每页1至8项，偏移须为非负整数')
    units={u['id']:u for u in snapshot['definition']['units']};unit_id=args.get('unit_id')
    if unit_id is not None and (not isinstance(unit_id,str) or unit_id not in units):raise ValueError('史料关联单位不存在')
    query=args.get('query','')
    if not isinstance(query,str):raise ValueError('史料检索关键词须为文本')
    rows=[];unfiltered_total=0
    for row in phase.get(kind,[]):
        identities=[row['parent_id'],row['child_id']] if kind=='relations' else row['unit_ids']
        if unit_id and unit_id not in identities:continue
        unfiltered_total+=1
        text=' '.join([str(row),*[units[i]['name'] for i in identities]])
        if query and query.lower() not in text.lower():continue
        rows.append(copy.deepcopy(row))
    page=rows[offset:offset+limit];used=set();people=set()
    for row in page:
        people.update([row['parent_id'],row['child_id']] if kind=='relations' else row['unit_ids'])
        for ev in [row['evidence'],*[p['evidence'] for p in row.get('places',[])]]:
            used.update(e['source_id'] for e in ev)
    return {'ok':True,'readonly':True,'scope':MEASUREMENT_SCOPE if kind=='measurements' else SCOPE,'phase_id':phase_id,
        **({'statistic_notes':{row['statistic']:MEASUREMENT_STATISTIC_NOTES[row['statistic']]for row in page
                              if row['statistic']in MEASUREMENT_STATISTIC_NOTES}}if kind=='measurements'else {}),
        'definition_hash':snapshot['definition_hash'],'total':len(rows),'offset':offset,kind:page,
        'query':query,'query_semantics':'literal_substring','unfiltered_total':unfiltered_total,
        'query_note':'query按文字子串筛选，不是语义检索或通配符；读取完整阶段须省略query并沿next_args读完。空筛选不表示本阶段无资料。',
        'unfiltered_args':{**args,'kind':kind,'query':'','phase_id':phase_id,'offset':0,'limit':limit,
            'definition_hash':snapshot['definition_hash']} if query else None,
        'units':[{k:units[i][k] for k in ('id','name','team')} for i in sorted(people)],
        'sources':{i:copy.deepcopy(snapshot['definition']['sources'][i]) for i in sorted(used)},
        'next_args':{**args,'kind':kind,'phase_id':phase_id,'offset':offset+limit,'limit':limit,
            'definition_hash':snapshot['definition_hash']} if offset+limit<len(rows) else None}
