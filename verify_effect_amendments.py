"""Replay explicit model edits from public Native calls; never repair effects."""
import copy
import json
import subprocess
import unittest

from backend import effect_amendments as a, turn_preview as p
from tools.qa.turn_preview_page_fixture import session, candidate
from gentactix import missions


class EffectAmendmentsTests(unittest.TestCase):
    def setUp(self):
        self.s=session();self.ctx=p.context(self.s,None,operation_id='amend-qa')
        self.good=candidate(self.s['war_state']);self.events=[]

    def record(self,tool,args,reply):
        seq=len(self.events)+1;call='call'+str(seq)
        self.events += [dict(type='tool/call',seq=seq,data=dict(name=tool,callId=call,arguments=copy.deepcopy(args))),
            dict(type='tool/result',seq=seq+1,data=dict(message=dict(toolCallId=call,
                 content=[dict(type='text',text=json.dumps(reply))])))]

    def first(self):
        value=copy.deepcopy(self.good);value['unit_updates'][0]['team']='red'
        reply=p.execute(self.ctx,dict(tool=p.TOOL,args=dict(candidate=value)))
        self.assertFalse(reply['ok']);self.record(p.TOOL,dict(candidate=value),reply)
        return reply

    def amend(self,base,edits,**extras):
        args=dict(base_ref=base,edits=edits)
        reply=p.amend(self.ctx,dict(tool=a.AMEND_TOOL,args=args,session_id='qa-native',
            candidate_events=copy.deepcopy(self.events),**extras))
        self.record(a.AMEND_TOOL,args,reply)
        return reply

    def payload(self,tool,args):
        return dict(tool=tool,args=args,session_id='qa-native',preview_events=copy.deepcopy(self.events))

    def test_shape_failure_explicit_edit_equals_full_correct_candidate(self):
        saved=copy.deepcopy(self.ctx);first=self.first()
        reply=self.amend(first['candidate_ref'],[dict(op='remove',path='/unit_updates/0/team')])
        self.assertTrue(reply['ok'],reply)
        full=p.execute(self.ctx,dict(tool=p.TOOL,args=dict(candidate=self.good)))
        self.assertEqual(reply['digest'],full['digest']);self.assertEqual(reply['after_hash'],full['after_hash'])
        self.assertEqual(self.ctx,saved)

    def test_failed_amendment_can_be_amended_without_retransmitting_base(self):
        first=self.first()
        second=self.amend(first['candidate_ref'],[dict(op='replace',path='/unit_updates/0/logistics/food',value=-1)])
        self.assertFalse(second['ok']);self.assertNotEqual(second['candidate_ref'],first['candidate_ref'])
        final=self.amend(second['candidate_ref'],[dict(op='remove',path='/unit_updates/0/team'),
            dict(op='replace',path='/unit_updates/0/logistics/food',value=self.good['unit_updates'][0]['logistics']['food'])])
        self.assertTrue(final['ok'],final)
        reconstructed=a.source(self.ctx,dict(session_id='qa-native',candidate_events=self.events),final['candidate_ref'])
        self.assertEqual(reconstructed,self.good)

    def test_report_and_paging_replay_the_entire_chain(self):
        first=self.first();reply=self.amend(first['candidate_ref'],[dict(op='remove',path='/unit_updates/0/team')])
        self.assertTrue(reply['ok'],reply)
        page=p.get_preview(self.ctx,self.payload(p.READ_TOOL,dict(preview_hash=reply['digest'],offset=16)))
        self.assertTrue(page['ok'],page);self.assertEqual(len(page['items']),6)
        final=dict(preview_hash=reply['digest'],report='双方按命令待命，粮食依本轮时长消耗。')
        report=p.submit_report(self.ctx,self.payload(p.REPORT_TOOL,final))
        self.assertTrue(report['ok'],report);self.record(p.REPORT_TOOL,final,report)
        # Final observer contains other legitimate tools too; the replay reader filters them.
        from backend.extensions import event_summary
        from types import SimpleNamespace
        observer=SimpleNamespace(runs=[dict(events=[event_summary(e,'qa-native') for e in self.events])])
        value,proof=p.resolve(final,observer,self.ctx)
        self.assertEqual(value,{**self.good,'report':final['report']})
        self.assertEqual(proof['call_id'],'call3');self.assertEqual(proof['report_source'],'dsh_native_report_tool')

    def test_unchanged_values_still_have_distinct_call_bound_references(self):
        first=self.first();path='/unit_updates/0/status'
        one=self.amend(first['candidate_ref'],[dict(op='add',path=path,value='待命')])
        two=self.amend(one['candidate_ref'],[dict(op='replace',path=path,value='待命')])
        self.assertEqual(one['candidate_hash'],two['candidate_hash'])
        self.assertNotEqual(one['candidate_ref'],two['candidate_ref'])

    def test_missing_stale_or_changed_world_evidence_is_refused(self):
        first=self.first();saved=copy.deepcopy(self.ctx)
        args=dict(base_ref=first['candidate_ref'],edits=[dict(op='remove',path='/unit_updates/0/team')])
        for kind in ('missing','operation','world','unpaired','reversed','foreign-call'):
            ctx=copy.deepcopy(self.ctx);events=copy.deepcopy(self.events)
            if kind=='missing':events=[]
            elif kind=='operation':ctx['turn_preview']['operation_id']='different'
            elif kind=='world':ctx['session']['war_state']['red_units'][0]['hp']-=1
            elif kind=='unpaired':events=events[:-1]
            elif kind=='reversed':events.reverse()
            else:events[1]['data']['message']['toolCallId']='other'
            reply=p.amend(ctx,dict(tool=a.AMEND_TOOL,args=args,session_id='qa-native',candidate_events=events))
            self.assertFalse(reply['ok'],(kind,reply));self.assertNotIn('candidate_ref',reply)
        self.assertEqual(self.ctx,saved)

    def test_forged_candidate_or_reply_fingerprint_is_refused(self):
        first=self.first()
        for kind in ('candidate','hash'):
            events=copy.deepcopy(self.events)
            if kind=='candidate':events[0]['data']['arguments']['candidate']['orders'][0]['action']='move'
            else:
                reply=json.loads(events[1]['data']['message']['content'][0]['text']);reply['candidate_hash']='f'*64
                events[1]['data']['message']['content'][0]['text']=json.dumps(reply)
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                a.source(self.ctx,dict(session_id='qa-native',candidate_events=events),first['candidate_ref'])

    def test_only_explicit_effect_paths_and_canonical_array_indices_are_accepted(self):
        for path in ('','/war_state/hp','/report','/source_note','/orders/01','/orders/999','/orders/~2'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                a.edit(self.good,dict(base_ref='a'*64,edits=[dict(op='remove',path=path)]))
        value=a.edit(self.good,dict(base_ref='a'*64,edits=[dict(op='add',path='/unit_updates/0/status',value='机动'),
            dict(op='replace',path='/unit_updates/0/status',value='待命'),dict(op='remove',path='/unit_updates/0/status')]))
        self.assertEqual(value,self.good)

    def test_afsim_and_unit_only_contexts_cannot_amend(self):
        first=self.first()
        for kind in ('afsim','not-native','no-operation'):
            ctx=copy.deepcopy(self.ctx)
            if kind=='afsim':ctx['session']['execution_backend']='afsim'
            elif kind=='not-native':ctx['session']['agent_mode']='legacy'
            else:ctx.pop('turn_preview')
            reply=p.amend(ctx,dict(tool=a.AMEND_TOOL,args=dict(base_ref=first['candidate_ref'],
                edits=[dict(op='remove',path='/unit_updates/0/team')]),session_id='qa-native',candidate_events=self.events))
            self.assertFalse(reply['ok'],reply)

    def test_native_selector_supplies_only_the_linked_public_chain(self):
        first=self.first();reply=self.amend(first['candidate_ref'],[dict(op='remove',path='/unit_updates/0/team')])
        noisy=[dict(type='message',seq=0,data=dict(reasoning='must not cross bridge'))]+self.events
        script="import {candidateEvidence,previewEvidence} from './plugins/dsh-gentactix/report-evidence.mjs';let text='';for await(const c of process.stdin)text+=c;const v=JSON.parse(text);process.stdout.write(JSON.stringify([candidateEvidence(v.events,v.ref),previewEvidence(v.events,v.digest)]));"
        result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(dict(events=noisy,ref=reply['candidate_ref'],digest=reply['digest'])),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout);self.assertEqual(values,[self.events,self.events])

    def test_process_policy_exposes_amendments_only_to_main_native_effect_engine(self):
        from backend import harness_engine as h
        self.assertIn(a.AMEND_TOOL,h.role_policy('engine',tools=True,process=True)['allowed_tools'])
        for role,flags in [('engine',dict(unit=True,process=True)),('engine',dict(external=True,process=True)),
                           ('engine',{}),('chat',dict(process=True)),('strategist',dict(process=True))]:
            self.assertNotIn(a.AMEND_TOOL,h.role_policy(role,tools=True,**flags)['allowed_tools'])

    def test_json_roundtrip_and_noop_after_success_keep_exact_physical_digest(self):
        first=p.execute(self.ctx,dict(tool=p.TOOL,args=dict(candidate=self.good)))
        self.assertTrue(first['ok'],first);self.record(p.TOOL,dict(candidate=self.good),first)
        path='/unit_updates/0/logistics/food';food=self.good['unit_updates'][0]['logistics']['food']
        reply=self.amend(first['candidate_ref'],[dict(op='replace',path=path,value=float(food))])
        self.assertTrue(reply['ok'],reply);self.assertEqual(reply['digest'],first['digest'])
        events=json.loads(json.dumps(self.events));raw=a.source(self.ctx,dict(session_id='qa-native',candidate_events=events),reply['candidate_ref'])
        self.assertEqual(raw,self.good)


if __name__=='__main__':unittest.main()
