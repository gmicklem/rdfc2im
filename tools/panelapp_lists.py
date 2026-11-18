#!/usr/bin/env python3
"""Genomics England PanelApp gene lists for a hybrid HumanMine [im-9n4.21].

HumanMine has public lists named `PL_GenomicsEngland_GenePanel:<Panel_name>`, made in December 2021 from the
Genomics England PanelApp (https://panelapp.genomicsengland.co.uk/): one per panel, Green (high confidence)
genes only. No code that made them survives. This tool makes them again from whatever PanelApp serves today,
under the same names (BlueGenes hard-codes `PL_GenomicsEngland_GenePanel:Radial_dysplasia` as an example).

  fetch   --out DIR [--cache-dir CACHE]   every current panel of the PanelApp v1 API, raw JSON, plus META.json
  lists   --in DIR --out DIR [--mine URL] the list definitions (name, description, tags, Green genes)
  resolve --in DIR --mine URL --out FILE  read-only check of how the genes resolve in a mine (/service/ids)

Policy (decided by the project owner): all panels the API lists, Green genes only (confidence_level "3"), each
panel's PanelApp version in the list description. STRs and regions are not genes: counted, not listed.

PanelApp has no stated rate limit; the fetch makes sequential requests, at most 2 per second, with the User-Agent
`rdfc2im-panelapp-lists/1.0` and back-off on 429 and 5xx. Terms of use: see BUILD.md (the PDF is the site's only
statement); the cached group is saved with redistributable=false.

Standard library only (rdfc2im.rawcache is imported only for --cache-dir).
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://panelapp.genomicsengland.co.uk/api/v1"
USER_AGENT = "rdfc2im-panelapp-lists/1.0"
MIN_INTERVAL = 0.5            # seconds between requests: at most 2 per second
RETRIES = 5
CACHE_GROUP = "panelapp"
GREEN = "3"                   # PanelApp confidence_level of a Green (high confidence) gene

LIST_PREFIX = "PL_GenomicsEngland_GenePanel:"
LIST_TYPE = "Gene"
LIST_TAGS = ["Genomics England gene panel", "im:public"]
# The 2021 text, "Decemeber" corrected; the version, date and count are appended per panel.
DESCRIPTION_TEXT = ("Gene panel from the Genomics England PanelApp. Only genes with a high level of confidence "
                    "(Green level) are included.")
# Attribution and usage limits, the last sentences of every PanelApp list description. PanelApp Terms of Use
# (December 2019): s.1.4 says GEL's status (and that of any identified contributors) as the authors of PanelApp and its
# content must always be acknowledged; s.1.1 says no commercial use (including commercial research) and no diagnostic
# use, medical decision-making or providing a healthcare service, unless there is a separate agreement with GEL.
# The userprofile description column is an unbounded text, so the length is not constrained.
ATTRIBUTION_TEXT = ("Source: Genomics England PanelApp (https://panelapp.genomicsengland.co.uk/); content authored by "
                    "Genomics England and its contributors, used under the PanelApp Terms of Use (December 2019). "
                    "Non-commercial use only; not for diagnostic use or medical decision-making.")
# The order the project owner asked for: HGNC id first, then Ensembl GRCh38 id, then symbol.
ID_ORDER = ("hgnc_id", "ensembl_id", "symbol")


class FetchError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- HTTP layer

class Http:
    """GET JSON, politely: sequential, MIN_INTERVAL apart, retried with back-off on 429, 5xx and network errors.
    Tests inject any object with get_json(url) and a `requests` counter instead."""

    def __init__(self, min_interval=MIN_INTERVAL, retries=RETRIES, sleep=time.sleep, urlopen=urllib.request.urlopen,
                 clock=time.monotonic, user_agent=USER_AGENT):
        self.min_interval, self.retries, self.sleep, self.urlopen = min_interval, retries, sleep, urlopen
        self.clock, self.user_agent = clock, user_agent
        self.requests = 0
        self._last = None

    def get_json(self, url, timeout=120):
        delay = 2.0
        for attempt in range(self.retries + 1):
            if self._last is not None:
                wait = self.min_interval - (self.clock() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = self.clock()
            self.requests += 1
            retry_after = None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent,
                                                           "Accept": "application/json"})
                with self.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500:
                    raise FetchError(f"GET {url}: HTTP {e.code}") from e
                err = f"HTTP {e.code}"
                ra = e.headers.get("Retry-After") if e.headers else None
                retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                err = f"{type(e).__name__}: {e}"
            if attempt == self.retries:
                raise FetchError(f"GET {url}: giving up after {attempt + 1} attempts ({err})")
            self.sleep(retry_after if retry_after is not None else delay)
            delay *= 2


# ---------------------------------------------------------------------------------------------- helpers

def dump_json(path, obj):
    """Canonical JSON (sorted keys, UTF-8, trailing newline): the same input always gives the same bytes."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, sort_keys=True, ensure_ascii=False, indent=1)
        fh.write("\n")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def list_pages(http, url):
    """Every result of a paginated list endpoint, following `next`."""
    results, seen = [], set()
    while url:
        if url in seen:
            raise FetchError(f"pagination loop at {url}")
        seen.add(url)
        page = http.get_json(url)
        if "results" not in page:
            raise FetchError(f"{url}: no 'results' in the response")
        results.extend(page["results"])
        url = page.get("next")
    return results


