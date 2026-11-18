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
