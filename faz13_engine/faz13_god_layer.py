# faz13_engine/faz13_god_layer.py
# ================================================================
# FAZ-13 GOD-LAYER (FINAL BUILD v2)
# Manual / Visual / Live fusion formatter
# - Import-time safe (no side effects)
# - Fly.io 512MB friendly
# - Telegram output length controlled
# ================================================================

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

log = logging.getLogger(__name__)


# -----------------------------
# ENV controls
# -----------------------------
def _env_bool(name: str, default: str = "0") -> bool:
    v = str(os.getenv(name, default)).strip().lower()
    return v in ("1", "true", "yes", "on", "y")


FAZ13_GOD_LAYER_INCLUDE_RAW = _env_bool("FAZ13_GOD_LAYER_INCLUDE_RAW", "0")
FAZ13_GOD_LAYER_RAW_MAX = int(os.getenv("FAZ13_GOD_LAYER_RAW_MAX", "1500"))
FAZ13_GOD_LAYER_TITLE = os.getenv("FAZ13_GOD_LAYER_TITLE", "FAZ-13 GOD-LAYER")


# -----------------------------
# Helpers
# -----------------------------
def _as_dict(obj: Any) -> Dict[str, Any]:
    """
    Gelen fusion objesini güvenli şekilde dict'e çevir.
    - dict ise direkt döner
    - string ise json.loads dene
    - değilse boş dict
    """
    try:
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, str):
            try:
                parsed = json.loads(obj)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}
    except Exception:
        return {}


def _safe_text(val: Any) -> str:
    try:
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="ignore").strip()
        if isinstance(val, (list, tuple)):
            return " ".join(str(x) for x in val).strip()
        return str(val).strip()
    except Exception:
        return ""


def _fmt_float(x: Any, ndigits: int = 2) -> str:
    try:
        return f"{float(x):.{ndigits}f}"
    except Exception:
        return "-"


def _fmt_vector(x: Any, ndigits: int = 1) -> str:
    """
    score_vector gibi tuple/list/iterable ise güzel yaz.
    """
    try:
        if x is None:
            return "-"
        if isinstance(x, (int, float)):
            return _fmt_float(x, ndigits)
        if isinstance(x, str):
            return x.strip()
        if isinstance(x, dict):
            # dict vector istemiyoruz ama patlamasın
            return json.dumps(x, ensure_ascii=False)
        if isinstance(x, Sequence) or isinstance(x, Iterable):
            vals = list(x)  # type: ignore[arg-type]
            if not vals:
                return "-"
            parts = []
            for v in vals[:8]:  # aşırı uzamasın
                parts.append(_fmt_float(v, ndigits))
            suffix = "" if len(vals) <= 8 else "…"
            return f"({', '.join(parts)}{suffix})"
        return _safe_text(x) or "-"
    except Exception:
        return "-"


