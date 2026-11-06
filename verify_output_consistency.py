"""Supply/sector/narrative contract regressions from the 50-turn audit."""
import copy
import unittest
from gentactix import adjudicator, battlefield, fire_control, reporting, supply


def world():
    return {'current_time': '1952-10-14 11:15', 'red_units': [
        {'name': '红方工兵排', 'type': '工兵', 'lat': 38, 'lng': 127.01, 'hp': 90,
         'supply': 100, 'attack_range': 3000, 'supply_node_id': 'r',
         'personnel': {'current': 22, 'committed': 30, 'casualties': 8, 'noncombat_losses': 0}}],
        'blue_units': [], 'engagements': [],
        'supply_nodes': [{'id': 'r', 'team': 'red', 'lat': 38, 'lng': 127}],
        'supply_routes': [{'name': '道路', 'team': 'red', 'unit_name': '红方工兵排',
                           'waypoints': [[38, 127], [38.01, 127.005], [38, 127.01]],
                           'status': 'cut', 'source': '教学估计'}]}


class SupplyTests(unittest.TestCase):
    def test_map_uses_same_polyline_and_status_as_kernel_without_mutation(self):
        w = world(); frozen = copy.deepcopy(w)
        adj = adjudicator.adjudicate(w)
        line = battlefield.build_battlefield_view(w, adj)['supply_lines'][0]
        self.assertEqual(line, adj['units'][0]['supply_paths'][0])
        self.assertEqual(line['coordinates'], w['supply_routes'][0]['waypoints'])
        self.assertEqual((line['status'], line['declared_status']), ('open', 'cut'))
        self.assertTrue(line['estimated'])
        self.assertEqual(w, frozen)

    def test_all_polyline_segments_are_checked_not_the_source_recipient_chord(self):
        w = world(); w['blue_units'] = [{'name': '敌', 'type': '步兵', 'lat': 38.01,
                                        'lng': 127.005, 'hp': 100, 'attack_range': 100}]
        adj = adjudicator.adjudicate(w, params={'control_radius_km': .1})
        self.assertEqual(adj['units'][0]['supply'], '已切断')
        self.assertEqual(adj['units'][0]['cut_by'], '敌')
        self.assertGreater(adj['units'][0]['cut_at_km'], .5)

    def test_small_control_circle_between_old_sampling_points_is_intercepted(self):
        a = [38, 127]; b = adjudicator.offset_point(a, 90, 1)
        center = adjudicator.offset_point(a, 90, .25)
        hit, name, distance = adjudicator._blocked_along(a, b, [('敌', center, .05)])
        self.assertTrue(hit); self.assertEqual(name, '敌'); self.assertAlmostEqual(distance, .2, places=3)
        self.assertFalse(adjudicator._blocked_along(a, b, [('外侧', [38.01, 127], .05)])[0])

    def test_alternative_open_route_keeps_connectivity_and_both_routes_visible(self):
        w = world(); w['blue_units'] = [{'name': '敌', 'type': '步兵', 'lat': 38.01,
                                        'lng': 127.005, 'hp': 100, 'attack_range': 100}]
        w['supply_routes'].append({**w['supply_routes'][0], 'name': '直路', 'waypoints': [[38, 127], [38, 127.01]]})
        row = adjudicator.adjudicate(w, params={'control_radius_km': .1})['units'][0]
        self.assertEqual(row['supply'], '未切断')
        self.assertEqual([r['status'] for r in row['supply_paths']], ['cut', 'open'])
        self.assertEqual(row['supply_path'], w['supply_routes'][1]['waypoints'])

    def test_moving_friendly_truck_cannot_move_declared_depot(self):
        w = world(); w['red_units'].append({'name': '卡车', 'type': '运输', 'lat': 38.02, 'lng': 127, 'hp': 100})
        first = adjudicator.adjudicate(w)['units'][0]
        w['red_units'][1]['lng'] = 128
        second = adjudicator.adjudicate(w)['units'][0]
        self.assertEqual(first['supply_path'], second['supply_path'])

    def test_wrong_team_duplicate_and_missing_nodes_never_use_a_guessed_depot(self):
        for mode in ('wrong', 'duplicate', 'missing'):
            w = world()
            if mode == 'wrong': w['supply_nodes'][0]['team'] = 'blue'
            elif mode == 'duplicate': w['supply_nodes'] *= 2
            else: w['supply_nodes'] = []
            row = adjudicator.adjudicate(w)['units'][0]
            self.assertEqual(row['supply_basis'], 'unknown'); self.assertEqual(row['supply_path'], [])
            self.assertTrue(row['supply_warnings'])

    def test_invalid_polyline_falls_back_to_known_node_with_warning(self):
        w = world(); w['supply_routes'][0]['waypoints'][1] = [float('nan'), 127]
        row = adjudicator.adjudicate(w)['units'][0]
        self.assertEqual(row['supply_basis'], 'node_direct'); self.assertTrue(row['supply_warnings'])

    def test_moved_recipient_adds_visible_estimated_last_mile(self):
        w = world(); original = copy.deepcopy(w['supply_routes'][0]['waypoints'])
        w['red_units'][0]['lng'] = 127.02
        row = adjudicator.adjudicate(w)['units'][0]
        self.assertEqual(row['supply_path'][:-1], original)
        self.assertEqual(row['supply_path'][-1], [38, 127.02])
        self.assertIn('末段', row['supply_paths'][0]['source'])

    def test_stale_adjudication_status_cannot_be_applied_to_changed_route(self):
        w = world(); adj = adjudicator.adjudicate(w)
        w['supply_routes'][0]['waypoints'][1] = [38.02, 127]
        line = battlefield.build_battlefield_view(w, adj)['supply_lines'][0]
        self.assertEqual(line['status'], 'unknown')

    def test_rearmost_unit_does_not_pick_a_front_unit_as_its_rear(self):
        rear = {'pos': (38, 127), 'name': '后'}
        front = {'pos': (38.01, 127), 'name': '前'}
        result = adjudicator._rear_point([rear, front], (38.02, 127), rear)
        self.assertLess(result[0], rear['pos'][0])
        self.assertAlmostEqual(adjudicator.distance_km(result, rear['pos']), 8, places=3)


