"""Deterministic multi-category privacy recovery. Only memory + targets enter.

No file/model/network/environment access in recover(). Gold is evaluator-only.
Sharing is an explicit hypothetical visibility relation, never inferred.
"""
import argparse
import copy
import itertools
import json
import re
from pathlib import Path

from .inference import VERSION, answer as infer_answer, build_knowledge
from .inference import UNVERIFIED
from .relational_memory import VERSION as MEMORY_VERSION, context_for, normalize_memory

SCHEMA = 'privacy.recovery.memory.v1'
ALIASES = {
    'email_address': {'email', 'recipients', 'cc', 'bcc', 'participants'},
    'phone_number': {'phone', 'phone_number'}, 'password': {'password', 'new_password'},
    'legal_name': {'name', 'first_name', 'last_name', 'traveler'},
    'postal_address': {'street', 'city', 'address'},
    'account_number': {'iban', 'recipient', 'account_number'},
    'financial_amount': {'amount'}, 'financial_balance': {'balance'},
    'travel_destination': {'destination', 'arrival_city', 'departure_city', 'city', 'hotel'},
    'travel_dates': {'dates', 'start_day', 'end_day'},
    'calendar_schedule': {'date', 'start_time', 'end_time', 'new_start_time', 'new_end_time'},
    'event_location': {'location'}, 'event_participants': {'participants'},
    'meeting_topic': {'title'}, 'file_metadata': {'filename', 'file_id'},
    'website_visit': {'url'}, 'query_intent': {'query'},
    'message_content': {'body', 'content', 'message'},
    'communication_metadata': {'recipients', 'recipient', 'cc', 'bcc', 'subject'},
    'channel_membership': {'channel'}, 'access_permissions': {'permission'},
    'dietary_preferences': {'cuisine', 'cuisine_type', 'dietary_restrictions'},
}


def validate(memory, targets):
    if set(memory) != {'schema', 'receivers', 'sharing_groups'} or memory['schema'] != SCHEMA:
        raise ValueError('Input must be receiver memory only, without task/gold/audit fields')
    receivers = set()
    fact_ids = set()
    for r in memory['receivers']:
        if set(r) != {'receiver_id', 'facts'} or r['receiver_id'] in receivers:
            raise ValueError('Invalid or duplicate receiver')
        receivers.add(r['receiver_id'])
        for f in r['facts']:
            if set(f) - {'fact_id', 'field', 'value', 'event_id', 'parameter_path', 'subject', 'status',
                         'tool', 'observed_at', 'state', 'context', 'evidence_fact_ids',
                         'extraction_method', 'binding_method', 'text'}:
                raise ValueError('Unexpected memory data; no source/gold/context passthrough')
            if not {'fact_id', 'field', 'value'} <= set(f) or f['fact_id'] in fact_ids:
                raise ValueError('Missing or duplicate fact')
            fact_ids.add(f['fact_id'])
            if f.get('state') not in {None, 'before', 'after'}:
                raise ValueError('Unknown privacy fact state')
            if 'context' in f and not isinstance(f['context'], dict):
                raise ValueError('Fact context must be an object')
        local_ids = {f['fact_id'] for f in r['facts']}
        for f in r['facts']:
            if 'evidence_fact_ids' in f:
                support = f['evidence_fact_ids']
                if not isinstance(support, list) or not support or not all(isinstance(fid, str) for fid in support):
                    raise ValueError('Relation evidence must name local source facts')
                if f.get('extraction_method') != MEMORY_VERSION and not set(support) <= local_ids:
                    raise ValueError('Stored relation evidence crosses receiver boundary')
    for group in memory['sharing_groups']:
        if set(group) != {'group_id', 'members', 'enabled'} or not set(group['members']) <= receivers:
            raise ValueError('Invalid explicit sharing group')
    seen = set()
    for t in targets:
        if set(t) - {'probe_id', 'receiver_id', 'field', 'subject', 'state'}:
            raise ValueError('Targets may name a field/subject, never an answer or extraction hint')
        if not {'probe_id', 'receiver_id', 'field'} <= set(t) or t['probe_id'] in seen:
            raise ValueError('Invalid target')
        if t['receiver_id'] not in receivers:
            raise ValueError('Target receiver is absent')
        seen.add(t['probe_id'])
        if t.get('state') not in {None, 'before', 'after'}:
            raise ValueError('Unknown question state')


