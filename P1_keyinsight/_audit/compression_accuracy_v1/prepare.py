"""Prepare fixed real-message inputs and source-grounded privacy test cases."""
import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
P0 = ROOT / 'P0_agentdojo'
sys.path.insert(0, str(P0))
sys.path.insert(0, str(HERE.parent / 'message_gain_v5'))
from p0_privacy.recovery_supplement import load_jobs
from p0_privacy.scoped_recovery import questions
from p0_privacy.relational_memory import normalize_memory
from p0_privacy.inference import build_knowledge, extracted, UNVERIFIED
from p0_privacy.simplification import simplify_graph, SimplificationConfig
from p0_privacy.response_memory import parse_response
from p0_privacy.input_alignment import VERSION as ALIGNMENT_VERSION, STATE_DEFINITIONS
from p0_privacy.input_alignment import annotate_observations, subject_bindings
from recoverer import canonical

PRIVATE = {'legal_name', 'email_address', 'phone_number', 'postal_address', 'password',
           'security_code', 'password_reset_token', 'password_reset_url', 'account_number',
           'financial_amount', 'financial_balance', 'financial_transaction', 'personal_interests',
           'calendar_start_time', 'calendar_end_time', 'calendar_schedule', 'event_location',
           'event_participants', 'meeting_topic', 'travel_itinerary', 'travel_dates',
           'travel_destination', 'file_metadata', 'assigned_work', 'access_permissions',
           'communication_metadata', 'message.recipient', 'booked_hotel', 'travel.start', 'travel.end'}


def enc(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_bytes())


def target_key(field, subject, state=None):
    return enc([field, subject, state])


def grounded_cases(job, memory, observations):
    """Positive proofs from raw observations; negatives need absent source values.

    No compressed graph, detector prediction or model label is consulted.
    """
    normalized = normalize_memory(memory)
    by_key = {}
    source_ids = {f['fact_id']: f for r in memory['receivers'] for f in r['facts']}
    for r in normalized['receivers']:
        for f in r['facts']:
            if f.get('status') in UNVERIFIED:
                continue
            for claim, _ in extracted(f):
                field, subject, value = claim['predicate'], claim['subject'], claim['object']
                state = claim.get('context', {}).get('state')
                if field not in PRIVATE or len(enc(value)) > 550 or value in (None, '', []):
                    continue
                evidence = f.get('evidence_fact_ids', [f['fact_id']])
                if not set(evidence) <= set(source_ids):
                    continue
                k = target_key(field, subject, state)
                item = by_key.setdefault(k, {'field': field, 'subject': subject,
                    **({'state': state} if state else {}), 'risk': True, 'references': [],
                    'proofs': [], 'label_basis': 'explicit_typed_or_grounded_local_relationship'})
                if canonical(value) not in [canonical(v) for v in item['references']]:
                    item['references'].append(value)
                item['proofs'].append({'receiver_id': r['receiver_id'], 'fact_ids': evidence})
    # Cross-receiver consequences use source facts, never a graph-arm outcome.
    records = [(r['receiver_id'], f) for r in normalized['receivers'] for f in r['facts']]
    knowledge = build_knowledge(records)
    for cid, node in knowledge['claims'].items():
        c = node['claim']
        if knowledge['taint'][cid] or c['predicate'] not in PRIVATE or len(enc(c['object'])) > 550:
            continue
        proofs = [s for s in node['supports'] if all(f.removeprefix('memory:') in source_ids for f in s)]
        if not proofs:
            continue
        state = c.get('context', {}).get('state')
        k = target_key(c['predicate'], c['subject'], state)
        if k not in by_key:
            by_key[k] = {'field': c['predicate'], 'subject': c['subject'],
                **({'state': state} if state else {}), 'risk': True, 'references': [c['object']],
                'proofs': [{'fact_ids': sorted(f.removeprefix('memory:') for f in s)} for s in proofs],
                'label_basis': 'bounded_rule_proof_over_original_visible_evidence'}
    # Read all category-defined private records in evaluator only. A reference
    # absent from all visible raw messages cannot be recovered in this closed view.
    task = copy.deepcopy(job['task'])
    from p0_privacy.catalog import CATEGORIES
    task['category_ids'] = sorted(CATEGORIES)
    environment_questions = questions(task, load(job['environment_path']))
    visible = enc(observations).casefold()
    negatives = {}
    for q in environment_questions:
        if q['field'] not in PRIVATE:
            continue
        state = 'before' if q['question'].startswith('任务开始前') else None
        k = target_key(q['field'], q['subject'], state)
        values = [x['value'] for x in q['references']]
        def unseen(v):
            # Avoid short common values as negative evidence; JSON/date variants
            # must all be absent, and every scalar in an object must be absent.
            if isinstance(v, dict):
                return all(unseen(x) for x in v.values())
            if isinstance(v, list):
                return all(unseen(x) for x in v)
            text = str(v)
            return len(text) >= 6 and all(t.casefold() not in visible for t in
                {text, text.replace('T', ' '), enc(v).strip('"')})
        if k not in by_key and values and all(unseen(v) for v in values):
            negatives[k] = {'field': q['field'], 'subject': q['subject'],
                **({'state': state} if state else {}), 'risk': False, 'references': values,
                'proofs': q['references'], 'label_basis': 'private_reference_values_absent_from_visible_records'}
    # Selection is deterministic, balanced when both classes exist, frozen
    # before Mem0/graph construction and all detector calls.
    rank = lambda item: hashlib.sha256(item[0].encode()).hexdigest()
    chosen = [v for _, v in sorted(by_key.items(), key=rank)[:12]]
    chosen += [v for _, v in sorted(negatives.items(), key=rank)[:12]]
    if not chosen:
        raise ValueError('No source-grounded cases for ' + job['task']['task_key'])
    chosen.sort(key=lambda v: hashlib.sha256(target_key(v['field'], v['subject'], v.get('state')).encode()).hexdigest())
    for i, q in enumerate(chosen):
        q['query_id'] = f'q{i}'
    return chosen


