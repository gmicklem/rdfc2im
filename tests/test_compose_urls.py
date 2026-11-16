"""trial/docker-compose.yml: no compose-internal service name may reach the browser [im-ore.8]."""
import os
import re

COMPOSE = os.path.join(os.path.dirname(__file__), "..", "trial", "docker-compose.yml")


def _text():
    with open(COMPOSE) as f:
        # comments explain the old setting; only live lines count
        return "\n".join(l for l in f.read().splitlines() if not l.lstrip().startswith("#"))


def test_no_internal_service_root():
    t = _text()
    assert "BLUEGENES_BACKEND_SERVICE_ROOT" not in t
    assert not re.search(r"https?://(mine|bluegenes|postgres|solr)[:/]", t)


def test_bluegenes_shares_mine_network_and_mine_publishes_its_port():
    t = _text()
    assert 'network_mode: "service:mine"' in t
    # BlueGenes' own port is published by the mine service, not by a ports: of bluegenes
    bg = t[t.index("\n  bluegenes:"):t.index("\nvolumes:")]
    assert "ports:" not in bg
    assert re.search(r'"127\.0\.0\.1:\$\{BG_PORT:-5000\}:5000"', t)


def test_artifacts_mount_is_per_stack():
    """im-ore.21: the staged webapp and BlueGenes jars come from RDFC2IM_ARTIFACTS (default ./artifacts), so a
    second stack's rebuild cannot overwrite the first stack's webapp."""
    t = _text()
    mounts = re.findall(r"^\s*- (\S+):(/usr/local/tomcat/webapps/humanmine|/opt/bluegenes/lib):ro", t, re.M)
    assert [m[1] for m in mounts] == ["/usr/local/tomcat/webapps/humanmine", "/opt/bluegenes/lib"]
    assert [m[0] for m in mounts] == ["${RDFC2IM_ARTIFACTS:-./artifacts}/humanmine",
                                      "${RDFC2IM_ARTIFACTS:-./artifacts}/bluegenes-lib"]
    assert "./artifacts/" not in t.replace("${RDFC2IM_ARTIFACTS:-./artifacts}/", "")
    with open(os.path.join(os.path.dirname(__file__), "..", "tools", "trial-stage.sh")) as f:
        assert "${RDFC2IM_ARTIFACTS:-" in f.read()
