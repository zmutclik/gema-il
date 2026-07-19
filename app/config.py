import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = Path(__file__).parent.parent

load_dotenv(BASE_DIR / ".env")

AI_URL = os.getenv("ai_url", "")
AI_MODEL = os.getenv("ai_model", "")
AI_KEY = os.getenv("ai_key", "")

ai_client: OpenAI | None = None
if AI_URL and AI_MODEL and AI_KEY:
    ai_client = OpenAI(base_url=AI_URL, api_key=AI_KEY)
