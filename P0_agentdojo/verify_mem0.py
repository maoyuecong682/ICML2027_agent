"""Verify existing outputs without API calls or modifying source records."""
import hashlib
import json
from pathlib import Path
import re

from mem0_compress import ROOT, dump, source_block, validate_snapshot


def main():
    folder = ROOT/"outputs/mem0_20261028/workspace_user_task_31"
    report_path = folder/"压缩报告.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for actor in ("A", "B"):
        before = json.loads((folder/actor/"执行记忆_压缩前.json").read_text(encoding="utf-8"))["messages"]
        after = json.loads((folder/actor/"执行记忆_压缩后.json").read_text(encoding="utf-8"))["messages"]
        validate_snapshot(before, after, source_block(actor, before))
        rows = [json.loads(line) for line in
                (folder/actor/"compression_api.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 2
        assert all(row["response"]["model"] == "deepseek-flash" for row in rows)
        report["actors"][actor]["compression_api"] = {
            "calls": len(rows), "returned_models": [r["response"]["model"] for r in rows],
            "prompt_tokens": sum(r["response"]["usage"]["prompt_tokens"] for r in rows),
            "completion_tokens": sum(r["response"]["usage"]["completion_tokens"] for r in rows),
            "seconds": round(sum(r["seconds"] for r in rows), 3)}
    assert hashlib.sha256(Path(report["source"]).read_bytes()).hexdigest() == report["source_sha256"]
    for file in folder.rglob("*"):
        if file.is_file() and file.suffix in (".json", ".jsonl"):
            assert not re.search(rb"sk-[A-Za-z0-9]{20,}", file.read_bytes()), "Credential pattern in output"
    dump(report_path, report)
    print("PASS: both actor snapshots, actual returned model, original source hash, credential-free JSON")


if __name__ == "__main__":
    main()
