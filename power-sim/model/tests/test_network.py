import pytest

from dtpower.components import PriceSignal
from dtpower.network import ModelError, Network
from dtpower.sims import bess_dr


def test_model_uses_industroml_kinds_and_interfaces():
    m = bess_dr.model()
    kinds = {a["id"]: a["kind"] for a in m["assets"]}
    assert kinds["UTIL"] == "utility_supply" and kinds["UPS-1"] == "ups" and kinds["GPU-1"] == "server"
    ifaces = {i["id"] for i in m["interfaces"]}
    for c in m["connections"]:
        assert c["from"] in ifaces and c["to"] in ifaces


def test_rejects_a_double_feed():
    m = bess_dr.model()
    m["connections"].append({"id": "C-99", "type": "cable", "from": "MSB.OUT", "to": "GPU-1.IN"})
    with pytest.raises(ModelError, match="fed twice"):
        Network(m, PriceSignal.flat(100))


def test_rejects_an_unknown_kind():
    m = bess_dr.model()
    m["assets"].append({"id": "X", "kind": "chiller", "domain": "mechanical", "container": "SITE"})
    with pytest.raises(ModelError, match="no simulation component"):
        Network(m, PriceSignal.flat(100))


def test_rejects_an_unconnected_asset():
    m = bess_dr.model()
    m["connections"] = [c for c in m["connections"] if c["id"] != "C-04"]
    with pytest.raises(ModelError, match="GPU-1"):
        Network(m, PriceSignal.flat(100))


def test_storage_is_optional():
    """Drop the BESS and its controller and the same network still runs."""
    m = bess_dr.model()
    m["assets"] = [a for a in m["assets"] if a["id"] not in ("BESS-1", "DR-1")]
    m["connections"] = [c for c in m["connections"] if c["id"] in ("C-01", "C-03", "C-04", "C-05")]
    rows = Network(m, PriceSignal.flat(100)).run(dt_min=5)
    assert len(rows) == 288
    assert rows[0]["assets"]["UTIL"]["import_kw"] == pytest.approx(rows[0]["assets"]["UPS-1"]["input_kw"])


def test_measured_load_replaces_the_model():
    """The telemetry seam: a measured GPU power is used instead of the model's."""
    net = Network(bess_dr.model({"BESS-1": {"enabled": False}}), PriceSignal.flat(100),
                  measurements={"GPU-1": lambda t: {"kw": 100.0 + t}})
    rows = net.run(dt_min=60)
    assert rows[5]["assets"]["GPU-1"]["kw"] == pytest.approx(105.0)
    assert rows[5]["assets"]["UPS-1"]["output_kw"] == pytest.approx(105.0)


def test_a_generator_lands_on_a_bus_not_a_feeder():
    m = bess_dr.model()
    m["connections"] = [dict(c, to="UPS-1.IN") if c["id"] == "C-05" else c for c in m["connections"]]
    with pytest.raises(ModelError, match="must land on a bus"):
        Network(m, PriceSignal.flat(100))
