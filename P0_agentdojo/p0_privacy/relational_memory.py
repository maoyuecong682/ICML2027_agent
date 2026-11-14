"""Named privacy assertions, derived only from each receiver's visible facts.

Raw evidence is retained. Every stored assertion names its subject and lists
the exact local facts that establish that binding. No environment/gold access.
"""
import copy
import csv
import hashlib
import io
import json
import re
from collections import defaultdict

VERSION = 'privacy.named-memory.v3'
EMAIL = r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'
PERSON = r'[A-Za-z][A-Za-z0-9_ -]{0,79}|[\u4e00-\u9fff]{1,20}'
UNKNOWN = {'someone', 'some user', 'a user', 'unknown', 'user', '某人', '某个用户', '用户'}
ID_TOOLS = {
    'update_scheduled_transaction': ('transaction_ref', 'bank:transaction:'),
    'delete_scheduled_transaction': ('transaction_ref', 'bank:transaction:'),
    'cancel_calendar_event': ('event_ref', 'calendar:event:'),
    'reschedule_calendar_event': ('event_ref', 'calendar:event:'),
    'get_file_by_id': ('file_ref', 'drive:file:'),
    'delete_file': ('file_ref', 'drive:file:'),
    'append_to_file': ('file_ref', 'drive:file:'),
}
TRANSACTION_TOOLS = {'send_money', 'schedule_transaction', 'update_scheduled_transaction',
                     'get_most_recent_transactions', 'get_scheduled_transactions'}
AFTER_TOOLS = {'send_money', 'schedule_transaction', 'update_scheduled_transaction',
               'create_calendar_event', 'reschedule_calendar_event', 'create_file',
               'append_to_file', 'update_password', 'update_user_info'}


def claim(subject, predicate, value, context=None):
    return {'subject': subject, 'predicate': predicate, 'object': value,
            'context': copy.deepcopy(context or {})}


def context_for(fact):
    context = copy.deepcopy(fact.get('context', {}))
    if fact.get('state'):
        context['state'] = fact['state']
    elif fact.get('tool') in AFTER_TOOLS:
        context['state'] = 'after'
    return context


