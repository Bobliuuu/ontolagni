import argparse, json, os, sys
from .build import build, write
from .render import render
from .query import Onto, verify

DEF = os.environ.get("ONTOLAGNI_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ontolagni")
    ap.add_argument("--dir", default=DEF)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("build"); p.add_argument("catalog"); p.add_argument("--store", default="")
    p.add_argument("--describe", help="JSON {node_id: {summary, readme}} (derived from READMEs)")
    p.add_argument("--ssh-config", action="append", default=[], help="ssh config file(s) -> boxes/<alias> nodes (path:store_path)")
    p.add_argument("--docs", action="append", default=[], help="LOCALDIR=STOREPREFIX docs scanned for box mentions")
    p.add_argument("--boxes", help="box registry JSON (path[:store_path]) merged into boxes/<alias> nodes")
    p.add_argument("--skills", help="skills manifest JSON (traceDB skills/MANIFEST.json) annotating skills/<name> nodes")
    p.add_argument("--carry", help="previously published ontology.jsonl: keep other writers' nodes/fields (merge, never clobber)")
    p.add_argument("--max-depth", type=int, default=4)
    p = sp.add_parser("render"); p.add_argument("--out", required=True)
    p = sp.add_parser("wiki"); p.add_argument("--out", required=True)
    p = sp.add_parser("find"); p.add_argument("text", nargs="*")
    for k in ("kind", "model", "chip", "campaign"): p.add_argument(f"--{k}")
    p.add_argument("--depth", type=int); p.add_argument("--limit", type=int, default=10)
    p = sp.add_parser("where"); p.add_argument("path")
    p = sp.add_parser("show"); p.add_argument("id")
    p = sp.add_parser("verify"); p.add_argument("catalog")
    p = sp.add_parser("publish", help="publish --dir to DEST (s3://bucket/ontology/ or a dir): compare-and-swap, keeps every overlay")
    p.add_argument("--to", required=True)
    p = sp.add_parser("overlay", help="merge NODES.jsonl into the published ontology at DEST as overlay NAME (concurrency-safe)")
    p.add_argument("nodes"); p.add_argument("--name", required=True); p.add_argument("--to", required=True)
    p.add_argument("--pull", action="store_true", help="afterwards copy the result into --dir")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        f = sys.stdin if a.catalog == "-" else open(a.catalog)
        desc = json.load(open(a.describe)) if a.describe else None
        extra = []
        if a.ssh_config or a.boxes:
            from .access import box_nodes
            cfgs = {}
            for spec in a.ssh_config:
                lp, sp_ = spec.split(":", 1); cfgs[sp_] = open(lp).read()
            docs = {}
            for spec in a.docs:
                ld, pre = spec.split("=", 1)
                for dp, _, fs in os.walk(ld):
                    for fn in fs:
                        if fn.endswith((".md", ".txt")):
                            try: docs[pre + os.path.relpath(os.path.join(dp, fn), ld)] = open(os.path.join(dp, fn)).read()
                            except OSError: pass
            extra = box_nodes(cfgs, docs)
            if a.boxes:
                from .access import merge_registry
                lp, _, sp_ = a.boxes.partition(":")
                extra = merge_registry(extra, json.load(open(lp)), sp_ or "config/boxes.json")
            extra.append({"id": "boxes", "kind": "box", "synthetic": True, "text": "boxes ssh access hosts"})
        ann = None
        if a.skills:
            from .access import skill_annotations
            ann = skill_annotations(json.load(open(a.skills)))
        nodes, meta = build(f, max_depth=a.max_depth, store_label=a.store, describe=desc, extra_nodes=extra, annotate=ann)
        if a.carry:
            from .build import carry
            nodes, cs = carry(nodes, open(a.carry)); meta["nodes"] = len(nodes); meta["carried"] = cs
            pm = os.path.join(os.path.dirname(a.carry), "meta.json")
            if os.path.exists(pm):
                for k, v in json.load(open(pm)).items():
                    meta.setdefault(k, v)  # e.g. overlays / overlay_t written by other tools
        write(nodes, meta, a.dir)
        print(json.dumps(meta)); return 0
    if a.cmd == "overlay":
        from .publish import publish, read_jsonl, pull
        ons = read_jsonl(sys.stdin.buffer.read() if a.nodes == "-" else open(a.nodes, "rb").read())
        r = publish(a.to, overlay=(a.name, ons)); print(json.dumps(r))
        if a.pull: pull(a.to, a.dir)
        return 0
    if a.cmd == "publish":
        from .publish import publish
        o = Onto(a.dir); r = publish(a.to, nodes=list(o.nodes.values()), meta=o.meta); print(json.dumps(r)); return 0
    if a.cmd == "render":
        o = Onto(a.dir); render(list(o.nodes.values()), o.meta, a.out, o.meta.get("store", "")); print("rendered", a.out); return 0
    o = Onto(a.dir)
    if a.cmd == "wiki":
        from .wiki import build_wiki
        print("wiki", a.out, build_wiki(list(o.nodes.values()), o.meta, a.out, o.meta.get("store", ""))); return 0
    if a.cmd == "find":
        r = o.find(" ".join(a.text), a.kind, a.model, a.chip, a.campaign, a.depth, a.limit)
    elif a.cmd == "where":
        r = o.where(a.path)
    elif a.cmd == "show":
        r = o.show(a.id)
    else:
        r = verify(o, open(a.catalog)); print(json.dumps(r)); return 0 if r["ok"] else 2
    print(json.dumps(r)); return 0


if __name__ == "__main__":
    sys.exit(main())
