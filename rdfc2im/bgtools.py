"""Patched BlueGenes tool set: the tool tarballs a mine's tool store needs, and how to install them.

Two of the 2021 npm tools fail on a 2026 mine because they call web services that no longer exist
(see docker_template's README, "BlueGenes tools that call dead external services"), and the
JBrowse 2 tool is not on npm at all. HumanMine runs hand-patched copies; this module makes the same
copies from the cached, unpatched tarballs, so a rebuilt mine does not depend on someone editing
bundles by hand.

    unpatched tarballs (cached_raw_data/bluegenes-tools/data) + jbrowse2-tool source
        --stage-->  patched tarballs + SHA256SUMS + patches.json   (cached_raw_data/bluegenes-tools-patched)
        --install-> <tools dir>/@intermine/<name>/ + tools.edn     (what BlueGenes' BLUEGENES_TOOL_PATH reads)

Two properties matter more than the rest:

* A patch that does not apply is an error. Every edit names its anchor text and the number of times
  it must occur; zero (a bundle that changed upstream, a wrong tarball) or "more than expected"
  raises PatchError. The failure this guards against is a "patched" tool that is silently the
  original, which looks fine until a browser calls a dead host.
* Output is byte-for-byte reproducible: members keep their stored order and metadata, the gzip
  header carries no timestamp or file name, and nothing depends on the clock. The sha256 recorded in
  patches.json is therefore a statement about the inputs and the patch list. (Identical bytes also
  need an identical zlib; the checksum is only compared on the same machine or in the cache.)

Standard library only.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile

PATCHED_SUFFIX = "-patched.1"
SCOPE = "@intermine"
JBROWSE2_NAME = "bluegenes-jbrowse2-tool"
NPM_MTIME = 499162500            # 1985-10-26 08:15 UTC, what `npm pack` stamps on every member
SKIP_TOOLS = ("bluegenes-esyn-viewer",)   # not on HumanMine's tool list; never installed


class PatchError(Exception):
    """A patch could not be applied exactly as specified. Never caught and continued past."""


# --- the patch list ---------------------------------------------------------------------------
# (patch id, member path inside the package, text that must be present, replacement, exact count)
# The same edits as docker_template/README.md and sequence-alignment-service/README.md, applied to
# the shipped source file as well as the bundle where there is one, so the two agree.
RCSB_V1 = "rcsbsearch/v1/query"
RCSB_V2 = "rcsbsearch/v2/query"
ALIGNER_HOST = "https://sequencealignment.apps.intermine.org"

PATCHES: dict[str, list[tuple[str, str, str, str, int]]] = {
    "bluegenes-protein-visualizer": [
        ("rcsb-v1-to-v2", "dist/bundle.js", RCSB_V1, RCSB_V2, 1),
        ("rcsb-v1-to-v2", "src/queries/accessionToPdb.js", RCSB_V1, RCSB_V2, 1),
    ],
    "bluegenes-msa-viewer": [
        # '' makes the tool POST to /align-sequence on the page's own origin
        ("msa-same-origin", "dist/bundle.js", '"%s"' % ALIGNER_HOST, '""', 1),
        ("msa-same-origin", "src/sequence-align-service.js", "'%s'" % ALIGNER_HOST, "''", 1),
        # Array.prototype.at exists in every browser since 2021, so plain arrays took the Backbone
        # collection branch: "TypeError: t.on is not a function"
        ("msa-array-at-crash", "dist/bundle.js", '!t instanceof Array||"at"in t', "!(t instanceof Array)", 1),
        # legacy wheel events: Firefox's handler reads a zero delta and cancels native scrolling
        ("msa-legacy-wheel", "dist/bundle.js",
         't.mousewheel="_onmousewheel",t.DOMMouseScroll="_onmousewheel",', "", 1),
    ],
}


def _version_edit(old_version: str) -> tuple[str, str, str, str, int]:
    return ("version-bump", "package.json", '"version": "%s"' % old_version,
            '"version": "%s%s"' % (old_version, PATCHED_SUFFIX), 1)


def apply_edit(text: str, pid: str, member: str, old: str, new: str, count: int) -> str:
    n = text.count(old)
    if n != count:
        raise PatchError(f"patch {pid} on {member}: expected {count} occurrence(s) of {old!r}, found {n}")
    return text.replace(old, new)


# --- tarballs ---------------------------------------------------------------------------------

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tool_name(tarball: str) -> str:
    """'intermine__bluegenes-msa-viewer-2.1.1.tgz' -> ('bluegenes-msa-viewer', '2.1.1')."""
    m = re.match(r"^intermine__(.+?)-(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)\.tgz$", os.path.basename(tarball))
    if not m:
        raise PatchError(f"not a cached @intermine tool tarball name: {tarball}")
    return m.group(1), m.group(2)


def _gzip(raw: bytes) -> bytes:
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=0) as gz:
        gz.write(raw)
    return out.getvalue()


def _write_tar(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for ti, data in members:
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return _gzip(buf.getvalue())


def patch_tarball(data: bytes, name: str, version: str) -> tuple[bytes, list[dict]]:
    """Return (patched .tgz bytes, applied patches) for package `name`, or raise PatchError.

    Members keep their order and metadata; only the edited members' contents (and sizes) change.
    """
    edits = list(PATCHES.get(name, [])) + [_version_edit(version)]
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for ti in tf.getmembers():
            body = tf.extractfile(ti).read() if ti.isreg() else b""
            members.append((ti, body))
    index = {ti.name: i for i, (ti, _) in enumerate(members)}
    applied = []
    for pid, member, old, new, count in edits:
        key = "package/" + member
        if key not in index:
            raise PatchError(f"patch {pid}: {name} {version} has no member {key}")
        ti, body = members[index[key]]
        members[index[key]] = (ti, apply_edit(body.decode("utf-8"), pid, member, old, new, count).encode("utf-8"))
        applied.append({"id": pid, "file": member, "occurrences": count})
    for ti, _ in members:
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
    return _write_tar(members), applied


def pack_source(src_dir: str) -> tuple[bytes, str, str]:
    """Pack a tool's source directory like `npm pack` would: package.json's "files", plus
    package.json, README and LICENSE. Returns (.tgz bytes, package name, version)."""
    with open(os.path.join(src_dir, "package.json"), encoding="utf-8") as fh:
        pkg = json.load(fh)
    rels: set[str] = set()
    roots = list(pkg.get("files", [])) + ["package.json", "README.md", "LICENSE"]
    for r in roots:
        p = os.path.join(src_dir, r)
        if os.path.isdir(p):
            for base, _dirs, files in os.walk(p):
                for f in files:
                    rels.add(os.path.relpath(os.path.join(base, f), src_dir))
        elif os.path.isfile(p):
            rels.add(r)
    for need in ("package.json", "config.json"):
        if need not in rels:
            raise PatchError(f"{src_dir} has no {need}")
    cfg = json.load(open(os.path.join(src_dir, "config.json"), encoding="utf-8"))
    for key in ("css", "js"):
        f = cfg["files"][key]
        if f not in rels:
            raise PatchError(f"{src_dir}: config.json names {f} but it is not in the package "
                             f"(run `npm run build` there, or pass --build)")
    members = []
    for rel in sorted(rels):
        path = os.path.join(src_dir, rel)
        with open(path, "rb") as fh:
            body = fh.read()
        ti = tarfile.TarInfo("package/" + rel.replace(os.sep, "/"))
        ti.mtime = NPM_MTIME
        ti.mode = 0o755 if os.stat(path).st_mode & 0o100 else 0o644
        members.append((ti, body))
    return _write_tar(members), pkg["name"], pkg["version"]


def build_source(src_dir: str, work_dir: str) -> str:
    """`npm ci && npm run build` in a copy of src_dir (the source tree is never touched); returns the copy.

    Needs the network (esbuild comes from the registry). npm audit's summary is printed, not acted on.
    """
    dst = os.path.join(work_dir, "jbrowse2-build")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src_dir, dst, ignore=shutil.ignore_patterns("node_modules", ".git"))
    for cmd in (["npm", "ci", "--no-fund"], ["npm", "run", "build"], ["npm", "audit", "--omit=dev"]):
        r = subprocess.run(cmd, cwd=dst, text=True, capture_output=True)
        print(f"$ {' '.join(cmd)} (exit {r.returncode})\n{(r.stdout + r.stderr).strip()[-1500:]}")
        if r.returncode and cmd[1] != "audit":
            raise PatchError(f"{' '.join(cmd)} failed in {dst}")
    return dst


# --- staging and installing -------------------------------------------------------------------

def stage(src_cache: str, jbrowse2_src: str, out_dir: str, build_dir: str | None = None) -> dict:
    """Write the patched set into out_dir (created; existing .tgz files are replaced). Returns the report."""
    if not os.path.isdir(src_cache):
        raise PatchError(f"unpatched tarball directory {src_cache} does not exist")
    os.makedirs(out_dir, exist_ok=True)
    report = {"tools": {}}
    seen = set()
    for fn in sorted(os.listdir(src_cache)):
        if not fn.endswith(".tgz"):
            continue
        name, version = tool_name(fn)
        if name in SKIP_TOOLS:
            continue
        seen.add(name)
        with open(os.path.join(src_cache, fn), "rb") as fh:
            data = fh.read()
        if name in PATCHES:
            data, applied = patch_tarball(data, name, version)
            out_version, patches = version + PATCHED_SUFFIX, applied
            out_fn = f"intermine__{name}-{out_version}.tgz"
        else:
            out_version, patches, out_fn = version, [], fn
        with open(os.path.join(out_dir, out_fn), "wb") as fh:
            fh.write(data)
        report["tools"][name] = {"file": out_fn, "version": out_version, "source_version": version,
                                 "source_file": fn, "patches": patches, "sha256": sha256(data)}
    missing = set(PATCHES) - seen
    if missing:
        raise PatchError(f"patched tools not found among the cached tarballs: {sorted(missing)}")
    if build_dir:
        jbrowse2_src = build_source(jbrowse2_src, build_dir)
    data, name, version = pack_source(jbrowse2_src)
    short = name.split("/", 1)[1]
    out_fn = f"intermine__{short}-{version}.tgz"
    with open(os.path.join(out_dir, out_fn), "wb") as fh:
        fh.write(data)
    report["tools"][short] = {"file": out_fn, "version": version, "source_version": version,
                              "source_file": "(source tree)", "patches": [], "sha256": sha256(data),
                              "built": bool(build_dir)}
    with open(os.path.join(out_dir, "patches.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(out_dir, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        for t in sorted(report["tools"].values(), key=lambda t: t["file"]):
            fh.write(f"{t['sha256']}  {t['file']}\n")
    return report


def _safe_extract(tgz: str, dest: str) -> None:
    """Extract a package tarball so that `package/x` lands at dest/x. Refuses links and escapes."""
    with tarfile.open(tgz, "r:gz") as tf:
        for ti in tf.getmembers():
            if not (ti.isreg() or ti.isdir()):
                raise PatchError(f"{tgz}: member {ti.name} is not a plain file or directory")
            rel = os.path.normpath(ti.name)
            parts = rel.split(os.sep)
            if parts[0] != "package" or ".." in parts or os.path.isabs(rel):
                raise PatchError(f"{tgz}: member {ti.name} is outside package/")
            target = os.path.join(dest, *parts[1:])
            if ti.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(tf.extractfile(ti).read())
            os.chmod(target, 0o755 if ti.mode & 0o100 else 0o644)


def install(tgz_dir: str, tools_dir: str) -> dict:
    """Make tools_dir hold exactly the tools in tgz_dir: @intermine/<name>/ each plus tools.edn.

    Anything else under tools_dir/@intermine is removed (the esyn viewer, an older copy). Each tool
    is extracted next to the final place and renamed in, so a failure leaves the old tool.
    """
    with open(os.path.join(tgz_dir, "patches.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    scope_dir = os.path.join(tools_dir, SCOPE)
    staging = os.path.join(tools_dir, ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(scope_dir, exist_ok=True)
    versions = {}
    for name, t in sorted(report["tools"].items()):
        path = os.path.join(tgz_dir, t["file"])
        with open(path, "rb") as fh:
            if sha256(fh.read()) != t["sha256"]:
                raise PatchError(f"{path} does not match the sha256 recorded in patches.json")
        new = os.path.join(staging, name)
        _safe_extract(path, new)
        with open(os.path.join(new, "package.json"), encoding="utf-8") as fh:
            pkg = json.load(fh)
        if pkg["name"] != f"{SCOPE}/{name}" or pkg["version"] != t["version"]:
            raise PatchError(f"{path}: package.json says {pkg['name']} {pkg['version']}, "
                             f"expected {SCOPE}/{name} {t['version']}")
        versions[f"{SCOPE}/{name}"] = pkg["version"]
    removed = []
    for entry in sorted(os.listdir(scope_dir)):
        if entry not in report["tools"]:
            shutil.rmtree(os.path.join(scope_dir, entry))
            removed.append(entry)
    for name in report["tools"]:
        final = os.path.join(scope_dir, name)
        shutil.rmtree(final, ignore_errors=True)
        os.rename(os.path.join(staging, name), final)
    shutil.rmtree(staging, ignore_errors=True)
    with open(os.path.join(tools_dir, "tools.edn"), "w", encoding="utf-8") as fh:
        fh.write("{:tools {" + "\n         ".join(f'"{k}" "{v}"' for k, v in sorted(versions.items())) + "}}\n")
    return {"installed": versions, "removed": removed}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="stage-bluegenes-tools", description=__doc__.split("\n\n")[0])
    ap.add_argument("--src-cache", default="cached_raw_data/bluegenes-tools/data",
                    help="directory of the unpatched cached tarballs (default %(default)s)")
    ap.add_argument("--jbrowse2-src", required=True, help="repos/jbrowse2/bluegenes-tool")
    ap.add_argument("--out", required=True, help="directory to write the patched tarballs to")
    ap.add_argument("--build", metavar="WORKDIR", help="rebuild the JBrowse 2 bundle (npm ci; npm run build) "
                    "in a copy under WORKDIR instead of using the committed dist/")
    ap.add_argument("--install-to", metavar="TOOLS_DIR", help="also install into this BLUEGENES_TOOL_PATH")
    a = ap.parse_args(argv)
    try:
        rep = stage(a.src_cache, a.jbrowse2_src, a.out, a.build)
        for name, t in sorted(rep["tools"].items()):
            p = ",".join(sorted({x["id"] for x in t["patches"]})) or "-"
            print(f"{t['sha256']}  {t['file']}  patches: {p}")
        if a.install_to:
            r = install(a.out, a.install_to)
            print(f"installed {len(r['installed'])} tools into {a.install_to}; removed: {r['removed'] or 'none'}")
    except PatchError as e:
        print(f"stage-bluegenes-tools: FAILED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
