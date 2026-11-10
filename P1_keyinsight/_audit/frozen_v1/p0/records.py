import json
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class Records:
    """Append-only raw events and an execution graph derived from the same events."""
    def __init__(self, folder=None):
        self.folder = folder
        self.nodes = []
        self.edges = []
        self.calls = []
        if folder:
            folder.mkdir(parents=True, exist_ok=True)

    def event(self, kind, actor, label, payload=None, parents=(), **meta):
        node = {"id": f"e{len(self.nodes):04d}", "type": kind, "actor": actor,
                "label": label, "timestamp": now(), "payload": payload or {}, **meta}
        if self.nodes:
            self.edge(self.nodes[-1]["id"], node["id"], "sequence")
        for parent in parents:
            if parent:
                self.edge(parent, node["id"], "data")
        self.nodes.append(node)
        self.append("events.jsonl", node)
        return node["id"]

    def edge(self, source, target, kind):
        edge = {"source": source, "target": target, "kind": kind}
        if edge not in self.edges:
            self.edges.append(edge)

    def append(self, filename, value):
        if self.folder:
            with (self.folder / filename).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")

    def request(self, value):
        self.calls.append(value)
        self.append("requests.jsonl", value)

    def usage(self):
        result = {}
        for actor in ("A", "B"):
            calls = [c for c in self.calls if c["actor"] == actor]
            result[actor] = {
                "attempts": len(calls), "responses": sum("response" in c for c in calls),
                "prompt_tokens": sum(c.get("response", {}).get("usage", {}).get("prompt_tokens", 0) or 0 for c in calls),
                "completion_tokens": sum(c.get("response", {}).get("usage", {}).get("completion_tokens", 0) or 0 for c in calls),
                "api_seconds": round(sum(c.get("seconds", 0) for c in calls), 3),
                "requested_models": sorted({c["request"]["model"] for c in calls}),
                "response_models": sorted({c["response"]["model"] for c in calls if "response" in c}),
            }
        return result