class FireTests(unittest.TestCase):
    def shot(self, bearing, sector=0, arc=60):
        w = world(); u = w['red_units'][0]
        u['fire_sector'] = {'bearing_deg': sector, 'arc_deg': arc}
        p = [u['lat'], u['lng']]; target = adjudicator.offset_point(p, bearing, .3)
        w['engagements'] = [{'attacker': u['name'], 'attacker_pos': p, 'lat': target[0], 'lng': target[1]}]
        return w

    def test_wrap_boundary_and_actual_outside_sector(self):
        for bearing in (350, 0, 30): self.assertEqual(fire_control.check(self.shot(bearing)), [])
        self.assertEqual(fire_control.check(self.shot(31))[0]['code'], 'outside_sector')

    def test_unknown_direction_is_not_guessed(self):
        w = self.shot(180); del w['red_units'][0]['fire_sector']
        self.assertEqual(fire_control.check(w), [])

    def test_inherited_sector_cannot_be_bypassed_by_omission(self):
        old = self.shot(0); new = self.shot(180); del new['red_units'][0]['fire_sector']
        self.assertIn('outside_sector', [i['code'] for i in fire_control.check(new, old)])

    def test_rotation_requires_reason_and_fixed_sector_cannot_rotate(self):
        old = self.shot(0); new = self.shot(180, 180)
        self.assertIn('undeclared_reorientation', [i['code'] for i in fire_control.check(new, old)])
        new['red_units'][0]['fire_sector_change'] = {'reason': '完成炮架转向，重新校射'}
        self.assertEqual(fire_control.check(new, old), [])
        old['red_units'][0]['fire_sector']['fixed'] = True
        self.assertIn('undeclared_reorientation', [i['code'] for i in fire_control.check(new, old)])

    def test_unknown_origin_range_and_sector_are_separate_checks(self):
        w = self.shot(180); w['red_units'][0]['attack_range'] = 50
        codes = {i['code'] for i in fire_control.check(w)}
        self.assertTrue({'outside_sector', 'range_exceeded'} <= codes)
        w['engagements'][0]['attacker_pos'] = [float('nan'), 0]
        self.assertIn('invalid_position', {i['code'] for i in fire_control.check(w)})
        w['engagements'][0]['attacker'] = '不存在'
        self.assertIn('unknown_attacker', {i['code'] for i in fire_control.check(w)})


