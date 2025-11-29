from typing import Any, Dict


def faz10_stability_check(source_type: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-10 — HardSync / Stability Check (v1 skeleton)
    Şimdilik:
      - meta'yı kopyalar
      - bazı default alanları garanti eder
      - ileride: FAZ-7 hafızasına göre anomali filtresi, temp noise filtresi
    """
    m = dict(meta or {})
    m.setdefault("league", "NBA")
    m.setdefault("market", "FT TOTAL")
    m.setdefault("_faz10_checked", True)
    m.setdefault("_faz10_source", source_type)
    return m
