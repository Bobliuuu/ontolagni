"""Ranking eval for ontolagni against a real catalog snapshot (paths/sizes/json keys only).

    python eval/run_eval.py [-v]      # prints MRR, hit@1/3/10, p50/p99 query latency, failing queries

Relevance: a result is relevant if its id equals a `rel` pattern, or (pattern ending in `*`) starts with it.
"""
import gzip, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
# The eval's data (a real catalog and its labelled queries) is data, not code: it lives outside this repository, in
# ONTOLAGNI_EVAL_DIR (catalog.jsonl.gz, queries.json, queries_heldout.json). Without it the ranking eval is skipped.
EVAL_DIR = os.environ.get("ONTOLAGNI_EVAL_DIR", "")
sys.path.insert(0, os.path.dirname(HERE))
from ontolagni import build, write, Onto  # noqa: E402


def load_onto(tmp):
    with gzip.open(os.path.join(EVAL_DIR, "catalog.jsonl.gz"), "rt") as f:
        nodes, meta = build(f)
    write(nodes, meta, tmp)
    return Onto(tmp)


def is_rel(i, pats):
    return any(i == p or (p.endswith("*") and i.startswith(p[:-1])) for p in pats)


def evaluate(onto, queries, limit=10):
    rr, h1, h3, h10, lat, fails = [], 0, 0, 0, [], []
    for q in queries:
        res = onto.find(q["q"], limit=limit)
        best = 1e9
        for _ in range(5):  # CPU time, best of 5: robust to a loaded machine
            t = time.process_time()
            onto.find(q["q"], limit=limit)
            best = min(best, (time.process_time() - t) * 1000)
        lat.append(best)
        rank = next((k + 1 for k, c in enumerate(res) if is_rel(c["id"], q["rel"])), None)
        rr.append(1 / rank if rank else 0.0)
        h1 += bool(rank and rank <= 1); h3 += bool(rank and rank <= 3); h10 += bool(rank and rank <= 10)
        if not rank or rank > 3:
            fails.append((q["q"], rank, [c["id"] for c in res[:3]]))
    n = len(queries)
    lat.sort()
    return {"n": n, "mrr": round(sum(rr) / n, 3), "hit@1": round(h1 / n, 3), "hit@3": round(h3 / n, 3),
            "hit@10": round(h10 / n, 3), "p50_ms": round(lat[n // 2], 2), "p99_ms": round(lat[int(n * .99)], 2)}, fails


def main():
    name = "queries_heldout.json" if "--heldout" in sys.argv else "queries.json"
    queries = json.load(open(os.path.join(EVAL_DIR, name)))
    with tempfile.TemporaryDirectory() as d:
        onto = load_onto(d)
        # sanity: every relevance pattern matches at least one real node
        for q in queries:
            assert any(is_rel(i, q["rel"]) for i in onto.nodes), f"no node matches {q}"
        m, fails = evaluate(onto, queries)
    print(json.dumps(m))
    if "-v" in sys.argv:
        for q, r, top in fails:
            print(f"  MISS rank={r} {q!r} -> {top}")


if __name__ == "__main__":
    main()
