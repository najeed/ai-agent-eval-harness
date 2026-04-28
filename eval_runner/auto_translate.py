"""
auto_translate.py

Utility for auto-translating raw unstructured text documents (TXT, MD, PDF, DOCX)
into structured JSON scenarios using a local LLM via Ollama.

NOTE: This feature requires a local LLM running via Ollama to function.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from . import config


def extract_text(file_path: Path) -> str:
    """Extracts raw text from a variety of document formats."""
    ext = file_path.suffix.lower()

    if ext in [".txt", ".md", ".csv", ".json"]:
        with open(file_path, encoding="utf-8") as f:
            return f.read()

    elif ext == ".pdf":
        try:
            import pypdf

            with open(file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                text = []
                for page in reader.pages:
                    text.append(page.extract_text() or "")
                return "\n".join(text)
        except ImportError:
            raise ImportError("pypdf is required to parse PDF files. Run: pip install pypdf")  # noqa: B904

    elif ext == ".docx":
        try:
            import docx

            doc = docx.Document(file_path)
            return "\n".join([paragraph.text for paragraph in doc.paragraphs])
        except ImportError:
            raise ImportError(  # noqa: B904
                "python-docx is required to parse DOCX files. Run: pip install python-docx"
            )

    else:
        raise ValueError(f"Unsupported file extension: {ext}. Supported: txt, md, pdf, docx.")


async def translate_to_scenario(
    text: str,
    model: str = "llama4",
    api_url: str = "http://localhost:11434/api/generate",
) -> dict[str, Any]:
    """Uses a local Ollama LLM to synthesize a scenario JSON from raw text."""

    prompt = f"""
You are an expert evaluator converting raw unstructured requirement documents into structured 
JSON scenarios for the AgentV.

Your task is to analyze the following document and synthesize a valid JSON scenario that meets 
the official AES (Agent Eval Specification) schema.

The schema requires:
- `id`: A unique string identifier.
- `metadata`: A block containing:
  - `id`: Should match top-level `id`.
  - `name`: Human readable name.
- `title`: A short string title.
- `industry`: The industry category (e.g., telecom, healthcare, ecommerce).
- `description`: A thorough description of the scenario.
- `workflow`: A block containing the task graph (AES v1.4.0 standard).

Output ONLY valid JSON. Do not include markdown formatting or explanations. 
The response should start with {{ and end with }}.

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
                json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)

                parsed_json = json.loads(response_text)

                # Basic validation/repair (AES v1.4.0 Alignment)
                if "id" not in parsed_json:
                    parsed_json["id"] = f"auto-{uuid.uuid4().hex[:8]}"

                if "metadata" not in parsed_json:
                    parsed_json["metadata"] = {
                        "id": parsed_json["id"],
                        "name": parsed_json.get("title")
                        or parsed_json.get("name")
                        or "Auto Scenario",
                        "compliance_level": "Standard",
                    }
                else:
                    parsed_json["metadata"].setdefault("id", parsed_json["id"])
                    parsed_json["metadata"].setdefault(
                        "name", parsed_json.get("title") or "Auto Scenario"
                    )
                    parsed_json["metadata"].setdefault("compliance_level", "Standard")

                parsed_json["aes_version"] = config.AES_VERSION

                if "workflow" not in parsed_json:
                    legacy_tasks = parsed_json.get("tasks", [])
                    parsed_json["workflow"] = {"nodes": legacy_tasks or [], "edges": []}

                # Cleanup legacy fields
                parsed_json["aes_version"] = 1.4
                # Maintenance: 'version' is legacy, only 'aes_version' remains.
                parsed_json.pop("version", None)
                parsed_json.pop("tasks", None)

                return parsed_json

    except aiohttp.ClientConnectorError:
        raise ConnectionError(f"Could not connect to Ollama at {api_url}. Is Ollama running?")  # noqa: B904
    except json.JSONDecodeError as e:
        raise ValueError(  # noqa: B904
            f"Ollama returned invalid JSON: {e}\nRaw Response: {response_text[:200]}..."
        )


def save_scenario(scenario: dict[str, Any], output_path: Path):
    """Saves the translated JSON scenario to disk."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(scenario, f, indent=2)
        print(f"[OK] Translated scenario saved to: {output_path}")
    except OSError as e:
        print(f"[ERROR] Could not save scenario to {output_path}: {e}")
