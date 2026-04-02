import logging
from typing import Dict, Any, List, Optional
from dataproc_engine.core.base_provider import BaseProvider, StandardSchema
from dataproc_engine.core.config import ConfigLoader
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.logger import StructuredLogger
from dataproc_engine.core.utils import discovery
import dataproc_engine.providers as providers

logger = StructuredLogger("DatasetEngine")

class DatasetEngine:
    """
    Orchestrator for the dataproc ETL process.
    """
    def __init__(self, config: Dict[str, Any] = None, llm_manager: Optional[LLMManager] = None):
        self.config = config or {}
        self.llm_manager = llm_manager or LLMManager(self.config)
        self.synthesis_engine = ParitySynthesizer()
        self.providers = {}

    def register_provider(self, industry: str, provider: BaseProvider):
        """
        Register a provider for a specific industry.
        """
        self.providers[industry] = provider
        logger.info(f"Registered provider for industry: {industry}")

    def get_provider(self, industry: str, config: Dict[str, Any]) -> BaseProvider:
        """
        Factory method to return a provider instance by industry name.
        Uses dynamic discovery to resolve providers from the providers/ package.
        """
        config["industry"] = industry
        
        if industry in self.providers:
            return self.providers[industry]

        # Dynamic discovery (AES v1.2 Universal Extensibility)
        provider_classes = discovery.discover_classes_in_package(providers, BaseProvider, instantiate=False)
        
        # Mapping variations
        industry_map = {
            "edtech": "education",
            "unstructured": "unstructured_provider",
            "demographics": "demographics",
            "labor": "labor",
            "environment": "environment",
            "housing": "housing",
            "media_and_entertainment": "media_and_entertainment",
            "decision_support": "decision_support"
        }
        lookup_key = industry_map.get(industry, industry)
        
        provider_cls = provider_classes.get(lookup_key)
        
        # Fallback: check for _provider suffix
        if not provider_cls and not lookup_key.endswith("_provider"):
            provider_cls = provider_classes.get(f"{lookup_key}_provider")
        
        if provider_cls:
            return provider_cls(config, llm_manager=self.llm_manager)
            
        raise ValueError(f"Unknown industry: {industry} (No provider discovered in providers/ package after scan of 20+ modules)")

    async def run_industry_pipeline(self, industry: str, target_dir: Optional[str] = None):
        """
        Execute the full ETL pipeline for a given industry.
        """
        if industry not in self.providers:
            raise ValueError(f"No provider registered for industry: {industry}")

        provider = self.providers[industry]

        # Inject secrets into the provider config
        secrets = ConfigLoader.load_secrets(industry)
        provider.config.update(secrets)
        
        logger.info(f"Starting pipeline for {industry}...")
        
        # 1. Extraction
        logger.info(f"[{industry}] Extracting raw artifacts...")
        raw_artifacts = await provider.extract()
        logger.info(f"[{industry}] Extracted {len(raw_artifacts)} artifacts.")

        # 2. Transformation
        logger.info(f"[{industry}] Transforming data...")
        transformed_data = await provider.transform(raw_artifacts)
        logger.info(f"[{industry}] Transformed {len(transformed_data)} records.")

        # 3. Validation
        logger.info(f"[{industry}] Validating data integrity...")
        is_valid = provider.validate(transformed_data)
        
        if not is_valid:
            logger.error(f"[{industry}] Data validation failed!")
            return None

        logger.info(f"[{industry}] Validation successful.")
        
        # 4. Correlation (Inter-industry signals)
        datasets = {industry: transformed_data}
        correlated_datasets = DataCorrelator.correlate(datasets, target_dir=target_dir)
        return correlated_datasets[industry]