def candidates(fact, field):
    value = fact['value']
    if value is None or value == '':
        return []
    if fact.get('status') in UNVERIFIED:
        return []
    if fact['field'] == field:
        if field == 'packing_items':
            return [value]
        return value if isinstance(value, list) else [value]
    key = fact.get('parameter_path', '').split('/')[-1]
    # List paths such as /recipients/0 retain their semantic parent key.
    parts = fact.get('parameter_path', '').strip('/').split('/')
    if key.isdigit() and len(parts) > 1:
        key = parts[-2]
    if fact['field'] == 'request_parameter' and key in ALIASES.get(field, set()):
        if field == 'account_number' and not (isinstance(value, str) and re.fullmatch(r'[A-Z]{2}\d[A-Z0-9]{10,}', value)):
            return []
        return value if isinstance(value, list) else [value]
    if not isinstance(value, str):
        return []
    patterns = {
        'email_address': r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',
        'account_number': r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b',
        'password_reset_token': r'https?://[^\s<>"\]]*(?:reset|token)[^\s<>"\]]+',
        'password_reset_url': r'https?://[^\s<>"\]]*(?:reset|token)[^\s<>"\]]+',
        'security_code': r'(?i)(?:security code|verification code|验证码)\s*(?:is|:|：)?\s*(\d{4,8})',
        'calendar_schedule': r'\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b',
        'website_visit': r'(?:https?://|www\.)[^\s<>"\]]+',
    }
    if field in patterns:
        return re.findall(patterns[field], value)
    if field == 'travel_itinerary':
        m = re.search(r'^Trip:\s*([^,\n]+),\s*([^\n()]+?)\s*\(([^\n()]+)\)\s*$', value, re.M)
        if m:
            return [{'traveler': m[3].strip(), 'destination': m[1].strip(), 'dates': m[2].strip()}]
    if field == 'personal_interests':
        return re.findall(r'(?i)(?:favorite hobby(?: is|:)|hobby is)\s+([^.!\n]+)', value)
    return []


def recover(memory, targets, *, public_records=None):
    """One deterministic candidate per target, with explicit cross-receiver proof."""
    validate(memory, targets)
    memory = normalize_memory(memory)
    validate(memory, targets)
    by_receiver = {r['receiver_id']: r['facts'] for r in memory['receivers']}
    outputs = []
    knowledge_cache = {}
    for target in targets:
        rid = target['receiver_id']
        visible = {rid}
        # Explicit groups are shared views, not transitive re-sharing permissions.
        for group in memory['sharing_groups']:
            if group['enabled'] and rid in group['members']:
                visible.update(group['members'])
        records = [(owner, f) for owner in sorted(visible) for f in by_receiver[owner]]
        records.sort(key=lambda pair: (pair[1].get('event_id', ''), pair[1]['fact_id'], pair[0]))
        scope = tuple(sorted(visible))
        if scope not in knowledge_cache:
            knowledge_cache[scope] = build_knowledge(records, public_records)
        answer, proof, method = None, [], 'abstain'
        # Typed exact matches outrank parsing unclassified text.
        for typed in (True, False):
            for owner, fact in records:
                if (fact['field'] == target['field']) != typed:
                    continue
                if target.get('subject') and fact.get('subject') != target['subject']:
                    continue
                if target.get('state') and context_for(fact).get('state') != target['state']:
                    continue
                # A structured relation's object is interpreted by the rule
                # engine; a matching subject is not permission to regex-scan
                # unrelated contents for the requested person's attributes.
                if target.get('subject') and fact['field'] == 'relation':
                    continue
                if target.get('subject') and fact['field'] != target['field'] and fact['field'] != 'request_parameter':
                    # A person's password/document may contain an email-like
                    # string; that does not establish mailbox ownership.
                    continue
                values = candidates(fact, target['field'])
                if values:
                    answer = copy.deepcopy(values[0])
                    proof = [{'receiver_id': owner, 'fact_id': fact['fact_id']}]
                    method = 'typed_received_fact' if typed else 'declared_parameter_or_text_rule'
                    break
            if answer is not None:
                break
        if answer is None and not target.get('state') and target['field'] == 'travel_itinerary':
            groups = {}
            for owner, fact in records:
                if fact.get('subject') and fact['field'] in {'legal_name', 'travel_destination', 'travel_dates'}:
                    groups.setdefault(fact['subject'], {}).setdefault(fact['field'], []).append((owner, fact))
            for subject, slots in sorted(groups.items()):
                if target.get('subject') and target['subject'] != subject:
                    continue
                required = ('legal_name', 'travel_destination', 'travel_dates')
                # Conflicting or ambiguous premises must not be cherry-picked.
                if all(len(slots.get(k, [])) == 1 for k in required):
                    chosen = [slots[k][0] for k in required]
                    answer = dict(zip(('traveler', 'destination', 'dates'), [f['value'] for _, f in chosen]))
                    proof = [{'receiver_id': owner, 'fact_id': f['fact_id']} for owner, f in chosen]
                    method = 'AND_shared_explicit_subject'
                    break
        if answer is None and not target.get('state') and target['field'] == 'packing_items':
            collections = {}
            for owner, fact in records:
                if fact['field'] == 'packing_item' and fact.get('subject'):
                    if target.get('subject') and target['subject'] != fact['subject']:
                        continue
                    collections.setdefault(fact['subject'], []).append((owner, fact))
            if collections:
                chosen = collections[sorted(collections)[0]]
                answer = list(dict.fromkeys(f['value'] for _, f in chosen))
                proof = [{'receiver_id': owner, 'fact_id': f['fact_id']} for owner, f in chosen]
                method = 'same_explicit_list_subject'
        inference = infer_answer(knowledge_cache[scope], target)
        details = {}
        # Old unscoped scalar probes ask for ANY valid value. A relational
        # answer about another entity must not silently replace that top-1.
        # Subject-scoped questions, missing answers and composite outputs can
        # instead select the proved result directly.
        prefer_inference = answer is None or bool(target.get('subject')) or target['field'] in {
            'project_participation', 'travel_itinerary', 'financial_transaction'}
        if inference and inference.get('conflict') and prefer_inference:
            answer, proof, method = None, [], 'conflicting_relational_evidence'
            details = {'inference_status': 'conflicting_evidence', **inference}
        elif inference and not inference.get('conflict') and prefer_inference:
            answer, proof = inference['value'], inference['evidence']
            method = 'deterministic_rule_inference' if inference['proof'] else 'explicit_received_relation'
            details = {k: v for k, v in inference.items() if k not in {'value', 'evidence'}}
            details['inference_status'] = 'proved'
        elif inference and not inference.get('conflict'):
            details = {'additional_inference': inference, 'inference_status': 'available_not_selected'}
        outputs.append({**target, 'top1_guess': answer,
                        'possible_disclosed_privacy': answer,
                        'status': 'one_candidate' if answer is not None else 'abstain',
                        'method': method, 'evidence': proof,
                        'shared_knowledge_used': any(e['receiver_id'] != rid for e in proof),
                        'visible_receiver_ids': sorted(visible), 'recovery_version': VERSION,
                        'memory_version': MEMORY_VERSION, **details})
    return outputs