def prepare():
    jobs = load_jobs()
    assert len(jobs) == 50
    manifest = []
    for key, job in sorted(jobs.items()):
        old = HERE.parent / 'message_gain_v5/tasks' / key.replace('/', '_')
        observations = load(old / 'observed_messages.json')
        previous = load(old / 'results.json')
        memory = load(old / 'with_all_memory.json')
        folder = HERE / 'tasks' / key.replace('/', '_')
        cases = grounded_cases(job, memory, observations['with'])
        dump(folder / 'evaluator_only_cases.json', cases)
        dump(folder / 'observations.json', observations['without'])
        dump(folder / 'candidate_message.json', previous['selected_message'])
        dump(folder / 'original_memory_for_grounding.json', memory)
        dump(folder / 'source_graph.json', job['versions']['0'])
        # Whole-message blocks preserve role, tool and record boundaries.
        blocks = [{'id': o['message_id'], 'task_id': key, 'receiver_id': o['receiver_id'],
                   'field': o['direction'], 'kind': 'observed', 'relation': 'whole_message',
                   'event_id': o['event_id'], 'tool': o['tool'],
                   'text': enc({'tool': o['tool'], 'content': o['content'], 'status': o['status']})}
                  for o in observations['without']]
        dump(folder / 'mem0_input.json', {'schema': 'privacy.text.input.v1', 'blocks': blocks, 'links': []})
        item = {'task': key, 'folder': str(folder.relative_to(HERE)),
                'selected_message_id': previous['selected_message']['message_id'],
                'receivers': previous['receiver_ids'], 'queries': len(cases),
                'positive': sum(c['risk'] for c in cases), 'negative': sum(not c['risk'] for c in cases),
                'input_sha256': {p.name: sha(p) for p in folder.glob('*.json')}}
        manifest.append(item)
        print('PREPARED', key, item['positive'], item['negative'], flush=True)
    protocol = {'tasks': 50, 'real_messages_only': True, 'one_existing_fixed_message_per_task': True,
        'sample': 'same 50/97 tasks and same selected messages as message_gain_v5',
        'arms': ['0 = common Mem0 + full active shared graph',
                 '12345 = 0 + existing five structural simplification switches',
                 'TRAIL = 12345 + shared-key/relationship-preserving compact representation prototype'],
        'visibility': 'same explicit all-business-services coalition in every arm',
        'risk_definition': 'whether a concrete private field about the specified subject/state is recoverable from history plus candidate',
        'not_measured': ['unauthorized disclosure', 'new privacy gain relative to before message',
                         'unrestricted semantic privacy detection', 'graph/Mem0 construction token cost'],
        'reference_policy': 'source-grounded finite private-field benchmark; original evidence proofs for positives; absent independent private references for negatives',
        'query_selection': 'up to 12 source-grounded positives and 12 absent-reference negatives; deterministic SHA256 order before detector runs',
        'false_negative_rate': 'FN / (TP+FN) * 100; N/A if no positive',
        'false_positive_rate': 'FP / (FP+TN) * 100; N/A if no negative',
        'storage': 'actual compact UTF-8 bytes of operational memory file; no audit/cache duplication',
        'detection_tokens': 'actual API usage.total_tokens = prompt_tokens + completion_tokens; all detector attempts counted',
        'same_detector': 'deepseek-flash, identical prompt/query list, temperature 0', 'manifest': manifest}
    dump(HERE / 'protocol.json', protocol)
    print('PREPARATION_COMPLETE', len(manifest), flush=True)


