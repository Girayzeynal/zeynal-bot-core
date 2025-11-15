# FAZ-6 ANA KOMUTA ODASI (ENGINE MAIN)
# Tüm FAZ-6 modüllerinin birleştiği merkez yapı.

from faz6_engine.faz6_test import run_faz6_test
from faz6_engine.faz6_real import run_faz6_real
from faz6_engine.faz6_balance import run_faz6_balance


def run_faz6_engine(context: dict = None, mode: str = "auto") -> dict:
    """
    FAZ-6 ENGINE, tüm alt modüllerin birleştiği kontrol merkezi.

    mode seçenekleri:
    - "test" → sadece test modülü çalışır.
    - "real" → sadece real modülü çalışır.
    - "balance" → balance modülü çalışır.
    - "auto" (varsayılan) → balance çalışır ve en iyi sonucu seçer.

    Bu fonksiyon FAZ-6'nın yüksek seviye API'sidir.
    """
    if context is None:
        context = {}

    # Komuta seçenekleri
    if mode == "test":
        return run_faz6_test(context)

    if mode == "real":
        return run_faz6_real(context)

    if mode == "balance":
        return run_faz6_balance(context, mode="auto")

    # Varsayılan → AUTO
    return run_faz6_balance(context, mode="auto")


# Bot tarafından çağrılan dış fonksiyon
def run(mode: str = "auto", context: dict = None) -> dict:
    return run_faz6_engine(context=context, mode=mode) 
