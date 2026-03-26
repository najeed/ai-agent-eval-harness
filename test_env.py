from langchain_google_genai import ChatGoogleGenerativeAI
import os
from dotenv import load_dotenv

load_dotenv()

try:
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
    print("LLM initialized successfully")
except Exception as e:
    print(f"Error: {e}")