def active_graph(source, observations):
    """Keep only operational past evidence; no future summaries or risk labels."""
    observations = annotate_observations(source['task']['task_key'], observations)
    by_mid = {o['message_id']: o for o in observations}
    reqs = {o['event_id']: o for o in observations if o['direction'] == 'R'}
    allowed_receipts = {n['disclosure_id'] for n in source['nodes']
                        if n['type'] == 'actual_disclosure' and n['event_id'] in reqs}
    allowed = set()
    nodes = []
    for n in source['nodes']:
        kind = n['type']
        keep = kind == 'business_receiver'
        if kind == 'actual_disclosure':
            keep = n['event_id'] in reqs
        elif kind in {'disclosed_atom', 'normalized_received_fact'}:
            keep = n.get('disclosure_id', n.get('receipt_id')) in allowed_receipts
        elif kind == 'graphiti_relation_claim':
            keep = bool(n.get('evidence')) and all(e['receipt_id'] in allowed_receipts for e in n['evidence'])
        elif kind == 'graphiti_entity':
            # Exclude model summaries: they can contain future updates.
            keep = any(n['label'] in enc(o['content']) and n.get('receiver_id') == o['receiver_id']
                       for o in observations)
        elif kind == 'graphiti_episode':
            episode_edges = [e for e in source['edges'] if e['source'] == n['id'] and e['kind'] == 'same_observed_request']
            request_ids = {r['id'] for r in source['nodes'] if r['type'] == 'actual_disclosure' and r['event_id'] in reqs}
            keep = any(e['target'] in request_ids for e in episode_edges)
        if not keep:
            continue
        fields = {'id', 'type', 'label', 'receiver_id', 'event_id', 'disclosure_id', 'receipt_id',
                  'parameters', 'empty_parameters', 'claim', 'predicate', 'extraction_method', 'evidence'}
        c = {k: copy.deepcopy(v) for k, v in n.items() if k in fields}
        receipt = n.get('disclosure_id', n.get('receipt_id'))
        event_id = n.get('event_id') or (receipt.rsplit('::', 1)[-1] if receipt else None)
        observation = by_mid.get(str(event_id) + ':R')
        if observation:
            c.update({k: observation[k] for k in ['state', 'state_basis', 'effect_status', 'observation_order']})
        else:
            c.update(state='unknown', state_basis='no_unique_record_version', effect_status='derived_label')
        if kind == 'actual_disclosure':
            c['parameters'] = copy.deepcopy(reqs[n['event_id']]['content'])
            c['subject'] = 'request:' + n['disclosure_id']
        if kind == 'disclosed_atom':
            c['annotation'] = {k: n['annotation'][k] for k in ['parameter_path', 'span_start', 'span_end']}
        # Existing graph claims are evidence-backed but model semantics remain unreviewed.
        if kind == 'graphiti_relation_claim':
            c['status'] = 'model_semantics_unreviewed'
        nodes.append(c)
        allowed.add(c['id'])
    edges = [{k: e[k] for k in ['id', 'source', 'target', 'kind']}
             for e in source['edges'] if e['source'] in allowed and e['target'] in allowed]
    # Add full own-service responses equally in every arm. They are prior
    # service knowledge, not new outgoing disclosures.
    for o in observations:
        if o['direction'] != 'S':
            continue
        n = {'id': 'response:' + o['receiver_id'] + ':' + o['event_id'], 'type': 'tool_response',
             'receiver_id': o['receiver_id'], 'event_id': o['event_id'],
             'label': o['tool'], 'content': o['content'], 'status': o['status'],
             **{k: o[k] for k in ['state', 'state_basis', 'effect_status', 'observation_order']}}
        if 'prior_write_event_id' in o:
            n['prior_write_event_id'] = o['prior_write_event_id']
        nodes.append(n)
    return {'task': source['task'], 'nodes': nodes, 'edges': edges, 'joint_factors': [],
            'statistics': {}, 'simplification': {}, 'input_alignment_version': ALIGNMENT_VERSION,
            'state_definitions': copy.deepcopy(STATE_DEFINITIONS),
            'subject_bindings': subject_bindings(source['task']['task_key'], observations)}


