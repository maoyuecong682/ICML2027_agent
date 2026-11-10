"""Deterministic public-background guesses, independent of evaluator answers.

Public record frequency is a deliberately simple candidate ranking, not an
estimated population prior. Background guesses never become received facts.
"""
import copy
import json
import re

from .public_background import validate_background
from .recovery import recover


class BackgroundRecovery:
    """Static background configuration; runtime inputs remain memory + targets."""

    def __init__(self, background):
        validate_background(background)
        self.background_sha256 = background['content_sha256']
        self.index = {}
        fields = background['privacy_definitions']['fields']
        services = {dependency for tools in background['tools_by_suite'].values()
                    for tool in tools for dependency in tool['service']['all_dependencies']}
        self.public_records = {'hotels': copy.deepcopy(background['public_records']['hotels'])} if (
            'hotels' in services and 'travel_destination' in fields) else {}

        def add(field, value, pointer):
            if field not in fields or value is None or value == '':
                return
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            candidate = self.index.setdefault(field, {}).setdefault(key, {
                'value': copy.deepcopy(value), 'public_sources': []})
            if pointer not in candidate['public_sources']:
                candidate['public_sources'].append(pointer)

        for domain, records in background['public_records'].items():
            # Tool service definitions decide which public services exist.
            if domain not in services:
                continue
            for i, record in enumerate(records):
                root = f'/public_records/{domain}/{i}'
                for key in ('city', 'arrival_city', 'departure_city'):
                    add('travel_destination', record.get(key), root + '/' + key)
                for key in ('departure_time', 'arrival_time'):
                    timestamp = record.get(key)
                    if timestamp:
                        add('travel_dates', timestamp.split('T')[0], root + '/' + key)
                        add('calendar_schedule', timestamp.replace('T', ' '), root + '/' + key)
                if record.get('address'):
                    add('event_location', record['address'], root + '/address')
                    add('postal_address', record['address'], root + '/address')
                add('dietary_preferences', record.get('cuisine_type'), root + '/cuisine_type')
                # Business contacts are guesses for a person's contact, not
                # claims that the user owns these publicly listed contacts.
                contact = record.get('contact_information', '')
                for email in re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', contact):
                    add('email_address', email, root + '/contact_information')
                match = re.search(r'Phone:\s*([^,;\n]+)', contact)
                if match:
                    add('phone_number', match[1].strip(), root + '/contact_information')
        self.index = {field: sorted(candidates.values(), key=lambda c: (
            -len(c['public_sources']), json.dumps(c['value'], ensure_ascii=False, sort_keys=True)))
            for field, candidates in self.index.items()}

    def recover(self, memory, targets):
        rows = recover(memory, targets, public_records=self.public_records)
        scoped = {target['probe_id'] for target in targets if target.get('subject')}
        for row in rows:
            row['public_background_sha256'] = self.background_sha256
            row['background_evidence'] = []
            row['basis'] = 'memory_supported' if row['top1_guess'] is not None else 'no_candidate'
            if row['top1_guess'] is not None:
                continue
            if row.get('inference_status') == 'conflicting_evidence':
                continue
            # An unbound public business contact/city cannot answer a question
            # about a particular person or event. A received binding may still
            # support a public-record join in recover() above.
            if row['probe_id'] in scoped:
                continue
            pool = self.index.get(row['field'], [])
            row['public_candidate_count'] = len(pool)
            if not pool:
                continue
            chosen = pool[0]
            row.update(top1_guess=copy.deepcopy(chosen['value']),
                       possible_disclosed_privacy=copy.deepcopy(chosen['value']),
                       status='one_candidate', method='public_record_frequency_guess',
                       basis='background_guess', background_evidence=copy.deepcopy(chosen['public_sources']))
        return rows
