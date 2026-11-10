"""Validate DSH-supplied operational effects without generating battle effects."""
import copy
import json
import math
from gentactix import campaign, missions, combat_effects


def _validate_facets(before,prior,row,old,new,order,shell_bound):
    """Validate model-supplied facets and visible intensities; never repair them."""
    campaign._validate_fortification_components(row)
    if len(row['fortification_components'])!=len(prior['fortification_components']):
        raise ValueError('DSH工事侧面须保留原索引和完整数量')
    gain_limit=before['mission']['definition']['combined_rules']['fortify_gain']
    pairs=list(zip(prior['fortification_components'],row['fortification_components']))
    common_gain=max(current['base_entrenchment']-previous['base_entrenchment'] for previous,current in pairs)
    common_loss=max(previous['fortification_integrity']-current['fortification_integrity'] for previous,current in pairs)
    if any(abs(current['base_entrenchment']-min(100,previous['base_entrenchment']+common_gain))>1e-6
           or abs(current['fortification_integrity']-max(0,previous['fortification_integrity']-common_loss))>1e-6
           for previous,current in pairs):
        raise ValueError('工事侧面须按同一构筑增量和共同侵蚀量变化，不能作为多个独立目标')
    for previous,current in zip(prior['fortification_components'],row['fortification_components']):
        loss=previous['fortification_integrity']-current['fortification_integrity']
        if loss<0 or loss>shell_bound+1e-6:raise ValueError('DSH工事侧面损耗缺少实际炮弹或发生无依据修复')
        gain=current['base_entrenchment']-previous['base_entrenchment']
        if gain<0 or gain>gain_limit+1e-6:raise ValueError('DSH工事侧面构筑基准越过本轮能力范围或索引改变')
        if gain and (order.get('action')!='fortify' or old['formation']['materials']<=new['formation']['materials']):
            raise ValueError('DSH工事侧面构筑必须有对应命令和材料消耗')
    spec=campaign.definition(before)
    fortified=spec['fortifications'][campaign.source_actor_key(before,old)]['integrity']>0
    parts=row['fortification_components']
    effective=min(p['base_entrenchment']*(.25+.75*p['fortification_integrity']/100 if fortified else 1) for p in parts)
    if abs(new['formation']['entrenchment']-math.floor(effective+1e-9))>1e-6:
        raise ValueError('DSH工事显示值与已提交的完整侧面状态不一致，不能混用两个最低值')
    protection=min(1,prior['base_protection']+(.25 if order.get('action')=='conceal' else 0))
    if fortified:protection*=.25+.75*min(p['fortification_integrity'] for p in parts)/100
    if abs(new['formation']['protection']-protection)>.001000001:
        raise ValueError('DSH防护值与工事侧面状态不一致')


def validate(before, after, supplied, orders):
    spec=campaign.definition(before)
    if spec is None:
        if supplied is not None:raise ValueError('本局未配置战役过程')
        return
    try:campaign._fields(supplied,{'actors'},'DSH战役过程 $.campaign')
    except ValueError as exc:
        raise ValueError(str(exc)+'；响应最外层必须有campaign，campaign只包含actors。combined_arms更新位于响应最外层$.combined_arms，与campaign并列。') from exc
    old={u['name']:u for _,u in missions.units(before)}
    new={u['name']:u for _,u in missions.units(after)}
    campaign._fields(supplied['actors'],old,'DSH战役部队 $.campaign.actors')
    state=copy.deepcopy(before['campaign'])
    for name,row in supplied['actors'].items():
        prior=state['actors'][name]
        optional={'fortification_components'} if prior.get('fortification_components') else set()
        campaign._fields(row,{'active','fortification_integrity','base_entrenchment','captured_this_turn'}|optional,name+'战役过程')
        if type(row['active']) is not bool or row['active']!=(campaign.release_seconds(after,new[name])==0):
            raise ValueError('DSH入场状态不符合冻结时点：'+name)
        campaign._number(row['fortification_integrity'],0,100,'工事完整度')
        campaign._number(row['base_entrenchment'],0,100,'基础工事')
        loss=prior['fortification_integrity']-row['fortification_integrity']
        if loss<0:raise ValueError('未配置永久工事修复，不能凭空恢复完整度')
        incoming={e['attacker'] for e in after.get('engagements',[]) if e.get('attacker') in orders
            and orders[e['attacker']].get('target')==name and orders[e['attacker']]['action'] in ('bombard','suppress')}
        shells=sum(max(0,old[n]['formation']['shells']-new[n]['formation']['shells']) for n in incoming)
        bound=shells*spec['fortifications'][campaign.source_actor_key(before,old[name])]['degradation_per_shell']
        if loss>bound+1e-6:raise ValueError('工事损耗缺少对应实际炮击和炮弹消耗：'+name)
        if optional:_validate_facets(before,prior,row,old[name],new[name],orders.get(name,{}),bound)
        if row['base_entrenchment']!=prior['base_entrenchment']:
            if orders.get(name,{}).get('action')!='fortify' or row['base_entrenchment']<prior['base_entrenchment']:
                raise ValueError('基础工事变化没有对应构筑命令：'+name)
            if old[name]['formation']['materials']<=new[name]['formation']['materials']:
                raise ValueError('构筑工事必须有材料消耗：'+name)
        captured=row['captured_this_turn']
        delta=combat_effects._count_delta(old[name]['personnel'],new[name]['personnel'],'captured')
        if delta is None and captured==0 and new[name]['personnel'].get('captured')==old[name]['personnel'].get('captured'):
            delta=0  # No new capture claim; existing unknown breakdown stays unknown.
        if type(captured) is not int or not 0<=captured<=old[name]['personnel']['current'] or delta!=captured:
            raise ValueError('本轮受降与累计被俘账不一致：'+name)
        if captured:
            captors=[o for o in orders.values() if o['action']=='capture' and o.get('target')==name]
            if not captors:raise ValueError('被俘增加缺少受降命令：'+name)
            # Before-state eligibility is checked by validate_orders; also require
            # a captor still present at the target at the end of this estimate.
            if not any(new[o['unit']]['personnel']['current']>0 and
                       missions.distance(new[o['unit']],new[name])*1000<=spec['surrender']['range_m']+1
                       for o in captors):raise ValueError('受降方已失能或离开接收距离')
        prior.update(copy.deepcopy(row))
    state.update(turn=after['mission']['turn'],execution_source='dsh_model_estimate')
    after['campaign']=state
    if after['mission']['definition'].get('campaign_plan'):
        state['objective']=campaign.assess(after)


