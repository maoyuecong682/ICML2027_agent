import sys, json
sys.stdout.reconfigure(encoding="utf-8")
from agentleak import Trace, AgentLeakRunner

tr = Trace(run_id="smoke")
tr.add_event(channel="inter_agent_message", source="A", target="B",
             content="GB29NWBK60161331926819 received 10.0 from DE89370400440532013000 on 2022-03-15")
tr.add_event(channel="shared_memory", source="B", target="mem0",
             content={"iban": "GB29NWBK60161331926819", "amount": 10.0})
tr.add_event(channel="final_output", content="Paid 10.00 to GB29NWBK60161331926819")
r = AgentLeakRunner().analyze(tr)
print("privacy_score:", r.privacy_score, "verdict:", r.score.verdict)
print("mode:", r.detection_mode, "tiers:", r.tiers, "events:", r.event_count)
print("findings:", len(r.findings))
for f in r.findings[:8]:
    print(f"  [{f.channel}] {f.detector}/{f.data_type} L{f.level} sev={getattr(f.severity,'value',f.severity)} -> {f.redacted_value}")
print("warnings:", r.warnings)
