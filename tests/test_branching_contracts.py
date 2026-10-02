import pytest

from ag_edgelab.contracts.branching import DecisionEdge, FunnelDefinition, FunnelVariant, NodeType, RuleNode, RuleVersion
from ag_edgelab.data.fingerprint import canonical_json


def rule(version="1", *, behavior=None, label="display"):
    return RuleVersion(rule_id="SWEEP", version=version, node_type=NodeType.FILTER,
                       implementation_sha256="a" * 64,
                       behavior_json=canonical_json({"threshold": 1} if behavior is None else behavior),
                       display_name=label)


def definition(r=None):
    r = r or rule()
    terminal = RuleVersion(rule_id="TRADE", version="1", node_type=NodeType.TRADE,
                           implementation_sha256="b" * 64, behavior_json="{}")
    return FunnelDefinition(funnel_id="SYNTH", version="1", entry_node_id="sweep", display_name="label",
                            nodes=(RuleNode(node_id="sweep", rule=r, edges=(DecisionEdge(output="PASS", target_node_id="trade"),)),
                                   RuleNode(node_id="trade", rule=terminal)))


def test_funnel_identity_is_deterministic_and_excludes_display_metadata():
    assert definition().sha256 == definition(rule(label="other")).sha256
    assert rule().sha256 == rule(label="renamed").sha256


def test_behavior_or_rule_version_change_changes_funnel_identity():
    base = definition()
    changed_behavior = definition(rule("2", behavior={"threshold": 2}))
    changed_version = definition(rule("2"))
    assert len({base.sha256, changed_behavior.sha256, changed_version.sha256}) == 3


def test_variant_mutation_requires_development_and_frozen_variant_rejects_mutation():
    variant = FunnelVariant(definition=definition())
    child = variant.mutate_rule("sweep", rule("2", behavior={"threshold": 2}), dataset_role="DEVELOPMENT")
    assert child.parent_sha256 == variant.sha256
    assert child.sha256 != variant.sha256
    with pytest.raises(ValueError, match="DEVELOPMENT"):
        variant.mutate_rule("sweep", rule("2"), dataset_role="VALIDATION")
    with pytest.raises(ValueError, match="frozen"):
        variant.freeze().mutate_rule("sweep", rule("2"), dataset_role="DEVELOPMENT")
