from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.pipeline import ingest_pdf, init_db

load_dotenv()
init_db()

parser = argparse.ArgumentParser(description="Ingest a local PDF into PaperQA storage.")
parser.add_argument("--file_path", required=True, help="Local path to a PDF file.")
parser.add_argument("--extract_equations", type=int, choices=[0, 1], default=1, help="1 to run equation OCR.")
parser.add_argument(
    "--eq_pages",
    choices=["methods_appendix", "all"],
    default="methods_appendix",
    help="Which pages to scan for equations.",
)
args = parser.parse_args()

try:
    result = ingest_pdf(
        file_path=args.file_path,
        extract_equations=bool(args.extract_equations),
        eq_pages=args.eq_pages,
    )
except FileNotFoundError as e:
    print(f"ERROR: {e}")
    print("Hint: check --file_path and run ingest again.")
    sys.exit(1)
except RuntimeError as e:
    print(f"ERROR: {e}")
    print("Hint: if equation extraction is enabled, set OPENAI_API_KEY in your environment (or .env).")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print(json.dumps(result, ensure_ascii=False, indent=2))
