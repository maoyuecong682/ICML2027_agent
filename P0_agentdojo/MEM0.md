# task_31 执行记忆压缩

使用真实 Mem0（mem0ai 1.0.5）的 `Memory.add(infer=True)` 完成事实提取、记忆操作整理，再以 `get_all` 取回本 agent 的全部记忆。提取和整理均调用 DeepSeek 的 `deepseek-flash`，关闭 thinking；每个 agent 两次模型调用，有请求、响应与 usage 审计。

## 本轮输出

目录：`outputs/mem0_20261028/workspace_user_task_31/`。

- `A/执行记忆_压缩后.json`：A 在读取云盘文件之后、向 B 报告之前的消息快照。
- `B/执行记忆_压缩后.json`：B 收到 A 报告之后、创建文件之前的消息快照。
- 各 agent 目录内同时有 `执行记忆_压缩前.json`、`同一信息块_前后对照.json`、`mem0_facts.json`、`compression_api.jsonl`、Qdrant 本地数据库和 SQLite 历史。
- `压缩报告.json`：大小、保留检查、来源哈希、模型调用指标和未验证事项。

两个 agent 的检查点不同，不能把它们理解为同一时刻的全局状态。每个 agent 仅处理自己当时看到的信息，分别存储，未读取未来披露内容。只替换最后一条工具返回的正文，保留系统提示、用户任务、调用参数和调用 ID。没有改写原始运行、接收者记忆或现有隐私分析产物，也没有重建已回收的隐私图。

## 隐私保留的具体范围

压缩结果 = Mem0 提炼的事实 + 确定性保护块。保护块保存当时上下文中的 vacation-plans.docx 原文、人物—目的地—日期关联、六项打包物品。保护块不是声称由 Mem0 自动生成的关系图，也不是依据后续披露信息倒灌的记忆。

大小以完整 messages 的紧凑 JSON 的 UTF-8 字节数统计，包含保护块，不能当作精确 DeepSeek token 或磁盘总占用。保留原始文件、数据库和审计记录意味着本轮并不减少磁盘总占用。A：30711→3786 字节（减少 87.67%）；B：5547→4150 字节（减少 25.18%）。

本轮仅保证受保护行程信息与工具消息协议保留；未承诺保留被省略的其他文件中的所有隐私，未重新运行隐私拉取器，也未用压缩上下文续跑 AgentDojo。因此尚不能证明全局隐私判断、任务成功率均不受影响。

本地向量使用 256 维词项哈希，具有真实的词项区分能力，但不是语义嵌入模型。它用于满足本轮 Mem0 存储接口；新建隔离记忆库后整库取回，不进行 top-k 语义检索实验。后续长程检索需要单独评估嵌入与召回。没有接入 Mem0 图存储。

## 复现

独立环境 `.venv_mem0`，避免改变 AgentDojo 的 `.venv`。依赖入口 `requirements-mem0.txt`，本轮实际环境锁定在 `requirements-mem0.lock.txt`。

```powershell
# 在环境变量中配置 DEEPSEEK_API_KEY；脚本和交付物中不保存凭据。
.venv_mem0\Scripts\python.exe -B mem0_compress.py --output outputs/mem0_repeat/workspace_user_task_31
.venv_mem0\Scripts\python.exe -B -m unittest tests.test_mem0_compress -v
```

输出目录必须不存在，防止覆盖既有结果。本轮失败的初始化尝试保存在 `outputs/mem0_20261028/setup_attempt_01/`，当时尚未调用模型；正式结果仅在 `workspace_user_task_31/`。

Mem0 1.0.5 的配置校验器枚举了固定嵌入供应商，因此脚本对自定义 local_hash 配置使用 `model_construct` 并向工厂注册真实实现；没有伪装成 OpenAI embedding 或使用恒定 mock 向量。Mem0 自带 DeepSeek 适配器的接口由审计适配器替换，以显式传入 JSON 响应要求、thinking 选项和保存调用记录，事实与记忆操作算法仍由 Mem0 执行。
