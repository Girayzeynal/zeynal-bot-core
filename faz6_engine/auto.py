from future import annotations
from typing import Dict, Any, List

from .ml_brain import MLBrain
from .memory_unit import MemoryUnit
from .optimizer import Optimizer
from .faz6_balance import BalanceEngine
from .faz6_core import Faz6Core

class Faz6AutoEngine:
"""
FAZ-6 otomatik motor:
- memory → brain → optimizer → balance → core
"""
def init(self):
self.memory = MemoryUnit()
self.brain = MLBrain()
self.optimizer = Optimizer()
self.balance = BalanceEngine()
self.core = Faz6Core()

def run(self) -> Dict[str, Any]:  
    last = self.memory.load()  

    preds = self.brain.predict(last)  
    optimized = self.optimizer.optimize(preds)  
    balanced = self.balance.rebalance(optimized)  
    final = self.core.process(balanced)  

    self.memory.save(final)  
    return {  
        "status": "ok",  
        "mode": "auto",  
        "result": final  
    }

def run_faz6_auto():
return Faz6AutoEngine().run()
