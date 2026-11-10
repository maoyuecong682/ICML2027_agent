import copy
import time

from openai import OpenAI

from .records import now


class DeepSeek:
    """Both actors use this adapter; credentials never enter artifacts."""
    def __init__(self, api_key, config, records):
        self.config, self.records = config, records
        self.client = OpenAI(api_key=api_key, base_url=config.base_url,
                             timeout=config.timeout_seconds, max_retries=0)

    def complete(self, actor, messages, tools):
        request = {"model": self.config.model, "messages": copy.deepcopy(messages),
                   "max_tokens": self.config.max_output_tokens,
                   "extra_body": {"thinking": {"type": "disabled"}}}
        # Assistant text-only turns must omit tool_calls, not send an empty
        # array (the provider rejects that otherwise valid conversation).
        for message in request['messages']:
            if message.get('tool_calls') == []:
                message.pop('tool_calls')
        if tools:
            request.update(tools=copy.deepcopy(tools), tool_choice="auto")
        record = {"actor": actor, "base_url": self.config.base_url,
                  "started_at": now(), "request": request}
        t0 = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            record.update(seconds=round(time.perf_counter()-t0, 3),
                          error={"type": type(exc).__name__, "message": str(exc)})
            self.records.request(record)
            raise
        record.update(seconds=round(time.perf_counter()-t0, 3), response=response.model_dump(mode="json"))
        self.records.request(record)
        choice = response.choices[0]
        if choice.finish_reason in ("length", "content_filter"):
            raise RuntimeError(f"Incomplete model response: {choice.finish_reason}")
        msg = choice.message
        return {"content": msg.content or "", "tool_calls": [
            {"id": t.id, "type": "function", "function": {
                "name": t.function.name, "arguments": t.function.arguments}}
            for t in (msg.tool_calls or [])]}
