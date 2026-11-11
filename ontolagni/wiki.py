"""Human wiki: one self-contained static index.html from ontology.jsonl (tree browser, search, per-node page, box table).
No server logic: any static file server works. IP-like strings are masked so the page never carries host addresses."""
from __future__ import annotations
import json, os, re

IP = re.compile(r"(?<!\d)\d{1,3}(?:\.\d{1,3}){3}(?!\d)")
KEEP = ("id", "kind", "parent", "bytes", "files", "depth", "children", "formats", "summary", "readme", "provider", "user", "key",
        "key_vault", "proxy", "docs", "ssh", "alias")


def _mask(v):
    if isinstance(v, str):
        return IP.sub("<ip>", v)
    if isinstance(v, list):
        return [_mask(x) for x in v]
    if isinstance(v, dict):
        return {_mask(k): _mask(x) for k, x in v.items()}
    return v


def build_wiki(nodes, meta, out_dir, store_label=""):
    os.makedirs(out_dir, exist_ok=True)
    slim, seen = [], set()
    for n in nodes:
        m = {k: _mask(n[k]) for k in KEEP if k in n}
        if m.get("id") and m["id"] not in seen:
            seen.add(m["id"]); slim.append(m)
    data = {"meta": {k: meta.get(k) for k in ("files", "nodes", "catalog_digest", "schema")}, "store": store_label or meta.get("store", ""),
            "nodes": slim}
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    open(os.path.join(out_dir, "index.html"), "w").write(PAGE.replace("__DATA__", blob))
    return len(slim)


PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Ontolagni wiki</title>
<style>
:root{--bg:#fff;--fg:#1b1f24;--mut:#6a737d;--line:#d8dee4;--acc:#0b5fff;--card:#f6f8fa}
@media(prefers-color-scheme:dark){:root{--bg:#0f1318;--fg:#e6e9ee;--mut:#8b95a1;--line:#2a313a;--acc:#6ea0ff;--card:#171c23}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;display:flex;height:100vh}
#side{width:340px;min-width:260px;border-right:1px solid var(--line);display:flex;flex-direction:column}
#side header{padding:12px;border-bottom:1px solid var(--line)}#q{width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
#tree{overflow:auto;padding:6px 8px;flex:1}main{flex:1;overflow:auto;padding:20px 28px;max-width:1000px}
.n{cursor:pointer;padding:2px 4px;border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.n:hover{background:var(--card)}.n.sel{background:var(--card);color:var(--acc)}
.t{display:inline-block;width:14px;color:var(--mut)}.sz{color:var(--mut);font-size:12px;margin-left:6px}
code,pre{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font:12.5px ui-monospace,monospace}pre{padding:8px;overflow:auto}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left}a{color:var(--acc);cursor:pointer}
.mut{color:var(--mut)}h1{font-size:20px;margin:0 0 4px}.bar{height:8px;background:var(--acc);border-radius:2px}
@media(max-width:700px){body{flex-direction:column}#side{width:100%;height:45vh}}
</style>
<div id=side><header><b>Ontolagni</b> <span class=mut id=stat></span><br><input id=q placeholder="search nodes: tenpct g7e oom…" autocomplete=off></header><div id=tree></div></div>
<main id=main></main>
<script id=d type=application/json>__DATA__</script>
<script>
const N=JSON.parse(document.getElementById('d').textContent),by={};N.nodes.forEach(n=>by[n.id]=n);
const h=n=>{for(const u of['B','KB','MB','GB','TB']){if(n<1024||u=='TB')return(u=='B'?n:n.toFixed(1))+u;n/=1024}};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const kids=n=>(n.children||[]).map(c=>by[c]).filter(Boolean).sort((a,b)=>(b.bytes||0)-(a.bytes||0));
const roots=N.nodes.filter(n=>n.depth==1).sort((a,b)=>(b.bytes||0)-(a.bytes||0));
const open=new Set();let sel=null;
document.getElementById('stat').textContent=N.meta.files.toLocaleString()+' files · '+N.nodes.length+' nodes';
function row(n,d){const k=kids(n),o=open.has(n.id);let s=`<div class="n${sel==n.id?' sel':''}" style="padding-left:${d*14}px" data-id="${esc(n.id)}"><span class=t data-t=1>${k.length?(o?'▾':'▸'):''}</span>${esc(n.id.split('/').pop()||n.id)}<span class=sz>${n.bytes?h(n.bytes):''}</span></div>`;
 if(o)k.forEach(c=>s+=row(c,d+1));return s}
function tree(){const q=document.getElementById('q').value.trim().toLowerCase();let t=document.getElementById('tree');
 if(q){const w=q.split(/\s+/);const r=N.nodes.filter(n=>{const x=(n.id+' '+(n.summary||'')+' '+(n.alias||'')).toLowerCase();return w.every(a=>x.includes(a))}).sort((a,b)=>(b.bytes||0)-(a.bytes||0)).slice(0,200);
  t.innerHTML=r.map(n=>`<div class="n" data-id="${esc(n.id)}">${esc(n.id)}<span class=sz>${n.bytes?h(n.bytes):''}</span></div>`).join('')||'<span class=mut>no match</span>'}
 else t.innerHTML=roots.map(n=>row(n,0)).join('')}
document.getElementById('tree').onclick=e=>{const r=e.target.closest('.n');if(!r)return;const id=r.dataset.id;
 if(e.target.dataset.t||!document.getElementById('q').value){open.has(id)?open.delete(id):open.add(id)}show(id)};
document.getElementById('q').oninput=tree;
function show(id,push=true){const n=by[id];if(!n)return;sel=id;if(push)location.hash=encodeURIComponent(id);
 let p=n.parent;while(p&&by[p]){open.add(p);p=by[p].parent}tree();
 const k=kids(n),mx=Math.max(1,...k.map(c=>c.bytes||0));let s=`<h1>${esc(n.id)}</h1><div class=mut>${esc(n.kind||'')} · ${(n.files||0).toLocaleString()} files · ${h(n.bytes||0)}</div>`;
 const crumbs=[];p=n.parent;while(p&&by[p]){crumbs.unshift(p);p=by[p].parent}if(crumbs.length)s+='<p>'+crumbs.map(c=>`<a data-go="${esc(c)}">${esc(c.split('/').pop())}</a>`).join(' / ')+'</p>';
 if(n.summary)s+=`<p>${esc(n.summary)}</p>`;
 if(n.kind=='box'&&n.alias){s+=`<h3>Access</h3><table>${['ssh','user','key','key_vault','proxy','provider'].filter(f=>n[f]).map(f=>`<tr><th>${f}</th><td><code>${esc(n[f])}</code></td></tr>`).join('')}</table>`;
  if(n.docs)s+='<h3>Mentioned in</h3>'+n.docs.map(d=>`<div><code>${esc(d)}</code></div>`).join('')}
 if(n.formats&&Object.keys(n.formats).length)s+='<h3>Formats</h3><p>'+Object.entries(n.formats).sort((a,b)=>b[1]-a[1]).map(([f,c])=>`<code>${esc(f)}</code> ${c.toLocaleString()}`).join(' · ')+'</p>';
 if(k.length){s+=`<h3>Children (${k.length})</h3><table>`+k.slice(0,300).map(c=>`<tr><td><a data-go="${esc(c.id)}">${esc(c.id.split('/').pop())}</a></td><td>${(c.files||0).toLocaleString()} files</td><td>${h(c.bytes||0)}</td><td style="width:25%"><div class=bar style="width:${Math.round(100*(c.bytes||0)/mx)}%"></div></td></tr>`).join('')+'</table>'}
 if(n.kind!='box'){s+=`<h3>Fetch</h3><pre>tracedb ls ${esc(n.id)}\ntracedb plan ${esc(n.id)}\ntracedb search "words" --prefix ${esc(n.id)}/${n.readme?`\ntracedb get ${esc(n.readme)} --head 8192`:''}</pre><div class=mut>store: ${esc(N.store)}</div>`}
 document.getElementById('main').innerHTML=s}
document.getElementById('main').onclick=e=>{const a=e.target.closest('[data-go]');if(a)show(a.dataset.go)};
function home(){let s=`<h1>What data exists where</h1><div class=mut>${esc(N.store)} · digest ${esc((N.meta.catalog_digest||'').slice(0,12))}</div><table><tr><th>root</th><th>files</th><th>size</th></tr>`+roots.map(r=>`<tr><td><a data-go="${esc(r.id)}">${esc(r.id)}/</a></td><td>${(r.files||0).toLocaleString()}</td><td>${h(r.bytes||0)}</td></tr>`).join('')+'</table><p class=mut>Pick a node on the left or search. Each page shows the exact traceDB commands to fetch it.</p>';
 document.getElementById('main').innerHTML=s}
addEventListener('hashchange',()=>{const id=decodeURIComponent(location.hash.slice(1));id?show(id,false):home()});
tree();location.hash?show(decodeURIComponent(location.hash.slice(1)),false):home();
</script></html>
"""
