from ag_edgelab.data.fingerprint import sha256_file, sha256_json


def test_sha256_is_deterministic(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    first = sha256_file(p)
    second = sha256_file(p)
    assert first == second
    assert len(first) == 64


def test_json_hash_is_order_independent_for_mapping_keys():
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})
