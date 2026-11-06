"""Native read-only effect preview, recovered from DSH's public tool trajectory.

No preview cache or mutable world is kept here. A final report references a
successful tool call from the current operation; the normal commit path checks
the same candidate again before accepting it.
"""
import copy
import json
from gentactix import commands,missions,turn_settlement
from .extensions import canonical_numbers as _canonical

VERSION='turn-effects-preview-1'
TOOL='preview_turn_effects'
REPORT_TOOL='submit_turn_report'
REPORT_VERSION='turn-report-proposal-1'
READ_TOOL='get_turn_preview'
PAGE_VERSION='turn-preview-page-1'


def context(session,prepared,*,native_orders=(),fixed_orders=None,operation_id,world_validator=None):
    from . import afsim_state
    value=afsim_state.operation_context(session)
    if world_validator is not None:value['_world_validator']=world_validator
    value['session'].update({k:session.get(k) for k in ('role_epoch','mission_id','product_mode','agent_mode')})
    value['turn_preview']=dict(version=VERSION,operation_id=operation_id,prepared=copy.deepcopy(prepared),
        native_orders=copy.deepcopy(list(native_orders)),fixed_orders=copy.deepcopy(fixed_orders))
    return value


def resolved_orders(ctx,candidate):
    """Resolve the existing command precedence without interpreting effects."""
    session=ctx['session'];spec=ctx['turn_preview'];fixed=spec['fixed_orders']
    orders=copy.deepcopy(fixed) if fixed is not None else copy.deepcopy(candidate.get('orders'))
    if not isinstance(orders,list) or any(not isinstance(o,dict) for o in orders):raise ValueError('候选命令必须为对象数组')
    if fixed is None and isinstance(orders,list):
        orders=[{k:v for k,v in o.items() if k not in ('intent_id','cancel_crossing')} if isinstance(o,dict) else o for o in orders]
    if spec['prepared']:
        names={o['unit'] for o in spec['native_orders']}
        orders=commands.merge_proposal(session,copy.deepcopy(spec['prepared']),
            [o for o in (orders or []) if isinstance(o,dict) and o.get('unit') not in names]+spec['native_orders'])
    checked=missions.validate_orders(session['war_state'],orders,session['time_step'],validator=ctx.get('_world_validator'))
    if any(u['name'] not in checked for _,u in missions.units(session['war_state']) if commands.available(u)):
        raise ValueError('双方可行动单位都需要明确命令，包括hold')
    return orders


def normalize(ctx,candidate):
    value=_canonical(copy.deepcopy(candidate))
    if not isinstance(value,dict):raise ValueError('候选效果必须为对象')
    for key in ('report','source_note'):value.pop(key,None)
    fixed=ctx['turn_preview']['fixed_orders']
    from . import effect_contract
    effect_contract.validate({**value,**({'orders':fixed} if fixed is not None else {})})
    value['orders']=resolved_orders(ctx,value)
    return value


def _digest(ctx,value,after_hash,settlement_hash):
    return missions.digest(dict(version=VERSION,operation_id=ctx['turn_preview']['operation_id'],
        before_hash=missions.digest(ctx['session']['war_state']),effects_hash=missions.digest(value),
        after_hash=after_hash,settlement_hash=settlement_hash))


def _preview(ctx,raw):
    spec=ctx['turn_preview'];session=ctx['session'];value=normalize(ctx,raw)
    from . import dsh_simulation
    after=dsh_simulation.apply(session['war_state'],value,session['time_step'],require_fire_ledger=True,validator=ctx.get('_world_validator'))
    if spec['prepared']:commands.verify_open(session,spec['prepared'],after,spec['native_orders'])
    summary=turn_settlement.projection(turn_settlement.build(after,session['war_state']))
    after_hash=missions.digest(after);summary_hash=missions.digest(summary)
    digest=_digest(ctx,value,after_hash,summary_hash)
    return dict(ok=True,readonly=True,version=VERSION,digest=digest,
        before_hash=missions.digest(session['war_state']),operation_id=spec['operation_id'],
        after_hash=after_hash,settlement_hash=summary_hash,settlement=summary,
        next_units_args=(dict(preview_hash=digest,kind='units',offset=len(summary['units']),limit=16)
                         if summary['unlisted_units'] else None),
        next_goals_args=(dict(preview_hash=digest,kind='goals',offset=len(summary['goals']),limit=16)
                         if summary['unlisted_goals'] else None),
        scope='候选效果已校验、目标已试评分；未执行或提交世界、命令与持续任务')


