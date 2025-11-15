# FAZ-6 BALANCE MODÜLÜ
# REAL ve TEST sonuçlarını birleştiren, denge ve koordinasyon modülü.

from faz6_engine.faz6_real import run_faz6_real
from faz6_engine.faz6_test import run_faz6_test


def _safe_run(func, context: dict) -> dict:
    """
    Alt modülü güvenli çalıştıran yardımcı fonksiyon.
    Hata olursa status=error döner, sistem kırılmaz.
    """
    try:
        result = func(context)
        if not isinstance(result, dict):
            return {
                "status": "error",
                "module": func.__name__,
                "detail": "Modül dict yerine başka tip döndürdü.",
            }
        return result
    except Exception as e:
        return {
            "status": "error",
            "module": func.__name__,
            "detail": str(e),
        }


def run_faz6_balance(context: dict = None, mode: str = "auto") -> dict:
    """
    FAZ-6 BALANCE modülü.

    Görevleri:
    - REAL ve TEST modüllerini koordine eder.
    - Seçilen moda göre (real/test/auto) sonuç üretir.
    - AUTO modunda:
        - REAL ve TEST ikisini de çalıştırır,
        - REAL sorunsuzsa onu ana sonuç yapar,
        - REAL hata verirse TEST'i yedek plan olarak kullanır.
    """
    if context is None:
        context = {}

    # --- MODE: real → direkt REAL çalıştır, aynen ilet ---
    if mode == "real":
        real_result = _safe_run(run_faz6_real, context)
        return {
            "status": "ok" if real_result.get("status") == "ok" else "error",
            "module": "FAZ-6 BALANCE",
            "selected_mode": "real",
            "selected": real_result,
            "real": real_result,
            "test": None,
            "context": context,
        }

    # --- MODE: test → direkt TEST çalıştır, aynen ilet ---
    if mode == "test":
        test_result = _safe_run(run_faz6_test, context)
        return {
            "status": "ok" if test_result.get("status") == "ok" else "error",
            "module": "FAZ-6 BALANCE",
            "selected_mode": "test",
            "selected": test_result,
            "real": None,
            "test": test_result,
            "context": context,
        }

    # --- MODE: auto (varsayılan) ---
    # Hem REAL hem TEST çalışır, REAL öncelikli, TEST yedek plan.
    real_result = _safe_run(run_faz6_real, context)
    test_result = _safe_run(run_faz6_test, context)

    # Varsayılan seçim REAL olsun
    selected_mode = "real"
    selected = real_result

    # REAL hata verdiyse TEST'e düş
    if real_result.get("status") != "ok" and test_result.get("status") == "ok":
        selected_mode = "test"
        selected = test_result

    # İkisi de hatalıysa genel hata döndür
    if real_result.get("status") != "ok" and test_result.get("status") != "ok":
        return {
            "status": "error",
            "module": "FAZ-6 BALANCE",
            "selected_mode": None,
            "selected": None,
            "real": real_result,
            "test": test_result,
            "context": context,
            "detail": "REAL ve TEST modüllerinin ikisi de hata döndürdü.",
        }

    # Seçilen sonuca göre pick & confidence bilgilerini üst seviyeye çıkar
    pick = selected.get("pick")
    confidence = selected.get("confidence")

    return {
        "status": "ok",
        "module": "FAZ-6 BALANCE",
        "selected_mode": selected_mode,
        "selected_pick": pick,
        "selected_confidence": confidence,
        "real": real_result,
        "test": test_result,
        "context": context,
    } 