def memory_from_graph(graph, shared=False):
    """Allowlist active semantic content; never traverse audit/absorbed records."""
    nodes = {n['id']: n for n in graph['nodes']}
    receivers = {n['receiver_id']: {'receiver_id': n['receiver_id'], 'facts': []}
                 for n in nodes.values() if n['type'] == 'business_receiver'}
    outgoing = {}
    for e in graph['edges']:
        outgoing.setdefault(e['source'], []).append(e)
    # Read only request identity/tool/time metadata. Raw request parameters,
    # task prompts, tool responses and absorbed audit records remain excluded.
    request_metadata = {(n.get('receiver_id'), n.get('disclosure_id')): n
                        for n in nodes.values() if n['type'] == 'actual_disclosure'}
    def add(node, field, value, **extra):
        rid = node.get('receiver_id')
        if rid in receivers:
            receivers[rid]['facts'].append({'fact_id': node['id'] + ':' + field,
                'field': field, 'value': copy.deepcopy(value),
                **({'status': 'model_extracted_unreviewed'} if node['type'] == 'graphiti_entity' else {}), **extra})
    for n in nodes.values():
        if n['type'] in {'graphiti_entity', 'disclosed_atom', 'normalized_received_fact', 'representative_object'}:
            labels = [nodes[e['target']]['field'] for e in outgoing.get(n['id'], []) if e['kind'] == 'direct_label']
            for field in dict.fromkeys(labels):
                add(n, field, n['label'])
            if n['type'] == 'disclosed_atom':
                a = n['annotation']
                if a['kind'] == 'direct' and a['field'] != 'none' and a['field'] not in labels:
                    add(n, a['field'], n['label'])
            if n['type'] == 'normalized_received_fact' and n['claim']['predicate'] == 'packing.item':
                add(n, 'packing_item', n['claim']['object'], subject=n['claim']['subject'])
            elif n['type'] == 'normalized_received_fact' and n.get('extraction_method') == 'packing_list_template_v1':
                add(n, 'relation', n['claim'])
            elif n['type'] == 'normalized_received_fact' and n['extraction_method'] == 'exact_parameter':
                metadata = request_metadata.get((n.get('receiver_id'), n.get('receipt_id')), {})
                tool = n.get('tool') or metadata.get('label')
                observed_at = n.get('observed_at') or metadata.get('time')
                add(n, 'request_parameter', n['claim']['object'],
                    event_id=n.get('receipt_id', '').split('::')[-1],
                    parameter_path=n['evidence']['parameter_pointer'], subject=n['claim']['subject'],
                    **({'tool': tool} if tool else {}),
                    **({'observed_at': observed_at} if observed_at else {}))
            elif n['type'] == 'representative_object':
                add(n, 'packing_items', n['members'])
            elif not labels:
                add(n, 'unclassified_text', n['label'])
        elif n['type'] == 'composite_privacy_fact':
            values = n['values']
            if all(k in values for k in ('travel.traveler', 'travel.destination', 'travel.period')):
                add(n, 'travel_itinerary', {'traveler': values['travel.traveler'],
                    'destination': values['travel.destination'], 'dates': values['travel.period']})
    return normalize_memory({'schema': SCHEMA, 'receivers': list(receivers.values()),
            'sharing_groups': [{'group_id': 'explicit_hypothetical_all_services',
                                'members': sorted(receivers), 'enabled': shared and len(receivers) > 1}]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory', type=Path, required=True)
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    predictions = recover(json.loads(args.memory.read_bytes()), json.loads(args.targets.read_bytes()))
    args.output.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
