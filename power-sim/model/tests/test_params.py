from dtpower.params import defaults, field, override, prefixed, resolve, unprefix

S = [
    field("a", "A", default=5, min=0, max=10),
    field("on", "On", kind="toggle", default=True),
    field("m", "Mode", kind="select", default="x", options=[{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}]),
]


def test_defaults_and_clamping():
    assert defaults(S) == {"a": 5, "on": True, "m": "x"}
    assert resolve(S, {"a": 99})["a"] == 10
    assert resolve(S, {"a": -1})["a"] == 0
    assert resolve(S, {"a": "nonsense"})["a"] == 5


def test_select_rejects_unknown_option():
    assert resolve(S, {"m": "z"})["m"] == "x"
    assert resolve(S, {"m": "y"})["m"] == "y"


def test_override_and_prefix_round_trip():
    o = override(S, {"a": {"default": 7}}, omit=("on",))
    assert [f["key"] for f in o] == ["a", "m"] and o[0]["default"] == 7
    assert S[0]["default"] == 5, "override must not mutate the source schema"
    pre = prefixed(S, "pcs")
    assert [f["key"] for f in pre] == ["pcs_a", "pcs_on", "pcs_m"]
    assert unprefix({"pcs_a": 3, "other": 1}, "pcs") == {"a": 3}
