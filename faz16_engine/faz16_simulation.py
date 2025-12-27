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

    Toplam skor dağılımını daha gerçekçi modellemek için normal dağılım karışımları
    kullanılır; örneklerin %80'i verilen sapma ile, %20'si 1.5 kat sapma ile üretilir.
    Negatif veya sıfır volatilite için dinamik minimum değer uygulanır.

    Args:
        base_total: Beklenen toplam skor ortalaması.
        vol: Standart sapma (negatif veya sıfırsa otomatik düzeltilir).
        n_iter: Örnek sayısı (varsayılan 10_000).
        line: Piyasa toplam çizgisi; verilirse over/under olasılıkları hesaplanır.

    Returns:
        Sözlük: {"mean", "std", "p25", "p50", "p75", "line", "p_over", "p_under"}.
    """
    # Dinamik minimum volatilite uygula
    if vol <= 0:
        vol = max(8.0, base_total * 0.05)

    rng = np.random.default_rng()
    weights = rng.random(n_iter)
    samples_base = rng.normal(loc=base_total, scale=vol, size=n_iter)
    samples_heavy = rng.normal(loc=base_total, scale=vol * 1.5, size=n_iter)
    samples = np.where(weights < 0.8, samples_base, samples_heavy)

    summary: Dict[str, Any] = {
        "mean": float(np.mean(samples)),
        "std": float(np.std(samples)),
        "p25": float(np.percentile(samples, 25)),
        "p50": float(np.percentile(samples, 50)),
        "p75": float(np.percentile(samples, 75)),
    }

    if line is not None:
        over_prob = float(np.mean(samples > line))
        under_prob = 1.0 - over_prob
        summary["line"] = float(line)
        summary["p_over"] = over_prob
        summary["p_under"] = under_prob

    return summary 