def green_genes(panel):
    """The panel's Green genes (entity_type gene, confidence_level "3"), in the API's order."""
    return [g for g in panel.get("genes", []) if str(g.get("confidence_level")) == GREEN
            and g.get("entity_type", "gene") == "gene"]


def green_records(panel):
    """The Green genes of a panel as gene records, each gene once (a super panel repeats the genes of its children),
    in the API's order. Defined after gene_record below; looked up at call time."""
    out, seen = [], set()
    for g in green_genes(panel):
        rec = gene_record(g)
        key = rec["hgnc_id"] or ("symbol:" + str(rec["symbol"]))
        if key not in seen:
            seen.add(key)
            out.append(rec)
    return out


def panel_summary(index_entry, panel):
    """The per-panel line of META.json."""
    return {"id": panel["id"], "name": panel["name"], "version": panel["version"],
            "version_created": panel["version_created"], "status": panel.get("status"),
            "types": sorted(t["slug"] for t in panel.get("types", [])),
            "genes_all": len(panel.get("genes", [])), "genes_green_rows": len(green_genes(panel)),
            "genes_green": len(green_records(panel)),
            "strs": len(panel.get("strs", [])), "regions": len(panel.get("regions", [])),
            "is_super_panel": any(t["slug"] == "super-panel" for t in panel.get("types", []))}


# ---------------------------------------------------------------------------------------------- fetch

def fetch(out_dir, http=None, today=None, log=print, resume=True):
    """Fetch every panel the API lists into out_dir: panels/<id>.json, panels-index.json, signedoff-index.json,
    META.json. With resume, a panel file already there at the version the index lists is not fetched again."""
    http = http or Http()
    today = today or datetime.date.today().isoformat()
    started = time.time()
    index = list_pages(http, f"{API_BASE}/panels/")
    index.sort(key=lambda p: p["id"])
    ids = [p["id"] for p in index]
    if len(set(ids)) != len(ids):
        raise FetchError("the panel index lists a panel id twice")
    signedoff = list_pages(http, f"{API_BASE}/panels/signedoff/")
    dump_json(os.path.join(out_dir, "panels-index.json"), index)
    dump_json(os.path.join(out_dir, "signedoff-index.json"), sorted(signedoff, key=lambda p: (p["id"], str(p.get("version")))))
    summaries, skipped = [], 0
    for n, entry in enumerate(index, 1):
        path = os.path.join(out_dir, "panels", f"{entry['id']}.json")
        panel = None
        if resume and os.path.exists(path):
            old = load_json(path)
            if old.get("version") == entry["version"] and old.get("version_created") == entry["version_created"]:
                panel, skipped = old, skipped + 1
        if panel is None:
            panel = http.get_json(f"{API_BASE}/panels/{entry['id']}/")
            if panel.get("id") != entry["id"]:
                raise FetchError(f"panel {entry['id']}: the API answered with panel {panel.get('id')}")
            dump_json(path, panel)
        summaries.append(panel_summary(entry, panel))
        if n % 50 == 0:
            log(f"  fetched {n}/{len(index)} panels, {http.requests} requests")
    meta = {"source": "Genomics England PanelApp", "api_base": API_BASE, "fetch_date": today,
            "user_agent": USER_AGENT, "panels": len(summaries), "panels_resumed_from_disk": skipped,
            "signed_off_entries": len(signedoff), "requests": http.requests,
            "genes_green_total": sum(s["genes_green"] for s in summaries),
            "genes_green_rows_total": sum(s["genes_green_rows"] for s in summaries),
            "strs_total": sum(s["strs"] for s in summaries), "regions_total": sum(s["regions"] for s in summaries),
            "seconds": round(time.time() - started, 1), "panel_list": summaries}
    dump_json(os.path.join(out_dir, "META.json"), meta)
    return meta


