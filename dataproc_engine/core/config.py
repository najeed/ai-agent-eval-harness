import os
import logging
from typing import Dict, Any

logger = logging.getLogger("dataproc-Config")

class ConfigLoader:
    """
    Utility for loading configuration and secrets from environment variables.
    """
    @staticmethod
    def load_secrets(industry: str) -> Dict[str, Any]:
        """
        Loads secrets for a specific industry based on standard environment variables.
        """
        secrets = {}
        if industry == "finance":
            secrets["sec_user_agent"] = os.environ.get("SEC_USER_AGENT")
            secrets["fred_api_key"] = os.environ.get("FRED_API_KEY")
            
            # Warn if secrets are missing but don't fail here (let provider validate)
            if not secrets["sec_user_agent"]:
                logger.warning("SEC_USER_AGENT not found in environment variables.")
            if not secrets["fred_api_key"]:
                logger.warning("FRED_API_KEY not found in environment variables.")
                
        return secrets

    @staticmethod
    def get_config(overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Returns the final merged configuration.
        """
        base_config = {
            "rate_limit": float(os.environ.get("DATAPROC_RATE_LIMIT", 1.0)),
            "limit": int(os.environ.get("DATAPROC_LIMIT", 10))
        }
        if overrides:
            base_config.update(overrides)
        return base_config
