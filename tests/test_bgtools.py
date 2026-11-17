"""rdfc2im/bgtools.py: the patched BlueGenes tool set, on tiny fixture tarballs (no network, no real tools).

What is pinned: each patch changes exactly what it names; a patch whose anchor text is missing (or
present too often) raises instead of producing an unpatched "patched" tool; the same inputs give
byte-identical output; install lays out @intermine/<name>/ + tools.edn and drops tools not in the set.
"""
import gzip
import io
import json
import os
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rdfc2im import bgtools  # noqa: E402
from rdfc2im.bgtools import PatchError  # noqa: E402

MSA_BUNDLE = ('x=1;a("https://sequencealignment.apps.intermine.org");if(!t instanceof Array||"at"in t){}'
              't.mousewheel="_onmousewheel",t.DOMMouseScroll="_onmousewheel",y=2;')
PV_BUNDLE = 'fetch("https://search.rcsb.org/rcsbsearch/v1/query")'


def make_tgz(files, mtime=1000):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, body in files.items():
            ti = tarfile.TarInfo("package/" + name)
            ti.size, ti.mtime, ti.mode = len(body), mtime, 0o644
            tf.addfile(ti, io.BytesIO(body.encode()))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=12345) as gz:   # a different header on purpose
        gz.write(buf.getvalue())
    return out.getvalue()


def pkgjson(name, version):
    return json.dumps({"name": "@intermine/" + name, "version": version}, indent=2)


def msa_files(**over):
    f = {"package.json": pkgjson("bluegenes-msa-viewer", "2.1.1"), "dist/bundle.js": MSA_BUNDLE,
         "src/sequence-align-service.js": "module.exports = 'https://sequencealignment.apps.intermine.org';"}
    f.update(over)
    return f


def pv_files(**over):
    f = {"package.json": pkgjson("bluegenes-protein-visualizer", "2.1.1"), "dist/bundle.js": PV_BUNDLE,
         "src/queries/accessionToPdb.js": "url = 'https://search.rcsb.org/rcsbsearch/v1/query'"}
    f.update(over)
    return f


def members(tgz):
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        return {m.name[len("package/"):]: tf.extractfile(m).read().decode() for m in tf.getmembers()}


def test_msa_patches_apply():
    out, applied = bgtools.patch_tarball(make_tgz(msa_files()), "bluegenes-msa-viewer", "2.1.1")
    m = members(out)
    assert m["dist/bundle.js"] == 'x=1;a("");if(!(t instanceof Array)){}y=2;'
    assert m["src/sequence-align-service.js"] == "module.exports = '';"
    assert json.loads(m["package.json"])["version"] == "2.1.1-patched.1"
    assert {a["id"] for a in applied} == {"msa-same-origin", "msa-array-at-crash", "msa-legacy-wheel", "version-bump"}


def test_rcsb_patch_applies_to_bundle_and_source():
    m = members(bgtools.patch_tarball(make_tgz(pv_files()), "bluegenes-protein-visualizer", "2.1.1")[0])
    assert "v2/query" in m["dist/bundle.js"] and "v1" not in m["dist/bundle.js"]
    assert "v2/query" in m["src/queries/accessionToPdb.js"]
    assert json.loads(m["package.json"])["version"] == "2.1.1-patched.1"


@pytest.mark.parametrize("drop", ["rcsbsearch/v3/query", "xx"])
def test_missing_anchor_refuses(drop):
    files = pv_files(**{"dist/bundle.js": PV_BUNDLE.replace("rcsbsearch/v1/query", drop)})
    with pytest.raises(PatchError, match="expected 1 occurrence"):
        bgtools.patch_tarball(make_tgz(files), "bluegenes-protein-visualizer", "2.1.1")


def test_already_patched_or_duplicated_anchor_refuses():
    already = members(bgtools.patch_tarball(make_tgz(pv_files()), "bluegenes-protein-visualizer", "2.1.1")[0])
    with pytest.raises(PatchError):                      # patching twice must not pass quietly
        bgtools.patch_tarball(make_tgz({**already, "package.json": pkgjson("x", "2.1.1")}),
                              "bluegenes-protein-visualizer", "2.1.1")
    with pytest.raises(PatchError, match="found 2"):
        bgtools.patch_tarball(make_tgz(pv_files(**{"dist/bundle.js": PV_BUNDLE * 2})),
                              "bluegenes-protein-visualizer", "2.1.1")


def test_wrong_package_version_refuses():
    with pytest.raises(PatchError, match="version"):
        bgtools.patch_tarball(make_tgz(pv_files()), "bluegenes-protein-visualizer", "9.9.9")


