# AgentDojo recipient adapter

完整任务目录见 [任务基本信息与接收者.json](outputs/任务基本信息与接收者.json)。单一文件合并 97 个任务的原文、难度、执行状态、类别与接收者数组：94 个未执行任务依据官方 `ground_truth` 在独立本地环境中的参考流程解析，3 个已执行任务依据原 TOOL 轨迹解析。`resolution_basis` 区分两者；`receivers[].evidence` 引用逐步工具证据，并区分模拟投递、权限、计划收款和仅有预订目标等状态。参考流程不保证覆盖模型将来采用的所有路径，运行时仍需按实际调用解析。原披露文件及其哈希引用保持原样，目录只合并基本元数据，不复制标注和原始记忆。

生成目录（本地参考工具执行，无模型或网络调用，只输出一个 JSON）：

```powershell
cd P0_agentdojo
.\.venv\Scripts\python.exe -B -X utf8 -m p0_privacy.recipient_catalog
```

`p0_privacy/recipients.py` 是本框架新增的确定性适配器，不是 AgentDojo 自带的通用隐私接收者判定 API。

输入为真实 `graph.json` 的 TOOL 事件（工具名、请求参数、执行错误、事件 ID），以及已安装 AgentDojo v1.2 suite 中注册的 `Function.dependencies` 和工具实现。TOOL.payload.target 表示响应回到哪个 agent，不能直接作为请求接收者。工具返回正文不复制成服务的新接收记忆。

输出包含逐事件的 `receipts`（服务接收请求）、`destinations`（明确的下游地址或用户）、解析状态、代码路径/行号/哈希和事件证据。`receivers`、`disclosures` 直接适配原隐私记忆与标注输入格式。接收者标识命名和业务边界仍是本实验约定，具体工具选择及地址不再按任务编号指定。

`p0_privacy.build.read_tasks()` 已默认使用适配器处理三个已有执行任务。CSV 只继续提供历史任务元数据与未执行任务的静态候选；未执行候选明确标为 `legacy_static_candidate_not_observed`。已有数据文件未覆盖，新构建才会使用新解析逻辑。

当前覆盖云盘请求、邮件请求及 Slack 私信的服务身份；邮件 recipients/cc/bcc、私信 recipient、共享 email 另行输出下游对象。共享成功只表示授权，不表示阅读。失败调用不记为已向下游成功投递。下游对象的内容记忆投影尚未接入：不会把整个服务请求（例如 BCC 列表）交给每个收件人。既有文件修改涉及 ACL 时标为 partial；尚未支持的工具标为 unresolved，构建遇到不完整解析会停止，不回退到人工任务编号映射。

task31 的两次真实 TOOL 分别是 e0004 `list_files({})` 与 e0008 `create_file(filename, content)`，均依赖 `cloud_drive`，输出唯一服务接收者 `app:workspace:drive`，下游对象为空。接收者已有知识未建模；判定其为请求接收者不等于证明它获得了新知识或发生不当泄露。A/B 在当前业务出口边界外。

复现（项目根目录，无模型调用，无任务重跑）：

```powershell
.\.venv\Scripts\python.exe -B -m p0_privacy.recipients --task workspace/user_task_31 --output outputs/recipient_resolution_20261102/workspace_user_task_31.json
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_recipients.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_privacy.py -v
```
