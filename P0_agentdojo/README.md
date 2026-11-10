# P0 AgentDojo 工作区

独立的双 agent 实现：A 读取数据，B 请求信息、执行写操作并作答。两个角色均使用 DeepSeek `deepseek-flash`，显式关闭思考模式。原始任务交给 AgentDojo 官方入口执行与评估。

实际抽样、结果与三个任务的 JSON/PNG 见 [P0.md](P0.md)。

任务级隐私图构建已固定接入 Graphiti：`python -m p0_privacy` 从既有真实运行构建实体关系、接收者证据、隐私属性与 AND 推断因子；默认生成 task14、task22、task31，完整构建 `python -m p0_privacy.build` 也会执行此阶段。图简化尚未应用，接收者知识合并仍是独立可选模块。依赖、数据库配置与复现步骤见 [隐私图架构](p0_privacy/README.md#graphiti-任务级隐私图固定架构)。

本机交付的 `.venv` 已可直接运行：基础环境从已验证的 CPython 3.12 环境物理复制，并补入同版本 Python 的 Pillow；没有连接旧工作区的 `.pth` 或符号链接。现已安装 Graphiti 构图依赖，组合环境共 95 个包，通过 `uv pip check`。初始环境记录见 [environment.bootstrap.json](environment.bootstrap.json)，当前完整环境使用下方的组合锁文件重建。

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r p0_privacy/requirements.lock.txt
$env:DEEPSEEK_API_KEY = '<your-key>'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m p0.run --run-id new_run --seed 20261028
```

密钥从环境读取，不写入工作区。运行目录不允许覆盖。`--sample-only` 仅固定抽样，不调用 API。

`p0/pipeline.py` 为 LangGraph 协作和 AgentDojo 适配；`policy.py` 为四套任务的显式工具权限；`backend.py` 为统一 DeepSeek 适配；`records.py` 保存原始事件及实际 API 请求；`run.py` 为抽样和官方执行入口；`render.py`、`report.py` 生成可审阅产物。
