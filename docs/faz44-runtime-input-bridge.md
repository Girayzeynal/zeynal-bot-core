# FAZ44 — çalışan model kanıtı ve geliştirme veri bağlantısı

Başlangıç PR #22 / `e195fcccb4a9bb0c8eab3eefa99d486a3d5e91a3`; push 42246126702 ve PR 42246136747 unit-tests/docker-build başarılı doğrulandı. Mevcut modeller, araştırma/prospektif kayıtlar ve FAZ13–43 kanıtları korunur. Yeni dal `feature/faz44-runtime-input-bridge-20261106`.

## Aşama 1 — model yürütme ve son gönderim kontrolleri

Dört yeni negatif regresyon eski davranışta başarısız oldu:

- Non-synthetic snapshot, yalnızca biçimi geçerli olan uydurma Git/model manifest'iyle sayısal çıktı üretebiliyordu.
- Kayıttan sonra servisin DEVELOPMENT modu değiştiğinde callback cevap verebiliyordu.
- Sentetik mod kapatıldıktan sonra cache'deki sentetik snapshot kullanılabiliyordu.
- Takvim capture anında taze olsa da teslim anında 300 saniyelik sınırı aşabiliyordu.

Non-synthetic sayısal çıktı için artık çalışan temiz feature HEAD'i, commit zamanı ve tüm model modülü SHA'ları hesap öncesinde ve sonrasında eşleşmelidir. Sonradan eski snapshot denetlenirken bugünün koduna yeniden bağlanmaz; orijinal kayıt/tahmin değiştirilmez. Kaynak izni yoksa önceki izin kapısı ABSTAIN vermeye devam eder; bu özellik kullanım izni veya CI/provider attestation üretmez.

Son gönderimde uygulama ve servis modu, sentetik kullanım izni, kaynak kullanım izni/expiry, UTC saatinin snapshot'tan geriye gitmemesi, maç başlangıcı, cutoff ve takvim tazeliği denetlenir. Maç başladıysa ALREADY_STARTED ret nedeni, diğer eskime nedenlerinden önce gelir. Bu öncelik değişikliğini eski regresyon yakaladı; ret kontrolleri gevşetilmeden düzeltildi.

Başlangıç 946/946. Son yerel tam regresyon **954/954**, bu aşamada **8 yeni test**; ilgili odaklı grup 53/53. İlk dört negatif test önce başarısız oldu; orijinal snapshot'ların daha sonra okunabilmesi ayrıca test edildi. Pozitif sahte kaynak/izin/model senaryoları yalnızca açıkça etiketli sentetik testlerdir. Gerçek sayısal tahmin veya prospektif kayıt 0; kaynak politikaları UNKNOWN kalır.

Kanıt: docs/evidence/faz44-runtime-20261106.json. Her yeni commit için exact SHA push ve PR CI ayrıca doğrulanır. Main merge, Fly.io/Telegram production, secret/ücretli kaynak veya gerçek scheduler/storage etkinleştirme yok.

## Aşama 2 — salt okunur arşivden gerçek geliştirme girdisi

`faz44_inputs.py`, FAZ40 arşiv yükleyicilerini, FAZ41 capture/replay doğrulamasını ve FAZ42 takvim/manifest kodunu kullanır. FAZ43 `/analyze` geliştirme CLI'si hem eski sabit paketleri hem yeni indeksli paketleri okuyabilir. Üretim `main.py`, Telegram polling/webhook veya üretim zamanlayıcısı başlatılmaz.

Her kaynak ve takvim belgesi SHA ile bir kez saklanır. Lig/TSİ günü bölümleri kaynak SHA'larına referans verir; başka lig, gün, sezon veya sentetik/gerçek karışımı reddedilir. Belgeler arasındaki aynı sağlayıcı maç kimliği ve aynı takım/başlangıç saati çakışmaları paketi reddeder. Takvim alınamadığında veya kısmen hata verdiğinde boş ve başarılı takvim sonucu üretilmez. Takvim yeniliği tahmin sırasında ayrıca mevcut 300 saniyelik kapıdan geçer.

