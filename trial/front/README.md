# Front for the ut demo BlueGenes (compose project `rdfc2im-ut-front`)

Browser origin stays `http://localhost:15001`. An nginx container (`network_mode: host`,
listens on 0.0.0.0:15001) fronts:

| Path | Goes to |
|------|---------|
| `POST /align-sequence` | aligner container, `127.0.0.1:13000` (built from the sequence-alignment-service checkout) |
| `/vendor/imjs/im.min.js` | imjs 4.0.0, mounted from `$FRONT_HOME/imjs` (default `~/.cache/rdfc2im-front`) |
| `/jbrowse2/` | JBrowse 2 container, `127.0.0.1:14881` (image `rdfc2im-jbrowse2` built by `build-jbrowse2.sh` from `repos/jbrowse2`; config generated from the mine by `gen-jbrowse-config.sh`) |
| everything else | BlueGenes jar on `:15011`, with `<script src="/vendor/imjs/im.min.js">` injected before `</head>` (`sub_filter`) |

imjs is not committed: `up.sh` fetches `imjs-4.0.0.tgz` from the npm registry and checks
SHA-256 (tarball `18d0e131...ca09`, `dist/im.min.js` `21f4ebf0...b8db`; same file as
docker_template/nginx/vendor/imjs). BlueGenes maint-2026 bundles imjs in app.js but has no
setting to emit a script tag, hence the injection.

Own project, not `rdfc2im-ut`: a rebuild of the mine stack neither touches nor orphans these.
Host networking is used because it is the simplest way to reach the jar, a plain process on
the sandbox host (the jar has no bind-address setting, so 15011 listens on all interfaces; it
is not published to the Mac).

JBrowse 2 is served on the BlueGenes origin, as HumanMine does, so the JBrowse 2 tool's iframe (`jbrowse2Url`
`/jbrowse2/`, patched in by `rdfc2im/bgtools.py`) is same-origin and no port is published. `up.sh` builds the image
when it is missing (`REBUILD_JBROWSE2=1` forces it; behind the sandbox's TLS-inspecting proxy `build-jbrowse2.sh`
adds the CA bundle to a copy of the Dockerfile), regenerates `$FRONT_HOME/jbrowse2/config.json` from the mine at
`MINE_URL` (default `http://localhost:18090/humanmine`, the URL the browser uses; a mine that is down leaves the last
config), tests `nginx.conf` in a throwaway container before touching the live one, and reloads nginx. The mine's
tracks changed? Run `gen-jbrowse-config.sh` again; no restart is needed (the file is mounted). Details in BUILD.md,
"JBrowse 2 on the front".

`./up.sh` starts everything (also the jar via `BG_START`), `./down.sh` removes the containers
(stop the jar with `lsof -ti tcp:15011 -sTCP:LISTEN` then `kill`). Env: `ALIGNER_SRC`, `FRONT_HOME`, `BG_START`, `JBROWSE2_SRC`, `MINE_URL`, `TAXON`, `REBUILD_JBROWSE2`.
