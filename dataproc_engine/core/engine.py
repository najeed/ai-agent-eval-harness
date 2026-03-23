import logging
from typing import Dict, Any, List, Optional
from dataproc_engine.core.base_provider import BaseProvider, StandardSchema
from dataproc_engine.core.config import ConfigLoader
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("DatasetEngine")

class DatasetEngine:
    """
    Orchestrator for the dataproc ETL process.
    """
    def __init__(self, config: Optional[Dict[str, Any]] = None, llm_manager: Optional[Any] = None):
        self.providers: Dict[str, BaseProvider] = {}
        self.config = config or {}
        self.llm_manager = llm_manager or LLMManager(self.config)
        self.synthesis_engine = ParitySynthesizer()

    def register_provider(self, industry: str, provider: BaseProvider):
        """
        Register a provider for a specific industry.
        """
        self.providers[industry] = provider
        logger.info(f"Registered provider for industry: {industry}")

    def get_provider(self, industry: str, config: Dict[str, Any]) -> BaseProvider:
        """
        Factory method to return a provider instance by industry name.
        """
        # Ensure the industry name is always in the config for metadata propagation
        config["industry"] = industry
        
        if industry in self.providers:
            return self.providers[industry]

        # Dynamic imports for all industrial providers
        if industry == "finance":
            from dataproc_engine.providers.finance import FinanceProvider
            return FinanceProvider(config, llm_manager=self.llm_manager)
        elif industry == "energy":
            from dataproc_engine.providers.energy import EnergyProvider
            return EnergyProvider(config, llm_manager=self.llm_manager)
        elif industry == "healthcare":
            from dataproc_engine.providers.healthcare import HealthcareProvider
            return HealthcareProvider(config, llm_manager=self.llm_manager)
        elif industry == "telecom":
            from dataproc_engine.providers.telecom import TelecomProvider
            return TelecomProvider(config, llm_manager=self.llm_manager)
        elif industry == "ecommerce":
            from dataproc_engine.providers.ecommerce import EcommerceProvider
            return EcommerceProvider(config, llm_manager=self.llm_manager)
        elif industry == "unstructured":
            from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
            return UnstructuredProvider(config, llm_manager=self.llm_manager)
        elif industry == "agriculture":
            from dataproc_engine.providers.agriculture import AgricultureProvider
            return AgricultureProvider(config, llm_manager=self.llm_manager)
        elif industry == "transportation":
            from dataproc_engine.providers.transportation import TransportationProvider
            return TransportationProvider(config, llm_manager=self.llm_manager)
        elif industry == "demographics":
            from dataproc_engine.providers.public_sector.demographics import DemographicsProvider
            return DemographicsProvider(config, llm_manager=self.llm_manager)
        elif industry == "labor":
            from dataproc_engine.providers.public_sector.labor import LaborProvider
            return LaborProvider(config, llm_manager=self.llm_manager)
        elif industry == "environment":
            from dataproc_engine.providers.public_sector.environment import EnvironmentProvider
            return EnvironmentProvider(config, llm_manager=self.llm_manager)
        elif industry == "education":
            from dataproc_engine.providers.education import EducationProvider
            return EducationProvider(config, llm_manager=self.llm_manager)
        elif industry == "edtech":
            # Clubbed with education
            from dataproc_engine.providers.education import EducationProvider
            return EducationProvider(config, llm_manager=self.llm_manager)
        elif industry == "housing":
            from dataproc_engine.providers.public_sector.housing import HousingProvider
            return HousingProvider(config, llm_manager=self.llm_manager)
        elif industry == "manufacturing":
            from dataproc_engine.providers.manufacturing import ManufacturingProvider
            return ManufacturingProvider(config, llm_manager=self.llm_manager)
        elif industry == "media_entertainment":
            from dataproc_engine.providers.media_entertainment import MediaProvider
            return MediaProvider(config, llm_manager=self.llm_manager)
        elif industry == "decision_support":
            from dataproc_engine.providers.decision_support import DecisionSupportProvider
            return DecisionSupportProvider(config, llm_manager=self.llm_manager)
        else:
            raise ValueError(f"Unknown industry: {industry}")

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


