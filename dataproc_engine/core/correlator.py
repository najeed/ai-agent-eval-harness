import logging
import os
import pandas as pd
from typing import List, Dict, Any, Optional
from .base_provider import StandardSchema

logger = logging.getLogger("DataCorrelator")

class DataCorrelator:
    """
    Establishes cross-industry correlations and enriches datasets with inferred signals.
    """
    
    @staticmethod
    def correlate_cross_sector(primary_dataset: List[StandardSchema], secondary_dataset: List[StandardSchema], correlation_type: str) -> List[StandardSchema]:
        """Convenience wrapper for two-dataset correlation."""
        datasets = {"primary": primary_dataset, "secondary": secondary_dataset}
        results = DataCorrelator.correlate(datasets)
        return results.get("primary", [])

    @staticmethod
    def correlate(datasets: Dict[str, List[StandardSchema]], target_dir: Optional[str] = None) -> Dict[str, List[StandardSchema]]:
        """
        Main entry point for cross-dataset correlation.
        """
        logger.info("Starting cross-industry correlation...")
        
        # 1. Discover existing datasets recursively in the target directory to enrich current run
        if target_dir and os.path.exists(target_dir):
            for root, _, files in os.walk(target_dir):
                for file in files:
                    if file.endswith((".csv", ".jsonl")):
                        # Infer industry from filename (e.g., finance_records.csv -> finance)
                        ind_name = file.split("_")[0].split(".")[0]
                        if ind_name not in datasets:
                            logger.info(f"Discovered '{ind_name}' dataset at {root}/{file} for correlation.")
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
            entity_map[industry] = {str(r.data.get("entity_name", r.data.get("name", ""))).lower().strip(): r for r in records}

        # 3. Propagate Signals
        for industry, current_records in datasets.items():
            if industry == "finance":
                for fin_record in current_records:
                    fin_name = str(fin_record.data.get("entity_name", "")).lower().strip()
                    if not fin_name: continue

                    # Telecom Enrichment
                    if "telecom" in entity_map:
                        from rapidfuzz import process, utils
                        tel_names = list(entity_map["telecom"].keys())
                        # Find the best match with a score threshold
                        match = process.extractOne(
                            fin_name, 
                            tel_names, 
                            processor=utils.default_process,
                            score_cutoff=85
                        )
                        
                        if match:
                            matched_name = match[0]
                            tel_record = entity_map["telecom"][matched_name]
                            logger.info(f"Fuzzy Match: {fin_name} <-> {matched_name} (Score: {match[1]})")
                            fin_record.data["telecom_footprint_speed"] = tel_record.data.get("value")
                            fin_record.provenance["correlated_telecom_id"] = tel_record.id
                    
                    # Energy Enrichment (Spatio-Temporal Matching)
                    if "energy" in datasets:
                        fin_date = fin_record.data.get("last_updated", "").split("T")[0] or fin_record.data.get("date", "")
                        matching_energy = [
                            r for r in datasets["energy"] 
                            if r.data.get("date") == fin_date or str(r.data.get("period")) == fin_date
                        ]
                        
                        if matching_energy:
                            avg_price = sum(r.data.get("latest_value", 0) for r in matching_energy) / len(matching_energy)
                            fin_record.data["spatio_temporal_energy_cost"] = avg_price
                        else:
                            energy_vals = [r.data.get("latest_value", 0.0) for r in datasets["energy"]]
                            if energy_vals:
                                fin_record.data["macro_energy_index_fallback"] = sum(energy_vals) / len(energy_vals)

                    # Ecommerce Sentiment Enrichment
                    if "ecommerce" in datasets:
                        ecom_sentiments = [r.data.get("sentiment", 0.5) for r in datasets["ecommerce"]]
                        if ecom_sentiments:
                            fin_record.data["global_ecommerce_sentiment"] = sum(ecom_sentiments) / len(ecom_sentiments)

            if industry == "healthcare":
                for hc_record in current_records:
                    # Link Healthcare ratings to local Energy reliability if available
                    if "energy" in datasets:
                        energy_vals = [r.data.get("latest_value", 0.0) for r in datasets["energy"]]
                        if energy_vals:
                            hc_record.data["energy_resiliency_index"] = sum(energy_vals) / len(energy_vals)

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


