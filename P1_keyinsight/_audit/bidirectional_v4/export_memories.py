"""Rebuild the existing 50 tasks' memories from recorded requests AND returns.

Offline export only: no task rerun, model call, environment/gold access, or
rewriting of v1-v3 evidence/results. Source hashes are checked after export.
"""
import copy
import argparse
import csv
import hashlib
import json
import socket
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'P0_agentdojo'))

from p0_privacy.recovery import memory_from_graph, validate
from p0_privacy.recovery_supplement import load_jobs
from p0_privacy.response_memory import VERSION, attach_tool_responses, parse_response

SOURCE_CSV = ROOT / 'P1_keyinsight/50任务_合并基线_自然语言填写表.csv'
OUTPUT_CSV = ROOT / 'P1_keyinsight/50任务_合并基线_含工具返回_自然语言填写表.csv'
LABELS = {
    'name': '姓名', 'first_name': '名字', 'last_name': '姓氏', 'email': '邮箱', 'street': '街道', 'city': '城市',
    'sender': '发送者', 'recipient': '接收方', 'recipients': '接收方', 'subject': '主题或说明',
    'body': '正文', 'content': '正文', 'filename': '文件名', 'id': '编号', 'id_': '编号',
    'amount': '金额', 'balance': '余额', 'date': '日期', 'recurring': '是否周期性执行',
    'start_time': '开始时间', 'end_time': '结束时间', 'location': '地点', 'participants': '参与者',
    'title': '标题', 'description': '描述', 'timestamp': '时间', 'channel': '频道', 'user': '用户',
    'file_path': '文件路径', 'file_id': '文件编号', 'query': '检索词', 'n': '查询条数',
    'hotel_names': '酒店', 'hotel_name': '酒店', 'restaurant_names': '餐厅', 'company_name': '公司',
    'url': '网址', 'permission': '权限', 'shared_with': '共享对象及权限', 'owner': '所有者',
    'size': '大小', 'last_modified': '最后修改时间', 'status': '状态', 'read': '是否已读',
    'attachments': '附件', 'cc': '抄送', 'bcc': '密送',
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readable(value):
    if isinstance(value, dict):
        return '\n'.join(f'{LABELS.get(k, k)}：{readable(v)}' for k, v in value.items())
    if isinstance(value, list):
        if not value:
            return '空列表（没有返回条目）'
        return '\n'.join(f'第{i}项：{readable(v)}' for i, v in enumerate(value, 1))
    if value is None:
        return '空值'
    return str(value)


def receiver_text(receiver, graph):
    rid = receiver['receiver_id']
    record = next(r for r in graph['receiver_memory'] if r['receiver_id'] == rid)
    responses = {r['event_id']: r for r in record['produced_responses']}
    lines = ['我保留向我发来的请求，也保留我在处理这些请求时实际返回的内容。',
             '以下是本服务自己的观察记录；不包含其他服务的返回，也不代表覆盖本服务全部既有资料。']
    for i, q in enumerate(record['received_requests'], 1):
        lines.append(f'第{i}次操作（{q["tool"]}）：')
        lines.append('收到的请求信息：\n' + (readable(q['parameters']) if q['parameters'] else '未附带参数。'))
        response = responses.get(q['event_id'])
        if response is None:
            lines.append('日志未记录返回内容，不能据此认定查询成功、失败或结果为空。')
        elif response['error'] is not None:
            lines.append('实际返回的是错误信息，不是查询到的资料：\n' + response['content'])
        else:
            lines.append(f'我向执行 agent {response["agent_id"]} 返回的内容：\n' + readable(parse_response(response['content'])))
    return '\n'.join(lines)


def main(output_csv=OUTPUT_CSV):
    if output_csv.exists():
        raise FileExistsError('Refusing to overwrite an annotation worksheet: ' + str(output_csv))
    jobs = load_jobs()
    assert len(jobs) == 50
    with SOURCE_CSV.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        headers, source_rows = list(reader.fieldnames), list(reader)
    by_key = {r['task编号']: r for r in source_rows}
    assert set(by_key) == set(jobs)
    sources = [SOURCE_CSV,
               ROOT / 'P0_agentdojo/outputs/batch47_20261104/47任务双版本隐私图.json',
               ROOT / 'P0_agentdojo/outputs/graphiti_privacy/任务隐私图.json']
    sources += [j['environment_path'].with_name('graph.json') for j in jobs.values()]
    sources += list((HERE.parent / 'reasoning_v3/memories').glob('*.json'))
    before = {p: sha(p) for p in sources}
    rows, tasks, totals = [], {}, Counter()
    for key, job in sorted(jobs.items(), key=lambda item: (item[0].split('/')[0], int(item[0].rsplit('_', 1)[-1]))):
        name = key.replace('/', '_')
        trace_path = job['environment_path'].with_name('graph.json')
        trace = json.loads(trace_path.read_bytes())
        graph = attach_tool_responses(job['versions']['0'], trace)
        memory = memory_from_graph(graph, shared=False)
        validate(memory, [])
        response_nodes = [n for n in graph['nodes'] if n['type'] == 'tool_response']
        source_events = {n['id']: n for n in trace['nodes'] if n['type'] == 'TOOL'}
        assert len(response_nodes) == len(source_events)
        for response in response_nodes:
            payload = source_events[response['event_id']]['payload']
            assert response['content'] == payload['delivered_content']
            assert not response['counts_as_incoming_disclosure']
        memory_path = HERE / 'receiver_memories' / (name + '.json')
        execution_path = HERE / 'execution_memories' / (name + '.json')
        dump(memory_path, memory)
        dump(execution_path, graph['execution_memory'])
        row = copy.deepcopy(by_key[key])
        full_views = []
        for i, receiver in enumerate(memory['receivers']):
            rid = receiver['receiver_id']
            local = {**copy.deepcopy(memory), 'receivers': [copy.deepcopy(receiver)], 'sharing_groups': []}
            validate(local, [])
            local_path = HERE / 'local_memories' / name / (rid.rsplit(':', 1)[-1] + '.json')
            dump(local_path, local)
            expected = {n['event_id']: n['content'] for n in response_nodes if n['receiver_id'] == rid}
            actual = {f['event_id']: f['value'] for f in receiver['facts'] if f['field'] == 'tool_response'}
            assert expected == actual
            text = receiver_text(receiver, graph)
            view_path = HERE / 'readable' / name / (rid.rsplit(':', 1)[-1] + '.txt')
            view_path.parent.mkdir(parents=True, exist_ok=True)
            view_path.write_text(text + '\n', encoding='utf-8')
            # Excel has a 32767-character cell limit. Full knowledge remains in
            # JSON/TXT; previews are explicitly labelled, never silently cut.
            preview = text if len(text) <= 24000 else (text[:23500] +
                '\n【此单元格仅显示前23500字；完整视角见】\n' + str(view_path.relative_to(ROOT)))
            row[f'接收者{"ABCD"[i]}当前视角（自然语言）'] = preview
            full_views.append(str(view_path.relative_to(ROOT)))
            totals['local_receiver_memories'] += 1
            totals['receiver_facts'] += len(receiver['facts'])
        for agent in graph['execution_memory']['agents']:
            expected = [n for n in source_events.values() if n['payload']['target'] == agent['agent_id']]
            assert [n['event_id'] for n in agent['tool_observations']] == [n['id'] for n in expected]
            totals['execution_tool_observations'] += len(expected)
        row['原始记忆文件'] = str(memory_path.relative_to(ROOT))
        row['执行记忆文件'] = str(execution_path.relative_to(ROOT))
        row['完整接收者自然语言视角文件'] = '\n'.join(full_views)
        row['填写规则'] += (
            ' 本版已加入本服务实际返回的内容；返回不算agent向服务新增披露。'
            '长视角在CSV中明确标为预览，完整正文保存在TXT与JSON。旧版请求侧视角及评估结果不覆盖。')
        row['当前结构与填写提示'] += ' 本版已包含工具返回，请基于完整知识重新判断；尚未重跑隐私恢复指标。'
        rows.append(row)
        totals['tasks'] += 1
        totals['service_tool_responses'] += len(response_nodes)
        totals['tool_errors'] += sum(n['error'] is not None for n in response_nodes)
        tasks[key] = {'execution_source': str(trace_path.relative_to(ROOT)),
                      'receiver_memory': str(memory_path.relative_to(ROOT)),
                      'execution_memory': str(execution_path.relative_to(ROOT)),
                      'receivers': len(memory['receivers']), 'tool_responses': len(response_nodes)}
    headers += ['执行记忆文件', '完整接收者自然语言视角文件']
    with output_csv.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    with output_csv.open(encoding='utf-8-sig', newline='') as handle:
        saved = list(csv.DictReader(handle))
    assert len(saved) == 50
    assert all(r['task原文'] == by_key[r['task编号']]['task原文'] for r in saved)
    assert all(r['task中文翻译'] == by_key[r['task编号']]['task中文翻译'] for r in saved)
    assert all(sha(p) == digest for p, digest in before.items())
    report = {'schema': VERSION, 'scope': 'existing 50/97 tasks; offline tool-return memory export',
              'new_api_calls': 0, 'new_task_executions': 0, 'privacy_scores_recomputed': False,
              'source_files_unchanged': True, 'totals': dict(totals), 'tasks': tasks,
              'source_sha256': {str(p.relative_to(ROOT)): digest for p, digest in before.items()},
              'worksheet': str(output_csv.relative_to(ROOT)),
              'response_semantics': 'own produced response knowledge, not new incoming disclosure',
              'state_semantics': 'before only for reads preceding any observed write to that service; otherwise after',
              'limitations': 'Observed knowledge only; no claim of complete pre-existing service knowledge. '
                             'Structured projection covers explicit known record shapes; raw returns are retained for all tools.'}
    dump(HERE / 'manifest.json', report)
    print(json.dumps({'output': str(output_csv), **dict(totals), 'source_files_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worksheet-output', type=Path, default=OUTPUT_CSV)
    args = parser.parse_args()
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('Offline export: network forbidden')):
        main(args.worksheet_output.resolve())
