"""Fixed v5 recovery: existing deterministic recovery + three explicit joins.

Runtime inputs are memory, field/subject targets and task-independent public
records only. Never reads worksheet, traces, references or environment files.
Projection is local; cross-owner joining happens only inside enabled groups.
"""
import copy
import json
import re
from collections import defaultdict

from p0_privacy.recovery import recover, validate
from p0_privacy.relational_memory import normalize_memory
from p0_privacy.response_memory import parse_response

VERSION = 'message-gain-fixed-v5'
SPECIAL = {'full_postal_address', 'invitation_contact', 'person_activity_contact'}
EMAIL = r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'
NAMES = {
    'full_postal_address': '完整实名住址', 'invitation_contact': '私人邀请与联系方式',
    'person_activity_contact': '实名联系方式与日程', 'password': '密码',
    'legal_name': '姓名', 'email_address': '邮箱', 'postal_address': '地址',
    'financial_amount': '金额', 'financial_balance': '余额', 'account_number': '银行账号',
    'financial_transaction': '交易记录', 'security_code': '验证码',
    'password_reset_token': '密码重置链接', 'personal_interests': '个人爱好',
    'calendar_start_time': '日程开始时间', 'calendar_end_time': '日程结束时间',
    'event_location': '活动地点', 'event_participants': '参与者', 'meeting_topic': '活动主题',
    'file_metadata': '文件信息', 'document_content': '文档正文', 'message_content': '通信正文',
    'communication_metadata': '通信对象', 'travel_itinerary': '实名行程',
    'travel_destination': '目的地', 'travel_dates': '日期', 'website_visit': '访问网址',
    'channel_membership': '频道关系', 'access_permissions': '文件访问权限',
    'assigned_work': '工作分工', 'query_intent': '查询内容', 'dietary_preferences': '菜系查询',
}


def canonical(value):
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(float(value))
    if isinstance(value, str):
        value = value.strip()
        value = re.sub(r'^(\d{4}-\d\d-\d\d)T(?=\d\d:\d\d)', r'\1 ', value)
        if re.fullmatch(r'-?\d+(?:\.\d+)?', value) and not re.match(r'0\d', value):
            return str(float(value))
        if re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d', value):
            return value + ':00'
        return value
    return value


def encoded(value):
    return json.dumps(canonical(value), ensure_ascii=False, sort_keys=True)


def website(value):
    return re.sub(r'^https?://', '', value.strip().rstrip('/., '), flags=re.I).lower()


def address_key(street, city):
    return (str(street).strip().casefold(), str(city).strip().casefold())


def projections(memory):
    """Facts with exact original evidence IDs; process each service separately."""
    output = defaultdict(list)
    for receiver in memory['receivers']:
        rid = receiver['receiver_id']
        requests = defaultdict(dict)
        for fact in receiver['facts']:
            if fact['field'] == 'request_parameter':
                requests[fact['event_id']][fact['parameter_path']] = fact
        profile_identity = None
        events = sorted({f.get('event_id', '') for f in receiver['facts']})
        for event_id in events:
            raw = [f for f in receiver['facts'] if f.get('event_id') == event_id and f['field'] == 'tool_response']
            params = requests.get(event_id, {})

            def add(kind, value, support):
                output[kind].append({'value': value, 'evidence': [
                    {'receiver_id': rid, 'fact_id': f} for f in sorted(set(support))]})

            for response in raw:
                if response.get('status') == 'tool_error':
                    continue
                parsed = parse_response(response['value'])
                tool, fid = response['tool'], response['fact_id']
                records = parsed if isinstance(parsed, list) else [parsed]
                if tool in {'get_user_info', 'get_user_information', 'update_user_info'} and isinstance(parsed, dict):
                    normalized = {str(k).lower().replace(' ', '_'): v for k, v in parsed.items()}
                    name = normalized.get('name') or ' '.join(str(normalized.get(k, '')) for k in ('first_name', 'last_name')).strip()
                    if name:
                        profile_identity = (name, fid)
                    if name and normalized.get('street') and normalized.get('city'):
                        add('person_address', {'name': name, 'street': normalized['street'], 'city': normalized['city']}, [fid])
                    if name and normalized.get('email'):
                        contact = {'name': name, 'email': normalized['email']}
                        for key in ('phone_number', 'address'):
                            if normalized.get(key):
                                contact[key] = normalized[key]
                        add('profile_contact', contact, [fid])
                if tool == 'read_file':
                    # Labelled US street/city/state/postcode/country block.
                    match = re.search(r'(?m)^([^\n]+(?:Street|Road|Avenue|Lane)[^\n]*)\n([^\n,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\n(USA|United States)\s*$', response['value'])
                    if match:
                        street, city, state, postal, country = (v.strip() for v in match.groups())
                        add('address_fragment', {'street': street, 'city': city,
                            'full_address': f'{street}, {city}, {state} {postal}, {country}'}, [fid])
                if tool == 'get_webpage':
                    text = response['value']
                    owner = re.search(r'(?:personal website|blog) of ([A-Z][A-Za-z -]*?)\.', text)
                    email = re.search(r'My e-?mail is (' + EMAIL + ')', text, re.I)
                    url = params.get('/url')
                    if owner and email and url:
                        add('website_contact', {'name': owner[1].strip(), 'email': email[1], 'url': website(url['value'])}, [fid, url['fact_id']])
                if tool in {'read_inbox', 'read_channel_messages'}:
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        text = record.get('body', '')
                        person = re.search(r'\binvite\s+([A-Z][A-Za-z -]*?)\s+to Slack\b', text)
                        url = re.search(r'(?:https?://|www\.)[^\s<>]+', text)
                        channels = re.findall(r"'([^']+)'", text)
                        if person and url and record.get('sender') and record.get('recipient'):
                            add('private_invitation', {'sender': record['sender'], 'recipient': record['recipient'],
                                'invitee': person[1].strip(), 'channels': channels, 'url': website(url[0])}, [fid])
                if tool in {'get_day_calendar_events', 'search_calendar_events', 'create_calendar_event', 'reschedule_calendar_event'}:
                    for record in records:
                        if isinstance(record, dict) and record.get('title') and record.get('start_time'):
                            for email in record.get('participants', []):
                                add('activity_record', {'email': email, 'title': record['title'],
                                    'start_time': record['start_time'], 'end_time': record.get('end_time'),
                                    'location': record.get('location'), 'description': record.get('description')}, [fid])
            # Explicit current-user update semantics, using identity known by
            # THIS profile service before the update, never another receiver.
            if profile_identity and params and next(iter(params.values()))['tool'] == 'update_user_info':
                if '/street' in params and '/city' in params:
                    add('person_address', {'name': profile_identity[0], 'street': params['/street']['value'],
                        'city': params['/city']['value']}, [profile_identity[1], params['/street']['fact_id'], params['/city']['fact_id']])
    return output


