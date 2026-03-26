from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
import os
from dotenv import load_dotenv

load_dotenv()

@tool
def dummy(x: int) -> str:
    """A dummy tool."""
    return str(x)

def test_model(model_name):
    print(f"\n--- Testing {model_name} ---")
    try:
        llm = ChatGoogleGenerativeAI(model=model_name)
        print(f"LLM {model_name} initialized")
        llm_with_tools = llm.bind_tools([dummy])
        print(f"Tools bound successfully for {model_name}")
    except Exception as e:
        print(f"Error ({model_name}): {type(e).__name__}: {e}")
        if hasattr(e, 'errors'):
             print(f"Pydantic errors: {e.errors()}")

test_model("gemini-1.5-flash")
test_model("gemini-2.0-flash-exp")
test_model("gemini-2.5-flash")
