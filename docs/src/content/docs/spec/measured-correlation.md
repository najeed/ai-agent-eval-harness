---
title: Measured entity correlation
description: Deterministic entity similarity, thresholds, and provenance in the AgentV data processor.
---

AgentV's `dataproc_engine.core.correlator.DataCorrelator` uses one comparison
algorithm in every installation:
`difflib.SequenceMatcher.ratio/autojunk=false/v1`. Optional RapidFuzz installation
does not select another scorer, threshold, normalization, or candidate.

Names are Unicode NFKC normalized, case-folded, converted to alphanumeric words
with punctuation/underscores replaced by spaces, and whitespace collapsed. This
normalization is identified as
`unicode-nfkc-casefold-alphanumeric-whitespace/v1`. Missing, non-string, and
empty normalized names cannot match.

The measured similarity is `100 * SequenceMatcher(None, source, candidate,
autojunk=False).ratio()`. It is a similarity metric on normalized strings, not a
probability that two records describe the same entity. No numeric confidence is
assigned to substring or heuristic classes. A short substring no longer receives
an automatic score of 95.

`correlate(datasets, minimum_similarity=85.0)` accepts the best candidate whose
measured score meets the explicit threshold, inclusively. The threshold must be
finite, greater than zero, and at most 100. A deployment may deliberately choose
another threshold, which is retained in provenance. Weak matches previously
accepted by the 0.5 fallback cutoff can now remain unlinked.

Ties use normalized candidate name order, then record ID order. Duplicate
normalized names retain the record with the first sorted ID. Candidate input
order and optional-library availability cannot change this decision.

The finance record retains `telecom_footprint_speed` and the existing
`provenance.correlated_telecom_id`. Its additional `provenance.telecom_correlation`
object records:

- `matched_record_id`, `source_name`, and `matched_name`;
- `similarity_score`, `score_scale: "0-100"`, and `minimum_similarity`;
- `algorithm`, `normalization`, and `tie_break` identifiers.

Re-running correlation removes a previous telecom link, enrichment, and its
provenance if the new inputs or threshold no longer permit that link. The
structured provenance is included in the existing `StandardSchema.to_dict()`
export. 