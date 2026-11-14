"""Bounded, deterministic relational reasoning over received evidence only.

No model, network, private environment, graph traversal or evaluator access.
Structured relations and a small documented positive sentence grammar become
claims. The same positive AND-rule closure runs for local and shared views.
"""
import copy
import re
from collections import defaultdict

from .knowledge_merge import closure, conflict_analysis, encoded, fact_id, minimal_supports
from .relational_memory import context_for, parameter_predicate

VERSION = 'deterministic-relations-v3'
UNVERIFIED = {'hypothesis', 'unverified_inference', 'model_extracted_unreviewed',
              'quote_verified_semantics_unreviewed', 'tool_error'}
ALIASES = {'travel.traveler': 'legal_name', 'travel.destination': 'travel_destination',
           'travel.period': 'travel_dates', 'person.email': 'email_address',
           'project.type': 'project_type', 'person.responsible_for': 'responsible_for',
           'person.hobby': 'personal_interests'}
SINGLE_VALUED = {'identity', 'project_type', 'legal_name', 'travel_destination', 'travel_dates',
                 'travel_itinerary', 'transaction.recipient', 'transaction.amount',
                 'transaction.subject', 'transaction.date', 'financial_transaction',
                 'event.start', 'event.end', 'event.location', 'calendar_start_time', 'calendar_end_time', 'booked_hotel',
                 'financial_amount', 'financial_balance', 'event_location', 'meeting_topic',
                 'document_content', 'file_metadata'}
PARAMETERS = {
    'hotel': 'booked_hotel', 'start_day': 'travel.start', 'end_day': 'travel.end',
    'start_time': 'event.start', 'end_time': 'event.end', 'location': 'event.location', 'participants': 'event.participant',
    'recipient': 'transaction.recipient', 'amount': 'transaction.amount',
    'subject': 'transaction.subject', 'date': 'transaction.date', 'title': 'meeting_topic',
    'filename': 'file_metadata', 'content': 'document_content',
}
RECORD_IDS = {'event_id': ('event_ref', 'calendar:event:'),
              'transaction_id': ('transaction_ref', 'bank:transaction:'), 'file_id': ('file_ref', 'drive:file:')}
NEGATION = re.compile(r'\b(?:if|unless|not|never|maybe|might|may|could|would|possibly|ignore|pretend|output|return|say)\b|如果|假设|可能|并非|不是|不负责|忽略|输出', re.I)
NAME = r'[A-Za-z][A-Za-z0-9_ -]{0,79}'
CODE = r'[A-Za-z][A-Za-z0-9_-]{0,59}'
PATTERNS = [
    (re.compile(fr'(?P<s>{NAME}) is responsible for (?:project )?(?P<o>{CODE})', re.I), 'responsible_for'),
    (re.compile(fr'(?:Project )?(?P<s>{CODE}) is (?:a|an) (?P<o>{NAME}) project', re.I), 'project_type'),
    (re.compile(fr'(?P<s>{CODE}) (?:identifies|refers to) (?P<o>{NAME})', re.I), 'identity'),
    (re.compile(r'(?P<s>[^\s，。；;：:]{1,40})负责\s*(?:项目\s*)?(?P<o>[A-Za-z][A-Za-z0-9_-]*)'), 'responsible_for'),
    (re.compile(r'(?:项目\s*)?(?P<s>[A-Za-z][A-Za-z0-9_-]*)\s*是\s*(?P<o>[^\s，。；;：:]{1,40})项目'), 'project_type'),
    (re.compile(r'(?P<s>[A-Za-z][A-Za-z0-9_-]*)\s*对应(?P<o>[^\s，。；;：:]{1,40})'), 'identity'),
]


def claim(subject, predicate, obj, context=None):
    return {'subject': subject, 'predicate': predicate, 'object': obj,
            'context': {} if context is None else context}


def rule(name, premises, conclusion):
    return {'rule_id': name, 'premises': premises, 'conclusion': conclusion}