class NarrativeTests(unittest.TestCase):
    def test_actual_zero_ammunition_consumption_is_not_claiming_no_ammunition(self):
        w=world();w['mission']={'definition':{},'ledger':[dict(unit='红方工兵排',ammo_spent=0,spent={})]}
        text,audit=reporting.render('本轮无弹药消耗。',w,turn=1)
        self.assertEqual(audit['status'],'screened')
        self.assertIn('无弹药消耗',text)
        _,audit=reporting.render('蓝方无弹可射。',w,turn=1)
        self.assertIn('inventory_claim',{i['code'] for i in audit['issues']})

    def test_zero_consumption_claim_requires_known_matching_receipts(self):
        for ledger in (None,[dict(unit='红方工兵排',ammo_spent=3,spent={})],
                       [dict(unit='红方工兵排',ammo_spent=0,spent={'shells':1})]):
            w=world()
            if ledger is not None:w['mission']={'definition':{},'ledger':ledger}
            with self.subTest(ledger=ledger):
                _,audit=reporting.render('本轮无弹药消耗。',w,turn=1)
                self.assertIn('inventory_claim',{i['code'] for i in audit['issues']})

    def test_unit_scoped_zero_consumption_does_not_deny_other_unit_fire(self):
        w=world();w['red_units'].append({'name':'红方步兵排','hp':100})
        w['mission']={'definition':{},'ledger':[dict(unit='红方工兵排',ammo_spent=0,spent={}),dict(unit='红方步兵排',ammo_spent=2,spent={})]}
        w['engagements']=[{'attacker':'红方步兵排'}]
        _,audit=reporting.render('红方工兵排本轮无弹药消耗。红方步兵排实施射击。',w,turn=1)
        self.assertEqual(audit['status'],'screened')

    def test_body_clock_is_not_hidden_by_correct_header(self):
        w = world(); old = {**w, 'current_time': '1952-10-14 11:00'}
        text = '【T+29 | 1952-10-14 11:15】七点一刻，高地安静。'
        result, audit = reporting.render(text, w, old, turn=29)
        self.assertIn('narrative_clock', {x['code'] for x in audit['issues']})
        self.assertNotIn('七点一刻', result); self.assertEqual(audit['original_text'], text)
        self.assertIn('11:15', result)

    def test_full_strength_and_supply_are_replaced_by_actual_ledger(self):
        w = world(); frozen = copy.deepcopy(w)
        result, audit = reporting.render('红方炮兵、工兵、运输三单位满编满供。', w, turn=50)
        self.assertNotIn('满编满供', result); self.assertIn('22/30', result)
        self.assertEqual(w, frozen); self.assertEqual(audit['status'], 'fallback')

    def test_no_fabricated_ammunition_from_zero_supply_or_hp(self):
        w = world(); w['red_units'][0].update(supply=0, hp=1)
        result, audit = reporting.render('弹药归零，红方快没人了。', w, turn=1)
        self.assertIn('22/30', result); self.assertNotIn('快没人', result)
        self.assertTrue({'inventory_claim', 'strength_claim'} <= {x['code'] for x in audit['issues']})

    def test_history_and_direction_claims_require_evidence(self):
        _, audit = reporting.render('今天第一次受阻，是唯一变化。七个方向全部被封，退路只剩一条。', world(), turn=1)
        self.assertTrue({'history_superlative', 'direction_count'} <= {x['code'] for x in audit['issues']})

    def test_review_keeps_recommendations_but_not_conflicting_sentence(self):
        result, audit = reporting.render('工兵满编。建议检查补给线路。', world(), review=True)
        self.assertNotIn('工兵满编', result); self.assertIn('建议检查补给线路', result)
        self.assertIn('22/30', result); self.assertTrue(audit['issues'])

    def test_unknown_numbers_stay_unknown_and_a_little_is_not_a_clock(self):
        w = world(); w['red_units'][0].pop('personnel')
        result, audit = reporting.render('炮位补上一点补给。', w, turn=1)
        self.assertEqual(audit['issues'], []); self.assertIn('未记录/未记录', result)

    def test_wrong_date_header_and_multiday_explicit_times_are_detected(self):
        w = world()
        text, audit = reporting.render('【T+99 | 1952-10-15 11:15】正文。', w, turn=29)
        self.assertIn('report_header', {i['code'] for i in audit['issues']})
        self.assertTrue(text.startswith('【T+29 | 1952-10-14 11:15】'))
        _, audit = reporting.render('1952-10-15 11:15发生交火。', w, turn=29)
        self.assertIn('narrative_clock', {i['code'] for i in audit['issues']})

    def test_live_review_regression_does_not_grant_firing_rights_from_connectivity(self):
        text, audit = reporting.render('几何内核给出的补给通断已把结论写死：谁先转open谁就获得开火权。'
                                       '蓝方无弹可射。建议继续观察。', world(), review=True)
        self.assertNotIn('开火权', text); self.assertNotIn('无弹可射', text)
        self.assertIn('建议继续观察', text)
        self.assertTrue({'inventory_claim', 'geometry_claim'} <= {x['code'] for x in audit['issues']})


