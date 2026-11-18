"""trial/front: aligner + nginx front for the ut BlueGenes [im-9n4.8]."""
import os
import re

FRONT = os.path.join(os.path.dirname(__file__), "..", "trial", "front")


def _read(name):
    with open(os.path.join(FRONT, name)) as f:
        return f.read()


def test_nginx_has_the_three_routes():
    t = _read("nginx.conf")
    assert re.search(r"location = /align-sequence \{[^}]*proxy_pass http://127\.0\.0\.1:13000", t)
    assert re.search(r"location /vendor/ \{[^}]*alias /usr/share/nginx/vendor/", t)
    assert "sub_filter '</head>' '<script src=\"/vendor/imjs/im.min.js\"></script></head>'" in t
    assert "proxy_pass http://127.0.0.1:15011" in t
    assert "listen 0.0.0.0:15001" in t


def test_compose_is_its_own_project_and_does_not_touch_the_mine_stack():
    t = _read("docker-compose.yml")
    assert "name: rdfc2im-ut-front" in t
    live = "\n".join(l for l in t.splitlines() if not l.lstrip().startswith("#"))
    assert "network_mode: host" in live
    assert "127.0.0.1:${ALIGNER_HTTP_PORT:-13000}:3000" in live
    assert "rdfc2im-ut-front-aligner" in live and "rdfc2im-ut-front-nginx" in live


def test_scripts_are_executable_and_use_the_project_name():
    for n in ("up.sh", "down.sh"):
        p = os.path.join(FRONT, n)
        assert os.access(p, os.X_OK), n
        assert "-p rdfc2im-ut-front" in _read(n)


# --- JBrowse 2 on the BlueGenes origin [im-9n4.10] ---------------------------------------------

def test_nginx_serves_jbrowse2_on_the_bluegenes_origin():
    t = _read("nginx.conf")
    # prefix stripped by the trailing slash of proxy_pass, so /jbrowse2/x -> container's /x
    assert re.search(r"location /jbrowse2/ \{[^}]*proxy_pass http://127\.0\.0\.1:14881/;", t)
    assert re.search(r"location = /jbrowse2 \{[^}]*return 301 /jbrowse2/;", t)
    # the imjs sub_filter stays on the BlueGenes location only (JBrowse 2 is not a BlueGenes page)
    assert t.count("sub_filter '</head>'") == 1
    assert t.index("location /jbrowse2/") < t.index("location / {")


def test_compose_runs_jbrowse2_on_loopback_from_the_built_image_with_the_generated_config():
    live = "\n".join(l for l in _read("docker-compose.yml").splitlines() if not l.lstrip().startswith("#"))
    assert "rdfc2im-ut-front-jbrowse2" in live
    assert "image: rdfc2im-jbrowse2:latest" in live and "pull_policy: never" in live
    assert "127.0.0.1:${JBROWSE2_HTTP_PORT:-14881}:80" in live       # no new published port
    assert "${JBROWSE2_CONFIG:?set JBROWSE2_CONFIG}:/usr/share/nginx/html/config.json:ro" in live


def test_up_sh_builds_generates_and_tests_before_it_touches_the_live_front():
    t = _read("up.sh")
    build = t.index('bash "$HERE/build-jbrowse2.sh"')
    gen = t.index('bash "$HERE/gen-jbrowse-config.sh"')
    test = t.index("nginx -t")
    up = t.index("docker compose -f")
    assert build < gen < test < up, "config check must come before compose up (a broken nginx.conf must not kill :15001)"
    assert t.index("nginx -s reload") > up


def test_gen_config_keeps_the_last_config_when_the_mine_is_down(tmp_path):
    import subprocess
    gen = os.path.join(FRONT, "gen-jbrowse-config.sh")
    assert os.access(gen, os.X_OK) and os.access(os.path.join(FRONT, "build-jbrowse2.sh"), os.X_OK)
    src = tmp_path / "jb2"
    (src / "config").mkdir(parents=True)
    (src / "docker").mkdir()
    (src / "docker" / "config.json").write_text('{"placeholder": true}\n')
    (src / "config" / "generate.mjs").write_text("process.exit(1)\n")     # the mine is "down": generation fails
    env = dict(os.environ, FRONT_HOME=str(tmp_path / "home"), JBROWSE2_SRC=str(src))
    out = tmp_path / "home" / "jbrowse2" / "config.json"
    r = subprocess.run(["bash", gen], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "placeholder" in r.stderr and out.read_text() == '{"placeholder": true}\n'
    out.write_text('{"last": "good"}\n')
    r = subprocess.run(["bash", gen], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "keeping the last generated" in r.stderr and out.read_text() == '{"last": "good"}\n'
    (src / "config" / "generate.mjs").write_text(
        "import {writeFileSync} from 'node:fs'; writeFileSync(process.argv[process.argv.indexOf('-o') + 1], '{\"fresh\": true}\\n')\n")
    r = subprocess.run(["bash", gen], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and out.read_text() == '{"fresh": true}\n'
    assert not (tmp_path / "home" / "jbrowse2" / "config.json.new").exists()
