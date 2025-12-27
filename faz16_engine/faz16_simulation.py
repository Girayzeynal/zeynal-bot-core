from typing import Dict, Any, Optional

import numpy as np


def faz16_run_simulation(
    base_total: float,
    vol: float,
    n_iter: int = 10000,
    line: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Gelişmiş Monte Carlo simülasyonu.

    Bu fonksiyon, toplam skorun dağılımını daha gerçekçi modellemek için
    normal dağılım karışımları kullanır. Lig skorları genellikle ağır
    kuyruklara ve değişkenliğe sahiptir; bu nedenle örneklerin %80'i
    verilen standart sapma (vol) ile, %20'si ise 1.5 katı ile üretilir.
    Böylece yüksek ve düşük skorların olasılığı daha doğru yansıtılır.

    Fonksiyon, örneklerin ortalamasını, standart sapmasını, 25./50./75.
    yüzdeliklerini hesaplar ve opsiyonel olarak bir çizgi (line) verildiğinde
    üst/alt olasılıklarını döndürür.

    Args:
        base_total: Beklenen toplam skorun ortalaması.
        vol: Tahmini standart sapma. Sıfır veya negatif ise minimum değer
            uygulanır.
        n_iter: Üretilecek örnek sayısı (varsayılan 10_000).
        line: Piyasa toplam çizgisi; verilirse "p_over" ve "p_under"
            olasılıkları hesaplanır.

    Returns:
        Bir sözlük: {"mean", "std", "p25", "p50", "p75", "line", "p_over", "p_under"}.
    """

    # Negatif veya sıfır volatilite gelirse dinamik bir minimum uygula.
    # Lig ortalaması 8,0 civarında; aynı zamanda skor toplamının %5'i kadar.
    if vol <= 0:
        vol = max(8.0, base_total * 0.05)

    rng = np.random.default_rng()
    # Karışım için rastgele ağırlıklar üret. 0.8 olasılıkla temel vol, aksi takdirde ağır kuyruk.
    weights = rng.random(n_iter)
    # İki farklı normal dağılımdan örnekler.
    samples_base = rng.normal(loc=base_total, scale=vol, size=n_iter)
    samples_heavy = rng.normal(loc=base_total, scale=vol * 1.5, size=n_iter)
    samples = np.where(weights < 0.8, samples_base, samples_heavy)

    # İstatistiksel özetleri hesapla.
    summary: Dict[str, Any] = {
        "mean": float(np.mean(samples)),
        "std": float(np.std(samples)),
        "p25": float(np.percentile(samples, 25)),
        "p50": float(np.percentile(samples, 50)),
        "p75": float(np.percentile(samples, 75)),
    }

    # Opsiyonel olarak çizgiye karşı over/under olasılıkları.
    if line is not None:
        over_prob = float(np.mean(samples > line))
        under_prob = 1.0 - over_prob
        summary["line"] = float(line)
        summary["p_over"] = over_prob
        summary["p_under"] = under_prob

    return summary 
