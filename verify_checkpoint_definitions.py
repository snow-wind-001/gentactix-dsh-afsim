"""Lossless single-file checkpoints; fixtures are not historical battle runs."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def fixture_session():
    from backend import main
    from tools.qa.turn_preview_page_fixture import session
    inputs=session();world=inputs['war_state'];definition=world['mission']['definition']
    value=main._new_session('完整22单位存档夹具，不是实际模型推演','1小时',False,
                            definition['battle'],False,False,agent_mode='native')
    value.update(war_state=world,last_war_state=copy.deepcopy(world),mission_id=world['mission']['id'],
                 historical_definition=copy.deepcopy(definition),product_mode='historical',simulation_mode='open')
    return value


class CheckpointDefinitionTests(unittest.TestCase):
    def source(self):
        definition=dict(id='fixture-v1',source='大规模夹具定义，不代表历史实有量。'*400,
                        values=[None,False,0,1.0,.125,-0.0])
        return dict(id='a'*12,historical_definition=copy.deepcopy(definition),
                    war_state=dict(mission=dict(definition=copy.deepcopy(definition)),units=[dict(id='A',people=5)]),
                    trajectory=[dict(before=dict(mission=dict(definition=copy.deepcopy(definition))),
                                     after=dict(mission=dict(definition=copy.deepcopy(definition))))])

    def test_json_save_owns_wire_snapshot_without_transactional_deepcopy(self):
        from backend import session_store as s,checkpoint_codec as c
        value=self.source();saved=copy.deepcopy(value)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            with patch.object(s,'serializable',side_effect=AssertionError('JSON save must not clone the transaction again')):
                s.save(value)
            document=json.loads((Path(directory)/(value['id']+'.json')).read_text())
            restored=c.decode(document)
            self.assertEqual(json.dumps(restored,ensure_ascii=False),json.dumps(saved,ensure_ascii=False))
            self.assertEqual(value,saved)

    def test_unchanged_save_does_not_clone_or_encode(self):
        from backend import session_store as s,checkpoint_codec as c
        value=self.source()
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            s.save(value);path=Path(directory)/(value['id']+'.json')
            before=(path.read_bytes(),path.stat().st_mtime_ns)
            with patch.object(s,'serializable',side_effect=AssertionError('No-op save must not clone history')), \
                 patch.object(c,'encode',side_effect=AssertionError('No-op save must not re-encode')):
                s.save(value)
            self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)

    def test_owned_snapshot_survives_later_input_mutation(self):
        from backend import session_store as s,checkpoint_codec as c
        value=self.source();saved=copy.deepcopy(value);encode=c.encode
        def changing_input(current,**kwargs):
            value['war_state']['units'][0]['people']=99
            return encode(current,**kwargs)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            with patch.object(c,'encode',side_effect=changing_input):s.save(value)
            restored=c.decode(json.loads((Path(directory)/(value['id']+'.json')).read_text()))
            self.assertEqual(value['war_state']['units'][0]['people'],99)
            self.assertEqual(restored,saved)

    def test_cache_signature_uses_captured_wire_when_legacy_input_changes(self):
        from backend import session_store as s,checkpoint_codec as c
        value=self.source();signature=s._signature
        def changing_input(current,wire=None):
            value['war_state']['units'][0]['people']=99
            return signature(current,wire)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            with patch.object(s,'_signature',side_effect=changing_input):s.save(value)
            # The first snapshot preceded the input change. The next save must
            # persist that change rather than mistake it for the saved content.
            s.save(value)
            restored=c.decode(json.loads((Path(directory)/(value['id']+'.json')).read_text()))
            self.assertEqual(restored['war_state']['units'][0]['people'],99)

    def test_non_string_mapping_keys_keep_the_legacy_checkpoint_format(self):
        from backend import session_store as s,checkpoint_codec as c
        value=self.source();value['legacy']={1:'one'};saved=copy.deepcopy(value)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            s.save(value);document=json.loads((Path(directory)/(value['id']+'.json')).read_text())
            self.assertEqual(document['format'],c.V1)
            self.assertEqual(c.decode(document),json.loads(json.dumps(saved)))
            self.assertEqual(value,saved)

    def test_non_json_candidate_preserves_the_previous_durable_checkpoint(self):
        from backend import session_store as s
        value=self.source()
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            s.save(value);path=Path(directory)/(value['id']+'.json')
            before=(path.read_bytes(),path.stat().st_mtime_ns)
            candidate=copy.deepcopy(value);candidate['unsupported']={1,2}
            with self.assertRaises(ValueError):s.save(candidate)
            self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)

    def test_single_file_roundtrip_preserves_order_types_and_values(self):
        from backend import checkpoint_codec as c
        original=self.source();saved=copy.deepcopy(original);packed=c.encode(original)
        self.assertEqual(packed['format'],'gentactix-session-v2')
        self.assertEqual(len(packed['definitions']),1)
        self.assertLess(len(json.dumps(packed,ensure_ascii=False)),len(json.dumps(original,ensure_ascii=False))*.6)
        restored=c.decode(json.loads(json.dumps(packed)))
        self.assertEqual(json.dumps(restored,ensure_ascii=False),json.dumps(original,ensure_ascii=False))
        self.assertEqual(original,saved)

    def test_decoded_definitions_are_independent_mutable_objects(self):
        from backend import checkpoint_codec as c
        packed=c.encode(self.source());before=copy.deepcopy(packed);restored=c.decode(packed)
        restored['war_state']['mission']['definition']['values'][0]=123
        self.assertIsNone(restored['historical_definition']['values'][0])
        self.assertIsNone(restored['trajectory'][0]['after']['mission']['definition']['values'][0])
        self.assertEqual(packed,before)

    def test_unique_short_and_legacy_data_keep_v1_without_reserved_marker_rules(self):
        from backend import checkpoint_codec as c
        for original in (dict(id='a'*12,definition=dict(x=1)),
                         dict(id='a'*12,definition=dict(note='unique'*3000)),
                         dict(id='a'*12,custom={'$definition':'literal','definition_refs':None})):
            with self.subTest(original=original['id']):
                packed=c.encode(original);self.assertEqual(packed['format'],'gentactix-session-v1')
                self.assertEqual(c.decode(packed),original)

    def test_unequal_numeric_types_or_key_order_are_never_coalesced(self):
        from backend import checkpoint_codec as c
        original=self.source();different=copy.deepcopy(original['historical_definition'])
        different['values'][3]=1
        original['last_war_state']=dict(mission=dict(definition=different))
        original['extra']={'definition':dict(reversed(list(original['historical_definition'].items())))}
        self.assertEqual(json.dumps(c.decode(c.encode(original))),json.dumps(original))

    def test_corrupt_body_table_digest_paths_and_unused_definitions_are_refused(self):
        from backend import checkpoint_codec as c
        for kind in ('body','definition','digest','missing','duplicate','path','nonempty','unused'):
            value=c.encode(self.source());ref=value['definition_refs'][0]
            if kind=='body':value['session']['id']='b'*12
            elif kind=='definition':next(iter(value['definitions'].values()))['values'][0]=1
            elif kind=='digest':value['session_digest']='0'*64
            elif kind=='missing':value['definitions'].clear()
            elif kind=='duplicate':value['definition_refs'].append(copy.deepcopy(ref))
            elif kind=='path':ref['path']=['unknown','definition']
            elif kind=='nonempty':value['session']['historical_definition']={}
            else:value['definitions']['0'*64]={'unused':1}
            with self.subTest(kind=kind),self.assertRaises(ValueError):c.decode(value)

    def test_restore_size_is_checked_before_large_reference_expansion(self):
        from backend import checkpoint_codec as c
        packed=c.encode(self.source())
        with self.assertRaisesRegex(ValueError,'大小|上限'):c.decode(packed,max_bytes=1000)
        self.assertEqual(c.decode(packed),self.source())

    def test_nonfinite_data_does_not_create_an_encoded_document(self):
        from backend import checkpoint_codec as c
        for value in (float('nan'),float('inf')):
            original=self.source();original['invalid']=value
            with self.assertRaises(ValueError):c.encode(original)

    def test_legacy_python_tuple_has_the_same_json_representation(self):
        from backend import checkpoint_codec as c
        original=self.source();original['coordinates']=(1.0,None,False)
        packed=c.encode(original);self.assertEqual(packed['format'],'gentactix-session-v2')
        restored=c.decode(json.loads(json.dumps(packed)))
        self.assertEqual(json.dumps(restored),json.dumps(original))
        self.assertIs(type(original['coordinates']),tuple)

    def test_malformed_json_reference_types_are_validation_errors(self):
        from backend import checkpoint_codec as c
        for kind in ('digest','path','part','last','size'):
            packed=c.encode(self.source());row=packed['definition_refs'][0]
            if kind=='digest':row['digest']=[]
            elif kind=='path':row['path']='not a path'
            elif kind=='part':row['path']=[False,'definition']
            elif kind=='last':row['path']=[[]]
            else:packed['expanded_bytes']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):c.decode(packed)

    def test_all45_frozen_catalogue_versions_retain_exact_ordered_data(self):
        from backend import checkpoint_codec as c
        from gentactix import historical_initial
        count=0;catalogue=historical_initial.catalog()
        for row in catalogue:
            for path in sorted((Path('data/historical_initial')/row['profile_id']).glob('*.json')):
                source=json.loads(path.read_text());world=dict(mission=dict(definition=source))
                original=dict(war_state=world,last_war_state=copy.deepcopy(world))
                with self.subTest(profile=row['profile_id'],version=path.stem):
                    restored=c.decode(json.loads(json.dumps(c.encode(original))))
                    self.assertEqual(json.dumps(restored),json.dumps(original));count+=1
        self.assertEqual(len(catalogue),45);self.assertGreaterEqual(count,57)

    def test_store_writes_compact_and_restores_complete_session_and_hashes(self):
        from backend import session_store,checkpoint_codec as c
        from gentactix import missions
        current=fixture_session();saved=copy.deepcopy(current)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            session_store.save(current);path=Path(folder)/(current['id']+'.json')
            document=json.loads(path.read_text());self.assertEqual(document['format'],'gentactix-session-v2')
            self.assertEqual(c.decode(document),session_store.serializable(current))
            restored,errors=session_store.load_all();self.assertFalse(errors)
            self.assertEqual(session_store.serializable(restored[current['id']]),session_store.serializable(current))
            self.assertEqual(missions.digest(restored[current['id']]['war_state']),missions.digest(current['war_state']))
        self.assertEqual(current,saved)

    def test_unchanged_legacy_checkpoint_is_not_reformatted_or_migrated(self):
        from backend import session_store
        current=fixture_session();current.pop('cancel_requested',None)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            path=Path(folder)/(current['id']+'.json')
            raw=json.dumps(dict(format='gentactix-session-v1',session=session_store.serializable(current)),ensure_ascii=False,indent=3)+'\n'
            path.write_text(raw);stamp=path.stat().st_mtime_ns
            restored,errors=session_store.load_all();self.assertFalse(errors)
            session_store.save(restored[current['id']])
            self.assertEqual(path.read_text(),raw);self.assertEqual(path.stat().st_mtime_ns,stamp)
            restored[current['id']]['history'].append('仅测试用户明确修改后的保存')
            session_store.save(restored[current['id']]);self.assertEqual(json.loads(path.read_text())['format'],'gentactix-session-v2')

    def test_unreadable_existing_checkpoint_is_preserved_on_save(self):
        from backend import session_store
        current=fixture_session()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            path=Path(folder)/(current['id']+'.json');path.write_text('original invalid data')
            with self.assertRaises(ValueError):session_store.save(current)
            self.assertEqual(path.read_text(),'original invalid data')

    def test_verified_unchanged_file_does_not_require_reexpanding_previous_state(self):
        from backend import session_store,checkpoint_codec as c
        current=fixture_session()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            session_store.save(current)
            with patch.object(c,'decode',side_effect=AssertionError('Do not re-expand an unchanged verified file')):
                session_store.save(current)
                current['history'].append('storage-only changed fixture')
                session_store.save(current)
            restored,errors=session_store.load_all();self.assertFalse(errors)
            self.assertEqual(restored[current['id']]['history'],current['history'])

    def test_external_file_change_invalidates_the_persistence_fingerprint(self):
        from backend import session_store
        current=fixture_session()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            session_store.save(current);path=Path(folder)/(current['id']+'.json');stamp=path.stat()
            bad=b'x'*stamp.st_size;path.write_bytes(bad)
            os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1000000))
            with self.assertRaises(ValueError):session_store.save(current)
            self.assertEqual(path.read_bytes(),bad)

    def test_failed_replace_keeps_previous_checkpoint_and_removes_temporary(self):
        from backend import session_store
        current=fixture_session()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            session_store.save(current);path=Path(folder)/(current['id']+'.json');raw=path.read_bytes()
            current['history'].append('changed')
            with patch('backend.session_store.os.replace',side_effect=OSError('fixture disk failure')):
                with self.assertRaises(OSError):session_store.save(current)
            self.assertEqual(path.read_bytes(),raw);self.assertFalse(path.with_suffix('.tmp').exists())

    def test_compact_document_uses_same_import_and_preview_validator(self):
        from backend import checkpoint_codec as c,main
        from fastapi.testclient import TestClient
        current=fixture_session();document=c.encode(main.session_store.serializable(current))
        self.assertEqual(main._prepare_import(document)['war_state'],current['war_state'])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}),patch.dict(main._SESSIONS,{},clear=True):
            response=TestClient(main.app).post('/api/sessions/import/preview',json=dict(document_json=json.dumps(document)))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['unit_count'],22)
            self.assertFalse(main._SESSIONS);self.assertFalse(list(Path(folder).iterdir()))

    def test_default_export_remains_expanded_and_compact_option_is_complete(self):
        from backend import checkpoint_codec as c,main
        from fastapi.testclient import TestClient
        current=fixture_session();before=copy.deepcopy(current)
        with patch.dict(main._SESSIONS,{current['id']:current},clear=True):
            client=TestClient(main.app);base='/api/sessions/'+current['id']+'/export'
            expanded=client.get(base);compact=client.get(base+'?compact=true')
            self.assertEqual(expanded.status_code,200);self.assertEqual(compact.status_code,200)
            self.assertEqual(expanded.json()['format'],'gentactix-session-v1')
            self.assertEqual(compact.json()['format'],'gentactix-session-v2')
            self.assertEqual(c.decode(compact.json()),expanded.json()['session'])
            self.assertLess(len(compact.content),len(expanded.content))
            self.assertEqual(current,before)


if __name__=='__main__':unittest.main()
