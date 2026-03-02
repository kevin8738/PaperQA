from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.pipeline import init_db, summarize_paper

load_dotenv()
init_db()

parser = argparse.ArgumentParser(description="Generate structured JSON summary for a paper.")
parser.add_argument("--paper_id", required=True, help="paper_id returned by ingest.")
args = parser.parse_args()

try:
    result = summarize_paper(args.paper_id)
except ValueError as e:
    print(f"ERROR: {e}")
    print("Hint: run ingest first.")
    sys.exit(1)
except RuntimeError as e:
    print(f"ERROR: {e}")
    print("Hint: verify pages are available and OPENAI_API_KEY is set in your environment (or .env).")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print(json.dumps(result, ensure_ascii=False, indent=2))
