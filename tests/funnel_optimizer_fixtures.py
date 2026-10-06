"""Compatibility imports for Funnel Optimizer V1 test fixtures.

The deterministic negative fixture is in the source package because the
acceptance-artifact producer uses the identical infrastructure proof.
"""

from ag_edgelab.optimization.synthetic_fixture import (build_event_table as build_fixture_table,
                                                       opportunities as fixture_opportunities,
                                                       rules as fixture_rules)

__all__ = ["build_fixture_table", "fixture_opportunities", "fixture_rules"]
