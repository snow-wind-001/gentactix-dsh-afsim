"""Explicit, frozen opening command relationships; never a historical scheduler."""
import copy
from . import missions

VERSION='historical-command-baseline-1'
WINDOW_DECLARATION_VERSION='source-opening-command-1'
SCOPE='采用所选阶段来源关系作为开局指挥；行政身份保持原样，运行不按史料日期自动转隶，临时任务群优先。'


def relations(snapshot):
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    return [r for r in phase.get('relations',[]) if r['kind'] in ('administrative','operational_command')]


def parents(snapshot):
    from . import historical_initial
    historical_initial.restore(snapshot)
    units={u['id']:u for u in snapshot['definition']['units']};result={i:u['parent_id'] for i,u in units.items()}
    rows=relations(snapshot)
    for kind in ('administrative','operational_command'):
        for row in rows:
            if row['kind']==kind:result[row['child_id']]=row['parent_id']
    for identity in result:
        cursor=identity;seen=set()
        while cursor is not None:
            if cursor not in units or cursor in seen:raise ValueError('开局指挥关系缺失或与行政树合并后成环')
            if units[cursor]['team']!=units[identity]['team']:raise ValueError('开局指挥关系跨阵营')
            seen.add(cursor);cursor=result[cursor]
    return result


def validate_window_declaration(snapshot, value):
    """Opt a registered window into the start phase, never later calendar orders."""
    from . import historical_initial
    fields={'version','phase_id','relation_ids','scope','evidence'}
    if (not isinstance(value,dict) or set(value)!=fields
            or value['version']!=WINDOW_DECLARATION_VERSION
            or value['phase_id']!=snapshot['phase_id']
            or not isinstance(value['scope'],str) or not value['scope'].strip()
            or len(value['scope'])>4000):
        raise ValueError('窗口开局指挥声明须绑定起始来源阶段、版本和采用范围')
    rows=relations(snapshot);ids=value['relation_ids']
    if (not rows or not isinstance(ids,list)
            or any(not isinstance(identity,str) for identity in ids)
            or len(ids)!=len(set(ids)) or set(ids)!={r['id'] for r in rows}):
        raise ValueError('窗口开局指挥须完整引用起始阶段已登记的行政及作战关系')
    historical_initial._evidence(value['evidence'],snapshot['definition']['sources'])
    return rows


def template(snapshot, window=None):
    if window is not None:
        declaration=window['definition'].get('opening_command')
        if declaration is None:return None
        validate_window_declaration(snapshot,declaration)
    if not relations(snapshot):return None
    return {'version':VERSION,'assumption':None}


def validate(snapshot,parameters,*,frozen=False):
    value=parameters.get('initial_command')
    campaign_scope=parameters.get('campaign_scope');window=None
    if campaign_scope:
        candidate=campaign_scope.get('window') if isinstance(campaign_scope,dict) else None
        declared=(isinstance(candidate,dict) and isinstance(candidate.get('definition'),dict)
                  and 'opening_command' in candidate['definition'])
        if not declared:
            if value is not None:raise ValueError('不能把局部阶段配属套用于累计会战；须先明确开局时段与指挥范围')
            return None
        from . import campaign_windows
        from datetime import datetime
        if campaign_scope.get('version')!='campaign-oob-window-1':
            raise ValueError('窗口开局指挥不能套用累计会战范围')
        campaign_windows.validate(snapshot,candidate,frozen=frozen)
        bounds=candidate['definition']['bounds']
        try:
            matching=(datetime.fromisoformat(parameters['clock']['start'])==datetime.fromisoformat(bounds['start'])
                      and datetime.fromisoformat(campaign_scope['planning_end'])==datetime.fromisoformat(bounds['end']))
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError('窗口开局指挥须保留固定模型起点和规划范围') from exc
        if not matching:raise ValueError('窗口开局指挥起点或规划范围不匹配')
        window=candidate
        if value is None:raise ValueError('已声明开局指挥的窗口须填写initial_command采用依据')
    if value is None:
        if relations(snapshot) and not frozen:raise ValueError('本阶段有分时指挥关系，须填写initial_command说明开局采用依据')
        return None
    if (not isinstance(value,dict) or set(value)!={'version','assumption'} or value['version']!=VERSION
            or not isinstance(value['assumption'],str) or not value['assumption'].strip() or len(value['assumption'])>2000):
        raise ValueError('initial_command须使用已支持版本并说明采用来源关系作为开局指挥的估计依据')
    rows=relations(snapshot)
    if not rows:raise ValueError('所选阶段未登记指挥关系，不能凭参数补造开局历史配属')
    tree=parents(snapshot)
    manifest={'version':VERSION,'profile_id':snapshot['profile_id'],'initial_version':snapshot['version'],
        'phase_id':snapshot['phase_id'],'source_definition_hash':snapshot['definition_hash'],
        'relation_ids':[r['id'] for r in rows],'assumption':value['assumption'],'scope':SCOPE}
    if window is not None:
        manifest['window']={k:copy.deepcopy(window[k]) for k in ('id','version','definition_hash')}
        manifest['scope']=('采用固定窗口起始阶段已登记的来源关系作为模型开局；'
            '行政身份保持，临时任务群优先，不按后续日期自动转隶。'
            +window['definition']['opening_command']['scope'])
    manifest['binding_hash']=missions.digest({'manifest':manifest,'parents':tree})
    return {**manifest,'parents':tree}


def from_world(world):
    definition=(world.get('mission') or {}).get('definition') or {}
    binding=definition.get('historical_calculation') or (definition.get('historical_synthetic') or {}).get('base')
    if not binding or 'initial_command' not in binding.get('parameters',{}):return None
    return validate(binding['initial'],binding['parameters'],frozen=True)


def manifest(binding):
    return {k:copy.deepcopy(v) for k,v in binding.items() if k!='parents'} if binding else None


def handoff(before,after):
    source,target=from_world(before),from_world(after)
    if source is None and target is None:return None
    def reference(world,binding):
        rows=(world.get('historical_initial') or {}).get('definition',{}).get('units',[])
        return ({u['id']:u['name'] for u in rows},binding['parents'] if binding else {u['id']:u['parent_id'] for u in rows})
    old_names,old=reference(before,source);new_names,new=reference(after,target);names={**old_names,**new_names}
    changes=[{'unit_id':i,'name':names[i],'before_parent':old.get(i),'after_parent':new.get(i),
        'before_name':names.get(old.get(i),'未列上级'),'after_name':names.get(new.get(i),'未列上级')}
        for i in sorted(set(old)&set(new)) if old[i]!=new[i]]
    a,b=manifest(source),manifest(target)
    return {'source':a,'target':b,'changed':a!=b,'changes':changes,
        'scope':'显式目标初态重新绑定开局指挥依据；继承的临时任务群保持优先，不按历史日期自动执行转隶。'}
