import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# RFT-eligible reasoning model. Swap to whichever RFT-supported model you have.
MODEL_NAME = os.getenv("OPENAI_RFT_MODEL", "o4-mini-2025-04-16")
PHOENIX_PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "spreadsheet-agent-benchmark-openai")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")

METRICS_DIR = "metrics_openai"
MAX_TOKENS = 2048
