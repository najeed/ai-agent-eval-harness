import json
from typing import Any

from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger
from eval_runner.utils import crypto

logger = StructuredLogger("HousingProvider")


class HousingProvider(BaseProvider):
    """
    Provider for Housing & Infrastructure data (HUD & World Bank).
    """

    def __init__(self, config: dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.housing_mode = config.get("housing_mode", "hud")  # hud, infrastructure
        self.api_key = config.get("hud_api_key")

    async def extract(self) -> list[RawArtifact]:
        if self.housing_mode == "infrastructure":
            # Gold Standard: World Bank Infrastructure
            indicator = self.config.get("indicator", "EG.ELC.ACCS.ZS")  # Access to electricity
            url = f"https://api.worldbank.org/v2/country/all/indicator/{indicator}?format=json"

            if self.allow_simulation:
                sim_infra = [
                    {"country": {"value": "India"}, "date": "2022", "value": 99.5},
                    {"country": {"value": "Nigeria"}, "date": "2022", "value": 55.4},
                ]
                return [
                    self.create_simulated_artifact(
                        id=f"WB-INFRA-{indicator}",
                        content=sim_infra,
                        source_url=url,
                        metadata={"indicator": indicator},
                    )
                ]
            return []

        # HUD: Housing and Urban Development (US) - Fair Market Rents
        # URI: https://www.huduser.gov/portal/datasets/fmr.html
        url = "https://www.huduser.gov/portal/datasets/fmr/api/"

        if self.allow_simulation:
            sim_hud = [
                {"msa_name": "San Francisco, CA", "fmr_2br": 3500, "year": 2023},
                {"msa_name": "Austin, TX", "fmr_2br": 1850, "year": 2023},
            ]
            return [
                self.create_simulated_artifact(
                    id="HUD-FMR", content=sim_hud, source_url=url, metadata={"source": "HUD"}
                )
            ]
        return []

    async def transform(self, raw_artifacts: list[RawArtifact]) -> list[StandardSchema]:
        results = []

        if self.housing_mode == "infrastructure":
            TARGET_SCHEMA = {"location": "string", "year": "integer", "access_rate": "number"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "location": row.get("country", {}).get("value"),
                        "year": int(row.get("date", 0)),
                        "access_rate": float(row.get("value") or 0),
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = crypto.record_id(
                            f"INFRA-{raw_data['location']}-{raw_data['year']}"
                        )
                        results.append(
                            StandardSchema(
                                id=record_id,
                                industry="housing",
                                data=verified,
                                provenance={"source": raw.source_url, "provider": "World Bank"},
                                checksum=crypto.checksum(json.dumps(verified, sort_keys=True)),
                            )
                        )
            return results

        # HUD Transformation
        TARGET_SCHEMA = {
            "location": "string",
            "rent_2br": "number",
            "year": "integer",
            "hpi_index": "number",
        }
        for raw in raw_artifacts:
            for row in raw.content:
                raw_data = {
                    "location": row.get("msa_name") or row.get("region") or "Unknown",
                    "rent_2br": float(row.get("fmr_2br", 0)),
                    "year": int(row.get("year", 0)),
                    "hpi_index": float(row.get("index_value", 0)),
                }
                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = crypto.record_id(f"HUD-{raw_data['location']}-{raw_data['year']}")
                    results.append(
                        StandardSchema(
                            id=record_id,
                            industry="housing",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "HUD"},
                            checksum=crypto.checksum(json.dumps(verified, sort_keys=True)),
                        )
                    )
        return results

    def validate(self, normalized_data: list[StandardSchema]) -> bool:
        return all(
            r.data.get("rent_2br", 0) >= 0 and r.data.get("access_rate", 0) >= 0
            for r in [r for r in normalized_data if "rent_2br" in r.data or "access_rate" in r.data]
        )
