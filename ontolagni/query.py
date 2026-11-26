"""Query the ontology. Loads one small JSONL; everything in-memory; no network."""
from __future__ import annotations
import difflib, hashlib, json, math, os, pickle, re
from bisect import bisect_left
from collections import defaultdict

TOK = re.compile(r"[a-z0-9.]+")
SPLIT = re.compile(r"[a-z]+|\d+(?:\.\d+)*")
DATE8 = re.compile(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])")
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12}
_FULL = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
         "december"]
MONTH_WORDS = {w: i + 1 for i, w in enumerate(_FULL)}
MONTH_WORDS.update({k: v for k, v in MONTHS.items()}); MONTH_WORDS["sept"] = 9
MONTH_RE = "|".join(sorted(MONTH_WORDS, key=len, reverse=True))
MD = re.compile(rf"\b({MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")
DM = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_RE})\b")
MONLY = re.compile(rf"\b({'|'.join(w for w in MONTH_WORDS if len(w) > 3 or w in ('oct', 'nov', 'dec', 'sep'))})\b")
ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
# alias -> extra query terms (weighted down). Hardware generation names, tool names, common abbreviations.
ALIAS = {
    "blackwell": ["b300"], "hopper": ["h100"], "ampere": ["a100"], "a10": ["a10g"], "rtx": ["g7e"],
    "nsight": ["ncu", "nsys", "profile"], "ncu": ["profile"], "nsys": ["profile"], "profiler": ["profile"],
    "traces": ["trace", "profile"], "trace": ["profile"], "checkpoint": ["ckpt"], "ckpt": ["checkpoint"],
    "drafter": ["draft", "spec"], "speculative": ["spec"], "spec": ["draft"], "kv": ["cache"],
    "gemma4": ["gemma"], "qwen3": ["qwen"], "glm5": ["glm"], "k3": ["kimi"], "deepseek": ["dsrehearsal", "q36"],
    "dialog": ["dialogs"], "dialogs": ["dialog", "transcripts"], "transcripts": ["dialogs"],
    "benchmark": ["bench"], "benchmarks": ["bench"], "stdout": ["log"], "logs": ["log"], "log": ["logs"],
}
# UI words: people say vis / viz / dashboard / page / viewer / ui for the same thing. Every one finds the others.
_UI = ["vis", "viz", "visualization", "visualisation", "visualize", "dashboard", "dashboards", "viewer", "ui",
       "webpage", "page", "site", "board", "localhost"]
for _w in _UI:
    ALIAS.setdefault(_w, [])
    ALIAS[_w] += [x for x in ("vis", "visualization", "dashboard", "ui") if x != _w]
# who used how much: usage, spend, tokens, seats, lanes
for _w, _a in {"usage": ["tokens", "spend", "cost"], "spend": ["usage", "cost"], "cost": ["usage", "spend"],
               "tokens": ["usage"], "claude": ["usage", "seats"], "claudes": ["claude", "usage", "seats"],
               "percent": ["usage", "share"], "share": ["usage"], "lane": ["lanes", "seat"],
               "lanes": ["lane", "seats"], "seat": ["seats", "lane"], "seats": ["seat", "lanes"]}.items():
    ALIAS.setdefault(_w, [])
    ALIAS[_w] += _a
# hardware vendors -> the chips we name things by; low-level code words; money words
for _w, _a in {"amd": ["mi300x", "mi350x", "mi355x", "rocm", "amddroplet"], "nvidia": ["h100", "h200", "b200", "b300", "cuda"],
               "intel": ["arc", "b390", "xpu"], "assembly": ["sass", "asm", "ptx"], "asm": ["sass", "assembly", "ptx"],
               "sass": ["asm", "assembly"], "ptx": ["sass", "asm"], "money": ["spend", "cost", "usage"],
               "spent": ["spend", "usage", "cost"], "paid": ["spend", "cost"], "bill": ["spend", "cost", "usage"],
               "key": ["keys", "ssh"], "keys": ["key", "ssh"], "box": ["boxes"], "boxes": ["box"],
               "optimization": ["lever", "levers", "gains"], "optimizations": ["lever", "levers", "gains"],
               "tricks": ["levers"], "wins": ["levers", "gains"], "competitors": ["companies", "leaders"],
               "competitor": ["companies"], "forefront": ["leaders", "companies"], "leaders": ["companies"],
               "companies": ["leaders"]}.items():
    ALIAS.setdefault(_w, [])
    ALIAS[_w] += [x for x in _a if x not in ALIAS[_w]]
