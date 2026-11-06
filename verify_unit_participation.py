"""One physical entity across withdrawal, rear waiting and return; no free reset."""
import copy
import json
import unittest

from gentactix import commands, missions, sim_clock
from tools.qa.campaign_lifecycle_fixture import session


def physical(before, name=None, point=None):
    after=copy.deepcopy(before)
    after['mission']['turn']+=1
    after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟')
    if name and point:
        next(u for _,u in missions.units(after) if u['name']==name).update(point)
    return after


def order(name, point, kind='withdraw', request_id='a'*32):
    return dict(unit=name,action='move',**point,participation=dict(
        version='unit-participation-request-1',id=request_id,kind=kind,destination=point))


class UnitParticipationTests(unittest.TestCase):
    def module(self):
        from gentactix import unit_participation
        return unit_participation

    def test_no_request_preserves_legacy_world_without_a_new_registry(self):
        p=self.module();w=session()['war_state'];a=physical(w);saved=copy.deepcopy(a)
        p.advance(w,a,[],1800,source='dsh_model_estimate')
        self.assertEqual(a,saved);self.assertNotIn('unit_participation',a)

    def test_withdrawal_arrives_once_and_changes_no_resource_or_identity(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];point=dict(lat=u['lat']+.002,lng=u['lng'])
        a=physical(w,u['name'],point);saved=copy.deepcopy(a);before=copy.deepcopy(w)
        raw=order(u['name'],point);p.advance(w,a,[raw],1800,source='dsh_model_estimate')
        row=p.unit_view(a,a['red_units'][1],'red')
        self.assertEqual(row['status'],'reserve');self.assertEqual(row['transition_count'],1)
        self.assertTrue(row['targetable']);self.assertFalse(row['controls_objectives'])
        self.assertEqual({k:v for k,v in a.items() if k!='unit_participation'},saved)
        self.assertEqual(w,before)
        p.advance(w,a,[raw],1800,source='dsh_model_estimate')
        self.assertEqual(p.unit_view(a,a['red_units'][1],'red')['transition_count'],1)

    def test_partial_motion_stays_targetable_and_not_yet_in_reserve(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];target=dict(lat=u['lat']+.01,lng=u['lng'])
        a=physical(w,u['name'],dict(lat=u['lat']+.001,lng=u['lng']))
        p.advance(w,a,[order(u['name'],target)],1800,source='dsh_model_estimate')
        row=p.unit_view(a,a['red_units'][1],'red')
        self.assertEqual(row['status'],'withdrawing');self.assertTrue(row['targetable'])
        self.assertIsNotNone(row['pending'])

    def test_command_replacement_cancels_only_intent_and_keeps_actual_position(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];target=dict(lat=u['lat']+.01,lng=u['lng'])
        a=physical(w,u['name'],dict(lat=u['lat']+.001,lng=u['lng']))
        p.advance(w,a,[order(u['name'],target)],1800,source='dsh_model_estimate')
        b=physical(a);p.advance(a,b,[dict(unit=u['name'],action='hold')],1800,source='dsh_model_estimate')
        row=p.unit_view(b,b['red_units'][1],'red')
        self.assertEqual(row['status'],'deployed');self.assertIsNone(row['pending'])
        self.assertEqual(b['red_units'][1],a['red_units'][1])

    def test_reserve_wait_and_return_keep_damage_stocks_and_registered_entity(self):
        from tools.qa.campaign_lifecycle_fixture import inputs
        from gentactix import historical_operations
        source,parameters=inputs();parameters['actors']['ww2.cn.division159']['equipment']['transport']=20
        p=self.module();w=historical_operations.initial(source,parameters)
        u=next(u for u in w['red_units'] if u['historical_unit_id']=='ww2.cn.division159');index=w['red_units'].index(u)
        u['personnel'].update(current=280,casualties=20)
        gear=next(e for e in u['equipment'] if e['category']=='transport');gear.update(operational=19,damaged=1)
        self.assertEqual(gear['committed'],gear['operational']+gear['damaged']+gear['destroyed'])
        point=dict(lat=u['lat']+.002,lng=u['lng']);a=physical(w,u['name'],point)
        p.advance(w,a,[order(u['name'],point)],1800,source='dsh_model_estimate')
        entity=p.unit_view(a,a['red_units'][index],'red')['entity_id']
        for _ in range(12):
            b=physical(a);b['red_units'][index]['logistics']['food']-=2
            p.advance(a,b,[dict(unit=u['name'],action='hold')],1800,source='dsh_model_estimate');a=b
        back=dict(lat=u['lat'],lng=u['lng']);b=physical(a,u['name'],back)
        p.advance(a,b,[order(u['name'],back,'reenter','b'*32)],1800,source='dsh_model_estimate')
        row=p.unit_view(b,b['red_units'][index],'red')
        self.assertEqual(row['status'],'deployed');self.assertEqual(row['entity_id'],entity)
        self.assertEqual(b['red_units'][index]['personnel']['current'],280)
        self.assertEqual(b['red_units'][index]['logistics']['food'],u['logistics']['food']-24)
        self.assertEqual(b['red_units'][index]['equipment'],u['equipment'])
        self.assertEqual(len(b['unit_participation']['actors']),6)

    def test_invalid_request_and_fake_calendar_withdrawal_do_not_change_world(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];point=dict(lat=u['lat']+.002,lng=u['lng'])
        for kind in ('teleport','reenter'):
            a=physical(w,u['name'],point);saved=copy.deepcopy(a)
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                p.advance(w,a,[order(u['name'],point,kind)],1800,source='dsh_model_estimate')
            self.assertEqual(a,saved)
        raw=order(u['name'],point);raw['participation']['source_event']='WJL-Oct17-withdrawal'
        with self.assertRaises(ValueError):p.check_order(w,raw)

    def test_reserve_cannot_attack_but_can_be_attacked(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];point=dict(lat=u['lat']+.0002,lng=u['lng'])
        a=physical(w,u['name'],point);p.advance(w,a,[order(u['name'],point)],1800,source='dsh_model_estimate')
        with self.assertRaises(ValueError):p.check_order(a,dict(unit=u['name'],action='fire',target=a['blue_units'][0]['name']))
        p.check_order(a,dict(unit=a['blue_units'][0]['name'],action='fire',target=u['name']))

    def test_returning_is_targetable_but_cannot_attack_or_score_before_actual_arrival(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1]
        rear=dict(lat=u['lat']+.002,lng=u['lng']);a=physical(w,u['name'],rear)
        p.advance(w,a,[order(u['name'],rear)],1800,source='dsh_model_estimate')
        target=dict(lat=u['lat']-.01,lng=u['lng']);b=physical(a,u['name'],dict(lat=u['lat']+.001,lng=u['lng']))
        p.advance(a,b,[order(u['name'],target,'reenter','b'*32)],1800,source='dsh_model_estimate')
        row=p.unit_view(b,b['red_units'][1]);self.assertEqual(row['status'],'returning')
        self.assertTrue(row['targetable']);self.assertFalse(row['controls_objectives'])
        with self.assertRaises(ValueError):p.check_order(b,dict(unit=u['name'],action='fire',target=b['blue_units'][0]['name']))

    def test_state_tampering_and_identity_omission_are_rejected(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];point=dict(lat=u['lat']+.002,lng=u['lng'])
        a=physical(w,u['name'],point);p.advance(w,a,[order(u['name'],point)],1800,source='dsh_model_estimate')
        for mutation in ('status','omit','clock'):
            b=copy.deepcopy(a)
            if mutation=='status':next(iter(b['unit_participation']['actors'].values()))['status']='teleport'
            elif mutation=='omit':b['unit_participation']['actors'].pop(next(iter(b['unit_participation']['actors'])))
            else:b['unit_participation']['elapsed_seconds']=0
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):p.validate_state(b)
        p.validate_state(json.loads(json.dumps(a)))

    def test_native_undelivered_move_does_not_count_as_exit(self):
        p=self.module();w=session()['war_state'];u=w['red_units'][1];point=dict(lat=u['lat']+.002,lng=u['lng'])
        a=physical(w);a['red_units'][1]['formation']['last_execution']=dict(turn=1,command_done=0,action='未交付')
        p.advance(w,a,[order(u['name'],point)],1800,source='afsim_native')
        row=p.unit_view(a,a['red_units'][1],'red')
        self.assertEqual(row['status'],'deployed');self.assertIsNotNone(row['pending'])

    def test_queue_keeps_explicit_participation_directive_through_preparation(self):
        s=session();cs=commands.state(s);u=s['war_state']['red_units'][1]
        identity=next(r['id'] for r in cs['registry'] if r['name']==u['name'])
        point=dict(lat=u['lat']+.002,lng=u['lng'])
        cs=commands.replace_queue(s,[dict(unit_id=identity,action='move',destination=point,
            duration='until_arrived',participation='withdraw')],control_team='red',director=True,no_fire=False,intent='')
        s['command_state']=cs;prepared=commands.prepare(s)
        raw=next(x['order'] for x in prepared['manual'] if x['order']['unit']==u['name'])
        self.assertEqual(raw['participation']['kind'],'withdraw')
        self.assertEqual(raw['participation']['id'],cs['orders'][0]['id'])
        self.assertEqual(raw['participation']['destination'],point)
        commands.validate_saved(s)

    def test_public_directive_requires_move_until_arrived_and_rejects_without_mutation(self):
        s=session();identity=next(iter(commands.resolve_units(s)));saved=copy.deepcopy(s)
        for action,duration,kind in [('hold','next','withdraw'),('move','next','withdraw'),
                                     ('move','until_arrived','teleport')]:
            draft=dict(unit_id=identity,action=action,duration=duration,participation=kind,
                destination=dict(lat=29.3,lng=115.8))
            with self.subTest(draft=draft),self.assertRaises(ValueError):
                commands.replace_queue(s,[draft],control_team='red',director=True,no_fire=False,intent='')
            self.assertEqual(s,saved)

    def test_participation_uses_unclipped_goal_and_keeps_request_id_until_arrival(self):
        s=session();identity,(entry,u)=next(iter(commands.resolve_units(s).items()))
        point=dict(lat=u['lat']+.02,lng=u['lng']);draft=dict(unit_id=identity,action='move',
            duration='until_arrived',participation='withdraw',destination=point)
        cs=commands.replace_queue(s,[draft],control_team=entry['team'],director=True,no_fire=False,intent='')
        s['command_state']=cs;first=commands.prepare(s);second=commands.prepare(s)
        raw=first['manual'][0]['order']
        self.assertEqual(raw,second['manual'][0]['order'])
        self.assertEqual(raw['participation']['destination'],point)
        self.assertLess(commands.distance(u,raw),commands.distance(u,point))
        edited={k:v for k,v in cs['orders'][0].items() if k in commands.DRAFT_FIELDS}
        edited.pop('participation')
        replacement=commands.replace_queue(s,[edited],control_team=entry['team'],director=True,no_fire=False,intent='')
        self.assertNotEqual(replacement['orders'][0]['id'],cs['orders'][0]['id'])
        self.assertNotIn('participation',replacement['orders'][0])


if __name__=='__main__':unittest.main()
