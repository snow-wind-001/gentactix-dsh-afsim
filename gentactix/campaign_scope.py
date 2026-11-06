"""Explicit deployment assumptions over a sourced cumulative campaign OOB.

The original presence records stay immutable. Opting in never upgrades a
campaign participant into a factually confirmed same-day deployment.
"""
from datetime import datetime

LEGACY_VERSION='campaign-oob-deployment-1'
VERSION='campaign-oob-deployment-2'
LOCAL_VERSION='historical-oob-coverage-1'
WINDOW_VERSION='campaign-oob-window-1'


def enabled(parameters):
    return bool(parameters.get('campaign_scope'))


def select(snapshot, window=None, *, frozen=False):
    if window is not None:
        from . import campaign_windows
        return campaign_windows.select(snapshot,window,frozen=frozen)
    rows=snapshot['definition']['units'];index={u['id']:u for u in rows}
    candidates={u['id'] for u in rows if u['role'] in ('formation','support') and
                any(p['status'] in ('reported_present','campaign_participant') for p in u['presence'])}
    ancestors=set()
    for identity in candidates:
        parent=index[identity]['parent_id']
        while parent:
            if parent in candidates:ancestors.add(parent)
            parent=index[parent]['parent_id']
    ids=[u['id'] for u in rows if u['id'] in candidates-ancestors]
    if {index[i]['team'] for i in ids}!={'red','blue'}:
        raise ValueError('会战累计序列仍缺双方地面战斗部队；不能将司令部作为步兵或虚构对手')
    if len(ids)>512:raise ValueError('当前会战部署最多512个不重叠执行单位，须先明确层级与计算范围')
    return ids


def selected(snapshot, parameters):
    """After validation, use the binding's inline window even during restore."""
    return select(snapshot,(parameters.get('campaign_scope') or {}).get('window'),frozen=True)


def coverage(snapshot, identities=None):
    """Expose omitted ancestor scope; existence of a child proves no completeness."""
    ids=select(snapshot) if identities is None else identities;rows=snapshot['definition']['units'];index={u['id']:u for u in rows}
    descendants={}
    for identity in ids:
        parent=index[identity]['parent_id']
        while parent:
            if index[parent]['role'] in ('formation','support'):
                descendants.setdefault(parent,[]).append(identity)
            parent=index[parent]['parent_id']
    return [{'parent_id':u['id'],'name':u['name'],'selected_descendant_ids':descendants[u['id']],
        'children_coverage':u.get('children_coverage',{}).get('status','unknown'),
        'evidence':u.get('children_coverage',{}).get('evidence',[]),
        'scope':'仅汇总已选下级；未列余部数值未知，不能称完整父级兵力'}
        for u in rows if u['id'] in descendants]


def local_coverage(snapshot):
    """New sourced child-coverage metadata opts a local profile into declarations.

    Earlier frozen profiles with no such metadata retain their old contract.
    """
    from . import historical_operations
    declared={u['id'] for u in snapshot['definition']['units'] if 'children_coverage' in u}
    if not declared:return []
    return [r for r in coverage(snapshot,historical_operations.partition(snapshot)) if r['parent_id'] in declared]


def validate_remainders(rows,remainders):
    if not isinstance(remainders,dict) or set(remainders)!={r['parent_id'] for r in rows}:
        raise ValueError('须逐个登记被下级替换父级的余部，不能静默漏计或补造')
    for row in rows:
        declaration=remainders[row['parent_id']]
        if (not isinstance(declaration,dict) or set(declaration)!={'policy','assumption'}
                or declaration['policy'] not in ('excluded_unquantified','covered_by_children')
                or not isinstance(declaration['assumption'],str) or not declaration['assumption'].strip()):
            raise ValueError('余部须明确声明未投入且数量未知，或有证据的完整下级覆盖：'+row['parent_id'])
        if declaration['policy']=='covered_by_children' and row['children_coverage']!='complete':
            raise ValueError('下级完整度未确证，不能宣称完整父级已被覆盖：'+row['parent_id'])


def validate_local(snapshot,parameters):
    value=parameters.get('oob_coverage')
    if enabled(parameters):
        if value is not None:raise ValueError('会战范围使用campaign_scope.remainders，不混用局部覆盖声明')
        return
    rows=local_coverage(snapshot)
    if not rows and value is None:return
    if not isinstance(value,dict) or set(value)!={'version','remainders'} or value['version']!=LOCAL_VERSION:
        raise ValueError('局部下级投入须提供oob_coverage及显式余部声明')
    validate_remainders(rows,value['remainders'])


def template(snapshot, window=None):
    import copy
    identities=select(snapshot,window)
    return {'version':WINDOW_VERSION if window else VERSION,
        'planning_end':window['definition']['bounds']['end'] if window else None,
        **({'window':copy.deepcopy(window)} if window else {}),
        'remainders':{r['parent_id']:{'policy':None,'assumption':'待说明未细分余部的处理范围；不能默认全部已由下级覆盖。'} for r in coverage(snapshot,identities)},
        'assumption':'待说明会战参战序列的开局与分批到场估计；不是已确证同日部署，下级缺项与海空独立过程不自动补齐。'}


def validate(snapshot,parameters,*,frozen=False):
    value=parameters.get('campaign_scope')
    if value is None:return
    legacy=isinstance(value,dict) and value.get('version')==LEGACY_VERSION
    windowed=isinstance(value,dict) and value.get('version')==WINDOW_VERSION
    if legacy and not frozen:raise ValueError('新会战配置必须登记下级覆盖与余部，请重新生成覆盖版本2；旧冻结对局仍可恢复')
    fields={'version','planning_end','assumption'}|({'remainders'} if not legacy else set())|({'window'} if windowed else set())
    if (not isinstance(value,dict) or set(value)!=fields or value['version'] not in (VERSION,LEGACY_VERSION,WINDOW_VERSION)
            or not isinstance(value['assumption'],str) or not value['assumption'].strip()):
        raise ValueError('会战范围必须声明版本、规划边界和部署估计依据')
    if windowed and not isinstance(value['window'],dict):
        raise ValueError('会战窗口范围缺少完整窗口快照，不能回退为累计序列')
    identities=select(snapshot,value['window'] if windowed else None,frozen=frozen)
    if not legacy:
        rows=coverage(snapshot,identities);remainders=value['remainders']
        validate_remainders(rows,remainders)
    try:end=datetime.fromisoformat(value['planning_end']);start=datetime.fromisoformat(parameters['clock']['start'])
    except (ValueError,TypeError) as exc:raise ValueError('会战规划边界与开局须为当地日期时间') from exc
    if end.tzinfo or start.tzinfo or end<=start:raise ValueError('会战规划边界须晚于开局，不使用混合时区')
    if windowed:
        bounds=value['window']['definition']['bounds']
        if start!=datetime.fromisoformat(bounds['start']) or end!=datetime.fromisoformat(bounds['end']):
            raise ValueError('所选会战窗口开局与规划边界须匹配固定版本；开放过程可按目标延伸，不改初态范围')
    if not parameters.get('campaign'):raise ValueError('会战序列部署必须配置分批入场与多方向目标，不能回退为四单位占点')
    if set(parameters['actors'])!=set(identities):raise ValueError('会战部署须覆盖全部已选不重叠地面叶子，不能丢兵或重复累计父子')


def end_time(snapshot,parameters):
    if enabled(parameters):return datetime.fromisoformat(parameters['campaign_scope']['planning_end'])
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
    return datetime.fromisoformat(phase['execution_window']['end'])
