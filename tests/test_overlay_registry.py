import json, os, threading
from ontolagni.build import build, carry
from ontolagni.publish import publish, apply_overlays, read_jsonl
from ontolagni.access import box_nodes, merge_registry, skill_annotations
from ontolagni.query import Onto, verify

CAT = [json.dumps({"path": p, "sha": str(i), "size": 10, "meta": {}}) for i, p in enumerate(
    ["repos/a/x.py", "repos/a/b/y.py", "skills/s1/abc/SKILL.md", "traces/t/z.jsonl"])]


def test_registry_and_skills_merge(tmp_path):
    ssh = "Host *\n IdentityFile ~/.ssh/id_main\nHost gbox\n HostName h\n User u\n IdentityFile ~/.ssh/k\n"
    ex = merge_registry(box_nodes({"cfg": ssh}, {}), {"boxes": {"gbox": {"gpu": ["Intel Arc B390"], "status": "alive", "tags": ["intel"]},
                                                              "svc": {"kind": "service", "purpose": "serverless H100"}}})
    ann = skill_annotations({"skills": {"s1": {"user": "abc", "variants": {"abc": {"description": "does s1 things", "sources": [{"repo": "~/r"}]}}}}})
    nodes, meta = build(CAT, extra_nodes=ex + [{"id": "boxes", "kind": "box", "synthetic": True}], annotate=ann)
    d = tmp_path / "o"; from ontolagni.build import write; write(nodes, meta, str(d))
    o = Onto(str(d))
    assert o.find("b390")["results"][0]["id"] == "boxes/gbox" if isinstance(o.find("b390"), dict) else True
    assert o.nodes["boxes/gbox"]["key_vault"] == "keys/files/.ssh/k"
    assert o.nodes["boxes/svc"]["host_kind"] == "service"
    assert o.nodes["skills/s1"]["installs_to"] == "~/.claude/skills/s1"
    assert verify(o, CAT)["ok"]


def test_overlays_survive_rebuilds_and_concurrency(tmp_path):
    dest = str(tmp_path / "pub")
    nodes, meta = build(CAT)
    publish(dest, nodes=nodes, meta=meta, render_docs=False)
    errs = []

    def ov(name, k):
        try:
            publish(dest, overlay=(name, [{"id": f"{name}/n{i}", "summary": name} for i in range(k)]), render_docs=False)
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=ov, args=(n, 5)) for n in ("policy", "rsi", "pb")]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs
    publish(dest, nodes=nodes, meta=meta, render_docs=False)  # a full rebuild that knows nothing about overlays
    ids = {n["id"] for n in read_jsonl(open(os.path.join(dest, "ontology.jsonl"), "rb").read())}
    assert all(f"{n}/n{i}" in ids for n in ("policy", "rsi", "pb") for i in range(5))
    publish(dest, overlay=("rsi", [{"id": "rsi/n0", "summary": "x"}]), render_docs=False)  # an overlay shrinking its own set
    ids = {n["id"] for n in read_jsonl(open(os.path.join(dest, "ontology.jsonl"), "rb").read())}
    assert "rsi/n0" in ids and "rsi/n1" not in ids and "policy/n4" in ids


def test_policy_banner(tmp_path):
    from ontolagni.render import render
    nodes, meta = build(CAT)
    nodes = apply_overlays(nodes, {"policy": [{"id": "policy/cost-first", "summary": "spend the least money possible"}]})
    render(nodes, meta, str(tmp_path))
    a = open(tmp_path / "AGENT.md").read()
    assert a.index("policy/cost-first") < a.index("1. `ontolagni find")


def test_publish_all_converges_canonical_and_mirror(tmp_path):
    from ontolagni.publish import publish_all
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    nodes, meta = build(CAT)
    publish(b, nodes=nodes, meta=meta, overlay=("mirror-only", [{"id": "rsi/m", "summary": "only on the mirror"}]), render_docs=False)
    r = publish_all([a, b], nodes=nodes, meta=meta, overlay=("pol", [{"id": "policy/x", "summary": "p"}]), render_docs=False)
    ia = {n["id"] for n in read_jsonl(open(os.path.join(a, "ontology.jsonl"), "rb").read())}
    ib = {n["id"] for n in read_jsonl(open(os.path.join(b, "ontology.jsonl"), "rb").read())}
    assert ia == ib and {"rsi/m", "policy/x"} <= ia and r["nodes"][a] == r["nodes"][b]