def _safe_get_any(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """
    Birden fazla key adayından ilk bulunanı döndürür.
    Örn: ["total", "barem", "total_line"]
    """
    try:
        for k in keys:
            if k in d and d[k] not in (None, "", []):
                return d[k]
        return default
    except Exception:
        return default


def _compact_json(data: Dict[str, Any]) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(data)


# ================================================================
# ANA GATEWAY
# ================================================================
def run_faz13_with_god_layer(input_kind: str, fusion: Any) -> str:
    """
    main.py tarafından çağrılır.
    input_kind:
      - "manual" / "visual" / "live" / vs.

    fusion:
      - normalize_manual_text / normalize_visual_meta / normalize_api_data vb. çıktısı (dict veya json-string)

    GOD-LAYER:
      - ÇÖKMEZ
      - Mevcut alanları insan-dostu formatta özetler
      - Alan yoksa bağırmaz, sade kalır
    """
    try:
        kind = (input_kind or "").strip().upper() or "UNKNOWN"
        data = _as_dict(fusion)

        # -----------------------------
        # Temel alanlar
        # -----------------------------
        match_str = _safe_get_any(
            data,
            ["match", "match_name", "teams", "pair", "fixture", "display_name"],
            default="Bilinmeyen Maç",
        )
        league = _safe_get_any(data, ["league", "lig", "competition", "family"], default="-")
        date = _safe_get_any(data, ["date", "tarih", "match_date", "date_str"], default="-")

        total_line = _safe_get_any(data, ["total", "barem", "total_line", "o_u_line", "line"], default=None)
        pick_side = _safe_get_any(data, ["pick", "side", "direction", "secim", "oy"], default=None)
        odds = _safe_get_any(data, ["odds", "oran", "price"], default=None)

        low_bound = _safe_get_any(data, ["score_low", "range_low", "min_total", "target_min"], default=None)
        high_bound = _safe_get_any(data, ["score_high", "range_high", "max_total", "target_max"], default=None)

        confidence = _safe_get_any(data, ["confidence", "conf", "risk_score", "p"], default=None)
        engine = _safe_get_any(data, ["engine", "model", "faz_engine"], default="FAZ-13")

        reasons = _safe_get_any(data, ["reasons", "debug_reasons", "notes", "why"], default=[])
        if isinstance(reasons, str):
            reasons = [reasons]
        if not isinstance(reasons, list):
            reasons = []

        # opsiyonel sinyaller
        news_consensus = _safe_get_any(
            data,
            ["news_total_consensus", "news_consensus", "meta_news_consensus", "total_consensus"],
            default=None,
        )
        score_vector = _safe_get_any(
            data,
            ["internal_score_vector", "score_vector", "vector", "sv"],
            default=None,
        )

        # -----------------------------
        # Output build
        # -----------------------------
        lines: List[str] = []
        lines.append(f"🧠 {FAZ13_GOD_LAYER_TITLE} [{kind}]")
        lines.append(f"⚙️ Engine: {_safe_text(engine)}")
        lines.append("")
        lines.append(f"🏀 Maç : {_safe_text(match_str)}")
        lines.append(f"🏷️ Lig : {_safe_text(league)}")
        lines.append(f"🗓️ Tarih : {_safe_text(date)}")

        if total_line is not None or pick_side is not None or odds is not None:
            lines.append("")
            lines.append("📌 Market / Seçim")
            if total_line is not None:
                lines.append(f" • Toplam barem : {_fmt_float(total_line, 1)}")
            if pick_side is not None:
                lines.append(f" • Seçim : {_safe_text(pick_side)}")
            if odds is not None:
                lines.append(f" • Oran : {_fmt_float(odds, 2)}")

        if low_bound is not None or high_bound is not None:
            lines.append("")
            lines.append("🎯 Skor Aralığı Tahmini")
            lb = _fmt_float(low_bound, 1) if low_bound is not None else "?"
            hb = _fmt_float(high_bound, 1) if high_bound is not None else "?"
            lines.append(f" • Hedef bant : {lb} — {hb}")

        if confidence is not None:
            lines.append("")
            lines.append("🧷 Güven / Risk")
            lines.append(f" • Confidence : {_fmt_float(confidence, 3)}")

        if news_consensus is not None or score_vector is not None:
            lines.append("")
            lines.append("🧬 İçsel Sinyaller")
            if news_consensus is not None:
                lines.append(f" • News consensus : {_safe_text(news_consensus)}")
            if score_vector is not None:
                lines.append(f" • Score vector : {_fmt_vector(score_vector, 2)}")

        if reasons:
            lines.append("")
            lines.append("🧾 Gerekçeler / Notlar")
            for r in reasons[:12]:
                txt = _safe_text(r)
                if txt:
                    lines.append(f" • {txt}")

        # RAW snapshot sadece env ile
        if FAZ13_GOD_LAYER_INCLUDE_RAW:
            compact = _compact_json(data)
            if len(compact) > FAZ13_GOD_LAYER_RAW_MAX:
                compact = compact[:FAZ13_GOD_LAYER_RAW_MAX] + "...(kısaltıldı)"
            lines.append("")
            lines.append("🧩 RAW FUSION SNAPSHOT")
            lines.append(compact)

        return "\n".join(lines)

    except Exception as e:
        log.exception("run_faz13_with_god_layer error: %s", e)
        return "❌ FAZ-13 GOD-LAYER hata: çıktı üretilemedi."
