"""
Local test runner for the morning brief pipeline.

Usage:
    python run_local.py                # build report only
    python run_local.py --send-email   # also send email
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from main import main

if __name__ == "__main__":
    main()
