"""Reconcile P7 metrics against actual API usage and official task results."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/p0_20261028_seed20261028"
OUTPUT = ROOT / "outputs/p7_20261028"


def main():
    tasks, sources = [], {}
    for ordinal, tid in enumerate((14, 22, 31), 1):
        folder = RUN/f"workspace_user_task_{tid}"
        paths = [folder/"result.json", folder/"requests.jsonl"]
        for path in paths:
            sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        result = json.loads(paths[0].read_bytes())
        calls = [json.loads(line) for line in paths[1].read_text(encoding="utf-8").splitlines()]
        assert all("response" in call and "usage" in call["response"] for call in calls)
        by_actor = {}
        for actor in ("A", "B"):
            selected = [call for call in calls if call["actor"] == actor]
            prompt = sum(c["response"]["usage"]["prompt_tokens"] for c in selected)
            completion = sum(c["response"]["usage"]["completion_tokens"] for c in selected)
            total = sum(c["response"]["usage"]["total_tokens"] for c in selected)
            assert total == prompt + completion
            assert prompt == result["agents"][actor]["prompt_tokens"]
            assert completion == result["agents"][actor]["completion_tokens"]
            assert len(selected) == result["agents"][actor]["attempts"]
            assert all(c["request"]["model"] == c["response"]["model"] == "deepseek-flash" for c in selected)
            by_actor[actor] = {
                "llm_calls": len(selected), "prompt_tokens": prompt,
                "completion_tokens": completion, "total_tokens": total,
                "prompt_cache_hit_tokens": sum(c["response"]["usage"].get("prompt_cache_hit_tokens", 0) for c in selected),
                "prompt_cache_miss_tokens": sum(c["response"]["usage"].get("prompt_cache_miss_tokens", 0) for c in selected),
                "api_seconds_sum": round(sum(c["seconds"] for c in selected), 3)}
            assert by_actor[actor]["prompt_cache_hit_tokens"]+by_actor[actor]["prompt_cache_miss_tokens"] == prompt
        task = {"task_ordinal": ordinal, "task_id": f"workspace/user_task_{tid}",
                "prompt": result["prompt"], "model": "deepseek-flash", "attempted_task_runs": 1,
                "started_at": result["started_at"], "finished_at": result["finished_at"],
                "wall_seconds": result["wall_seconds"], "official_task_success": result["utility"],
                "observed_success_rate": result["utility"], "status": result["status"], "by_actor": by_actor}
        for key in ("llm_calls", "prompt_tokens", "completion_tokens", "total_tokens",
                    "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "api_seconds_sum"):
            task[key] = round(sum(v[key] for v in by_actor.values()), 3) if key.endswith("sum") else sum(v[key] for v in by_actor.values())
        tasks.append(task)
    aggregate = {"task_count": len(tasks), "successful_tasks": sum(t["official_task_success"] for t in tasks),
                 "task_success_rate": sum(t["official_task_success"] for t in tasks)/len(tasks),
                 "wall_seconds_sum": round(sum(t["wall_seconds"] for t in tasks), 3),
                 "wall_seconds_mean": round(sum(t["wall_seconds"] for t in tasks)/len(tasks), 6)}
    for key in ("llm_calls", "prompt_tokens", "completion_tokens", "total_tokens", "api_seconds_sum"):
        aggregate[key] = round(sum(t[key] for t in tasks), 3) if key.endswith("sum") else sum(t[key] for t in tasks)
    output = {"schema": "p7.execution_metrics.v1", "scope": "Original uncompressed P0 task execution; one run per task",
              "definitions": {
                  "wall_seconds": "Existing perf_counter measurement around run_task_with_pipeline, including official evaluation and synchronous execution logging; excludes later artifact rendering and offline analysis",
                  "tokens": "Sum of provider usage across every A/B call; repeated context and cache-hit prompt tokens included; not unique memory size",
                  "success": "AgentDojo official utility 0/1; one observation per task, not a repeated-run reliability estimate",
                  "long_run": "These are short multi-step traces (4/4/5 LLM calls), not validated long-horizon or repeated multi-task sessions"},
              "excluded": ["Mem0 compression", "privacy annotation and merging", "P6 recovery and deletion audit", "compressed-context continuation"],
              "tasks": tasks, "aggregate": aggregate, "source_hashes": sources}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT/"P7_执行指标.json").write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# P7：三个任务的执行耗时、token 与成功率", "",
             "统计来自原始真实运行的 `result.json` 与 `requests.jsonl`，逐 agent 核对 API usage。未重新调用 API。", "",
             "| 实验任务 | AgentDojo 任务 | 执行耗时（秒） | 输入 token | 输出 token | 总 token | LLM 调用 | 官方成功 |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for t in tasks:
        lines.append(f"| task{t['task_ordinal']} | {t['task_id']} | {t['wall_seconds']:.3f} | {t['prompt_tokens']} | {t['completion_tokens']} | {t['total_tokens']} | {t['llm_calls']} | {t['official_task_success']} |")
    lines += ["", f"总耗时：{aggregate['wall_seconds_sum']:.3f} 秒；平均耗时：{aggregate['wall_seconds_mean']:.3f} 秒；总 token：{aggregate['total_tokens']}；整体成功率：{aggregate['successful_tasks']}/{aggregate['task_count']}＝100%。", "",
              "耗时口径：原任务执行、API 等待、工具操作、同步日志与官方评估；不含之后的图像渲染、Mem0 压缩、隐私标注／合并或 P6 审计。API 时间之和单独保存在 JSON，不等于端到端墙钟时间。", "",
              "Token 为 DeepSeek API 返回的各次 usage 累加，含重复历史上下文及缓存命中的输入 token；不是去重后的记忆容量，也不是费用。JSON 另有缓存命中／未命中及 A、B 分项。", "",
              "每个任务只有一次运行：成功为 1，单次观察成功率为 100%，不能据此估计多次运行的可靠性。这里是未压缩运行的成功指标，不是压缩后续跑成功率。", "",
              "这三个任务分别仅有 4、4、5 次模型调用，属于短的多步骤执行轨迹；尚未验证真正长程、持续记忆或跨任务运行性能。后续长程实验可沿用相同统计口径。", "",
              "复现：`.venv\\Scripts\\python.exe -B -m p0.p7_metrics`。完整数据及源文件哈希见同目录 `P7_执行指标.json`。"]
    (OUTPUT/"P7_执行指标.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in sources.items())
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
