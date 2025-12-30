import telegram  # Örnek olarak telegram bot API kullanımı

# ... (Diğer gerekli import ve ayarlar)

def format_analysis_message(game_id):
    # 1. Analiz verilerini ve market datasını çek
    analysis = run_analysis(game_id)  # kullanıcı analiz fonksiyonu (varsayım)
    # analysis içeriği: analysis.profile, analysis.baseline_info, analysis.tempo, analysis.pace, analysis.gap, analysis.vs, 
    # analysis.profile_score, analysis.baseline_src, analysis.confidence, analysis.mode, analysis.risk vb.
    try:
        market_data = fetch_market_data(game_id)  # Market API çağrısı (handikap, total için)
        market_status = "OK"
        market_reason = "-"
        if not market_data:
            # API yanıt verdi ama ilgili maç için veri yok
            market_status = "ERROR"
            market_reason = "NO_MARKET"
    except Exception as e:
        # API bağlantı hatası meydana geldi
        market_data = None
        market_status = "ERROR"
        market_reason = "API_CONNECTION_ERROR"
    
    # 2. Risk göstergeleri ve notlar
    risk_indicators = analysis.get_risk_indicators()  # Bu fonksiyon örnek; analizden risk verileri gelmeli
    # risk_indicators örneğin ["Back-to-back maçı", "Yorgunluk riski yüksek"] gibi listelenebilir
    
    # 3. Hata avcısı bölümündeki bayrakları belirle
    issues = []  # tespit edilen sorun kodları
    if analysis.missing_critical_data:
        issues.append("KRITIK_VERI_YOK")
    if analysis.sample_size_insufficient:
        issues.append("YETERSIZ_ORNEKLEM")
    if market_status == "ERROR" and market_reason == "NO_MARKET":
        issues.append("MARKET_YOK")
    
    # 4. Alt/Üst edge kontrolü
    ou_edge = False
    if market_data and hasattr(analysis, "predicted_total"):
        pred_total = analysis.predicted_total
        market_total = market_data.total if market_data else None
        if market_total and abs(pred_total - market_total) > 5:  # Örneğin 5 puandan büyük fark varsa edge diyelim
            ou_edge = True
    
    # 5. Mesajı parça parça oluştur
    msg_lines = []
    # Başlık ve maç bilgisi
    msg_lines.append(f"<b>FAZ-13 Ön Analiz: {analysis.match_title}</b>")
    msg_lines.append(f"Seçili periyot bandı: {analysis.period_band}")
    # Risk göstergeleri
    msg_lines.append("<b>Risk G\u00f6stergeleri:</b> " + (", ".join(risk_indicators) if risk_indicators else "Yok"))
    # Notlar (madde madde)
    msg_lines.append("<b>Notlar:</b>")
    msg_lines.append(f"- profile: {analysis.profile}")
    msg_lines.append(f"- baseline info: {analysis.baseline_info}")
    msg_lines.append(f"- tempo: {analysis.tempo}")
    msg_lines.append(f"- pace: {analysis.pace}")
    msg_lines.append(f"- gap: {analysis.gap}")
    msg_lines.append(f"- vs: {analysis.vs}")
    # Hata Avcısı
    msg_lines.append("<b>Hata Avc\u0131s\u0131:</b>")
    if issues:
        msg_lines.append(", ".join(issues))
    else:
        msg_lines.append("YOK")
    # Market Entegrasyonu
    msg_lines.append("<b>Market Entegrasyonu:</b>")
    msg_lines.append(f"status: {market_status}, reason: {market_reason}")
    if market_data:
        msg_lines.append(f"Handikap: {market_data.handicap}, Toplam: {market_data.total}")
    # Meta Skor
    confidence_percent = f"{analysis.confidence:.0%}"  # Güven değerini yüzde yap (örn 0.823 -> "82%")5
    msg_lines.append("<b>Meta Skor:</b> " +
                     f"profile: {analysis.profile}, baseline_src: {analysis.baseline_src}, "
                     f"confidence: {confidence_percent}, mode: {analysis.mode}, "
                     f"risk: {analysis.risk}, issues: {len(issues)}")
    # Alt/Üst edge uyarısı (varsa)
    if ou_edge:
        msg_lines.append("<b>Alt/Üst Uyar\u0131s\u0131:</b> Model bu maçta toplam sayı çizgisinde beklenenin dışında bir sapma öngörüyor! (Detaylar FAZ-17'de)")
    # Dipnot
    msg_lines.append("Bu \u00e7\u0131kt\u0131 analiz/sim\u00fclasyon ama\u00e7l\u0131d\u0131r. Bahis tavsiyesi de\u011fildir.")
    
    # Tüm satırları tek bir string haline getirin
    final_message = "\n".join(msg_lines)
    return final_message

# ... (Telegram bot send_message ile final_message'ı gönderme vs.)
