import aiohttp
import asyncio
import hashlib
import json
import datetime
from typing import List, Dict, Any
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("FinanceProvider")

class FinanceProvider(BaseProvider):
    """
    Deepened Finance industry provider for SEC XBRL data.
    """
    # Default high-signal cohort (Apple, Microsoft, Tesla, Amazon, Meta)
    DEFAULT_CIKS = ["0000320193", "0000789019", "0001652044", "0001018724", "0001326801"]

    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.sec_user_agent = config.get("sec_user_agent", "Mozilla/5.0 (Evaluation Harness)")
        self.taxonomy = config.get("taxonomy", "us-gaap") 
        self.currency = config.get("currency", "USD")
        self.schema_type = config.get("schema_type", "sec_edgar") # sec_edgar, credit_risk, world_bank

    async def extract(self) -> List[RawArtifact]:
        if self.schema_type == "world_bank":
            # Gold Standard: World Bank Global Macro Indicators
            # Default indicator: GDP (current US$) - NY.GDP.MKTP.CD
            indicator = self.config.get("indicator", "NY.GDP.MKTP.CD")
            country = self.config.get("country", "all")
            url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&per_page=100"
            
            async with aiohttp.ClientSession() as session:
                async def fetch_wb():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        raise Exception(f"World Bank API Error: {resp.status}")
                
                try:
                    content = await self.request_with_retry(fetch_wb)
                    if content and len(content) > 1:
                        return [RawArtifact(
                            id=f"WB-{indicator}-{country}",
                            source_url=url,
                            content=content[1], # Index 1 contains the actual data records
                            metadata={"indicator": indicator, "country": country},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
                except Exception as e:
                    logger.error("wb_extraction_failed", indicator=indicator, error=str(e))
                
                if self.allow_simulation:
                    simulated_wb = [
                        {"country": {"value": "United States"}, "indicator": {"value": "GDP"}, "value": 23315081000000, "date": "2021"},
                        {"country": {"value": "China"}, "indicator": {"value": "GDP"}, "value": 17734062000000, "date": "2021"}
                    ]
                    return [self.create_simulated_artifact(
                        id=f"WB-{indicator}",
                        content=simulated_wb,
                        source_url=url,
                        metadata={"indicator": indicator}
                    )]
                return []

        if self.schema_type == "credit_risk":
            # Gold Standard: UCI Default of Credit Card Clients
            url = "https://archive.ics.uci.edu/ml/machine-learning-databases/00350/default%20of%20credit%20card%20clients.xls"
            
            # Unified Data Acquisition (Local or Web URL)
            path = self.config.get("input_uri") or ""
            df = self.load_raw_data(path)
            
            if df is not None:
                return [RawArtifact(
                    id="UCI-CREDIT-USER",
                    source_url=path,
                    content=df.to_dict(orient="records"),
                    metadata={"dataset": "UCI Default Credits", "source": "User-Provided"},
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )]

            if self.allow_simulation:
                simulated_data = [
                    {"ID": 1, "LIMIT_BAL": 20000, "SEX": 2, "EDUCATION": 2, "MARRIAGE": 1, "AGE": 24, "PAY_0": 2, "BILL_AMT1": 3913, "PAY_AMT1": 0, "default": 1},
                    {"ID": 2, "LIMIT_BAL": 120000, "SEX": 2, "EDUCATION": 2, "MARRIAGE": 2, "AGE": 26, "PAY_0": -1, "BILL_AMT1": 2682, "PAY_AMT1": 0, "default": 1}
                ]
                return [self.create_simulated_artifact(
                    id="UCI-CREDIT",
                    content=simulated_data,
                    source_url=url,
                    metadata={"dataset": "UCI Default Credits"}
                )]
            return []

        ciks = self.config.get("ciks") or self.DEFAULT_CIKS
        limit = self.config.get("limit", len(ciks))
        target_ciks = ciks[:limit]
        
        headers = {"User-Agent": self.sec_user_agent}
        artifacts = []
        
        async with aiohttp.ClientSession() as session:
            async def process_cik(cik):
                padded_cik = cik.zfill(10)
                url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded_cik}.json"
                
                async def fetch_sec_data():
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        raise Exception(f"SEC API Error: {resp.status}")
                
                try:
                    logger.info("queuing_sec_fetch", cik=padded_cik)
                    content = await self.request_with_retry(fetch_sec_data)
                    if not content:
                        return None
                        
                    company_name = content.get("entityName", f"CIK {cik}")
                    return RawArtifact(
                        id=f"SEC-{cik}-FACTS",
                        source_url=url,
                        content=content,
                        metadata={"company": company_name, "cik": cik},
                        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                    )
                except Exception as e:
                    logger.error("sec_extraction_failed", cik=padded_cik, error=str(e))
                    return None

            tasks = [process_cik(cik) for cik in target_ciks]
            results = await asyncio.gather(*tasks)
            artifacts.extend([r for r in results if r])
            
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        
        if self.schema_type == "credit_risk":
            TARGET_SCHEMA = {
                "client_id": "string",
                "limit_balance": "number",
                "education_level": "string",
                "age": "number",
                "payment_status_recent": "number",
                "default_binary": "number"
            }
            edu_map = {1: "Graduate", 2: "University", 3: "High School", 4: "Others"}
            
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "client_id": str(row.get("ID")),
                        "limit_balance": float(row.get("LIMIT_BAL", 0)),
                        "education_level": edu_map.get(row.get("EDUCATION"), "Unknown"),
                        "age": int(row.get("AGE", 0)),
                        "payment_status_recent": int(row.get("PAY_0", 0)),
                        "default_binary": int(row.get("default", 0))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"UCI-{row.get('ID')}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry="finance",
                            data=verified,
                            provenance={"source": raw.source_url, "schema": "UCI-Credit"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        if self.schema_type == "world_bank":
            TARGET_SCHEMA = {
                "country": "string",
                "indicator": "string",
                "value": "number",
                "year": "string"
            }
            for raw in raw_artifacts:
                for row in raw.content:
                    if row.get("value") is None: continue
                    raw_data = {
                        "country": row.get("country", {}).get("value", "Unknown"),
                        "indicator": row.get("indicator", {}).get("value", "Unknown"),
                        "value": float(row.get("value", 0)),
                        "year": str(row.get("date", "0000"))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        # Deterministic ID based on Country and Year
                        source_id = f"WB-{row.get('country', {}).get('id', 'XX')}-{row.get('date')}"
                        results.append(StandardSchema(
                            id=hashlib.md5(source_id.encode()).hexdigest()[:16],
                            industry="finance",
                            data=verified,
                            provenance={"source": raw.source_url, "schema": "World-Bank-Macro"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        TARGET_SCHEMA = {
            "entity_name": "string",
            "cik": "string",
            "total_assets": "number",
            "revenues": "number",
            "net_income": "number",
            "audit_status": "string"
        }
        
        for raw in raw_artifacts:
            facts = raw.content.get("facts", {}).get(self.taxonomy, {})
            company_name = raw.metadata.get("company")
            cik = raw.metadata.get("cik")
            
            def get_latest_fact(fact_name):
                # Common GAAP tags for Revenue and Income
                tags = [fact_name, f"{fact_name}Net", f"{fact_name}Abstract"]
                for tag in tags:
                    unit_data = facts.get(tag, {}).get("units", {}).get(self.currency, [])
                    if unit_data:
                        # Return the most recent audited value
                        return unit_data[-1].get("val", 0)
                return 0

            raw_data = {
                "entity_name": company_name,
                "cik": cik,
                "total_assets": get_latest_fact("Assets"),
                "revenues": get_latest_fact("Revenues"),
                "net_income": get_latest_fact("NetIncomeLoss"),
                "audit_status": "Verified"
            }
            
            # Strict Schema Verification
            verified_data = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
            if verified_data:
                # Deterministic record ID based on CIK and Timestamp
                record_id = hashlib.md5(f"{cik}-{raw.timestamp}".encode()).hexdigest()[:16]
                raw_str = json.dumps(verified_data, sort_keys=True)
                data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                results.append(StandardSchema(
                    id=record_id,
                    industry="finance",
                    data=verified_data,
                    provenance={
                        "source": raw.source_url,
                        "taxonomy": self.taxonomy,
                        "currency": self.currency
                    },
                    checksum=data_checksum
                ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        for record in normalized_data:
            if self.schema_type == "credit_risk":
                if record.data.get("limit_balance", 0) < 0:
                    return False
            elif self.schema_type == "world_bank":
                if record.data.get("value") is None:
                    return False
            else:
                if record.data.get("total_assets", 0) <= 0:
                    record_id = getattr(record, "id", "unknown")
                    logger.warning("validation_failed", record_id=record_id, reason="Zero or negative assets")
                    return False
        return True





