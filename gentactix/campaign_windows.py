"""Versioned campaign admission windows; references never execute orders.

The inline pin travels with a calculation binding, so restoring a saved world
does not depend on the current registry. Unknown deployments remain unknown.
"""
import copy
from datetime import datetime
import json
from pathlib import Path

from . import historical_initial as hi
from .json_numbers import canonical_numbers

DATA_ROOT = Path(__file__).resolve().parent.parent / 'data/campaign_windows'
FORMAT = 'gentactix-campaign-window-1'
REPRESENTATIONS = {'actor', 'covered_reference', 'command_reference', 'after_window', 'outside_window'}
PRESENCE = {'reported_action', 'window_reference', 'prior_reference', 'departure_only', 'not_applicable'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('会战窗口'+label+'字段非法')


def validate_definition(value, snapshot):
    hi.restore(snapshot)
    _fields(value, {'format','id','version','label','battle','historical_initial',
                   'start_phase_id','phase_ids','bounds','units','sectors','milestones','limitations'}
            |{key for key in ('parameter_estimates','opening_command') if isinstance(value,dict) and key in value}, '定义')
    if (value['format'] != FORMAT or not hi._identity(value['id'])
            or not hi._identity(value['version']) or not _text(value['label'])
            or not _text(value['limitations'])):
        raise ValueError('会战窗口格式、身份或范围说明非法')
    source = snapshot['definition']
    expected = {'profile_id':snapshot['profile_id'],'version':snapshot['version'],
                'definition_hash':snapshot['definition_hash']}
    if value['historical_initial'] != expected or value['battle'] != source['battle']:
        raise ValueError('会战窗口必须绑定同一历史初态版本和内容摘要')
    phases = {p['id']:p for p in source['phases']}
    ids = value['phase_ids']
    if (not isinstance(ids,list) or not ids or len(ids)!=len(set(ids))
            or any(i not in phases for i in ids) or value['start_phase_id']!=ids[0]
            or snapshot['phase_id']!=ids[0]):
        raise ValueError('会战窗口阶段及开局不一致')
    if [p['id'] for p in source['phases'] if p['id'] in ids] != ids:
        raise ValueError('会战窗口阶段必须保持来源顺序')
    bounds = value['bounds']
    _fields(bounds, {'start','end','kind','note'}, '边界')
    try:
        start=datetime.fromisoformat(bounds['start']);end=datetime.fromisoformat(bounds['end'])
    except (ValueError, TypeError) as exc:
        raise ValueError('会战窗口边界须为当地日期时间') from exc
    if start.tzinfo or end.tzinfo or end<=start or bounds['kind']!='model_scope_limit' or not _text(bounds['note']):
        raise ValueError('会战窗口边界须说明计算范围，不冒充史实钟点')
    if 'opening_command' in value:
        from . import initial_command
        initial_command.validate_window_declaration(snapshot,value['opening_command'])
    units={u['id']:u for u in source['units']}
    if not isinstance(value['units'],dict) or set(value['units'])!=set(units):
        raise ValueError('会战窗口须说明每个来源身份的表示方式，不能遗漏参考或余部')
    operations={o['id']:o for p in source['phases'] for o in p.get('operations',[])}
    relations={r['id']:r for p in source['phases'] for r in p.get('relations',[])}
    selected=[]
    for identity,row in value['units'].items():
        _fields(row, {'representation','represented_by','presence_basis','extent',
                      'opening','operation_ids','operational_reference','evidence'}, '单位')
        if (row['representation'] not in REPRESENTATIONS or row['presence_basis'] not in PRESENCE
                or not _text(row['extent']) or row['opening']!='requires_explicit_estimate'):
            raise ValueError('会战窗口须区分投入范围、来源参战与开局估计')
        hi._evidence(row['evidence'], source['sources'])
        if (not isinstance(row['operation_ids'],list) or len(row['operation_ids'])!=len(set(row['operation_ids']))
                or any(i not in operations or identity not in operations[i]['unit_ids'] for i in row['operation_ids'])):
            raise ValueError('会战窗口单位事件必须引用涉及本身份的来源记录')
        relation=row['operational_reference']
        if relation is not None and (relation not in relations or relations[relation]['child_id']!=identity):
            raise ValueError('会战窗口临时指挥引用非法；不能改写行政隶属')
        kind=row['representation'];target=row['represented_by']
        if kind=='actor':
            if units[identity]['role'] not in ('formation','support') or target is not None or row['presence_basis']=='not_applicable':
                raise ValueError('会战窗口执行身份不能是司令部或重复覆盖身份')
            selected.append(identity)
        elif kind=='covered_reference':
            if target not in units or target==identity:
                raise ValueError('会战窗口覆盖参考须指向另一个有效身份')
        elif target is not None:
            raise ValueError('会战窗口非覆盖参考不得指向计算聚合')
        if kind=='outside_window':
            if row['presence_basis'] not in ('prior_reference','not_applicable'):
                raise ValueError('窗口外参考须说明先前记录或不适用，不能伪造后续到场')
            if any(p['phase_id'] in ids and p['status']=='reported_present' for p in units[identity]['presence']):
                raise ValueError('窗口外参考不能隐藏来源已记载的本窗口在场单位')
        if kind=='command_reference' and units[identity]['role']!='command':
            raise ValueError('会战窗口指挥参考不能隐藏战斗部队')
    interaction=phases[ids[0]].get('interaction')
    teams=set(interaction['active_teams']) if interaction else {'red','blue'}
    if interaction:
        if any(p.get('interaction',{}).get('active_teams')!=interaction['active_teams']
               or p.get('interaction',{}).get('kind')!='non_contact_transfer' for p in (phases[i] for i in ids)):
            raise ValueError('非接敌会战窗口不能混入交战或未声明阵营的阶段')
        if any(u['team'] not in teams and u['role'] in ('formation','support')
               and any(r['phase_id'] in ids and r['status']=='reported_present' for r in u['presence']) for u in units.values()):
            raise ValueError('非接敌会战窗口不能隐藏来源记载的在场对手')
    if not selected or {units[i]['team'] for i in selected}!=teams or len(selected)>512:
        raise ValueError('会战窗口执行阵营须匹配来源，普通交战须有双方，不重叠身份不超过512个')
    for identity in selected:
        parent=units[identity]['parent_id']
        while parent:
            if parent in selected:raise ValueError('会战窗口不得父子重复计量')
            parent=units[parent]['parent_id']
    for identity,row in value['units'].items():
        if row['representation']!='covered_reference':continue
        target=row['represented_by']
        # An administrative ancestor is a display aggregate of selected leaves;
        # a selected ancestor may instead carry its undecomposed organic child.
        def ancestor(a,b):
            parent=units[b]['parent_id']
            while parent:
                if parent==a:return True
                parent=units[parent]['parent_id']
            return False
        if target not in selected or not (ancestor(identity,target) or ancestor(target,identity)):
            raise ValueError('会战窗口覆盖只能连接真实行政祖先和已选执行身份')
    if not isinstance(value['sectors'],list) or not value['sectors']:
        raise ValueError('会战窗口缺少来源方向参考')
    sector_ids=set()
    for row in value['sectors']:
        _fields(row, {'id','label','position','unit_ids','operation_ids','evidence'}, '方向')
        if (not hi._identity(row['id']) or row['id'] in sector_ids or not _text(row['label'])
                or row['position'] is not None or not row['unit_ids']
                or any(i not in selected for i in row['unit_ids'])
                or any(i not in operations for i in row['operation_ids'])):
            raise ValueError('会战窗口方向只绑定具名参考，不补造精确部署')
        sector_ids.add(row['id']);hi._evidence(row['evidence'],source['sources'])
    if not isinstance(value['milestones'],list) or not value['milestones']:
        raise ValueError('会战窗口缺少历史节点参考')
    seen=set()
    for row in value['milestones']:
        _fields(row, {'operation_id','phase_id','policy'}, '节点')
        if (row['phase_id'] not in ids or row['operation_id'] in seen or row['policy']!='reference_only'
                or row['operation_id'] not in {o['id'] for o in phases[row['phase_id']].get('operations',[])}):
            raise ValueError('会战窗口节点须指向窗口内事件，开放模式不强迫按历史时钟执行')
        seen.add(row['operation_id'])
    if 'parameter_estimates' in value:
        from . import campaign_estimates
        campaign_estimates.validate_definition(value['parameter_estimates'],value,snapshot,selected)
    return selected


def load(identity, version='1.0.0'):
    if not hi._identity(identity) or not hi._identity(version):
        raise ValueError('会战窗口身份或版本非法')
    path=DATA_ROOT/identity/(version+'.json')
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise ValueError('会战窗口注册版本不可用') from exc
    if value.get('id')!=identity or value.get('version')!=version:
        raise ValueError('会战窗口注册路径与版本不一致')
    return value


def pin(identity, version='1.0.0'):
    value=canonical_numbers(load(identity,version))
    initial=value['historical_initial']
    snapshot=hi.initial(value['battle'],value['start_phase_id'],version=initial['version'])['historical_initial']
    validate_definition(value,snapshot)
    return {'format':FORMAT,'id':identity,'version':version,'definition_hash':hi.digest(value),'definition':copy.deepcopy(value)}


def validate(snapshot, value, *, frozen=False):
    _fields(value, {'format','id','version','definition_hash','definition'}, '快照')
    d=value['definition']
    if (not isinstance(d,dict) or value['format']!=FORMAT or value['id']!=d.get('id')
            or value['version']!=d.get('version')):
        raise ValueError('会战窗口快照摘要或版本被修改')
    registered=None
    if value['definition_hash']!=hi.digest(d):
        if frozen:raise ValueError('会战窗口快照摘要或版本被修改')
        # A legacy browser input can lose 32.0's spelling. Only the registered
        # original digest AND equal canonical contents establish that case.
        # Frozen recovery never consults the registry or rewrites old pins.
        registered=load(value['id'],value['version'])
        if (value['definition_hash']!=hi.digest(registered)
                or canonical_numbers(registered)!=canonical_numbers(d)):
            raise ValueError('会战窗口快照摘要或版本被修改')
    selected=validate_definition(d,snapshot)
    if not frozen and canonical_numbers(registered if registered is not None else load(value['id'],value['version']))!=canonical_numbers(d):
        raise ValueError('会战窗口不匹配已注册的只读版本')
    return selected


def transport_pin(snapshot, value):
    """Rebind verified input metadata for a NEW draft, never migrate a save."""
    validate(snapshot,value)
    definition=canonical_numbers(value['definition'])
    return dict(format=FORMAT,id=value['id'],version=value['version'],
                definition_hash=hi.digest(definition),definition=definition)


def equivalent_pins(left, right):
    """Match verified stored choices across number spellings, without migration."""
    if left is None or right is None:return left is right
    try:
        for value in (left,right):
            _fields(value,{'format','id','version','definition_hash','definition'},'快照')
            if (value['format']!=FORMAT or value['definition_hash']!=hi.digest(value['definition'])
                    or value['id']!=value['definition']['id']or value['version']!=value['definition']['version']):return False
        return (left['id']==right['id']and left['version']==right['version']
                and hi.digest(canonical_numbers(left['definition']))==hi.digest(canonical_numbers(right['definition'])))
    except (ValueError,KeyError,TypeError):return False


def select(snapshot, value, *, frozen=False):
    return validate(snapshot,value,frozen=frozen)


def catalog(battle):
    rows=[]
    for path in sorted(DATA_ROOT.glob('*/*.json')):
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('battle')!=battle:continue
        pinned=pin(value['id'],value['version'])
        rows.append({k:copy.deepcopy(value[k]) for k in ('id','version','label','historical_initial','start_phase_id','bounds','limitations')})
    return rows
