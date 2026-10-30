import logging
import math
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import pandas as pd

from .base_provider import StandardSchema

logger = logging.getLogger("DataCorrelator")

CORRELATION_ALGORITHM = "difflib.SequenceMatcher.ratio/autojunk=false/v1"
CORRELATION_NORMALIZATION = "unicode-nfkc-casefold-alphanumeric-whitespace/v1"
DEFAULT_MINIMUM_SIMILARITY = 85.0


def _entity_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w\s]|_", " ", value).split())


class DataCorrelator:
    """
    Establishes cross-industry correlations and enriches datasets with inferred signals.
    """

    @staticmethod
    def correlate_cross_sector(
        primary_dataset: list[StandardSchema],
        secondary_dataset: list[StandardSchema],
        correlation_type: str,
    ) -> list[StandardSchema]:
        """Convenience wrapper for two-dataset correlation."""
        datasets = {"primary": primary_dataset, "secondary": secondary_dataset}
        results = DataCorrelator.correlate(datasets)
        return results.get("primary", [])

    @staticmethod
    def correlate(
        datasets: dict[str, list[StandardSchema]],
        target_dir: str | None = None,
        *,
        minimum_similarity: float = DEFAULT_MINIMUM_SIMILARITY,
    ) -> dict[str, list[StandardSchema]]:
        """
        Main entry point for cross-dataset correlation.
        """
        if (
            isinstance(minimum_similarity, bool)
            or not isinstance(minimum_similarity, (int, float))
            or not math.isfinite(minimum_similarity)
            or not 0 < minimum_similarity <= 100
        ):
            raise ValueError("minimum_similarity must be finite and greater than 0, up to 100")
        logger.info("Starting cross-industry correlation...")

        # 1. Discover existing datasets recursively in the target directory to enrich current run
        if target_dir and os.path.exists(target_dir):
            for root, directories, files in os.walk(target_dir):
                directories.sort()
                for file in sorted(files):
                    if file.endswith((".csv", ".jsonl")):
                        # Infer industry from filename (e.g., finance_records.csv -> finance)
                        ind_name = file.split("_")[0].split(".")[0]
                        if ind_name not in datasets:
                            logger.info(
                                f"Discovered '{ind_name}' dataset at {root}/{file} for correlation."
                            )
                            try:
                                path = os.path.join(root, file)
                                if file.endswith(".csv"):
                                    df = pd.read_csv(path)
                                else:
                                    df = pd.read_json(path, lines=True)

                                # Use native serialization helper
                                datasets[ind_name] = [
                                    StandardSchema.from_pandas(row, ind_name)
                                    for _, row in df.iterrows()
                                ]
                            except Exception as e:
                                logger.warning(f"Failed to load existing dataset {file}: {e}")

        # 2. Build an Entity Map (Industry -> Name -> Record)
        entity_map = {}
        for industry, records in datasets.items():
            # Sorting fixes ties and duplicate normalized names independently of input order.
            entity_map[industry] = {}
            for record in sorted(records, key=lambda r: str(r.id)):
                name = _entity_name(record.data.get("entity_name", record.data.get("name")))
                if name:
                    entity_map[industry].setdefault(name, record)

        # 3. Propagate Signals
        for industry, current_records in datasets.items():
            if industry == "finance":
                for fin_record in current_records:
                    # Re-running correlation must not retain a link rejected by the new inputs.
                    fin_record.data.pop("telecom_footprint_speed", None)
                    fin_record.provenance.pop("correlated_telecom_id", None)
                    fin_record.provenance.pop("telecom_correlation", None)
                    fin_name = _entity_name(fin_record.data.get("entity_name"))
                    if not fin_name:
                        continue

                    # Telecom Enrichment
                    if "telecom" in entity_map:
                        tel_names = sorted(entity_map["telecom"])
                        matched_name = None
                        score = 0.0
                        # A single scorer makes optional dependencies irrelevant to evidence.
                        for name in tel_names:
                            measured = (
                                100.0
                                * SequenceMatcher(None, fin_name, name, autojunk=False).ratio()
                            )
                            if measured >= minimum_similarity and measured > score:
                                matched_name, score = name, measured

                        if matched_name:
                            tel_record = entity_map["telecom"][matched_name]
                            logger.info(
                                "Measured entity similarity: "
                                f"{fin_name} <-> {matched_name} (Score: {score})"
                            )
                            fin_record.data["telecom_footprint_speed"] = tel_record.data.get(
                                "value"
                            )
                            fin_record.provenance["correlated_telecom_id"] = tel_record.id
                            fin_record.provenance["telecom_correlation"] = {
                                "matched_record_id": tel_record.id,
                                "similarity_score": score,
                                "score_scale": "0-100",
                                "minimum_similarity": float(minimum_similarity),
                                "algorithm": CORRELATION_ALGORITHM,
                                "normalization": CORRELATION_NORMALIZATION,
                                "source_name": fin_name,
                                "matched_name": matched_name,
                                "tie_break": "normalized-name-then-record-id-ascending",
                            }

                    # Energy Enrichment (Spatio-Temporal Matching)
                    if "energy" in datasets:
                        fin_date = fin_record.data.get("last_updated", "").split("T")[
                            0
                        ] or fin_record.data.get("date", "")
                        matching_energy = [
                            r
                            for r in datasets["energy"]
                            if r.data.get("date") == fin_date
                            or str(r.data.get("period")) == fin_date
                        ]

                        if matching_energy:
                            avg_price = sum(
                                r.data.get("latest_value", 0) for r in matching_energy
                            ) / len(matching_energy)
                            fin_record.data["spatio_temporal_energy_cost"] = avg_price
                        else:
                            energy_vals = [
                                r.data.get("latest_value", 0.0) for r in datasets["energy"]
                            ]
                            if energy_vals:
                                fin_record.data["macro_energy_index_fallback"] = sum(
                                    energy_vals
                                ) / len(energy_vals)

                    # Ecommerce Sentiment Enrichment
                    if "ecommerce" in datasets:
                        ecom_sentiments = [
                            r.data.get("sentiment", 0.5) for r in datasets["ecommerce"]
                        ]
                        if ecom_sentiments:
                            fin_record.data["global_ecommerce_sentiment"] = sum(
                                ecom_sentiments
                            ) / len(ecom_sentiments)

            if industry == "healthcare":
                for hc_record in current_records:
                    # Link Healthcare ratings to local Energy reliability if available
                    if "energy" in datasets:
                        energy_vals = [r.data.get("latest_value", 0.0) for r in datasets["energy"]]
                        if energy_vals:
                            hc_record.data["energy_resiliency_index"] = sum(energy_vals) / len(
                                energy_vals
                            )

        return datasets

    @staticmethod
    def normalize_signal(value: Any, min_val: float, max_val: float) -> float:
        """
        Unified 0.0-1.0 signal normalization.
        """
        try:
            val = float(value)
            return (val - min_val) / (max_val - min_val) if max_val > min_val else 0.5
        except (ValueError, TypeError):
            return 0.0
