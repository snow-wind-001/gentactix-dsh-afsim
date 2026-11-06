"""Source hierarchy and task organization over immutable executable leaves.

No combat or manpower is calculated here. A task split/merge changes command
membership only; existing movement orders are required for physical assembly.
"""
import copy
import uuid
from . import commands,missions

VERSION='force-organization-1'
TREE_VERSION='force-organization-2'
OBSERVATION_VERSION='force-observation-2'
MEMBER_FIELDS={
    'command_id':'本执行成员的命令ID，用于现有单位命令接口；不是上级ID。',
    'command_chain':'本成员的上级指挥ID链，最高上级到直接上级；不是本页成员名单。计算分队的历史父单位可出现在链中。',
    'command_path':'与command_chain逐项对应的上级名称、类型和依据；临时组织覆盖开局指挥。',
    'administrative_path':'历史行政参考的上级路径，不授予当前行动指挥权。',
    'available':'仅表示人员等物理状态可用；不代表已到场、调用者权限或任意动作合法。',
    'operational_status':'ready仅表示物理可用且已到场；动作仍须通过能力、资源及命令校验。'}
NODE_FIELDS={
    'execution_count':'按本次hierarchy统计的执行叶子数；command模式只计当前指挥成员，与members查询一致。',
    'totals':'该节点按本次hierarchy选择的唯一叶子汇总；未列余部不计入。',
    'historical_totals':'行政参考汇总；临时任务群为null，不能与totals相加。',
    'command_execution_count':'开局或兼容指挥结构的覆盖数，含后来临时抽调的参考；实际指挥看effective_execution_count。',
    'effective_execution_count':'当前互斥指挥覆盖，排除已经配属其他临时指挥的叶子。',
    'child_ids':'所选来源树或临时群的结构子节点；抽调不删除来源节点，实际叶子沿members分页。'}


def leaf_key(team,unit):
    return missions.digest([team,unit.get('calculation_unit_id'),unit.get('historical_unit_id'),unit['name']])


def leaves(session):
    return {leaf_key(entry['team'],unit):(identity,entry,unit)
            for identity,(entry,unit) in commands.resolve_units(session).items()}


def state(session):
    return copy.deepcopy(session.get('force_organization') or {'version':VERSION,'revision':0,'groups':[],'events':[]})


def _upgrade(value):
    value=copy.deepcopy(value);value['version']=TREE_VERSION
    for group in value['groups']:group.setdefault('parent_id',None)
    return value


def _graph(value):
    index={g['id']:g for g in value['groups']};children={i:[] for i in index}
    for group in index.values():
        parent=group.get('parent_id')
        if parent is not None:
            if parent not in index or index[parent]['team']!=group['team']:
                raise ValueError('临时上级不存在或跨阵营')
            children[parent].append(group['id'])
    depth={}
    for identity in index:
        chain=[];cursor=identity
        while cursor is not None:
            if cursor in chain:raise ValueError('临时指挥层级存在循环')
            chain.append(cursor)
            if len(chain)>32:raise ValueError('临时指挥层级最多32层')
            cursor=index[cursor].get('parent_id')
        depth[identity]=len(chain)-1
    members={}
    for identity in sorted(index,key=lambda i:depth[i],reverse=True):
        members[identity]=list(dict.fromkeys(index[identity]['members']+
            [key for child in children[identity] for key in members[child]]))
    return index,children,depth,members


def _prune(value):
    """Remove empty terminal groups, preserving HQs with surviving descendants."""
    while True:
        parents={g.get('parent_id') for g in value['groups']}
        keep=[g for g in value['groups'] if g['members'] or g['id'] in parents]
        if len(keep)==len(value['groups']):return value
        value['groups']=keep


