"""Unit roles on DSH's native registry; only wargame observations and proposals."""
import copy
import json

from gentactix import commands
from . import harness_engine as h
from . import unit_order_submission


def situation_index(rows,present_ids):
    """Detached complete identity/tactical index; full facts stay in observation tools."""
    result=[]
    for row in rows:
        present=row['id'] in present_ids
        personnel=row.get('personnel')
        entry={key:copy.deepcopy(row.get(key)) for key in ('id','team','name','type','position',
            'available','attack_range','personnel_strength_pct')}
        entry.update(personnel_current=personnel.get('current') if isinstance(personnel,dict) else None,
            in_world=present,detail_query=dict(ids=[row['id']],limit=1,detail=True) if present else None)
        participation=row.get('capabilities',{}).get('participation')
        if isinstance(participation,dict):
            entry['participation']={key:copy.deepcopy(participation[key]) for key in
                ('status','targetable','controls_objectives','operation_zone') if key in participation}
        arrival=row.get('capabilities',{}).get('arrival')
        if isinstance(arrival,dict):entry['arrival']=copy.deepcopy(arrival)
        result.append(entry)
    return result


def plan(session, prepared, observer, *, instruction='', briefing=''):
    cs = prepared['state']
    controlled = {x['command']['unit_id'] for x in prepared['manual']} | {x['unit_id'] for x in prepared['blocked'] + prepared['expired']}
    controlled.update(x['unit_id'] for x in prepared.get('cancelled_tasks',[]))
    units = commands.resolve_units(session, cs)
    orders, decisions = [], []
    bindings = cs.setdefault('agent_sessions', {})
    observation = commands.view(session)
    from . import afsim_state
    known_units=situation_index(observation['units'],set(units))
    mission_observation=afsim_state.mission_context(session['war_state'])
    for identity in cs['unit_agents']:
        if identity in controlled:
            continue
        pair = units.get(identity)
        if not pair or pair[0].get('ambiguous') or not commands.available(pair[1]):
            continue
        entry, unit = pair
        if not cs['director'] and entry['team'] != cs['control_team']:
            raise ValueError('单位Agent越过控制方权限')
        if observer.cancel_requested or session.get('cancel_requested'):
            raise RuntimeError('用户取消，单位候选不提交')
        # All currently displayed units are known in this version. No fog/LOS claim.
        context=unit_order_submission.context(session, prepared, identity, operation_id=observer.operation_id)
        unit_observation = next(x for x in observation['units'] if x['id'] == identity)
        if session.get('execution_backend') == 'afsim':
            row = afsim_state.observation(session, {'ids': [identity], 'detail': True})['units'][0]
            unit_observation = {**row, 'capabilities': {'actions': row['actions'], 'move_km': row['move_km'],
                                                       **({'participation':row['participation']} if 'participation' in row else {}),
                                                       **({'air_pools':row['air_pools']} if 'air_pools' in row else {})}}
        prompt = ('你是以下唯一单位的原生DSH智能体。仅提出该单位本轮一项行动，不写权威状态。'
            '前次会话文字可能是未提交候选，以本次权威观察为准；禁止继承别的角色提示。'
            '只能使用当前capabilities.actions；全局硬限制优先，意图是软偏好。'
            + ('当前阶段与目标通过get_campaign_lifecycle、get_campaign_objectives分页核对；阶段和目标进度只由宿主结算。'
               '任务群和持续任务按需用get_force_organization、get_force_tasks查询；不要从旧对话重建权威状态。' if mission_observation else '')
            + 'known_units覆盖全部登记身份，仅为态势索引；自身unit保留完整约束。索引未列字段不代表0，不证明完整战力或侦察探测。'
            '攻击或依赖另一单位的装备、库存及参与详情前，调用get_afsim_observation，使用该条detail_query按ID读取当前详情；不要从旧会话或缺字段推算。'
            '本单位地面射击前也读取detail中的fire_resources：按ammo_work.applies_to和indirect.generic_work_per_cycle区分直射与炮击，未设标记沿原双约束；分类炮弹计量的炮击不额外耗直射工作量。on_hand为当前已提交余额，含已结算到货，用于下一次命令；不是上一轮期初。周期上限不含未来到货，不是实际火力或战损预测；轮末到货不能追付到货前的射击。'
            'in_world=false为仅留身份参考；in_world=true和available=true也不等于已到场或可交战，须核对arrival和participation。position=null表示坐标未知，不得编造。'
            '会战上级与任务群可用get_force_organization分页查询，只汇总当前投入叶子，不重复累计父单位。get_afsim_changes的mode=aggregate读取多轮累计，mode=changes核对逐轮证据，沿next_args读完；史料用retrieve_history。' +
            'move若duration=next须在move_km内；远处目标可用duration=until_arrived，由宿主提交本轮预算内路段，不宣称本轮到达。fire及AFSIM的air_support需合法敌方target_id；航空资源独立于地面弹药。'
            '若capabilities.air_pools含多项，air_support必须附air_pool为本方可用池id，不得使用敌方池。不要输出内部推理。'
            'capabilities.participation标明当前参与状态；明确退出当前作战或重新投入且该能力enabled时，move+until_arrived才附participation="withdraw"或"reenter"，不能借此恢复兵力或瞬移。'
            '本单位身份由宿主按Native会话绑定，不需要抄写unit_id。若仍显式提供unit_id，必须完整匹配当前unit.id，否则拒收，不修正为其他身份。'
            + unit_order_submission.INSTRUCTION + ' 动作结构示例：{"order":{"action":"hold|move|fire|...",'
            '"duration":"next","destination":{"lat":0,"lng":0},"target_id":"敌方id"},'
            '"rationale":"本单位公开依据","expected_effect":"预期"}；不用的字段省略。\n'
            + json.dumps({'unit': unit_observation,
                'known_units': known_units, 'mission': mission_observation,
                'known_units_view':{'version':'unit-situation-index-1','registered_count':len(known_units),
                    'present_count':sum(row['in_world'] for row in known_units),'complete_registered_index':True,
                    'detail_tool':'get_afsim_observation','scope':'全部登记身份索引，非全部历史编制或感知范围；仅本单位可提交命令，其他单位详情按ID读取'},
                'current_time': session['war_state'].get('current_time'), 'time_step': session['time_step'],
                'no_fire': cs['no_fire'] and entry['team'] == cs['control_team'],
                'intent': cs['intent'], 'round_instruction': instruction, 'rule_briefing': briefing,
                'observation_version': prepared['world_version']}, ensure_ascii=False))
        start = len(observer.runs)
        binding=bindings.get(identity)
        proof = None
        empty_recovery=False
        def remember_binding(value):
            # Keep the real registry handle locally even if its completed run
            # has no output. Adopt it into prepared state only after a valid
            # proposal; never create a replacement chat to recover an empty one.
            nonlocal binding
            binding=copy.deepcopy(value)
        for attempt in range(2):
            if observer.cancel_requested or session.get('cancel_requested'):
                raise RuntimeError('用户取消，单位候选不提交')
            try:
                run, binding = h.unit_run(binding, prompt, observer, context=context,
                    namespace=f"{session['id']}-e{session.get('role_epoch', 0)}-{identity}",on_session=remember_binding)
            except h.EmptyFinalResponseError as exc:
                if observer.runs:
                    observer.runs[-1].update(accepted=False,rejection='empty_unit_response',output_diagnostics=exc.diagnostics)
                if observer.cancel_requested or session.get('cancel_requested'):
                    raise RuntimeError('用户取消，原生单位空答不再恢复，候选未提交') from exc
                if attempt or observer.empty_recoveries>=1:
                    raise h.HarnessRunError('原生单位空答恢复额度已用完，候选未提交，原战局保留。') from exc
                if not binding:
                    raise h.HarnessRunError('原生单位空答缺少可恢复的SDK绑定，不能另建会话代替。') from exc
                observer.empty_recoveries+=1;empty_recovery=True
                observer.progress.update(phase='empty_output_recovery',recovery_attempt=1)
                h.ENGINE_NOTICES.append({'level':'warning','message':'一名单位Agent未给出可用命令，正在原SDK会话恢复1次；战局未推进，思考强度与预算保留。'})
                prompt=('【原生单位空答恢复；不是新的战局回合】上次运行正常结束，但未提交可用命令。'
                    '依据以下同一权威观察、同一单位身份和本轮限制，实际调用submit_unit_order提交一项合法行动、公开依据与预期；'
                    '普通文字中的工具标记不执行，不要只写说明。不写权威状态，不替其他单位下令；取得成功回执后简短确认。\n'+prompt)
                continue
            submitted = unit_order_submission.submitted(observer, context, start=start)
            if submitted:
                parsed, proof = submitted
                observer.runs[-1].update(final_format='native_unit_order_tool')
                break
            try:
                parsed=h.parse_json_object(run.final_response)
                break
            except h.JSONOutputError as exc:
                if observer.runs:
                    observer.runs[-1].update(accepted=False,rejection='invalid_unit_json',output_diagnostics=exc.diagnostics)
                if attempt:raise ValueError('原生单位JSON恢复后仍无法解析，候选未提交：'+str(exc)) from exc
                prompt=h.json_recovery_prompt(prompt,exc,observer,cancel_check=lambda:bool(session.get('cancel_requested')))
        draft = parsed.get('order')
        if not isinstance(draft,dict):
            raise ValueError('原生Agent的order须为动作对象；身份由本会话绑定：'+identity)
        if 'unit_id' in draft and draft['unit_id']!=identity:
            raise ValueError('原生Agent提交unit_id='+str(draft['unit_id'])[:128]+'；本会话绑定='+identity+'，不能改写单位身份')
        draft={**draft,'unit_id':identity}
        validated = commands.replace_queue(session, [draft], control_team=cs['control_team'],
            director=cs['director'], no_fire=cs['no_fire'], intent=cs['intent'])
        raw = commands.step_order(session, validated['orders'][0], cs)
        orders.append(raw)
        decisions.append({'team': entry['team'], 'unit_name': entry['name'], 'unit_id': identity,
            'action': raw['action'], 'rationale': str(parsed.get('rationale') or ''),
            'expected_effect': str(parsed.get('expected_effect') or ''), 'source': 'native_unit_agent',
            **({'proposal': proof} if proof else {}),
            'run_ids': [r['id'] for r in observer.runs[start:]]})
        bindings[identity] = binding
        if empty_recovery and observer.progress.get('phase')=='empty_output_recovery':
            observer.progress.pop('phase',None);observer.progress.pop('recovery_attempt',None)
    return orders, decisions
