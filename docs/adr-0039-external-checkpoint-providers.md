# ADR-0039 — Harici checkpoint sağlayıcısı ve bağımsız kurtarma

Tarih: 2026-11-06. Durum: **TEKNİK ÖNERİ; TEDARİK/AKTİVASYON ONAYI YOK**.
Görev: [PR #14 son kabul kapısı](https://github.com/Girayzeynal/zeynal-bot-core/pull/14#issuecomment-6678352052).
Başlangıç: `1c11b1a518d355ce547e4672d5cb92f69f7029eb`.

## Karar

İlk yetkili sentetik denemede referans aday olarak **AWS S3 Standard nesne
depolaması + ayrı yönetilen PostgreSQL pin otoritesi + bağımsız imza güven kökü**
önerilir. Cloudflare R2 maliyet odaklı alternatif adaydır. Bu, kaynak açma,
sağlayıcıya bağlanma veya ücretli hizmet satın alma kararı değildir. Mevcut yetkili
hedef yoktur; `LOCAL_ONLY` ve kapalı harici sözleşme korunur.

Somut yönetilen DB adayı **Amazon RDS for PostgreSQL**, ayrı kontrol hesabında;
signer adayı ayrı güvenlik hesabında **AWS KMS**'dir. Bu üç hesabı aynı üst yönetici
kontrol ediyorsa gerçek idari bağımsızlık varsayılmaz; ayrıca onaylı başka
sağlayıcı/operatör seçilmesi gerekir. RDS ve KMS için ücretsiz hesap/kota
doğrulanmadı. Mevcut yetkili PostgreSQL veya imza altyapısı varsa yeniden
sertifikalandırılması yeni kaynak açmaktan önce değerlendirilir.
[RDS ürün sınırları](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html)
ve [maliyet kalemleri](https://aws.amazon.com/rds/postgresql/pricing/).

Üç düzlem ayrı değerlendirilir: değişmez checkpoint baytları, güncel monoton pin
otoritesi ve imza/UTC doğrulama güveni. Tek bucket, volume veya ortak yönetici
hesabı üçünün bağımsızlığına kanıt değildir. Farklı uygulama isimleri, aynı
volume/host/account kontrolüne dayanıyorsa bağımsız kurtarma sağlamaz.

## Adayların kesin sınırları

| Aday | Sağlayabileceği rol | Kendiliğinden sağlamadığı garanti |
|---|---|---|
| AWS S3 Standard | Koşullu create-once nesneler, exact GET/read-back; nesne düzeyinde güçlü tutarlılık | Birden çok anahtarın veya bucket+DB'nin atomik işlemi; uygulama nesil/chain kuralı; bağımsız imza kökü |
| Cloudflare R2 doğrudan API | Belgelenmiş atomik koşullu Put ve güçlü read-after-write; alternatif checkpoint hedefi | S3 uyumluluğundan türetilen tüm S3 garantileri, çoklu nesne işlemi veya bağımsız pin otoritesi |
| Ayrı PostgreSQL primary | Beklenen generation/digest ile tek satır CAS ve aynı DB içindeki değişmez pin geçmişi | S3 ile dağıtık transaction, yanlış yapılandırılmış WAL/failover altında dayanıklı ACK veya bağımsız güven kökü |
| Fly Volume | Tek Machine'e bağlı yerel SQLite çalışma diski; ayrı yetki verilirse sentetik hedef diski | Paylaşılan object API, otomatik volume replikasyonu, global CAS, bağımsız pin/imza otoritesi |

S3 `If-None-Match: *` ve `If-Match` koşullarını destekler; koşul atlanırsa normal
yazma var olan nesneyi değiştirebilir. IAM/bucket politikası koşulsuz yazmayı ve
silme yollarını da engellemelidir. Versioning tek başına WORM değildir; mevcut
delete-marker/lifecycle davranışı ayrıca denetlenmelidir.
[S3 koşullu yazmalar](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
ve [politika ile zorunlu kılma](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html).

S3 tek anahtarda atomiklik ve güçlü read-after-write belgeler; anahtarlar arası
atomiklik vermez. Dolayısıyla `If-Match` desteği, pin'in generation+parent
kurallarını veya nesne yayınıyla birlikte DB commit'ini ispatlamaz. ETag bir
eşzamanlılık belirtecidir; uygulamanın SHA-256 doğrulamasının yerine geçmez.
[S3 tutarlılık modeli](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel).

R2'nin güncel belgesi koşullu PUT'un commit sırasında atomik değerlendirilmesini
ve güçlü okumaları açıklar. Buna rağmen timeout sonrası negatif okuma, önceki
isteğin daha sonra commit olamayacağını kanıtlamaz. Cache'li public/custom-domain
yolu yerine doğrudan API seçilmelidir; listeleme hiçbir zaman trusted latest
pin kaynağı değildir. Bunlar doküman bulgularıdır, bizim adaptörümüzün sertifikası
değildir. [R2 tutarlılık ve koşullu yazma modeli](https://developers.cloudflare.com/r2/reference/consistency/).

Fly Volume aynı fiziksel sunucuya bağlı yerel NVMe saklamadır; volume'lar arası
replikasyon uygulamaya aittir. Bir volume üzerindeki SQLite dosya kilidi farklı
makinelerde global kilit değildir. Snapshot alınabilmesi tek başına son
checkpoint'in kurtarılabildiğini ispatlamaz.
[Fly volume modeli](https://docs.fly.io/volumes/overview) ve
[uygulama dayanıklılığı](https://fly.io/docs/apps/app-availability/).

## Önerilen pin kontrol düzlemi

Bu bölüm tasarımdır; SQL, DB veya servis kurulmadı. Pin servisi yetkili primary
üzerinde ledger başına benzersiz head satırını işler. `SELECT FOR UPDATE` veya
beklenen generation/digest koşullu `UPDATE ... RETURNING` aynı transaction'da
head güncellemesi ve append-only geçmiş kaydıyla birleştirilir. Yeni nesil tam
olarak `old+1`, parent digest eski pin olmalıdır. Aynı nesilde farklı digest
benzersizlik/CAS ile reddedilir. Head okumaları gecikmeli replica'ya yönlendirilmez.
Serialization failure veya belirsiz commit için force-update yapılmaz; aynı
candidate digest ile primary üzerinden denetim/yeniden deneme gerekir.
[PostgreSQL transaction kilitleri](https://www.postgresql.org/docs/current/explicit-locking.html).

Dayanıklılık için fsync, WAL, synchronous commit ve failover/RPO politikasının
somut kurulumu incelenmelidir. Sadece “PostgreSQL kullanılıyor” demek ACK'nin
güç kesintisi/failover sonrasında korunduğunu kanıtlamaz. Eski DB yedeğine dönüşü
tespit edecek son generation/digest tanığı, o DB'nin rollback alanı dışında
tutulmalıdır. [WAL ayarları](https://www.postgresql.org/docs/current/runtime-config-wal.html)
ve [disk/cache dayanıklılığı](https://www.postgresql.org/docs/current/wal-reliability.html).

Yayın sırası: bundle → manifest → commit marker → her nesnenin exact read-back'i
→ imzalı candidate pin → pin servisi CAS/read-back. S3 ve DB arasında transaction
yoktur. Hata halinde referanssız nesne kalabilir; eksik checkpoint'e işaret eden
pin yayımlanamaz. Otomatik silme/GC bu hazırlığın kapsamında değildir. Yetkili
signer bir candidate'ı imzalayabilir; o imza candidate'ın CAS yarışını kazandığı
anlamına gelmez.

## İmza ve bağımsız kök

Öneri: collector'dan, bucket yöneticisinden ve pin DB yönetiminden ayrı imza
servisi/operatörü. Asimetrik anahtarın public fingerprint'i, issuer, key ID ve
algoritma checkpoint dışında önceden onaylanır. İmza amacı, canonical bytes,
manifest/SHA, ledger, generation, parent, UTC ve request challenge bağları zorunlu.
Verifier anahtar/algoritmayı payload'dan seçmez. Şifreleme anahtarı, ETag veya
yerel hash imza kökü değildir. Bir imza da gerçek runtime/volume ayrılığını tek
başına kanıtlamaz.

AWS KMS ayrı bir güvenlik hesabında aday olabilir; public key ile servis dışında
doğrulama desteklenir. Verifier, doğru key/algorithm/message formatını bağımsız
olarak sabitlemelidir. Bu çalışma KMS/anahtar kurmadı, secret oluşturmadı ve
kriptografik verifier uygulamadı.
[KMS public-key işlemleri](https://docs.aws.amazon.com/kms/latest/developerguide/offline-public-key.html).

## En az izinler, bölge ve ağ

| Kimlik | Tasarlanan en az yetki | Yasak/ayrı tutulacak yetki |
|---|---|---|
| Nesne yayımlayıcı | Sadece onaylı sentetik prefix için koşullu Put ve read-back Get | Delete, koşulsuz overwrite, prod prefix, bucket/IAM yönetimi |
| Temiz restore runtime | Sabit pinin nesne/manifest/commit anahtarları için Get | Put/Delete/List, kaynak workspace, prod DB/volume, Telegram token |
| Pin istemcisi | Yetkili serviste current ve expected-head CAS | Doğrudan serbest UPDATE/DELETE/DDL, eski head'i zorla yazma |
| Signer | Onaylı claim'leri imzalayan bağımsız servis rolü | Collector'a private key/sign-anything yetkisi, prod secret erişimi |
| Verifier | Önceden sabitlenmiş public trust registry ve bağımsız UTC kanalı | Payload'dan root yükleme, private key veya source disk ihtiyacı |

S3 için ilk bölge adayı `eu-west-1`dir; bu bir ölçülmüş latency veya veri ikameti
onayı değildir. EU kontrol düzlemi ve signer'ın somut yerleşimi ayrıca seçilmeli;
aynı failure domain ve ortak yönetici riski kayda geçmelidir. R2 için location
hint garanti sayılmaz; gerekli ise jurisdiction ve hesap uygunluğu ayrıca
onaylanmalıdır. [R2 yerleşim sınırları](https://developers.cloudflare.com/r2/reference/data-location/).

Yalnızca onaylı TLS object, pin, signer ve UTC uçlarına çıkış planlanır; public
cache, proxy cache ve gizli fallback yoktur. Bağımsız hedef kaynak host/volume'a
erişemez. Bağlantı reddi/403/429/timeout, daha gevşek hedefe veya eski pin'e geçme
nedeni değildir. Uygulama audit hook'u OS/network izolasyonunun yerine geçmez.

## Fiyat uydurmadan maliyet değerlendirmesi

Hesap, bölge ve trafik hacmi seçilmeden sabit tutar veya “tamamen ücretsiz”
taahhüdü verilmez. İlk tahmin girdileri: günde checkpoint sayısı, ortalama bundle
boyutu, retention günleri, restore/yeniden deneme sayısı ve log hacmi.

- Nesne hacmi yaklaşık `günlük checkpoint × bundle boyutu × retention günü`dür;
  sürümleme/lock/log kopyaları eklenir. Put/Get, read-back, koşullu retry ve
  multipart sayıları ayrıca ölçülür.
- S3'te storage/request/transfer kalemleri; R2'de storage ve operasyon sınıfları
  değerlendirilir. R2'nin doğrudan egress fiyat politikası toplam sistemin
  ücretsiz olduğunu göstermez; kaynak runtime transferi ayrıca maliyet doğurabilir.
  [S3 fiyat kalemleri](https://aws.amazon.com/s3/pricing/) ve
  [R2 fiyat kalemleri](https://developers.cloudflare.com/r2/pricing/).
- DB compute/storage/WAL/backup/HA ve bölge trafiği; signer key/işlem/audit
  kalemleri ayrı teklif gerektirir. Fly Machine/volume/snapshot ayrıca ücret
  doğurabilir. Ücretsiz kota/uygun hesap bulunduğu varsayılmaz.
  [KMS fiyatlandırma](https://aws.amazon.com/kms/pricing/) ve
  [Fly fiyatlandırma](https://fly.io/docs/about/pricing/).

## Tehditler ve temiz iki-runtime kabul kriterleri

Kabul için somut sağlayıcı sürümü/konfigürasyonu ve iki gerçekten ayrık runtime
gerekir. Aşağıdakiler gelecekteki canlı deney kapılarıdır; şu an **NOT_VERIFIED**:

1. Aynı anahtara yarışan iki koşullu yazıcıdan yalnızca biri oluşturmalı; diğer
   aynı baytları görmeli, farklı baytlar conflict olmalı. Streaming limit, gerçek
   decode edilmiş ağ akışında uygulanmalı; Content-Length/ETag yeterli değildir.
2. Nesneler commit-last yayımlanmalı. Partial upload, bozuk/truncated bundle,
   kayıp ACK, 403/429 ve partition tamamlanmış checkpoint üretmemeli. Negatif
   okumadan sonra in-flight commit ihtimali UNKNOWN kalmalı.
3. Pin otoritesi farklı süreç/makine istekleriyle CAS/fork/rollback testini
   geçmeli; DB restart/failover ve eski backup testi dış high-water tanığıyla
   denetlenmeli. Multi-object/DB atomikliği varsayılmamalı.
4. Public root ayrı kanaldan sabitlenmeli; yanlış issuer, root, purpose, UTC
   nonce, skew ve monotonic lease reddedilmeli. Signer ve storage yöneticisinin
   aynı olması bağımsızlık kanıtı sayılmamalı.
5. Hedef farklı runtime/run/filesystem/storage kimliğine sahip olmalı; source
   workspace/volume erişimi kapalıyken yalnızca onaylı sentetik paketi kurtarmalı.
   Aynı hostta iki dizin/süreç bu ölçüt değildir.
6. Gerçek restore DB SHA-256, SQLite integrity, ledger ID ve audit hash'i bağımsız
   gözlemle eşleşmeli. Kaynak ortadan kalktıktan sonra kalıcı hedeften geri yükleme
   tekrar sınanmalı; sadece self-reported PERSISTENT veya farklı JSON ID'leri yetmez.
7. Deneme başına tek değişmez sonuç, dışarıda tutulan digest ve UTC/platform
   kanıtları bulunmalı. Kayıp ACK/expiry sonrası yeni başarı uydurulamaz.

## Offline test düzeneği ve yetkilendirme listesi

`python -I tests/faz39_offline_acceptance.py`, yalnızca bellekteki sahte
provider/otorite/attestor ile 11 kontrol grubu çalıştırır. 9 sabit `--fault`
seçeneği bozuk implementasyonları sınar. CLI endpoint, token, DB, output veya
deploy parametresi almaz; socket, child process ve production importlarını
audit hook ile reddeder. Üretim ve gerçek veri dosyaları kullanılmaz.

Başarı `OFFLINE_ACCEPTANCE_PASS` olur; **VERIFIED değildir**. Sahte sağlayıcıların
olumlu VERIFIED durumları reddedilir; gerçek harici kalıcılık, imza doğrulaması ve
bağımsız Cloud kurtarması false/NOT_VERIFIED kalır. Existing SQLite/WAL ve sandbox
regresyonları korunur. Bu belge/tüm testlerin geçmesi canlı deneye izin vermez.

Canlı deney öncesi operatörün ayrı onaylaması gereken somut bilgiler:

- [ ] Sağlayıcı, hesap/owner, namespace/prefix ve kesin region/jurisdiction.
- [ ] Sadece SYNTHETIC_TEST veri, sabit retention, maliyet tavanı ve cleanup sınırı.
- [ ] Birbirinden ve üretimden ayrık source/target runtime/volume kimlikleri.
- [ ] Salt gerekli object/pin/signer/UTC izinleri; production secret erişimi yok.
- [ ] Bağımsız public root fingerprint/issuer ve dış high-water saklama hedefi.
- [ ] Provider capability kanıtı, immutable sonuç digest'inin bağımsız saklanması.
- [ ] Restart/failover/source erişim kesme deneyinin kapsamı ve durdurma koşulları.
- [ ] Kaynak oluşturma, anahtar işlemi ve olası ücretler için açık yetki.

**Bu kutular onaylanmış değildir.** Şu görev sadece doküman ve offline testtir;
PR taslak, `LOCAL_ONLY`, gerçek yeni prospektif kayıt sayısı sıfırdır.