def online(graph):
    allowed = {'id', 'type', 'label', 'receiver_id', 'event_id', 'disclosure_id', 'receipt_id',
               'parameters', 'empty_parameters', 'claim', 'predicate', 'extraction_method',
               'members', 'member_count', 'content', 'status', 'subject',
               'state', 'state_basis', 'effect_status', 'observation_order', 'prior_write_event_id'}
    nodes = [{k: v for k, v in n.items() if k in allowed} for n in graph['nodes']]
    edges = [{k: v for k, v in e.items() if k in {'source', 'target', 'kind'}} for e in graph['edges']]
    messages = {(n['receiver_id'], n['event_id'], 'S' if n['type'] == 'tool_response' else 'R')
                for n in nodes if n['type'] in {'actual_disclosure', 'tool_response'}}
    bindings = [copy.deepcopy(b) for b in graph.get('subject_bindings', [])
                if (b['receiver_id'], b['event_id'], b['direction']) in messages]
    return {'schema': 'active_privacy_graph', 'visibility': 'explicit_shared_business_services',
            'nodes': nodes, 'edges': edges, 'input_alignment_version': ALIGNMENT_VERSION,
            'state_definitions': copy.deepcopy(STATE_DEFINITIONS), 'subject_bindings': bindings}


def trail_from_parent(parent):
    """Repack 12345 alone; retain record scopes and explicit cross-owner keys.

    Original requests/returns suffice to preserve unknown natural-language
    relations. No private environment, targets or removed node is consulted.
    """
    receivers = sorted({n['receiver_id'] for n in parent['nodes'] if n.get('receiver_id')})
    records = []
    aligned = parent.get('input_alignment_version') == ALIGNMENT_VERSION
    for n in parent['nodes']:
        if n['type'] == 'actual_disclosure':
            record = [receivers.index(n['receiver_id']), n['event_id'], 'R', n['label'], n['subject'], n['parameters']]
        elif n['type'] == 'tool_response':
            record = [receivers.index(n['receiver_id']), n['event_id'], 'S', n['label'], n['id'],
                      parse_response(n['content']) if n.get('status') != 'error' else {'tool_error': n['content']}]
        else:
            continue
        if aligned:
            record.extend(n[k] for k in ['state', 'state_basis', 'effect_status', 'observation_order'])
        records.append(record)
    records.sort(key=lambda r: (r[1], r[2]))
    # Shared keys index exact emails, URLs and explicit record IDs with their
    # local owner and path. Equality is a join candidate, not an identity proof.
    keys = defaultdict(list)
    def visit(v, pointer, owner, event):
        if isinstance(v, dict):
            for k, x in v.items():
                visit(x, pointer + '/' + str(k), owner, event)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                visit(x, pointer + '/' + str(i), owner, event)
        elif isinstance(v, str):
            found = re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:https?://|www\.)[^\s<>]+', v)
            if pointer.rsplit('/', 1)[-1] in {'id_', 'id', 'event_id', 'file_id', 'transaction_id'}:
                found.append('record:' + v)
            for key in set(found):
                keys[key].append([owner, event, pointer])
    for record in records:
        owner, event, _, _, _, content = record[:6]
        visit(content, '', owner, event)
    shared = [[k, v] for k, v in sorted(keys.items()) if len({x[0] for x in v}) > 1]
    # Field paths are semantic roles, even when named request.parameter. Keep
    # all active assertions with their exact subject and context as one unit.
    relations = [[receivers.index(n['receiver_id']), n['claim']] for n in parent['nodes']
                 if n['type'] == 'normalized_received_fact']
    field_roles = [[receivers.index(n['receiver_id']), n.get('disclosure_id', n.get('receipt_id')),
                    n['label']] for n in parent['nodes'] if n['type'] == 'disclosed_atom']
    result = {'schema': 'TRAIL_relation_preserving_compact_prototype_v2', 'receivers': receivers,
            'record_columns': ['receiver_index', 'event_id', 'direction', 'tool', 'subject', 'record_content'],
            'records': records, 'scoped_relations': relations, 'retained_fragments': field_roles,
            'cross_receiver_exact_key_candidates': shared,
            'join_policy': 'preserve explicit subject/predicate/object, record boundaries and time; common keys are candidates requiring compatible meaning; never equate people by task membership'}
    if aligned:
        result['record_columns'] += ['state', 'state_basis', 'effect_status', 'observation_order']
        result.update({k: copy.deepcopy(parent[k]) for k in
                       ['input_alignment_version', 'state_definitions', 'subject_bindings']})
    return result


