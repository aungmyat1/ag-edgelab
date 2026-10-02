from __future__ import annotations

from ag_edgelab.funnels.base import FunnelRule


class RuleRegistryError(ValueError):
    pass


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], FunnelRule] = {}

    def register(self, rule: FunnelRule) -> None:
        key = (rule.rule_id, rule.rule_version)
        if key in self._rules:
            raise RuleRegistryError(f"duplicate rule {rule.rule_id}@{rule.rule_version}")
        if not rule.rule_hash:
            raise RuleRegistryError(f"rule {rule.rule_id}@{rule.rule_version} has empty hash")
        self._rules[key] = rule

    def resolve(self, rule_id: str, rule_version: str) -> FunnelRule:
        try:
            return self._rules[(rule_id, rule_version)]
        except KeyError as exc:
            raise RuleRegistryError(f"missing rule {rule_id}@{rule_version}") from exc

    def as_mapping(self) -> dict[tuple[str, str], FunnelRule]:
        return dict(self._rules)
