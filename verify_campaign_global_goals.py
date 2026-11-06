"""Invalid global goal inputs must be rejected before unit drafts lock globals."""
import copy
import json
import subprocess
import unittest

from backend import scenario_builder as sb, scenario_assembly as sa
from tools.qa.transfer_campaign_fixture import campaign_inputs
from tools.upgrade_long_march_transfer import WINDOW


class CampaignGlobalGoalsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot,self.parameters=campaign_inputs()
        self.basis=sb.historical_basis(self.snapshot['definition']['battle'],force_scope='campaign',campaign_window_id=WINDOW,termination_mode='objectives')
        self.assembly=sa.create(self.basis);self.addCleanup(sa.close,self.assembly.id)

    def globals(self):
        result={k:copy.deepcopy(v) for k,v in self.parameters.items() if k not in ('format','phase_id','actors')}
        result['campaign_scope'].pop('window')
        return result

    def test_null_threshold_is_rejected_without_saving_or_locking_globals(self):
        before=self.assembly.export_state();value=self.globals()
        value['campaign_plan']['nodes'][0]['condition']['minimum_personnel']=None
        result=self.assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':value})
        self.assertFalse(result['updated'],result)
        self.assertEqual(self.assembly.export_state(),before)

    def test_unknown_actor_is_rejected_in_global_stage_not_readonly_final(self):
        value=self.globals();value['campaign_plan']['nodes'][0]['unit_ids']=['invented.army']
        result=self.assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':value})
        self.assertFalse(result['updated'],result)
        self.assertFalse(self.assembly.global_ready)

    def test_cyclic_global_dependencies_cannot_be_saved_as_a_valid_partial_draft(self):
        value=self.globals();value['campaign_plan']['nodes'][0]['after']['node_ids']=['transfer-resources']
        result=self.assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':value})
        self.assertFalse(result['updated'],result)
        self.assertEqual(self.assembly.revision,0)

    def test_valid_global_goals_do_not_require_invented_unit_strengths(self):
        before=copy.deepcopy(self.basis['configuration_template']['actors'])
        result=self.assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':self.globals()})
        self.assertTrue(result['updated'],result)
        self.assertEqual(self.assembly.configuration['actors'],before)
        self.assertTrue(all(a['personnel'] is None for a in before.values()))

    def test_failed_global_goal_can_be_corrected_before_the_unit_stage(self):
        bad=self.globals();bad['campaign_plan']['nodes'][-1]['condition']['minimum_food']=None
        result=self.assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':bad})
        self.assertFalse(result['updated'],result)
        result=self.assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':self.globals()})
        self.assertTrue(result['updated'],result)
        for part in self.assembly.parts:
            result=self.assembly.tool(part,'update_scenario_configuration',{'revision':self.assembly.revision,
                'patch':{'actors':{i:self.parameters['actors'][i] for i in self.assembly.assigned(part)}}})
            self.assertTrue(result['updated'],result)
        self.assertTrue(self.assembly.tool('final','validate_scenario_configuration',{})['valid'])

    def test_frontend_admits_transfer_only_with_readonly_source_scope(self):
        interaction=self.basis['interaction'];p=self.parameters
        cases=[{'parameters':p,'interaction':interaction},{'parameters':p}]
        for edit in ('owner','surrender','region','mode','graph'):
            bad=copy.deepcopy(p)
            if edit=='owner':bad['goal']['team']='blue'
            elif edit=='surrender':bad['campaign']['surrender']['enabled']=True
            elif edit=='region':bad['campaign']['objective']['relief_regions']=[{'center':p['area']['center'],'radius_km':1}]
            elif edit=='mode':bad['goal']['termination_mode']='deadline'
            else:bad.pop('campaign_plan')
            cases.append({'parameters':bad,'interaction':interaction})
        reply=subprocess.run(['node','tools/qa/campaign_delay_contract.mjs'],input=json.dumps(cases),capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(reply.stdout),[True,False,False,False,False,False,False])


if __name__=='__main__':unittest.main()
