import aiohttp
import asyncio
import hashlib
import json
import datetime
import os
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
        self.finance_mode = config.get("finance_mode", "sec_edgar")

    async def extract(self) -> List[RawArtifact]:
        """
        Unified extraction logic for World Bank, UCI Credit, and SEC XBRL.
        """
        if self.finance_mode == "worldbank":
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
                            content=content,
                            metadata={"indicator": indicator, "country": country},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
                except Exception as e:
                    logger.error("wb_extraction_failed", indicator=indicator, error=str(e))
                
                if self.allow_simulation:
                    logger.warning("wb_api_failure_using_sim")
                    simulated_wb = [
                        {"page": 1},
                        [
                            {"country": {"value": "United States", "id": "US"}, "indicator": {"value": "GDP"}, "value": 23315081000000, "date": "2021"},
                            {"country": {"value": "China", "id": "CN"}, "indicator": {"value": "GDP"}, "value": 17734062000000, "date": "2021"}
                        ]
                    ]
                    return [self.create_simulated_artifact(
                        id=f"WB-{indicator}",
                        content=simulated_wb,
                        source_url=url,
                        metadata={"indicator": indicator}
                    )]
                return []

        if self.finance_mode == "credit_risk":
            url = "https://archive.ics.uci.edu/ml/machine-learning-databases/00350/default%20of%20credit%20card%20clients.xls"
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
                    {"ID": 1, "LIMIT_BAL": 20000, "SEX": 2, "EDUCATION": 2, "MARRIAGE": 1, "AGE": 24, "PAY_0": 2, "BILL_AMT1": 3913, "PAY_AMT1": 0, "default.payment.next.month": 1},
                    {"ID": 2, "LIMIT_BAL": 120000, "SEX": 2, "EDUCATION": 2, "MARRIAGE": 2, "AGE": 26, "PAY_0": -1, "BILL_AMT1": 2682, "PAY_AMT1": 0, "default.payment.next.month": 1}
                ]
                return [self.create_simulated_artifact(
                    id="UCI-CREDIT",
                    content=simulated_data,
                    source_url=url,
                    metadata={"dataset": "UCI Default Credits"}
                )]
            return []

        if self.finance_mode == "sec_edgar":
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
                        if content:
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
                
                if not artifacts and self.allow_simulation:
                    logger.warning("sec_api_failure_using_sim")
                    for cik in target_ciks:
                        sim_content = {
                            "entityName": f"SIM Company {cik}",
                            "facts": {self.taxonomy: {"Revenues": {"units": {self.currency: [{"val": 100, "fy": 2023, "fp": "FY"}]}}}}
                        }
                        artifacts.append(self.create_simulated_artifact(
                            id=f"SEC-{cik}-FACTS",
                            content=sim_content,
                            source_url="https://sim-sec.example.org/",
                            metadata={"company": f"SIM Company {cik}", "cik": cik}
                        ))
            return artifacts
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        is_strict = self.llm_manager.strategy not in ["heuristic", "mock"]
        
        # Define schemas based on gold standard data sources
        SCHEMAS = {
            "sec_edgar": {
                "entity_name": "string", "cik": "string", "total_assets": "number",
                "revenues": "number", "net_income": "number", "audit_status": "string"
            },
            "worldbank": {
                "country": "string", "indicator": "string", "value": "number", "year": "integer"
            },
            "credit_risk": {
                "account_id": "string", "limit_balance": "number", "education": "integer",
                "age": "integer", "default_payment": "integer"
            }
        }
        
        target_schema = SCHEMAS.get(self.finance_mode, SCHEMAS["sec_edgar"])
        
        for raw in raw_artifacts:
            # 1. World Bank (Two-Tier List Awareness)
            if self.finance_mode == "worldbank":
                # World Bank returns [ {paging}, [data_list] ]
                data_list = raw.content[1] if isinstance(raw.content, list) and len(raw.content) > 1 else raw.content
                if not isinstance(data_list, list): data_list = [raw.content]
                
                for row in data_list:
                    if not isinstance(row, dict): continue
                    raw_data = {
                        "country": row.get("country", {}).get("value", "Unknown"),
                        "indicator": row.get("indicator", {}).get("value", "GDP"),
                        "value": float(row.get("value") or 0),
                        "year": int(row.get("date", 0))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, target_schema, strict=is_strict)
                    if verified:
                        source_id = f"WB-{row.get('country', {}).get('id', 'XX')}-{row.get('date')}"
                        results.append(StandardSchema(
                            id=hashlib.md5(source_id.encode()).hexdigest()[:16],
                            industry="finance", data=verified,
                            provenance={"source": raw.source_url, "schema": "World-Bank-Macro"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
                continue

            # 2. UCI Credit Risk
            if self.finance_mode == "credit_risk":
                # Supported keys: LIMIT_BAL, AGE, ID, EDUCATION, default.payment.next.month
                for row in raw.content:
                    raw_data = {
                        "account_id": str(row.get("ID", "0")),
                        "limit_balance": float(row.get("LIMIT_BAL", 0)),
                        "education": int(row.get("EDUCATION", 0)),
                        "age": int(row.get("AGE", 0)),
                        "default_payment": int(row.get("default.payment.next.month", 0))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, target_schema, strict=is_strict)
                    if verified:
                        results.append(StandardSchema(
                            id=hashlib.md5(str(raw_data["account_id"]).encode()).hexdigest()[:16],
                            industry="finance", data=verified,
                            provenance={"source": raw.source_url, "schema": "UCI-Credit-Risk"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
                continue

            # 3. SEC XBRL (Standard Mode)
            facts = raw.content.get("facts", {}).get(self.taxonomy, {})
            company_name = raw.metadata.get("company")
            cik = raw.metadata.get("cik")
            
            def get_latest_fact(fact_name):
                tags = [fact_name, f"{fact_name}Net", f"{fact_name}Abstract"]
                for tag in tags:
                    actual_tag = next((k for k in facts.keys() if k.lower() == tag.lower()), tag)
                    unit_data = facts.get(actual_tag, {}).get("units", {}).get(self.currency, [])
                    if unit_data: return unit_data[-1].get("val", 0)
                return 0

            raw_data = {
                "entity_name": company_name, "cik": cik,
                "total_assets": float(get_latest_fact("Assets")),
                "revenues": float(get_latest_fact("Revenues")),
                "net_income": float(get_latest_fact("NetIncomeLoss")),
                "audit_status": "Audited"
            }
            verified = self.llm_manager._verify_schema(raw_data, target_schema, strict=is_strict)
            if verified:
                record_id = hashlib.md5(f"{cik}-{raw.timestamp}".encode()).hexdigest()[:16]
                results.append(StandardSchema(
                    id=record_id, industry="finance", data=verified,
                    provenance={"source": raw.source_url, "taxonomy": self.taxonomy, "currency": self.currency},
                    checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        """
        Industry-specific semantic validation rules.
        """
        for record in normalized_data:
            if self.finance_mode == "credit_risk":
                if record.data.get("limit_balance", 0) < 0: return False
            elif self.finance_mode == "worldbank":
                if record.data.get("value") is None: return False
            elif self.finance_mode == "sec_edgar":
                # Default SEC validation: Assets should be positive
                if record.data.get("total_assets", 0) <= 0:
                    return False
        return True

