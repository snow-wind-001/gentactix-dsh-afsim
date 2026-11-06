"""Custom synthetic inputs are reproducible parameters, never historical data."""
import copy
import unittest
from gentactix import combined_arms as ca, missions


def configuration(red=2, blue=4):
    return {'version':'synthetic-config-1', 'teams':{
        t:[{'name':f'{t}自定义编组{i+1}', 'personnel':1200+i*100,
            'equipment':{'armor':i,'artillery':4,'air_defense':2,'engineer':6,'transport':12},
            'food':60,'ammo':70,'shells':100,'aa_rounds':80,'fuel_liters':900,'fatigue':20}
           for i in range(n)] for t,n in [('red',red),('blue',blue)]}}


class SyntheticConfigurationTests(unittest.TestCase):
    def test_fractional_food_and_ammo_work_is_preserved_without_rounding(self):
        config=configuration(1,1);config['teams']['red'][0].update(food=.125,ammo=1.375)
        original=copy.deepcopy(config)
        world=missions.initial('CA-AJ18-v1',configuration=config)
        self.assertEqual(world['red_units'][0]['logistics'],{'food':.125,'ammo':1.375})
        self.assertEqual(config,original)
        self.assertTrue(missions.validate(world))

    def test_fractional_stock_validation_still_rejects_boolean_nonfinite_and_out_of_range(self):
        for field in ('food','ammo'):
            for value in (True,False,float('nan'),float('inf'),-float('inf'),-.001,100.001,'0.5',None):
                with self.subTest(field=field,value=value):
                    config=configuration(1,1);config['teams']['red'][0][field]=value
                    with self.assertRaises(ValueError):ca.configure('CA-AJ18-v1',config)

    def test_discrete_formation_counts_remain_integer_when_stocks_are_fractional(self):
        for field in ('personnel','shells','aa_rounds','fuel_liters','fatigue'):
            with self.subTest(field=field):
                config=configuration(1,1);config['teams']['red'][0][field]=1.25
                with self.assertRaises(ValueError):ca.configure('CA-AJ18-v1',config)
        config=configuration(1,1);config['teams']['red'][0]['equipment']['artillery']=1.25
        with self.assertRaises(ValueError):ca.configure('CA-AJ18-v1',config)

    def test_unequal_rosters_and_counts_use_separate_ledgers(self):
        c=configuration(); w=missions.initial('CA-AJ18-v1', configuration=c)
        self.assertEqual([len(w[t+'_units']) for t in ('red','blue')],[2,4])
        self.assertEqual(w['blue_units'][3]['personnel']['current'],1500)
        self.assertEqual(w['blue_units'][3]['equipment'][0]['operational'],3)
        self.assertEqual(w['red_units'][0]['logistics'],{'food':60,'ammo':70})
        missions.validate(w)

    def test_base_definition_and_input_are_not_modified(self):
        baseline=ca.definition('CA-AJ18-v1'); c=configuration(); saved=copy.deepcopy(c)
        ca.configure('CA-AJ18-v1',c)
        self.assertEqual(c,saved); self.assertEqual(ca.definition('CA-AJ18-v1'),baseline)

    def test_equal_configuration_has_equal_hash_and_changed_count_changes_it(self):
        c=configuration(); a=missions.initial('CA-AJ18-v1', configuration=c)
        b=missions.initial('CA-AJ18-v1', configuration=copy.deepcopy(c))
        self.assertEqual(a['mission']['definition_hash'],b['mission']['definition_hash'])
        c['teams']['blue'][0]['personnel']+=1
        self.assertNotEqual(a['mission']['definition_hash'],missions.initial('CA-AJ18-v1', configuration=c)['mission']['definition_hash'])

    def test_tampered_definition_and_ledger_are_rejected(self):
        a=missions.initial('CA-AJ18-v1', configuration=configuration())
        a['mission']['definition']['initial_state']['red_units'][0]['personnel']['current']+=1
        with self.assertRaises(ValueError): missions.validate(a)
        a=missions.initial('CA-AJ18-v1', configuration=configuration())
        a['red_units'][0]['equipment'][0]['operational']+=1
        with self.assertRaises(ValueError): missions.validate(a)

    def test_invalid_counts_unknown_fields_and_duplicate_names_are_rejected(self):
        bad=[]
        for key,value in [('personnel',True),('personnel',0),('personnel',100001),('shells',-1),('fatigue',101),('food',float('nan'))]:
            c=configuration();c['teams']['red'][0][key]=value;bad.append(c)
        c=configuration();c['teams']['red']=[];bad.append(c)
        c=configuration(13,1);bad.append(c)
        c=configuration();c['teams']['blue'][0]['name']=c['teams']['red'][0]['name'];bad.append(c)
        c=configuration();c['teams']['red'][0]['arbitrary_script']='include evil';bad.append(c)
        c=configuration();c['teams']['red'][0]['equipment']['laser']=1;bad.append(c)
        for c in bad:
            with self.subTest(c=c), self.assertRaises(ValueError):ca.configure('CA-AJ18-v1',c)

    def test_native_template_accepts_custom_roster_without_python_combat(self):
        from backend import afsim_world
        w=missions.initial('CA-AJ18-v1', configuration=configuration(1,3))
        orders=[{'unit':u['name'],'action':'hold'} for _,u in missions.units(w)]
        scene=afsim_world.compile_scene(w,orders,1800,native_rules=True)
        self.assertEqual(len(scene['entities']),4)
        self.assertIn('GTXMODEL',scene['script'])
        with self.assertRaises(ValueError):missions.advance(w,orders,'30分钟')

    def test_api_config_persists_and_cannot_be_used_in_historical_replay(self):
        import os, tempfile
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from backend import main, session_store
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GENTACTIX_SESSION_DIR':directory}), \
                patch('tools.afsim.launch.status',return_value={'available':True}):
            client=TestClient(main.app); c=configuration()
            r=client.post('/api/sessions',json={'scenario':'自定义编制验收','mission_id':'CA-AJ18-v1','execution_backend':'afsim','synthetic_configuration':c})
            self.assertEqual(r.status_code,200,r.text); sid=r.json()['session_id']
            s=main._SESSIONS[sid];s['war_state']=missions.initial(s['mission_id'],configuration=c)
            session_store.save(s); restored,errors=session_store.load_all()
            self.assertEqual(errors,[]);self.assertEqual(restored[sid]['synthetic_configuration'],c)
            self.assertEqual(restored[sid]['war_state'],s['war_state'])
            r=client.post('/api/sessions',json={'scenario':'拒绝改史料','simulation_mode':'replay','synthetic_configuration':c})
            self.assertEqual(r.status_code,422)
            main._SESSIONS.pop(sid,None)


if __name__=='__main__':unittest.main()
