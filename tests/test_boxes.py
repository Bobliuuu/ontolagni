import json
from ontolagni.access import parse_ssh_config, box_nodes
from ontolagni.build import build
from ontolagni.query import Onto, verify
from ontolagni.render import render

CFG = """Host tenpct-g1 tenpct-g2
  HostName host-one.invalid
  User ubuntu
  IdentityFile ~/.ssh/id_x
  ProxyCommand aws ssm start-session --target i-abc
Host gpu
  HostName host-two.invalid
"""


def test_boxes_and_render(tmp_path):
    cat = [json.dumps({"path": "repos/ten-percent/README.md", "sha": "a", "size": 5}),
           json.dumps({"path": "traces/codex/s.jsonl", "sha": "b", "size": 9})]
    boxes = box_nodes({"config/ssh_config.txt": CFG}, {"config/memory/n.md": "use tenpct-g1 for runs; the gpu is fast"})
    assert {b["alias"] for b in boxes} == {"tenpct-g1", "tenpct-g2", "gpu"}
    g1 = next(b for b in boxes if b["alias"] == "tenpct-g1")
    assert g1["provider"] == "aws-ssm" and "config/memory/n.md" in g1["docs"]
    assert next(b for b in boxes if b["alias"] == "gpu")["docs"] == ["config/ssh_config.txt"]  # short generic alias: no fuzzy doc links
    boxes.append({"id": "boxes", "kind": "box", "synthetic": True})
    nodes, meta = build(cat, describe={"repos/ten-percent": {"summary": "the ten percent challenge"}}, extra_nodes=boxes)
    d = str(tmp_path / "o")
    from ontolagni.build import write
    write(nodes, meta, d)
    o = Onto(d)
    assert o.find("tenpct-g1")[0]["id"] == "boxes/tenpct-g1"
    assert o.find("challenge")[0]["id"] == "repos/ten-percent"
    assert verify(o, cat)["ok"]
    render(nodes, meta, str(tmp_path / "r"), "s3://x")
    assert "tenpct-g1" in (tmp_path / "r" / "ONTOLOGY.md").read_text()
    assert "boxes" in json.load(open(tmp_path / "r" / "agent_index.json"))


def test_blob_pointer_counts_real_size():
    cat = [json.dumps({"path": "repos/a/model.bin", "sha": "x", "size": 120, "meta": {"blob": "x", "blob_size": 5000000000}})]
    nodes, _ = build(cat)
    assert next(n for n in nodes if n["id"] == "repos/a")["bytes"] == 5000000000
