# Hibrit motor — araştırma başlangıç denetimi

Temel commit `8974ec4ff90154675bfa545d3b0125eb8b0da756` (PR #83 merge).
Üretimdeki image kaynak SHA'sı `dacec114341edd08bd54d631f1128f0624eccf2a`;
iki commit'in Git ağacı aynıdır. Bu geliştirme main'e veya Fly.io'ya gönderilmez.

## Mevcut motorların gerçek görevleri

| Bileşen | Kod / bağımlılık | Gerçek durum ve sınırlama |
|---|---|---|
| Faz13 legacy | `faz13_engine/faz13_engine.py`, `core/aggregate_engine.py`, baseline store, mevcut Monte Carlo | Skor uzlaştırması `(ev PF + dep PA)/2`; baseline yetersizliğinde ret. Bazı legacy confidence değerleri örneklem heuristiğidir, kalibrasyon kanıtı değildir. |
| Üretim V1 | `verified_analysis.py`, `verified_history.py`, `prematch_monte_carlo.py` | Gerçek /analyze yolu bu servisten erken döner. Sezon/takım/fikstür ve normal süre kontrolü, 10+10 geçmiş, tarihsel çeyrek ortalamaları, 10.000 normal-skor MC. |
| Faz17 | `faz17_engine/faz17_engine.py`, aiohttp, The Odds API key | Piyasa kaynağı/quote eşleştirmesi; bağımsız skor tahmin modeli değildir. Bu görevde ücretli uç noktası çağrılmaz ve secret aranmaz. |
| Faz22 | `faz22_engine/faz22_engine.py`, league profiles | Eşik, confidence ve karar/risk katmanı. Sabit std çarpanları ve confidence sınırları öğrenilmiş olasılık değildir. |
| Faz23 | `faz23_engine/faz23_engine.py`, SQLite | Faz13/17/22 çıktısından güçlü sinyal filtresi. Constructor DB açar; denetimde üretim dosyasıyla başlatılmaz. Legacy snapshot tablosu yeni immutable ledger ile aynı değildir. |
| Eski advanced stats script'i | `team_advanced_stats.py`, BDL key | `/stats` oyuncu satırlarını game gibi sayar ve olmayan `opp_pts` alanını 0'a düşürür. Yeni modelde bu çıktı kullanılmaz. Kod üretim yolunda değiştirilmez. |

Faz13 sayısal referansı yeniden yazılmaz: mevcut `historical_research.reference_predict`
kullanılır; canlı V1 skor/çeyrek formülüyle eşdeğerliği regresyonda sınanır.
Yeni Gaussian araştırma dağılımı V1 Python-random MC'sinin aynısı diye sunulmaz.
Faz17/22/23 için bağımsız gerçek isabet oranı veya yeni model üstünlüğü mevcut değildir.

## Mevcut gerçek arşiv

| Lig / sezon | Benzersiz tamamlanmış maç | Periyot |
|---|---:|---:|
| NBA 2026/2027 | 160 | 160 |
| EuroLeague 2026/2027 | 100 | 100 |
| EuroLeague 2025/2026 | 380 | 380 |

Kaynaklar önceki çalışmanın pinned `collection.json` ve EuroLeague 2025 catalog'udur;
640 maç tam bağımsız sezon kapsamı iddiası değildir. Skor gözlem/ingestion zamanları
korunur; geçmiş kaynakların tahmin öncesinde erişilebilirliği kanıtlanmış değildir.
Önceki strict replay uygun örnek sayısı 0'dır. Mevcut 2 gerçek üretim snapshot'ı
bu eğitim arşivine aktarılmaz; henüz yeni model final eşleşmesi yoktur.

İlk arşivde NBA ORB/TOV yok, EuroLeague takım istatistikleri yoktu. ESPN summary
ve resmî EuroLeague `.../games/{gameCode}/stats` ücretsiz uç noktalarıyla ayrıca
box-score gözlemleri toplanır. Bunlar sonradan alınmış HISTORICAL_DATA'dır;
oyuncunun gerçek oynadığı süre veya ilk beşi maç öncesi lineup gibi kullanılmaz.
Kaynak 403/429, eksik alan, kimlik/skor/periyot çelişkisi ayrı raporlanır.

## Kanıt ve güvenlik sözleşmesi

- Varsayılan `PIT_PROVEN_BACKTEST`: kaynak gözlemi ve ingestion cutoff öncesi.
- Açık `AVAILABILITY_ASSUMED_RESEARCH`: önceki maçın start+24h erişilebilirliği
  varsayımıdır; gerçek erişilebilirlik veya canlı tahmin performansı değildir.
- Her modelin train/validation/test sınırı ve model/source digest'i ayrı tutulur.
- `source_permission=NOT_ESTABLISHED` bir veri sağlayıcısı lisansı değildir;
  üretim terfisi için bu engel de kalkmalıdır. Yerel araştırma kullanıcı yetkisiyle yapılır.
- Box possession `FGA + 0.44*FTA - ORB + total TOV` bir tahmindir. Uzatmalı
  maçın toplam box score'u normal süre possession eğitimi için kullanılmaz.
- Roster, injury, PBP context geçişi yoksa ilgili bileşen ABSTAIN/NOT_AVAILABLE;
  eksik veriye lig ortalaması atayıp doğrulanmış girdi denmez.
- Yeni kod `hybrid_engine` altında, production import/call graph'ından ayrıdır.
  `/data`, bot polling/webhook, Fly veya secret erişimi yoktur.

Bu denetim model doğruluğu/kalibrasyon tamamlandı demek değildir. Nihai kabul,
aynı maçlarda bağımsız zaman dönemlerinde ölçülen iyileşme ve insan yayın onayı gerektirir.
