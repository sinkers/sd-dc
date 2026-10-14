import json
import threading
import urllib.error
import urllib.request

import pytest

from dtpower.server import make_server


@pytest.fixture(scope="module")
def base():
    httpd = make_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_health_and_listing(base):
    assert get(base + "/healthz")["ok"]
    assert [s["id"] for s in get(base + "/api/sims")] == ["bess-dr"]
    comps = get(base + "/api/components")
    assert comps["ups"]["role"] == "conversion" and comps["bess"]["kind_proposed"]


def test_describe_and_run(base):
    d = get(base + "/api/sims/bess-dr")
    assert "BESS-1" in d["assets"]
    r = post(base + "/api/sims/bess-dr/run", {"scenario": "nsw-spike", "params": {"BESS-1": {"capacity_kwh": 800}}})
    assert r["params"]["BESS-1"]["capacity_kwh"] == 800
    assert len(r["rows"]) == 288 and r["summary"]["saving"] > 0


def test_bad_requests(base):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/api/sims/bess-dr/run", {"scenario": "nope"})
    assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/sims/nope")
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/../../etc/passwd")
    assert e.value.code == 404
