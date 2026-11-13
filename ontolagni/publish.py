"""Concurrency-safe publishing of the ontology, and overlays (extra nodes other tools add).

Published layout (s3://<bucket>/<prefix>/ or a local dir):
  ontology.jsonl, meta.json, AGENT.md, ONTOLOGY.md, agent_index.json, wiki/index.html   (derived, re-rendered on publish)
  overlays/<name>.jsonl     one file per writer (push-boxes, rsi, bootstrap, ...): that writer's nodes, replaced wholesale

Every publish (a full rebuild or `ontolagni overlay`) does a compare-and-swap loop on ontology.jsonl:
  read current (+ETag) -> carry its nodes/fields into ours -> apply ALL overlay files -> write with If-Match -> on conflict retry.
So concurrent writers can't lose each other's nodes: a writer whose swap lost re-reads and re-applies everything, and since
overlay files are separate objects, any later publish (by anyone) applies them too. Full rebuilds preserve overlays the same way.
Overlay nodes: same id as an existing node -> fields merged (digest/size fields are never touched); new id -> synthetic node
tagged overlay=<name>. A synthetic node an overlay published before and no longer lists is removed.
S3 needs boto3 (optional dependency; everything else is stdlib)."""
from __future__ import annotations
import json, os, random, tempfile, time

PROTECT = {"id", "digest", "files", "bytes", "formats", "depth"}


def norm(n: dict, name: str) -> dict:
    n = {"files": 0, "bytes": 0, "formats": {}, "depth": n["id"].count("/") + 1, **n}
    if n["depth"] > 1:
        n.setdefault("parent", "/".join(n["id"].split("/")[:-1]))
    n["synthetic"] = True
    n["overlay"] = name
    return n


def apply_overlays(nodes: list[dict], overlays: dict[str, list[dict]]) -> list[dict]:
    by = {n["id"]: n for n in nodes}
    for name, ons in overlays.items():
        ids = {o["id"] for o in ons}
        for i in [i for i, n in by.items() if n.get("overlay") == name and n.get("synthetic") and i not in ids]:
            del by[i]
    for name in sorted(overlays):
        for o in overlays[name]:
            n = by.get(o["id"])
            if n is None:
                by[o["id"]] = norm(dict(o), name)
            else:
                for k, v in o.items():
                    if k not in PROTECT:
                        n[k] = v
                if not n.get("synthetic"):
                    n["overlays"] = sorted(set(n.get("overlays", [])) | {name})
    for i, n in by.items():  # hook new nodes into their parent's children
        p = n.get("parent")
        if p in by and i not in by[p].get("children", []):
            by[p]["children"] = sorted(set(by[p].get("children", [])) | {i})
    return sorted(by.values(), key=lambda n: n["id"])


def read_jsonl(b: bytes) -> list[dict]:
    return [json.loads(l) for l in b.decode().splitlines() if l.strip()]


def dump_jsonl(nodes) -> bytes:
    return "".join(json.dumps(n, separators=(",", ":"), sort_keys=True) + "\n" for n in nodes).encode()


# ----------------------------------------------------------------------------------------------- targets
class S3Target:
    def __init__(self, url: str):
        import boto3
        rest = url[5:].rstrip("/")
        self.bucket, _, self.prefix = rest.partition("/")
        self.prefix = self.prefix + "/" if self.prefix else ""
        self.c = boto3.client("s3")

    def get(self, key):
        try:
            r = self.c.get_object(Bucket=self.bucket, Key=self.prefix + key)
            return r["Body"].read(), r["ETag"]
        except self.c.exceptions.NoSuchKey:
            return None, None

    def put(self, key, data: bytes, if_match=None, if_none_match=False) -> bool:
        kw = {"IfMatch": if_match} if if_match else ({"IfNoneMatch": "*"} if if_none_match else {})
        try:
            self.c.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, **kw)
            return True
        except Exception as e:  # 412 PreconditionFailed / 409 ConditionalRequestConflict: someone else won the swap
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409"):
                return False
            raise

    def overlays(self) -> dict:
        out = {}
        pag = self.c.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=self.bucket, Prefix=self.prefix + "overlays/"):
            for o in page.get("Contents", []):
                k = o["Key"][len(self.prefix):]
                if k.endswith(".jsonl"):
                    out[os.path.basename(k)[:-6]] = read_jsonl(self.get(k)[0] or b"")
        return out


