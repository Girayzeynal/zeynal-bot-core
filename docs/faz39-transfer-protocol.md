# FAZ39: sağlayıcıdan bağımsız aktarım ve WAL kurtarması

`faz39_transfer.py`, mevcut `faz39_recovery.snapshot/restore` doğrulamasını
kullanır. Yerel yedekleme API'si ve örnek collector konfigürasyonu değişmez:

```json
{"mode":"LOCAL_ONLY","external_target":null,"upload_enabled":false}
```

Zamanlayıcıya veya Telegram/Fly.io akışına entegrasyon yoktur. Gerçek bir uzak
sağlayıcı adaptörü, kimlik bilgisi veya harici hedef yapılandırılmadı.

## Protokol

`ObjectStore` adaptör sözleşmesi iki işlem ister: boyutu sınırlandırılmış
`read(key, maximum_bytes)` ve atomik, üzerine yazmayan
`put_if_absent(key, bytes)`. Bu sözleşmeyi ihlal eden bir sağlayıcı güvenli
sayılmaz; her gerçek sağlayıcı ayrıca sınanmalıdır. Hazır referans adaptör
`DirectoryStore`, yalnızca yerel dosya sisteminde çalışır. Ağ SDK'sı, ortamdan
anahtar keşfi, otomatik sağlayıcı yükleme veya gizli anahtar kullanımı yoktur.

Yayın sırası:

1. `objects/BUNDLE_SHA256.tar.gz`: mevcut denetlenmiş SQLite kurtarma paketi.
2. `manifests/MANIFEST_SHA256.json`: deterministik aktarım manifesti.
3. `commits/MANIFEST_SHA256.json`: **en son** oluşturulan tamamlama kaydı.

Her nesne, yazım sonrasında aynı anahtardan geri okunup beklenen baytlarla
karşılaştırılır. Aynı paket aynı manifest kimliğini üretir. Aynı anda çalışan
iki yayımlayıcı tek tamamlama nesnesi oluşturabilir; diğeri `ALREADY_EXPORTED`
döndürür. Var olan farklı baytlar değiştirilmez. Kesinti, henüz tamamlanmamış
nesneler bırakabilir; bunlar commit marker olmadan içe aktarılamaz. Aynı
paketle yeniden deneme güvenlidir. Otomatik silme/üzerine yazma yapılmaz.

Manifest schema v1 şunları bağlar:

| Alan | Doğrulama |
|---|---|
| `protocol`, `schema_version` | Sabit protokol ve desteklenen tamsayı sürüm |
| `source_commit` | İç bundle manifestindeki 40 haneli kaynak SHA |
| `bundle` | SHA-256, tam bayt uzunluğu ve içerikten türetilmiş nesne anahtarı |
| `files` | İç manifest ve SQLite için ayrı SHA-256 ve tamsayı dosya uzunlukları |
| `ledger` | Kullanım modu, değişmez ledger UUID ve FAZ39 audit özeti hash'i |

`source_commit`, paketin kaynak sürümüdür; geçmiş tahminlerin kendi model
SHA'ları SQLite içinde özgün biçimde korunur. Sentetik veri `PROSPECTIVE` diye
yeniden etiketlenemez. JSON yinelenen anahtarları ve sonlu olmayan sayıları
reddeder. Nesne anahtarları dosya yolu enjeksiyonuna kapalıdır. Yerel adaptör,
sahibiyle sınırlı dizin/dosya izinleri, symlink reddi, fsync ve atomik hard-link
kullanır. Bu, makine yöneticisine karşı imza veya bağımsız zaman kanıtı değildir.

Sınırlar: sıkıştırılmış bundle 32 MiB, açılmış SQLite 128 MiB, manifest 64 KiB.
Tar/PAX metaverisi de dahil açılan toplam akış sınırlandırılır. Arşiv üyeleri
açılmadan önce ad, tür, tekrar ve uzunluk açısından sınanır.
SQLite bütünlüğü, hazır kayıtlar ve tahmin bağları mevcut karantina kurtarma
katmanında tekrar denetlenir. İçe aktarım yeni bir hedef dizin ister; mevcut
veritabanına kayıt eklemez ve eski tahminleri değiştirmez.

İçe aktarım için **güvenilir manifest SHA-256 pini** zorunludur. Kendiliğinden
bir `latest` seçilmez. En yeni pinin oturum dışında güvenle korunması ayrıca
gereklidir; eski bir pin verilirse sistem daha yeni yedek olduğunu bilemez.
Dosya kilidi/kopya SQLite, farklı makinelerde dağıtık tek-yazıcı garantisi vermez.

## Yerel kullanım

```sh
python -m faz39_transfer export BUNDLE.tar.gz /absolute/local-staging \
  --expected-bundle-sha256 TRUSTED_BUNDLE_SHA256 \
  --config config/faz39-local.example.json

python -m faz39_transfer import /absolute/local-staging /absolute/new-restore \
  --expected-manifest-sha256 TRUSTED_MANIFEST_SHA256 \
  --config config/faz39-local.example.json
```

CLI yalnızca yerel referans adaptörü oluşturur; collector validator'ı harici
konfigürasyonu reddetmeye devam eder. Python API'sinde gelecekteki bir EXTERNAL
adaptör için ayrı, açık hedef alias'ı ve EXTERNAL politika gerekir; yazma ayrıca
`upload_enabled=True` gerektirir. Bunlar bu çalışma ortamında etkinleştirilmedi.
Bu dalda gerçek bir EXTERNAL adaptör veya uzak bağlantı fabrikası yoktur.
Gerçek hedef ve erişim yetkisi için ayrıca kullanıcı yetkilendirmesi gerekir.
Bu yol testlerde yalnızca bellekteki sahte adaptörle sınanır; sır veya ağ yoktur.

## SQLite WAL ve aktif yazıcı testleri

Mevcut SQLite Online Backup API korunur; commit edilmiş WAL sayfaları da tam
SQLite kopyasına girer. Ana `.sqlite` dosyası ile `-wal/-shm` dosyalarını ayrı
ayrı aktararak tutarlılık sağlandığı varsayılmaz.

`tests/test_faz39_storage.py` içindeki 28 test şunları kapsar:

- Commit edilmiş WAL sayfaları, açık WAL işleminin dışlanması, rollback ve
  commit sonrasında iki tablonun birlikte görünmesi.
- Artımlı yedek sürerken gerçek ayrı yazıcı thread'inin 256 satırı tek işlemde
  güncellemesi: yedek tek nesildir, karışık nesil veya yarım işlem içermez.
- Rollback journal'da EXCLUSIVE yazıcı: süre aşımı, sıfır yayın ve sağlam kaynak.
- Hash/uzunluk/manifest/SQLite bozulması, yarım aktarım, yeniden deneme,
  eşzamanlı yayın, üzerine yazmama, symlink ve yeni Python sürecinde içe aktarım.

## Gerçek doğrulama seviyesi

Sonuç yalnızca **LOCAL_RECOVERY_VERIFIED** seviyesindedir. Gerçek SQLite/WAL
mekanizması aynı Cloud makinesinde çalıştırıldı; veriler sentetiktir. Farklı
Cloud oturumu, harici sağlayıcı dayanıklılığı, makine/disk kaybından sonra
kurtarma, güvenilir harici pin deposu ve gerçek prospektif tahmin üretimi
**DOĞRULANMADI**. `durable_storage_verified` ve
`separate_cloud_runtime_verified` alanları otomatik olarak true olmaz.
Sentetik kayıtlar gerçek prospektif örnek değildir. Üretim zamanlayıcısı kapalıdır.
