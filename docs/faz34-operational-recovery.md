# FAZ34 — tek seferlik çalıştırma ve kesinti sonrası güvenli kurtarma

Taban SHA: `66e14bb349c0ff408da1ef9ce6e69fabac06f4e3` (FAZ33).
Dal: `feature/nba-command-20261104`; PR #12 açık, taslak ve birleştirilmemiş.
FAZ33 push/PR unit-tests ve docker-build başarıları bağımsız doğrulandı.

Kullanıcının bildirdiği `Selected model is at capacity` kesintisinden sonra
faz34.py, research_recovery.py ve tests/test_faz34.py dosyaları bulundu.
Çalışma kayıp değildi. Değişiklikler ek bir yerel kaynak kopyasıyla korundu;
reset/clean veya tahmin silme yapılmadı. Kapasite hatası yerel uygulama
traceback'i olarak yeniden üretilmedi; servis hatasının yerel kök nedeni
kanıtlanmış sayılmaz. Önceki FAZ34 hedef test işlemi tamamlanmıştı.

## Yeniden başlatılabilir tek geliştirme turu

```sh
python -m faz34 run-once NEW_CUTS.sqlite COPIED_HISTORY.sqlite STATE_DIRECTORY
python -m faz34 run-once NEW_CUTS.sqlite COPIED_HISTORY.sqlite STATE_DIRECTORY --dry-run
```

Bu komut sürekli servis veya üretim zamanlayıcısı kurmaz. Her çağrı mevcut ESPN
NBA takvimini yeniden okur ve işlenmemiş T24H, T6H, T60M kesitlerini belirler.
FAZ33'ün resmî sezon, başlangıç/durum, kaynak zamanı, ingestion, model SHA ve
özellik kapsamı kuralları korunur. Kesit erkenken kayıt yoktur. Beş dakikalık
kayıt penceresi kaçtıysa eski saate yazılmaz. Başlamış/ertelenmiş/saati
belirsiz veya kimliği çelişkili maç reddedilir.

Aynı FAZ25/FAZ33 dosya kilidi toplama, denetim ve yedekleme boyunca tutulur.
İkinci süreç `BUSY` döner; veri toplayıcıyı bile başlatmaz. Kilit alındıktan
sonra FAZ33 turunun ortak gövdesi çalıştırılır; ikinci bir kilit alma girişimi
veya kendi kendini kilitleme yoktur. SQLite kilit beklemesi bir saniyeyle
sınırlıdır. Kaynak kontrolü temiz geliştirme commit'ini denetlemeye devam eder.

`STATE_DIRECTORY/operations.sqlite` içinde SHA zincirli, UPDATE/DELETE/REPLACE
engelli operasyon olayları tutulur:

- STARTED: gerçek UTC, kaynak SHA, defter modu ve önceki kesitlerin digest'i.
- FINISHED: tur durumu, son digest ve yeni kayıtların özgün SHA/zaman kanıtları.
- CHECKPOINT_VERIFIED veya CHECKPOINT_FAILED: yedek sonucu.
- INTERRUPTED: önceki tur STARTED durumunda kalmış ve kilit yeni süreççe alınmış.

Yeni süreç aynı kesitleri defterden okur; önceki STARTED olayından hareketle
eski kesiti yeniden üretmez. Süreç SQLite transaction'ı tamamlamadan ölürse
SQLite geri alır. Commit'ten sonra günlük tamamlanmadan ölürse kayıt korunur;
yeniden çalıştırma onu ALREADY_RECORDED olarak görür. Önceki kesitlerin SHA,
kayıt zamanı, kesim zamanı ve model SHA bilgileri çalıştırma sonunda yeniden
karşılaştırılır. Operasyon sayısı veya kesit sayısı farklı maç sayılmaz.

Referans FAZ13/FAZ28 ve FAZ31 durumunun tek transaction içindeki FAZ33 paketi
aynen kullanılır. Model yoksa NO_MODEL_AVAILABLE ve sayısal gölge tahmini null
kalır. Final sonuçları ayrı tabloda tutulur; geçmiş tahminler değiştirilmez.
Üretim katsayıları değiştirilmedi.

## Yedekleme kilitlenmesinin giderilmesi

