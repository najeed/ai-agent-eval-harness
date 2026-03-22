import logging
from typing import Dict, Any
from dataproc_engine.core.base_provider import BaseProvider
from dataproc_engine.core.config import ConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dataproc-Engine")

class DatasetEngine:
    """
    Orchestrator for the dataproc ETL process.
    """
    def __init__(self):
        self.providers: Dict[str, BaseProvider] = {}

    def register_provider(self, industry: str, provider: BaseProvider):
        """
        Register a provider for a specific industry.
        """
        self.providers[industry] = provider
        logger.info(f"Registered provider for industry: {industry}")

    async def run_industry_pipeline(self, industry: str):
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
        transformed_data = provider.transform(raw_artifacts)
        logger.info(f"[{industry}] Transformed {len(transformed_data)} records.")

        # 3. Validation
        logger.info(f"[{industry}] Validating data integrity...")
        is_valid = provider.validate(transformed_data)
        
        if not is_valid:
            logger.error(f"[{industry}] Data validation failed!")
            return None

        logger.info(f"[{industry}] Validation successful.")
        return transformed_data
