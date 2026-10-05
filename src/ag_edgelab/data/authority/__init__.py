"""EdgeLab canonical market-data authority (DATA_AUTHORITY_R1).

This package is the single place where "what counts as authoritative market
data" is defined for EdgeLab. It is deliberately strategy-free: nothing here
evaluates, selects, tunes, or scores a trading rule. It answers only:

  * where did these bytes come from, and can that be proven again?
  * what is the canonical schema, and does this dataset satisfy it?
  * what is the timezone frame, and how do we KNOW?
  * which observations are missing, and why — without ever inventing one?
  * which higher timeframes descend from which raw lineage?
  * which partition is a given observation in, and may it be read?

Design rules (enforced by tests):

  RAW IMMUTABILITY   raw bytes are never rewritten; derived datasets name
                     their raw parents by hash.
  FAIL CLOSED        a missing or mismatched hash is an error, never a
                     warning and never a silent re-derivation.
  NO INVENTION       no forward fill, no synthesised candle, no assumed
                     spread, no assumed volume. Absence stays absent.
  NO SILENT REPAIR   suspicious observations are CLASSIFIED, not fixed.
  CAUSAL ONLY        derived bars are completed-bar semantics; an accessor
                     may never expose a bucket that has not closed.
"""

from ag_edgelab.data.authority.schema import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalBar,
    PRICE_DECIMALS,
    SchemaViolation,
    dumps_canonical,
    loads_canonical,
    canonical_dataset_hash,
    validate_canonical_series,
)

__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "CanonicalBar",
    "PRICE_DECIMALS",
    "SchemaViolation",
    "dumps_canonical",
    "loads_canonical",
    "canonical_dataset_hash",
    "validate_canonical_series",
]
