# FAZ42 — tarihsel ve prospektif doğrulama

Issue #20; PR #19 `df6393e875bd9f809e6ecb041d889e5d682fce9f` tabanlı `feature/faz42-dual-track-20261106` dalı. FAZ41 yeniden yazılmadı. Başlangıç 853/853 test; PR #19 push 42220681781 ve PR 42220690476 unit-tests/docker-build başarılı doğrulandı.

## Hat A — başlangıç iş yükünün yaklaşık %60'ı

`faz42_history.py`, FAZ41 sağlayıcı replay/izin politikasını ve FAZ40 projeksiyon/Monte Carlo/metrik motorunu kullanır. Sezon ve kanonik maç kimliğine göre gözlem, özgün maç, periyot, oyuncu dakika ve eksik alan sayıları ayrılır. Aynı kaynağın tekrar gözlenmesi veya farklı sağlayıcı kimliği örneklem sayısını artırmaz. Çelişkili final/kimlik ve aynı takım/başlangıç çakışması reddedilir. TBL/CBA/JAPAN/LEGA mevcut adlandırma desteğine rağmen bu hatta doğrulanmış arşiv adaptörü yoktur; NO_VERIFIED_ADAPTER ile ABSTAIN edilir.

Walk-forward'da açık UTC train/validation/test sınırları vardır; eşit başlangıç zamanları aynı bölümde kalır. Model eğitimi veya test üstünde parametre araması yapılmaz. Her tahminde ham iddia replay'i, yayın varsa yayın zamanı, gözlem, ingestion ve materialization kesitten önce olmalıdır. Bugün oluşturulan FAZ40 wrapper'ı ancak özgün v2 kanıtın dört saat kontrolünden geçmesinden sonra araştırma hesabına verilir; bu, geçmiş tahmini gerçekten o gün kaydetmiş olmak anlamına gelmez. Kendi/sonraki maç sonuçları girdi olamaz. İzin/örnek/tazelik yetersizse ABSTAIN.

NBA.com CDN kaynağı FAZ41 düzeyinde doğrulanabilse de FAZ40 tarihsel projeksiyonu için ESPN ham arşiv adaptörü gerekir; NBA.com verisi ESPN cevabıymış gibi dönüştürülmez. Bağımsız kaynak mutabakatı elde edildiği iddia edilmez.

MAE/RMSE ev/deplasman/toplam/fark için 1Q–4Q, 1H/2H ve normal süre bazında ayrılır. Maç seviyesinde üç olaylı normal süre Brier/log-loss/kalibrasyon hesapları FAZ40'tan gelir; çeyrek olasılığı uydurulmaz. Validation ve test örnekleri ayrı kalır; varsayılan en az 30 uygun maç olmadan toplu metrik null'dır. Bu eşik güvenilirlik garantisi değildir.

`faz42_audit.py`, mevcut salt okunur FAZ40 yükleyicilerini kullanır; ledger veya SQLite yazmaz. Yerel eski yanıtlar yeni v2 nesnesine alınırken ingestion/materialization bugünkü gerçek saattir. Eski gözlem veya veri tabanı ingestion saati, yeni nesnenin oluşturulma zamanı gibi gösterilmez. Kesit saati uydurulmadan gerçek saat tick'i beklenir. Kaynak dosyaların başta/sonda hash'leri kontrol edilir.

| Lig | Özgün maç / periyot | Dakika kanıtlı maç | Dakika alanlı oyuncu satırı | İzni uygun maç |
|---|---:|---:|---:|---:|
| NBA | 75 / 75 | 1 | 19 | 0 |
| EuroLeague | 2 / 2 | 1 | 24 | 0 |
| EuroCup | 2 / 2 | 1 | 21 | 0 |
| TBL/CBA/JAPAN/LEGA | Doğrulanmış adaptör yok | 0 | 0 | 0 |

Bunlar yerel gerçek arşiv ve önceki oturumun unsigned kaynak manifestlerinden yeniden kontrol edilen kapsam sayılarıdır; yeni canlı API erişim testi değildir. Doğrulanmış play-by-play, lineup stint ve prematch kadro sayısı 0. ESPN'in 26 oyuncu satırının 19'unda dakika vardır; 26'sı oynadı denmez. Tüm kaynak izinleri UNKNOWN kaldı. Validation/test uygun tahmin sayıları 0, tüm gerçek toplu metrikler null. FAZ40'ın önceki source-clock araştırma sayısı yeni PIT uygunluğu olarak kullanılmadı.

İlk aşama yerel test: 865/865, 12 yeni deterministik test. Sentetik testte yeterli örnek/izin verildiğinde periyot ve olasılık metrikleri hesaplanır; gerçek performans diye sunulmaz. Kanıt: `docs/evidence/faz42-track-a-20261106.json`. CI exact commit SHA ile push sonrası doğrulanır.

```sh
python -m faz42_audit /path/to/static-research.sqlite \
  --euro-evidence docs/evidence/euroleague-eurocup-audit-20261104.json \
  --train-end-utc 1793491200 --validation-end-utc 1793664000
```

## Hat B — yaklaşık %40, geliştirme ve dry-run

Issue #20'nin kayıt saklama/zamanlayıcı için ayrı onay sınırı korunur. Gerçek kalıcı ledger veya üretim zamanlayıcısı bu çalışmada etkinleştirilmez. Yerel sentetik test ve ağa açıkça izin verilen salt okunur discovery dry-run, gerçek prospektif performansından ayrı raporlanacaktır. Özgün FAZ24/FAZ29 ve FAZ41 kanıtları değişmez; main/Fly.io/Telegram/secrets/ücretli servis işlemi yoktur.

