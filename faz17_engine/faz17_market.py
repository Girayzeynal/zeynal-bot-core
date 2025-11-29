from typing import Dict, Any, List


def implied_prob(odds: float) -> float:
    """
    Decimal odd → implied probability.
    Örn: 1.80 → 0.555...
    """
    if odds <= 1.0:
        return 0.0
    return 1.0 / odds


def faz17_enrich_with_market(
    model_prob_over: float,
    odds_over: float,
    odds_under: float,
) -> Dict[str, float]:
    """
    Model tahmini + piyasa oranlarını alıp:
    - implied_over / implied_under
    - model_edge_over / model_edge_under
    döndürür.
    """

    imp_over = implied_prob(odds_over)
    imp_under = implied_prob(odds_under)

    # Under için model olasılığını tamamlayıcı alıyoruz
    model_prob_under = max(0.0, min(1.0, 1.0 - model_prob_over))

    edge_over = model_prob_over - imp_over
    edge_under = model_prob_under - imp_under

    return {
        "implied_over": float(imp_over),
        "implied_under": float(imp_under),
        "model_prob_over": float(model_prob_over),
        "model_prob_under": float(model_prob_under),
        "edge_over": float(edge_over),
        "edge_under": float(edge_under),
    }


def faz17_pick_edge_lines(
    candidates: List[Dict[str, Any]],
    min_edge: float = 0.03,
) -> List[Dict[str, Any]]:
    """
    Kupon aday listesini alır, minimum edge'e göre filtreler.
    candidates elemanı örnek:
        {
          "match_key": "...",
          "line": 159.5,
          "odds_over": 1.72,
          "odds_under": 1.60,
          "model_prob_over": 0.58,
        }
    """

    selected: List[Dict[str, Any]] = []

    for c in candidates:
        market_info = faz17_enrich_with_market(
            model_prob_over=float(c["model_prob_over"]),
            odds_over=float(c["odds_over"]),
            odds_under=float(c["odds_under"]),
        )
        best_edge = max(
            market_info["edge_over"],
            market_info["edge_under"],
        )
        if best_edge >= min_edge:
            out = dict(c)
            out.update(market_info)
            out["best_edge"] = float(best_edge)
            selected.append(out)

    # Edge'e göre sırala (büyükten küçüğe)
    selected.sort(key=lambda x: x.get("best_edge", 0.0), reverse=True)
    return selected

def faz17_market_adjust(model_prob_over: float,
                        model_prob_under: float,
                        odds_over: float,
                        odds_under: float) -> dict:
    """
    FAZ-17 basit market uyumlayıcı:
    Model olasılıklarını ve piyasa oranlarını harmanlayıp
    edge ve bias çıkarır.
    """
    try:
        imp_over = 1.0 / float(odds_over)
    except:
        imp_over = 0.0

    try:
        imp_under = 1.0 / float(odds_under)
    except:
        imp_under = 0.0

    edge_over = model_prob_over - imp_over
    edge_under = model_prob_under - imp_under

    return {
        "model_prob_over": model_prob_over,
        "model_prob_under": model_prob_under,
        "implied_over": imp_over,
        "implied_under": imp_under,
        "edge_over": edge_over,
        "edge_under": edge_under,
    }
