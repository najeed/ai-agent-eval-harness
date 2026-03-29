import json
import os
import random
import aiohttp
from typing import Dict, Any, List, Optional
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("LLMManager")

class LLMManager:
    """
    Manages multi-provider LLM extraction with tiered fallback.
    Tiers: Cloud (Gemini/OpenAI) -> Ollama (Text-only) -> Heuristics (Structured text only)
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.strategy = config.get("llm_strategy", "auto")
        self.preferred_provider = config.get("llm_provider", "gemini")
        self.preferred_model = config.get("model")
        self.estimated_cost_cents = 0.0
        
        # 2026 Tier 1 Economic Mapping (Cents per 1k tokens)
        self.pricing = {
            "gemini-1.5-pro": {"in": 0.35, "out": 1.05},
            "gemini-1.5-flash": {"in": 0.0075, "out": 0.03},
            "gpt-4o": {"in": 0.50, "out": 1.50},
            "gpt-4o-mini": {"in": 0.015, "out": 0.06},
            "claude-3-5-sonnet": {"in": 0.30, "out": 1.50},
        }

    async def extract_structured_data(self, content: str, target_schema: Dict[str, Any], source_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Extract data with V2.0 TokenGuard (Check-API-First).
        """
        effective_strategy = self.strategy
        
        # 0. V2: TokenGuard (Economic Interception)
        if source_hint and self.strategy != "mock":
             interception = self._token_guard_intercept(content, source_hint)
             if interception:
                 logger.info(f"V2: TokenGuard intercepted request for {source_hint}. Routing current call to Tier 3 (Heuristic).")
                 effective_strategy = "heuristic" # Bypass for this call only
        
        # 0.5 Tier 0: Mock
        if effective_strategy == "mock":
            import random
            mock_data = {}
            for key, expected_type in target_schema.items():
                if expected_type == "number":
                    mock_data[key] = round(random.uniform(1000.0, 1000000.0), 2)
                elif expected_type == "string":
                    mock_data[key] = f"Mocked-{key}-{random.randint(100, 999)}"
                else:
                    mock_data[key] = None
            return self._verify_schema(mock_data, target_schema)

        # 1. Tier 1: Cloud Providers (Preferred)
        if effective_strategy in ["auto", "cloud"]:
            result = await self._try_cloud_providers(content, target_schema)
            if result:
                return self._verify_schema(result, target_schema)
        
        # 2. Tier 2: Local Ollama (Fallback for text-only)
        if effective_strategy in ["auto", "ollama"] and len(content) < 50000:
             result = await self._try_ollama(content, target_schema)
             if result:
                 return self._verify_schema(result, target_schema)
                
        # 3. Tier 3: Heuristics (Final fallback for structured patterns)
        if effective_strategy in ["auto", "heuristic"]:
            result = self._try_heuristics(content, target_schema)
            if result:
                return self._verify_schema(result, target_schema)
                
        logger.error("All extraction tiers failed or could not process the data.")
        return None

    async def analyze_sentiment(self, content: str) -> float:
        """
        Analyze sentiment score (0.0 - 1.0) with fallback to heuristics.
        """
        if self.strategy in ["auto", "cloud"]:
            result = await self._call_sentiment_llm(content)
            if result is not None:
                return result
        
        return self._heuristic_sentiment(content)

    async def _call_sentiment_llm(self, content: str) -> Optional[float]:
        """
        Universal multi-provider sentiment extraction.
        """
        schema = {"sentiment_score": "number"}
        prompt = f"Analyze the sentiment of this text. Return ONLY JSON with a score 0.0 (very negative) to 1.0 (very positive): {content[:3000]}"
        
        # 1. Try Cloud Providers (Harden: Universal Support)
        result = await self._try_cloud_providers(content[:3000], schema)
        if result and "sentiment_score" in result:
            return float(result["sentiment_score"])
            
        # 2. Try Ollama (Harden: Local Fallback)
        if self.strategy in ["auto", "ollama"]:
            result = await self._try_ollama(content[:3000], schema)
            if result and "sentiment_score" in result:
                return float(result["sentiment_score"])
                
        return None

    def _heuristic_sentiment(self, content: str) -> float:
        """
        Expanded Keyword-based sentiment fallback.
        Supports intensifiers and industry-specific sentiment signals.
        """
        pos = {
            "growth", "profit", "bullish", "strong", "exceeded", "surplus", "advantage", "gain", 
            "rise", "positive", "beat", "robust", "resilient", "outperform", "efficient", 
            "stability", "climb", "dividend", "acquisition", "innovation", "leadership"
        }
        neg = {
            "decline", "loss", "bearish", "weak", "missed", "deficit", "risk", "fall", 
            "negative", "drop", "lower", "volatile", "contraction", "headwinds", "stagnation", 
            "debt", "downgrade", "obsolescence", "insolvency", "underperform"
        }
        intensifiers = {"extremely": 1.5, "very": 1.3, "slightly": 0.7, "highly": 1.4}
        
        text = content.lower()
        words = text.split()
        
        pos_score = 0
        neg_score = 0
        
        for i, word in enumerate(words):
            multiplier = 1.0
            clean_word = word.strip(".,!?;:\"'()")
            if i > 0 and words[i-1].strip(".,!?;:\"'()") in intensifiers:
                multiplier = intensifiers[words[i-1].strip(".,!?;:\"'()")]
            
            if clean_word in pos:
                pos_score += 1 * multiplier
            elif clean_word in neg:
                neg_score += 1 * multiplier
        
        total = pos_score + neg_score
        if total == 0:
            return 0.5 # Neutral
            
        return round(pos_score / total, 2)

    async def _try_cloud_providers(self, content: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        provider = self.preferred_provider
        api_key = os.getenv(f"{provider.upper()}_API_KEY")
        
        if not api_key:
            logger.info(f"Cloud provider {provider} skipped (no API key).")
            return None
            
        logger.info(f"Attempting cloud extraction with {provider}...")
        
        if provider == "openai":
            return await self._call_openai(content, schema, api_key)
        elif provider == "gemini":
            return await self._call_gemini(content, schema, api_key)
        elif provider == "claude":
            return await self._call_claude(content, schema, api_key)
        elif provider == "grok":
            return await self._call_grok(content, schema, api_key)
        
        return None

    async def _call_openai(self, content: str, schema: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
        url = "https://api.openai.com/v1/chat/completions"
        model = self.preferred_model or "gpt-4o"
        prompt = self._build_prompt(content, schema)
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._record_usage(data.get("usage", {}), model)
                        return json.loads(data["choices"][0]["message"]["content"])
            except Exception as e:
                logger.error(f"OpenAI call failed: {e}")
        return None

    async def _call_gemini(self, content: str, schema: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
        model = self.preferred_model or "gemini-1.5-pro"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        prompt = self._build_prompt(content, schema)
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"}
            }
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        return json.loads(text)
            except Exception as e:
                logger.error(f"Gemini call failed: {e}")
        return None

    async def _call_claude(self, content: str, schema: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
        url = "https://api.anthropic.com/v1/messages"
        model = self.preferred_model or "claude-3-5-sonnet-20240620"
        prompt = self._build_prompt(content, schema)
        
        async with aiohttp.ClientSession() as session:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": f"Return ONLY JSON: {prompt}"}]
            }
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["content"][0]["text"]
                        return json.loads(text)
            except Exception as e:
                logger.error(f"Claude call failed: {e}")
        return None

    async def _call_grok(self, content: str, schema: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
        url = "https://api.x.ai/v1/chat/completions"
        model = self.preferred_model or "grok-1"
        prompt = self._build_prompt(content, schema)
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return json.loads(data["choices"][0]["message"]["content"])
            except Exception as e:
                logger.error(f"Grok call failed: {e}")
        return None

    async def _try_ollama(self, content: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = "http://localhost:11434/api/generate"
        # 2026 SOTA Priority: Kimi K2.5, Llama 3.1/4, Qwen 2.5, DeepSeek V3
        env_model = os.getenv("OLLAMA_MODEL")
        model = self.preferred_model or env_model or "kimi-k2.5"
        
        prompt = self._build_prompt(content, schema)
        
        logger.info(f"Attempting local extraction with Ollama ({model})...")
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                async with session.post(url, json=payload, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        return json.loads(data.get("response", "{}"))
        except Exception as e:
            logger.warning(f"Ollama extraction failed: {str(e)}")
            
        return None

    def _try_heuristics(self, content: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Hardened Tier 3 Heuristic extraction (Regex-based).
        """
        import re
        extracted = {}
        
        # 1. Standard Key-Value Patterns
        for key, expected_type in schema.items():
            clean_key = key.replace('_', ' ')
            patterns = [
                rf"{key}\s*[:=]\s*([^;\n\r\|]+)",               # Allow commas as they might be thousands separators
                rf"{clean_key}\s*[:=]\s*([^;\n\r\|]+)",         # Stop at semicolon or newline instead
                rf'"{key}"\s*:\s*"([^"]+)"',
                rf'"{key}"\s*:\s*([\d\.,]+)',                    # Allow dots and commas
                rf"<{key}>(.*?)</{key}>",
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if match:
                    val = match.group(1).strip().strip('"').strip("'")
                    extracted[key] = val
                    break
        
        # 2. Schema-Specific Inference (e.g., matching floating point numbers for revenue)
        if len(extracted) < len(schema):
            for key, expected_type in schema.items():
                if key not in extracted and expected_type == "number":
                    num_match = re.search(rf"{key}.*?(\d[\d\.,]*)", content, re.IGNORECASE)
                    if num_match:
                        extracted[key] = num_match.group(1).replace(",", "")

        # 3. Decision Logic: High-signal discovery
        found_keys = set(extracted.keys())
        signal_ratio = len(found_keys) / len(schema)
        
        if signal_ratio >= 0.5:
            logger.info(f"Heuristic extraction succeeded with {int(signal_ratio*100)}% coverage.")
            return extracted
            
        return None

    def _build_prompt(self, content: str, schema: Dict[str, Any]) -> str:
        return f"""
        Extract the following information from the provided text and return ONLY a JSON object matching this schema:
        {json.dumps(schema, indent=2)}
        
        Text to extract from:
        ---
        {content}
        ---
        """

    def _verify_schema(self, data: Dict[str, Any], schema: Dict[str, Any], strict: bool = False) -> Optional[Dict[str, Any]]:
        """
        Post-extraction verification with optional strict enforcement.
        """
        logger.info(f"Verifying output against schema (strict={strict})...")
        corrected_data = data.copy()
        
        for key, expected_type in schema.items():
            if key not in corrected_data:
                if strict:
                    logger.error(f"STRICT FAILURE: Required key '{key}' missing.")
                    return None
                    
                logger.warning(f"Missing key '{key}'. Attempting inference...")
                # Basic inference: if 'revenue' is missing but 'total_revenue' exists
                for alt_key in [f"total_{key}", f"{key}_amount", key.replace("_", "")]:
                    if alt_key in corrected_data:
                        corrected_data[key] = corrected_data[alt_key]
                        break
                
                if key not in corrected_data:
                    logger.error(f"Inference failed for required key '{key}'.")
                    return None
            
            # Type Enforcement
            val = corrected_data[key]
            if expected_type == "number":
                try:
                    if isinstance(val, str):
                        # Handle "$1,234.56" -> 1234.56
                        clean_val = val.replace("$", "").replace(",", "").strip()
                        corrected_data[key] = float(clean_val)
                    elif not isinstance(val, (int, float)):
                        raise ValueError("Not a number")
                except ValueError:
                    logger.error(f"Type failure for '{key}': {val} is not a valid number.")
                    return None
            elif expected_type == "string":
                if not isinstance(val, str):
                    corrected_data[key] = str(val)
            elif expected_type == "integer":
                try:
                    corrected_data[key] = int(float(str(val)))
                except (ValueError, TypeError):
                    logger.error(f"Type failure for '{key}': {val} is not a valid integer.")
                    return None


    def _token_guard_intercept(self, content: str, source_hint: str) -> bool:
        """
        V2: Check if source is a known public entity that should bypass Tier 1.
        """
        public_domains = ["sec.gov", "census.gov", "worldbank.org", "who.int", "fcc.gov", "noaa.gov"]
        for domain in public_domains:
            if domain in source_hint.lower() or domain in content[:500].lower():
                return True
        return False

    def _record_usage(self, usage: Dict[str, Any], model: str):
        """
        V2: Tracks estimated spend in cents based on 2026 pricing.
        """
        if not usage or model not in self.pricing:
            return
            
        prices = self.pricing[model]
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        cost = (prompt_tokens / 1000 * prices["in"]) + (completion_tokens / 1000 * prices["out"])
        self.estimated_cost_cents += cost
        logger.info(f"V2: Extraction cost: {cost:.4f} cents. Total session: {self.estimated_cost_cents:.2f} cents.")

    def get_session_economics(self) -> Dict[str, Any]:
        return {
            "total_cost_cents": round(self.estimated_cost_cents, 4),
            "roi_status": "positive" if self.estimated_cost_cents < 5.0 else "divergent"
        }


