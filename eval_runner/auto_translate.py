"""
auto_translate.py

Utility for auto-translating raw unstructured text documents (TXT, MD, PDF, DOCX)
into structured JSON scenarios using a local LLM via Ollama.

NOTE: This feature requires a local LLM running via Ollama to function.
"""

import json
import uuid
import re
from pathlib import Path
from typing import Dict, Any, Optional

import aiohttp


def extract_text(file_path: Path) -> str:
    """Extracts raw text from a variety of document formats."""
    ext = file_path.suffix.lower()

    if ext in [".txt", ".md", ".csv", ".json"]:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    elif ext == ".pdf":
        try:
            import PyPDF2

            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = []
                for page in reader.pages:
                    text.append(page.extract_text() or "")
                return "\n".join(text)
        except ImportError:
            raise ImportError(
                "PyPDF2 is required to parse PDF files. Run: pip install PyPDF2"
            )

    elif ext == ".docx":
        try:
            import docx

            doc = docx.Document(file_path)
            return "\n".join([paragraph.text for paragraph in doc.paragraphs])
        except ImportError:
            raise ImportError(
                "python-docx is required to parse DOCX files. Run: pip install python-docx"
            )

    else:
        raise ValueError(
            f"Unsupported file extension: {ext}. Supported: txt, md, pdf, docx."
        )


async def translate_to_scenario(
    text: str,
    model: str = "llama3",
    api_url: str = "http://localhost:11434/api/generate",
) -> Dict[str, Any]:
    """Uses a local Ollama LLM to synthesize a scenario JSON from raw text."""

    prompt = f"""
You are an expert evaluator converting raw unstructured requirement documents into structured JSON scenarios for the AI Agent Evaluation Harness.

Your task is to analyze the following document and synthesize a valid JSON scenario that meets the official AES (Agent Eval Specification) schema. 

The schema requires:
- `scenario_id`: A unique string identifier.
- `title`: A short string title.
- `industry`: The industry category (e.g., telecom, healthcare, ecommerce).
- `description`: A thorough description of the scenario.
- `tasks`: A list of objects, each containing:
  - `task_id`: String identifier (e.g., "t1")
  - `description`: Instructions for the task
  - `expected_outcome`: What should happen
  - `success_criteria`: A list of objects with "metric" and "threshold" keys (e.g., {{"metric": "tool_correctness", "threshold": 1.0}})

Output ONLY valid JSON. Do not include markdown formatting or explanations. The response should start with {{ and end with }}.

--- BEGIN DOCUMENT ---
{text}
--- END DOCUMENT ---

JSON Output:
"""

    payload = {"model": model, "prompt": prompt, "format": "json", "stream": False}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    text_resp = await resp.text()
                    raise RuntimeError(f"Ollama API error ({resp.status}): {text_resp}")

                result = await resp.json()
                response_text = result.get("response", "")

                # Try parsing the immediate response, checking for markdown blocks just in case
                json_match = re.search(
                    r"```json\s*(.*?)\s*```", response_text, re.DOTALL
                )
                if json_match:
                    response_text = json_match.group(1)

                parsed_json = json.loads(response_text)

                # Basic validation/repair
                if "scenario_id" not in parsed_json:
                    parsed_json["scenario_id"] = f"auto-{uuid.uuid4().hex[:8]}"
                if "version" not in parsed_json:
                    parsed_json["version"] = "2.0.0"
                if "tasks" not in parsed_json:
                    parsed_json["tasks"] = []

                return parsed_json

    except aiohttp.ClientConnectorError:
        raise ConnectionError(
            f"Could not connect to Ollama at {api_url}. Is Ollama running?"
        )
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Ollama returned invalid JSON: {e}\nRaw Response: {response_text[:200]}..."
        )


def save_scenario(scenario: Dict[str, Any], output_path: Path):
    """Saves the translated JSON scenario to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=2)
    print(f"[OK] Generated Scenario saved to: {output_path}")