def validate(session):
    value=state(session);index=leaves(session)
    if (value.get('version') not in (VERSION,TREE_VERSION) or type(value.get('revision')) is not int or value['revision']<0
            or not isinstance(value.get('groups'),list) or len(value['groups'])>1024 or not isinstance(value.get('events'),list)):
        raise ValueError('任务组织格式或版本非法')
    seen=set();groups=set()
    for g in value['groups']:
        fields={'id','label','team','members','assumption'}|({'parent_id'} if value['version']==TREE_VERSION else set())
        if (set(g)!=fields or not isinstance(g['id'],str)
                or not g['id'] or g['id'] in groups or not isinstance(g['label'],str)
                or not g['label'].strip() or len(g['label'])>80 or not isinstance(g['assumption'],str)
                or not g['assumption'].strip() or len(g['assumption'])>2000 or g['team'] not in ('red','blue')
                or not isinstance(g['members'],list) or (not g['members'] and value['version']==VERSION)
                or (g.get('parent_id') is not None and not isinstance(g['parent_id'],str))):
            raise ValueError('任务群身份或依据非法')
        groups.add(g['id'])
        for key in g['members']:
            if key not in index or key in seen or index[key][1]['team']!=g['team']:
                raise ValueError('任务群成员未知、跨阵营或重复配属')
            seen.add(key)
    _,_,_,expanded=_graph(value)
    if any(not members for members in expanded.values()):raise ValueError('临时编组必须有直接或间接执行下级')
    return True


def _summary(rows):
    def total(values):return sum(values) if all(type(v) in (int,float) for v in values) else None
    result={k:total([u.get('personnel',{}).get(k) for _,_,u in rows])
            for k in ('committed','current','casualties','noncombat_losses')}
    result['units']=len(rows)
    result['equipment']={k:total([next((e.get('operational') for e in u.get('equipment',[]) if e.get('category')==k),None) for _,_,u in rows])
                         for k in ('armor','artillery','air_defense','engineer','transport')}
    return result


def view(session):
    validate(session);index=leaves(session);world=session.get('war_state') or {}
    spec=world.get('mission',{}).get('definition',{})
    initial=world.get('historical_initial') or (spec.get('historical_calculation') or {}).get('initial')
    sources=(initial or {}).get('definition',{}).get('units',[])
    phase=(initial or {}).get('phase_id');nodes={}
    for u in sources:
        presence=next((p['status'] for p in u['presence'] if p['phase_id']==phase),'unverified')
        nodes[u['id']]={'id':u['id'],'name':u['name'],'team':u['team'],'parent_id':u['parent_id'],
            'role':u['role'],'echelon':u['echelon'],'presence':presence,'evidence':copy.deepcopy(u['evidence']),
            'children_coverage':copy.deepcopy(u.get('children_coverage',{'status':'unknown','scope':'史料未证明下级完整；汇总仅限当前投入叶子','evidence':[]})),
            'children':[],'execution_ids':[],'own_keys':[]}
    for key,(identity,entry,u) in index.items():
        source=u.get('historical_unit_id');node_id=source or 'execution:'+key
        if node_id not in nodes:
            nodes[node_id]={'id':node_id,'name':u['name'],'team':entry['team'],'parent_id':None,
                'role':'formation','echelon':u.get('echelon','计算编组'),'presence':'calculation_only',
                'evidence':[],'children':[],'execution_ids':[],'own_keys':[]}
        nodes[node_id]['own_keys'].append(key)
    for node in nodes.values():
        parent=node['parent_id']
        if parent in nodes:nodes[parent]['children'].append(node['id'])
    memo={}
    def collect(identity,trail=()):
        if identity in trail:raise ValueError('指挥树存在循环')
        if identity not in memo:
            n=nodes[identity];keys=set(n['own_keys'])
            for child in n['children']:keys.update(collect(child,trail+(identity,)))
            memo[identity]=keys
        return memo[identity]
    for node in nodes.values():
        keys=sorted(collect(node['id']));node['execution_ids']=[index[k][0] for k in keys]
        node['totals']=_summary([index[k] for k in keys]);node.pop('own_keys')
        node['scope']='当前投入叶子汇总；未部署、未列下级和历史名册缺项不自动补兵'
    organization=state(session);task_index,task_children,depth,expanded=_graph(organization)
    groups=[]
    def append_group(identity):
        group=task_index[identity]
        groups.append({**group,'parent_id':group.get('parent_id'),'children':task_children[identity],
            'depth':depth[identity],'direct_member_ids':[index[k][0] for k in group['members']],
            'member_ids':[index[k][0] for k in expanded[identity]],
            'totals':_summary([index[k] for k in expanded[identity]]),'historical_reorganization':False})
        for child in task_children[identity]:append_group(child)
    for group in task_index.values():
        if group.get('parent_id') is None:append_group(group['id'])
    assigned={index[k][0] for g in organization['groups'] for k in g['members']}
    for node in nodes.values():node['effective_execution_ids']=[i for i in node['execution_ids'] if i not in assigned]
    from . import initial_command
    opening=initial_command.from_world(world);extra={}
    if opening:
        children={i:[] for i in nodes}
        for node in nodes.values():
            node['command_parent_id']=opening['parents'].get(node['id'],node['parent_id'])
            if node['command_parent_id'] in children:children[node['command_parent_id']].append(node['id'])
        own={i:[] for i in nodes}
        for key,(_,entry,unit) in index.items():own[unit.get('historical_unit_id') or 'execution:'+key].append(key)
        cache={}
        def collect_command(identity):
            if identity not in cache:
                cache[identity]=set(own[identity])
                for child in children[identity]:cache[identity].update(collect_command(child))
            return cache[identity]
        for node in nodes.values():
            keys=sorted(collect_command(node['id']));active=[k for k in keys if index[k][0] not in assigned]
            node.update(command_children=children[node['id']],command_execution_ids=[index[k][0] for k in keys],
                command_totals=_summary([index[k] for k in keys]),effective_execution_ids=[index[k][0] for k in active],
                effective_command_totals=_summary([index[k] for k in active]))
        extra={'command_baseline':initial_command.manifest(opening),
            'command_roots':[n['id'] for n in nodes.values() if n['command_parent_id'] not in nodes]}
    from . import unit_participation
    return {**extra,'version':organization['version'],'revision':organization['revision'],'nodes':list(nodes.values()),
        **({'participation_supported':True} if unit_participation.supported(world) else {}),
        'roots':[n['id'] for n in nodes.values() if n['parent_id'] not in nodes],
        'execution_ids':[r[0] for r in index.values()],
        'inactive_ids':[r[0] for r in index.values() if not commands.available(r[2])],
        'totals':{t:_summary([r for r in index.values() if r[1]['team']==t]) for t in ('red','blue')},
        'groups':groups,'events':state(session)['events'][-12:],
        'scope':'历史建制只读；任务群为当前临时指挥关系。分兵不生成人员，合兵不瞬移或合并士兵账本。'+(initial_command.SCOPE if opening else '')}


