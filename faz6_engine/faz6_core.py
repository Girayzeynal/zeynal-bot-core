from .memory_unit import MemoryUnit
from .ml_brain import MLBrain
from .optimizer import Optimizer

class FAZ6Core:
    """
    FAZ-6 temel çekirdeği.
    """

    def __init__(self):
        self.memory = MemoryUnit()
        self.brain = MLBrain()
        self.optimizer = Optimizer()

    def analyze(self, stats: dict) -> dict:
        base = self.brain.simple_predict(stats)
        return base

    def learn(self, result: dict):
        self.memory.save(result)
        return self.optimizer.adjust(self.memory.get_all())
