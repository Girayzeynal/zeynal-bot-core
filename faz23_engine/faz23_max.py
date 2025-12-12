# faz23_engine/faz23_max.py

import time
import math
import hashlib
import json

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    import numpy as np
except ImportError:
    np = None  # numpy yoksa devam

# ================================================================
# CONFIG
# ================================================================

@dataclass
class Faz23MaxConfig:
    base_iter: int = 500
    max_iter: int = 2400
    low_uncert_spread: float = 12.0
    high_uncert_spread: float = 26.0
    cache_limit: int = 60
    min_total: float = 120.0
    max_total: float = 260.0
    history_path: str = "/data/faz23_history.jsonl"

FAZ23_MAX_CACHE: Dict[str, Dict[str, Any]] = {}
