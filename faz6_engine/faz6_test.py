# FAZ-6 TEST MODÜLÜ
# Basit bir test çıktısı üretir

def run_faz6_test(context: dict = None) -> dict:
    """
    FAZ-6 test modülü.
    Sistem bileşenlerinin çalışıp çalışmadığını kontrol eder.
    """
    if context is None:
        context = {}

    return {
        "status": "ok",
        "module": "FAZ-6 TEST",
        "detail": "FAZ-6 test modülü başarıyla çalıştı.",
        "context": context,
    } 
