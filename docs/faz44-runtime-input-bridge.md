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
