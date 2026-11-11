# FAZ47 — salt okunur kadro durum adaptörü

Başlangıç checkpoint'i `ece685aeefa244a0513356d3be3a26de276bf434`. PR #12'deki FAZ39 dosyaları kopyalanmadı, import edilmedi veya cherry-pick yapılmadı. Yeni `faz47_lineup_view.py`, mevcut FAZ46/FAZ41 kaynak kapısının üzerinde isteğe bağlı bir geliştirme API'sidir. Tahmin, Telegram, zamanlayıcı veya ledger yoluna otomatik bağlanmadı. Önceki katsayılar, kanıt dosyaları ve veritabanları değiştirilmez.

## Durum sözleşmesi

| Kanıt | Durum | İlk beş / belirsizlik |
|---|---|---|
| Kanıt yok | UNAVAILABLE | `starting_five=None`; eksik bilgi görünür |
| FAZ46'nın replay edebildiği teyitsiz kaynak listesi | UNAVAILABLE | Liste ayrı tutulur; beş isim, `active` veya `startFive` bayrağı tahmin üretmez |
| İzinli kaynak, fixture/lig/sezon ve PIT kapılarından geçen normalleştirilmiş resmî duyuru | OFFICIAL | Özgün beş korunur; bu tek başına bağımsız kaynak attestation'ı değildir |
| Muhtemel ilk beş kaynağı/modeli | Desteklenmiyor | `projected_adapter_status=NOT_AVAILABLE`; PROJECTED uydurulmaz |

`excluded`, `uncertain` ve `active_for_target` alanları doğrulanmış ayrı kaynak olmadığı için **None** kalır. Boş listeye dönüştürülerek herkesin sağlıklı/oynamaya uygun olduğu ima edilmez. OFFICIAL bir takım diğerini yükseltmez; teyitsiz liste resmî duyuru yanında da ayrı alan olarak kalır.

## Kaynak ve model bağı

`lineup_view(observations, *, fixture, cutoff_utc, model_manifest, trusted_model_sha256, ...)` önce FAZ42 model manifestini ve dışarıdan beklenen manifest pin'ini doğrular. Ardından bütün gözlemleri `prematch_context` üzerinden geçirir; tek bir geçersiz kaynakta kısmi sonuç dönmez. Kaynak izinleri UNKNOWN kalırsa gerçek gözlem modele kabul edilmez; testlerdeki sentetik izinler varsayılan politikaya yazılmaz.

Çıktı, hedef fixture/UTC cutoff, özgün published/observed/ingested/materialized saatleri, sağlayıcı ve maç kimlikleri, raw/evidence/context/policy digest'leri ve model SHA/manifest pin'ini bağlar. Kanıtlar tekrar ve sıra değişikliğine göre deterministik olarak tekilleştirilir. Kaynak metinleri veya eski payload'lar normalize edilip yeniden yazılmaz; girdiler ve çıktı birbirine mutable referans taşımaz.

Model bağı açıkça `PINNED_REFERENCE_NOT_EXECUTION_ATTESTATION` olarak işaretlidir: **model çalıştırıldığı iddia edilmez**. Çıktı bir `READ_ONLY_DEVELOPMENT_NOT_PREDICTION` görünümüdür; hash'i olan değiştirilebilir bir JSON nesnesidir, kalıcı immutable prediction ledger kaydı değildir. Model kaynak dosyalarının yeni çalışma ortamıyla eşleşmesini veya GitHub CI onayını bu API tek başına kanıtlamaz. Bu kontroller gerçek generation yolunun mevcut manifest doğrulamasında kalır.

`validate_lineup_view(view, observations, **expected)` çağıranın beklediği fixture/cutoff/model/pin üzerinden kaynağı tekrar oynatır. Yalnızca yerel hash eşleşmesi yeterli sayılmaz. Çıktının statü, kaynak saati, model SHA, cutoff veya bilinmeyen sakatlık alanı değiştirilip yeniden hash'lense de replay eşitliği sağlanmaz. JSON hash kontrolü Python'daki `True == 1` gibi tip eşitlikleriyle aşılmayı da engeller.

Geçerli eski prematch kanıtı maçtan sonra yeniden okunabilir. Bu, geriye tarihli yeni tahmin değildir; API saat atmaz, tahmin hesaplamaz ve veritabanına yazmaz. `prospective_records_created=0`, `storage_status=NOT_ACTIVATED` sabittir. Yeni kayıt, HTTP, SQLite veya simülasyon işlemi bu modülde yoktur.

## Doğrulama

21 yeni deterministik sentetik test; NBA, EuroLeague ve EuroCup durum eşlemesi, kaynak/izin/pin/fixture hataları, zaman sınırları, alias çakışmaları, yeniden hash'lenen sahte alanlar, model kullanım sınıfı, immutable girdi davranışı ve idempotency kapsar. HTTP, SQLite ve model/simülasyon girişleri hata verecek şekilde yamalandığında API çalışır. Bunlar gerçek kadro veya tahmin doğruluğu değildir. Kesintiden korunan geliştirme dosyaları 11 Kasım'da yeniden kontrol edildi; testler tekrar çalıştırıldı. Komutlar, log hash'leri ve tam regresyon sonucu [kanıt kaydında](evidence/faz47-read-only-lineup-view-20261111.json) tutulur; exact-SHA GitHub CI commit sonrasında PR #26 üzerinden ayrıca doğrulanır.

Korunan gerçek FAZ46 audit dosyası, önceki hazır oluş kaydındaki dosya SHA'sı ve audit payload pin'iyle salt okunur doğrulandı. **3 audit / 0 kadro gözlemi / 0 resmî ilk beş**: NBA/ESPN, EuroLeague ve EuroCup kayıtlarının üçü de `ABSTAIN_ROSTER_NOT_PUBLISHED`. Bu önceki kaynak gözlemidir; bugünkü canlı takvim/kadro durumu olarak sunulmaz. Yeni sağlayıcı isteği yapılmadı. Mevcut arşivden gerçek bir OFFICIAL adaptör örneği üretilemedi; sentetik fixture'lar bu açığı kapatmış sayılmaz.

Gerçek tahmin–sonuç çifti **0**, yeni prospektif tahmin **0**, kalibrasyon **NOT_ESTABLISHED**. Sonraki gerekli işlem, izin ve zaman kanıtı bulunan gerçek kadro/ilk beş kaynağını ayrı bir sağlayıcı adaptöründe replay edebilmek ve bu görünümü geliştirme raporuna bağlamaktır. PROJECTED, sakatlık ve rotasyon etkisi veri olmadan eklenmez. Bağımsız ikinci Cloud kurtarması ve harici kalıcı depolama doğrulanmış değildir. PR taslak kalır; main merge, Fly.io/Telegram production, scheduler, secret veya dış depolama yüklemesi yoktur.
