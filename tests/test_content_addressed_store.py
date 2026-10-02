from dataclasses import FrozenInstanceError

import pytest

from ag_edgelab.verification.provenance import ContentAddressedStore, UnknownProvenanceError


class MutableRecord:
    def __init__(self, digest):
        self.digest = digest

    @property
    def sha256(self):
        return self.digest


def test_every_public_store_constructor_rejects_wrong_key_content_pairs():
    record = MutableRecord("a" * 64)
    for construct in (ContentAddressedStore, ContentAddressedStore.build):
        with pytest.raises(ValueError, match="does not match"):
            construct({"f" * 64: record})


@pytest.mark.parametrize("key", ["invalid", "A" * 64, "a" * 63, "g" * 64])
def test_store_rejects_noncanonical_address_keys(key):
    with pytest.raises(ValueError, match="canonical SHA-256"):
        ContentAddressedStore({key: MutableRecord(key)})


def test_store_copies_and_freezes_input_mapping():
    digest = "b" * 64
    record = MutableRecord(digest)
    original = {digest: record}
    store = ContentAddressedStore(original)
    original.clear()
    original["c" * 64] = MutableRecord("c" * 64)
    assert store.resolve(digest) is record
    assert len(store._records) == 1
    with pytest.raises(TypeError):
        store._records["c" * 64] = original["c" * 64]
    with pytest.raises(FrozenInstanceError):
        store._records = {}


def test_resolve_rechecks_record_identity_after_store_creation():
    record = MutableRecord("d" * 64)
    store = ContentAddressedStore({record.sha256: record})
    record.digest = "e" * 64
    with pytest.raises(UnknownProvenanceError, match="no longer matches"):
        store.resolve("d" * 64)


def test_valid_record_under_its_content_hash_resolves():
    record = MutableRecord("f" * 64)
    store = ContentAddressedStore.build({record.sha256: record})
    assert store.resolve(record.sha256) is record
    with pytest.raises(UnknownProvenanceError):
        store.resolve("e" * 64)
