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
    L = [f"# Ontology: what data exists where", "",
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
        L += ["## Boxes: how to get in", "", "Derived from `~/.ssh/config`. Key material is NOT in this store: private keys live KMS-encrypted in the separate vault store at the `vault key` path (`tracedb --store $VAULT_STORE get <path>`).", "",
              "| alias | provider | user | key | vault key | via | docs |", "|---|---|---|---|---|---|---|"]
        for b in boxes:
            via = (b.get("proxy") or "direct").replace("|", "\\|")[:70]
            docs = ", ".join(f"`{d}`" for d in b.get("docs", [])[:3])
            L.append(f"| `{b['alias']}` | {b.get('provider','?')} | {b.get('user','?')} | `{b.get('key','?')}` | `{b.get('key_vault','-')}` | {via} | {docs} |")
    open(os.path.join(out_dir, "ONTOLOGY.md"), "w").write("\n".join(L) + "\n")

    agent_md = f"""# AGENT.md: ontolagni + traceDB protocol
Store: {store_label or meta.get('store')}  (env TRACEDB_STORE). Auth: AWS profile `lab` / machine role.
1. `ontolagni find <words> [--kind repo|trace|config|box]` -> ranked nodes, each with `next` commands.
2. `tracedb plan <path>` -> bytes/requests, no fetch. Default budget 8 MiB (`TRACEDB_MAX_BYTES`).
3. `tracedb get <path> --head N | --tail N | --start A --end B`.
4. Content questions: `tracedb search "words" [--prefix traces/codex/] [--paths]` -> path, offset, snippet, exact `get` command.
5. Boxes: `ontolagni find <alias>` -> boxes/<alias> (ssh alias, user, key path, vault path, proxy, docs). Use `ssh <alias>`; never print keys. Secrets: separate vault store (env VAULT_STORE, KMS-encrypted); main store holds only redacted text.
Layout: repos/<project>/..  traces/<source>/..  config/..  boxes/<alias> (synthetic)  index/fts.sqlite
Secrets were redacted at ingest as `[REDACTED:*]`; skipped files are listed in config/ingest-skips.jsonl.
`ontolagni verify <catalog.jsonl>` proves this ontology matches the store.
"""
    open(os.path.join(out_dir, "AGENT.md"), "w").write(agent_md)
    idx = {"schema": meta["schema"], "store": store_label or meta.get("store"), "catalog_digest": meta["catalog_digest"],
           "files": meta["files"],
           "roots": {r["id"]: {"files": r["files"], "bytes": r["bytes"]} for r in roots},
           "projects": {c["id"]: {k: c[k] for k in ("files", "bytes", "summary", "readme", "children", "status", "metrics", "mtime_min", "mtime_max", "weekly") if k in c} for c in (kids("repos") if "repos" in by else [])},
           "trace_sources": {c["id"]: {"files": c["files"], "bytes": c["bytes"]} for c in (kids("traces") if "traces" in by else [])},
           "boxes": {b["alias"]: {k: b[k] for k in ("ssh", "user", "key", "key_vault", "proxy", "provider", "docs") if k in b} for b in boxes},
           "recipes": {"find": "ontolagni find <words>", "plan": "tracedb plan <path>", "read": "tracedb get <path> --head 4096",
                       "grep": "tracedb search \"<words>\" --prefix <p>", "box": "ontolagni find <alias> --kind box"}}
    json.dump(idx, open(os.path.join(out_dir, "agent_index.json"), "w"), indent=1, sort_keys=True)