class CampaignNarrativeTests(unittest.TestCase):
    def setUp(self):
        from tools.qa.campaign_plan_fixture import world
        self.world = world()

    def test_real_partial_formation_and_internal_goal_prose_is_not_published_as_fact(self):
        text, audit = reporting.render('红方五个步兵师全部待命。north已完成，south仍active，preserve为waiting_dependency。',
                                       self.world, turn=0)
        self.assertEqual(audit['status'], 'fallback')
        codes = {r['code'] for r in audit['issues']}
        self.assertTrue({'partial_formation_scope', 'internal_goal_label'} <= codes)
        self.assertNotIn('五个步兵师', text)
        self.assertNotIn('waiting_dependency', text)
        self.assertIn('第161师万家岭投入部', text)

    def test_correct_scoped_names_remain_available_for_explanation(self):
        text, audit = reporting.render('第161师万家岭投入部保持待命；北侧方向控制尚未达成。', self.world, turn=0)
        self.assertEqual(audit['status'], 'screened')
        self.assertIn('第161师万家岭投入部保持待命', text)

    def test_actual_first_turn_cannot_publish_input_pending_as_new_goal_verdict(self):
        from backend import dsh_simulation
        from verify_campaign_plan_backends import proposal
        world = dsh_simulation.apply(self.world, proposal(self.world), '30分钟')
        text, audit = reporting.render('本回合为会战首轮物理观察，目标图各节点仍处于pending状态。', world, self.world, turn=1)
        self.assertEqual(audit['status'], 'fallback')
        self.assertNotIn('pending', text)
        self.assertIn('当前条件成立；前置目标尚未达成', text)

    def test_program_facts_distinguish_predicate_from_unmet_dependencies(self):
        from backend import dsh_simulation
        from verify_campaign_plan_backends import proposal
        self.world = dsh_simulation.apply(self.world, proposal(self.world), '30分钟')
        self.assertTrue(self.world['campaign_plan']['nodes']['preserve']['condition'])
        text = reporting.facts(self.world)
        self.assertIn('两方向达成后保持投入兵力：当前条件成立；前置目标尚未达成', text)
        self.assertNotIn('waiting_dependency', text)

    def test_dsh_turn_prompt_preserves_scoped_names_and_host_goal_semantics(self):
        from backend import dsh_simulation
        text = dsh_simulation.prompt(self.world)
        self.assertIn('投入部', text)
        self.assertIn('不得把部分投入单位汇称完整师', text)
        self.assertIn('物理条件成立不等于前置目标已完成', text)
        import json
        view=json.loads(text.split('\n当前态势：',1)[1].split('\n史料：',1)[0])
        self.assertNotIn('campaign_plan', view)

    def completed_world(self):
        from verify_force_task_execution import setup, register, execution, step
        s,_,groups,points=setup()
        first=register(s,groups['north'],points['north'],execution('先行'))
        register(s,groups['south'],points['south'],execution('预备',after=[first]))
        first_frame,_=step(s);last,_=step(first_frame)
        return last['war_state'],first_frame['war_state']

    def test_real_second_round_is_not_published_as_first_execution_round(self):
        after,previous=self.completed_world()
        for raw in ['本回合（1938-10-07 00:30至01:00）为轮初态势的首轮执行。第51师按令南移。',
                    '本轮是第一轮推演。','本轮序号T+1，部队开始行动。']:
            with self.subTest(raw=raw):
                text,audit=reporting.render(raw,after,previous,turn=2)
                self.assertIn('narrative_turn',{i['code'] for i in audit['issues']})
                self.assertNotIn('首轮执行',text)
                self.assertEqual(audit['original_text'],raw)

    def test_completed_goal_cannot_be_described_as_pending_next_round(self):
        after,previous=self.completed_world()
        raw='第51师到位后南侧方向控制条件待后续回合观察确认。'
        text,audit=reporting.render(raw,after,previous,turn=2)
        self.assertIn('goal_verdict',{i['code'] for i in audit['issues']})
        self.assertNotIn('待后续回合观察确认',text)
        self.assertIn('南侧方向控制：当前条件成立；目标条件满足',text)

    def test_unmet_goal_cannot_be_reported_complete_and_condition_is_separate(self):
        from backend import dsh_simulation
        from verify_campaign_plan_backends import proposal
        after=dsh_simulation.apply(self.world,proposal(self.world),'30分钟')
        for raw in ['南侧方向控制已完成。','两方向达成后保持投入兵力的当前条件不成立。']:
            with self.subTest(raw=raw):
                _,audit=reporting.render(raw,after,self.world,turn=1)
                self.assertIn('goal_verdict',{i['code'] for i in audit['issues']})

    def test_prior_goal_state_and_conditional_planning_are_not_final_verdicts(self):
        after,previous=self.completed_world()
        raw='轮初南侧方向控制尚未达成。若南侧方向控制未完成，下一回合应继续机动。第51师首次执行南移，本轮为第二轮推演。'
        text,audit=reporting.render(raw,after,previous,turn=2)
        self.assertEqual(audit['status'],'screened')
        self.assertIn('轮初南侧方向控制尚未达成',text)

    def test_explicit_round_context_uses_session_not_only_phase_turn(self):
        from backend import dsh_simulation
        text=dsh_simulation.prompt(self.world,turn=9)
        self.assertIn('本轮序号T+9',text)
        self.assertIn('目标由宿主在本轮结果校验后评分',text)

    def test_actual_fresh_first_cannot_deny_first_round_or_claim_no_scoring(self):
        from backend import dsh_simulation
        from verify_campaign_plan_backends import proposal
        after=dsh_simulation.apply(self.world,proposal(self.world),'30分钟')
        raw='本回合为T+1，非战局首轮编号；各方向目标尚未经物理观察评分。'
        text,audit=reporting.render(raw,after,self.world,turn=1)
        self.assertTrue({'narrative_turn','goal_verdict'}<={i['code'] for i in audit['issues']})
        self.assertNotIn('非战局首轮编号',text)
        self.assertNotIn('尚未经物理观察评分',text)

    def test_true_predicate_waiting_dependencies_and_latched_verdict_are_distinct(self):
        from backend import dsh_simulation
        from verify_campaign_plan_backends import proposal
        after=dsh_simulation.apply(self.world,proposal(self.world),'30分钟')
        text,audit=reporting.render('两方向达成后保持投入兵力的当前条件成立，目标尚未完成。',after,self.world,turn=1)
        self.assertEqual(audit['status'],'screened')
        # A latched milestone may remain completed after its predicate stops
        # holding. This is a report-input fixture, not new battle execution.
        latched=copy.deepcopy(after)
        latched['campaign_plan']['nodes']['north'].update(status='completed',condition=False)
        for node in latched['mission']['definition']['campaign_plan']['nodes']:
            if node['id']=='north':node['latch']=True
        _,audit=reporting.render('北侧方向控制的当前条件不成立，该目标已完成。',latched,after,turn=2)
        self.assertEqual(audit['status'],'screened')

    def test_review_and_unit_first_action_are_not_current_round_ordinals(self):
        after,previous=self.completed_world()
        for raw in ['本轮不是首轮。第51师首次执行该任务。','首轮第159师北移，本轮第51师南移。']:
            _,audit=reporting.render(raw,after,previous,turn=2)
            self.assertEqual(audit['status'],'screened')
        _,audit=reporting.render('首轮南侧方向控制尚未完成。建议核对两轮任务差异。',after,previous,turn=2,review=True)
        self.assertEqual(audit['status'],'screened')


if __name__ == '__main__':
    unittest.main(verbosity=2)