def member_ids(session,group_id,*,hierarchy='command'):
    v=view(session)
    for g in v['groups']:
        if g['id']==group_id:return g['member_ids']
    for n in v['nodes']:
        if n['id']==group_id:return n.get('command_execution_ids',n['execution_ids']) if hierarchy=='command' else n['execution_ids']
    raise ValueError('指挥节点或任务群不存在')


def effective_member_ids(session,group_id):
    value=view(session)
    for group in value['groups']:
        if group['id']==group_id:return group['member_ids']
    for node in value['nodes']:
        if node['id']==group_id:return node['effective_execution_ids']
    raise ValueError('指挥节点或任务群不存在')


def command_chains(organization):
    index,_,_,_=_graph(organization);result={}
    for group in index.values():
        cursor=group['id'];chain=[]
        while cursor is not None:
            chain.append(cursor);cursor=index[cursor].get('parent_id')
        for key in group['members']:result[key]=chain[::-1]
    return result


def command_chain(session,key):
    return effective_command_chains(session).get(key,[])


def effective_command_chains(session):
    from . import initial_command
    result=command_chains(state(session));world=session.get('war_state') or {}
    opening=initial_command.from_world(world)
    initial=world.get('historical_initial') or (world.get('mission',{}).get('definition',{}).get('historical_calculation') or {}).get('initial')
    parents=opening['parents'] if opening else {u['id']:u['parent_id'] for u in (initial or {}).get('definition',{}).get('units',[])}
    for key,(_,entry,unit) in leaves(session).items():
        if key in result:continue
        identity=unit.get('historical_unit_id');cursor=identity if unit.get('calculation_unit_id') else parents.get(identity)
        chain=[]
        while cursor is not None:
            if cursor in chain:raise ValueError('当前指挥链成环')
            chain.append(cursor);cursor=parents.get(cursor)
        result[key]=chain[::-1]
    return result


