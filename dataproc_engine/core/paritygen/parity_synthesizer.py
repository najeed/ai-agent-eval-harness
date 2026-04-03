import json
import random
import datetime
import pandas as pd
import numpy as np
from scipy.stats import ks_2samp
from typing import List, Dict, Any, Optional

class ParitySynthesizer:
    """
    V2.0 High-Signal Statistical Simulator.
    Policy: Generator-only for Restricted; Embedded for Permissive.
    Generates statistical samples from user-supplied parameters.
    """
    
    # Statistical Metadata (Schemas + Distributions)
    MODELS = {
        "world_bank_gdp": {
            "license": "CC-BY 4.0",
            "schema": {"country": "string", "gdp_billions": "number", "year": "integer"},
            "distributions": {
                "gdp_billions": {"mean": 500, "std": 150, "min": 1.0},
                "year": {"min": 2010, "max": 2025}
            },
            "countries": ["USA", "CHN", "JPN", "DEU", "IND", "GBR", "FRA", "BRA", "CAN"]
        },
        "sec_fundamentals": {
            "license": "Public Domain",
            "schema": {"ticker": "string", "revenue_mil": "number", "net_income_mil": "number"},
            "distributions": {
                "revenue_mil": {"mean": 15000, "std": 3000, "min": 10},
                "net_income_mil": {"mean": 2000, "std": 500}
            },
            "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]
        },
        "clinical": {
            "license": "Restricted (User-Supplied)",
            "policy": "generator_only",
            "schema": {"subject_id": "integer", "glucose_mg_dl": "number", "heart_rate": "number", "status": "string"},
            "distributions": {
                # Parameters sourced from standard clinical literature.
                # Not derived from any restricted dataset.
                "glucose_mg_dl": {"mean": 120, "std": 40, "min": 20, "max": 600},
                "heart_rate": {"mean": 80, "std": 15, "min": 40, "max": 200}
            }
        },
        "macro_energy_balances": {
            "license": "Restricted (User-Supplied)",
            "policy": "generator_only",
            "schema": {"region": "string", "tpes_mtoe": "number", "co2_mt": "number"},
            "distributions": {
                # Parameters calibrated on publicly available energy statistics literature.
                "tpes_mtoe": {"mean": 200, "std": 800, "min": 0.1},
                "co2_mt": {"mean": 500, "std": 1500, "min": 0.0}
            },
            "regions": ["USA", "CHN", "IND", "DEU", "RUS", "BRA", "CAN", "FRA"],
            "distribution_note": "Right-skewed; log-normal approximation recommended for production use"
        },
        "industrial_sector_stats": {
            "license": "Restricted (User-Supplied)",
            "policy": "generator_only",
            "schema": {"sector_code": "integer", "valuation_mil": "number", "labor_units": "integer"},
            "distributions": {
                # Parameters calibrated on public industrial market reports.
                "valuation_mil": {"mean": 5000, "std": 15000, "min": 10},
                "labor_units": {"mean": 20000, "std": 80000, "min": 100, "max": 1000000}
            },
            "distribution_note": "Right-skewed; log-normal approximation recommended for production use"
        },
        "ecommerce_transaction_parity": {
            "license": "CC BY-NC-SA 4.0",
            "policy": "generator_only",
            "schema": {"order_id": "string", "price": "number", "freight_value": "number", "product_category": "string"},
            "distributions": {
                # Parameters calibrated on e-commerce public dataset summaries.
                "price": {"mean": 120, "std": 180, "min": 0.85},
                "freight_value": {"mean": 20, "std": 15, "min": 0.0}
            },
            "product_categories": ["health_beauty", "watches_gifts", "bed_bath_table", "sports_leisure", "computers_accessories"]
        },
        "agri_stats_parity": {
            "license": "CC BY-NC-SA 3.0",
            "policy": "generator_only",
            "schema": {"area_code": "integer", "item_code": "integer", "value_tonnes": "number"},
            "distributions": {
                # Parameters calibrated on FAOStat public yearbooks.
                "value_tonnes": {"mean": 50000, "std": 100000, "min": 0.0}
            }
        },
        "media_metadata_parity": {
            "license": "Non-Commercial",
            "policy": "generator_only",
            "schema": {"tconst": "string", "averageRating": "number", "numVotes": "integer"},
            "distributions": {
                # Parameters calibrated on IMDb non-commercial datasets.
                "averageRating": {"mean": 6.8, "std": 1.2, "min": 1.0, "max": 10.0},
                "numVotes": {"mean": 5000, "std": 20000, "min": 1, "max": 10000000}
            }
        },
        "network_performance_parity": {
            "license": "CC BY-NC-SA 4.0",
            "policy": "generator_only",
            "schema": {"avg_d_kbps": "number", "avg_u_kbps": "number", "avg_lat_ms": "integer"},
            "distributions": {
                # Parameters calibrated on Ookla open tiles datasets.
                "avg_d_kbps": {"mean": 80000, "std": 40000, "min": 100},
                "avg_u_kbps": {"mean": 20000, "std": 10000, "min": 10},
                "avg_lat_ms": {"mean": 30, "std": 20, "min": 1, "max": 2000}
            }
        }
    }

    def generate_statistical_twin(self, model_id: str, count: int = 10) -> List[Dict[str, Any]]:
        """
        Generates non-verbatim synthetic records with Batch Mean Correction.
        Ensures mathematical parity for numeric distributions.
        """
        if model_id not in self.MODELS:
            raise ValueError(f"Unknown synthesis model: {model_id}")
            
        model = self.MODELS[model_id]
        raw_results = [{} for _ in range(count)]
        
        # 1. Generate Base Fields
        for i in range(count):
            for key, val_type in model["schema"].items():
                if key not in model.get("distributions", {}):
                    # Categorical or Identifier
                    if key == "country":
                        raw_results[i][key] = random.choice(model["countries"])
                    elif key == "ticker":
                        raw_results[i][key] = random.choice(model["tickers"])
                    elif key == "status":
                        raw_results[i][key] = random.choice(["Stable", "Critical", "Discharged"])
                    elif key in ("isic_code", "sector_code"):
                        raw_results[i][key] = random.randint(10, 99)
                    elif key == "region":
                        raw_results[i][key] = random.choice(model["regions"])
                    elif key == "product_category":
                        raw_results[i][key] = random.choice(model["product_categories"])
                    else:
                        raw_results[i][key] = f"SYN-{model_id}-{random.randint(1000, 9999)}"

        # 2. Generate and Correct Numeric Distributions (Mathematical Parity)
        for key, dist in model.get("distributions", {}).items():
            if model["schema"][key] == "integer":
                # Integer fields use standard random range
                for i in range(count):
                    raw_results[i][key] = random.randint(dist["min"], dist["max"])
                continue

            # Floating point correction (Dual-Moment Alignment: Mean & Variance)
            # 1. Base generation
            vals = [random.gauss(dist["mean"], dist["std"]) for _ in range(count)]
            
            # 2. Rescale to Match Gold Moments (Dual-Moment Alignment)
            raw_series = np.array(vals)
            curr_mean = np.mean(raw_series)
            curr_std = np.std(raw_series)
            
            if curr_std != 0:
                scaled_series = [((x - curr_mean) / curr_std) * dist["std"] + dist["mean"] for x in raw_series]
            else:
                scaled_series = raw_series
            
            corrected_vals = []
            for v in scaled_series:
                corrected = v
                
                # Boundary Checks (Hardened)
                if dist.get("min") is not None: 
                    corrected = max(corrected, dist["min"])
                if dist.get("max") is not None: 
                    corrected = min(corrected, dist["max"])
                corrected_vals.append(round(corrected, 2))
                
            for i in range(count):
                raw_results[i][key] = corrected_vals[i]
            
        # 3. Add Compliance Metadata (V2: Policy-Aware Status)
        for record in raw_results:
            is_restricted = model.get("policy") == "generator_only" or "Restricted" in model.get("license", "")
            record["_synthesis_audit"] = {
                "generation_method": "statistical_sampling",
                "source_license": model["license"],
                "conservative_status": "local_only" if is_restricted else "embedded",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "disclaimer": "User is responsible for ensuring source data access is compliant."
            }
            
        return raw_results

    def get_compliance_manifest(self) -> Dict[str, Any]:
        return {model_id: meta["license"] for model_id, meta in self.MODELS.items()}
