"""Service-owned response knowledge, separate from incoming disclosures.

Only matched, recorded TOOL events enter. No private environment, task prompt,
source_candidates, or another service's response is used as memory evidence.
"""
import ast
import copy
import json
from collections import Counter

from p0.policy import READ_TOOLS
from p0.tool_memory import execution_memory_from_graph, tool_observation

VERSION = 'privacy.bidirectional-memory.v1'
PROJECTION = 'tool_response_projection_v1'


def attach_tool_responses(graph, execution_graph):
    """Return a new graph with active, service-scoped response nodes.

    The source service knows what it returned; only the addressed agent sees
    that return. Responses are not counted as new agent-to-service disclosures.
    Reattachment replaces the response layer, never appends duplicate facts.
    """
    result = copy.deepcopy(graph)
    previous = {n['id'] for n in result['nodes'] if n['type'] == 'tool_response'}
    result['nodes'] = [n for n in result['nodes'] if n['id'] not in previous]
    result['edges'] = [e for e in result['edges']
                       if e['source'] not in previous and e['target'] not in previous]
    events = {n['id']: n for n in execution_graph['nodes'] if n['type'] == 'TOOL'}
    if len(events) != sum(n['type'] == 'TOOL' for n in execution_graph['nodes']):
        raise ValueError('Duplicate execution event IDs')
    requests = {n['event_id']: n for n in result['nodes'] if n['type'] == 'actual_disclosure'}
    services = {n['receiver_id']: n for n in result['nodes'] if n['type'] == 'business_receiver'}
    task_key = result['task']['task_key']
    read_tools = READ_TOOLS[task_key.split('/', 1)[0]]
    mutated, responses = set(), {}
    for event in execution_graph['nodes']:
        if event.get('type') != 'TOOL' or event['id'] not in requests:
            continue
        request, payload = requests[event['id']], event['payload']
        if request['label'] != payload['name'] or request['parameters'] != payload['arguments']:
            raise ValueError('Response source does not match the observed service request')
        rid = request['receiver_id']
        if rid not in services:
            raise ValueError('Response source service is absent')
        observation = tool_observation(event)
        if observation is not None:
            nid = f'response:{rid}:{event["id"]}'
            state = 'before' if rid not in mutated and payload['name'] in read_tools else 'after'
            node = {'id': nid, 'type': 'tool_response', 'label': payload['name'],
                    'receiver_id': rid, **observation, 'state': state,
                    'knowledge_origin': 'service_produced_response',
                    'counts_as_incoming_disclosure': False}
            result['nodes'].append(node)
            result['edges'].append({'id': 'response_edge:' + nid, 'source': nid,
                                    'target': services[rid]['id'], 'kind': 'retains_tool_response',
                                    'semantics': '服务保留自身实际返回的内容；不是新增外部披露'})
            responses[event['id']] = node
        # A failed write may have partial effects; do not call later reads pre-task state.
        if payload['name'] not in read_tools:
            mutated.add(rid)
    missing = set(requests) - set(events)
    if missing:
        raise ValueError('Missing execution events for observed requests: ' + ', '.join(sorted(missing)))
    for node in result['nodes']:
        if node['type'] == 'business_receiver':
            node['visibility'] = '请求参数及本服务实际返回的内容'
            node['receipt_rules'] = '请求与返回分别保留来源；自身返回不算新增外部披露；既有未观察资料未知'
        elif node['type'] == 'receiver_memory_state':
            node['cumulative_response_ids'] = [responses[did.rsplit('::', 1)[-1]]['id']
                for did in node.get('cumulative_disclosure_ids', [])
                if did.rsplit('::', 1)[-1] in responses]
    for memory in result.get('receiver_memory', []):
        memory['produced_responses'] = [copy.deepcopy(n) for n in responses.values()
                                        if n['receiver_id'] == memory['receiver_id']]
    result['execution_memory'] = execution_memory_from_graph(execution_graph)
    result['memory_observation_version'] = VERSION
    result.setdefault('edge_semantics', {})['retains_tool_response'] = '服务保留自身实际返回的内容；不是新增外部披露'
    result.setdefault('boundary', {})['knowledge_scope'] = 'observed service requests and own tool responses; per-agent delivery'
    result.setdefault('statistics', {}).update(tool_responses=len(responses),
        nodes=len(result['nodes']), edges=len(result['edges']),
        node_types=dict(Counter(n['type'] for n in result['nodes'])))
    return result


