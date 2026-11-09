import ast, glob, hashlib, json, os, subprocess, sys, time
import pytest
from ontolagni import build, write, Onto, verify

ROOT = os.path.dirname(os.path.dirname(__file__))


def catalog():
    L = []
    def add(p, size, keys=None):
        L.append(json.dumps({"path": p, "sha": hashlib.sha256(p.encode()).hexdigest(), "size": size,
                             "meta": {"keys": keys} if keys else {}}))
    for c in ["deepseek-h100-20260115", "llama-mmlu-a100-20260203", "gemma-2b-l4", "phi-a100-20260301"]:
        for j in range(30):
            add(f"logs/{c}/dispatch/jobs/b2-t{j}-01/vllm.log", 1000 + j)
            add(f"logs/{c}/probe/census/nodes-w{j}.csv", 500)
        add(f"research/{c}/dialogs/agent.jsonl", 9000, ["kind", "role", "text"])
    add("data/sample-h100/batch-v1/prompts.jsonl", 4_000_000, ["prompt", "id"])
    return L


@pytest.fixture(scope="module")
def onto(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("o"))
    nodes, meta = build(catalog())
    write(nodes, meta, d)
    return Onto(d), d


def test_siloed_no_store_imports():
    bad = []
    for f in glob.glob(f"{ROOT}/ontolagni/*.py"):
        for n in ast.walk(ast.parse(open(f).read())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                   [n.module or ""] if isinstance(n, ast.ImportFrom) and n.level == 0 else []
            for m in mods:
                if m.split(".")[0] not in sys.stdlib_module_names and m.split(".")[0] != "ontolagni":
                    bad.append((f, m))
    assert not bad, bad


def test_derived_fields(onto):
    o, _ = onto
    n = o.nodes["logs/deepseek-h100-20260115"]
    assert n["model"] == "deepseek" and n["chip"] == "h100" and n["date"] == "20260115" and n["kind"] == "logs"
    assert o.nodes["logs/llama-mmlu-a100-20260203"]["chip"] == "a100"
    assert "date" not in o.nodes["logs/gemma-2b-l4"]  # nothing invented


def test_find_ranks_and_filters(onto):
    o, _ = onto
    r = o.find("deepseek vllm logs")
    assert r[0]["id"].startswith("logs/deepseek-h100-20260115")
    assert all(x["chip"] == "a100" for x in o.find("", chip="a100", depth=2) if "chip" in x)
    assert o.find("dialogs agent")[0]["id"].endswith("dialogs") or "dialogs" in o.find("dialogs agent")[0]["id"]
    assert o.find("prompt")[0]["id"].startswith("data/sample-h100")  # matched via schema keys
    assert o.find("zzzznotthere") == []


def test_where_longest_prefix(onto):
    o, _ = onto
    w = o.where("logs/deepseek-h100-20260115/dispatch/jobs/b2-t3-01/vllm.log")
    ids = [x["id"] for x in w]
    assert ids[0] == "logs/deepseek-h100-20260115/dispatch/jobs"  # deepest owner (max_depth=4)
    assert ids[-2:] == ["logs/deepseek-h100-20260115", "logs"]
    assert o.where("nonexistent/x") == []


def test_cards_always_carry_cost_and_plan_first(onto):
    o, _ = onto
    c = o.find("deepseek")[0]
    assert c["next"]["est_raw_bytes"] == c["bytes"] and "tracedb ls" in c["next"]["list"]


def test_verify_correct_then_detects_drift(onto):
    o, d = onto
    assert verify(o, catalog())["ok"]
    drift = catalog()
    r = json.loads(drift[0]); r["sha"] = "0" * 64; drift[0] = json.dumps(r)
    v = verify(o, drift)
    assert not v["ok"] and "logs/deepseek-h100-20260115" in v["bad"]
    v2 = verify(o, catalog()[:-1])
    assert not v2["ok"]


def test_quick_load_and_query(tmp_path):
    # 40k-node scale (10x real: ~3.8k; field-weighted index build is part of load) must still load+query fast
    lines = []
    for c in range(400):
        for j in range(50):
            p = f"logs/camp{c}-b300-2026{(c%12)+1:02d}01/seat{j}/jobs/job{j}/x.log"
            lines.append(json.dumps({"path": p, "sha": hashlib.sha256(p.encode()).hexdigest(), "size": 10}))
    nodes, meta = build(lines); write(nodes, meta, str(tmp_path))
    t = time.process_time(); o = Onto(str(tmp_path)); load = time.process_time() - t  # CPU time: robust to a loaded box
    t = time.process_time()
    for _ in range(50): o.find("camp77 seat3 x log")
    q = (time.process_time() - t) / 50
    assert load < 1.5 and q < 0.02, (load, q, len(o.nodes))


def test_cli_roundtrip(tmp_path):
    cat = tmp_path / "c.jsonl"; cat.write_text("\n".join(catalog()))
    env = {**os.environ, "PYTHONPATH": ROOT}
    run = lambda *a: subprocess.run([sys.executable, "-m", "ontolagni.cli", "--dir", str(tmp_path / "o"), *a],
                                    capture_output=True, text=True, env=env)
    assert run("build", str(cat)).returncode == 0
    assert run("verify", str(cat)).returncode == 0
    out = json.loads(run("find", "deepseek").stdout)
    assert out and out[0]["id"].startswith("logs/deepseek")