def test_missing_member_refuses():
    f = msa_files()
    del f["src/sequence-align-service.js"]
    with pytest.raises(PatchError, match="no member"):
        bgtools.patch_tarball(make_tgz(f), "bluegenes-msa-viewer", "2.1.1")


def test_deterministic_whatever_the_input_gzip_header():
    a = bgtools.patch_tarball(make_tgz(msa_files(), mtime=1), "bluegenes-msa-viewer", "2.1.1")[0]
    b = bgtools.patch_tarball(make_tgz(msa_files(), mtime=1), "bluegenes-msa-viewer", "2.1.1")[0]
    assert a == b
    assert a[4:8] == b"\0\0\0\0"          # gzip MTIME field is zero


def jb_src(d, js=True):
    d.mkdir(exist_ok=True)
    (d / "package.json").write_text(json.dumps({"name": "@intermine/bluegenes-jbrowse2-tool", "version": "0.1.0",
                                                 "files": ["config.json", "dist"]}))
    (d / "config.json").write_text(json.dumps({"files": {"css": "dist/style.css", "js": "dist/bundle.js"}}))
    (d / "dist").mkdir(exist_ok=True)
    (d / "dist" / "style.css").write_text("a{}")
    if js:
        (d / "dist" / "bundle.js").write_text("1")
    return str(d)


def make_cache(tmp_path):
    c = tmp_path / "cache"
    c.mkdir(exist_ok=True)
    for fn, files in (("intermine__bluegenes-msa-viewer-2.1.1.tgz", msa_files()),
                      ("intermine__bluegenes-protein-visualizer-2.1.1.tgz", pv_files()),
                      ("intermine__bluegenes-esyn-viewer-1.0.1.tgz", {"package.json": pkgjson("bluegenes-esyn-viewer", "1.0.1")}),
                      ("intermine__bluegenes-gwas-visualizer-1.0.0.tgz", {"package.json": pkgjson("bluegenes-gwas-visualizer", "1.0.0")})):
        (c / fn).write_bytes(make_tgz(files))
    return str(c)


def test_stage_and_install(tmp_path):
    out = str(tmp_path / "out")
    rep = bgtools.stage(make_cache(tmp_path), jb_src(tmp_path / "jb"), out)
    assert sorted(rep["tools"]) == ["bluegenes-gwas-visualizer", "bluegenes-jbrowse2-tool",
                                    "bluegenes-msa-viewer", "bluegenes-protein-visualizer"]   # no esyn viewer
    sums = open(os.path.join(out, "SHA256SUMS")).read()
    assert all(t["sha256"] in sums for t in rep["tools"].values())
    tools = tmp_path / "tools"
    (tools / "@intermine" / "bluegenes-esyn-viewer").mkdir(parents=True)
    r = bgtools.install(out, str(tools))
    assert r["removed"] == ["bluegenes-esyn-viewer"]
    assert (tools / "@intermine" / "bluegenes-jbrowse2-tool" / "dist" / "bundle.js").read_text() == "1"
    edn = (tools / "tools.edn").read_text()
    assert '"@intermine/bluegenes-msa-viewer" "2.1.1-patched.1"' in edn and "esyn" not in edn
    assert not (tools / ".staging").exists()
    # same inputs, second run: identical bytes
    rep2 = bgtools.stage(make_cache(tmp_path), jb_src(tmp_path / "jb"), str(tmp_path / "out2"))
    assert {k: v["sha256"] for k, v in rep["tools"].items()} == {k: v["sha256"] for k, v in rep2["tools"].items()}


def test_stage_fails_when_a_patched_tool_is_not_cached(tmp_path):
    c = make_cache(tmp_path)
    os.remove(os.path.join(c, "intermine__bluegenes-msa-viewer-2.1.1.tgz"))
    with pytest.raises(PatchError, match="not found"):
        bgtools.stage(c, jb_src(tmp_path / "jb"), str(tmp_path / "out"))


def test_jbrowse2_source_without_built_bundle_refuses(tmp_path):
    with pytest.raises(PatchError, match="npm run build"):
        bgtools.pack_source(jb_src(tmp_path / "jb", js=False))


def test_install_refuses_a_tampered_tarball(tmp_path):
    out = str(tmp_path / "out")
    bgtools.stage(make_cache(tmp_path), jb_src(tmp_path / "jb"), out)
    with open(os.path.join(out, "intermine__bluegenes-gwas-visualizer-1.0.0.tgz"), "ab") as fh:
        fh.write(b"x")
    with pytest.raises(PatchError, match="sha256"):
        bgtools.install(out, str(tmp_path / "tools"))
