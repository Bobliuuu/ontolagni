"""Query the ontology. Loads one small JSONL; everything in-memory; no network."""
from __future__ import annotations
import json, math, os, re
from collections import defaultdict

TOK = re.compile(r"[a-z0-9.]+")


def toks(s: str):
    return TOK.findall(s.lower())


class Onto:
    def __init__(self, dir_: str):
        self.dir = dir_
        with open(os.path.join(dir_, "meta.json")) as f:
            self.meta = json.load(f)
        self.nodes: dict[str, dict] = {}
        with open(os.path.join(dir_, "ontology.jsonl")) as f:
            for l in f:
                n = json.loads(l)
                self.nodes[n["id"]] = n
        self._inv: dict[str, list] = defaultdict(list)
        self._len: dict[str, int] = {}
        for i, n in self.nodes.items():
            t = toks(n["text"])
            self._len[i] = len(t)
            tf: dict[str, int] = {}
            for w in t:
                tf[w] = tf.get(w, 0) + 1
            for w, c in tf.items():
                self._inv[w].append((i, c))
        self._avg = (sum(self._len.values()) / max(len(self._len), 1)) or 1

    def find(self, text: str = "", kind=None, model=None, chip=None, campaign=None, depth=None, limit=10):
        cand = None
        q = toks(text)
        scores: dict[str, float] = defaultdict(float)
        N = len(self.nodes)
        for w in q:
            post = self._inv.get(w)
            if not post:
                # prefix match fallback (agents type partial ids)
                post = [(i, c) for k, ps in self._inv.items() if k.startswith(w) for i, c in ps] if len(w) >= 3 else []
            if not post:
                continue
            if len(post) > 0.3 * N and len(q) > 1:
                continue  # near-universal term: ~zero idf, but scanning it costs O(N)
            idf = math.log(1 + (N - len(post) + .5) / (len(post) + .5))
            for i, c in post:
                L = self._len[i]
                scores[i] += idf * c * 2.2 / (c + 1.2 * (0.25 + 0.75 * L / self._avg))
        pool = scores if q else {i: 0.0 for i in self.nodes}
        out = []
        for i, s in pool.items():
            n = self.nodes[i]
            if kind and n.get("kind") != kind: continue
            if model and n.get("model") != model: continue
            if chip and n.get("chip") != chip: continue
            if campaign and not (i == campaign or i.startswith(campaign.rstrip("/") + "/")): continue
            if depth and n["depth"] != depth: continue
            if not depth and n["depth"] == 1: continue  # roots are navigation, not answers
            out.append((-s, n["depth"], i))
        out.sort()
        return [self.card(self.nodes[i], -s) for s, _, i in out[:limit]]

    def where(self, path: str):
        """Longest-prefix owner chain for a path or prefix."""
        p = path.strip("/").split("/")
        for d in range(min(len(p), 8), 0, -1):
            g = "/".join(p[:d])
            if g in self.nodes:
                chain = []
                cur = g
                while cur:
                    chain.append(cur)
                    cur = self.nodes[cur].get("parent")
                return [self.card(self.nodes[c]) for c in chain]
        return []

    def show(self, id_: str):
        n = self.nodes.get(id_)
        if not n:
            return None
        c = self.card(n)
        c["children"] = n.get("children", [])
        c["keys"] = n.get("keys", [])
        return c

    def card(self, n, score=None):
        c = {"id": n["id"], "kind": n.get("kind"), "files": n["files"], "bytes": n["bytes"],
             "formats": n["formats"]}
        for k in ("model", "chip", "date", "topic", "ts_min", "ts_max"):
            if k in n: c[k] = n[k]
        if score is not None: c["score"] = round(score, 3)
        # exact next step for the agent: always plan first, never pull blindly
        c["next"] = {"list": f"tracedb ls {n['id']}/ --limit 50", "summary": f"tracedb summary {n['id']} --depth 1",
                     "est_raw_bytes": n["bytes"]}
        return c


def verify(onto: "Onto", catalog_lines) -> dict:
    """Correctness: rebuild from the catalog and compare every node digest, file count and byte count."""
    from .build import build
    nodes, meta = build(catalog_lines)
    want = {n["id"]: n for n in nodes}
    bad, missing, extra = [], [], []
    for i, n in want.items():
        o = onto.nodes.get(i)
        if o is None:
            missing.append(i)
        elif (o["digest"], o["files"], o["bytes"]) != (n["digest"], n["files"], n["bytes"]):
            bad.append(i)
    extra = [i for i in onto.nodes if i not in want]
    return {"ok": not (bad or missing or extra), "bad": bad[:20], "missing": missing[:20], "extra": extra[:20],
            "catalog_digest_match": meta["catalog_digest"] == onto.meta["catalog_digest"]}
