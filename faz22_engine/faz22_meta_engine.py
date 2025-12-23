# faz22_engine/faz22_meta_engine.py

from typing import Dict, Any
from faz22_engine.faz22_meta import faz22_meta  # mevcut fonksiyonun

def faz22_meta_engine(faz13_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Public entry point expected by main.py
    Wraps existing faz22_meta logic
    """
    return faz22_meta(faz13_output)
