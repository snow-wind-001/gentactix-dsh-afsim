"""A zero exit code cannot authenticate a WSF run that reported script errors."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import afsim_world,afsim_turns,harness_engine as h


class AfsimExecutionErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.paths=dict(state=self.root/'state',workspace=self.root/'workspace')
        self.paths['state'].mkdir();self.log=self.paths['state']/'public-stdout.txt'
        self.world=dict(current_time='1938-10-06 00:00',red_units=[dict(name='甲',type='步兵',lat=29.3,lng=115.5)],blue_units=[])
        self.scene=afsim_world.compile_scene(self.world,[],900)
        lines=['WSF Version: 2.9.0 fixture','GTXCLOCK|900']
        for identity,row in self.scene['entities'].items():
            lat=row['origin']['lat'];lng=row['origin']['lng']
            lines.append(f'GTXPOS|{identity}|{int(lat)}|{round((lat-int(lat))*1e8)}|{int(lng)}|{round((lng-int(lng))*1e8)}')
        lines.append('Simulation complete');self.valid='\n'.join(lines)
        self.addCleanup(patch.stopall)
        patch('tools.afsim.launch.layout',return_value=self.paths).start()
        patch.object(h,'afsim_call',side_effect=self.call).start()

    def call(self,tool,args):
        self.assertEqual(tool,'run_mission')
        payload=(dict(status='completed',returncode=0,stdout_path=str(self.log))
                 if args.get('action')=='status' else dict(process_id='fixture-native-process'))
        return dict(dispatch_id='fixture-dispatch',payload=payload)

    def run_with(self,extra):
        self.log.write_text(self.valid+'\n'+extra)
        return afsim_world.run_scene({},self.scene)

    def test_script_exception_with_zero_exit_and_complete_positions_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'AFSIM.*错误'):
            self.run_with('***** ERROR: Script Exception:\nDescription: AuxData exists, but is not correct type.')

    def test_fatal_and_explicit_domain_error_are_not_treated_as_success(self):
        for message in ('***** FATAL: execution failed','GTXERROR|unknown-physical-effect'):
            with self.subTest(message=message),self.assertRaises(RuntimeError):self.run_with(message)

    def test_rejected_output_keeps_native_status_and_failure_evidence(self):
        with self.assertRaises(RuntimeError):self.run_with('***** ERROR: Script Exception:')
        jobs=list((self.paths['workspace']/'jobs').iterdir());self.assertEqual(len(jobs),1)
        failure=json.loads((jobs[0]/'failure.json').read_text())
        self.assertEqual(failure['returncode'],0)
        self.assertEqual(failure['status'],'completed')
        self.assertEqual(failure['reason'],'native_output_error')
        self.assertFalse((jobs[0]/'result.json').exists())

    def test_error_blocks_observation_and_state_application_unchanged(self):
        before=copy.deepcopy(self.world);self.log.write_text(self.valid+'\n***** ERROR: Script Exception:')
        session=dict(war_state=self.world,time_step='15分钟')
        with patch.object(afsim_world,'apply_observations',side_effect=AssertionError('No state application')):
            with self.assertRaisesRegex(RuntimeError,'AFSIM.*错误'):
                afsim_turns.execute_scene(session,[],h.RunObserver('fixture'),scene=self.scene)
        self.assertEqual(self.world,before)

    def test_warnings_and_embedded_error_words_are_not_runtime_error_records(self):
        positions,evidence=self.run_with('***** WARNING: diagnostic only\nlabel contains ***** ERROR: historical text')
        self.assertEqual(len(positions),1);self.assertEqual(evidence['returncode'],0)

    def test_clean_complete_native_result_retains_existing_contract(self):
        positions,evidence=self.run_with('')
        self.assertEqual(positions[next(iter(positions))],{'lat':29.3,'lng':115.5})
        self.assertEqual(evidence['source'],'dsh_native_mcp_controller')
        self.assertEqual(evidence['entity_count'],1)


if __name__=='__main__':unittest.main()
