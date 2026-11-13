"""Reproducible demo benchmark on a SYNTHETIC catalog (generated here, deterministic): measures the mechanics of
build / find / verify, not ranking quality on a real store.

    python3 eval/demo_bench.py     # writes eval/results/demo.json

The catalog is a listing of {path, sha, size, meta}, the same contract `tracedb export-catalog` produces.
"""
import hashlib, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from ontolagni import build, write, Onto, verify  # noqa: E402

TOPICS = ["vllm-throughput", "kv-cache", "spec-decode", "mmlu-eval", "oom-repro", "gemm-sweep", "lora-train", "prefill-bench",
          "tokenizer-fuzz", "attention-prof"]
CHIPS = ["h100", "a100", "b300", "l4", "a10g"]
MODELS = ["qwen", "gemma", "kimi", "glm"]
ROOTS = ["logs", "research", "experiments"]


def catalog(files_per_campaign=400):
    lines, campaigns = [], []
    k = 0
    for ti, topic in enumerate(TOPICS):
        for ci, chip in enumerate(CHIPS):
            model = MODELS[(ti + ci) % len(MODELS)]
            date = f"2026{1 + (k % 9):02d}{1 + (k % 27):02d}"
            name = f"{model}-{topic}-{chip}-{date}"
            k += 1
            campaigns.append({"name": name, "topic": topic, "chip": chip, "model": model})
            for root in ROOTS:
                for j in range(files_per_campaign):
                    sub = ("dispatch/jobs", "probe/census", "dialogs")[j % 3]
                    p = f"{root}/{name}/{sub}/f{j:03d}.{('log', 'csv', 'jsonl')[j % 3]}"
                    lines.append(json.dumps({"path": p, "sha": hashlib.sha256(p.encode()).hexdigest(), "size": 1000 + j * 37,
                                             "meta": {"keys": ["role", "text"]} if j % 3 == 2 else {}}))
    return lines, campaigns


def main():
    lines, campaigns = catalog()
    cat_bytes = sum(len(l) + 1 for l in lines)
    bt = []
    for _ in range(3):
        t = time.perf_counter(); nodes, meta = build(iter(lines)); bt.append(time.perf_counter() - t)
    with tempfile.TemporaryDirectory() as d:
        write(nodes, meta, d)
        onto_bytes = os.path.getsize(os.path.join(d, "ontology.jsonl"))
        t = time.perf_counter(); onto = Onto(d); load_s = time.perf_counter() - t
        hits1 = hits3 = 0
        lat = []
        qs = [(c, f"{c['topic'].replace('-', ' ')} {c['chip']} {c['model']} logs") for c in campaigns]
        for c, q in qs:
            res = onto.find(q, limit=10)
            ids = [r["id"] for r in res]
            want = f"logs/{c['name']}"
            hits1 += bool(ids and ids[0] == want)
            hits3 += want in ids[:3]
            best = 1e9
            for _ in range(5):
                t = time.process_time(); onto.find(q, limit=10); best = min(best, (time.process_time() - t) * 1000)
            lat.append(best)
        lat.sort()
        v_ok = verify(onto, iter(lines))
        # tamper: change one file's content hash, expect verify to flag exactly the nodes on that file's path chain
        bad_lines = list(lines)
        r = json.loads(bad_lines[0]); r["sha"] = "0" * 64; bad_lines[0] = json.dumps(r)
        v_bad = verify(onto, iter(bad_lines))
        dot = onto.where(json.loads(lines[0])["path"])
    out = {"synthetic": True, "files": meta["files"], "nodes": meta["nodes"], "campaigns": len(campaigns),
           "catalog_bytes": cat_bytes, "ontology_bytes": onto_bytes, "shrink": round(cat_bytes / onto_bytes, 1),
           "build_s": round(min(bt), 3), "load_ms": round(load_s * 1000, 1), "queries": len(qs),
           "hit_at_1": round(hits1 / len(qs), 3), "hit_at_3": round(hits3 / len(qs), 3),
           "find_p50_ms": round(lat[len(lat) // 2], 2), "find_max_ms": round(lat[-1], 2),
           "verify_clean_ok": v_ok["ok"], "verify_tampered_ok": v_bad["ok"], "verify_tampered_flagged": len(v_bad["bad"]),
           "where_chain": len(dot),
           "size_rows": [{"what": "catalog listing", "mb": round(cat_bytes / 1e6, 2)}, {"what": "ontology", "mb": round(onto_bytes / 1e6, 2)}]}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "demo.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
