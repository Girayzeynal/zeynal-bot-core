# faz6_engine_main.py  
# FAZ-6 Merkezi Motor – tüm modülleri yönetir

import time

# Modüllerin import edilmesi
from faz6_engine.faz6_test import run_faz6_test
from faz6_engine.faz6_balance import run_faz6_balance
from faz6_engine.optimizer import run_faz6_risk


def run_faz6_engine(mode="test"):
    """
    FAZ-6 Ana Motor
    mode parametresi ile hangi alt modülün çalışacağı seçilir.
    """

    print(f"FAZ-6 ENGINE BAŞLATILDI → mode={mode}")

    if mode == "test":
        print("TEST modu çalıştırılıyor...")
        return run_faz6_test()

    elif mode == "balance":
        print("BALANCE modu çalıştırılıyor...")
        return run_faz6_balance()

    elif mode == "risk":
        print("RISK modu çalıştırılıyor...")
        return run_faz6_risk()

    else:
        print(f"Tanımsız mode alındı: {mode}")
        return {"status": "error", "message": "Geçersiz mode", "timestamp": time.time()}


def run():
    """
    Varsayılan çalıştırıcı.
    Deploy sonrası sistem testi için FAZ-6 TEST modunu çağırır.
    """
    print("FAZ-6 varsayılan RUN fonksiyonu çalıştı.")
    return run_faz6_engine("test")