def build():
    protocol = load(HERE / 'protocol.json')
    completed = 0
    for item in protocol['manifest']:
        folder = HERE / item['folder']
        if not (folder / 'mem0' / 'memory.json').exists():
            continue
        if (folder / 'frozen_inputs.json').exists():
            previous = load(folder / 'arms/TRAIL/memory.json')
            if previous.get('schema') != 'TRAIL_relation_preserving_compact_prototype_v2':
                parent = load(folder / 'arms/12345/memory.json')
                trail = trail_from_parent(parent)
                arm_dir = folder / 'arms/TRAIL'
                archive = arm_dir / 'previous_representation_v1'
                archive.mkdir(exist_ok=True)
                for p in [*arm_dir.glob('request.json'), *arm_dir.glob('prediction.json'),
                          *arm_dir.glob('response_*.json'), arm_dir / 'memory.json']:
                    p.replace(archive / p.name)
                (arm_dir / 'memory.json').write_text(enc(trail), encoding='utf-8')
                frozen = load(folder / 'frozen_inputs.json')
                frozen['arm_memory_bytes']['TRAIL'] = (arm_dir / 'memory.json').stat().st_size
                frozen['arm_memory_sha256']['TRAIL'] = sha(arm_dir / 'memory.json')
                dump(folder / 'frozen_inputs.json', frozen)
                print('PRESERVED_ALL_SCOPED_ROLES', item['task'], flush=True)
            completed += 1
            continue
        observations = load(folder / 'observations.json')
        mem0 = load(folder / 'mem0' / 'memory.json')
        facts = {f['id']: f for f in mem0['facts']}
        canonical_texts = {o['id']: facts[o['fact_ref']]['text'] for o in mem0['occurrences']}
        # Mem0 may group equivalent texts, but this experiment needs exactly
        # the same observed content in every graph arm and no future rewrite.
        for o in observations:
            text = canonical_texts[o['message_id']]
            expected = enc({'tool': o['tool'], 'content': o['content'], 'status': o['status']})
            if json.loads(text) != json.loads(expected):
                raise ValueError('Whole-message Mem0 representative changed record contents')
        full = active_graph(load(folder / 'source_graph.json'), observations)
        simplified = simplify_graph(full, SimplificationConfig(enabled=True))
        base, compressed = online(full), online(simplified)
        trail = trail_from_parent(compressed)
        arms = {'0': base, '12345': compressed, 'TRAIL': trail}
        # Audit each exact operation and retain it outside active storage.
        dump(folder / 'simplification_audit.json', simplified['simplification'])
        for arm, memory in arms.items():
            p = folder / 'arms' / arm / 'memory.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(enc(memory), encoding='utf-8')
        cases = load(folder / 'evaluator_only_cases.json')
        targets = [{k: c[k] for k in ['query_id', 'field', 'subject', 'state'] if k in c} for c in cases]
        dump(folder / 'targets.json', targets)
        inputs = {'task': item['task'], 'arm_memory_bytes': {
            arm: (folder / 'arms' / arm / 'memory.json').stat().st_size for arm in arms},
            'query_sha256': sha(folder / 'targets.json'), 'candidate_sha256': sha(folder / 'candidate_message.json'),
            'arm_memory_sha256': {a: sha(folder / 'arms' / a / 'memory.json') for a in arms}}
        dump(folder / 'frozen_inputs.json', inputs)
        completed += 1
        print('BUILT', item['task'], inputs['arm_memory_bytes'], flush=True)
    print('THREE_ARMS_FROZEN', completed, '/ 50 tasks', flush=True)


