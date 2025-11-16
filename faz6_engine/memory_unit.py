class MemoryUnit:
    """
    FAZ-6 hafıza birimi – çok basit in-memory kayıt.
    Gerçek sistemde dosya / DB olabilir.
    """
    def __init__(self):
        self._store = []

    def save(self, result: dict) -> None:
        self._store.append(result)

    def get_all(self) -> list[dict]:
        return list(self._store)
