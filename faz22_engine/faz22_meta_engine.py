# faz22_engine/faz22_meta_engine.py

from typing import Dict, Any
from faz22_engine.faz22_meta import faz22_meta_engine as _impl


def faz22_meta_engine(faz13_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Public entry point expected by main.py

    - main.py şu importu yapar:
        from faz22_engine.faz22_meta_engine import faz22_meta_engine

    - Bu dosya, gerçek implementasyonu (faz22_meta_engine)
      faz22_meta.py içinden güvenli şekilde wrap eder.
    """
    return _impl(faz13_output) 
