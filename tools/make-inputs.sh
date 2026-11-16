#!/bin/sh
# Rebuild in/ from the upstream projects.  Idempotent; re-run to refresh.
#
#   in/config/<source>/            dbcls/rdf-config                 config/
#   in/intermine/bio/              intermine/intermine              bio/
#   in/humanmine-bio-sources/      intermine/humanmine-bio-sources
#   in/humanmine_project.xml       intermine/humanmine              project.xml
#   in/humanmine_priorities.properties  intermine/humanmine     dbmodel/resources/genomic_priorities.properties
#   in/humanmine_model.xml         humanmine.org  /service/model?format=xml
#   in/humanmine_model.json        humanmine.org  /service/model?format=json
#
# Clones land in $CACHE (default in/.upstream) so a refresh is a `git pull`,
# not a 150 MB re-download.  Set CACHE to share one checkout between workspaces.
#
# CACHED=1 (tools/full-build.sh --use-cached-data): the live model is copied from the directory
# MODEL_DIR (full-build.sh restores it there from cached_raw_data/humanmine-model) instead of
# fetched. The clones are not part of that cache: a missing one is cloned, a present one is left
# as it is (no pull).
# OFFLINE=1 (tools/full-build.sh --offline; implies CACHED=1) makes no network request at all: the
# clones must already be in $CACHE (no clone, no pull). Anything missing is an error that names it.
set -e

CACHE=${CACHE:-in/.upstream}
MINE=${MINE:-https://www.humanmine.org/humanmine}
OFFLINE=${OFFLINE:-0}
CACHED=${CACHED:-0}
[ "$OFFLINE" = 1 ] && CACHED=1

mkdir -p "$CACHE" in

clone() {                       # clone <url> <dir> [extra git flags]
    if [ "$OFFLINE" = 1 ]; then
        [ -d "$CACHE/$2/.git" ] || { echo "ERROR: OFFLINE=1 and no clone $CACHE/$2 - run once without --offline (e.g. with --use-cached-data or nothing) to clone it" >&2; exit 1; }
        echo "  $2: using the existing clone"
    elif [ "$CACHED" = 1 ] && [ -d "$CACHE/$2/.git" ]; then
        echo "  $2: using the existing clone (no pull)"
    elif [ -d "$CACHE/$2/.git" ]; then
        echo "  $2: refreshing"
        git -C "$CACHE/$2" pull --quiet --ff-only || echo "  $2: pull failed, keeping the cached copy"
    else
        echo "  $2: cloning"
        # shellcheck disable=SC2086
        git clone --depth 1 --quiet $3 "$1" "$CACHE/$2"
    fi
}

echo "upstream sources ->  $CACHE"
clone https://github.com/dbcls/rdf-config.git                rdf-config
clone https://github.com/intermine/intermine.git             intermine --filter=blob:none
clone https://github.com/intermine/humanmine.git             humanmine
clone https://github.com/intermine/humanmine-bio-sources.git humanmine-bio-sources

# Trees are copied by tools/copy_tree.py, files by copy_file - never `cp -r` or `tar`. Both failed
# here on the virtiofs workspace mount, one after the other, on the first fresh run:
#   cp -r of a clone:  "failed to extend ... .git/objects/pack/pack-....pack: Permission denied",
#                      leaving a 0-byte pack (in a .git the script then deleted anyway)
#   tar | tar:         "tar: .: Directory renamed before its status could be extracted" (tar
#                      compares inode numbers, which that mount does not keep stable)
# copy_tree.py uses plain chunked read/write, re-reads every file it wrote and compares, leaves
# .git out, and keeps modes (gradlew) and symlinks. Plain `cp` has also been seen to write the
# right number of NULs on that mount without failing, hence copy_file's cmp.
TOOLS=$(cd "$(dirname "$0")" && pwd)     # next to this script, whatever the caller's cwd
copy_tree() { python3 "$TOOLS/copy_tree.py" "$@"; }

copy_file() {                   # copy_file SRC DST - a small file, checked
    cp "$1" "$2"
    cmp -s "$1" "$2" || { echo "ERROR: copying $1 to $2 did not produce an identical file" >&2; exit 1; }
}

echo "assembling in/"
rm -rf in/config in/intermine in/humanmine-bio-sources
copy_tree "$CACHE/rdf-config/config"       in/config             --exclude .git
copy_tree "$CACHE/intermine/bio"           in/intermine/bio      --exclude .git
copy_tree "$CACHE/humanmine-bio-sources"   in/humanmine-bio-sources --exclude .git
copy_file "$CACHE/humanmine/project.xml"   in/humanmine_project.xml
copy_file "$CACHE/humanmine/dbmodel/resources/genomic_priorities.properties" in/humanmine_priorities.properties

# The live model is the merged, deployed model - it has no upstream file.
for fmt in xml json; do
    if [ "$CACHED" = 1 ]; then
        [ -s "${MODEL_DIR:-}/humanmine_model.$fmt" ] || { echo "ERROR: CACHED=1 and no \$MODEL_DIR/humanmine_model.$fmt (MODEL_DIR=${MODEL_DIR:-unset})" >&2; exit 1; }
        copy_file "$MODEL_DIR/humanmine_model.$fmt" "in/humanmine_model.$fmt"
        continue
    fi
    echo "  humanmine_model.$fmt: $MINE/service/model?format=$fmt"
    curl -fsS -o "in/humanmine_model.$fmt" "$MINE/service/model?format=$fmt" \
        || echo "  WARNING could not fetch the live model as $fmt; keeping any existing copy"
done

echo "done.  in/ is $(du -sh in | cut -f1) (gitignored)."
