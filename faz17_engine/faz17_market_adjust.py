def faz17_market_adjust(model_prob_over: float,
                        model_prob_under: float,
                        odds_over: float,
                        odds_under: float) -> dict:
    """
    FAZ-17 tek maç market analiz motoru:
    Model olasılıklarını implied prob ile karşılaştırıp edge üretir.
    """

    def imp(x):
        try:
            x = float(x)
            if x <= 1.0:
                return 0.0
            return 1.0 / x
        except:
            return 0.0

    imp_over = imp(odds_over)
    imp_under = imp(odds_under)

    # Under tamamlayıcı model olasılığı
    model_prob_under = max(0.0, min(1.0, 1.0 - model_prob_over))

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