def parse_response(text):
    """Decode benchmark JSON/Python-literal/YAML records; retain raw text always."""
    for decoder in (json.loads, ast.literal_eval):
        try:
            return decoder(text)
        except (ValueError, SyntaxError, TypeError, RecursionError):
            pass
    import yaml
    try:
        # BaseLoader preserves identifiers, dates and leading-zero strings exactly.
        return yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return text


def response_facts(node):
    """Raw response plus bounded explicit record fields, with local evidence IDs."""
    fid = node['id'] + ':raw'
    meta = {'event_id': node['event_id'], 'tool': node['tool'],
            'observed_at': node['observed_at'], 'state': node['state'],
            'knowledge_origin': 'service_produced_response', 'direction': 'receiver_to_agent'}
    facts = [{'fact_id': fid, 'field': 'tool_response', 'value': node['content'], **meta,
              **({'status': 'tool_error'} if node['error'] is not None else {})}]
    if node['error'] is not None:
        return facts

    def add(field, value, subject, path):
        if value is None or value == '' or value == []:
            return
        facts.append({'fact_id': fid + ':' + str(len(facts)), 'field': field,
                      'value': copy.deepcopy(value), 'subject': subject,
                      'response_path': path, 'evidence_fact_ids': [fid],
                      'extraction_method': PROJECTION, **meta})

    value, tool = parse_response(node['content']), node['tool']
    if tool == 'get_balance':
        add('financial_balance', value, 'bank:self', '')
    elif tool == 'get_iban':
        add('account_number', node['content'], 'bank:self', '')
    elif tool == 'read_file':
        add('document_content', node['content'], node['id'] + ':document', '')
    items = value if isinstance(value, list) else [value]
    for index, record in enumerate(items):
        if not isinstance(record, dict):
            continue
        path = '/' + str(index) if isinstance(value, list) else ''
        identity = record.get('id_', record.get('id'))
        if tool in {'get_user_info', 'get_user_information', 'search_contacts_by_name', 'search_contacts_by_email'}:
            name = record.get('name') or ' '.join(str(record.get(k, '')) for k in ('first_name', 'last_name')).strip()
            subject = name or node['id'] + path + ':person'
            add('legal_name', name, subject, path)
            for key, field in [('email', 'email_address'), ('phone', 'phone_number'),
                               ('phone_number', 'phone_number'), ('street', 'postal_address'), ('city', 'postal_address')]:
                add(field, record.get(key), subject, path + '/' + key)
        elif tool in {'get_most_recent_transactions', 'get_scheduled_transactions'} and identity is not None:
            subject = 'bank:transaction:' + str(identity)
            add('financial_amount', record.get('amount'), subject, path + '/amount')
            add('account_number', record.get('recipient'), subject, path + '/recipient')
            if all(k in record for k in ('recipient', 'amount', 'subject', 'date')):
                add('financial_transaction', {k: record[k] for k in ('recipient', 'amount', 'subject', 'date')}, subject, path)
        elif tool in {'list_files', 'get_file_by_id', 'search_files', 'search_files_by_filename', 'create_file'} and identity is not None:
            subject = 'drive:file:' + str(identity)
            add('file_metadata', record.get('filename'), subject, path + '/filename')
            add('document_content', record.get('content'), subject, path + '/content')
        elif tool in {'get_day_calendar_events', 'search_calendar_events', 'create_calendar_event', 'reschedule_calendar_event'} and identity is not None:
            subject = 'calendar:event:' + str(identity)
            for key, field in [('start_time', 'calendar_start_time'), ('end_time', 'calendar_end_time'),
                               ('title', 'meeting_topic'), ('location', 'event_location'), ('participants', 'event_participants')]:
                add(field, record.get(key), subject, path + '/' + key)
        elif tool in {'search_emails', 'get_unread_emails', 'get_received_emails', 'get_sent_emails',
                      'get_draft_emails', 'send_email', 'read_inbox', 'read_channel_messages'}:
            subject = node['id'] + path + ':message'
            add('message_content', record.get('body'), subject, path + '/body')
            metadata = {k: record[k] for k in ('sender', 'recipients', 'channel', 'subject', 'timestamp') if k in record}
            add('communication_metadata', metadata or None, subject, path)
    return facts
