### 最小预实验

实验目的：找出流程里真正影响隐私判断和任务完成的地方
实验必须体现的过程：连续执行任务、整理记忆和再次共享信息的过程 再附上实际运行记录 一整个pipeline
体现 谁获得了什么信息 信息共享给了谁 记忆整理后保留了什么
【注意】 删除一条记忆后，接收者仍然知道此前内容


### 最终pipeline

[TASK]AgentDojo（任务+注入+utility）── DeepSeek API（deepseek-flash）── 2 agents
        │
[执行图\隐私图表示]   LangGraph StateGraph + checkpointer
        │
[图信息压缩]     Mem0（压缩，history 留痕）
        │
[自写:隐私合并] Rubrics + μ(z) + 算子层 ←← 唯一新增代码，实验自变量
        │
[接收者视图]   外发点 ─► AgentLeak SDK（接收者视图/通道审计）
        │
[隐私泄露程度的判断]   llmprivacy（联合推断 → attack success + top-1 recovery 双报）
        │
   Langfuse（trace + t + 双口径 token 记账）github.com/langfuse/langfuse

Baseline：agentdojo（阶段1）→ + CaMeL（阶段2）
交付物：对算子层做单点冻结干预（其余 IDENTITY、被试点 REDACT），
        泄露×任务四象限定位关键点；贪心前向扫描定位联合敏感位


注：API == ${DEEPSEEK_API_KEY} 
model == deepseek-flash


### 模块迁移

| 研究问题 | 设置 |
|---|---|
| 隐私领域的任务 | agentdojo 仓库：github.com/ethz-spylab/agentdojo（ETH Zurich SPY Lab，NeurIPS 2024 D&B） |
| 最小规模实验的agent个数 | 2 |
| Agent 背后的llm backbone | deepseek-flash<br>Api:${DEEPSEEK_API_KEY} |
| 隐私图/执行图的数据结构 | LangGraph（github.com/langchain-ai/langgraph）StateGraph+checkpointer（SQLite/Postgres） |
| 执行、隐私记忆压缩方法 | Mem0（github.com/mem0ai/mem0 |
| 隐私信息合并方法（特别指的是信息本身不是相同的，而是联合在一起看可以得到新的隐私信息的“联合”这个过程） | |
| baseline | AgentDojo; |
| 接收者能够接受到多少隐私\什么隐私 需要一个能让我们看出来\看明白的方式 | |
| 单个长程任务的流程可视化（连续执行任务、记忆整理、信息再次共享） | Langfuse（github.com/langfuse/langfuse）session视图 |
| 任务完成情况{0，1}或者平均任务成功率 | 任务成功率（task success） |
| 接收者是否推断出敏感信息{0，1}==隐私是否泄露 | OCELOT 的 top-1 secret recovery |
| 记忆的占用空间（如何统计以及单位是什么） | token（钱） |
| 长程任务执行时间t | Langfuse（github.com/langfuse/langfuse） |
| 交付：流程里真正影响隐私判断和任务完成的地方 | |