def _failure(exc,reference,ctx=None,raw=None):
    from .effect_contract import ShapeError
    result=dict(ok=False,readonly=True,version=VERSION,error=str(exc),**reference)
    if isinstance(exc,ShapeError):result.update(issues=exc.issues[:64],issue_count=len(exc.issues))
    if reference and ctx is not None and isinstance(raw,dict):
        from . import effect_constraints
        facts=effect_constraints.diagnose(ctx,raw)
        if 'constraints' in facts:
            total=len(facts['constraints']);facts['constraints']=facts['constraints'][:16]
            facts['constraints_next_args']=(dict(kind='constraints',candidate_ref=reference['candidate_ref'],offset=16,limit=16)
                if total>16 else None)
        result['calculation_diagnostics']=facts
    return result


def _enabled(ctx,*,native=False):
    spec=ctx.get('turn_preview');session=ctx.get('session',{})
    if (not spec or spec.get('version')!=VERSION or session.get('execution_backend')=='afsim'
            or native and session.get('agent_mode')!='native'
            or session.get('war_state',{}).get('mission',{}).get('status')!='active'):
        raise ValueError('本次操作未开放DSH过程候选预览')


def execute(ctx,payload):
    reference={}
    try:
        _enabled(ctx)
        args=payload.get('args')
        if payload.get('tool')!=TOOL:raise ValueError('未知过程预览工具')
        from .effect_contract import validate_arguments
        validate_arguments(args)
        from . import effect_amendments
        reference=effect_amendments.reference(ctx,TOOL,args,args['candidate'])
        return {**_preview(ctx,args['candidate']),**reference}
    except (ValueError,KeyError,TypeError) as exc:
        args=payload.get('args')
        return _failure(exc,reference,ctx,args.get('candidate') if isinstance(args,dict) else None)


def amend(ctx,payload):
    """Replay explicit edits from public Native evidence, then fully validate."""
    reference={};raw=None
    try:
        _enabled(ctx,native=True)
        from . import effect_amendments as a
        args=payload.get('args')
        if payload.get('tool')!=a.AMEND_TOOL or not isinstance(args,dict):raise ValueError('未知候选修订工具或参数')
        raw=a.edit(a.source(ctx,payload,args.get('base_ref')),args)
        reference=a.reference(ctx,a.AMEND_TOOL,args,raw)
        return {**_preview(ctx,raw),**reference}
    except (ValueError,KeyError,TypeError) as exc:
        return _failure(exc,reference,ctx,raw)


def _resolve_preview(digest,observer,ctx):
    from .effect_amendments import candidates
    for raw,reply,sid,call in candidates(observer,ctx):
        if reply.get('ok') is not True or reply.get('digest')!=digest:continue
        if (reply.get('before_hash')!=missions.digest(ctx['session']['war_state'])
                or reply.get('operation_id')!=ctx['turn_preview']['operation_id']):
            raise ValueError('过程预览指纹与当前操作或轮初世界不一致')
        value=normalize(ctx,raw);summary=reply.get('settlement')
        if (not isinstance(summary,dict) or missions.digest(summary)!=reply.get('settlement_hash')
                or _digest(ctx,value,reply.get('after_hash'),reply.get('settlement_hash'))!=digest):
            raise ValueError('过程预览指纹与当前操作、轮初世界或候选效果不一致')
        if summary.get('version') not in (turn_settlement.VERSION,turn_settlement.LEGACY_VERSION):
            raise ValueError('过程预览结算摘要版本未支持')
        return value,dict(version=VERSION,digest=reply['digest'],after_hash=reply['after_hash'],
            settlement_hash=reply['settlement_hash'],session_id=sid,call_id=call,evidence='dsh_public_tool_trajectory',
            **({'settlement_version':summary['version']} if summary['version']!=turn_settlement.LEGACY_VERSION else {})),summary
    raise ValueError('本次DSH操作轨迹中没有匹配的成功过程预览；操作/轮初世界指纹不符或证据缺失，不接受伪造或跨操作引用')


