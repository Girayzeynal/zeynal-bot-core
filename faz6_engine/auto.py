"""
FAZ-6 AUTO ENGINE
Sistemin tüm birimlerini otomatik olarak çalıştırır:
- ML Brain
- Memory Unit
- Balance Engine
- Optimizer
- Core Engine

Bu modül Faz-6’nın "otomatik pilotudur".
"""

from faz6_engine.ml_brain import MLBrain
from faz6_engine.memory_unit import MemoryUnit
from faz6_engine.optimizer import Optimizer
from faz6_engine.faz6_balance import BalanceEngine
from faz6_engine.faz6_core import Faz6Core


class AutoEngine:
    def __init__(self):
        self.memory = MemoryUnit()
        self.brain = MLBrain()
        self.optimizer = Optimizer()
        self.balance = BalanceEngine()
        self.core = Faz6Core()

    def auto_cycle(self):
        """
        Tek bir otomatik Faz-6 döngüsü çalıştırır.
        """

        # 1) Hafızadan son bilgileri al
        last_memory = self.memory.load()

        # 2) ML Brain ile tahmin
        predictions = self.brain.predict(last_memory)

        # 3) Tahminleri optimize et
        optimized = self.optimizer.optimize(predictions)

        # 4) Balance Engine çalıştır
        balanced = self.balance.rebalance(optimized)

        # 5) Faz-6 Core'a gönder
        result = self.core.process(balanced)

        # 6) Çıktıyı yeniden hafızaya kaydet
        self.memory.save(result)

        return result


# Basit test modu
def auto_test():
    engine = AutoEngine()
    return engine.auto_cycle()
