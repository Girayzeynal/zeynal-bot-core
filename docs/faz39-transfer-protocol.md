# FAZ39: sağlayıcıdan bağımsız aktarım ve WAL kurtarması

`faz39_transfer.py`, mevcut `faz39_recovery.snapshot/restore` doğrulamasını
kullanır. Yerel yedekleme API'si ve örnek collector konfigürasyonu değişmez:

```json
{"mode":"LOCAL_ONLY","external_target":null,"upload_enabled":false}
```

Zamanlayıcıya veya Telegram/Fly.io akışına entegrasyon yoktur. Gerçek bir uzak
sağlayıcı adaptörü, kimlik bilgisi veya harici hedef yapılandırılmadı.

PR #14'ün sonraki harici sözleşme/trusted-pin/bağımsız kanıt hazırlığı,
[`faz39-independent-recovery-runbook.md`](faz39-independent-recovery-runbook.md)
ve `faz39_checkpoint_contract.py` içindedir. Bu ayrı, varsayılan kapalı katman
yerel protokolü değiştirmez; gerçek harici kalıcılık veya ikinci Cloud kurtarması
doğrulaması sağlamaz.

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
İçe aktarım sonucu bunu `checkpoint_selection=EXACT_TRUSTED_PIN` ve
`pin_freshness=NOT_ATTESTED` alanlarıyla açıkça belirtir. Eski ama geçerli bir
pin bilinçli olarak eski yedeği seçebilir; bunun en yeni pin olduğu iddia edilmez.

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

## Güvenli hata ve tekrar deneme denetimi

`tests/test_faz39_transfer_safety.py`, 17 ek regresyonla önceki kapsamı genişletir.
Tamamlama kaydı görünür olduktan sonra dizin fsync'i başarısız olabilir. Önceki
kod, aynı nesneyi tekrar gördüğünde bu bariyeri atlayabiliyordu. Yerel adaptör
artık mevcut nesne için de dizin fsync'ini tekrarlar. Hata devam ediyorsa
`ALREADY_EXPORTED` başarısı bildirilmez; önceden görünür olan nesne silinmez.
Geçici dosya adı çakışmasında temizleme yalnızca bu çağrının başarıyla oluşturduğu
dosyayı siler; `O_EXCL` ile reddedilen başka yazıcıya ait dosyaya dokunulmaz.

| Senaryo | Güvenli davranış |
|---|---|
| Eksik/geçersiz trusted pin | Adaptör okumasından önce ret |
| Doğru pin, eksik commit marker | İçe aktarım yok, latest/fallback seçimi yok |
| Eski içerik yeni pin anahtarında | SHA/uzunluk uyuşmazlığı nedeniyle ret |
| Bozuk/truncated bundle | Hedef oluşturulmadan ret |
| Dosya fsync'inde ENOSPC | Başarı yok, henüz yayımlanmamış geçici dosya temizlenir |
| Manifest link'inde EACCES | Tamamlama kaydı yok; aynı paketle tekrar denenebilir |
| Commit link'inden sonra dizin fsync hatası | Nesne görünür olabilir; hata/sonuç belirsizdir, tekrar denemede bariyer zorunludur |
| İçe aktarım sırasında ENOSPC | Doğrulanmış kurtarma bildirimi yok; kısmi hedef korunur ve üzerine yazılmaz |
| Gecikmeli read-after-write / kayıp ACK | Başarı varsayılmaz; aynı içerik kimliğiyle tekrar deneme yapılır |
| Eşzamanlı okuyucu/yayımlayıcı | Commit marker öncesi okuyucu reddedilir |
| Aynı hedefe iki importer | Tek işlem hedefi oluşturur, diğeri mevcut hedef nedeniyle reddedilir |

CLI hata halinde JSON `TRANSFER_FAILED` ve sıfırdan farklı çıkış kodu verir.
`publication_state=UNKNOWN_AUDIT_REQUIRED`, `local_recovery_verified=false`
alanları hata sonrasında sıfır yazma varsayılmasını engeller. Ham I/O hata
metinleri yazdırılmaz. Marker/ACK sonrası hatada nesneler zaten görünür olabilir;
aynı trusted pin ile yeniden deneme veya salt okunur denetim gerekir. Eksik
hedef otomatik silinmez. Başarılı yerel replay, harici kalıcılık kanıtı olmaz.

Disk gerçekten doldurulmadı: ENOSPC/fsync/link/yazma hataları kontrollü olarak
enjekte edilir. Hedef izin reddi ayrıca mevcut non-root Linux kullanıcısında
gerçek `chmod 0500` ile sınanır (root bu testi atlar). Ağ gecikmesi ve kayıp ACK
bellek adaptöründe taklit edilir. Ayrı Cloud runtime yoktur. Bu ortamda izinli
`/workspace` ve `/tmp` aynı dosya sistemi aygıtındadır; iki dizin/süreç deneyi
iki bağımsız dosya sistemi veya Cloud kurtarması olarak raporlanmaz.
