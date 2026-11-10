# Optional privacy text compression

`privacy_memory_compression.py` exports `compress_memory(..., strategy="none"|"mem0")`.
Default is `none`: no API or Mem0 import. `mem0` uses installed Mem0 1.0.5 and
DeepSeek `deepseek-flash`, with audited calls. Run with `.venv_mem0/Scripts/python.exe`.

```powershell
.venv_mem0/Scripts/python.exe privacy_memory_compression.py --input outputs/ocelot_20261028/披露信息.json --task workspace/user_task_31 --strategy none --output outputs/privacy_text_trial/none
.venv_mem0/Scripts/python.exe privacy_memory_compression.py --input outputs/ocelot_20261028/披露信息.json --task workspace/user_task_31 --strategy mem0 --output outputs/privacy_text_trial/mem0
```

Set `DEEPSEEK_API_KEY` in the process environment, or explicitly supply `--env-file`.
Outputs must not exist. Source files and old experiment outputs are never rewritten.

Inputs: existing disclosure bundle (only annotated non-`none` spans), P6 raw
receiver snapshot (all received string parameters, unclassified), or normalized
`privacy.text.input.v1` with `blocks` and optional occurrence-ID `links`.
Comparison must use the SAME input/projection for both conditions. These adapters
are different input granularities, not equivalent experiments. The disclosure
adapter does not discover new sensitive spans or import the existing graph.

Each block has unique `id`, `task_id`, `receiver_id`, `field`, `text` and optional
`kind`, `relation`, `event_id`, original offsets/source IDs. Explicit links have
exactly `link_id`, `type`, `members`. The caller must provide any needed association
links; co-occurrence does not create identity or itinerary bindings.

Mem0 receives one batch per task/receiver/field/kind/relation. Its custom fact
extraction prompt groups equivalent or identical text and emits source-ID groups.
The memory-management stage stores those groups in a fresh isolated Qdrant store.
All scope texts are jointly visible to the LLM; the lexical-hash embedding is NOT
a semantic model and no semantic retrieval recall result is claimed. Large scopes
are rejected rather than silently truncated (default 80 blocks).

Validation requires every occurrence exactly once, no invented source IDs, no
cross-scope merge, and a canonical text copied exactly from a member. Partial
overlaps, changed dates, negations and uncertainty should remain separate. This
is still LLM equivalence judgment, not a semantic correctness proof. Invalid output
fails the run; it never silently falls back to baseline or labels an empty store
as successful compression. Text-identical names are value reuse, not entity resolution.

Inference reads **memory.json only**, for BOTH conditions. `facts` store texts;
`occurrences` retain event IDs and point to facts; links keep occurrence IDs.
`inference_blocks(memory)` resolves representative texts if an evaluator needs
per-occurrence input. Do not interpret old source offsets as offsets in the new
representative. `before.json`, API logs and original evidence are audit-only;
feeding them to the compressed inference arm invalidates the comparison.

No graph structure is compressed; no receiver knowledge is merged across recipients;
no existing online pipeline is changed. This text strategy is opt-in. To measure
future inference, hold the evaluator, queries and available links fixed and change
only the strategy. A surface-form-sensitive evaluator can change its answer after
a semantically valid paraphrase substitution: report that limitation separately.
`report.json` distinguishes text bytes from total active JSON bytes (metadata may
outweigh savings); retained audits/database sizes are excluded and no disk savings
or unchanged future inference are claimed.
