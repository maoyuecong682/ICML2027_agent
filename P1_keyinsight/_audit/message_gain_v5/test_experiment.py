import copy
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parents[2]/'P0_agentdojo'))
from run import make_memory, targets_for
from recoverer import recover_fixed, SPECIAL
from p0_privacy.recovery_supplement import load_jobs
import json


class MessageExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs=load_jobs()

    def case(self,key,eid,direction,include):
        j=self.jobs[key]
        trace=json.loads(j['environment_path'].with_name('graph.json').read_bytes())
        return make_memory(j['versions']['0'],trace,eid,direction,include)

    def result(self,memory,field,subject):
        rid=memory['receivers'][0]['receiver_id']
        return recover_fixed(memory,[{'probe_id':'p','field':field,'subject':subject,'receiver_id':rid}],{})[0]

    def assert_strict(self,key,eid,direction,field,subject):
        before,_=self.case(key,eid,direction,False)
        after,obs=self.case(key,eid,direction,True)
        assert all(o['event_id']<=eid for o in obs)
        rids=[r['receiver_id'] for r in after['receivers']]
        for arm in (before,after):
            for r in arm['receivers']:
                local={'schema':arm['schema'],'receivers':[r],'sharing_groups':[]}
                self.assertIsNone(self.result(local,field,subject)['top1_guess'])
            arm['sharing_groups']=[{'group_id':'g','members':rids,'enabled':True}]
        self.assertIsNone(self.result(before,field,subject)['top1_guess'])
        result=self.result(after,field,subject)
        self.assertIsNotNone(result['top1_guess'])
        self.assertGreaterEqual(len({x['receiver_id'] for x in result['evidence']}),2)

    def test_address_join_requires_new_update_and_both_services(self):
        self.assert_strict('banking/user_task_13','e0009','R','full_postal_address','Emma Johnson')

    def test_invitation_join_requires_new_web_return_and_both_services(self):
        self.assert_strict('slack/user_task_10','e0020','S','invitation_contact','Dora')

    def test_contact_activity_join_requires_new_calendar_return(self):
        self.assert_strict('travel/user_task_7','e0015','S','person_activity_contact','Emma Johnson')

    def test_one_message_only_and_no_same_event_return_for_request(self):
        a,oa=self.case('banking/user_task_14','e0011','R',False)
        b,ob=self.case('banking/user_task_14','e0011','R',True)
        self.assertEqual({o['message_id'] for o in ob}-{o['message_id'] for o in oa},{'e0011:R'})
        self.assertFalse(any(o['message_id']=='e0011:S' for o in ob))
        for ra,rb in zip(a['receivers'],b['receivers']):
            if ra['receiver_id']=='app:banking:bank':self.assertEqual(ra,rb)

    def test_without_response_does_not_remove_request_or_add_future_summary(self):
        a,oa=self.case('slack/user_task_18','e0013','S',False)
        b,ob=self.case('slack/user_task_18','e0013','S',True)
        self.assertIn('e0013:R',{o['message_id'] for o in oa})
        self.assertNotIn('e0013:S',{o['message_id'] for o in oa})
        self.assertTrue(all(o['event_id']<='e0013' for o in ob))
        self.assertFalse(any('summary of the article' in str(o['content']) for o in ob))

    def test_denied_sharing_cannot_infer_invitation_contact(self):
        memory,_=self.case('slack/user_task_10','e0020','S',True)
        memory['sharing_groups']=[{'group_id':'g','members':[r['receiver_id'] for r in memory['receivers']],'enabled':False}]
        self.assertIsNone(self.result(memory,'invitation_contact','Dora')['top1_guess'])

    def test_bank_profile_is_not_assumed_to_own_the_bank_transactions(self):
        memory,_=self.case('banking/user_task_8','e0005','S',True)
        memory['sharing_groups']=[{'group_id':'g','members':[r['receiver_id'] for r in memory['receivers']],'enabled':True}]
        self.assertIsNone(self.result(memory,'financial_transaction','Emma Johnson')['top1_guess'])


if __name__=='__main__':
    unittest.main()