Arşivden türetilen yeni gözlemlerde özgün kaynak gözlem zamanı korunur; ingestion ve materialization bugünün gerçek saatidir. `_faz44_derivation` özgün üst kayıt SHA'sını ve zamanını taşır. Bunlar eski maç öncesinde varmış gibi etiketlenmez; tarihsel walk-forward için PIT uygunluğu kazandırmaz. Mevcut dosyaların hash'leri okumadan önce ve sonra karşılaştırılır.

Gerçek dosyaların salt okunur türetim kontrolünde **77 NBA, 2 EuroLeague, 2 EuroCup = 81 ayrı maç** bulundu; 32 yeniden gözlem birleştirildi. EL/EC katalog satırları periyot/oyuncu örneği sayılmadı. Bu sayı eğitim uygunluğu veya kullanım izni anlamına gelmez.

Yeni paket yalnızca `/tmp` veya `/workspace/scratch` altında `faz44-inputs-*.json` adıyla yayımlanır: 0600 geçici dosya, dosya fsync, exclusive hard-link ve dizin fsync. Aynı içerik idempotent; farklı içerik veya symlink üzerine yazılmaz. Eşzamanlı iki yayın yalnızca bir tam dosya oluşturur. Yerel bir input dosyasıdır; kalıcı prospektif ledger veya bağımsız Cloud kurtarma kanıtı değildir. fsync/link hatasında CLI yayını doğrulanmış göstermez.

### Açık kaynak politikası

`faz44_policy.py --template` mevcut FAZ41 **UNKNOWN** kayıtlarını üretir. Kullanım izni kendiliğinden verilmez. İsteğe bağlı politika belgesi için ayrı trusted SHA, açık operatör inceleme kaydı, HTTPS belge referansı/digest, inceleme ve bitiş zamanı ve yalnızca `DEVELOPMENT_RESEARCH_ONLY` kapsamı zorunludur. Bu belge sağlayıcı imzası veya hukukî lisans doğrulaması değildir. Gerçek izin dokümanı incelenmeden PERMITTED yapılmamalıdır.

Yerleşik sağlayıcının host/sahip/path/veri türü/kanıt seviyesi değiştirilemez. Ek kaynaklar yalnızca ikincil haber/yorum olabilir; resmî istatistik/ilk beş kanıtına yükseltilemez. Yerel/IP hedefleri, çelişkili sahiplik, süresi dolmuş veya gelecekteki inceleme ve gizli onay makbuzları reddedilir. Gerçek izin politikası oluşturulmadı; mevcut kaynak izinleri UNKNOWN.

### Geliştirme prosedürü

Temiz feature checkout'unda, gerçek gün kullanılarak (iki komutta da aynı ayrı trusted pin):

```bash
python -m faz44_inputs --nba-database /path/to/research.sqlite \
  --euro-evidence docs/evidence/euroleague-eurocup-audit-20261104.json \
  --nba-refresh docs/evidence/master-nba-refresh-20261106.json \
  --day YYYY-MM-DD --days 2 --live-schedule \
  --output /workspace/scratch/faz44-inputs-session.json

python -m faz43_development --day YYYY-MM-DD \
  --inputs /workspace/scratch/faz44-inputs-session.json \
  --trusted-bundle-sha256 PRINTED_PAYLOAD_SHA256
```

Canlı takvim okumaları sadece açık `--live-schedule` ile; varsayılan sıfır ağ isteğidir. İzin yoksa mevcut ABSTAIN kapısı korunur. İsteğe bağlı incelenmiş politika kullanılacaksa iki komuta da `--source-policy` ve `--trusted-policy-sha256` birlikte verilmelidir. İzin değişikliğinde eski paket yeni politikaya yeniden bağlanmaz; yeni derivation gerekir. Yeni HEAD sonrasında sayısal üretim için paket yeniden oluşturulmalıdır. Gerçek scheduler/storage açılmaz; üretim botuna paket yüklenmez.

Testler: aşama 1 **954/954**; aşama 2'nin yeni odaklı grubu **25/25**. Yeni testler aynı paket üzerinde eşzamanlı yayın, disk doluluğu, izin hatası, kaynak dosyasının korunması, eski paket uyumu, yanlış pin/politika/gün/lig, belgeler arası kimlik çakışması ve kısmi takvim hatası retlerini kapsar. Sayısal pozitif testler sentetiktir. Tam regresyon sonucu ve exact SHA CI ayrı kanıt dosyasında verilir.

## Gerçek geliştirme denemesi ve devam noktası

