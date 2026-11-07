"""Build the ontology from a catalog listing (JSONL of {path, sha, size, meta}).

Contract with the store is a *file format only*: no store code is imported (siloed).
Nothing is invented: every field is derived from paths/meta in the listing; absent -> omitted.
"""
from __future__ import annotations
import hashlib, json, re, sys
from collections import Counter, defaultdict

CAMPAIGN_RE = re.compile(
    r"^(?P<topic>[a-z0-9.\-]+?)(?:-(?P<chip>b300|h100|a100|g7e|a10g|tiramisu|a100))?-(?P<date>\d{8})(?:T(?P<time>\d{4})Z)?(?:-(?P<suffix>[a-z]|team|block2))?$")
MODELS = ["glm-5.3-flash", "kimi-k3", "gemma-4-31b", "qwen3.8-27b", "qwen3.5", "qwen", "gemma", "glm", "kimi", "deepseek"]
CHIPS = ["b300", "h100", "a100", "g7e", "a10g", "tiramisu", "l4", "g5", "g6"]
ROOT_KIND = {"logs": "logs", "research": "research", "experiments": "experiment", "data": "dataset",
             "docs": "docs", "reports": "report", "bugs": "bug", "evals": "eval", "traces": "trace", "rsi": "rsi-store"}
FMT = {".jsonl": "jsonl", ".json": "json", ".md": "md", ".log": "log", ".csv": "csv", ".tsv": "tsv",
       ".gz": "gz", ".txt": "txt", ".py": "py", ".sh": "sh", ".sqlite": "sqlite", ".so": "bin"}
SCHEMA_VERSION = 1


def fmt(path: str) -> str:
    for ext, f in FMT.items():
        if path.endswith(ext):
            return f
    return "other"


def derive_tags(group: str) -> dict:
    """Fields derivable from the group's own name; nothing guessed."""
    parts = group.split("/")
    t: dict = {}
    if parts[0] in ROOT_KIND:
        t["kind"] = ROOT_KIND[parts[0]]
    name = parts[1] if len(parts) > 1 else parts[0]
    m = CAMPAIGN_RE.match(name)
    if m:
        t["topic"] = m["topic"]
        if m["chip"]:
            t["chip"] = m["chip"]
        t["date"] = m["date"]
    low = group.lower()
    for mo in MODELS:
        if mo in low:
            t["model"] = mo
            break
    if "chip" not in t:
        for c in CHIPS:
            if re.search(rf"(^|[-_/]){c}([-_/]|$)", low):
                t["chip"] = c
                break
    return t


def group_key(path: str, depth: int) -> str:
    p = path.split("/")
    return "/".join(p[:depth]) if len(p) > depth else None


def build(catalog_lines, max_depth: int = 4, store_label: str = "") -> tuple[list[dict], dict]:
    """Nodes at depth 1 (root), 2 (campaign/dataset) and 3 (sub-group). Files shallower than a depth belong to their parent only."""
    acc: dict[str, dict] = {}
    cat_h = hashlib.sha256()
    n_files = 0
    for line in catalog_lines:
        if not line.strip():
            continue
        r = json.loads(line)
        path, size, sha = r["path"], r["size"], r["sha"]
        n_files += 1
        cat_h.update(f"{path}\0{sha}\n".encode())
        p = path.split("/")
        for d in range(1, min(max_depth, len(p) - 1) + 1):
            g = "/".join(p[:d])
            a = acc.get(g)
            if a is None:
                a = acc[g] = {"files": 0, "bytes": 0, "fmts": Counter(), "keys": Counter(), "h": hashlib.sha256(),
                              "children": set(), "ts": []}
            a["files"] += 1
            a["bytes"] += size
            a["fmts"][fmt(path)] += 1
            a["h"].update(f"{path}\0{sha}\n".encode())
            if d < len(p) - 1 and d < max_depth:
                a["children"].add("/".join(p[:d + 1]))
            for k in (r.get("meta") or {}).get("keys", []) or []:
                a["keys"][k] += 1
            ts = (r.get("meta") or {}).get("ts")
            if ts:
                a["ts"].append(ts)
    nodes = []
    for g in sorted(acc):
        a = acc[g]
        depth = g.count("/") + 1
        tags = derive_tags(g)
        node = {
            "id": g, "depth": depth, "files": a["files"], "bytes": a["bytes"],
            "digest": a["h"].hexdigest(), "formats": dict(a["fmts"].most_common()),
            **{k: v for k, v in tags.items()},
        }
        if depth > 1:
            node["parent"] = "/".join(g.split("/")[:-1])
        if a["children"]:
            node["children"] = sorted(a["children"])
        if a["keys"]:
            node["keys"] = [k for k, _ in a["keys"].most_common(24)]
        if a["ts"]:
            node["ts_min"], node["ts_max"] = min(a["ts"]), max(a["ts"])
        node["text"] = " ".join(filter(None, [g.replace("/", " ").replace("-", " ").replace("_", " "),
                                             tags.get("model", ""), tags.get("chip", ""), tags.get("kind", ""),
                                             tags.get("date", ""), " ".join(a["fmts"]), " ".join(node.get("keys", []))]))
        nodes.append(node)
    meta = {"schema": SCHEMA_VERSION, "files": n_files, "nodes": len(nodes), "catalog_digest": cat_h.hexdigest(),
            "store": store_label}
    return nodes, meta


def write(nodes, meta, out_dir):
    import os
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "ontology.jsonl"), "w") as f:
        for n in nodes:
            f.write(json.dumps(n, separators=(",", ":"), sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