def observation(session,args):
    """Bounded native tool pages; host state stays outside model context."""
    if set(args)-{'offset','limit','node_id','team','kind','revision','hierarchy'}:raise ValueError('编制查询字段非法')
    offset=args.get('offset',0);limit=args.get('limit',12);kind=args.get('kind','nodes')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=32:
        raise ValueError('编制页码须为非负整数，每页1至32项')
    if kind not in ('nodes','groups','members') or args.get('team') not in (None,'red','blue'):raise ValueError('编制查询类型或阵营非法')
    value=view(session)
    hierarchy=args.get('hierarchy','command')
    if hierarchy not in ('historical','command'):raise ValueError('编制层次须为历史建制或作战指挥')
    if 'revision' in args and (type(args['revision']) is not int or args['revision']!=value['revision']):
        raise ValueError('编制修订已变化，请从第一页重新读取成员')
    if kind=='members':
        selected=set(value['execution_ids'])
        if args.get('node_id'):
            node=next((n for n in value['nodes'] if n['id']==args['node_id']),None)
            group=next((g for g in value['groups'] if g['id']==args['node_id']),None)
            if group is not None:selected=set(group['member_ids'])
            elif node is not None:selected=set(node['effective_execution_ids'] if hierarchy=='command' else node['execution_ids'])
            else:raise ValueError('指挥节点或任务群不存在')
        organization=state(session)
        owners={key:g['id'] for g in organization['groups'] for key in g['members']}
        chains=effective_command_chains(session)
        nodes={n['id']:n for n in value['nodes']};groups={g['id']:g for g in value['groups']}
        def path(chain,basis):
            return [{'id':identity,'name':groups[identity]['label'] if identity in groups else nodes[identity]['name'],
                     'kind':'temporary_group' if identity in groups else 'historical_node','basis':basis} for identity in chain]
        def administrative(unit):
            identity=unit.get('historical_unit_id');cursor=identity if unit.get('calculation_unit_id') else nodes.get(identity,{}).get('parent_id')
            chain=[]
            while cursor in nodes:
                chain.append(cursor);cursor=nodes[cursor]['parent_id']
            return path(chain[::-1],'administrative_reference')
        from . import campaign
        matching=[(key,row) for key,row in leaves(session).items() if row[0] in selected
                  and (not args.get('team') or row[1]['team']==args['team'])]
        total=len(matching)
        def member(item):
            key,(identity,entry,unit)=item;wait=campaign.release_seconds(session['war_state'],unit)
            return {'leaf_key':key,'command_id':identity,'historical_unit_id':unit.get('historical_unit_id'),
                'calculation_unit_id':unit.get('calculation_unit_id'),'name':entry['name'],'team':entry['team'],
                'task_group_id':owners.get(key),'available':commands.available(unit),
                'arrival_wait_seconds':wait,'operational_status':('incapacitated' if not commands.available(unit) else
                                                               'waiting_arrival' if wait>0 else 'ready'),
                'command_chain':chains.get(key,[]),'command_path':path(chains.get(key,[]),
                    'temporary_assignment' if key in owners else 'source_opening' if value.get('command_baseline') else 'legacy_administrative_fallback'),
                'administrative_path':administrative(unit),'personnel':copy.deepcopy(unit.get('personnel'))}
        rows=[member(item) for item in matching[offset:offset+limit]]
    else:rows=value[kind]
    if kind!='members' and args.get('node_id'):
        ids=set(member_ids(session,args['node_id'],hierarchy=hierarchy))
        rows=[r for r in rows if ids.intersection(r.get('command_execution_ids',r.get('execution_ids',r.get('member_ids',[]))) if hierarchy=='command' else r.get('execution_ids',r.get('member_ids',[])))]
    if args.get('team'):rows=[r for r in rows if r['team']==args['team']]
    page=rows if kind=='members' else rows[offset:offset+limit]
    if kind!='members':total=len(rows)
    # A root may have hundreds of descendants: expose counts and read leaves
    # through the existing paged observation tool rather than repeat them here.
    if kind!='members':
        executed={row[0]:row for row in leaves(session).values()}
        def node_details(row):
            historical=row.get('execution_ids',[]);effective=row.get('effective_execution_ids',row.get('member_ids',[]))
            selected=effective if hierarchy=='command' else row.get('execution_ids',row.get('member_ids',[]))
            children=row.get('command_children',row.get('children',[])) if hierarchy=='command' else row.get('children',[])
            return {k:v for k,v in row.items() if k not in ('members','execution_ids','effective_execution_ids','direct_member_ids','member_ids','children','command_execution_ids','command_children')}|{
                'execution_count':len(selected),'totals':_summary([executed[i] for i in selected]),
                'historical_totals':copy.deepcopy(row['totals']) if 'execution_ids' in row else None,
                'historical_execution_count':len(historical),'effective_execution_count':len(effective),
                'direct_execution_count':len(row.get('direct_member_ids',[])),
                'command_execution_count':len(row.get('command_execution_ids',row.get('execution_ids',row.get('member_ids',[])))),
                'child_ids':children[:32],'child_count':len(children)}
        page=[node_details(row) for row in page]
    return {'ok':True,'observation_version':OBSERVATION_VERSION,'kind':kind,
        'reference_scope':'session','session_id':session.get('id'),
        'field_semantics':copy.deepcopy(MEMBER_FIELDS if kind=='members' else NODE_FIELDS),
        **({'command_baseline':copy.deepcopy(value['command_baseline'])} if value.get('command_baseline') else {}),
        'scope':value['scope'],'hierarchy':hierarchy,'revision':value['revision'],'totals':value['totals'],
        'totals_scope':'all_deployed_leaves_not_selection',
        'items':page,'total':total,'next_args':{**args,'offset':offset+limit,'limit':limit,'revision':value['revision']} if offset+limit<total else None}


