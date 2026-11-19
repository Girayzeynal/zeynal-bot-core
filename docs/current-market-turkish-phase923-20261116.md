# FAZ 92.3 — Türkçe piyasa görünümü ve ayrı güncel değerlendirme

PR #89'un mevcut `feature/hybrid-market-roster-evidence-20261114` dalındaki devamıdır.
Başlangıç: `0932713d41dbd2fac1c271fcb5006f61f4450922`.

## Türkçe görünüm

FanDuel, BetOnline.ag, LowVig.ag ve DraftKings marka/kimlikleri korunur.
Kaynak JSON anahtarları, bookmaker ID, fiyatlar ve SHA değerleri çevrilmez.
Telegram görünümünde:

| Teknik alan | Gösterim |
|---|---|
| FULL | Maçın tamamı |
| TOTAL | Toplam sayı |
| HOME / AWAY | Ev sahibi / deplasman takım toplamı |
| HOME_HANDICAP | Ev sahibi handikabı |
| WINNER | Maç sonucu |
| 1Q–4Q | 1.–4. çeyrek |
| 1H / 2H | İlk yarı / ikinci yarı |
| SETTLEMENT_RULE_UNVERIFIED | Ödeme ve uzatma kuralı doğrulanmadı |
| STALE_AT_DECISION_TIME | Kaynak gözlemi bu değerlendirme için eskimiş |

`NOT_CALIBRATED` denetim işareti, Türkçe açıklamasıyla görünmeye devam eder.
Platform, oran sağlayıcısı ve kaynak alan adı ayrı gösterilir. Aynı platformun
satırları gruplanır; farklı platform fiyatları birleştirilmez.

## Gerçek sorun ve düzeltmenin sınırı

Kullanıcının paylaştığı gerçek izole bot çıktısında 16 Kasım 08:49:48 TSİ'deki
ilk tahmine, 11:25:01 TSİ'de alınan gerçek The Odds API oranları eşlik ediyordu.
Eski `market_views.assess` fiyatın ilk tahmin anında erişilebilir olmasını ister;
ayrıca provider paneli native `QuoteEvidence` aktarmıyordu. Dolayısıyla sonraki
fiyat eski tahmin için uygun sayılamıyor, EV yolu çağrılmıyordu. Bu davranışı
ilk tahminin saatini ileri taşıyarak veya eski denetim politikasını gevşeterek
değiştirmiyoruz.

Yeni `current_market_review` native katalog ve fiyat belgelerini kendi SHA
adreslerinden yeniden okur, parser üyeliğini doğrular ve gerçek fiyat kanıtını
oluşturur. Ayrı güncel değerlendirme saati, özgün tahmin saati ve fiilî kayıt
saati tutulur. Sonraki oran güncel incelemede kullanılabilir; ilk tahminin geçmiş
girdisi veya o andaki piyasa avantajı sayılmaz. Mevcut tahmin modeli ve 10.000
QMC örneğinin SHA değeri yeniden doğrulanır; yeni tahmin/eğitim yapılmaz.

Boston–Orlando için önceki bağlama kuralı korunur: ESPN 00:00 UTC, sağlayıcı
00:10 UTC; sınır erken olan **00:00 UTC**'dir. Genel bir ±10 dakika toleransı
eklenmez. Kararın dosyaya ilk kaydı maç başlangıcına yetişmediyse kayıt
`POST_TIPOFF_REVIEW_ONLY` olur. Maç öncesi karar olarak sunulmaz.

## Eklemeli karar arşivi

İzole `data/provider-evidence` belgelerinden ayrı olarak, `data/current-market-reviews`
altına `review-<manifest_sha256>.json` yazılır. Kaydın payload SHA'sı, ilk tahmin
SHA'sı, model sürümü, örnek SHA'sı, fiyat gözlemleri, karar ve kayıt zamanları
saklanır. Aynı karar manifesti aynı ilk kaydı döndürür; üzerine yazılmaz.
SQLite açılmaz. Dosya sayısı/boyutu sınırlıdır; sınır dolunca eski kayıt silmek
yerine açık hata verilir. Disk hatası başarılı arşivleme olarak raporlanmaz.

Bu kayıtlar ilk tahminin `/accuracy` hesabına dahil değildir. Aynı maça ait
çok sayıda fiyatı bağımsız maç örnekleri saymaz. Güncel kararlar için de henüz
bir performans üstünlüğü veya otomatik kalibrasyon iddiası yoktur.

## Beklenen getiri ve eksik kanıtlar

Gerçek oran görüldüğünde `1 / ondalık oran`, iade dışı koşullu başa baş eşiği
olarak gösterilebilir. Bu yalnız fiyat matematiğidir; gerçek olay olasılığı veya
doğrulanmış avantaj değildir. Modelin ham normal süre kütlesi ayrı gösterilir.

Ham sözleşme EV hesabı için belirli platform/lig/dönem/piyasaya ait, karar anında
geçerli ve zaman damgalı ödeme/uzatma kuralı gerekir. Kurala göre OT örnekleri
gerekiyor ve arşivde yoksa EV hesaplanmaz. Tam sayı çizgisinde iade kütlesi
korunur: `EV = p_kazanma * (oran - 1) - p_kaybetme`; iade olasılığı kayıp
sayılmaz. Çeyrek baremli bölünmüş bahisler desteklenmediği için kapalı kalır.

**Canlı yapılandırmada doğrulanmış platform ödeme kuralları henüz bağlı değil.**
Bu increment FanDuel/DraftKings vb. için kural uydurmaz ve gerçek EV hazır
iddiasında bulunmaz. Sentetik kural testleri yalnız matematik/doğrulama yolunu
sınar. Kalibrasyon yokken ham EV mümkün olsa da kalibre edilmiş güven yüzdesi,
bahis seçimi veya doğrulanmış model üstünlüğü üretilmez. `NO_EDGE` ancak gerçek
hesaplanan ham EV pozitif değilse kullanılır; eksik veri bununla karıştırılmaz.

## Gerçek ortam durumu

Kullanıcının paylaştığı önceki bot yanıtları gerçek kaynak ve Telegram akışına
ait kullanıcı kanıtıdır. Bu yeni sürümün Cloud'dan doğrudan gerçek Bot API E2E
teslimi yapılmadı; özel test erişimi burada yok. Yerel PTB + HTTP testi gerçek
Telegram teslimi olarak adlandırılmaz. API-Basketball'ın önceki lig/sezon plan
reddi çözülmüş sayılmaz; ücretli abonelik veya staged secret aktivasyonu yapılmaz.

İzole botun çalıştığı kendi terminalinde Ctrl+C'den sonra kanonik başlatıcı:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Bu mevcut araştırma dalını günceller. Test botunda uygun başlamamış maç için
`/analyze` ve **Piyasa** düğmesiyle Türkçe satırlar ve ayrı karar SHA'sı kontrol
edilebilir. Sadece eski botu çalışır bırakmak yeni kodun yüklendiğini kanıtlamaz.

**Üretim NO-GO:** ödeme/OT kapsamı, ileri kalibrasyon ve bu sürümün gerçek E2E
kanıtı eksiktir. Main merge, Fly deploy, üretim DB/diski/snapshot veya secret
değişikliği yapılmaz. Faz13 varsayılanı ve değişmez tahmin arşivleri korunur.

Yerel test kanıtı: `current-market-turkish-phase923-evidence-20261116.json`.
GitHub Actions'ın bu commit'e ait son durumu PR #89 üzerinde ayrıca raporlanır.