def concrete_person(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in UNKNOWN


def parameter_predicate(tool, key, default):
    # A Slack recipient is not a bank payee; an email subject is not a bank
    # transaction description. Missing tool metadata keeps v1 input compatible.
    if tool and key in {'recipient', 'amount', 'subject', 'date'} and tool not in TRANSACTION_TOOLS:
        return {'recipient': 'message.recipient', 'subject': 'message.subject'}.get(key)
    return default


def readable(value):
    labels = {'email_address': '邮箱', 'personal_interests': '爱好', 'phone_number': '电话号码',
              'identity': '对应的人', 'financial_amount': '金额', 'calendar_start_time': '开始时间',
              'calendar_end_time': '结束时间', 'event.start': '开始时间', 'event.end': '结束时间',
              'transaction.amount': '金额', 'transaction_ref': '操作的交易', 'file_ref': '操作的文件',
              'event_ref': '操作的活动', 'file_metadata': '文件名', 'document_content': '正文'}
    state = {'before': '变更前', 'after': '变更后'}.get(value['context'].get('state'), '时间未注明')
    obj = value['object'] if isinstance(value['object'], str) else json.dumps(value['object'], ensure_ascii=False)
    subject = value['subject']
    for prefix, label in [('bank:transaction:', '交易 #'), ('calendar:event:', '日历活动 #'), ('drive:file:', '云盘文件 #')]:
        if subject.startswith(prefix):
            subject = label + subject.removeprefix(prefix)
            break
    return f"{subject} 的{labels.get(value['predicate'], value['predicate'])}是 {obj}（{state}）。"


def text_assertions(text):
    """Explicit bindings only, with finite English/Chinese sentence/table forms."""
    from .inference import NEGATION
    for line in text.splitlines():
        line = line.strip().lstrip('-* ').strip()
        if not line or NEGATION.search(line):
            continue
        patterns = [
            (fr"(?P<person>{PERSON})(?:'s (?:email|e-mail)(?: address)?(?: is|:) | can be contacted at )(?P<value>{EMAIL})\.?", 'email_address'),
            (fr'(?P<person>{PERSON})\s*的(?:邮箱|电子邮件地址)(?:是|为|[:：])\s*(?P<value>{EMAIL})[。.]?', 'email_address'),
            (fr'(?P<person>{PERSON})\s*[:：]\s*(?P<value>{EMAIL})', 'email_address'),
            (fr"(?P<person>{PERSON})(?:'s (?:favorite )?hobby is| enjoys) (?P<value>[^.!\n]+)[.!]?", 'personal_interests'),
            (fr'(?P<person>{PERSON})\s*的(?:爱好|兴趣)(?:是|为|[:：])\s*(?P<value>[^。！\n]+)[。！]?', 'personal_interests'),
            (fr"(?P<person>{PERSON})'s (?:website|blog) is (?P<value>(?:https?://|www\.)[^\s]+)", 'owns_website'),
        ]
        for pattern, predicate in patterns:
            match = re.fullmatch(pattern, line, re.I)
            if match and concrete_person(match['person']):
                yield claim(match['person'].strip(), predicate, match['value'].strip())
                break
    # Name/email tables preserve row membership. A bag of names and emails is
    # deliberately not treated as a table without a labelled header.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for delimiter in (',', '|', '\t'):
        if not lines or delimiter not in lines[0]:
            continue
        rows = list(csv.reader(io.StringIO('\n'.join(lines)), delimiter=delimiter))
        rows = [[cell.strip() for cell in row] for row in rows]
        if delimiter == '|':
            rows = [[cell for cell in row if cell] for row in rows]
        header = [cell.lower() for cell in rows[0]]
        names = [i for i, name in enumerate(header) if name in {'name', '姓名', 'person'}]
        emails = [i for i, name in enumerate(header) if name in {'email', 'e-mail', '邮箱'}]
        if len(names) != 1 or len(emails) != 1:
            continue
        for row in rows[1:]:
            if len(row) != len(header):
                continue
            name, email = row[names[0]], row[emails[0]]
            if concrete_person(name) and re.fullmatch(EMAIL, email):
                yield claim(name, 'email_address', email)


def normalize_memory(memory):
    """Idempotent local normalization; pooling never manufactures local claims.

    Recompute stored v3 assertions from retained evidence, so deleting a source
    also removes assertions that depended on it. Normalization runs per receiver.
    """
    from .inference import UNVERIFIED, build_knowledge, extracted
    result = copy.deepcopy(memory)
    for receiver in result['receivers']:
        raw = [f for f in receiver['facts'] if f.get('extraction_method') != VERSION]
        usable = [f for f in raw if f.get('status') not in UNVERIFIED]
        additions = {}

        def add(value, sources, method):
            # Generic references to "a user" are kept in the original memory,
            # but are never turned into a named person's assertion.
            if not concrete_person(value['subject']):
                return
            support = sorted(set(sources))
            payload = json.dumps([value, support], ensure_ascii=False, sort_keys=True)
            fid = 'named:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]
            additions[fid] = {'fact_id': fid, 'field': 'relation', 'value': value,
                              'subject': value['subject'], 'evidence_fact_ids': support,
                              'extraction_method': VERSION, 'binding_method': method,
                              'text': readable(value)}
            times = sorted({f['observed_at'] for f in usable if f['fact_id'] in support and f.get('observed_at')})
            if times:
                additions[fid]['observed_at'] = times[-1]

        requests = defaultdict(list)
        for fact in usable:
            if fact['field'] == 'request_parameter' and fact.get('subject'):
                requests[fact['subject']].append(fact)
            if fact['field'] != 'relation':
                for value, _ in extracted(fact):
                    add(value, [fact['fact_id']], 'explicit_field_or_sentence')
            if isinstance(fact['value'], str) and fact['field'] in {
                    'request_parameter', 'message_content', 'unclassified_text', 'tool_response', 'document_content'}:
                for value in text_assertions(fact['value']):
                    # Explicit person sentences stand independently of the
                    # enclosing message's addressee or unrelated subject ID.
                    add(value, [fact['fact_id']], 'explicit_named_text')

        for request, facts in requests.items():
            paths = defaultdict(list)
            for fact in facts:
                paths[fact.get('parameter_path', '')].append(fact)
            tools = {f['tool'] for f in facts if f.get('tool')}
            tool = next(iter(tools)) if len(tools) == 1 else None
            # Ambiguous/inconsistent metadata supplies no tool-dependent link.
            if len(tools) > 1:
                continue
            for fact in paths.get('/id', []) + paths.get('/id_', []):
                if tool in ID_TOOLS and isinstance(fact['value'], (str, int)) and not isinstance(fact['value'], bool):
                    predicate, prefix = ID_TOOLS[tool]
                    add(claim(request, predicate, prefix + str(fact['value']), context_for(fact)),
                        [fact['fact_id']], 'tool_scoped_record_identifier')
            # A tool explicitly taking a person's name and email supplies a
            # binding. Search queries and unrelated fields are not such tools.
            if tool == 'invite_user_to_slack':
                for name in paths.get('/user', []):
                    for email in paths.get('/user_email', []):
                        if concrete_person(name['value']) and isinstance(email['value'], str) and re.fullmatch(EMAIL, email['value']):
                            add(claim(name['value'], 'email_address', email['value']),
                                [name['fact_id'], email['fact_id']], 'explicit_contact_parameters')
            if tool in {'send_direct_message', 'send_email'}:
                recipients = paths.get('/recipient', []) if tool == 'send_direct_message' else [
                    f for path, values in paths.items() if path.startswith('/recipients/') for f in values]
                bodies = paths.get('/body', [])
                if len(recipients) != 1:
                    continue
                recipient = recipients[0]
                for body in bodies:
                    text = body['value']
                    if not isinstance(text, str):
                        continue
                    greeting = re.match(fr'\s*(?:Hi|Hello|Dear)\s+(?P<name>{PERSON})[,!，！]', text, re.I)
                    person = recipient['value'] if tool == 'send_direct_message' else greeting['name'].strip() if greeting else None
                    if not concrete_person(person):
                        continue
                    # A greeting naming a different person is ambiguous.
                    if greeting and greeting['name'].strip() != person:
                        continue
                    support = [recipient['fact_id'], body['fact_id']]
                    if tool == 'send_email' and isinstance(recipient['value'], str) and re.fullmatch(EMAIL, recipient['value']):
                        add(claim(person, 'email_address', recipient['value']), support, 'single_addressee_and_greeting')
                    # Match an affirmative clause, preserving "your" as the
                    # addressee. Hypothetical/negated clauses are discarded.
                    from .inference import NEGATION
                    for clause in re.split(r'[.!?\n;]+', text):
                        if NEGATION.search(clause):
                            continue
                        hobby = re.search(r'\byour (?:favorite )?hobby is\s+([A-Za-z][A-Za-z -]*?)(?=\s+(?:makes|and|but|which|so)\b|$)', clause, re.I)
                        if hobby:
                            add(claim(person, 'personal_interests', hobby[1].strip()), support, 'explicit_addressee_your_hobby')
                    # Visiting a site is not proof that the addressee owns it.
                    # Keep only the personal hobby, never invent owns_website.
        # Persist the local consequences as well, e.g. bank:transaction:7 has
        # amount 1200, instead of making the stored reader follow request IDs.
        # They remain distinguished from received assertions; inference will
        # re-prove them from source facts, never trust these cached conclusions.
        local_facts = raw + [additions[key] for key in sorted(additions)]
        knowledge = build_knowledge([(receiver['receiver_id'], f) for f in local_facts])
        for cid, node in knowledge['claims'].items():
            if (cid in knowledge['initial_supports'] or knowledge['taint'][cid]
                    or node['claim']['subject'].startswith('request:')):
                continue
            for support in node['supports']:
                add(node['claim'], [fid.removeprefix('memory:') for fid in support], 'local_rule_closure')
        receiver['facts'] = raw + [additions[key] for key in sorted(additions)]
    return result