def align_inputs():
    """Rebuild input-only snapshots; keep the scored experiment immutable."""
    from run_api import make_detection_request
    output = HERE / 'aligned_inputs_v2'
    protocol = load(HERE / 'protocol.json')
    manifest = []
    preserved = {str(p.relative_to(HERE)): sha(p) for p in HERE.glob('tasks/*/arms/*/*.json')}
    preserved.update({str(p.relative_to(HERE)): sha(p) for p in HERE.glob('tasks/*/targets.json')})
    for item in protocol['manifest']:
        source_folder = HERE / item['folder']
        folder = output / item['folder']
        raw_history = load(source_folder / 'observations.json')
        raw_candidate = load(source_folder / 'candidate_message.json')
        annotated = annotate_observations(item['task'], raw_history + [raw_candidate])
        history, candidate = annotated[:-1], annotated[-1]
        # Filter by the exact message, never by a query or reference answer.
        candidate['subject_bindings'] = [b for b in subject_bindings(item['task'], annotated)
                                         if b['message_id'] == candidate['message_id']]
        full = active_graph(load(source_folder / 'source_graph.json'), raw_history)
        simplified = simplify_graph(full, SimplificationConfig(enabled=True))
        base, compressed = online(full), online(simplified)
        trail = trail_from_parent(compressed)
        arms = {'0': base, '12345': compressed, 'TRAIL': trail}
        dump(folder / 'observations.json', history)
        dump(folder / 'candidate_message.json', candidate)
        targets_bytes = (source_folder / 'targets.json').read_bytes()
        (folder / 'targets.json').write_bytes(targets_bytes)
        targets = json.loads(targets_bytes)
        for arm, memory in arms.items():
            arm_folder = folder / 'arms' / arm
            arm_folder.mkdir(parents=True, exist_ok=True)
            (arm_folder / 'memory.json').write_text(enc(memory), encoding='utf-8')
            dump(arm_folder / 'request_preview.json', make_detection_request(memory, candidate, targets))
        record = {'task': item['task'], 'folder': item['folder'],
                  'source_folder': str(source_folder.relative_to(ROOT)), 'receivers': item['receivers'],
                  'targets_sha256': sha(folder / 'targets.json'),
                  'candidate_sha256': sha(folder / 'candidate_message.json'),
                  'reference_sha256': sha(source_folder / 'evaluator_only_cases.json'),
                  'history_messages': len(history), 'history_bindings': len(base['subject_bindings']),
                  'candidate_bindings': len(candidate['subject_bindings']),
                  'arm_sha256': {a: sha(folder / 'arms' / a / 'memory.json') for a in arms},
                  'request_sha256': {a: sha(folder / 'arms' / a / 'request_preview.json') for a in arms}}
        manifest.append(record)
        print('ALIGNED', item['task'], 'bindings', record['history_bindings'] + record['candidate_bindings'], flush=True)
    assert all(sha(HERE / path) == value for path, value in preserved.items())
    dump(output / 'manifest.json', {'input_alignment_version': ALIGNMENT_VERSION, 'tasks': manifest,
        'model_calls': 0, 'questions_and_references_unchanged': True,
        'old_scored_inputs_unchanged': True, 'states_and_bindings_from_visible_observations_only': True})
    # Freeze the follow-up cohort before any new predictions, stratified only
    # by suite and multi-receiver status, not by labels or recovery outcomes.
    strata = defaultdict(list)
    for item in manifest:
        strata[(item['task'].split('/', 1)[0], len(item['receivers']) > 1)].append(item)
    quotas = {k: len(v) * 20 // 50 for k, v in strata.items()}
    remaining = 20 - sum(quotas.values())
    ranked = sorted(strata, key=lambda k: (-(len(strata[k]) * 20 % 50), k))
    for k in ranked[:remaining]:
        quotas[k] += 1
    selected = []
    for stratum in sorted(strata):
        entries = sorted(strata[stratum], key=lambda x: hashlib.sha256(
            ('aligned-inputs-v2-20of50:' + x['task']).encode()).hexdigest())
        selected.extend(entries[:quotas[stratum]])
    selected.sort(key=lambda x: x['task'])
    assert len(selected) == 20
    dump(output / 'cohort_20.json', {'status': 'prepared_waiting_for_user_confirmation', 'model_calls': 0,
        'selection': 'largest-remainder proportional allocation by suite and multi-receiver status; SHA256 order within strata',
        'selection_salt': 'aligned-inputs-v2-20of50:',
        'strata': [{'suite': k[0], 'multi_receiver': k[1], 'population': len(strata[k]), 'selected': quotas[k]}
                   for k in sorted(strata)], 'tasks': selected})
    print('ALIGNED_ALL_50_AND_FROZEN_20_NO_MODEL_CALLS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'build', 'align'])
    args = parser.parse_args()
    {'prepare': prepare, 'build': build, 'align': align_inputs}[args.stage]()