Kod checkpoint'i `dbae079eb9b6afbfeba20114c4b658fa1b26612a`: yerel **979/979**, push [42251567948](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42251567948) ve PR [42251577480](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42251577480) unit-tests/docker-build başarılı. Her iki unit log'u 979 test / OK içeriyor. PR #23 taslak ve tabanı PR #22 dalıdır; main ile birleştirme yapılmadı.

Gerçek 5 HTTP takvim isteği 5 belge üretti: ESPN üç tarih, EuroLeague ve EuroCup sezon katalogları. Katalogdaki gelecekteki fikstürler, tamamlanmış/periyot/oyuncu örneği değildir. Yeni yerel input paketinde 81 tarihsel maç ve 6 lig/gün bölümü bulunuyor. `/analyze` geliştirme CLI'si iki gün için denendi:

| TSİ gün | Doğrulanabilir takvim eşleşmesi | Sonuç | Yeni prospektif kayıt |
|---|---:|---|---:|
| 2026-11-06 | 4 EuroLeague | 4 × ABSTAIN: SCHEDULE_USAGE_NOT_ESTABLISHED | 0 |
| 2026-11-07 | 9 NBA | 9 × ABSTAIN: SCHEDULE_USAGE_NOT_ESTABLISHED | 0 |

Paket payload SHA: `243c7b571128ec55fd8172b02ff29119847687a754ac9294afbc11589f176f1e`. Dosya SHA ve kaynak HTTP zamanları `docs/evidence/faz44-real-input-smoke-20261106.json` içinde. Aynı paketin ikinci yayını `created=False`; dosya hash'i sabit. SQLite salt okunur integrity_check `ok`; kaynak SQLite SHA `43adc6de12bc065e38b666dad8ba2cd9a48c5786c1185b396de5a37ebe4dd002`. Başlangıç commit'indeki 72 eski kanıt dosyası byte düzeyinde değişmedi.

Bu input köprüsünün kompakt skor gözlemlerinde 77/2/2 maçın periyotları var; oyuncu dakika, doğrulanmış PBP, maç öncesi kadro ve beşli/rotasyon gözlemi **0**. Önceki ayrı oyuncu/katalog denetimlerinin sayıları buraya eklenmedi veya silinmedi. Kaynak izni uygun eğitim örneği 0; gerçek walk-forward/kalibrasyon veya güncel modele ait MAE/RMSE/Brier/log-loss üretilmedi. Testteki sayısal başarı gerçek doğruluk değildir.

Kalan işler bağımlılık sırasıyla:

1. Gerçek kaynak izin belgelerini incelemek ve dışarıdan güvenilen pin ile geliştime amaçlı politikaya bağlamak. UNKNOWN varsayılanını korumak; izin belgesi yoksa ABSTAIN.
2. Kompakt skor arşivinden ayrı oyuncu/PBP/ilk beş gözlemlerini orijinal gözlem/ingestion/materialization zamanlarıyla bağlamak. Yeni alınan veriyi eski tahmin cutoff'larında kullanılabilir saymamak. NBA resmî kaynak erişimi/ESPN çapraz denetimi ve haber izinleri henüz tamamlanmış değil.
3. İzinli, kronolojik ve yeterli takım geçmişi oluşunca mevcut 10.000+ MC / walk-forward / ölçüm katmanını aynı maç setleriyle çalıştırmak; calib ve model karşılaştırmalarını sürüm bazında ayırmak.
4. Gerçek scheduler ve kalıcı storage için ayrı yetki ve bağımsız Cloud geri yükleme kanıtı sağlanmadan günlük prospektif sistem hazır ilan edilmemeli. Mevcut günlük komut yalnızca geliştirme planı üretir; gerçek ledger'a yazmaz.

Yerel paket oturumlar arası kalıcılık garantisi vermez. İkinci Cloud runtime testi, harici storage, production zamanlayıcı/bot entegrasyonu doğrulanmadı ve etkinleştirilmedi. Sonraki oturum temiz yeni HEAD üzerinde taze input üretmelidir; bu dosyayı tekrar kullanarak yeni HEAD veya güncel kaynak tazeliği kanıtı üretmiş saymamalıdır. Tüm master görev tamamlanmış değildir; bu aşama denetlenebilir bir checkpoint'tir.
