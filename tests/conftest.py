import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A shell started in a directory reached through a symbolic link exports PWD in the link's spelling, and bash
# trusts it: tools/full-build.sh would then print paths under the link while the tests build theirs from the
# real path of this file (two tests failed that way once the worktrees moved behind a link, 20 Nov 2026).
# Give every subprocess the real spelling.
import os as _os
_os.environ["PWD"] = _os.path.realpath(_os.getcwd())
