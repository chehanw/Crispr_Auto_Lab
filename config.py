"""
Central configuration: API keys, model names, paths, constants.
All values loaded from environment — never hardcoded.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"

SGRNA_LIBRARY_PATH = DATA_DIR / "sgrna_library.csv"

# ── Anthropic ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# Model tiers (see performance.md)
MODEL_MAIN = "claude-sonnet-4-6"       # orchestration + protocol gen
MODEL_FAST = "claude-haiku-4-5-20251001"  # parser, reviewer (high-frequency)

# ── LLM Sampling ──────────────────────────────────────────────────────────
MAX_TOKENS = 4096
TEMPERATURE = 0.2   # low — we want deterministic structured outputs

# ── sgRNA Retrieval ────────────────────────────────────────────────────────
TOP_K_GUIDES = 3    # number of sgRNAs returned per gene
MIN_EFFICIENCY_SCORE = 0.5
