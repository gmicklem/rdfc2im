# Front for the ut demo BlueGenes (compose project `rdfc2im-ut-front`)

Browser origin stays `http://localhost:15001`. An nginx container (`network_mode: host`,
listens on 0.0.0.0:15001) fronts:

| Path | Goes to |
|------|---------|
| `POST /align-sequence` | aligner container, `127.0.0.1:13000` (built from the sequence-alignment-service checkout) |
| `/vendor/imjs/im.min.js` | imjs 4.0.0, mounted from `$FRONT_HOME/imjs` (default `~/.cache/rdfc2im-front`) |
| everything else | BlueGenes jar on `:15011`, with `<script src="/vendor/imjs/im.min.js">` injected before `</head>` (`sub_filter`) |

imjs is not committed: `up.sh` fetches `imjs-4.0.0.tgz` from the npm registry and checks
SHA-256 (tarball `18d0e131...ca09`, `dist/im.min.js` `21f4ebf0...b8db`; same file as
docker_template/nginx/vendor/imjs). BlueGenes maint-2026 bundles imjs in app.js but has no
setting to emit a script tag, hence the injection.

Own project, not `rdfc2im-ut`: a rebuild of the mine stack neither touches nor orphans these.
Host networking is used because it is the simplest way to reach the jar, a plain process on
the sandbox host (the jar has no bind-address setting, so 15011 listens on all interfaces; it
is not published to the Mac).

`./up.sh` starts everything (also the jar via `BG_START`), `./down.sh` removes the containers
(stop the jar with `lsof -ti tcp:15011 -sTCP:LISTEN` then `kill`). Env: `ALIGNER_SRC`, `FRONT_HOME`, `BG_START`.
