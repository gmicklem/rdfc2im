"""The gene-symbol lookup cache (scope.resolve_gene_ids) and the RDFC2IM_OFFLINE guard (fetch.py).

Nothing here touches the network: resolvers are stubs, and the one test that reaches the real
_request replaces urllib's opener with one that fails the test if it is ever used.
"""
import os

import pytest

from rdfc2im import fetch
from rdfc2im.scope import resolve_gene_ids


class Resolver:
    """A stand-in resolver; __name__ is part of the cache file name, as for the real ones."""
    def __init__(self, ids, name="resolve_ncbigene_symbols"):
        self.ids, self.calls, self.__name__ = ids, [], name

    def __call__(self, symbols, taxon="9606"):
        self.calls.append((list(symbols), taxon))
        return list(self.ids)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RDFC2IM_OFFLINE", "RDFC2IM_RESOLVER_REFRESH", "RDFC2IM_RESOLVER_CACHE"):
        monkeypatch.delenv(k, raising=False)


def test_first_lookup_resolves_and_saves_the_second_reads_the_cache(tmp_path):
    r, d = Resolver(["1", "2"]), str(tmp_path / "lookup")
    assert resolve_gene_ids(r, ["B", "A"], "9606", d) == ["1", "2"]
    assert len(r.calls) == 1
    (name,) = os.listdir(d)
    assert name.startswith("resolve_ncbigene_symbols-9606-") and name.endswith(".txt")
    assert open(os.path.join(d, name)).read() == "1\n2\n"
    again = Resolver(["never"])
    assert resolve_gene_ids(again, ["A", "B"], "9606", d) == ["1", "2"]   # symbol order is irrelevant
    assert again.calls == []


def test_key_covers_resolver_taxon_and_symbols(tmp_path):
    d = str(tmp_path)
    resolve_gene_ids(Resolver(["1"]), ["A"], "9606", d)
    resolve_gene_ids(Resolver(["2"]), ["A"], "10090", d)
    resolve_gene_ids(Resolver(["3"]), ["A", "B"], "9606", d)
    resolve_gene_ids(Resolver(["4"], "resolve_ensembl_symbols"), ["A"], "9606", d)
    assert len(os.listdir(d)) == 4


def test_refresh_ignores_the_cache_and_overwrites_it(tmp_path, monkeypatch):
    d = str(tmp_path)
    resolve_gene_ids(Resolver(["old"]), ["A"], "9606", d)
    monkeypatch.setenv("RDFC2IM_RESOLVER_REFRESH", "1")
    fresh = Resolver(["new"])
    assert resolve_gene_ids(fresh, ["A"], "9606", d) == ["new"]
    assert len(fresh.calls) == 1
    monkeypatch.delenv("RDFC2IM_RESOLVER_REFRESH")
    assert resolve_gene_ids(Resolver(["x"]), ["A"], "9606", d) == ["new"]


def test_offline_hit_reads_the_cache(tmp_path, monkeypatch):
    d = str(tmp_path)
    resolve_gene_ids(Resolver(["7"]), ["A"], "9606", d)
    monkeypatch.setenv("RDFC2IM_OFFLINE", "1")
    r = Resolver(["never"])
    assert resolve_gene_ids(r, ["A"], "9606", d) == ["7"]
    assert r.calls == []


def test_offline_miss_fails_naming_the_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RDFC2IM_OFFLINE", "1")
    r = Resolver(["never"])
    with pytest.raises(fetch.OfflineError) as e:
        resolve_gene_ids(r, ["A", "B"], "9606", str(tmp_path / "lookup"))
    assert r.calls == []
    msg = str(e.value)
    assert str(tmp_path / "lookup" / "resolve_ncbigene_symbols-9606-") in msg and "2 symbols" in msg
    assert "--offline" in msg
    assert not (tmp_path / "lookup").exists(), "an offline miss must not create anything"


def test_an_empty_answer_is_cached_too(tmp_path):
    d = str(tmp_path)
    resolve_gene_ids(Resolver([]), ["NOSUCH"], "9606", d)
    again = Resolver(["never"])
    assert resolve_gene_ids(again, ["NOSUCH"], "9606", d) == []
    assert again.calls == []


def test_a_failing_resolver_leaves_no_cache_file(tmp_path):
    def boom(symbols, taxon="9606"):
        raise RuntimeError("endpoint down")
    with pytest.raises(RuntimeError):
        resolve_gene_ids(boom, ["A"], "9606", str(tmp_path))
    assert os.listdir(tmp_path) == []


class _NoNetwork:
    def open(self, *a, **k):
        raise AssertionError("a network request was made")


def test_offline_blocks_every_sparql_request_before_urllib(monkeypatch):
    monkeypatch.setenv("RDFC2IM_OFFLINE", "1")
    monkeypatch.setattr(fetch.urllib.request, "build_opener", lambda *a: _NoNetwork())
    with pytest.raises(fetch.OfflineError) as e:
        fetch._request("https://example.org/sparql", "SELECT 1", "POST", "text/tab-separated-values", 5)
    assert "https://example.org/sparql" in str(e.value)
    with pytest.raises(fetch.OfflineError):      # and _fetch_once does not swallow it as a "network error"
        fetch._fetch_once("SELECT 1", "https://example.org/sparql", 5)


def test_online_requests_still_reach_urllib(monkeypatch):
    seen = []

    class Opener:
        def open(self, req, timeout=None):
            seen.append(req.full_url)
            raise OSError("stub: no network")
    monkeypatch.setattr(fetch.urllib.request, "build_opener", lambda *a: Opener())
    body, fmt, err = fetch._fetch_once("SELECT 1", "https://example.org/sparql", 5)
    assert body is None and "stub: no network" in err and seen
