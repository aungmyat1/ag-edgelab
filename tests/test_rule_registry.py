import pytest

from ag_edgelab.funnels.registry import RuleRegistry, RuleRegistryError


class Rule:
    rule_id = "ctx"
    rule_version = "1"
    rule_hash = "a" * 64

    def evaluate(self, context):
        raise NotImplementedError


def test_registry_rejects_duplicate_version_identity():
    reg = RuleRegistry()
    reg.register(Rule())
    with pytest.raises(RuleRegistryError, match="duplicate"):
        reg.register(Rule())


def test_registry_requires_hash():
    class Bad(Rule):
        rule_id = "bad"
        rule_hash = ""

    with pytest.raises(RuleRegistryError, match="empty hash"):
        RuleRegistry().register(Bad())