def resolve(final,observer,ctx):
    if (not isinstance(final,dict) or set(final)!={'preview_hash','report'} or not isinstance(final['preview_hash'],str)
            or not isinstance(final['report'],str) or not final['report'].strip()):
        raise ValueError('原生过程须先preview_turn_effects，再只返回{preview_hash,report}；不能省略成功工具证据')
    value,proof,_=_resolve_preview(final['preview_hash'],observer,ctx)
    submitted=submitted_report(observer,ctx)
    if submitted:
        if submitted[0]!=final:raise ValueError('最终战报与本次原生工具提交的战报候选不一致')
        proof.update(report_source=submitted[1]['source'],report_digest=submitted[1]['report_digest'],
            report_session_id=submitted[1]['session_id'],report_call_id=submitted[1]['call_id'])
    return {**value,'report':final['report']},proof


def recovery_hint(observer,ctx):
    """Read verified Native evidence; never repair a reply or choose a result."""
    for run in reversed(observer.runs):
        for event in reversed(run.get('events',[])):
            if event.get('type')!='tool/result':continue
            message=event.get('message')
            if not isinstance(message,dict):continue
            text='\n'.join(b.get('text','') for b in (message.get('content') or []) if isinstance(b,dict) and b.get('type')=='text')
            try:
                reply=json.loads(text)
                if not isinstance(reply,dict) or not isinstance(reply.get('digest'),str):continue
                _,proof,summary=_resolve_preview(reply['digest'],observer,ctx)
            except (ValueError,KeyError,TypeError):continue
            return dict(preview_hash=proof['digest'],settlement=summary)
    return None


