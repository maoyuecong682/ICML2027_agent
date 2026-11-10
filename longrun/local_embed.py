"""本地 OpenAI 兼容 embeddings 服务（mem0 的 embedder 指向它）。

为什么需要：DeepSeek 只提供 chat，没有 /v1/embeddings（实测 404），而 mem0 的
向量检索必须有 embedder。这里用确定性字符 n-gram 哈希向量替代语义模型：

    优点：零外部依赖、可复现、不下载模型、不联网
    代价：只保留词面重合信息，不理解同义改写

对图记忆够用——真正承担召回的是 mem0 的实体-关系图遍历，向量只负责给出种子。
凡是依赖"语义近义"的实验结论，都要标注这一限制。

    python local_embed.py --port 8731
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 256


def embed(text: str) -> list[float]:
    """字符 n-gram（n=2,3,4）哈希到 DIM 维，TF 加权后 L2 归一化。"""
    s = re.sub(r"\s+", " ", str(text)).strip().lower()
    vec = [0.0] * DIM
    if not s:
        return vec
    for n in (2, 3, 4):
        for i in range(max(0, len(s) - n + 1)):
            g = s[i:i + n]
            h = int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big")
            vec[h % DIM] += 1.0 / n           # 长 gram 权重低一点，避免只匹配整句
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/embeddings"):
            return self._send(404, {"error": {"message": "not found"}})
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": {"message": "bad json"}})
        inp = payload.get("input", "")
        items = inp if isinstance(inp, list) else [inp]
        data = [{"object": "embedding", "index": i, "embedding": embed(x)}
                for i, x in enumerate(items)]
        self._send(200, {"object": "list", "model": payload.get("model", "local-ngram"),
                         "data": data,
                         "usage": {"prompt_tokens": sum(len(str(x)) for x in items),
                                   "total_tokens": sum(len(str(x)) for x in items)}})

    def do_GET(self):
        self._send(200, {"object": "list", "data": [{"id": "local-ngram", "object": "model"}]})


def serve(port: int = 8731):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8731)
    a = ap.parse_args()
    print(f"local-ngram embeddings on http://127.0.0.1:{a.port}/v1")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