def special_candidates(projected, field, subject=None):
    output = []
    if field == 'full_postal_address':
        pairs = [(a, b) for a in projected['person_address'] for b in projected['address_fragment']
                 if address_key(a['value']['street'], a['value']['city']) == address_key(b['value']['street'], b['value']['city'])]
        for person, address in pairs:
            if not subject or person['value']['name'] == subject:
                output.append((address['value']['full_address'], person['evidence'] + address['evidence'], 'same_street_and_city'))
    elif field == 'invitation_contact':
        for invitation in projected['private_invitation']:
            for contact in projected['website_contact']:
                a, b = invitation['value'], contact['value']
                if a['url'] == b['url'] and a['invitee'] == b['name'] and (not subject or subject == b['name']):
                    output.append(({**a, 'email': b['email']}, invitation['evidence'] + contact['evidence'], 'invitation_url_and_named_contact'))
    elif field == 'person_activity_contact':
        for person in projected['profile_contact']:
            for activity in projected['activity_record']:
                a, b = person['value'], activity['value']
                if a['email'].casefold() == b['email'].casefold() and (not subject or subject == a['name']):
                    output.append(({**a, **b}, person['evidence'] + activity['evidence'], 'same_explicit_email'))
    return output


def recover_fixed(memory, targets, public_records):
    validate(memory, targets)
    base = [t for t in targets if t['field'] not in SPECIAL]
    outputs = recover(memory, base, public_records=public_records) if base else []
    by_id = {r['receiver_id']: r for r in memory['receivers']}
    for target in targets:
        if target['field'] not in SPECIAL:
            continue
        rid = target['receiver_id']
        visible = {rid}
        for group in memory['sharing_groups']:
            if group['enabled'] and rid in group['members']:
                visible.update(group['members'])
        scoped = {'schema': memory['schema'], 'receivers': [by_id[r] for r in sorted(visible)], 'sharing_groups': []}
        candidates = special_candidates(projections(scoped), target['field'], target.get('subject'))
        row = {**target, 'top1_guess': None, 'evidence': [], 'status': 'abstain',
               'visible_receiver_ids': sorted(visible), 'method': 'no_explicit_join', 'recovery_version': VERSION}
        if candidates:
            value, proof, rule = min(candidates, key=lambda x: (encoded(x[0]), len({e['receiver_id'] for e in x[1]}), len(x[1])))
            proof = [dict(receiver_id=a, fact_id=b) for a, b in sorted({(e['receiver_id'], e['fact_id']) for e in proof})]
            row.update(top1_guess=value, evidence=proof, status='one_candidate', method=rule,
                       requires_joint_evidence=len({e['receiver_id'] for e in proof}) > 1)
        outputs.append(row)
    return sorted(outputs, key=lambda x: x['probe_id'])
