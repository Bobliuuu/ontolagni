import json
from ontolagni.build import build, load_scope_exclude


def cat(*paths):
    return [json.dumps({"path": p, "sha": "s" + p, "size": 10}) for p in paths]


def test_excluded_subtrees_are_left_out(tmp_path):
    lines = cat("repos/keep/a.py", "repos/fun/b.py", "repos/fun/x/c.py", "repos/funny/d.py", "traces/t/e.jsonl")
    nodes, meta = build(lines, exclude=["repos/fun"])
    ids = {n["id"] for n in nodes}
    assert "repos/fun" not in ids and "repos/fun/x" not in ids
    assert "repos/funny" in ids and "repos/keep" in ids  # prefix match is per path segment
    repos = next(n for n in nodes if n["id"] == "repos")
    assert repos["files"] == 2 and "repos/fun" not in repos["children"]
    assert meta["files"] == 3 and meta["scope_excluded_files"] == 2 and meta["scope_exclude"] == ["repos/fun"]


def test_policy_file(tmp_path):
    p = tmp_path / "POLICY.json"
    p.write_text(json.dumps({"exclude": [], "scope_exclude": ["repos/a/", "traces/b"]}))
    assert load_scope_exclude(str(p)) == ["repos/a", "traces/b"]
    assert load_scope_exclude("", "") == []


def test_no_exclude_is_unchanged():
    lines = cat("repos/a/x.py", "repos/b/y.py")
    assert build(lines)[0] == build(lines, exclude=[])[0]


def test_carry_does_not_bring_excluded_back():
    from ontolagni.build import carry
    nodes, _ = build(cat("repos/keep/a.py"), exclude=["repos/fun"])
    prev = [json.dumps({"id": "repos/fun", "files": 1}), json.dumps({"id": "rsi/x", "summary": "overlay"})]
    out, st = carry(nodes, prev, exclude=["repos/fun"])
    ids = {n["id"] for n in out}
    assert "repos/fun" not in ids and "rsi/x" in ids and st["carried"] == 1
