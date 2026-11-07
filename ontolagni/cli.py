import argparse, json, os, sys
from .build import build, write
from .query import Onto, verify

DEF = os.environ.get("ONTOLAGNI_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ontolagni")
    ap.add_argument("--dir", default=DEF)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("build"); p.add_argument("catalog"); p.add_argument("--store", default="")
    p = sp.add_parser("find"); p.add_argument("text", nargs="*")
    for k in ("kind", "model", "chip", "campaign"): p.add_argument(f"--{k}")
    p.add_argument("--depth", type=int); p.add_argument("--limit", type=int, default=10)
    p = sp.add_parser("where"); p.add_argument("path")
    p = sp.add_parser("show"); p.add_argument("id")
    p = sp.add_parser("verify"); p.add_argument("catalog")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        f = sys.stdin if a.catalog == "-" else open(a.catalog)
        nodes, meta = build(f, store_label=a.store); write(nodes, meta, a.dir)
        print(json.dumps(meta)); return 0
    o = Onto(a.dir)
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