class DirTarget:
    """Local dir: the same protocol, with an exclusive flock instead of If-Match."""
    def __init__(self, d: str):
        self.d = d
        os.makedirs(os.path.join(d, "overlays"), exist_ok=True)
        import fcntl
        self._lk = open(os.path.join(d, ".publish.lock"), "w")
        fcntl.flock(self._lk, fcntl.LOCK_EX)

    def get(self, key):
        p = os.path.join(self.d, key)
        if not os.path.exists(p):
            return None, None
        b = open(p, "rb").read()
        return b, str(os.stat(p).st_mtime_ns)

    def put(self, key, data, if_match=None, if_none_match=False):
        p = os.path.join(self.d, key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        return True

    def overlays(self):
        od = os.path.join(self.d, "overlays")
        return {f[:-6]: read_jsonl(open(os.path.join(od, f), "rb").read()) for f in sorted(os.listdir(od)) if f.endswith(".jsonl")}


def target(dest: str):
    return S3Target(dest) if dest.startswith("s3://") else DirTarget(dest)


# ----------------------------------------------------------------------------------------------- publish
def publish(dest: str, nodes: list[dict] | None = None, meta: dict | None = None, overlay: tuple[str, list] | None = None,
            render_docs: bool = True, tries: int = 12) -> dict:
    """nodes/meta: a fresh build to publish (None: keep the published nodes, e.g. for an overlay-only publish).
    overlay: (name, nodes) written to overlays/<name>.jsonl first."""
    from .build import carry
    t = target(dest)
    if overlay:
        name, ons = overlay
        t.put(f"overlays/{name}.jsonl", dump_jsonl(ons))
    for attempt in range(tries):
        cur_b, etag = t.get("ontology.jsonl")
        cur_meta = json.loads(t.get("meta.json")[0] or b"{}")
        if nodes is None:
            merged = read_jsonl(cur_b or b"")
            m = dict(cur_meta)
        else:
            merged, _ = carry([dict(n) for n in nodes], (cur_b or b"").decode().splitlines())
            m = {**cur_meta, **(meta or {})}
        ovs = t.overlays()
        merged = apply_overlays(merged, ovs)
        m["nodes"] = len(merged)
        if ovs:
            m["overlays"] = sorted(set(m.get("overlays", [])) | set(ovs))
            m["overlay_t"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok = t.put("ontology.jsonl", dump_jsonl(merged), if_match=etag, if_none_match=etag is None)
        if ok:
            t.put("meta.json", json.dumps(m, indent=1, sort_keys=True).encode())
            if render_docs:
                _render_and_put(t, merged, m)
            return {"ok": True, "nodes": len(merged), "overlays": sorted(ovs), "attempts": attempt + 1}
        time.sleep(min(30, 0.5 * 2 ** attempt) * (0.5 + random.random()))
    raise RuntimeError(f"publish: lost the compare-and-swap {tries} times; retry later")


def _render_and_put(t, nodes, meta):
    from .render import render
    from .wiki import build_wiki
    with tempfile.TemporaryDirectory() as d:
        render(nodes, meta, d, meta.get("store", ""))
        build_wiki(nodes, meta, os.path.join(d, "wiki"), meta.get("store", ""))
        for rel in ("AGENT.md", "ONTOLOGY.md", "agent_index.json", "wiki/index.html"):
            p = os.path.join(d, rel)
            if os.path.exists(p):
                t.put(rel, open(p, "rb").read())


def pull(dest: str, out_dir: str):
    """Copy the published ontology.jsonl + meta.json into a local ontology dir (for queries)."""
    t = target(dest)
    os.makedirs(out_dir, exist_ok=True)
    for k in ("ontology.jsonl", "meta.json"):
        b, _ = t.get(k)
        if b is not None:
            open(os.path.join(out_dir, k), "wb").write(b)