def rules():
    def c(s, p, o):
        return claim(s, p, o, '?context')
    result = [
        rule('responsibility_and_project_type',
             [c('?person', 'responsible_for', '?project'), c('?project', 'project_type', '?kind')],
             c('?person', 'project_participation', {'person': '?person', 'project': '?project', 'project_type': '?kind'})),
        rule('identity_names_record', [c('?record', 'identity', '?person')], c('?record', 'legal_name', '?person')),
        rule('named_travel_components',
             [c('?trip', 'legal_name', '?person'), c('?trip', 'travel_destination', '?place'), c('?trip', 'travel_dates', '?dates')],
             c('?trip', 'travel_itinerary', {'traveler': '?person', 'destination': '?place', 'dates': '?dates'})),
        rule('traveler_scoped_itinerary',
             [c('?trip', 'legal_name', '?person'), c('?trip', 'travel_destination', '?place'), c('?trip', 'travel_dates', '?dates')],
             c('?person', 'travel_itinerary', {'traveler': '?person', 'destination': '?place', 'dates': '?dates'})),
        rule('transaction_components',
             [c('?tx', 'transaction.recipient', '?recipient'), c('?tx', 'transaction.amount', '?amount'),
              c('?tx', 'transaction.subject', '?description'), c('?tx', 'transaction.date', '?date')],
             c('?tx', 'financial_transaction', {'recipient': '?recipient', 'amount': '?amount', 'subject': '?description', 'date': '?date'})),
        rule('website_owner_and_interest',
             [c('?person', 'owns_website', '?site'), c('?site', 'personal_interests', '?hobby')],
             c('?person', 'personal_interests', '?hobby')),
        rule('event_participant_attends', [c('?event', 'event.participant', '?person')], c('?person', 'attends', '?event')),
        rule('event_participant_value', [c('?event', 'event.participant', '?person')], c('?event', 'event_participants', '?person')),
        rule('attendee_and_event_time', [c('?person', 'attends', '?event'), c('?event', 'event.start', '?time')],
             c('?person', 'calendar_schedule', '?time')),
        rule('attendee_and_event_location', [c('?person', 'attends', '?event'), c('?event', 'event.location', '?place')],
             c('?person', 'event_location', '?place')),
        # Public records need a received hotel anchor; public availability alone
        # never establishes a user's stay. This remains a destination clue.
        rule('received_hotel_and_public_city',
             [c('?request', 'booked_hotel', '?hotel'), claim('?hotel', 'public.hotel_city', '?city')],
             c('?request', 'travel_destination', '?city')),
    ]
    for source, target in [('event.start', 'calendar_start_time'), ('event.end', 'calendar_end_time'),
                           ('event.location', 'event_location'), ('transaction.amount', 'financial_amount')]:
        result.append(rule('record_property:' + target, [c('?record', source, '?value')], c('?record', target, '?value')))
    result.append(rule('named_record_identity', [c('?record', 'legal_name', '?person')], c('?record', 'identity', '?person')))
    result.append(rule('financial_recipient',
        [c('?record', 'transaction.recipient', '?recipient'), c('?record', 'transaction.amount', '?amount')],
        c('?record', 'account_number', '?recipient')))
    for reference, predicates in {
        'event_ref': ('event.start', 'event.end', 'event.location', 'event.participant', 'event_participants',
                      'calendar_start_time', 'calendar_end_time', 'event_location', 'meeting_topic'),
        'transaction_ref': ('transaction.recipient', 'transaction.amount', 'transaction.subject', 'transaction.date',
                            'financial_amount', 'account_number', 'financial_transaction'),
        'file_ref': ('file_metadata', 'document_content', 'travel_itinerary'),
    }.items():
        for predicate in predicates:
            result.append(rule('record_reference:' + predicate,
                [c('?request', reference, '?record'), c('?request', predicate, '?value')], c('?record', predicate, '?value')))
    for predicate in ('responsible_for', 'travel_destination', 'travel_dates', 'email_address',
                      'personal_interests', 'attends', 'owns_website', 'account_number',
                      'phone_number', 'postal_address', 'financial_amount', 'financial_balance',
                      'financial_transaction', 'calendar_schedule', 'event_location'):
        result.append(rule('identity_attribute:' + predicate,
                      [c('?record', 'identity', '?person'), c('?record', predicate, '?value')],
                      c('?person', predicate, '?value')))
    return result


