# ontolagni

Middleware ontology: **what data exists where**. Output is for agents (JSON), not humans.
Siloed: stdlib only, imports nothing from traceDB; the only contract is a catalog listing
(`tracedb export-catalog` → JSONL of `{path, sha, size, meta}`). Every node carries a content digest of its
subtree so `ontolagni verify` proves the ontology matches the store.

    tracedb export-catalog --out cat.jsonl && ontolagni build cat.jsonl
    ontolagni find qwen g7e vllm            # ranked nodes, each with file/byte counts and the next tracedb command
    ontolagni where logs/x/y/z.log          # owner chain
    ontolagni verify cat.jsonl              # exit 2 if anything drifted

Agents: ontolagni (find) → `tracedb plan`/`ls`/`get --head` (budgeted). Never pull blind.
