from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
import os
from dotenv import load_dotenv

load_dotenv()

@tool
def dummy(x: int) -> str:
    """A dummy tool."""
    return str(x)

try:
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
    print("LLM initialized with 1.5-flash")
    llm_with_tools = llm.bind_tools([dummy])
    print("Tools bound successfully for 1.5-flash")
except Exception as e:
    print(f"Error (1.5-flash): {e}")

try:
    llm2 = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
    print("\nLLM initialized with 2.5-flash")
    llm_with_tools2 = llm2.bind_tools([dummy])
    print("Tools bound successfully for 2.5-flash")
except Exception as e:
    print(f"Error (2.5-flash): {e}")