### Hat B uygulaması

`faz42_schedule.py`, NBA için mevcut FAZ33 season/scheduled parser'ını; EuroLeague/EuroCup için resmi fixture parser'ını kullanır. Kanonik tekilleştirme, sağlayıcı alias'ları, aynı takım/başlangıç çakışması, tam katalog, kaynak endpoint'i, izin ve tazelik denetlenir. UTC ve Europe/Istanbul dönüşümü tarih değişimini açıkça gösterir. Sadece takvim keşfi yapılması tahmin veya kullanım izni değildir.

`faz42_snapshot.py`, 1Q–4Q, 1H/2H, takım toplamları, toplam sayı ve farkı mevcut FAZ40 referansından alır. Simülasyon en az 10.000, tohum ve model sürümü açıktır. Model manifest'i temiz feature dalındaki Git SHA'sına ve kod dosyalarının SHA-256 değerlerine bağlanır; hash üretirken HEAD değişirse reddedilir. Cutoff, gerçek oluşturulma saati, kaynakların digest'leri ve yalnızca gerçekten kullanılan dondurulmuş girdiler kaydedilir. İzin/eksik PIT geçmişi/eski takvim/başlangıç veya üretim süresi aşımı ABSTAIN'dir. Ham girdilerden yeniden hesaplama sadece sentetik ilk kayıt kapısında yapılır; sonradan sonuç denetimi özgün tahmini değiştirmez veya yeniden üretmez.

Varsayılan gerçek kullanım **UNPERSISTED_DRY_RUN / NOT_ACTIVATED**'dır. `faz42_test_store.py` yalnızca `/tmp/faz42-test-*` gibi izole sentetik dizinlerde, PredictionLedger bağlantısı üzerine ayrı FAZ42 tabloları açabilir. Gerçek kayıt modu yoktur. Var olan üretim/legacy DB yolları reddedilir; eski prediction/outcome tabloları doldurulmaz. Tek transaction, benzersiz kanonik maç anahtarı, UPDATE/DELETE/REPLACE retleri, tekrar çalıştırma, yeniden açma, yarış ve SQLite kilidi test edilir. Son kontrol SQL'den sonra başlangıç veya üretim süresi aşıldığını görürse rollback edilir. Bu sentetik güvenlik deneyi gerçek disk kalıcılığı veya production zamanlama garantisi değildir.

Final sonuçlar ayrı tabloda özgün snapshot SHA'sıyla eşleşir. Final olmayan, farklı takım/başlangıç veya çelişkili ikinci sonuç reddedilir. Normal süre/uzatma skorları ayrı tutulur; REGULATION_ONLY tahmininin toplam/fark ve üç olaylı olasılık hatası normal süre sonucuyla hesaplanır. Küçük örneklemde toplu metrik null, periyot hataları tekil kayıt düzeyindedir. Gerçek tahmin/sonuç çifti oluştuğu veya model eğitildiği iddia edilmez.

`faz42_dry_run.py` varsayılan olarak ağa bağlanmaz; `--live-discovery` ile yalnızca üç ESPN takvim günü ve iki resmi EuroLeague/EuroCup kataloğunu okur, önümüzdeki 48 saati kanonik tekilleştirir. Zamanlayıcı veya gerçek storage başlatmaz. Kaynak izni UNKNOWN kalırsa tahmin ABSTAIN olur. API 403/429 ve ağ/yanıt hataları başarı gibi sunulmaz. Sistem UTC epoch kullanır; bağımsız UTC/kaynak attestation yapılmadı.

### Hat B test kanıtı ve CI

Hat A `ca9d0d6b22b62fe243d481699f764c8dd434e382` için push 42223738445 ve PR 42223787921 unit-tests/docker-build başarılı; CI günlükleri 865/OK.

Hat B ile yerel tam regresyon **888/888**, odaklı FAZ42 grubu **35/35**; başlangıca göre 35 yeni test. Üç testte dört ret açığı önce yeniden üretildi: yanlış kaynak endpoint'i, bilinmeyen doğruluk alanı, uydurma kalibrasyon etiketi ve kullanılmayan cross-league kaynağın model girdisi diye sunulması. Kaynak/şema/izin ve model replay kontrolleriyle düzeltildi. Bu testler sentetiktir. Gerçek kalıcı ledger veya scheduler için Issue #20'deki ayrı onay şartı geçerlidir; mevcut çalışmada bunlar etkinleştirilmedi.

```sh
python -m unittest discover -s tests -v
python -m faz42_dry_run                  # ağ ve kayıt yok
python -m faz42_dry_run --live-discovery # sadece opt-in salt okunur discovery
```

Sonraki aşama: kaynak izinlerini ve zaman kanıtlarını doğrulamak, diğer ligler için gerçek adaptörler edinmek, oyuncu/PBP/lineup kapsamını artırmak. Gerçek kayıt saklama hedefi ve operasyonel zamanlayıcı incelenip ayrıca onaylanmadan üretim pilotu etkinleştirilmez. Kalibrasyon için yeterli izinli/PIT güvenli örnek ve ayrı kronolojik test dönemi gerekir. Tek maç veya bu küçük arşiv üzerinden katsayı optimizasyonu yapılmadı.
