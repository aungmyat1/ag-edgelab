from ag_edgelab.data.fingerprint import canonical_json, sha256_json


def test_canonical_mapping_order_does_not_change_hash():
    assert sha256_json({"b": 2, "a": 1}) == sha256_json({"a": 1, "b": 2})
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
