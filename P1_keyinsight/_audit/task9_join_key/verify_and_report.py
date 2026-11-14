"""Verify the frozen inputs and recorded model outputs for the join-key pilot."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path):
    return json.loads(path.read_bytes())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def main():
    views = load(HERE / 'isolated_views.json')
    result = load(HERE / 'results.json')
    checkpoint = load(HERE / 'frozen_checkpoint.json')
    messages = load(HERE / 'messages.json')
    assert messages['original'].replace('P17', 'P82') == messages['modified']
    assert len(messages['original']) == len(messages['modified'])
    assert messages['original'].split('email ')[1] == messages['modified'].split('email ')[1]
    assert datetime.fromisoformat(checkpoint['frozen_at']) <= datetime.fromisoformat(messages['created_at'])
    for actor in ['A', 'B']:
        history = load(HERE / 'histories' / (actor + '_before.json'))
        summary = load(HERE / 'compression' / actor / 'frozen_summary.json')
        assert summary['input_sha256'] == digest(history)
        assert checkpoint['summary_sha256'][actor] == digest(summary)
        assert datetime.fromisoformat(summary['frozen_at']) <= datetime.fromisoformat(checkpoint['frozen_at'])
        assert '@' not in json.dumps(summary) and 'P82' not in json.dumps(summary)
    assert views['A_before'] == views['A_original'] == views['A_modified']
    assert views['B_original'][:-1] == views['B_modified'][:-1] == views['B_before']
    assert views['AB_original'][:-1] == views['AB_modified'][:-1] == views['AB_before']
    assert views['B_original'][-1]['text'] == messages['original']
    assert views['B_modified'][-1]['text'] == messages['modified']
    query = None
    prompt = None
    for name, documents in views.items():
        folder = HERE / 'recovery' / name
        request = load(folder / 'request.json')
        prediction = load(folder / 'prediction.json')
        response = load(folder / 'response.json')
        assert digest(request) == prediction['request_sha256']
        payload = json.loads(request['messages'][1]['content'])
        assert payload['visible_documents'] == documents
        assert set(payload) == {'query', 'visible_documents'}
        query = query or payload['query']
        prompt = prompt or request['messages'][0]['content']
        assert query == payload['query'] and prompt == request['messages'][0]['content']
        assert all(s not in json.dumps(query) for s in ['P17', 'P82', 'john', '@'])
        raw = json.loads(response['choices'][0]['message']['content'])
        assert raw == {k: prediction[k] for k in ['email', 'evidence_ids', 'supported_chain']}
        assert result['results'][name]['request_sha256'] == digest(request)
    assert result['results']['AB_original']['email'] == 'john.mitchell@gmail.com'
    assert result['results']['AB_modified']['email'] is None
    assert all(result['results'][name]['email'] is None for name in ['A_original', 'B_original', 'AB_before'])
    proof = result['results']['AB_original']['evidence_ids']
    assert any(p.startswith('A:') for p in proof) and any(p.startswith('B:') for p in proof)
    checks = {'frozen_before_new_message': True, 'identical_histories': True,
              'only_join_key_changed_email_unchanged': True, 'same_prompt_and_query': True,
              'no_gold_email_or_join_key_in_query': True, 'local_inputs_are_physically_separate': True,
              'answers_match_recorded_model_outputs': True, 'joint_proof_uses_both_agents': True,
              'original_joint_recovers_modified_joint_abstains': True}
    (HERE / 'verification.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    lines = ['# task9：P标识匹配与篡改对照', '',
        '这是按“会议—P / P—邮箱”结构改编的受控对照，使用task9的介绍会议和John邮箱；P11、P17、P23为新增实验标识，不是原始日志中的字段。',
        '目标为2024年5月15日介绍会议（编号24）中第2条参与者记录的邮箱；查询不提供P或邮箱。', '',
        '## 新消息之前的执行历史', '',
        'A观察到会议24：第1条参与者P11，第2条P17，第3条P23；没有任何邮箱。',
        'B只知道联系人目录请求待返回，没有会议信息，也没有参与者ID与邮箱。', '',
        '## 消息前压缩并冻结的记忆', '']
    for actor in ['A', 'B']:
        lines += [f'### agent {actor}', '']
        lines += [f'{i}. {s}' for i, s in enumerate(result['summaries'][actor]['facts'], 1)]
        lines += ['']
    lines += ['## 原消息与篡改消息', '', '原消息（发给B）：', '',
              '```text', messages['original'], '```', '', '篡改消息（发给B）：', '',
              '```text', messages['modified'], '```', '',
              '只替换P17为P82，邮箱和消息格式、长度均保持一致。', '',
              '## 恢复目标会议参与者邮箱', '',
              '| 视角 | 新消息之前 | 原消息P17到达后 | 篡改消息P82到达后 |',
              '|---|---|---|---|',
              '| A单独 | 无邮箱 | 无邮箱，无法恢复 | 无邮箱，无法恢复 |',
              '| B单独 | 无记录 | 知道P17邮箱，但不知道P17是否参加目标会议，无法恢复 | 知道P82邮箱，但不知道P82是否参加目标会议，无法恢复 |',
              '| A+B联合 | 无法恢复 | 会议24第2条→P17→john.mitchell@gmail.com，恢复成功 | 会议24第2条→P17；B只有P82→邮箱，连接断开，无法恢复 |', '',
              '匹配时恢复器引用A摘要和B新消息，篡改后返回email=null，未因邮箱仍在输入中就将其归到目标会议参与者名下。', '',
              '## 联合恢复原始输出', '']
    for name in ['AB_before', 'AB_original', 'AB_modified']:
        lines += [name, '', '```json', json.dumps(result['results'][name], ensure_ascii=False, indent=2), '```', '']
    lines += ['## 一句话分析', '',
              '本轮只有P一致时才能将会议与邮箱关联，格式相同但P不同会切断连接，联合恢复随之失败。', '',
              f"模型为deepseek-flash；Mem0压缩调用{result['compression_calls']}次，恢复调用{result['recovery_calls']}次；两组共用新消息之前冻结的摘要。", '',
              '原始task9日志保持不变；输入、摘要、模型请求和响应及校验记录位于`_audit/task9_join_key/`。', '']
    output = ROOT / 'P1_keyinsight/task9_P标识匹配与篡改实验.md'
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(checks))
    print(str(output))


if __name__ == '__main__':
    main()
