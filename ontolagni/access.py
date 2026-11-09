"""Box-access nodes from an ssh config: how to get into every box. Derived only from the config text and the docs
that mention each alias; nothing guessed. Output nodes are synthetic (no catalog digest) under id boxes/<alias>.
Private keys are never read: only the IdentityFile *path* is recorded."""
from __future__ import annotations
import re

HINTS = [("ssm", "aws-ssm"), ("vast", "vast.ai"), ("runpod", "runpod"), ("lambda", "lambda-labs"), ("csclub", "uwaterloo-csclub"),
         ("csc-", "uwaterloo-csclub"), ("tiramisu", "uwaterloo-csclub"), ("wato", "wato-cluster"), ("slam", "gcp"),
         ("googleusercontent", "gcp"), ("amazonaws", "aws"), ("g7e", "aws"), ("tenpct", "aws-ssm"), ("rdf2", "vast.ai"),
         ("spark", "dgx-spark")]


def parse_ssh_config(text: str) -> list[dict]:
    hosts, cur = [], None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"(?i)^(\S+)\s*[= ]\s*(.+)$", line)
        if not m:
            continue
        k, v = m.group(1).lower(), m.group(2).strip()
        if k == "host":
            cur = {"aliases": v.split(), "opts": {}}; hosts.append(cur)
        elif k == "match":
            cur = None
        elif cur is not None:
            cur["opts"].setdefault(k, v)
    return hosts


def box_nodes(config_texts: dict, docs: dict) -> list[dict]:
    """config_texts: {store_path: ssh-config text}; docs: {store_path: text} (any docs that may mention aliases)."""
    nodes, seen = {}, {}
    for src, text in config_texts.items():
        for h in parse_ssh_config(text):
            o = h["opts"]
            for alias in h["aliases"]:
                if "*" in alias or "?" in alias or alias == "!":
                    continue
                n = nodes.get(alias)
                new = {"id": f"boxes/{alias}", "alias": alias, "kind": "box", "ssh": f"ssh {alias}",
                       "hostname": o.get("hostname", alias), "user": o.get("user"), "key": o.get("identityfile"),
                       "proxy": o.get("proxycommand") or o.get("proxyjump"), "port": o.get("port")}
                new = {k: v for k, v in new.items() if v}
                if n is None:
                    nodes[alias] = new; seen[alias] = [src]
                else:  # same alias in several config files: keep first, fill gaps, remember sources
                    for k, v in new.items():
                        n.setdefault(k, v)
                    seen[alias].append(src)
    for alias, n in nodes.items():
        low = (alias + " " + n.get("hostname", "") + " " + (n.get("proxy") or "")).lower()
        for needle, prov in HINTS:
            if needle in low:
                n["provider"] = prov; break
        k = n.get("key", "")
        if k.startswith("~/.ssh/"):  # private key lives encrypted in the vault store (KMS), same relative path
            n["key_vault"] = "home/ssh/" + k[len("~/.ssh/"):]
        n["config_files"] = sorted(set(seen[alias]))
        generic = len(alias) < 5 and not re.search(r"[0-9-]", alias)
        pat = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(alias)}(?![A-Za-z0-9_-])")
        docs_l = [] if generic else [p for p, t in docs.items() if pat.search(t)]
        n["docs"] = sorted(set(docs_l) | set(seen[alias]))[:25]
        n["purpose"] = f"how to reach {alias}"
        n["text"] = " ".join([alias, n.get("provider", ""), n.get("hostname", ""), "ssh box host access login connect"])
    return list(nodes.values())
