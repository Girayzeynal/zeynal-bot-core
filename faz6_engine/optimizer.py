class Optimizer:
    """
    FAZ-6 optimizer — Hafıza + ML beyni birlikte çalışınca
    hata azaltma algoritmalarını yönetecek.
    """

    def adjust(self, memory_list: list) -> dict:
        if not memory_list:
            return {"adjustment": 0}

        total = len(memory_list)
        correct = len([m for m in memory_list if m.get("correct")])

        ratio = correct / total
        adj = round((ratio - 0.5) * 2, 2)

        return {"adjustment": adj}
