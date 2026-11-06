"""Defensive campaign goals must not turn into assaults; legacy stays pinned."""
import copy
import json
import subprocess
import unittest
from gentactix import historical_operations as ho,missions,campaign
from tools.qa.jizhong_assembly_fixture import inputs


class CampaignDelayTests(unittest.TestCase):
    def test_goal_graph_does_not_require_redundant_legacy_relief_regions(self):
        from tools.qa.wanjialing_estimate_fixture import inputs as graph_inputs
        s,p=graph_inputs();p['campaign']['objective']['relief_regions']=[]
        w=ho.initial(s,p)
        self.assertEqual(set(w['campaign_plan']['nodes']),{n['id']for n in p['campaign_plan']['nodes']})
        self.assertEqual(w['mission']['status'],'active')
        delay_s,delay=self.parameters();delay['campaign']['objective']['relief_regions']=[]
        self.assertEqual(ho.initial(delay_s,delay)['mission']['status'],'active')
        legacy_s,legacy=inputs();legacy['campaign']['objective']['relief_regions']=[]
        self.assertNotIn('campaign_plan',legacy)
        with self.assertRaisesRegex(ValueError,'1至6'):ho.initial(legacy_s,legacy)

    def parameters(self):
        snapshot,p=inputs();p['goal'].update(profile='delay',required_survivors=2,required_turns=2)
        p['rules'].update(goal_profile='delay',required_survivors=2)
        p['campaign']['objective_policy']='defensive-delay-1'
        p['goal']['exit']={'lat':38.7,'lng':115.6}
        return snapshot,p

    def world(self):
        s,p=self.parameters();return ho.initial(s,p)

    def test_survival_does_not_require_occupying_assault_points(self):
        w=self.world()
        for _,u in missions.units(w):u['lat']=38.3;u['lng']=115.8
        self.assertFalse(campaign.assess(w)['town_control'])
        for turn in (1,2):w['mission']['turn']=turn;missions.evaluate(w)
        self.assertEqual(w['mission']['winner'],'red');self.assertTrue(w['mission']['metrics']['condition'])

    def test_enemy_reaching_exit_and_force_loss_each_prevent_completion(self):
        for cause in ('enemy_exit','force_loss'):
            w=self.world()
            if cause=='enemy_exit':w['blue_units'][0].update(w['mission']['definition']['exit'])
            else:
                for u in w['red_units']:
                    loss=u['personnel']['current']-1;u['personnel']['current']=1;u['personnel']['casualties']+=loss
            w['mission']['turn']=2;missions.evaluate(w)
            with self.subTest(cause=cause):self.assertFalse(w['mission']['metrics']['condition'])

    def test_future_friendly_units_cannot_satisfy_survivor_count(self):
        s,p=self.parameters();red=[u['id'] for u in s['definition']['units'] if u['team']=='red' and u['id'] in p['actors']]
        for identity in red[1:]:p['campaign']['arrivals'][identity]['not_before']='1942-05-02T00:00:00'
        w=ho.initial(s,p);w['mission']['turn']=1;missions.evaluate(w)
        self.assertFalse(w['mission']['metrics']['condition'])

    def test_future_enemy_at_exit_does_not_block_until_arrival(self):
        s,p=self.parameters();identity=next(u['id'] for u in s['definition']['units'] if u['team']=='blue' and u['id'] in p['actors'])
        p['actors'][identity]['position']=copy.deepcopy(p['goal']['exit']);p['campaign']['arrivals'][identity]['not_before']='1942-05-02T00:00:00'
        w=ho.initial(s,p);w['mission']['turn']=1;missions.evaluate(w)
        self.assertTrue(w['mission']['metrics']['condition'])

    def test_legacy_goal_binding_and_hash_stay_unchanged(self):
        s,p=self.parameters();p['campaign'].pop('objective_policy');legacy=ho.definition(s,p)
        upgraded=copy.deepcopy(p);upgraded['campaign']['objective_policy']='defensive-delay-1'
        new=ho.definition(s,upgraded);self.assertNotEqual(missions.digest(new),missions.digest(legacy))
        restored=ho.from_binding({'format':ho.FORMAT,'initial':s,'parameters':p})
        self.assertEqual(restored,legacy)
        self.assertIn('控制据点',legacy['goal']);self.assertIn('迟滞',new['goal']);self.assertNotIn('控制据点',new['goal'])

    def test_policy_rejects_wrong_profile_or_unknown_version(self):
        for mode in ('bad_version','assault'):
            s,p=self.parameters()
            if mode=='bad_version':p['campaign']['objective_policy']='unknown'
            else:p['goal']['profile']='assault';p['rules']['goal_profile']='assault'
            with self.subTest(mode=mode),self.assertRaises(ValueError):ho.initial(s,p)

    def test_goal_graph_conflict_identifies_the_optional_policy_and_repair(self):
        from tools.qa.wanjialing_estimate_fixture import inputs as graph_inputs
        s,p=graph_inputs()
        p['goal']['profile']='delay';p['rules']['goal_profile']='delay'
        p['campaign']['objective_policy']='defensive-delay-1'
        with self.assertRaisesRegex(ValueError,r'objective_policy.*campaign_plan') as error:
            campaign.validate_parameters(s,p)
        self.assertIn('移除',str(error.exception))
        self.assertIn('不要移入campaign.objective',str(error.exception))
        # The complete supplied graph remains usable once the conflicting
        # optional policy is explicitly removed by the caller.
        p['campaign'].pop('objective_policy')
        campaign.validate_parameters(s,p)
        self.assertIsNotNone(ho.initial(s,p)['campaign_plan'])

    def test_frontend_distinguishes_explicit_delay_from_legacy_campaign_goals(self):
        _,p=self.parameters();legacy=copy.deepcopy(p);legacy['campaign'].pop('objective_policy')
        assault=copy.deepcopy(legacy);assault['goal']['profile']='assault'
        local=copy.deepcopy(legacy);local.pop('campaign')
        reply=subprocess.run(['node','tools/qa/campaign_delay_contract.mjs'],input=json.dumps([p,legacy,assault,local]),text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(reply.stdout),[True,False,True,True])

    def test_frontend_accepts_validated_delay_graph_and_rejects_conflicting_policies(self):
        from tools.qa.wanjialing_estimate_fixture import inputs as graph_inputs
        s,p=graph_inputs();p['goal']['profile']='delay';p['rules']['goal_profile']='delay'
        ho.initial(s,p)  # Backend already accepts this exact supported contract.
        conflict=copy.deepcopy(p);conflict['campaign']['objective_policy']='defensive-delay-1'
        deadline=copy.deepcopy(p);deadline['goal']['termination_mode']='deadline'
        for invalid in [conflict,deadline]:
            with self.assertRaises(ValueError):ho.initial(s,invalid)
        reply=subprocess.run(['node','tools/qa/campaign_delay_contract.mjs'],input=json.dumps([p,conflict,deadline]),text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(reply.stdout),[True,False,False])


if __name__=='__main__':unittest.main()
