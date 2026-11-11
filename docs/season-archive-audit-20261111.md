# NBA / EuroLeague 2026–2027 arşiv ve kalibrasyon denetimi

## Başlangıç ve izolasyon

İncelenen main: `0e634083ccd1da87c7313710a17aa6e63fb5abe2` (#78). PR #79 açık/taslak: `c847b04da89fa14d8771fa544daf44f7ac5852a7`. İkisinin unit-tests ve docker-build işleri başarılı; PR #79 unit logunda 253 test / OK doğrulandı. Eski FAZ47 çalışma ağacı ve diğer dallar korundu. Bu dal `dev/season-fixture-audit-20261111`, PR #79 üzerine kuruludur; yeni taslak PR main'i hedeflese de **main'e merge yapılmaz** ve PR #79 bağımlılığı incelemede görünür tutulur.

Fly.io'ya bağlanılmadı; `/data` okunmadı veya yazılmadı. Üretim veritabanının güncel içeriği/hash'i bu oturumda ölçülmedi. Yeni denetleyici `/data` yollarını, symlink'leri, WAL/journal içeren aktif dosyaları ve güvenli snapshot olmayan WAL ana dosyalarını reddeder. Sadece ayrıca sağlanmış yerel statik SQLite kopyasını `mode=ro&immutable=1`, query_only ve açık bağlantı kapatma ile okur. Şema eksikliği, SQLite bozulması, yarış veya dosya hash değişikliği kısmi örnek sayısı üretmez. Mevcut ledger şemasına migration veya tahmin yazımı yoktur.

## Gerçek kaynak kontrolü — 11 Kasım 2026

İlk belgeler yaklaşık **19:13 TSİ** alındı. İstekler açık/ücretsiz uçlara yapıldı; anahtar, ücretli servis veya engel aşma kullanılmadı. Ham belgeler yalnızca yerel scratch dizinindedir; GitHub'a sadece kod, testler ve özet/hash metadatası eklenir.

| Kaynak ve kapsam | HTTP | Kaynak belgesinden doğrulanan kapsam |
|---|---|---|
| ESPN NBA `scoreboard?dates=20261110&limit=1000` | 200 | Tek sağlayıcı gün sorgusu: 6 bağımsız maç, 6 FINAL, 6 geçerli periyot dökümü |
| NBA.com `scheduleLeagueV2.json` | 403 | Resmî NBA çapraz kontrolü yapılamadı; 0 maç var diye yorumlanmadı |
| EuroLeague resmî `E2026/games` kataloğu | 200 | `total=380`, 380 bağımsız normal sezon fikstürü, 100 oynanmış/sonucu ve periyotları tutarlı, 280 henüz oynanmamış |
| ESPN 1–10 Kasım aralığı sorgusu (`dates=20261101-20261110&limit=1000&seasontype=2`) | 400 | Toplu tarih sorgusu başarısız; kapsam genişlemiş veya boş takvim diye raporlanmadı |

ESPN'in gün etiketi UTC maç günüyle birebir aynı olmak zorunda değildir. NBA sayısı tüm sezonun arşivi değildir. EuroLeague'de sayfa toplamı ile dönen kayıt sayısı eşleşir; bu, bağımsız beklenen sezon evreni ve tüm geçmişin eksiksizliği doğrulaması değildir. Kataloglardaki sezon/lig/periyot kimlikleri ve maç içi skor aritmetiği kontrol edildi; ikinci bağımsız sonuç sağlayıcısıyla bütün maçlar çapraz doğrulanmış sayılmaz. Sonuçlarda normal süre ile uzatma ayrı tutulur.

Bu dosyalar **sonradan edinilmiş retrospektif araştırma gözlemleridir**. Gözlem ve ingestion saatleri ayrı tutulur; geçmiş tipoff öncesi veriymiş gibi zaman atanmaz. Kaynak erişimi, model eğitimi için kullanım izni kanıtı değildir: `source_permission=NOT_ESTABLISHED`, `point_in_time_training_eligible=False`. Oyuncu, ilk beş, dakika, sakatlık, rotasyon ve tempo verileri bu sorgularda toplanmadı. Eksik veriler üretilmedi.

## Kodda kapatılan boşluklar

- `season_archive_inventory.py`: ESPN NBA ve resmî EuroLeague normal sezon yerel belgelerinin ayrı native sözleşmeleri. Sezon/lig/UTC/ev-deplasman/FINAL kontrolü, ham belge hash'i, ayrı kaynak saatleri, quarter toplamları ve uzatmanın öncesindeki beraberlik kontrolü. Aynı kanonik maçın farklı sağlayıcı ID alias'ları tek maça iner; aynı takım/başlangıç çakışması ve çelişkili sonuçlar reddedilir. Sağlayıcı namespace'leri körlemesine birleştirilmez. Eksik periyotlar None kalır.
- `season_ledger_audit.py`: SQL JOIN çarpımına dayanmayan, tekil kaynak maçı ve tahmin sürümünü ayrı sayan yerel salt okunur denetim. Aynı maçta 200 sürüm bir bağımsız maça karşılık gelir. Katalog alias'ları da örneklemi büyütmez; çelişkili alias skorları o kaynak maçını karantinaya alır. NBA/ESPN kanıtı EuroLeague doğrulaması olarak kullanılamaz. REGULATION_ONLY, FINAL_WITH_OT ve zaman sınırları ayrı doğrulanır.
- `calibration_safety_gate.py`: yeni denetimi kullanır; dışarıdan pin'lenen kataloglar opsiyoneldir. Threshold yalnızca tamsayı ve en az 2 olabilir. Yeterli aday sayısı bile otomatik eğitimi/terfiyi açmaz. Boş/tekrarlı/desteklenmeyen lig listeleri ve eksik katalog pin'leri fail-closed reddedilir.

Ham JSON içindeki türetilmiş sonuçları değiştirip yeniden hash'lemek yeterli değildir: katalog native kaynaktan yeniden oynatılır. Yerel pin, bağımsız kaynak attestation'ı değildir. Model veya kaynak izinleri bu kodla otomatik onaylanmaz.

## Eşleşmeler ve kalibrasyon

Üretim ledger kopyası bu ortamda yok. Bu nedenle **güncel üretim tahmin–sonuç eşleşmesi bilinmiyor**; eski FAZ dallarının 0 çift raporu güncel main'e taşınmadı. Yerel kopya sağlanmadan raporda sayılar None ve `ledger_not_found` kalır. Gerçek mevcut üretim metrikleri hesaplanmadı; MAE/RMSE/Brier/log-loss/kalibrasyon değeri uydurulmadı.

Main'de `prediction_versions.version_id` isteğin artan numarasıdır, model SHA/sürümü değildir. Mevcut tablo setinde tahminin kanonik takım ID'leri, sezon kökeni, model/source digest'i, özelliklerin tahminden önce erişilebilirlik saatleri ve bağımsız final alım kanıtı yoktur. `main.py` kalıcı ledger yazımını yalnızca NBA dalında yapar; EuroLeague için aynı production kayıt hattı doğrulanmadı. Bu boşluklar giderilmeden kaynak skoru ile eşleşen adaylar bile PIT güvenli, model bazında kalibrasyon örneği sayılmaz.

Yeni rapor `independent_candidate_fixtures`, `source_matched_independent_fixtures`, `candidate_prediction_versions` ve `verified_prematch_fixtures` alanlarını ayırır. Aday eşleşmeler yalnızca kaynak/kayıt tutarlılığını gösterir. Okunamayan DB'de doğrulanmış sayı None'dır; okunabilir eski şemada eksik model/PIT kanıtı nedeniyle doğrulanmış eğitim örneği 0 kalır. Metrikler None, kalibrasyon NOT_ESTABLISHED ve `automatic_model_update_permitted=False` kalır.

Örnek kullanım (yalnızca yerel güvenli kopya ve dışarıdan beklenen pin'ler):

```bash
python calibration_safety_gate.py /workspace/snapshots/ledger.sqlite \
  --nba-catalog /workspace/snapshots/nba-catalog.json \
  --nba-catalog-sha256 EXPECTED_PAYLOAD_SHA256
```

Katalog, `archive_catalog(raw, provider=..., observed_at_utc=..., ingested_at_utc=...)` API'sinin envelope çıktısıdır. Hash'i dosyanın yanından körlemesine güvenilir kabul etmek yerine beklenen pin bağımsız olarak verilmelidir. CLI çıkış 1 kalibrasyonun engelli olduğunu, 2 geçersiz işlem/girdi olduğunu belirtir; engelli durum otomatik model güncellemesi yapmaz.

## Testler ve kalan işler

PR #79 başlangıç testleri: 253/253. 28 yeni deterministik sentetik regresyonla tam küme **281/281**, odaklı grup **31/31** başarılı. İlk odaklı denemede bir sentetik uzatma fixture'ının aynı dict referansını dört çeyrekte paylaşması yanlış ret gerekçesi üretti; fixture ayrı nesnelerle düzeltildi. Son testlerde başarısızlık yoktur. Testler üretim DB'sini kullanmaz. Exact-SHA GitHub Actions sonuçları yeni commit push edildikten sonra taslak PR'da ayrıca doğrulanır.

Öncelikli sonraki işler: izin ve bağımsız sezon evreni kanıtı; NBA için başarısız tarih aralığı yerine mevcut tek-gün toplayıcısıyla sınırlı ve receipt'li backfill; EuroLeague sonuç/detay/oyuncu adaptörleri; model ve PIT kimliklerini append-only yeni kanıt katmanında tutma; kronolojik train/validation/test ayrımı ve challenger/champion değerlendirmesi. Bunlar bu checkpoint'te tamamlanmış değildir. Üretim değişikliği, merge, deploy, scheduler aktivasyonu ve secret işlemi yapılmadı.
