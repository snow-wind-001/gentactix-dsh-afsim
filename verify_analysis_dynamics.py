"""Visible causal explanations use committed motion receipts, not speculation."""
import copy
import unittest

from backend import afsim_state
from gentactix import missions, movement_feedback as movement, sim_clock
from verify_movement_feedback import world


def example(*, estimated=False):
    before = world()
    after = copy.deepcopy(before)
    after['mission']['turn'] = 1
    seconds = sim_clock.duration_seconds(before['mission']['definition']['time_step'])
    after['simulation_clock']['elapsed_seconds'] = seconds
    orders = []
    for index, ((_, old), (_, new)) in enumerate(zip(missions.units(before),missions.units(after))):
        action = 'move' if index == 0 else 'hold'
        if action == 'move': new['lng'] += .002
        ground = missions.distance(old,new) if action=='move' else 0
        new['formation']['fatigue'] = movement.fatigue_value(before,old,action,ground,following=new)
        orders.append(dict(unit=old['name'],action=action))
    receipt = movement.validate_transition(before,after,orders,seconds,
        source='dsh_model_estimate' if estimated else 'afsim_native_estimate')
    if estimated: after['dsh_execution'] = {'movement':receipt}
    else:
        after['afsim'] = {'entity_count':len(orders)}
        after['combined_arms']['movement_feedback'] = receipt
    frame = dict(turn=1,before=before,after=after,changes=[])
    return dict(id='analysis-motion-qa',turn_count=1,war_state=after,
        time_step=before['mission']['definition']['time_step'],trajectory=[frame])


class AnalysisDynamicsTests(unittest.TestCase):
    def test_prompt_preserves_causal_direction_instead_of_treating_wait_as_fatigue_source(self):
        session = example()
        prompt = afsim_state.analysis_prompt(session,'解释疲劳与等待')
        self.assertIn('轮初疲劳影响等待',prompt)
        self.assertIn('等待不作为疲劳增量',prompt)

    def test_native_and_dsh_facts_show_prior_current_and_actual_ground_without_changing_world(self):
        for estimated in (False,True):
            session = example(estimated=estimated);saved=copy.deepcopy(session)
            text = afsim_state.analysis_facts(session)
            old = session['trajectory'][0]['before']['red_units'][0]
            new = session['war_state']['red_units'][0]
            self.assertIn(f"轮初疲劳{old['formation']['fatigue']:g}→当前{new['formation']['fatigue']:g}",text)
            self.assertIn('本轮陆地里程',text)
            self.assertIn('等待不作为疲劳增量',text)
            self.assertIn('DSH模型估计' if estimated else 'AFSIM教学模型',text)
            self.assertEqual(session,saved)

    def test_missing_prior_frame_leaves_cause_unknown_despite_current_fatigue(self):
        session = example();session['trajectory']=[]
        text=afsim_state.analysis_facts(session)
        self.assertIn('疲劳归因缺少同轮前态或运动回执',text)
        self.assertNotIn('疲劳已核对',text)

    def test_stale_or_inconsistent_receipt_does_not_certify_cause(self):
        for change in ('stale','inconsistent'):
            session=example();receipt=session['war_state']['combined_arms']['movement_feedback']
            if change=='stale':receipt['turn']=0
            else:receipt['units'][0]['fatigue_expected']+=10
            text=afsim_state.analysis_facts(session)
            self.assertIn('疲劳归因',text)
            if change=='inconsistent':self.assertIn('不一致',text)
            else:self.assertIn('缺少同轮前态或运动回执',text)

    def test_legacy_without_motion_model_keeps_existing_analysis_unextended(self):
        session=example();session['war_state']['mission']['definition'].pop('movement_feedback')
        self.assertNotIn('等待不作为疲劳增量',afsim_state.analysis_prompt(session,'解释当前'))
        self.assertNotIn('疲劳归因',afsim_state.analysis_facts(session))


if __name__ == '__main__':unittest.main()