# ---------------------------------------------------------------------------------------------- lists

# The 2021 lists were named by replacing each space of the panel name by "_" and leaving every other character
# alone (checked on the 154 panels whose name has not changed since: tests/test_panelapp_lists.py). The one
# character that rule would carry into a name and that no 2021 name has is "/", which breaks BlueGenes' list URLs;
# it becomes "_". Nothing else in a current panel name needs an exception.
NAME_CHAR_EXCEPTIONS = {"/": "_"}

# 17 panels that were in HumanMine's 2021 set were renamed in PanelApp (panel id -> the 2021 list-name suffix).
# Found by comparing the 2021 member lists with the current Green genes and the names: see
# baselines/panelapp-2026-11-18-vs-2021.md. The list follows the panel's current name; `replaces` in the list
# definition names the 2021 list so that the upload (T2.3) can retire it.
RENAMED_SINCE_2021 = {
    134: "Arrhythmogenic_cardiomyopathy",
    260: "Auditory_Neuropathy_Spectrum_Disorder",
    13: "Brugada_syndrome",
    230: "Cataracts",
    168: "Craniosynostosis",
    293: "Diabetes_-_neonatal_onset",
    9: "Disorders_of_sex_development",
    53: "Ehlers_Danlos_syndromes",
    480: "Familial_hyperparathyroidism",
    402: "Genetic_epilepsy_syndromes",
    126: "Hearing_loss",
    49: "Hypertrophic_cardiomyopathy_-_teen_and_adult",
    185: "Limb_girdle_muscular_dystrophy",
    83: "Membranoproliferative_glomerulonephritis",
    398: "Primary_immunodeficiency",
    98: "Segmental_overgrowth_disorders",
    243: "Tumour_predisposition_-_childhood_onset",
}
PANEL_SELECTIONS = {"all": None, "100k": "rare-disease-100k"}   # --select: all panels, or HumanMine's 2021 type


def list_suffix(panel_name):
    """The `<Panel_name>` of a list name: spaces to underscores (leading and trailing ones dropped, runs
    collapsed), every other character kept except the ones in NAME_CHAR_EXCEPTIONS."""
    s = "_".join(panel_name.split())
    for a, b in NAME_CHAR_EXCEPTIONS.items():
        s = s.replace(a, b)
    return s


def list_name(panel_name):
    return LIST_PREFIX + list_suffix(panel_name)


def file_stem(name):
    """File name for a list: `:` as `__` like the 2021 archive, anything outside [A-Za-z0-9._,&()-] as `_`."""
    return re.sub(r"[^A-Za-z0-9._,&()-]", "_", name.replace(":", "__"))


def ensembl_grch38(gene_data):
    """(ensembl gene id, release) from gene_data.ensembl_genes.GRch38, the newest release; (None, None) if none."""
    eg = gene_data.get("ensembl_genes")
    if isinstance(eg, str):                 # some genes carry the string "{}" instead of an object
        try:
            eg = json.loads(eg)
        except ValueError:
            eg = None
    rels = (eg.get("GRch38") if isinstance(eg, dict) else None) or {}
    best = None
    for rel, v in (rels.items() if isinstance(rels, dict) else ()):
        eid = v.get("ensembl_id") if isinstance(v, dict) else None
        if not eid:
            continue
        key = int(rel) if str(rel).isdigit() else -1
        if best is None or key > best[0]:
            best = (key, eid, str(rel))
    return (best[1], best[2]) if best else (None, None)


def gene_record(g):
    gd = g.get("gene_data") or {}
    eid, rel = ensembl_grch38(gd)
    sym = gd.get("gene_symbol") or g.get("entity_name")
    return {"hgnc_id": gd.get("hgnc_id") or None, "symbol": sym, "ensembl_grch38": eid, "ensembl_release": rel,
            "hgnc_symbol": gd.get("hgnc_symbol") or None, "biotype": gd.get("biotype") or None}


