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
    p.add_argument("--max-depth", type=int, default=4)
    p = sp.add_parser("render"); p.add_argument("--out", required=True)
    p = sp.add_parser("wiki"); p.add_argument("--out", required=True)
    p = sp.add_parser("find"); p.add_argument("text", nargs="*")
    for k in ("kind", "model", "chip", "campaign"): p.add_argument(f"--{k}")
    p.add_argument("--depth", type=int); p.add_argument("--limit", type=int, default=10)
    p = sp.add_parser("where"); p.add_argument("path")
    p = sp.add_parser("show"); p.add_argument("id")
    p = sp.add_parser("verify"); p.add_argument("catalog")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        f = sys.stdin if a.catalog == "-" else open(a.catalog)
        desc = json.load(open(a.describe)) if a.describe else None
        extra = []
        if a.ssh_config:
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
            extra.append({"id": "boxes", "kind": "box", "synthetic": True, "text": "boxes ssh access hosts"})
        nodes, meta = build(f, max_depth=a.max_depth, store_label=a.store, describe=desc, extra_nodes=extra); write(nodes, meta, a.dir)
        print(json.dumps(meta)); return 0
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
