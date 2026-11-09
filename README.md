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

## Where data lives

This repository is code only. The ontology it builds is data and never lives in a checkout:

- `ONTOLAGNI_DIR`, else `$XDG_DATA_HOME/ontolagni` (`~/.local/share/ontolagni`): where `build` writes and `find`
  reads. (Not `ONTOLOGY_DIR`: that name is ignored.)
- The published copy is in its own private bucket (named in the deployment, not here), apart from the
  traceDB store it describes.
- The ranking eval (`eval/rank_metrics.py`) runs on a real catalog and labelled queries kept outside the repository:
  set `ONTOLAGNI_EVAL_DIR` to a folder with `catalog.jsonl.gz`, `queries.json`, `queries_heldout.json` (and its
  `test_ranking.py`). Without it the eval is skipped.
