class MemoryUnit:
    """
    FAZ-6 hafıza sistemi — maç sonuçlarını, tahminleri ve hata örneklerini saklar.
    Bu bir iskelet yapıdır.
    """

    def __init__(self):
        self.storage = []

    def save(self, data: dict):
        self.storage.append(data)

    def get_all(self):
        return self.storage

    def clear(self):
        self.storage = []
