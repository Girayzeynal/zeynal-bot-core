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