def candidate_identifiers(rec):
    """[(kind, value)] in the order a lookup tries them: HGNC id, Ensembl GRCh38 id, symbol; missing ones skipped."""
    vals = {"hgnc_id": rec.get("hgnc_id"), "ensembl_id": rec.get("ensembl_grch38"), "symbol": rec.get("symbol")}
    return [(k, vals[k]) for k in ID_ORDER if vals[k]]


def description(panel, fetch_date, now_named=False):
    """now_named: the list keeps its 2021 name, so say what PanelApp calls the panel now."""
    note = (f" PanelApp now names this panel \"{panel['name']}\"; the list keeps the name it had in 2021."
            if now_named else "")
    return (f"{DESCRIPTION_TEXT} Panel {panel['id']}, version {panel['version']} "
            f"(created {panel['version_created'][:10]}), fetched {fetch_date}. "
            f"See https://panelapp.genomicsengland.co.uk/panels/{panel['id']}/ for more details.{note} {ATTRIBUTION_TEXT}")


def build_list(panel, fetch_date, keep_2021_names=False):
    """The list definition of one panel: name, description, tags, Green genes (deduplicated, API order)."""
    genes = green_records(panel)
    old = RENAMED_SINCE_2021.get(panel["id"])
    suffix = old if (keep_2021_names and old) else list_suffix(panel["name"])
    return {"name": LIST_PREFIX + suffix, "type": LIST_TYPE, "tags": list(LIST_TAGS),
            "description": description(panel, fetch_date, bool(keep_2021_names and old)),
            "replaces": (LIST_PREFIX + old) if old and not keep_2021_names else None,
            "panel": {"id": panel["id"], "name": panel["name"], "version": panel["version"],
                      "version_created": panel["version_created"], "disease_group": panel.get("disease_group"),
                      "types": sorted(t["slug"] for t in panel.get("types", []))},
            "counts": {"genes_green": len(genes), "genes_other_confidence": len(panel.get("genes", [])) - len(green_genes(panel)),
                       "strs_ignored": len(panel.get("strs", [])), "regions_ignored": len(panel.get("regions", []))},
            "genes": genes}


def read_panels(in_dir):
    meta = load_json(os.path.join(in_dir, "META.json"))
    panels = [load_json(os.path.join(in_dir, "panels", f"{p['id']}.json")) for p in meta["panel_list"]]
    return meta, sorted(panels, key=lambda p: p["id"])


def select_panels(panels, select):
    slug = PANEL_SELECTIONS[select]
    return [p for p in panels if slug is None or any(t["slug"] == slug for t in p.get("types", []))]


def mine_list_names(mine, http=None):
    """Names of the lists a mine serves to an anonymous reader (GET /service/lists, read-only)."""
    http = http or Http(min_interval=0)
    return {l["name"] for l in http.get_json(mine.rstrip("/") + "/service/lists?format=json").get("lists", [])}


