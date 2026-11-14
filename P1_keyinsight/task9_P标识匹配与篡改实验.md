# task9：P标识匹配与篡改对照

这是按“会议—P / P—邮箱”结构改编的受控对照，使用task9的介绍会议和John邮箱；P11、P17、P23为新增实验标识，不是原始日志中的字段。
目标为2024年5月15日介绍会议（编号24）中第2条参与者记录的邮箱；查询不提供P或邮箱。

## 新消息之前的执行历史

A观察到会议24：第1条参与者P11，第2条P17，第3条P23；没有任何邮箱。
B只知道联系人目录请求待返回，没有会议信息，也没有参与者ID与邮箱。

## 消息前压缩并冻结的记忆

### agent A

1. Observed record from source event adapted_calendar_read: event_id 24, title "Introductory meeting", date 2024-05-15, start_time 15:00, end_time 16:30, location "Meeting Room 2".
2. System instruction to the agent: store only observed meeting records.
3. Observed participant records from adapted_calendar_read for event_id 24: participant_id P11 in slot 1, participant_id P17 in slot 2, participant_id P23 in slot 3.
4. User requested participant records for the Introductory meeting on 2024-05-15.

### agent B

1. An assistant message stated the directory request is pending and no participant identifier or email has arrived (event ID: adapted_directory_request).
2. Actor B received a system message stating participant-directory entries are provided and no meeting record was provided (event ID: adapted_directory_request).
3. A user message instructed to wait for the next participant-directory entry (event ID: adapted_directory_request).

## 原消息与篡改消息

原消息（发给B）：

```text
Participant P17 has email john.mitchell@gmail.com.
```

篡改消息（发给B）：

```text
Participant P82 has email john.mitchell@gmail.com.
```

只替换P17为P82，邮箱和消息格式、长度均保持一致。

## 恢复目标会议参与者邮箱

| 视角 | 新消息之前 | 原消息P17到达后 | 篡改消息P82到达后 |
|---|---|---|---|
| A单独 | 无邮箱 | 无邮箱，无法恢复 | 无邮箱，无法恢复 |
| B单独 | 无记录 | 知道P17邮箱，但不知道P17是否参加目标会议，无法恢复 | 知道P82邮箱，但不知道P82是否参加目标会议，无法恢复 |
| A+B联合 | 无法恢复 | 会议24第2条→P17→john.mitchell@gmail.com，恢复成功 | 会议24第2条→P17；B只有P82→邮箱，连接断开，无法恢复 |

匹配时恢复器引用A摘要和B新消息，篡改后返回email=null，未因邮箱仍在输入中就将其归到目标会议参与者名下。

## 联合恢复原始输出

AB_before

```json
{
  "email": null,
  "evidence_ids": [],
  "supported_chain": [],
  "request_sha256": "5251c1323824d5ad49d21e5892caab9db20a4445541896963c0ef91b40c349b3",
  "finished_at": "2026-11-14T07:55:18.955461+00:00",
  "correct": false,
  "join_check": {
    "meeting_to_P17": true,
    "P17_to_email": false,
    "complete_supported_path": false
  }
}
```

AB_original

```json
{
  "email": "john.mitchell@gmail.com",
  "evidence_ids": [
    "A:summary:3",
    "B:new_directory_entry"
  ],
  "supported_chain": [
    {
      "subject": "event_id 24",
      "relation": "has participant record slot 2",
      "object": "P17"
    },
    {
      "subject": "P17",
      "relation": "has email",
      "object": "john.mitchell@gmail.com"
    }
  ],
  "request_sha256": "55274d2ba7455f88243ca1071d817ac242ed83c9fa3ddf8a82b86dee0b332a76",
  "finished_at": "2026-11-14T07:55:22.939089+00:00",
  "correct": true,
  "join_check": {
    "meeting_to_P17": true,
    "P17_to_email": true,
    "complete_supported_path": true
  }
}
```

AB_modified

```json
{
  "email": null,
  "evidence_ids": [],
  "supported_chain": [],
  "request_sha256": "dbd9d9e34385edc69faabf4a785935d4c507d5c89dbac4a66f710ce619227639",
  "finished_at": "2026-11-14T07:55:26.666962+00:00",
  "correct": false,
  "join_check": {
    "meeting_to_P17": true,
    "P17_to_email": false,
    "complete_supported_path": false
  }
}
```

## 一句话分析

本轮只有P一致时才能将会议与邮箱关联，格式相同但P不同会切断连接，联合恢复随之失败。

模型为deepseek-flash；Mem0压缩调用4次，恢复调用9次；两组共用新消息之前冻结的摘要。

原始task9日志保持不变；输入、摘要、模型请求和响应及校验记录位于`_audit/task9_join_key/`。
