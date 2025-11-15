def run_faz6_engine():
    try:
        from .faz6_test import run_faz6_test
        return run_faz6_test()
    except Exception as e:
        return f"FAZ-6 TEST MODÜL HATASI: {str(e)}"# faz6_engine_main.py
# FAZ-6 Ana Motor – tüm modları yöneten merkez

from faz6_engine.faz6_test import run_faz6_test
from faz6_engine.faz6_balance import run_faz6_balance
from faz6_engine.optimizer import run_faz6_risk

def run_faz6_engine(mode: str = "test", context: dict = None) -> dict:
    """
    FAZ-6'nın tüm modlarını yöneten ana motor.
    Mode seçenekleri:
      - test
      - balance
      - risk
    """

    if context is None:
        context = {}

    # TEST MODU
    if mode == "test":
        return run_faz6_test(context)

    # BALANCE MODU
    if mode == "balance":
        return run_faz6_balance(context)

    # RISK MODU
    if mode == "risk":
        return run_faz6_risk(context)

    # BİLİNMEYEN MOD — güvenlik
    return {
        "status": "error",
        "msg": f"Bilinmeyen FAZ-6 modu: {mode}"
    }

# Telegram tarafından çağrılan ana fonksiyon
def run(context: dict) -> dict:
    """
    Ana entrypoint — varsayılan olarak test modunu çalıştırır.
    """
    return run_faz6_engine("test", context) 