HINT = ("ontolagni find matches node ids, READMEs, summaries and tags only, never file contents. "
        "Next: `ontolagni find ops search` (the search runbook), then `tracedb search` (full text).")
STOP = {"the", "a", "an", "of", "for", "in", "on", "to", "and", "or", "all", "any", "show", "me", "where", "are",
        "is", "what", "which", "find", "get", "latest", "happened", "from", "with", "my", "our"}
ROOT_WORDS = {"data": "dataset", "logs": "logs", "log": "logs", "research": "research", "experiments": "experiment",
              "experiment": "experiment", "dataset": "dataset", "datasets": "dataset", "reports": "report"}
W_LEAF, W_PATH, W_TAG, W_KEY, W_FMT = 3.0, 2.0, 1.5, 0.6, 0.3
W_TEXT = 0.25  # page body (ops/memory pages carry it): a word deep in a page still finds it, below any id/summary match


def toks(s: str):
    return TOK.findall(s.lower())


def subtoks(t: str):
    """Extra index terms for one token: the date inside 20261021t0506z, and the letter prefix of qwen3.8 / drafterft."""
    out = []
    m = DATE8.search(t)
    if m and m.group() != t:
        out.append(m.group())
    parts = SPLIT.findall(t)
    if len(parts) > 1 and len(parts[0]) >= 3 and parts[0].isalpha() and parts[0] != t:
        out.append(parts[0])
    return out