Eski SQLite backup döngüsünde kilitli kaynak için toplam süre sınırı yoktu.
`faz25.backup` artık monotonic toplam süre bütçesi, küçük sayfa grupları,
progress callback ve kısa yeniden bekleme kullanır. Doğrudan çağrıda varsayılan
bütçe 5 saniyedir. Hem kaynak hem hedef bağlantı hata/iptalde kapatılır;
bütünlük kontrolü de süre sınırını gözetir. Tamamlanmamış snapshot yayımlanmaz.

`research_recovery.make_bundle` bütün veritabanlarını **ortak 15 saniyelik**
kopyalama/paketleme bütçesiyle işler; her dosya için süreyi sıfırlamaz. Dosyalar
0600, paket fsync edilmiş ve atomik/no-clobber yayımlanır. Yerel depolama
başarısı Cloud oturumları arasında kalıcılık garantisi değildir.

Her gerçek tur sonrasında yönetilen üç veritabanı için paket oluşturulur:
prospective.sqlite, history.sqlite, operations.sqlite. Paketteki kaynak SHA,
dosyaların SHA-256 manifesti, SQLite integrity_check ve anlamsal tahmin/
kaynak/operasyon doğrulaması kontrol edilir. Eski FAZ24 defterleri ayrıca
korunur; kapsamlı kurtarma paketine salt okunur eklenebilir.

FINISHED olayı snapshot'tan önce, CHECKPOINT_VERIFIED onayı sonra yazılır;
paket kendi SHA'sını içeriyormuş gibi gösterilmez. Checkpoint başarısızsa
kesit geri alınmaz/silinmez: CHECKPOINT_FAILED ve yeni kesit sayısı açıkça
raporlanır. İşlem başarısızsa yeni kayıt sayısı doğrulanmadan sıfır varsayılmaz.
Toplama turunda süre aşımı RUN_TIMEOUT olur; tamamlanmış kayıtlar denetlenir
ve yerel yedekleme denenir. CLI hata durumunda sıfırdan farklı çıkış kodu verir.

## Gerçek takvim ve kayıt durumu

5 Kasım 2026 gerçek ESPN sorgusunda:

| Denetim | Sayı |
|---|---:|
| Yaklaşan maç | 18 |
| Üç kesit için toplam durum | 54 |
| Henüz gelmemiş kesit | 52 |
| Kaçırılmış kesit | 2 |
| Kayıt penceresindeki kesit | 0 |
| Yeni gerçek tahmin kesiti | **0** |
| Yeni uygun prospektif eğitim örneği | **0** |

Sonraki kesit sorgu anında **5 Kasım 20:00 UTC / 23:00 Türkiye** görünmektedir.
Takvim değişebilir. Erken kayıt veya geçmişe dönük doldurma yapılmadı. Nihai
commit'in temiz checkout'undan yapılan gerçek run-once ve yeniden çalıştırma
sonuçları ayrıca çalışma çıktısında raporlanır. Sürekli arka plan toplayıcısı,
cron, Fly.io veya Telegram zamanlayıcısı kurulmadı.

## Kalıcılık ve geri yükleme

```sh
python -m faz34 restore RECOVERY.tar.gz NEW_DIRECTORY --expected-sha256 EXTERNAL_SHA256
```

SHA-256 paket dışından beklenen değerle karşılaştırılır. Paket önce mevcut
güvenli doğrulayıcıdan geçer; sadece yeni 0700 hedef dizine 0600 dosyalar yazılır.
Mevcut dizin veya dosyanın üzerine yazılmaz. Dosyalar fsync edilir; ancak bütün
kopyalama bitince RESTORE_COMPLETE.json yazılır. Kesinti olursa yeni dizin
kısmi kalabilir ve tamamlandı işareti oluşmaz; eski veriler etkilenmez.
Bu durumda farklı yeni hedef kullanılmalıdır. Anlamsal denetim ve hash'ler
kaynak imzası veya sağlayıcı erişilebilirlik garantisi değildir.

Gerçek yeni Codex Cloud ortamı/oturumu oluşturup geri yükleme **DOĞRULANMADI**.
Mevcut araçlar yalnızca bağlı ortamın durum/diagnostic bilgilerini sunuyor;
yeni Cloud ortamı oluşturma işlevi yok. Aynı ortam ID'si ve dosyaların mevcut
olması, yeni bir Cloud oturumunda kalıcılık deneyi sayılmadı. Temiz süreç/yeni
hedef dizin testleri bu sınırla ayrı raporlanır. Harici yükleme yapılmadı.

