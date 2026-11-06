import json
import math
import statistics
from itertools import combinations, product
from typing import Any

from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger
from eval_runner.utils import crypto

logger = StructuredLogger("DecisionSupportProvider")


class DecisionSupportProvider(BaseProvider):
    """
    Higher-order provider that correlates data across multiple industries
    to provide synthetic "Decision Support" metrics and policy insights.
    """

    def __init__(self, config: dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.decision_support_mode = config.get("decision_support_mode", "policy_risk")
        if self.decision_support_mode == "standard":
            self.decision_support_mode = "policy_risk"

    async def extract(self) -> list[RawArtifact]:
        """
        Decision Support typically 'extracts' from internal engine state or
        consolidated datasets. For the pilot, we simulate the correlation inputs.
        """
        if self.allow_simulation:
            sim_input = {
                "agriculture": {"region": "USA", "yield_gap": -0.15},  # 15% below norm
                "environment": {"region": "USA", "temp_anomaly": +2.5},  # 2.5C above norm
                "economics": {"region": "USA", "inflation": 0.04},  # 4% CPI
            }
            return [
                self.create_simulated_artifact(
                    id="DECISION-CORRELATION",
                    content=sim_input,
                    source_url="internal://engine/correlation",
                    metadata={"source": "Internal Correlation Engine"},
                )
            ]
        return []

    async def transform(self, raw_artifacts: list[RawArtifact]) -> list[StandardSchema]:
        self.ensure_simulation_allowed(raw_artifacts)
        results = []
        TARGET_SCHEMA = {"region": "string", "risk_score": "number", "insight_summary": "string"}

        for raw in raw_artifacts:
            input_data = raw.content

            if self.decision_support_mode == "policy_risk":
                # Logic: Combine yield gap + temp anomaly + inflation
                yield_impact = abs(input_data.get("agriculture", {}).get("yield_gap", 0)) * 2
                temp_impact = input_data.get("environment", {}).get("temp_anomaly", 0) / 5

                risk_score = round((yield_impact + temp_impact) * 10, 2)

                raw_data = {
                    "region": input_data.get("agriculture", {}).get("region", "Unknown"),
                    "risk_score": risk_score,
                    "insight_summary": f"High risk identified due to yield gap ({input_data['agriculture']['yield_gap']}) and temperature anomaly (+{input_data['environment']['temp_anomaly']}C).",  # noqa: E501
                }

                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    results.append(
                        StandardSchema(
                            id=crypto.record_id(f"RISK-{raw_data['region']}"),
                            industry="decision_support",
                            data=verified,
                            provenance=self.record_provenance(
                                raw,
                                {
                                    "source": "Cross-Sector Analysis",
                                    "provider": "DecisionSupportEngine",
                                },
                            ),
                            checksum=crypto.checksum(json.dumps(verified, sort_keys=True)),
                        )
                    )

        return results

    def validate(self, normalized_data: list[StandardSchema]) -> bool:
        return all(0 <= r.data.get("risk_score", 0) <= 100 for r in normalized_data)

    def correlate_sectors(self, datasets: dict[str, list[StandardSchema]]) -> list[dict[str, Any]]:
        """Measure cross-sector co-movement over explicitly matched observations.

        ``correlation_keys`` selects shared observation coordinates, e.g. region/date.
        Otherwise use a shared date/period/year/timestamp and any shared region/country.
        Never align by row position or impute missing values. At least three complete
        observations are required; constant series have undefined coefficients (None).
        Composite anomalies are mean absolute population z-scores, not probabilities
        or causal claims. ``correlation_anomaly_threshold`` defaults to 2 standard
        deviations. Every result binds the exact contributing data and provenance.
        """
        from agentv_runtime.canonical import canonical_json_encode

        if not isinstance(datasets, dict) or any(
            not isinstance(sector, str) or not sector or not isinstance(rows, list)
            for sector, rows in datasets.items()
        ):
            raise ValueError("datasets must map sector names to record lists")
        minimum = self.config.get("correlation_min_observations", 3)
        threshold = self.config.get("correlation_anomaly_threshold", 2.0)
        if type(minimum) is not int or minimum < 3:
            raise ValueError("correlation_min_observations must be an integer of at least three")
        if not _finite_number(threshold) or threshold <= 0:
            raise ValueError("correlation_anomaly_threshold must be finite and positive")
        configured_keys = self.config.get("correlation_keys")
        if configured_keys is not None and (
            not isinstance(configured_keys, list)
            or not configured_keys
            or any(not isinstance(key, str) or not key for key in configured_keys)
            or len(set(configured_keys)) != len(configured_keys)
        ):
            raise ValueError("correlation_keys must contain unique field names")

        for rows in datasets.values():
            identities = set()
            for row in rows:
                if (
                    not isinstance(row, StandardSchema)
                    or not isinstance(row.data, dict)
                    or not isinstance(row.provenance, dict)
                ):
                    raise ValueError("Correlation inputs must be StandardSchema records")
                if not isinstance(row.id, str) or not row.id or row.id in identities:
                    raise ValueError("Correlation records require unique nonempty identities")
                identities.add(row.id)
                if _simulated(row) and not self.allow_simulation:
                    raise PermissionError("Simulated correlation inputs require allow_simulation")

        results = []
        for left_sector, right_sector in combinations(sorted(datasets), 2):
            left_rows, right_rows = datasets[left_sector], datasets[right_sector]
            common = (
                set.intersection(*(set(row.data) for row in left_rows + right_rows))
                if left_rows and right_rows
                else set()
            )
            keys = configured_keys
            if keys is None:
                time = next(
                    (key for key in ("date", "period", "year", "timestamp") if key in common), None
                )
                if time is None:
                    continue
                keys = [key for key in ("region", "country") if key in common] + [time]
            left, right = (
                _index_observations(left_rows, keys),
                _index_observations(right_rows, keys),
            )
            shared = sorted(left.keys() & right.keys())
            left_metrics = sorted(
                {
                    key
                    for row in left_rows
                    for key, value in row.data.items()
                    if key not in keys and _finite_number(value)
                }
            )
            right_metrics = sorted(
                {
                    key
                    for row in right_rows
                    for key, value in row.data.items()
                    if key not in keys and _finite_number(value)
                }
            )
            for left_metric, right_metric in product(left_metrics, right_metrics):
                matched = [
                    key
                    for key in shared
                    if _finite_number(left[key].data.get(left_metric))
                    and _finite_number(right[key].data.get(right_metric))
                ]
                if len(matched) < minimum:
                    continue
                x = [float(left[key].data[left_metric]) for key in matched]
                y = [float(right[key].data[right_metric]) for key in matched]
                pearson = _coefficient(x, y)
                spearman = _coefficient(_average_ranks(x), _average_ranks(y))
                zx, zy = _standard_scores(x), _standard_scores(y)
                anomaly_scores = [(abs(a) + abs(b)) / 2 for a, b in zip(zx, zy, strict=True)]

                def evidence(row):
                    content = {
                        "id": row.id,
                        "industry": row.industry,
                        "data": row.data,
                        "provenance": row.provenance,
                    }
                    return {
                        "record_id": row.id,
                        "declared_checksum": row.checksum,
                        "content_digest": "sha3_256:"
                        + crypto.checksum(canonical_json_encode(content)),
                    }

                result = {
                    "sectors": [left_sector, right_sector],
                    "metrics": [left_metric, right_metric],
                    "observation_count": len(matched),
                    "pearson": pearson,
                    "spearman": spearman,
                    "coefficient_status": "measured"
                    if pearson is not None
                    else "undefined_constant_series",
                    "risk": {
                        "method": "mean_absolute_population_z_score",
                        "composite_anomaly_score": max(anomaly_scores),
                        "threshold": float(threshold),
                        "anomalies": [
                            {"observation": json.loads(key), "score": score}
                            for key, score in zip(matched, anomaly_scores, strict=True)
                            if score >= threshold
                        ],
                    },
                    "provenance": {
                        "algorithm": "paired_pearson_and_average_rank_spearman",
                        "alignment_keys": list(keys),
                        "observations": [
                            {
                                "key": json.loads(key),
                                "left": evidence(left[key]),
                                "right": evidence(right[key]),
                            }
                            for key in matched
                        ],
                        "execution_mode": "simulated"
                        if any(
                            _simulated(row) for key in matched for row in (left[key], right[key])
                        )
                        else "measured",
                    },
                }
                result["correlation_id"] = crypto.checksum(canonical_json_encode(result))
                results.append(result)
        return results


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _simulated(row):
    return (
        bool(row.provenance.get("simulation"))
        or row.provenance.get("execution_mode") == "simulated"
    )


def _index_observations(rows, keys):
    indexed = {}
    for row in rows:
        if any(
            key not in row.data
            or not isinstance(row.data[key], (str, int))
            or isinstance(row.data[key], bool)
            or row.data[key] == ""
            for key in keys
        ):
            raise ValueError(
                "Observation alignment requires nonempty string or integer coordinates"
            )
        key = json.dumps([row.data[field] for field in keys], separators=(",", ":"))
        if key in indexed:
            raise ValueError("Duplicate observation coordinates are ambiguous")
        indexed[key] = row
    return indexed


def _average_ranks(values):
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        for index in ordered[start:end]:
            ranks[index] = (start + 1 + end) / 2
        start = end
    return ranks


def _coefficient(x, y):
    if min(x) == max(x) or min(y) == max(y):
        return None
    # Scale before covariance calculation to avoid overflowing finite large inputs.
    x_scale, y_scale = max(map(abs, x)), max(map(abs, y))
    return statistics.correlation(
        [value / x_scale for value in x], [value / y_scale for value in y]
    )


def _standard_scores(values):
    scale = max(map(abs, values)) or 1
    normalized = [value / scale for value in values]
    deviation = statistics.pstdev(normalized)
    mean = statistics.fmean(normalized)
    return [(value - mean) / deviation if deviation else 0.0 for value in normalized]