class Onto:
    _CACHED = ("meta", "nodes", "_inv", "_len", "_idt", "_avg", "_sz", "_vocab", "_years", "_maxfiles")

    def __init__(self, dir_: str):
        self.dir = dir_
        cache = self._cache_path(dir_)
        if cache:
            try:
                with open(cache, "rb") as f:
                    self.__dict__.update(pickle.load(f))
                return
            except Exception:
                pass
        self._build(dir_)
        if cache:  # building parses ~17k nodes (1-2 s); the pickle loads in a fraction of that
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                tmp = f"{cache}.{os.getpid()}"
                with open(tmp, "wb") as f:
                    pickle.dump({k: getattr(self, k) for k in self._CACHED}, f, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(tmp, cache)
                for old in os.listdir(os.path.dirname(cache)):  # drop caches of older ontology versions
                    if old.startswith(os.path.basename(cache).split("-")[0]) and old != os.path.basename(cache):
                        try:
                            os.remove(os.path.join(os.path.dirname(cache), old))
                        except OSError:
                            pass
            except OSError:
                pass

    @staticmethod
    def _cache_path(dir_: str):
        """Built-index cache keyed by the ontology files' size+mtime and this module's source (a code change rebuilds).
        ONTOLAGNI_CACHE=0 disables it."""
        if os.environ.get("ONTOLAGNI_CACHE", "1") == "0":
            return None
        try:
            st = [os.stat(os.path.join(dir_, f)) for f in ("ontology.jsonl", "meta.json")]
            code = os.stat(__file__)
        except OSError:
            return None
        where = hashlib.sha1(os.path.abspath(dir_).encode()).hexdigest()[:10]
        ver = hashlib.sha1(repr([(s.st_size, s.st_mtime_ns) for s in st] + [code.st_size, code.st_mtime_ns]).encode()).hexdigest()[:12]
        root = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        return os.path.join(root, "ontolagni", f"{where}-{ver}.pkl")

    def _build(self, dir_: str):
        with open(os.path.join(dir_, "meta.json")) as f:
            self.meta = json.load(f)
        self.nodes: dict[str, dict] = {}
        with open(os.path.join(dir_, "ontology.jsonl")) as f:
            for l in f:
                n = json.loads(l)
                self.nodes[n["id"]] = n
        self._inv: dict[str, list] = defaultdict(list)
        self._len: dict[str, float] = {}
        self._idt: dict[str, set] = {}
        memo: dict = {}

        def expand(text):  # tokens + sub-tokens as (term, mult); memoised: path components repeat a lot
            r = memo.get(text)
            if r is None:
                ws = toks(text.replace("_", " ").replace("-", " "))
                r = memo[text] = (tuple(ws), tuple((t, 1.0) for t in ws) +
                                  tuple((x, 0.8) for t in ws for x in subtoks(t)))
            return r
        for i, n in self.nodes.items():
            wtf: dict[str, float] = {}

            def add(text, w):
                ws, ex = expand(text)
                for t, m in ex:
                    wtf[t] = wtf.get(t, 0.0) + w * m
                return ws
            comps = i.split("/")
            idt: set = set()
            for k, c in enumerate(comps):
                idt.update(add(c, W_LEAF if k == len(comps) - 1 and k > 0 else (0.4 if k == 0 else W_PATH)))
            for f_ in ("model", "chip", "kind", "topic", "date"):
                if n.get(f_):
                    add(str(n[f_]), W_TAG)
            add(" ".join(n.get("keys", [])), W_KEY)
            for f_ in ("project", "source"):
                if n.get(f_):
                    add(str(n[f_]), W_TAG)
            if n.get("summary"):
                add(n["summary"], W_KEY)
            if n.get("synthetic"):
                add(" ".join(str(n.get(f_, "")) for f_ in ("alias", "provider", "purpose", "host_kind", "cpu", "os", "lifecycle")), W_TAG)
                add(" ".join(str(x) for f_ in ("gpu", "tags") for x in (n.get(f_) or [])), W_TAG)
            if n.get("skill"):
                add(f"skill skills {n['skill']} " + ("user installed" if n.get("user_installed") else "repo local"), W_TAG)
            for f_ in n.get("formats", {}):
                add(f_, W_FMT)
            self._idt[i] = idt
            self._len[i] = sum(wtf.values())  # body text is left out of the length: a long page must not bury its own id
            if n.get("text"):
                add(n["text"], W_TEXT)
            for w, c in wtf.items():
                self._inv[w].append((i, c))
        self._avg = (sum(self._len.values()) / max(len(self._len), 1)) or 1
        # saturate once at load: query time is then just idf * weight * (precomputed tf part)
        for w, ps in self._inv.items():
            self._inv[w] = [(i, c * 2.2 / (c + 1.2 * (0.25 + 0.75 * self._len[i] / self._avg))) for i, c in ps]
        self._sz = {i: 1.0 + 0.08 * math.log10(1 + n["files"]) for i, n in self.nodes.items()}
        self._vocab = sorted(self._inv)
        self._years = sorted({w[:4] for w in self._inv if len(w) == 8 and DATE8.fullmatch(w)}, reverse=True)
        self._maxfiles = max((n["files"] for n in self.nodes.values()), default=1)

    # -------------------------------------------------------------- query parsing
    def _prefix_terms(self, w):
        lo = bisect_left(self._vocab, w)
        out = []
        while lo < len(self._vocab) and self._vocab[lo].startswith(w) and len(out) < 64:
            out.append(self._vocab[lo]); lo += 1
        return out

    def _parse(self, text: str):
        """-> list of (term, weight, kind). kind: 'exact' | 'prefix'."""
        q = text.lower()
        terms: list = []
        spans = []
        for m in ISO.finditer(q):
            terms.append((m.group(1) + m.group(2) + m.group(3), 3.0)); spans.append(m.span())
        for rx, mi, di in ((MD, 1, 2), (DM, 2, 1)):
            for m in rx.finditer(q):
                mo, d = MONTH_WORDS[m.group(mi)], int(m.group(di))
                if 1 <= d <= 31:
                    for y in self._years[:2] or ["2026"]:
                        terms.append((f"{y}{mo:02d}{d:02d}", 3.0 if y == (self._years or ["2026"])[0] else 1.5))
                    spans.append(m.span())
        q2 = list(q)
        for a, b in spans:
            for k in range(a, b):
                q2[k] = " "
        q = "".join(q2)
        for m in MONLY.finditer(q):  # bare month ("in october"): match any date in that month
            if True:
                for y in self._years[:2]:
                    terms.append(("~" + f"{y}{MONTH_WORDS[m.group(1)]:02d}", 1.0))
                q = q[:m.start()] + " " * (m.end() - m.start()) + q[m.end():]
        raw = [w.strip(".") for w in toks(q)]  # "flash." / "droplet..." at the end of a sentence
        raw = [w for w in raw if w]
        words = [w for w in raw if w not in STOP or len(raw) == 1]
        seen = set()
        for w in words:
            if w in seen:
                continue
            seen.add(w)
            terms.append((w, 1.0))
            for a in ALIAS.get(w, ()):
                terms.append((a, 0.6))
            if w.endswith("s") and len(w) > 4 and w[:-1] not in seen:
                terms.append((w[:-1], 0.6))
            terms += self._repair(w)
        return terms, words

    def _repair(self, w: str) -> list:
        """Extra terms for words people type that are not index terms as written: a typo ("visualzation"), two words
        run together ("gaplanes" -> gap + lanes), or one part of an id written as one token ("droplet" in amddroplet,
        "next" in flashnext)."""
        if len(w) < 4 or w.isdigit() or not w[0].isalpha():
            return []
        out = []
        if len(self._inv.get(w, ())) <= 2:  # unknown or nearly so ("gaplanes" in one stray note): try repairs too
            best = None
            for i in range(3, len(w) - 2):
                a, b = w[:i], w[i:]
                if a in self._inv and b in self._inv and (best is None or min(len(a), len(b)) > min(map(len, best))):
                    best = (a, b)
            if best:
                out += [(best[0], 1.0), (best[1], 1.0)]
            if len(w) >= 5:
                cands = [v for L in range(len(w) - 2, len(w) + 3) for v in self._by_len().get((w[0], L), ())]
                out += [(c, 1.0) for c in difflib.get_close_matches(w, cands, n=2, cutoff=0.84) if c != w]
        inside = [v for v in self._vocab if w in v and not v.startswith(w) and v != w]
        if 0 < len(inside) <= 200:  # a word inside a few ids; skip near-universal fragments
            out += [(v, 0.5) for v in inside[:48]]
        return out

    def _by_len(self):
        """(first letter, length) -> alphabetic vocabulary terms, for typo repair. Built on first use, not cached."""
        b = getattr(self, "_bylen", None)
        if b is None:
            b = defaultdict(list)
            for v in self._vocab:
                if v.isalpha():
                    b[(v[0], len(v))].append(v)
            self._bylen = b
        return b

    def find(self, text: str = "", kind=None, model=None, chip=None, campaign=None, depth=None, limit=10):
        q_raw = text.strip().lower()
        terms, words = self._parse(text)
        N = len(self.nodes)
        scores: dict[str, float] = defaultdict(float)
        hit_terms: dict[str, set] = defaultdict(set)
        want_kind = {ROOT_WORDS[w] for w in words if w in ROOT_WORDS}
        nterms = 0
        multi = len(words) > 1
        for term, weight in terms:
            if term.startswith("~"):
                post, tw = [(i, c) for k in self._prefix_terms(term[1:]) for i, c in self._inv[k]], weight
            else:
                post, tw = self._inv.get(term), weight
                if not post and len(term) >= 3 and weight >= 1.0:  # agents type partial ids
                    post = [(i, c) for k in self._prefix_terms(term) for i, c in self._inv[k]]
                    tw = weight * 0.7
            if not post:
                continue
            if weight >= 1.0:
                nterms += 1
            if len(post) > 0.3 * N and multi:
                continue  # near-universal term: ~zero idf, but scanning it costs O(N)
            idf = math.log(1 + (N - len(post) + .5) / (len(post) + .5))
            k = tw * idf
            if weight >= 1.0:
                for i, c in post:
                    scores[i] += k * c
                    hit_terms[i].add(term)
            else:
                for i, c in post:
                    scores[i] += k * c
        pool = scores if (terms or q_raw) else {i: 0.0 for i in self.nodes}
        if not terms and not q_raw:
            pool = {i: 0.0 for i in self.nodes}
        out = []
        inv_nterms = 1.0 / max(nterms, 1)
        for i, s in pool.items():
            n = self.nodes[i]
            if kind and n.get("kind") != kind: continue
            if model and n.get("model") != model: continue
            if chip and n.get("chip") != chip: continue
            if campaign and not (i == campaign or i.startswith(campaign.rstrip("/") + "/")): continue
            if depth and n["depth"] != depth: continue
            if not depth and n["depth"] == 1: continue  # roots are navigation, not answers
            if s > 0:
                cov = len(hit_terms[i]) * inv_nterms
                s *= (0.4 + 0.6 * cov * cov) * self._sz[i]  # coordination (explain the whole query) x size sanity
                if want_kind and n.get("kind") in want_kind:
                    s *= 1.3
                if n.get("kind") == "ops":
                    s *= 1.6  # ops pages are the curated "how/where is X" answers: they beat a raw path match
            out.append((-s, n["depth"], i))
        out.sort()
        out = out[:max(limit, 40)]
        if words or "/" in q_raw:  # exact-id / full-path-coverage boosts, only for the shortlist
            qp = q_raw.strip("/")
            nw = len(words)
            for k, (ms, d, i) in enumerate(out):
                s = -ms
                if "/" in q_raw and (i == qp or i.startswith(qp + "/")):
                    s += 50.0 - d  # exact id / path-prefix wins outright
                elif nw and nw <= len(self._idt[i]) and all(w in self._idt[i] for w in words):
                    s *= 1.25  # every query word is in the id path
                out[k] = (-s, d, i)
            out.sort()
        res = [self.card(self.nodes[i], -s) for s, _, i in out[:limit]]
        if words and not res:  # never answer with an empty list: say what find cannot see and where to look next
            q = " ".join(words)
            res = [{"id": None, "kind": "hint", "note": HINT,
                    "next": {"runbook": "ontolagni find ops search", "search": f"tracedb search '{q}' --limit 20"}}]
        return res

    def where(self, path: str):
        """Longest-prefix owner chain for a path or prefix."""
        p = path.strip("/").split("/")
        for d in range(min(len(p), 8), 0, -1):
            g = "/".join(p[:d])
            if g in self.nodes:
                chain = []
                cur = g
                while cur:
                    chain.append(cur)
                    cur = self.nodes[cur].get("parent")
                return [self.card(self.nodes[c]) for c in chain]
        return []

    def show(self, id_: str):
        n = self.nodes.get(id_)
        if not n:
            return None
        c = self.card(n)
        c["children"] = n.get("children", [])
        c["keys"] = n.get("keys", [])
        return c

    def card(self, n, score=None):
        c = {"id": n["id"], "kind": n.get("kind"), "files": n["files"], "bytes": n["bytes"],
             "formats": n["formats"]}
        for k in ("model", "chip", "date", "topic", "ts_min", "ts_max", "project", "source", "summary", "readme",
                  "alias", "provider", "key_vault", "ssh", "user", "key", "proxy", "host_kind", "purpose", "status", "docs", "hostname"):
            if k in n: c[k] = n[k]
        if score is not None: c["score"] = round(score, 3)
        # exact next step for the agent: always plan first, never pull blindly
        if n.get("synthetic"):
            c["next"] = {"docs": [f"tracedb get {d} --head 4096" for d in n.get("docs", [])[:5]],
                         "search": f"tracedb search {n.get('alias', n['id'])} --limit 10"}
            return c
        c["next"] = {"list": f"tracedb ls {n['id']}/ --limit 50", "summary": f"tracedb summary {n['id']} --depth 1",
                     "est_raw_bytes": n["bytes"]}
        return c


def verify(onto: "Onto", catalog_lines) -> dict:
    """Correctness: rebuild from the catalog and compare every node digest, file count and byte count."""
    from .build import build
    nodes, meta = build(catalog_lines)
    want = {n["id"]: n for n in nodes}
    bad, missing, extra = [], [], []
    for i, n in want.items():
        o = onto.nodes.get(i)
        if o is None:
            missing.append(i)
        elif (o["digest"], o["files"], o["bytes"]) != (n["digest"], n["files"], n["bytes"]):
            bad.append(i)
    extra = [i for i in onto.nodes if i not in want and not onto.nodes[i].get("synthetic")]
    return {"ok": not (bad or missing or extra), "bad": bad[:20], "missing": missing[:20], "extra": extra[:20],
            "catalog_digest_match": meta["catalog_digest"] == onto.meta["catalog_digest"]}