def checked_relation(value):
    if not isinstance(value, dict) or set(value) - {'subject', 'predicate', 'object', 'context'}:
        raise ValueError('Relation must contain only subject, predicate, object and optional context')
    if not {'subject', 'predicate', 'object'} <= set(value):
        raise ValueError('Incomplete relation')
    if not all(isinstance(value[k], str) and value[k] and not value[k].startswith('?') for k in ('subject', 'predicate')):
        raise ValueError('Relation subject and predicate must be ground identifiers')
    if not isinstance(value.get('context', {}), dict):
        raise ValueError('Relation context must be an object')
    from .knowledge_merge import variables
    if variables(value):
        raise ValueError('Received relations cannot contain rule variables')
    return claim(value['subject'], ALIASES.get(value['predicate'], value['predicate']),
                 copy.deepcopy(value['object']), copy.deepcopy(value.get('context', {})))


def extracted(fact):
    """Return assertions and whether each is an explicit relational query value."""
    if fact.get('binding_method') == 'local_rule_closure':
        return []
    if fact.get('status') in UNVERIFIED:
        return []
    field, value, subject = fact['field'], fact['value'], fact.get('subject')
    context = context_for(fact)
    if field == 'relation':
        return [(checked_relation(value), True)]
    out = []
    if subject and field not in {'request_parameter', 'unclassified_text', 'message_content', 'tool_response'}:
        predicate = ALIASES.get(field, field)
        # Lists represent multiple assertions, not a guessed association.
        for item in value if isinstance(value, list) else [value]:
            if item is not None and item != '':
                out.append((claim(subject, predicate, item, context), True))
    if field == 'request_parameter' and subject:
        parts = fact.get('parameter_path', '').strip('/').split('/')
        key = parts[-2] if len(parts) > 1 and parts[-1].isdigit() else parts[-1]
        predicate = parameter_predicate(fact.get('tool'), key, PARAMETERS.get(key))
        if key in {'new_start_time', 'new_end_time'}:
            predicate = 'event.start' if key == 'new_start_time' else 'event.end'
        if predicate and value is not None and value != '':
            for item in value if isinstance(value, list) else [value]:
                out.append((claim(subject, predicate, item, context), False))
        if key in RECORD_IDS and isinstance(value, (str, int)):
            reference, prefix = RECORD_IDS[key]
            out.append((claim(subject, reference, prefix + str(value), context), False))
    # Whole affirmative sentences only; never infer a relation from cooccurrence.
    if isinstance(value, str) and field in {'request_parameter', 'unclassified_text', 'message_content',
                                           'tool_response', 'document_content'}:
        # A labelled table or explicit possessive sentence supplies a binding;
        # nearby names and addresses by themselves never supply one.
        if re.match(r'\A(?:Employee Hobbies|员工爱好)\s*\n', value, re.I):
            for line in value.splitlines()[1:]:
                match = re.fullmatch(r'\s*[-*]\s+([^:\n：]+)[:：]\s*([^\n]+?)\s*', line)
                if match:
                    out.append((claim(match[1].strip(), 'personal_interests', match[2].strip()), True))
        for line in value.splitlines():
            if NEGATION.search(line):
                continue
            email = re.fullmatch(fr"(?P<person>{NAME})(?:'s (?:email|e-mail)(?: address)? is| can be contacted at) (?P<email>[\w.+-]+@[\w.-]+\.[A-Za-z]{{2,}})\.?", line.strip(), re.I)
            if email:
                out.append((claim(email['person'].strip(), 'email_address', email['email']), True))
        for sentence in re.split(r'[\n。;；]+|(?<!\d)\.|\.(?!\d)', value):
            sentence = sentence.strip()
            if not sentence or NEGATION.search(sentence):
                continue
            for pattern, predicate in PATTERNS:
                match = pattern.fullmatch(sentence)
                if match:
                    out.append((claim(match['s'].strip(), predicate, match['o'].strip()), True))
                    break
    return out


