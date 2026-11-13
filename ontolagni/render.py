"""Two renderings of one ontology (same source of truth, ontology.jsonl):
  human: ONTOLOGY.md  - readable tree, what each project/source is, sizes, how to ask, box access table.
  agent: AGENT.md (protocol, <2 KB) + agent_index.json (compact, machine-first: roots, projects, sources, boxes, recipes).
"""
from __future__ import annotations
import json, os


def _h(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


def _d(t):
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")


def render(nodes, meta, out_dir, store_label=""):
    os.makedirs(out_dir, exist_ok=True)
    by = {n["id"]: n for n in nodes}
    kids = lambda i: [by[c] for c in by[i].get("children", []) if c in by]
    roots = [n for n in nodes if n["depth"] == 1]
    boxes = sorted((n for n in nodes if n.get("synthetic") and n.get("alias")), key=lambda n: n["alias"])
    policies = sorted((n for n in nodes if n["id"].startswith("policy/") and n.get("summary")), key=lambda n: n["id"])
    pol_lines = [f"- **{n['id']}**: {n['summary']}" for n in policies]
    L = [f"# Ontology: what data exists where", ""] + (["## Policies (apply to every task)", ""] + pol_lines + [""] if pol_lines else []) + [
         f"Store: `{store_label or meta.get('store') or '?'}` · {meta['files']:,} files · {meta['nodes']} nodes · catalog digest `{meta['catalog_digest'][:12]}`", "",
         "Ask in plain words (`ontolagni find tenpct g7e oom`), then fetch with traceDB (`tracedb ls/get`), or search inside files "
         "(`tracedb search 'text'`). Never pull blind: `tracedb plan <path>` first.", "", "## Top level", "",
         "| root | files | size | what |", "|---|---:|---:|---|"]
    what = {"repos": "working trees of every project (code, docs, results, logs), secrets redacted",
            "traces": "agent session traces (Claude Code, Codex, Cursor, project trace dumps)",
            "config": "how to reach boxes, ssh config, per-project memory notes, skills", "index": "full-text search index",
            "boxes": "one node per ssh alias: user, key path, proxy, docs that mention it"}
    for r in roots:
        L.append(f"| `{r['id']}/` | {r['files']:,} | {_h(r['bytes'])} | {what.get(r['id'], '')} |")
    for root, title in (("repos", "Projects (repos/)"), ("traces", "Trace sources (traces/)")):
        if root not in by:
            continue
        L += ["", f"## {title}", ""]
        for c in sorted(kids(root), key=lambda n: -n["bytes"]):
            L.append(f"### `{c['id']}/`  ({c['files']:,} files, {_h(c['bytes'])})")
            if c.get("summary"):
                L += ["", c["summary"]]
            if c.get("mtime_max"):
                L += ["", "Active " + _d(c["mtime_min"]) + " -> " + _d(c["mtime_max"])]
            for k, t in (("status", "Status"), ("metrics", "Numbers")):
                if c.get(k):
                    L += ["", f"{t} (from its README):"] + [f"- {x}" for x in c[k][:5]]
            top = sorted(kids(c["id"]), key=lambda n: -n["bytes"])[:8] if c.get("children") else []
            if top:
                L += ["", "Biggest sub-trees: " + ", ".join(f"`{t['id'].split('/',2)[-1]}` ({_h(t['bytes'])})" for t in top)]
            if c.get("readme"):
                L += ["", f"Read first: `tracedb get {c['readme']} --head 8192`"]
            L.append("")
    if boxes:
        L += ["## Boxes: how to get in", "", "Derived from `~/.ssh/config` plus the box registry (`config/boxes.json`: hardware, status, notes; refresh with `keys boxes probe --publish`). "
              "Key material is NOT in this store: private keys live KMS-encrypted in the separate vault store at the `vault key` path (`keys pull` restores all of them).", "",
              "| alias | status | provider | hardware | shell | user | key | via | notes |", "|---|---|---|---|---|---|---|---|---|"]
        order = {"alive": 0, "auth-failed": 1}
        for b in sorted(boxes, key=lambda b: (order.get(b.get("status"), 2), b.get("lifecycle") == "gone", b["alias"])):
            via = (b.get("jump") or b.get("proxy") or "direct").replace("|", "\\|")[:40]
            hw = "; ".join(b.get("gpu") or []) or (b.get("cpu") or "")
            hw += (f", {b['mem_gb']} GB RAM" if b.get("mem_gb") else "")
            st = (b.get("status") or "?") + (f" ({b['lifecycle']})" if b.get("lifecycle") not in (None, "active") else "")
            notes = " ".join((b.get("notes") or [])[:2]).replace("|", "/")[:160]
            L.append(f"| `{b['alias']}` | {st} | {b.get('provider','?')} | {hw.replace('|', '/')[:70]} | {b.get('shell','')[:10]} | {b.get('user','')} | `{b.get('key','-')}` | {via} | {notes} |")
    skills = sorted((n for n in nodes if n.get("skill")), key=lambda n: (not n.get("user_installed"), n["skill"]))
    if skills:
        L += ["", "## Skills (skills/)", "", "Every Claude Code / agent skill found on any machine, saved by `skills push`. "
              "`U` = the user-level set that `skills pull` installs into `~/.claude/skills/` on every machine.", "",
              "| | skill | variants | installs to | what |", "|---|---|---:|---|---|"]
        for n in skills:
            L.append(f"| {'U' if n.get('user_installed') else ''} | `{n['skill']}` | {len(n.get('variants', []))} | {n.get('installs_to','')} | {(n.get('summary') or '').replace('|', '/')[:140]} |")
    open(os.path.join(out_dir, "ONTOLOGY.md"), "w").write("\n".join(L) + "\n")

    st_ = store_label or meta.get("store") or ""
    setup = (st_.rsplit("/", 1)[0] + "/setup") if st_.startswith("s3://") else "<bucket>/setup"
    pol = ("Policies (apply to every task; `ontolagni show <id>`):\n" + "\n".join(pol_lines) + "\n") if pol_lines else ""
    agent_md = f"""# AGENT.md: ontolagni + traceDB protocol
{pol}Store: {store_label or meta.get('store')}  (env TRACEDB_STORE). Auth: AWS profile `lab` / machine role.
1. `ontolagni find <words> [--kind repo|trace|config|box]` -> ranked nodes, each with `next` commands.
2. `tracedb plan <path>` -> bytes/requests, no fetch. Default budget 8 MiB (`TRACEDB_MAX_BYTES`).
3. `tracedb get <path> --head N | --tail N | --start A --end B`.
4. Content questions: `tracedb search "words" [--prefix traces/codex/] [--paths]` -> path, offset, snippet, exact `get` command.
5. Boxes: `ontolagni find <alias|gpu|provider>` -> boxes/<alias> (ssh alias, status, hardware, shell, key, route, notes; registry config/boxes.json). Use `ssh <alias>`; `keys doctor` checks every box. Never print keys. Secrets: separate vault store (env VAULT_STORE, KMS-encrypted); main store holds only redacted text.
6. Skills: `ontolagni find skills` -> skills/<name> (source repo + commit, installs_to). `skills pull` installs the user set into ~/.claude/skills.
New machine: read {setup}/SETUP.md (`aws s3 cp {setup}/SETUP.md -`): one bootstrap restores keys, creds, ssh config, skills, CLAUDE.md, memory, this ontology.
Layout: repos/<project>/..  traces/<source>/..  config/..  skills/<name>/<variant>/..  boxes/<alias> (synthetic)  index/
Secrets were redacted at ingest as `[REDACTED:*]`; skipped files are listed in config/ingest-skips.jsonl.
`ontolagni verify <catalog.jsonl>` proves this ontology matches the store.
"""
    open(os.path.join(out_dir, "AGENT.md"), "w").write(agent_md)
    idx = {"schema": meta["schema"], "store": store_label or meta.get("store"), "catalog_digest": meta["catalog_digest"],
           "files": meta["files"],
           "roots": {r["id"]: {"files": r["files"], "bytes": r["bytes"]} for r in roots},
           "projects": {c["id"]: {k: c[k] for k in ("files", "bytes", "summary", "readme", "children", "status", "metrics", "mtime_min", "mtime_max", "weekly") if k in c} for c in (kids("repos") if "repos" in by else [])},
           "trace_sources": {c["id"]: {"files": c["files"], "bytes": c["bytes"]} for c in (kids("traces") if "traces" in by else [])},
           "boxes": {b["alias"]: {k: b[k] for k in ("ssh", "user", "key", "key_vault", "proxy", "provider", "docs", "status", "lifecycle", "gpu", "cpu", "mem_gb", "os", "shell", "jump", "notes", "has_main_key", "last_verified", "purpose") if k in b} for b in boxes},
           "skills": {n["skill"]: {k: n[k] for k in ("summary", "installs_to", "user_installed", "variant", "readme") if k in n} for n in skills},
           "recipes": {"find": "ontolagni find <words>", "plan": "tracedb plan <path>", "read": "tracedb get <path> --head 4096",
                       "grep": "tracedb search \"<words>\" --prefix <p>", "box": "ontolagni find <alias> --kind box", "skills": "ontolagni find skills", "new_machine": f"aws s3 cp {setup}/SETUP.md -"}}
    json.dump(idx, open(os.path.join(out_dir, "agent_index.json"), "w"), indent=1, sort_keys=True)
