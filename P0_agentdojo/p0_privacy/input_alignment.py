"""Deterministic subject pointers and temporal metadata from visible messages.

No questions, references, private environment, model client or future log enters.
The state convention matches service-scoped response memory; write requests
describe a requested after-state, not evidence that the write succeeded.
"""
import copy
import re
from collections import defaultdict

from p0.policy import READ_TOOLS, WRITE_TOOLS
from .response_memory import parse_response, response_facts

VERSION = 'privacy.input-alignment.v1'
STATE_DEFINITIONS = {
    'before': 'Record observed before this service has completed any write call in the task; it need not be modified later.',
    'after': 'Record observed after a service write call, or a desired write-state in a request. Check effect_status.',
    'unknown': 'The visible tool semantics or source record do not establish its state.',
    'effect_status': 'requested is an outgoing request, not a successful write; error gives no successful record.',
    'record_path': 'RFC 6901 pointer into parsed content of the exact receiver/event/direction message, not a list position in another message.',
}

REFERENCE_TOOLS = {
    'get_file_by_id': ('drive:file:', ('file_id',)),
    'append_to_file': ('drive:file:', ('file_id',)),
    'delete_file': ('drive:file:', ('file_id',)),
    'share_file': ('drive:file:', ('file_id',)),
    'cancel_calendar_event': ('calendar:event:', ('event_id',)),
    'reschedule_calendar_event': ('calendar:event:', ('event_id',)),
    'add_calendar_event_participants': ('calendar:event:', ('event_id',)),
    'update_scheduled_transaction': ('bank:transaction:', ('id', 'id_', 'transaction_id')),
}


def annotate_observations(task_key, observations):
    """Compute phases in visible order, with an independent clock per service."""
    suite = task_key.split('/', 1)[0]
    read, write = READ_TOOLS[suite], WRITE_TOOLS[suite]
    seen, requests, writes = set(), {}, {}
    previous = None
    result = []
    for order, original in enumerate(observations):
        row = copy.deepcopy(original)
        eid, side, rid, tool = (row[k] for k in ['event_id', 'direction', 'receiver_id', 'tool'])
        if side not in {'R', 'S'} or row['message_id'] != eid + ':' + side:
            raise ValueError('Invalid message direction or identifier')
        match = re.fullmatch(r'e(\d+)', eid)
        if not match:
            raise ValueError('Expected a recorded numeric event ID')
        position = (int(match[1]), side == 'S')
        if row['message_id'] in seen or previous is not None and position < previous:
            raise ValueError('Duplicate or out-of-order visible message')
        seen.add(row['message_id'])
        previous = position
        if side == 'R':
            requests[eid] = (rid, tool)
        elif requests.get(eid) != (rid, tool):
            raise ValueError('Tool return has no matching visible request')
        row['observation_order'] = order
        row['state'] = ('after' if tool in write or rid in writes else 'before') if tool in read | write else 'unknown'
        row['state_basis'] = ('write_request' if side == 'R' else 'write_response') if tool in write else (
            'read_after_service_write' if rid in writes else 'read_before_service_write') if tool in read else 'unknown_tool_semantics'
        row['effect_status'] = 'requested' if side == 'R' else 'error' if row.get('status') == 'error' else (
            'observed_write_result' if tool in write else 'observed_read' if tool in read else 'unknown')
        if rid in writes:
            row['prior_write_event_id'] = writes[rid]
        result.append(row)
        # Failed calls can have partial effects; later reads cannot establish
        # the original state merely because a write returned an error.
        if side == 'S' and tool in write:
            writes[rid] = eid
    return result


def pointer_value(value, pointer):
    if not pointer:
        return value
    if not pointer.startswith('/'):
        raise ValueError('Record path must be a JSON pointer')
    for part in pointer[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def parsed_content(observation):
    return parse_response(observation['content']) if observation['direction'] == 'S' else observation['content']


def subject_bindings(task_key, observations):
    """Map only explicit subjects to exact local record/field pointers."""
    bindings = []
    for o in observations:
        if 'state' not in o:
            raise ValueError('Annotate message states before constructing bindings')
        base = {k: copy.deepcopy(o[k]) for k in ['message_id', 'receiver_id', 'event_id',
            'direction', 'state', 'state_basis', 'effect_status', 'observation_order']}
        if 'prior_write_event_id' in o:
            base['prior_write_event_id'] = o['prior_write_event_id']
        raw_subject = 'response:' + o['receiver_id'] + ':' + o['event_id']
        if o['direction'] == 'R':
            subject = f'request:{task_key}::{o["receiver_id"]}::{o["event_id"]}'
            bindings.append({**base, 'subject': subject, 'record_path': '', 'binding_kind': 'request_object'})
            reference = REFERENCE_TOOLS.get(o['tool'])
            if reference and isinstance(o['content'], dict):
                prefix, keys = reference
                for key in keys:
                    value = o['content'].get(key)
                    if isinstance(value, (str, int)) and not isinstance(value, bool):
                        bindings.append({**base, 'subject': prefix + str(value), 'record_path': '',
                            'identifier': {'path': '/' + key, 'value': value}, 'binding_kind': 'request_record_reference'})
            continue
        bindings.append({**base, 'subject': raw_subject, 'record_path': '', 'binding_kind': 'whole_response'})
        if o.get('status') == 'error':
            continue
        parsed = parsed_content(o)
        node = {'id': raw_subject, 'event_id': o['event_id'], 'tool': o['tool'],
                'observed_at': o.get('observed_at'), 'state': o['state'], 'content': o['content'], 'error': None}
        grouped = {}
        for fact in response_facts(node):
            if 'subject' not in fact or 'response_path' not in fact:
                continue
            path = fact['response_path']
            record_path = '/' + path.split('/')[1] if isinstance(parsed, list) and path.startswith('/') else ''
            key = (fact['subject'], record_path)
            binding = grouped.setdefault(key, {**base, 'subject': fact['subject'], 'record_path': record_path,
                'binding_kind': 'explicit_response_record', 'field_paths': defaultdict(list)})
            if path not in binding['field_paths'][fact['field']]:
                binding['field_paths'][fact['field']].append(path)
            record = pointer_value(parsed, record_path)
            if isinstance(record, dict):
                identity_key = 'id_' if 'id_' in record else 'id' if 'id' in record else None
                if identity_key:
                    binding['identifier'] = {'path': record_path + '/' + identity_key, 'value': record[identity_key]}
        for b in grouped.values():
            b['field_paths'] = dict(b['field_paths'])
            bindings.append(b)
    validate_bindings(observations, bindings)
    return bindings


def validate_bindings(observations, bindings):
    by_id = {o['message_id']: o for o in observations}
    seen = set()
    for binding in bindings:
        source = by_id[binding['message_id']]
        key = (binding['message_id'], binding['subject'], binding['record_path'])
        if key in seen:
            raise ValueError('Duplicate subject binding')
        seen.add(key)
        for field in ['receiver_id', 'event_id', 'direction', 'state', 'state_basis', 'effect_status', 'observation_order']:
            if binding[field] != source[field]:
                raise ValueError('Binding changed source ownership or state')
        content = parsed_content(source)
        pointer_value(content, binding['record_path'])
        identifier = binding.get('identifier')
        if identifier and pointer_value(content, identifier['path']) != identifier['value']:
            raise ValueError('Identifier is not supported by the source record')
        for paths in binding.get('field_paths', {}).values():
            for path in paths:
                pointer_value(content, path)
        if source.get('status') == 'error' and binding['binding_kind'] != 'whole_response':
            raise ValueError('An error is not a successfully observed record')
    return True