def _names(label,assumption):
    if not isinstance(label,str) or not label.strip() or len(label)>80 or not isinstance(assumption,str) or not assumption.strip() or len(assumption)>2000:
        raise ValueError('必须给出任务群名称与临时配属依据')


def _finish(session,value,kind,before,detail):
    value['revision']+=1
    value['events'].append({'id':uuid.uuid4().hex,'revision':value['revision'],'kind':kind,
        'turn':session.get('turn_count',0),'time':(session.get('war_state') or {}).get('current_time'),
        'before':before,'after':copy.deepcopy(value['groups']),'detail':detail,
        'world_digest':missions.digest(session.get('war_state')),'source':'human_task_organization'})
    validate({**session,'force_organization':value})
    return value


def _group_identity(value):
    """Short session-local references; keep all existing and retired IDs intact.

    Revisions already serialize organization writes. API routes and native tool
    contexts bind the session, and phase handoffs carry IDs and revision together.
    Older imported arbitrary IDs remain valid and must not collide with new ones.
    """
    used={g['id'] for g in value['groups']}
    for event in value['events']:
        if not isinstance(event,dict):continue
        for field in ('before','after'):
            rows=event.get(field,[])
            if isinstance(rows,list):used.update(g['id'] for g in rows if isinstance(g,dict) and isinstance(g.get('id'),str))
    sequence=value['revision']+1
    while 'task:'+str(sequence) in used:sequence+=1
    return 'task:'+str(sequence)


def detach(session,unit_ids,label,assumption,*,parent_id=None):
    commands.assert_writable(session)
    _names(label,assumption);validate(session)
    if not isinstance(unit_ids,list) or not unit_ids or len(unit_ids)!=len(set(unit_ids)):
        raise ValueError('请选择不重复的现有下级单位')
    all_units=commands.resolve_units(session)
    if any(i not in all_units or all_units[i][0].get('ambiguous') for i in unit_ids):
        raise ValueError('任务群含未知或身份歧义单位')
    teams={all_units[i][0]['team'] for i in unit_ids}
    if len(teams)!=1:raise ValueError('不能跨阵营编组')
    team=next(iter(teams));keys=[leaf_key(team,all_units[i][1]) for i in unit_ids]
    value=_upgrade(state(session));before=copy.deepcopy(value['groups'])
    if parent_id is not None:
        parent=next((g for g in value['groups'] if g['id']==parent_id),None)
        if parent is None or parent['team']!=team:raise ValueError('临时上级不存在或跨阵营')
    for g in value['groups']:g['members']=[k for k in g['members'] if k not in keys]
    value['groups'].append({'id':_group_identity(value),'label':label.strip(),'team':team,'members':keys,
        'parent_id':parent_id,'assumption':assumption.strip()})
    _prune(value)
    return _finish(session,value,'detach',before,assumption)


