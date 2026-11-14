"""Create a NEW worksheet from the user's current CSV, preserving every cell.

Append execution-agent observations and review columns; never overwrite the
input worksheet or any previously generated continuation.
"""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path

from export_memories import HERE, ROOT

DEFAULT_SOURCE = ROOT / 'P1_keyinsight/50任务_合并基线_含工具返回_自然语言填写表.csv'
DEFAULT_OUTPUT = ROOT / 'P1_keyinsight/50任务_合并基线_含工具返回_继续标注版.csv'


def agent_text(agent):
    actor = agent['agent_id']
    lines = [f'我是执行 agent {actor}，不是表中用同一字母标记的业务接收者。',
             '以下列出我实际收到的工具返回及其他agent消息；原有完整活动上下文仍由执行日志保存。']
    if not agent['tool_observations']:
        lines.append('我没有直接收到原生工具返回；不能据此认为我没有收到其他agent提供的报告。')
    for i, observation in enumerate(agent['tool_observations'], 1):
        lines.append(f'第{i}次工具返回（{observation["tool"]}，事件{observation["event_id"]}）：')
        lines.append(('返回错误：' if observation['error'] is not None else '实际收到的内容：') + '\n' + observation['content'])
    for message in agent['received_agent_messages']:
        lines.append(f'来自执行 agent {message["source"]} 的消息（事件{message["event_id"]}）：\n{message["content"]}')
    return '\n'.join(lines)


def main(source, output):
    if output.exists() or output.resolve() == source.resolve():
        raise FileExistsError('Refusing to overwrite an existing worksheet: ' + str(output))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with source.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        headers, original = list(reader.fieldnames), list(reader)
    if len(original) != 50 or len({r['task编号'] for r in original}) != 50:
        raise ValueError('Expected exactly the existing 50 task rows')
    extra = ['本版系统核查提示', '执行agent A实际收到的记忆（自然语言）',
             '执行agent B实际收到的记忆（自然语言）', '完整执行agent自然语言记忆文件',
             '你继续填写：核查结论', '你继续填写：核查说明']
    if set(extra) & set(headers):
        raise ValueError('Continuation columns already exist; choose a fresh base worksheet')
    manifest = json.loads((HERE / 'manifest.json').read_bytes())
    rows = []
    for source_row in original:
        row = copy.deepcopy(source_row)
        key = row['task编号']
        name = key.replace('/', '_')
        execution = json.loads((HERE / 'execution_memories' / (name + '.json')).read_bytes())
        memory = json.loads((HERE / 'receiver_memories' / (name + '.json')).read_bytes())
        paths = []
        for agent in execution['agents']:
            text = agent_text(agent)
            target = HERE / 'readable' / name / f'execution_agent_{agent["agent_id"]}.txt'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + '\n', encoding='utf-8')
            preview = text if len(text) <= 24000 else text[:23500] + '\n【本单元格仅显示预览，完整记忆见】\n' + str(target.relative_to(ROOT))
            row[f'执行agent {agent["agent_id"]}实际收到的记忆（自然语言）'] = preview
            paths.append(str(target.relative_to(ROOT)))
        row['完整执行agent自然语言记忆文件'] = '\n'.join(paths)
        count = manifest['tasks'][key]['tool_responses']
        row['本版系统核查提示'] = (
            f'已将本任务{count}次真实工具返回纳入系统记忆；服务只保留自己的返回，执行agent只保留实际送达自己的返回与消息。'
            '原表全部单元格与人工调整逐字保留；服务接收者A/B/C/D与执行agent A/B是不同角色。'
            '原有“你填写”栏可继续填写；新增核查栏留空。此前仅请求视角下的0%结果尚未重算，不能当作新版结果。')
        empty = [r['receiver_id'] for r in memory['receivers'] if not r['facts']]
        if not empty:
            row['本版系统核查提示'] += ' 当前各方导出记忆均有事实；若旧提示仍说某方记忆为空，应以本版记忆文件为准。'
        else:
            row['本版系统核查提示'] += ' 当前仍为空的接收者：' + '、'.join(empty) + '。'
        rows.append(row)
    with output.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=headers + extra, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    with output.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        saved = list(reader)
        assert reader.fieldnames[:2] == ['task原文', 'task中文翻译']
    assert len(saved) == 50
    assert all(new[h] == old[h] for new, old in zip(saved, original) for h in headers)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    proof = {'source': str(source.relative_to(ROOT)), 'source_sha256': before,
             'output': str(output.relative_to(ROOT)), 'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
             'task_count': 50, 'original_columns_preserved': headers, 'appended_columns': extra,
             'every_original_cell_preserved': True, 'source_file_unchanged': True}
    (HERE / 'continued_worksheet_manifest.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    main(args.source.resolve(), args.output.resolve())