def instruction(world):
    spec=campaign.definition(world)
    if spec is None:return ''
    from gentactix import mission_termination
    ending=('满足冻结规则的连续达标要求后结算，不按规划参考回合自动结束。'
        if mission_termination.objective_driven(world['mission']['definition']) else '在截止回合结算。')
    goal_instruction=('目标由宿主按冻结会战目标图评分，原据点/阻援标志仅保留为过程对照，不控制全局终止。'
        '不得提交或改写campaign_plan状态；不要按历史结局代填目标完成。'
        if world['mission']['definition'].get('campaign_plan') else
        '目标标志由程序判定：据点控制、各阻援区域控制与有生力量保持必须同时满足，')
    facets_note=('\n已有fortification_components的单位须在该actor中明确提交同顺序、同数量的完整数组，每项仅含base_entrenchment和fortification_integrity。'
        '这些是同一单位的潜在工事强度侧面，不能相加当作人数、库存或工事数量；其他单位不得新造数组。'
        '每个侧面完整度不可增加，其损耗分别受实际炮弹证据约束；每个基准不可降低，增加须fortify及材料消耗，且不超过fortify_gain。'
        '一次全单位构筑对所有侧面采用同一增量并在100封顶；炮击采用共同侵蚀量并在0封底，不能任意挑选侧面更新。'
        '有永久工事时，formation.entrenchment取各侧面base_entrenchment*(0.25+0.75*fortification_integrity/100)的最小值并向下取整数；'
        'formation.protection按最小完整度及原base_protection计算，conceal沿既有规则临时增加0.25，千分位量化容差保留。'
        '无永久工事则不乘完整度因子。变化时在unit_updates明确提交对应formation数值；宿主只验证，不代填或纠正模型结果。'
        if any(r.get('fortification_components') for r in world['campaign']['actors'].values()) else '')
    return ('\n本局有显式战役过程参数。每轮额外提交campaign={"actors":{"精确单位名":'
        '{"active":布尔值,"fortification_integrity":0至100,"base_entrenchment":0至100,"captured_this_turn":本轮被俘整数}}}，覆盖全部单位。'
        '响应最外层的campaign仅包含actors；combined_arms如需更新，放在响应最外层与campaign并列。'
        + ('本局全部配置单位从开局active，not_before仅为来源估计参考，不限制行动。'
           if spec.get('availability_mode')=='immediate' else
           'active严格按轮末时钟与not_before判断；等待部队不能提前移动、开火或被攻击。') +
        '永久工事完整度不能增加，减少量不超过实际命中该目标的炮击单位所消耗炮弹×degradation_per_shell；未炮击不减。'
        'base_entrenchment只允许本单位fortify且有材料消耗时增加；不要提交base_protection或来源。'
        'capture命令附target，须满足已知受降范围和压制/缺弹条件；模型可以估计部分或零人受降，不能强制复刻历史俘虏配额。'
        '被俘增加与captured_this_turn一致，包含于casualties合计并相应减少current；这一部分不需要虚构射击事件，其他新增战斗减员仍须有对应交火。'+
        goal_instruction+ending+
        '不要提交campaign.objective、turn、version、execution_source。冻结约束：'+json.dumps(spec,ensure_ascii=False)+facets_note)