def build_knowledge(records, public_records=None):
    initial, leaves, explicit = {}, {}, set()

    def add(value, support, owner, direct=False):
        cid = fact_id(value)
        node = initial.setdefault(cid, {'claim': value, 'occurrences': [], 'proofs': [], 'supports': []})
        node['supports'] = minimal_supports(node['supports'] + [frozenset(support)])
        for leaf in support:
            leaves[leaf] = owner
        if direct:
            explicit.add(cid)

    for owner, fact in records:
        for value, direct in extracted(fact):
            support = ['memory:' + fid for fid in fact.get('evidence_fact_ids', [fact['fact_id']])]
            add(value, support, owner, direct)
    for index, hotel in enumerate((public_records or {}).get('hotels', [])):
        if hotel.get('name') and hotel.get('city'):
            add(claim(hotel['name'], 'public.hotel_city', hotel['city']),
                [f'public:/public_records/hotels/{index}'], None)
    initial_supports = {cid: list(node['supports']) for cid, node in initial.items()}
    inferred = closure(initial, rules())
    conflicts, taint = conflict_analysis(inferred, SINGLE_VALUED)
    return {'claims': inferred, 'leaves': leaves, 'explicit': explicit,
            'conflicts': conflicts, 'taint': taint, 'initial_supports': initial_supports}


def answer(knowledge, target):
    candidates, rejected = [], []
    for cid, node in knowledge['claims'].items():
        value = node['claim']
        if value['predicate'] != target['field']:
            continue
        if target.get('subject') and value['subject'] != target['subject']:
            continue
        if target.get('state') and value['context'].get('state') != target['state']:
            continue
        if not node['proofs'] and cid not in knowledge['explicit']:
            continue
        # No exclusively public proof may become a private relationship.
        supports = [s for s in node['supports'] if any(knowledge['leaves'][f] is not None for f in s)]
        if not supports:
            continue
        if knowledge['taint'][cid]:
            rejected.append(cid)
            continue
        candidates.append((cid, node, supports))
    if not candidates:
        return {'conflict': True, 'conflicting_claim_ids': rejected} if rejected else None
    if target.get('subject') and not target.get('state') and target['field'] in SINGLE_VALUED:
        values = {encoded(node['claim']['object']) for _, node, _ in candidates}
        if len(values) > 1:
            return {'conflict': True, 'reason': 'question_needs_time_or_context',
                    'conflicting_claim_ids': [cid for cid, _, _ in candidates]}
    # One valid value per field, preserving P0's top-1 contract. Distinct
    # nonconflicting subjects/contexts are allowed; conflicting claims above
    # are rejected before this stable selection.
    cid, node, supports = min(candidates, key=lambda x: encoded(x[1]['claim']))
    owners = knowledge['leaves']
    chosen = min(supports, key=lambda s: (len({owners[f] for f in s if owners[f] is not None}), len(s), sorted(s)))
    received = sorted((owners[f], f.removeprefix('memory:')) for f in chosen if owners[f] is not None)
    public = sorted(f.removeprefix('public:') for f in chosen if owners[f] is None)
    receiver_sets = minimal_supports([frozenset(owners[f] for f in s if owners[f] is not None) for s in supports])
    # Return only rule applications that have a proof contained in the chosen
    # leaf set. Alternative proofs do not inflate the evidence used here.
    proof, visited = [], set()

    def visit(key):
        if key in visited:
            return
        visited.add(key)
        # A received assertion is a leaf even if reversible identity rules
        # can also re-derive it. Do not include circular, redundant proofs.
        if any(s <= chosen for s in knowledge['initial_supports'].get(key, [])):
            return
        current = knowledge['claims'][key]
        for application in current['proofs']:
            if all(any(s <= chosen for s in knowledge['claims'][p]['supports']) for p in application['premise_fact_ids']):
                for premise in application['premise_fact_ids']:
                    visit(premise)
                proof.append({**copy.deepcopy(application), 'conclusion': copy.deepcopy(current['claim'])})
                break

    visit(cid)
    return {'value': copy.deepcopy(node['claim']['object']), 'claim': copy.deepcopy(node['claim']),
            'evidence': [{'receiver_id': owner, 'fact_id': fid} for owner, fid in received],
            'public_evidence': public, 'proof': proof,
            'minimal_receiver_sets': [sorted(s) for s in receiver_sets],
            'requires_joint_evidence': all(len(s) > 1 for s in receiver_sets),
            'version': VERSION}