def make_lists(in_dir, out_dir, mine=None, select="all", keep_2021_names=False, http=None):
    meta, panels = read_panels(in_dir)
    panels = select_panels(panels, select)
    lists = [build_list(p, meta["fetch_date"], keep_2021_names) for p in panels]
    names = [l["name"] for l in lists]
    if len(set(names)) != len(names):
        raise FetchError("two panels would get the same list name: " +
                         ", ".join(sorted({n for n in names if names.count(n) > 1})))
    existing = mine_list_names(mine, http) if mine else None
    index = []
    for l in lists:
        dump_json(os.path.join(out_dir, "lists", file_stem(l["name"]) + ".json"), l)
        index.append({"name": l["name"], "file": "lists/" + file_stem(l["name"]) + ".json", "panel_id": l["panel"]["id"],
                      "panel_name": l["panel"]["name"], "version": l["panel"]["version"],
                      "genes": l["counts"]["genes_green"], "replaces": l["replaces"],
                      "exists_in_mine": None if existing is None else l["name"] in existing})
    dump_json(os.path.join(out_dir, "index.json"), {"fetch_date": meta["fetch_date"], "select": select,
                                                    "mine": mine, "lists": index})
    with open(os.path.join(out_dir, "index.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("name\tpanel_id\tversion\tgenes\treplaces\texists_in_mine\n")
        for r in index:
            fh.write("\t".join(str(x if x is not None else "") for x in (
                r["name"], r["panel_id"], r["version"], r["genes"], r["replaces"], r["exists_in_mine"])) + "\n")
    return index


# ---------------------------------------------------------------------------------------------- resolve

JOB_BATCH = 1000          # identifiers per /service/ids job
JOB_POLL_SECONDS = 1.0
JOB_TIMEOUT = 600


class MineHttp:
    """JSON over HTTP to a mine: GET, POST (JSON body) and DELETE. Injectable for tests."""

    def __init__(self, urlopen=urllib.request.urlopen, sleep=time.sleep, retries=3):
        self.urlopen, self.sleep, self.retries = urlopen, sleep, retries

    def request(self, method, url, body=None, timeout=300):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(self.retries + 1):
            try:
                with self.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method),
                                  timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    try:
                        return json.loads(raw) if raw.strip() else {}
                    except ValueError:
                        return {"raw": raw.strip()}
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == self.retries:
                    raise FetchError(f"{method} {url}: HTTP {e.code} {e.read()[:300]!r}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise FetchError(f"{method} {url}: {e}") from e
            self.sleep(5 * (attempt + 1))

    def get_json(self, url):
        return self.request("GET", url)


def wait_for_mine(mine, http, max_wait=2400, sleep=time.sleep, log=print):
    """Block until GET /service/version answers (a mine being rebuilt is down for a while); FetchError if it
    does not within max_wait seconds. An outage is never a result."""
    waited = 0
    while True:
        try:
            http.request("GET", mine.rstrip("/") + "/service/version")
            return
        except FetchError:
            if waited >= max_wait:
                raise
            log(f"  {mine} is not answering; waiting ({waited} s so far)")
            sleep(30)
            waited += 30


def run_ids_job(mine, identifiers, http, organism="H. sapiens", type_="Gene", sleep=time.sleep, log=print):
    """Resolve identifiers with the mine's id resolution service (POST /service/ids, poll the status, read the
    results, delete the job). Returns the raw `results` object. Read-only as far as the mine's data goes."""
    base = mine.rstrip("/") + "/service/ids"
    body = {"identifiers": list(identifiers), "type": type_, "caseSensitive": False, "wildCards": False}
    if organism:
        body["extra"] = organism
    uid = http.request("POST", base, body)["uid"]
    waited = 0.0
    try:
        while True:
            status = http.request("GET", f"{base}/{uid}/status").get("status")
            if status == "SUCCESS":
                break
            if status == "ERROR":
                raise FetchError(f"id resolution job {uid} failed: {http.request('GET', f'{base}/{uid}/status')}")
            if waited > JOB_TIMEOUT:
                raise FetchError(f"id resolution job {uid} still {status} after {JOB_TIMEOUT} s")
            sleep(JOB_POLL_SECONDS)
            waited += JOB_POLL_SECONDS
        return http.request("GET", f"{base}/{uid}/results")["results"]
    finally:
        try:
            http.request("DELETE", f"{base}/{uid}")
        except FetchError:
            pass


def parse_ids_results(results):
    """{input identifier (lower case): {"genes": [object ids], "categories": [...], "reasons": [...]}} for the
    identifiers the job could place, plus the set of unresolved inputs (lower case); "summaries" maps an object id
    to the mine's summary fields for it (symbol, primaryIdentifier, ...).
    MATCH: matched the object's own key field; DUPLICATE: several objects; OTHER/TYPE_CONVERTED/WILDCARD: the
    service's issue categories, e.g. a match through a synonym ("OTHER", reason "Synonym")."""
    found = {}

    def add(ident, gene_id, cat, reason=None, summary=None):
        e = found.setdefault(ident.lower(), {"genes": [], "categories": [], "reasons": [], "summaries": {}})
        if gene_id is not None and gene_id not in e["genes"]:
            e["genes"].append(gene_id)
        if summary:
            e["summaries"][gene_id] = summary
        if cat not in e["categories"]:
            e["categories"].append(cat)
        if reason and reason not in e["reasons"]:
            e["reasons"].append(reason)

    matches = results.get("matches", {})
    for m in matches.get("MATCH", []):
        for ident in m.get("input", []):
            add(ident, m["id"], "MATCH", summary=m.get("summary"))
    for cat, entries in matches.items():
        if cat == "MATCH":
            continue
        for issue in entries:
            for m in issue.get("matches", []):
                add(issue["input"], m["id"], cat, issue.get("reason"), m.get("summary"))
    unresolved = {u.lower() for u in results.get("unresolved", []) if isinstance(u, str)}
    for u in results.get("unresolved", []):
        if isinstance(u, dict):
            unresolved.add(str(u.get("input", u)).lower())
    for ident in list(found):
        if not found[ident]["genes"]:
            unresolved.add(ident)
            del found[ident]
    return found, unresolved


def resolve_values(mine, values, http, organism, sleep=time.sleep, log=print):
    """{value (lower case): outcome} for a set of identifier strings; outcome is
    {"status": "unique"|"ambiguous"|"unresolved", "genes": [...], "categories": [...], "reasons": [...]}."""
    values = sorted(set(values))
    out = {}
    for i in range(0, len(values), JOB_BATCH):
        batch = values[i:i + JOB_BATCH]
        for attempt in range(4):
            wait_for_mine(mine, http, sleep=sleep, log=log)
            try:
                results = run_ids_job(mine, batch, http, organism, sleep=sleep, log=log)
                break
            except FetchError as e:
                if attempt == 3:
                    raise
                log(f"  job failed ({e}); checking the mine and trying again")
        found, unresolved = parse_ids_results(results)
        for v in batch:
            k = v.lower()
            if k in found:
                e = found[k]
                out[k] = dict(e, status="unique" if len(e["genes"]) == 1 else "ambiguous")
            else:
                out[k] = {"status": "unresolved", "genes": [], "categories": [], "reasons": [], "summaries": {}}
        log(f"  job {i // JOB_BATCH + 1}: {len(batch)} identifiers, {len(found)} placed, {len(unresolved)} not found")
    return out


def explain(rec, outcomes):
    """Why a gene did not resolve cleanly, as far as PanelApp's own data and the three outcomes can tell."""
    why = []
    if not rec.get("hgnc_id"):
        why.append("no HGNC id in PanelApp")
    if not rec.get("ensembl_grch38"):
        why.append("no Ensembl GRCh38 id in PanelApp")
    if rec.get("hgnc_symbol") and rec.get("symbol") and rec["hgnc_symbol"] != rec["symbol"]:
        why.append(f"PanelApp symbol {rec['symbol']} differs from its HGNC symbol {rec['hgnc_symbol']}")
    if rec.get("biotype") and rec["biotype"] != "protein_coding":
        why.append(f"biotype {rec['biotype']}")
    for kind in ID_ORDER:
        o = outcomes.get(kind)
        if o and o["status"] == "ambiguous":
            why.append(f"{kind} matches {len(o['genes'])} genes")
    return why


def pct(a, b):
    return round(100.0 * a / b, 2) if b else None


def resolve(in_dir, mine, out_file, http=None, organism="H. sapiens", select="all", sleep=time.sleep, log=print):
    """Check read-only how the Green genes of every panel resolve in a mine: each identifier type on its own,
    then the chain HGNC id -> Ensembl GRCh38 id -> symbol. Writes out_file (JSON) and out_file + '.unresolved.tsv'."""
    http = http or MineHttp()
    meta, panels = read_panels(in_dir)
    panels = select_panels(panels, select)
    per_panel = {p["id"]: green_records(p) for p in panels}
    values = {kind: set() for kind in ID_ORDER}
    for recs in per_panel.values():
        for r in recs:
            for kind, v in candidate_identifiers(r):
                values[kind].add(v)
    wait_for_mine(mine, http, sleep=sleep, log=log)
    version = http.get_json(mine.rstrip("/") + "/service/version")
    if not isinstance(version, dict):
        version = {"version": version}
    version.setdefault("version", version.get("raw"))
    log(f"mine {mine}: version {version.get('version')}; identifiers: " +
        ", ".join(f"{k} {len(v)}" for k, v in values.items()))
    outcome = {kind: resolve_values(mine, values[kind], http, organism, sleep, log) for kind in ID_ORDER}

    tallies = lambda: {"genes": 0, **{k: {"have": 0, "unique": 0, "ambiguous": 0, "unresolved": 0, "unique_by_category": {}} for k in ID_ORDER},
                       "chain": {"resolved": 0, "by_hgnc_id": 0, "by_ensembl_id": 0, "by_symbol": 0,
                                 "fallback": 0, "ambiguous": 0, "unresolved": 0, "conflict": 0}}
    total, panel_stats, problems = tallies(), {}, []
    distinct = {}
    for p in panels:
        t = tallies()
        for r in per_panel[p["id"]]:
            outs = {}
            for kind, v in candidate_identifiers(r):
                outs[kind] = outcome[kind][v.lower()]
            chain_kind = next((k for k in ID_ORDER if k in outs and outs[k]["status"] == "unique"), None)
            genes_found = sorted({g for o in outs.values() if o["status"] == "unique" for g in o["genes"]})
            conflict = len(genes_found) > 1
            if chain_kind is None:
                status = "ambiguous" if any(o["status"] == "ambiguous" for o in outs.values()) else "unresolved"
            else:
                status = "resolved"
            first = next(iter(candidate_identifiers(r)), (None,))[0]
            fallback = status == "resolved" and chain_kind != "hgnc_id"
            for tl in (t, total):
                tl["genes"] += 1
                for kind in ID_ORDER:
                    if kind in outs:
                        tl[kind]["have"] += 1
                        tl[kind][outs[kind]["status"]] += 1
                        if outs[kind]["status"] == "unique":
                            cat = "+".join(outs[kind]["categories"])
                            tl[kind]["unique_by_category"][cat] = tl[kind]["unique_by_category"].get(cat, 0) + 1
                c = tl["chain"]
                if status == "resolved":
                    c["resolved"] += 1
                    c["by_" + chain_kind] += 1
                    c["fallback"] += fallback
                else:
                    c[status] += 1
                c["conflict"] += conflict
            key = r["hgnc_id"] or r["symbol"]
            distinct.setdefault(key, (r, outs, status, chain_kind, conflict))
            if status != "resolved" or fallback or conflict or any(
                    outs.get(k, {}).get("status") == "ambiguous" for k in ID_ORDER):
                problems.append({"panel_id": p["id"], "panel": p["name"], "symbol": r["symbol"], "hgnc_id": r["hgnc_id"],
                                 "ensembl": r["ensembl_grch38"], "status": status if not fallback else "resolved-by-fallback",
                                 "resolved_by": chain_kind, "conflict": conflict,
                                 "outcomes": {k: {"status": o["status"], "genes": o["genes"], "categories": o["categories"],
                                                  "reasons": o["reasons"]} for k, o in outs.items()},
                                 "why": explain(r, outs)})
        panel_stats[str(p["id"])] = {"name": p["name"], **t}
    dtotal = {"distinct_genes": len(distinct),
              "chain_unresolved": sum(1 for v in distinct.values() if v[2] == "unresolved"),
              "chain_ambiguous": sum(1 for v in distinct.values() if v[2] == "ambiguous"),
              "chain_fallback": sum(1 for v in distinct.values() if v[2] == "resolved" and v[3] != "hgnc_id"),
              "conflicts": sum(1 for v in distinct.values() if v[4]),
              "by_identifier": {k: {st: sum(1 for v in distinct.values() if k in v[1] and v[1][k]["status"] == st)
                                    for st in ("unique", "ambiguous", "unresolved")} for k in ID_ORDER}}
    result = {"mine": mine, "mine_version": version.get("version"), "fetch_date": meta["fetch_date"],
              "run_date": datetime.date.today().isoformat(), "select": select, "organism": organism,
              "id_order": list(ID_ORDER), "identifiers_submitted": {k: len(v) for k, v in values.items()},
              "total": total, "distinct": dtotal, "panels": panel_stats, "problems": problems}
    dump_json(out_file, result)
    with open(out_file + ".unresolved.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("panel_id\tpanel\tsymbol\thgnc_id\tensembl_grch38\tstatus\tresolved_by\tconflict\thgnc_outcome\t"
                 "ensembl_outcome\tsymbol_outcome\twhy\n")
        for pr in problems:
            o = pr["outcomes"]
            cell = lambda k: (o[k]["status"] + (":" + "/".join(o[k]["categories"]) if o[k]["categories"] else "")) if k in o else "absent"
            fh.write("\t".join(str(x) for x in (pr["panel_id"], pr["panel"], pr["symbol"], pr["hgnc_id"] or "", pr["ensembl"] or "",
                                                pr["status"], pr["resolved_by"] or "", "yes" if pr["conflict"] else "",
                                                cell("hgnc_id"), cell("ensembl_id"), cell("symbol"),
                                                "; ".join(pr["why"]))) + "\n")
    # one row per distinct gene: what T2.3 needs to upload (the mine's own identifier for each gene)
    with open(out_file + ".genes.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("hgnc_id\tsymbol\tensembl_grch38\tstatus\tresolved_by\tmine_object_id\tmine_primaryIdentifier\tmine_symbol\t"
                 "hgnc_outcome\tensembl_outcome\tsymbol_outcome\tpanelapp_hgnc_symbol\tbiotype\n")
        for key in sorted(distinct, key=str):
            r, outs, status, chain_kind, conflict = distinct[key]
            gid = sm = pid = msym = ""
            if chain_kind:
                o = outs[chain_kind]
                gid = o["genes"][0]
                sm = o.get("summaries", {}).get(gid, {})
                pid, msym = sm.get("primaryIdentifier", ""), sm.get("symbol", "")
            fh.write("\t".join(str(x) for x in (r["hgnc_id"] or "", r["symbol"] or "", r["ensembl_grch38"] or "", status,
                                                chain_kind or "", gid, pid, msym,
                                                *(("absent" if k not in outs else outs[k]["status"] + (
                                                    ":" + "+".join(outs[k]["categories"]) if outs[k]["categories"] else ""))
                                                  for k in ID_ORDER),
                                                r.get("hgnc_symbol") or "", r.get("biotype") or "")) + "\n")
    return result


# ---------------------------------------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="fetch every current panel")
    f.add_argument("--out", required=True)
    f.add_argument("--cache-dir", help="also save DIR as the rdfc2im cache group 'panelapp' here")
    f.add_argument("--no-resume", action="store_true", help="fetch every panel even if its file is already in --out")
    f.add_argument("--min-interval", type=float, default=MIN_INTERVAL)
    ls = sub.add_parser("lists", help="build the list definitions")
    ls.add_argument("--in", dest="in_dir", required=True)
    ls.add_argument("--out", required=True)
    ls.add_argument("--mine", help="read the names of the lists the mine already has (anonymous GET /service/lists)")
    ls.add_argument("--select", choices=sorted(PANEL_SELECTIONS), default="all",
                    help="all panels (policy), or only the 'rare-disease-100k' type that HumanMine's 2021 set was")
    ls.add_argument("--keep-2021-names", action="store_true", help="name the 17 renamed panels' lists as in 2021")
    r = sub.add_parser("resolve", help="read-only check of how the genes resolve in a mine")
    r.add_argument("--in", dest="in_dir", required=True)
    r.add_argument("--mine", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--organism", default="H. sapiens")
    r.add_argument("--select", choices=sorted(PANEL_SELECTIONS), default="all")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "fetch":
            meta = fetch(a.out, Http(min_interval=a.min_interval), resume=not a.no_resume)
            print(f"fetched {meta['panels']} panels, {meta['requests']} requests, {meta['genes_green_total']} Green gene entries, "
                  f"{meta['strs_total']} STRs and {meta['regions_total']} regions (ignored), {meta['seconds']} s")
            if a.cache_dir:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from rdfc2im import rawcache
                info = rawcache.save(CACHE_GROUP, a.out, a.cache_dir, meta={
                    "source": "PanelApp v1 API", "api_base": API_BASE, "fetch_date": meta["fetch_date"],
                    "panels": str(meta["panels"]), "redistributable": "false",
                    "licence": "Genomics England PanelApp Terms of Use (Dec 2019), not read: see BUILD.md"})
                print(f"cached group {CACHE_GROUP}: {info['files']} files, {info['bytes']} bytes in {a.cache_dir}")
        elif a.cmd == "lists":
            index = make_lists(a.in_dir, a.out, a.mine, a.select, a.keep_2021_names)
            print(f"{len(index)} lists, {sum(r['genes'] for r in index)} gene entries in {a.out}")
        else:
            res = resolve(a.in_dir, a.mine, a.out, organism=a.organism, select=a.select)
            c = res["total"]["chain"]
            print(f"{res['total']['genes']} gene entries: chain resolved {c['resolved']} (fallback {c['fallback']}), "
                  f"ambiguous {c['ambiguous']}, unresolved {c['unresolved']}; report {a.out}")
    except FetchError as e:
        print(f"panelapp_lists: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
