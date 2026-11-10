"""Subject-specific questions cannot borrow another subject's answer."""
import copy
import json
import unittest

from p0_privacy.background_recovery import BackgroundRecovery
from p0_privacy.catalog import CATEGORIES
from p0_privacy.public_background import DEFAULT_OUTPUT
from p0_privacy.recovery import SCHEMA, recover
from p0_privacy.scoped_recovery import questions, score_answers


def memory(facts):
    return {'schema': SCHEMA, 'receivers': [{'receiver_id': 'a', 'facts': facts}], 'sharing_groups': []}


def target(field, subject):
    return [{'probe_id': 'p0', 'receiver_id': 'a', 'field': field, 'subject': subject}]


def task_for(field):
    category = next(key for key, value in CATEGORIES.items() if field in value['direct'].values())
    return {'category_ids': [category]}


class ScopedRecoveryTests(unittest.TestCase):
    def test_questions_have_exact_people_and_independent_references(self):
        env = {'inbox': {'contact_list': [{'name': 'Alice', 'email': 'alice@example.org'},
                                          {'name': 'Bob', 'email': 'bob@example.org'}]}}
        qs = questions(task_for('email_address'), env)
        alice = next(q for q in qs if q['subject'] == 'Alice')
        self.assertIn('Alice', alice['question'])
        self.assertEqual(alice['references'][0]['value'], 'alice@example.org')
        prediction = {'question_id': alice['question_id'], 'field': 'email_address',
                      'subject': 'Alice', 'top1_guess': 'bob@example.org'}
        self.assertEqual(score_answers([prediction], qs)[0]['top1_recovery'], 0)
        prediction['top1_guess'] = 'alice@example.org'
        self.assertEqual(score_answers([prediction], qs)[0]['top1_recovery'], 1)
        prediction['subject'] = 'Bob'
        with self.assertRaises(ValueError):
            score_answers([prediction], qs)

    def test_calendar_question_keeps_event_identity_and_start_end_distinct(self):
        env = {'calendar': {'initial_events': [
            {'id_': '7', 'start_time': '2026-11-07T09:00:00', 'end_time': '2026-11-07T10:00:00'},
            {'id_': '8', 'start_time': '2026-11-08T11:00:00', 'end_time': '2026-11-08T12:00:00'}]}}
        original = copy.deepcopy(env)
        qs = questions(task_for('calendar_schedule'), env)
        q = next(q for q in qs if q['subject'] == 'calendar:event:7' and q['field'] == 'calendar_start_time')
        self.assertIn('#7', q['question'])
        self.assertEqual(len([q for q in qs if q['field'].startswith('calendar_')]), 4)
        guess = {'question_id': q['question_id'], 'field': q['field'], 'subject': q['subject'],
                 'top1_guess': '2026-11-07 10:00:00'}
        self.assertEqual(score_answers([guess], qs)[0]['top1_recovery'], 0)
        guess['top1_guess'] = '2026-11-07 09:00:00'
        self.assertEqual(score_answers([guess], qs)[0]['top1_recovery'], 1)
        self.assertEqual(env, original)

    def test_unknown_person_abstains_instead_of_using_public_contact_guess(self):
        engine = BackgroundRecovery(json.loads(DEFAULT_OUTPUT.read_bytes()))
        self.assertIsNone(engine.recover(memory([]), target('email_address', 'Alice'))[0]['top1_guess'])

    def test_bare_email_in_a_message_does_not_identify_its_owner(self):
        facts = [{'fact_id': 'text', 'field': 'message_content', 'value': 'Alice, Bob, bob@example.org'}]
        self.assertIsNone(recover(memory(facts), target('email_address', 'Alice'))[0]['top1_guess'])
        facts[0]['value'] = "Alice's email is alice@example.org."
        self.assertEqual(recover(memory(facts), target('email_address', 'Alice'))[0]['top1_guess'], 'alice@example.org')
        self.assertIsNone(recover(memory(facts), target('email_address', 'Bob'))[0]['top1_guess'])

    def test_event_reference_is_not_a_file_or_another_request_reference(self):
        facts = [{'fact_id': 'event', 'field': 'request_parameter', 'subject': 'request:1',
                  'parameter_path': '/event_id', 'value': '7'},
                 {'fact_id': 'start', 'field': 'request_parameter', 'subject': 'request:1',
                  'parameter_path': '/start_time', 'value': '2026-11-07 09:00:00'}]
        q = target('calendar_start_time', 'calendar:event:7')
        self.assertEqual(recover(memory(facts), q)[0]['top1_guess'], '2026-11-07 09:00:00')
        self.assertIsNone(recover(memory(facts), target('calendar_start_time', 'calendar:event:8'))[0]['top1_guess'])
        facts[0]['parameter_path'] = '/file_id'
        self.assertIsNone(recover(memory(facts), q)[0]['top1_guess'])
        facts[0]['parameter_path'] = '/event_id'
        facts[1]['subject'] = 'request:2'
        self.assertIsNone(recover(memory(facts), q)[0]['top1_guess'])

    def test_labelled_hobby_table_binds_each_person(self):
        facts = [{'fact_id': 'text', 'field': 'message_content',
                  'value': 'Employee Hobbies\n\n- Alice: painting\n- Bob: hiking'}]
        self.assertEqual(recover(memory(facts), target('personal_interests', 'Alice'))[0]['top1_guess'], 'painting')
        self.assertEqual(recover(memory(facts), target('personal_interests', 'Bob'))[0]['top1_guess'], 'hiking')

    def test_two_trips_for_one_person_have_separate_questions_and_references(self):
        category = next(k for k, v in CATEGORIES.items() if any(j[0] == 'travel_itinerary' for j in v['joint']))
        env = {'cloud_drive': {'initial_files': [
            {'id_': '7', 'content': "Emma Johnson's Vacation Itinerary\nDestination: Hawaii\nDates: June 2024"},
            {'id_': '22', 'content': "Emma Johnson's Vacation Itinerary\nDestination: Europe\nDates: June 2025"}]}}
        qs = [q for q in questions({'category_ids': [category]}, env) if q['field'] == 'travel_itinerary']
        self.assertEqual({q['subject'] for q in qs}, {'drive:file:7', 'drive:file:22'})
        first = next(q for q in qs if q['subject'] == 'drive:file:7')
        second = next(q for q in qs if q['subject'] == 'drive:file:22')
        self.assertIn('#7', first['question'])
        self.assertEqual(score_answers([{'question_id': first['question_id'], 'field': first['field'],
            'subject': first['subject'], 'top1_guess': second['references'][0]['value']}], qs)[0]['top1_recovery'], 0)

    def test_conflicting_typed_scoped_fact_abstains(self):
        facts = [{'fact_id': 'first', 'field': 'travel_destination', 'subject': 'trip:1', 'value': 'Paris'},
                 {'fact_id': 'second', 'field': 'travel_destination', 'subject': 'trip:1', 'value': 'Rome'}]
        row = recover(memory(facts), target('travel_destination', 'trip:1'))[0]
        self.assertIsNone(row['top1_guess'])
        self.assertEqual(row['inference_status'], 'conflicting_evidence')


if __name__ == '__main__':
    unittest.main()