def merge(session,group_ids,label,assumption):
    commands.assert_writable(session)
    _names(label,assumption);validate(session);value=_upgrade(state(session))
    if not isinstance(group_ids,list) or len(group_ids)<2 or len(set(group_ids))!=len(group_ids):
        raise ValueError('合兵须选择至少两个不同任务群')
    selected=[g for g in value['groups'] if g['id'] in group_ids]
    if len(selected)!=len(group_ids) or len({g['team'] for g in selected})!=1:
        raise ValueError('任务群缺失或跨阵营，不能合兵')
    if len({g['parent_id'] for g in selected})!=1:raise ValueError('只能合编同级任务群，请先明确转隶关系')
    before=copy.deepcopy(value['groups'])
    identity=_group_identity(value)
    for group in value['groups']:
        if group['parent_id'] in group_ids:group['parent_id']=identity
    value['groups']=[g for g in value['groups'] if g['id'] not in group_ids]
    value['groups'].append({'id':identity,'label':label.strip(),'team':selected[0]['team'],'parent_id':selected[0]['parent_id'],
        'members':[k for g in selected for k in g['members']],'assumption':assumption.strip()})
    return _finish(session,value,'merge',before,assumption)


def wrap(session,group_ids,label,assumption):
    """Create a common superior; lower group identities and leaf owners survive."""
    commands.assert_writable(session);_names(label,assumption);validate(session)
    value=_upgrade(state(session));before=copy.deepcopy(value['groups'])
    if not isinstance(group_ids,list) or len(group_ids)<2 or len(set(group_ids))!=len(group_ids):
        raise ValueError('统一指挥须选择至少两个不同的同级任务群')
    selected=[g for g in value['groups'] if g['id'] in group_ids]
    if (len(selected)!=len(group_ids) or len({g['team'] for g in selected})!=1
            or len({g['parent_id'] for g in selected})!=1):raise ValueError('统一指挥仅支持同阵营同级任务群')
    identity=_group_identity(value);parent=selected[0]['parent_id']
    for group in selected:group['parent_id']=identity
    value['groups'].append({'id':identity,'label':label.strip(),'team':selected[0]['team'],
        'parent_id':parent,'members':[],'assumption':assumption.strip()})
    return _finish(session,value,'wrap',before,assumption)


def reparent(session,group_id,parent_id,assumption):
    commands.assert_writable(session);_names('临时转隶',assumption);validate(session)
    value=_upgrade(state(session));before=copy.deepcopy(value['groups'])
    group=next((g for g in value['groups'] if g['id']==group_id),None)
    if group is None:raise ValueError('待转隶任务群不存在')
    group['parent_id']=parent_id
    # Check cycles before pruning; otherwise invalid ancestors could disappear.
    _graph(value);_prune(value)
    return _finish(session,value,'reparent',before,assumption)


def queue(session,group_id,order):
    if session.get('simulation_mode')=='replay' or session.get('product_mode')=='analysis':
        raise ValueError('严格史料回溯不能改写部队命令')
    members=effective_member_ids(session,group_id)
    if not members:raise ValueError('此节点没有当前指挥下级；参考节点不部署，已临时配属下级请通过其任务指挥链下令')
    index=commands.resolve_units(session)
    ids=[i for i in members if commands.available(index[i][1])]
    if not ids:raise ValueError('此编组已无可行动下级；原人员与战损记录保留')
    if not isinstance(order,dict) or set(order)-(set(commands.DRAFT_FIELDS)-{'id','unit_id'}):
        raise ValueError('编组命令字段非法')
    cs=commands.state(session)
    # Preserve unrelated orders and route every selected leaf through the same
    # permission, capability, resource and distance checks as individual orders.
    retained=[{k:copy.deepcopy(v) for k,v in o.items() if k in commands.DRAFT_FIELDS}
              for o in cs['orders'] if o['unit_id'] not in members]
    drafts=[dict(copy.deepcopy(order),unit_id=i) for i in ids]
    return commands.replace_queue(session,retained+drafts,control_team=cs['control_team'],
        director=cs['director'],no_fire=cs['no_fire'],intent=cs['intent'])