def _valid_digest(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _preview_observer(payload):
    from .effect_amendments import observer
    return observer(payload,'preview_events')


def _constraint_page(ctx,payload):
    from . import effect_amendments,effect_constraints
    args=payload['args'];offset=args.get('offset',0);limit=args.get('limit',16)
    if (set(args)-{'candidate_ref','kind','offset','limit'} or not _valid_digest(args.get('candidate_ref'))
            or type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=16):
        raise ValueError('约束分页须提供本操作candidate_ref，offset非负且limit为1至16整数')
    raw=effect_amendments.source(ctx,payload,args['candidate_ref'])
    facts=effect_constraints.diagnose(ctx,raw);rows=facts.get('constraints',[])
    if offset>len(rows):raise ValueError('约束分页offset超出本候选范围')
    return dict(ok=True,readonly=True,version=PAGE_VERSION,kind='constraints',
        operation_id=ctx['turn_preview']['operation_id'],candidate_ref=args['candidate_ref'],
        candidate_hash=facts['candidate_hash'],before_hash=facts['before_hash'],
        total=len(rows),offset=offset,limit=limit,items=rows[offset:offset+limit],
        next_args=(dict(kind='constraints',candidate_ref=args['candidate_ref'],offset=offset+limit,limit=limit)
            if offset+limit<len(rows) else None),complete_validation=False,
        scope='从本次公开候选／修订轨迹重建的条件与上限，不是成功预览、到货分配或状态修补；改变依赖后须完整预览。')


def get_preview(ctx,payload):
    """Page a validated candidate using the existing public Native evidence.

    Revalidate on each request; no cached candidate, world or effect executor.
    Ordinary observation tools continue to expose the committed initial state.
    """
    try:
        spec=ctx.get('turn_preview');session=ctx.get('session',{})
        if (not spec or spec.get('version')!=VERSION or session.get('agent_mode')!='native'
                or session.get('execution_backend')=='afsim' or session.get('war_state',{}).get('mission',{}).get('status')!='active'):
            raise ValueError('本次操作未开放Native候选轮末观察')
        args=payload.get('args')
        if payload.get('tool')==READ_TOOL and isinstance(args,dict) and args.get('kind')=='constraints':
            return _constraint_page(ctx,payload)
        if (payload.get('tool')!=READ_TOOL or not isinstance(args,dict)
                or set(args)-{'preview_hash','kind','offset','limit'} or not _valid_digest(args.get('preview_hash'))):
            raise ValueError('候选观察须提供有效preview_hash和有界分页参数')
        kind=args.get('kind','units');offset=args.get('offset',0);limit=args.get('limit',16)
        if kind not in ('units','goals') or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=16:
            raise ValueError('候选分页kind须为units/goals，offset非负，limit为1至16整数')
        value,proof,summary=_resolve_preview(args['preview_hash'],_preview_observer(payload),ctx)
        from . import dsh_simulation
        before=session['war_state']
        after=dsh_simulation.apply(before,value,session['time_step'],require_fire_ledger=True,validator=ctx.get('_world_validator'))
        if spec['prepared']:commands.verify_open(session,spec['prepared'],after,spec['native_orders'])
        full=turn_settlement.build(after,before,version=summary['version'])
        if (missions.digest(after)!=proof['after_hash']
                or missions.digest(turn_settlement.projection(full))!=proof['settlement_hash']):
            raise ValueError('候选观察与原成功预览的轮末世界或结算摘要指纹不一致')
        rows=full[kind]
        if offset>len(rows):raise ValueError('候选分页offset超出本次条目范围')
        items=copy.deepcopy(rows[offset:offset+limit])
        if kind=='units':
            old={(t,u['name']):u for t,u in missions.units(before)}
            current={(t,u['name']):u for t,u in missions.units(after)}
            def stock(unit,key):
                formation=unit.get('formation')
                return turn_settlement.number(formation.get(key)) if isinstance(formation,dict) else None
            for row in items:
                identity=(row['team'],row['name'])
                row['classified_inventory']={key:dict(before=stock(old[identity],key),after=stock(current[identity],key))
                                             for key in turn_settlement.CLASSIFIED}
        else:
            for row in items:row['reason']=row['reason'][:200]
        return dict(ok=True,readonly=True,version=PAGE_VERSION,preview_hash=proof['digest'],
            operation_id=spec['operation_id'],after_hash=proof['after_hash'],settlement_version=summary['version'],
            turn=full['turn'],current_time=full['current_time'],kind=kind,total=len(rows),offset=offset,limit=limit,items=items,
            next_args=(dict(preview_hash=proof['digest'],kind=kind,offset=offset+limit,limit=limit) if offset+limit<len(rows) else None),
            scope='指定预览的候选轮末结算；分类库存为该候选前后已知量，未知不补0。未执行、未提交、未消费队列或持续任务。')
    except (ValueError,KeyError,TypeError) as exc:
        return dict(ok=False,readonly=True,version=PAGE_VERSION,error=str(exc))


def _report_args(args):
    if (not isinstance(args,dict) or set(args)!={'preview_hash','report'}
            or not _valid_digest(args['preview_hash'])
            or not isinstance(args['report'],str) or not args['report'].strip() or len(args['report'])>32768):
        raise ValueError('战报候选只接受本次preview_hash和完整非空report，不修改或猜测内容')
    return args


def _report_digest(ctx,args):
    return missions.digest(dict(version=REPORT_VERSION,operation_id=ctx['turn_preview']['operation_id'],
        before_hash=missions.digest(ctx['session']['war_state']),**args))


def _report_claim_issues(ctx, value, text):
    """Use the same pure candidate validator and public-claim screen as commit.

    No additional simulation, narrative rewrite or mutable preview cache. DSH
    receives the issues and may resubmit prose against the same valid effects.
    """
    from . import dsh_simulation
    from gentactix import reporting
    before=ctx['session']['war_state']
    after=dsh_simulation.apply(before,value,ctx['session']['time_step'],require_fire_ledger=True,validator=ctx.get('_world_validator'))
    _,audit=reporting.render(text,after,before,turn=after['mission']['turn'])
    return audit['issues']


def submit_report(ctx,payload):
    """Verify Native journal evidence supplied by the registered runtime tool.

    No candidate/report cache or mutable world: final acceptance reads the
    original tool call/result pair again from the operation's public trajectory.
    """
    try:
        spec=ctx.get('turn_preview');session=ctx.get('session',{})
        if (not spec or spec.get('version')!=VERSION or session.get('agent_mode')!='native'
                or session.get('execution_backend')=='afsim' or session.get('war_state',{}).get('mission',{}).get('status')!='active'):
            raise ValueError('本次操作未开放Native战报候选工具')
        if payload.get('tool')!=REPORT_TOOL:raise ValueError('未知战报工具')
        args=_report_args(payload.get('args'));observer=_preview_observer(payload)
        value,_,_=_resolve_preview(args['preview_hash'],observer,ctx)
        issues=_report_claim_issues(ctx,value,args['report'])
        if issues:
            return dict(ok=False,readonly=True,version=REPORT_VERSION,issues=issues,
                error='战报触发已知断言筛查；请依据本次成功预览修正正文后重新提交',
                hint='先按issues中的quote定位原句；库存须写明单位全名及粮食、弹药工作量或炮弹分类库存，未耗尽须有当前正库存。时段停火写明单位及本轮最后N小时/分钟，并与过程账一致。依据不足则省略该断言，不改写已经通过的效果。')
        return dict(ok=True,readonly=True,version=REPORT_VERSION,preview_hash=args['preview_hash'],
            operation_id=spec['operation_id'],before_hash=missions.digest(session['war_state']),
            report_digest=_report_digest(ctx,args),claim_screening='known-claims-1',
            scope='候选绑定与已知断言筛查通过，非全文语义证明；世界、队列及任务仍未提交')
    except (ValueError,KeyError,TypeError) as exc:
        return dict(ok=False,readonly=True,version=REPORT_VERSION,error=str(exc))


def submitted_report(observer,ctx):
    """Recover the last valid structured report, never parse free-form text."""
    from .extensions import public_tool_results
    accepted=None
    for arguments,reply,event in public_tool_results(observer,REPORT_TOOL):
        if reply.get('version')!=REPORT_VERSION:continue
        args=_report_args(arguments);value,_,_=_resolve_preview(args['preview_hash'],observer,ctx)
        if (reply.get('operation_id')!=ctx['turn_preview']['operation_id']
                or reply.get('before_hash')!=missions.digest(ctx['session']['war_state'])
                or reply.get('preview_hash')!=args['preview_hash'] or reply.get('report_digest')!=_report_digest(ctx,args)):
            raise ValueError('原生战报候选指纹与当前世界、操作或完整正文不一致')
        if _report_claim_issues(ctx,value,args['report']):
            raise ValueError('原生战报候选仍含已知断言问题，不能凭ok结果绕过最终复核')
        accepted=copy.deepcopy(args),dict(source='dsh_native_report_tool',report_digest=reply['report_digest'],**event)
    if accepted:
        latest=recovery_hint(observer,ctx)
        if not latest or latest['preview_hash']!=accepted[0]['preview_hash']:
            raise ValueError('提交战报后又有新预览，须为最新候选重新提交完整战报')
    return accepted


INSTRUCTION=('\n【原生候选结算流程】失败时calculation_diagnostics.constraints最多返回16条，'
    '沿constraints_next_args调用既有get_turn_preview读取其余失败候选约束；candidate_ref不是成功preview_hash，条件上限不是必须到货或可自动套用的修订。'
    '先生成本轮完整效果对象，调用preview_turn_effects({candidate:该对象})。'
    'candidate沿上面的效果结构，但不写report或source_note。工具校验资源/时钟/命令后返回本轮宿主结算；失败返回candidate_ref；按issues的JSON Pointer路径调用amend_turn_effects({base_ref:该引用,edits:[{op:"replace",path:"/unit_updates/0/logistics/food",value:自行计算的正确值}]})。remove不带value，add/replace必须给value。修订工具从本次DSH公开轨迹重建原候选并执行完整校验，未使用任何缓存或隐含纠正。修订失败可引用新的candidate_ref继续改；也可重发完整候选。unit_updates和orders行必须使用unit精确全名，不用name/unit_name，更新行不能附team或只读身份字段。'
    '成功预览只是候选，不表示命令或持续任务已提交。依据settlement写本轮物理过程，粮食和弹药分别按毛收支，观察阶段与轮末阶段分别说明。'
    '目标condition_sampled=false且condition=null表示尚未采样，不能说其条件不满足；仅对condition_sampled=true的目标作条件判断。'
    'phase_at_end记录该目标所属阶段在轮末的实际状态；active表示已激活，即使本轮尚未采样，也不能称尚未激活。'
    '公开report只会在成功提交后显示，不写“仍待原子提交”等内部流程；预览自身未执行这一事实只用于工具阶段。'
    '依据成功预览调用submit_turn_report({preview_hash:该digest,report:完整中文战报})，直到工具返回ok=true。'
    '若返回issues，只修正对应正文并沿用本次有效preview_hash重新提交；不能由正文反馈擅改战损、库存或重新捏造效果。'
    '战报以该原生工具的结构化参数为准；成功后最终只需简短确认，不再拼接包含长段中文的JSON，也不重复unit_updates。'
    '不能自行计算/编造digest；宿主从本次DSH公开工具轨迹取回候选并重新校验。不改候选后再沿用旧指纹。'
    '其他观察工具仍读轮初状态，轮末结论以成功预览为准；摘要未列单位不等于没有该单位。'
    '成功预览若有next_units_args或next_goals_args，调用get_turn_preview并沿next_args读完候选轮末条目，包含摘要未列的单位和目标；'
    '分类库存按该工具的classified_inventory前后值读取，不把轮初观察当成轮末，也不从弹药工作量反推炮弹。')