## Ücretsiz harici saklama seçenekleri — etkinleştirilmedi

Depo GitHub API üzerinden public olarak doğrulandı. Aşağıdaki seçenekler
incelendi; yeni servis/anahtar/billing yapılandırması yapılmadı.

| Seçenek | Ücretsiz kullanım çerçevesi | Süreklilik ve sınır | Değerlendirme |
|---|---|---|---|
| Kullanıcının kendi diskine/halihazırdaki NAS'ına indirme | Mevcut donanım varsa ek servis ücreti yok | Oturum dışında tutulmalı; elle aktarım ve ayrı hash saklama gerekir | Hemen uygulanabilir, kullanıcı tarafından saklanması gerekir |
| Mevcut GitHub Actions artifact | Public repoda standart Actions kullanımı ve hesap politikaları çerçevesinde | Artifact saklama süresi yapılandırılır; süresi dolunca silinir | Süreli yedek için; tek kalıcı arşiv sayılmamalı |
| GitHub Release asset | Mevcut public depo, yeni sağlayıcı/anahtar gerekmez | Dosya 2 GiB altında olmalı; toplam release boyutu/bandwidth için belgede sınır yok; silme ve depo politikaları geçerli | Uzun süreli, sürümlü kopya adayı; burada release/tag/upload oluşturulmadı |

Kaynaklar HTTP 200 ile okundu; URL/gözlem/hash kanıtı kaydedildi:

- https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts
- https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases

Public depoya tahmin/veri paketi yüklemek onu yayımlamak anlamına gelir.
Bu fazda karşılaştırma yapıldı; herhangi bir artifact veya release yüklemesi
başlatılmadı. GitHub hesabının saklama/bütçe politikasının ayrıca doğrulanması
ve oturum dışında en az bir kopyanın korunması gerekir. Ücretli servis kurulmadı.

## Testler, kesinti bulguları ve açık riskler

**687 regresyon testi başarılı**, 37.556 saniye; **14 yeni FAZ34 testi**.
İlk tam koşuda 12 hata vardı: elle başlatılan yardımcı IsolatedAsyncioTestCase
fixture'ının kendi runner'ı olmadığı için cleanup'ları çalışmıyor, sanal saat
sonraki gerçek FINAL testlerine sızıyordu. Cleanup'lar etkin dış test runner'ına
aktarıldı. Gerçek FINAL doğrulayıcıları veya sonuç kayıtları gevşetilmedi.

Testler: yeni süreç/defterle idempotency, örtüşen çağrı kilidi, yarım kalan
günlükten toparlanma, sahip olunan alt sürecin os._exit ile kesilmesi,
SQLite transaction geri alma ve kilit bırakma, erken/kaçırılmış kesit,
çalıştırma/yedek paket toplam süresi, başarısız checkpoint sonrası kayıt
koruma, dry-run, SQL/hash bozulması ve yeni hedefe hash doğrulamalı restore.
Sentetik test kayıtları hiçbir gerçek tahmin veya eğitim örneği sayılmadı.

Eski FAZ24/FAZ29/FAZ30 kanıtları ve ilgili arşivler için yedi hash değişmedi;
beş mevcut SQLite dosyasında integrity_check başarılı. Compileall ve diff
kontrolleri başarılı. Nihai commit'in unit-tests/docker-build CI sonucu
ayrıca GitHub'dan doğrulanır; yerel Docker başarısı iddia edilmez.

Açık riskler: yeni Cloud ortamı testi ve harici kalıcı kopya henüz yok;
çalıştırıcı kesit saatinde çağrılmazsa pencere kaçabilir; sağlayıcı kesintileri
ve eksik takım/rakip geçmişi gerçek kayıt oluşmasını engelleyebilir. Sakatlık,
kadro, piyasa ve toparlanma verileri doğrulanmış değildir; tempo kutu skoru
tahminidir. Gölge model hâlâ eğitilmemiştir. Merge veya üretim dağıtımı yapılmadı.
