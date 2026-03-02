from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.pipeline import answer_question, init_db

load_dotenv()
init_db()

parser = argparse.ArgumentParser(description="Citation-enforced QA for a paper.")
parser.add_argument("--paper_id", required=True, help="paper_id returned by ingest.")
parser.add_argument("--question", required=True, help="Question to ask.")
parser.add_argument("--top_k", type=int, default=10, help="How many chunks to retrieve.")
args = parser.parse_args()

try:
    result = answer_question(paper_id=args.paper_id, question=args.question, top_k=args.top_k)
except ValueError as e:
    print(f"ERROR: {e}")
    print("Hint: check paper_id and question.")
    sys.exit(1)
except RuntimeError as e:
    print(f"ERROR: {e}")
    print("Hint: run build_index first, then retry QA.")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print(json.dumps(result, ensure_ascii=False, indent=2))
