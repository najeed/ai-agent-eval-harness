import hashlib
import json
import asyncio
import os
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("HealthcareProvider")

class HealthcareProvider(BaseProvider):
    """
    Deepened Consumer for CMS Hospital Data - Multi-dataset support.
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        # Support multiple CMS datasets (General, Patient Exp, Mortality)
        self.csv_paths = config.get("input_uris", [config.get("input_uri", "Hospital_General_Information.csv")])
        self.schema_type = config.get("schema_type", "cms") # cms (default), mimic_iii, mimic_iv

    async def extract(self) -> List[RawArtifact]:
        if self.schema_type in ["mimic_iii", "mimic_iv"]:
            # Gold Standard: MIMIC Clinical Research Data (Simulated)
            dataset_version = "MIMIC-IV" if self.schema_type == "mimic_iv" else "MIMIC-III"
            
            # Unified Data Acquisition (Local or Web URL)
            path = self.config.get("input_uri") or ""
            df = self.load_raw_data(path)
            
            if df is not None:
                return [RawArtifact(
                    id=f"{dataset_version}-USER",
                    source_url=path,
                    content=df.to_dict(orient="records"),
                    metadata={"dataset": f"{dataset_version} Clinical Database", "source": "User-Provided"},
                    timestamp=datetime.utcnow().isoformat()
                )]
            
            # High-Fidelity Simulation (MIMIC-IV includes diagnosis codes and modular hosp/icu data)
            sim_content = [
                {"subject_id": "1001", "hadm_id": "210001", "lab_item": "Glucose", "value": 112, "uom": "mg/dL", "flag": "normal", "module": "hosp"},
                {"subject_id": "1002", "hadm_id": "210002", "lab_item": "Creatinine", "value": 1.4, "uom": "mg/dL", "flag": "abnormal", "module": "hosp"},
                {"subject_id": "1003", "hadm_id": "210003", "lab_item": "Potassium", "value": 4.5, "uom": "mEq/L", "flag": "normal", "module": "icu"}
            ] if self.schema_type == "mimic_iv" else [
                {"subject_id": 1001, "hadm_id": 156001, "lab_item": "Glucose", "value": 112, "uom": "mg/dL", "flag": "normal"},
                {"subject_id": 1002, "hadm_id": 156002, "lab_item": "Creatinine", "value": 1.4, "uom": "mg/dL", "flag": "abnormal"},
                {"subject_id": 1003, "hadm_id": 156003, "lab_item": "Hemoglobin", "value": 13.5, "uom": "g/dL", "flag": "normal"}
            ]

            return [RawArtifact(
                id=f"{dataset_version}-SIM",
                source_url="https://mimic.mit.edu/",
                content=sim_content,
                metadata={"dataset": f"{dataset_version} Clinical Database", "type": "lab_events"},
                timestamp=datetime.utcnow().isoformat()
            )]

        limit = self.config.get("limit", 50)
        artifacts = []
        
        async def fetch_csv(path):
            try:
                # For the pilot, we assume local CSV access, but structured for remote expansion
                logger.info("processing_cms_dataset", path=path)
                # Check if file exists otherwise use simulation
                if os.path.exists(path):
                    df = pd.read_csv(path)
                    subset = df.head(limit)
                    content = subset.to_dict(orient="records")
                else:
                    logger.warning("cms_file_missing_using_sim", path=path)
                    content = [
                        {"Hospital Name": "SIM CLINIC A", "Provider ID": "001", "Hospital overall rating": 4, "Mortality national comparison": "Same"},
                        {"Hospital Name": "SIM CLINIC B", "Provider ID": "002", "Hospital overall rating": 5, "Mortality national comparison": "Above"}
                    ]
                
                content_hash = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:12]
                
                return RawArtifact(
                    id=f"cms-{content_hash}",
                    source_url=path,
                    content=content,
                    metadata={"source": "CMS", "type": "hospital_metrics"},
                    timestamp=datetime.utcnow().isoformat()
                )
            except Exception as e:
                logger.error("cms_extraction_failed", path=path, error=str(e))
                return None

        # Fix paths if they are placeholders
        actual_paths = [p for p in self.csv_paths if os.path.exists(p)]
        if not actual_paths:
            actual_paths = ["sim_cms.csv"] # Trigger simulation in fetch_csv

        tasks = [fetch_csv(p) for p in actual_paths]
        results = await asyncio.gather(*tasks)
        artifacts = [r for r in results if r]
        
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        
        if self.schema_type in ["mimic_iii", "mimic_iv"]:
            dataset_version = "MIMIC-IV" if self.schema_type == "mimic_iv" else "MIMIC-III"
            TARGET_SCHEMA = {
                "subject_id": "string",
                "admission_id": "string",
                "lab_test": "string",
                "result_value": "number",
                "result_unit": "string",
                "status_flag": "string",
                "data_module": "string"
            }
            for artifact in raw_artifacts:
                for row in artifact.content:
                    raw_data = {
                        "subject_id": str(row.get("subject_id")),
                        "admission_id": str(row.get("hadm_id")),
                        "lab_test": row.get("lab_item"),
                        "result_value": float(row.get("value", 0)),
                        "result_unit": row.get("uom"),
                        "status_flag": row.get("flag"),
                        "data_module": row.get("module", "hosp") if self.schema_type == "mimic_iv" else "legacy"
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"{dataset_version}-{row.get('subject_id')}-{row.get('hadm_id')}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry="healthcare",
                            data=verified,
                            provenance={"source": artifact.source_url, "schema": dataset_version},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        TARGET_SCHEMA = {
            "facility_name": "string",
            "provider_id": "string",
            "overall_rating": "number",
            "mortality_metric": "string",
            "patient_experience": "string",
            "location": "string"
        }
        
        for artifact in raw_artifacts:
            rows = artifact.content
            for row in rows:
                # Deterministic ID based on Provider ID or Patient ID
                p_id = str(row.get("Provider ID") or row.get("provider_id") or row.get("patient_id") or "NA")
                facility_name = self.scrub_pii(row.get("Hospital Name") or row.get("hospital_name") or row.get("department", "Unknown"))
                
                # Deterministic ID for cross-dataset record linking
                record_id = hashlib.md5(f"{p_id}-{facility_name}".encode()).hexdigest()[:16]
                
                raw_data = {
                    "facility_name": facility_name,
                    "provider_id": p_id,
                    "overall_rating": row.get("Hospital overall rating", 0) or row.get("rating", 0) or 4.0, # Default rating for patient data
                    "mortality_metric": row.get("Mortality national comparison", "Not Available"),
                    "patient_experience": row.get("Patient experience national comparison", row.get("status", "Not Available")),
                    "location": self.scrub_pii(str(row.get("Address") or row.get("location", "Unknown")))
                }
                
                # Strict Schema Verification
                verified_data = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified_data:
                    raw_str = json.dumps(verified_data, sort_keys=True)
                    data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                    results.append(StandardSchema(
                        id=record_id,
                        industry="healthcare",
                        data=verified_data,
                        provenance={
                            "source": "CMS dataset",
                            "file": artifact.source_url,
                            "provider_id": p_id
                        },
                        checksum=data_checksum
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        for record in normalized_data:
            if self.schema_type in ["mimic_iii", "mimic_iv"]:
                if not record.data.get("subject_id"): return False
            else:
                if not record.data.get("facility_name"):
                    logger.warning("validation_failed", record_id=record.id, reason="Missing facility name")
                    return False
        return True