def continue_session(source, target):
    """Rebind organization and pending human tasks to an already validated phase.

    Returns detached session fields. No physical ledger or live session is edited.
    Exited members and expired/blocked tasks remain explicit in the handoff.
    """
    validate(source)
    old=leaves(source);new=leaves(target)
    old_ids={row[0]:key for key,row in old.items()}
    mapping={identity:new[key][0] for key,(identity,_,_) in old.items() if key in new}
    report={'version':'force-command-handoff-1','source_session_id':source['id'],
        'source_turn':source.get('turn_count',0),'carried':[],'blocked':[],'terminated':[],
        'exited_members':[],'identity_map':mapping,'unit_agent_sessions':'fresh_bindings_required'}
    from . import initial_command
    opening=initial_command.handoff(source.get('war_state') or {},target.get('war_state') or {})
    if opening:report['initial_command']=opening
    fields={}
    if source.get('force_organization') is not None:
        value=state(source);before=copy.deepcopy(value['groups'])
        for group in value['groups']:
            report['exited_members'].extend({'group_id':group['id'],'leaf_key':k,'command_id':old[k][0]}
                for k in group['members'] if k not in new)
            group['members']=[k for k in group['members'] if k in new]
        _prune(value)
        fields['force_organization']=_finish({**target,'force_organization':value},value,
            'phase_handoff',before,{'source_session_id':source['id'],'exited_members':report['exited_members']})
    policy=commands.state(source)
    if any('execution' in r for r in policy.get('task_plans',{}).values()):
        raise ValueError('持续任务跨阶段迁移尚未实现；请保留原局，不能静默丢失任务或重新激活。等待单世界生命周期迁移支持')
    cs=commands.state(target)
    cs.update({k:copy.deepcopy(policy[k]) for k in ('control_team','director','no_fire','intent')})
    cs['unit_agents']=[mapping[i] for i in policy.get('unit_agents',[]) if i in mapping]
    child={**target,**fields,'command_state':cs}
    for order in policy['orders']:
        entry={'command_id':order['id'],'source_unit_id':order['unit_id']}
        identity=mapping.get(order['unit_id'])
        if identity is None or not commands.available(new[old_ids[order['unit_id']]][2]):
            report['terminated'].append({**entry,'reason':'单位退出当前阶段或已失能，未重新补满'})
            continue
        draft={k:copy.deepcopy(order[k]) for k in ('action','duration','destination','air_pool','end_turn','participation') if k in order}
        draft['unit_id']=identity
        if 'target_id' in order:
            if order['target_id'] not in mapping:
                report['terminated'].append({**entry,'reason':'目标已退出当前阶段，须重新指定'})
                continue
            draft['target_id']=mapping[order['target_id']]
        if draft['duration']=='until_turn':
            draft['end_turn']=order['end_turn']-source.get('turn_count',0)+target.get('turn_count',0)
            if draft['end_turn']<=target.get('turn_count',0):
                report['terminated'].append({**entry,'reason':'持续准备命令已到截止回合'})
                continue
        try:
            # Validate each task against the new phase without replacing other tasks.
            candidate=commands.replace_queue({**child,'command_state':{**cs,'orders':[]}},[draft],
                **{k:cs[k] for k in ('control_team','director','no_fire','intent')})['orders'][0]
            report['carried'].append({**entry,'unit_id':identity,'new_command_id':candidate['id']})
        except ValueError as exc:
            candidate={**draft,'id':uuid.uuid4().hex,'status':'blocked','source':'human',
                'created_turn':target.get('turn_count',0),'rule_version':commands.rule_version(child),'reason':str(exc)}
            report['blocked'].append({**entry,'unit_id':identity,'reason':str(exc)})
        if order.get('task_context'):candidate['task_context']=copy.deepcopy(order['task_context'])
        cs['orders'].append(candidate)
    cs['revision']=policy['revision']+1
    task_ids={o.get('task_context',{}).get('task_id') for o in cs['orders']}
    if task_ids-{None}:
        cs['task_plans']={k:copy.deepcopy(v) for k,v in policy.get('task_plans',{}).items() if k in task_ids}
    fields.update(command_state=cs,command_handoff=report)
    if target.get('execution_backend')=='afsim':
        from backend import afsim_air
        afsim_air.validate_reservations(target['war_state'],[
            commands.step_order({**target,**fields},o,cs) for o in cs['orders'] if o['status']!='blocked'])
    commands.validate_saved({**target,**fields})
    return fields
