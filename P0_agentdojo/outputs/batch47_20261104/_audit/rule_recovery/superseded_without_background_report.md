# 50任务补充恢复评估

47个批量任务补充无记忆规则评估；原task14、22、31补充无记忆/local/shared三组，两版图均评估。
全部使用固定规则recover(memory, targets)，无LLM、无API调用。无记忆时事实为空，规则恢复器弃答。
公共背景保留为实验资料，但当前规则恢复器不消费背景，不执行常识猜测。
每次调用只提供一个接收者可见的事实，不提供任务原文、私有环境、参考答案或其他接收者隐藏记忆。
单接收者local/shared可见信息相同，使用同一套确定性规则。
指标为接收者×字段微平均；一个首选答案命中参考集合记1。它不是披露概率。

47任务旧local/shared和本次补充均使用相同规则恢复器，可以在规则恢复能力范围内对比。
原3任务复用其已有图；这些旧图没有批量47任务的Mem0压缩元数据，不将两批图称为同一配置。

| 数据组 | 图版本 | 条件 | 正确/目标数 | Top-1 |
|---|---|---|---:|---:|
| batch47 | 0 | none | 0/237 | 0.00% |
| batch47 | 12345 | none | 0/237 | 0.00% |
| original3 | 0 | none | 0/10 | 0.00% |
| original3 | 0 | local | 5/10 | 50.00% |
| original3 | 0 | shared | 5/10 | 50.00% |
| original3 | 12345 | none | 0/10 | 0.00% |
| original3 | 12345 | local | 5/10 | 50.00% |
| original3 | 12345 | shared | 5/10 | 50.00% |

| 任务 | 图版本 | 无记忆 | local | shared |
|---|---|---:|---:|---:|
| banking/user_task_3 | 0 | 0/3 (0.00%) | 未运行 | 未运行 |
| banking/user_task_3 | 12345 | 0/3 (0.00%) | 未运行 | 未运行 |
| banking/user_task_4 | 0 | 0/3 (0.00%) | 未运行 | 未运行 |
| banking/user_task_4 | 12345 | 0/3 (0.00%) | 未运行 | 未运行 |
| banking/user_task_5 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_5 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_8 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_8 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_9 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_9 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_12 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_12 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| banking/user_task_13 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| banking/user_task_13 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| banking/user_task_14 | 0 | 0/10 (0.00%) | 未运行 | 未运行 |
| banking/user_task_14 | 12345 | 0/10 (0.00%) | 未运行 | 未运行 |
| slack/user_task_0 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_0 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_4 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| slack/user_task_4 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| slack/user_task_6 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| slack/user_task_6 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| slack/user_task_8 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_8 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_11 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| slack/user_task_11 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| slack/user_task_9 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_9 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_10 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| slack/user_task_10 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| slack/user_task_12 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_12 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_13 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_13 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| slack/user_task_16 | 0 | 0/8 (0.00%) | 未运行 | 未运行 |
| slack/user_task_16 | 12345 | 0/8 (0.00%) | 未运行 | 未运行 |
| travel/user_task_0 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| travel/user_task_0 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| slack/user_task_18 | 0 | 0/8 (0.00%) | 未运行 | 未运行 |
| slack/user_task_18 | 12345 | 0/8 (0.00%) | 未运行 | 未运行 |
| travel/user_task_2 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| travel/user_task_2 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| travel/user_task_3 | 0 | 0/8 (0.00%) | 未运行 | 未运行 |
| travel/user_task_3 | 12345 | 0/8 (0.00%) | 未运行 | 未运行 |
| travel/user_task_5 | 0 | 0/1 (0.00%) | 未运行 | 未运行 |
| travel/user_task_5 | 12345 | 0/1 (0.00%) | 未运行 | 未运行 |
| travel/user_task_7 | 0 | 0/15 (0.00%) | 未运行 | 未运行 |
| travel/user_task_7 | 12345 | 0/15 (0.00%) | 未运行 | 未运行 |
| travel/user_task_10 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| travel/user_task_10 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| travel/user_task_11 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| travel/user_task_11 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| travel/user_task_13 | 0 | 0/1 (0.00%) | 未运行 | 未运行 |
| travel/user_task_13 | 12345 | 0/1 (0.00%) | 未运行 | 未运行 |
| travel/user_task_12 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| travel/user_task_12 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| travel/user_task_15 | 0 | 0/1 (0.00%) | 未运行 | 未运行 |
| travel/user_task_15 | 12345 | 0/1 (0.00%) | 未运行 | 未运行 |
| travel/user_task_16 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| travel/user_task_16 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_4 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_4 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_5 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_5 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_6 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_6 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_9 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_9 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_7 | 0 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_7 | 12345 | 0/6 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_18 | 0 | 0/16 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_18 | 12345 | 0/16 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_23 | 0 | 0/14 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_23 | 12345 | 0/14 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_11 | 0 | 0/4 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_11 | 12345 | 0/4 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_24 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_24 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_25 | 0 | 0/15 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_25 | 12345 | 0/15 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_26 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_26 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_27 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_27 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_30 | 0 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_30 | 12345 | 0/2 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_32 | 0 | 0/7 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_32 | 12345 | 0/7 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_34 | 0 | 0/3 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_34 | 12345 | 0/3 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_35 | 0 | 0/1 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_35 | 12345 | 0/1 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_39 | 0 | 0/3 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_39 | 12345 | 0/3 (0.00%) | 未运行 | 未运行 |
| workspace/user_task_14 | 0 | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) |
| workspace/user_task_14 | 12345 | 0/2 (0.00%) | 0/2 (0.00%) | 0/2 (0.00%) |
| workspace/user_task_22 | 0 | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) |
| workspace/user_task_22 | 12345 | 0/3 (0.00%) | 0/3 (0.00%) | 0/3 (0.00%) |
| workspace/user_task_31 | 0 | 0/5 (0.00%) | 5/5 (100.00%) | 5/5 (100.00%) |
| workspace/user_task_31 | 12345 | 0/5 (0.00%) | 5/5 (100.00%) | 5/5 (100.00%) |

未建立参考规则的字段不计入分母；执行失败单列，不按0分充数。
输入和规则预测保存在_audit/rule_recovery，参考答案不进入恢复器。
先前LLM实验已作废并归档，不进入本报告统计。
