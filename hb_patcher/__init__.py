"""
hb_patcher — HoopBrain Auto-Patcher Modülü
==========================================

Bu modül, HoopBrain Core’un otomatik olarak kendini güncellemesi için
hazırlanmış FULL AUTO PATCH motorunu içerir.

Modül Yapısı:
    - patcher_core.py   → Ana patch motoru
    - github_api.py     → GitHub API ile iletişim
    - file_parser.py    → Dosya düzenleme yardımcıları
    - patterns.py       → Eklenecek / silinecek kod kuralları

Versiyon:
    HB-PATCHER v1.0.0
"""

__version__ = "1.0.0"
__all__ = [
    "apply_patch",
]

try:
    # apply_patch direkt import edilebilir hale geliyor
    from .patcher_core import apply_patch
except Exception as e:
    # Patch motoru import edilemezse sessiz log bırak (main.py crash etmesin)
    import logging
    logging.getLogger("hb-patcher").warning(
        f"hb_patcher import sırasında hata: {e}"
    )
