# PR #89: preserved description before the European integration

The text below preserves the previous PR description, including historical evidence and limitations. Current acceptance and setup instructions are in the Phase 95 report.

18 maçlık UserLAnd challenger incelemesi tamamlandı; ancak terminal özetinde bütün total_coverage alanları null görünüyordu. Hesaplama kaybı yok: coverage.markets.TOTAL yerine coverage.TOTAL okunuyordu. Yeni salt okunur görünüm bu aktarımı düzeltir; kayıtlı deney protokolüne bağlı model dosyaları byte-identical kalır.

**HEAD:** `b0e589f5807dfed265db83192b9d072650406e14`  
Commits: `8ea2d11` kapsam görünümü, `907def2` yalnız görünüm ile offline review çalıştırmasını ayıran metadata. Mevcut PR #89 dal/base korunur; main/Fly/secret/disk/snapshot işlemi yok.

Başlatıcı izin düzeltmesi `b0e589f`: 100755 geri getirildi; aynı blob SHA, model/plan byte'ları değişmedi. Güncel HEAD CI sonuçları aşağıda.

### FAZ 94.1 — protokolü koruyan düzeltme

- Yeni challenger_summary.py mevcut SHA-bağlı rapordan doğru toplam kapsamasını okur. Desteklenmeyen bant/boş model açık gerekçeyle eksik kalır; güven yüzdesi veya kalibrasyon üretmez.
- `--challenger-summary`: en son yazılmış mevcut raporu okur; yeniden simülasyon, eğitim, SQLite veya Telegram çağrısı yok. Rapor seçimi performansa göre yapılmaz; bozuk en son raporda fail-closed.
- `--challenger-review` launcher yolu, değişmeyen legacy review CLI'sini çalıştırıp kaydedilen raporu doğru gösterir; argümanlar ve nonzero başarısızlık kodu korunur. Sadece görüntüleme / review child çalışması ayrı alanlarda gösterilir.
- 27 protocol-pin dosyasında değişiklik yok. Kullanıcının UTC epoch 1794926907 kaydına ait `1e8f24a665a8b34a2ca22c37e408591ae8547b12788fe70c7150079b43249317` hash'i regresyonla aynen doğrulandı. Özel plan kopyalanmadı veya yeniden kaydedilmedi.
- Read-only path/SHA/scope, symlink/production-path, 16 MiB dosya ve 1024 dosya tarama sınırları; native gzip schema regresyonu, gerçek subprocess + sentetik SQLite başarısızlık yolu. Eski rapor/forecast/ilk yayın değişmez.
- 18 maçta updated toplam MAE 15.9017 vs Faz13 16.4889 (~%3.56 daha düşük), frozen 16.6856. Takım MAE 10.4720 vs Faz13 10.7333; kazanan üçünde de 13/18. Üç gün kümesi / görülmüş geliştirme verisi; MC/QMC/quarter varyantlarının aynı mean'i üç bağımsız üstünlük değildir.
- [Kapsam, legacy CLI sınırı ve komut](docs/challenger-coverage-phase941-20261117.md).

### Doğrulama ve sınırlar

- Önceki 1332 + **14 yeni test**: exact-head GitHub unit ve Docker tam suite'leri **1346/1346 PASS**, 0 failure/error. Hash uyumu, native kapsam şeması, launcher ve subprocess/SQLite regresyonları PASS.
- Hard **1 CPU / 256 MiB**, normal/PDF birleşik suite ayrı ayrı **377/377 PASS**. İki CI'daki en yüksek hard-limit birleşik NBA/karar peak **166.22 MiB**. Ağ kapalı / native-byte ve loopback testidir; canlı Telegram latency değildir.
- [PR CI 44115715020](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44115715020) ve [push CI 44115697404](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44115697404): **completed / success**.
- Cloud environment startup explicit failure verdi; **yerel test koşuldu iddiası yok**. Aynı dalda GitHub connector ile iki commit yapıldı. Yeni viewer'ın özel UserLAnd / gerçek Telegram E2E'si henüz denenmedi.
- Üretim **NO-GO**; mevcut 100 yeni maç / 20 gün protokolü, kalibrasyon ve kaynak şartları değişmedi. Mevcut planı yeniden oluşturmak gerekmiyor.

İzole poller gerekirse Ctrl+C ile durdurulduktan sonra:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-summary
```
Bu komut mevcut 18-game raporunu okuyabilir; modelleri yeniden çalıştırmaz.

<details><summary>Korunan FAZ 94 ve önceki kanıtlar</summary>

Gerçek 18 maçlık UserLAnd incelemesinde sabit hibrit, basit aynı-girdi baseline'ını geçemedi. Bu değişiklik yeni varsayımları üretime taşımadan, mevcut adayları aynı orijinal girdilerle ölçen offline akışı ve yeni, önceden kayıtlı ileri deneyi ekler. Eski tahminler ve aktif Telegram matematiği korunur.

**HEAD:** `074e4d74827756164fd1ea58ae4f346d9346a5c2`  
**Dal/base:** mevcut PR #89; araştırma dalı ve base değişmedi. Main merge / Fly deploy / secret / disk / snapshot işlemi yok.

### FAZ 94 — aynı girdide adaylar ve ileri doğrulama

- Yeni `--challenger-review`: salt okunur native SQLite + hash bağlı orijinal assets; frozen model, Faz13 referansı, güncellenen Bayes MC/QMC, mevcut stokastik periyot adayı ve yeterli box varsa mevcut possession MC/analitik. Aynı fixture kesişiminde takım/toplam/fark/periyot hataları, Brier/log loss, reliability, bant kapsaması/interval skoru ve eşli farklar.
- Hedef final predictor'a verilmez; yalnız çıktıdan sonra değerlendirmeye eklenir. Kaynak/etiket zamanı, ilk yayın, model/sezon ayrımı korunur. Eksik aday sıfır hata değildir; analitik örnek yoksa quantile uydurulmaz.
- Gerçek Philadelphia cut'ı **19** yakın maç tutuyor; orijinal fit **170** maça dayanıyor. Bunları tam lig yeniden eğitimi saymak yanlış olur. Yeni sınırlı aday, orijinal posterior sufficient statistics'e yalnız **iki** yeni, tekrar sayılmayan geçmiş maçı ekler (**172** toplam), likelihood noise sabit. Bağımsız scalar Kalman testi batch algebra'yı doğrular.
- Bu **fixed-noise posterior update**; tam lig refit, yeni oyuncu/tempo katsayısı veya recency optimizasyonu değildir. Düzeltilmiş eski etiket/yeni takım full-refit gerektirir; sessizce eski katkı değiştirilmez.
- Stokastik periyot adayı eski quarter_shadow'u kullanır; toplam patikalarını ve nokta skorlarını korur. Periyot kalibrasyonu kanıtlanmış sayılmaz.
- `--challenger-plan / --challenger-capture / --challenger-results`: kod/politika önceden hash ile kaydedilir; aynı plan tekrar kayıtta tarih yenilenmez. Yalnız plan SONRASI yeni orijinal cut, en fazla 1 saat input yaşı ve en az 15 dk lead; batch en fazla dört. 180 sn yalnız maçlar arasında admission bütçesidir.
- ForwardRegistry ile ilk araştırma yayını korunur; tekrar capture yeniden model çalıştırmaz, tipoff/commit sınırı fail-closed. Sonuçlar native ledger'dan exact original SHA/fixture ile sonradan birleşir. Geliştirmede görülmüş eski 18 maç yeni confirmatory cohort'a giremez.
- Tek predeclared primary: UPDATED_BAYES_STOCHASTIC_PERIODS vs Faz13 team MAE; en az **100 yeni ortak maç / 20 TSİ gün kümesi**, %80 kapsam, en az %2 göreli iyileşme ve tek primary eşli gün-cluster fark aralığının üst sınırı <0. Model/metric seçimi sonuca göre yapılmaz. Tek primary interval, çoklu keşif panelinden ayrıdır. Otomatik promotion/kalibrasyon yok.
- Bu işler explicit offline CLI'dadır; Telegram isteğinde eğitim/güncelleme yok. Mevcut /analyze skor, UI ve dar/geniş bant mantığı değişmedi. Rapor dizini ledger/assets altında olamaz; review ana DB ve mevcut WAL hash'lerini önce/sonra karşılaştırır, eşzamanlı değişimde geri yazmadan BLOCKED.

### Gerçek örnek — üstünlük kanıtı değil

Cloud'da özel 18 kayıtlık DB yok. Preserved gerçek Philadelphia forecast + pinned native ESPN final, yeni izole replay KOPYASINDA incelendi; yalnız final kopyaya eklendi, kaynak paket ve eski forecast SHA değişmedi. Tek maçta frozen toplam hata **−33.21108**, Faz13 **−34.95**, güncellenen Bayes **−32.99370**. Küçük fark başarı/kalibrasyon/OOS üstünlüğü değildir. Possession iki yöntem de yetersiz orijinal box nedeniyle ABSTAIN.

- Yeni public native rapor: `docs/evidence/challenger-phase94-native-20261117.json.gz`; file SHA `a0768224b5c287c1342f064c8fcecc3c3f7a2fe7b3c89e761611de776dee2e2c`; payload SHA `81a1da7c929850a8d1295ee8162e26b4e7321cf9ff9958f2f2768f5413fc13a0`.
- Native replay **n=1**; yeni protokol confirmatory **n=0**. Eski bitmiş örnek yeni ileri capture'a alınmadı.
- UserLAnd'deki 18 maçın MAE **16.6856 vs 16.4889** baseline bilgisi kullanıcı native raporundan aktarılmıştır; Cloud'a tam native 18 arşivi aktarılmış gibi gösterilmez.
- [Kapsam, komutlar ve kalan üretim kapıları](docs/production-readiness-phase94-20261117.md).

### Son HEAD doğrulaması ve açık kapılar

- Önceki 1291 + **41 yeni test** korunur. Hedef native/posterior/protokol/launcher subset **48/48 PASS**. Yerel tam suite **1332/1332 PASS**, 0 failure/error, **91,165 sn**. Bash syntax, diff whitespace ve protected-source diff kontrolleri PASS.
- İlk geliştirme denemesi 19 satırı full hierarchy minimum 30'a vermenin gerçek engelini açığa çıkardı; eşik düşürülmedi. Bağımsız Kalman doğrulamalı sınırlı posterior update kullanıldı. Eski metadata'sı eksik kayıtlar da raw KeyError yerine açık admission engeli verir. Başarısız test kaldırılmadı.
- Exact HEAD GitHub unit ve deployment-image tam suite'leri **1332/1332 PASS**.
- Hard **1 CPU / 256 MiB**, network-none normal/PDF görüntülerindeki birleşik provider/PTB/player/challenger suite'i ayrı ayrı **363/363 PASS**, 0 failure/error. PR normal/PDF cgroup peak **119.64 / 122.51 MiB**.
- İki CI'daki en yüksek hard-limit birleşik NBA/karar cgroup peak **165.91 MiB**. Gerçek canlı Telegram/internet gecikmesi ölçümü değildir.
- Mevcut hybrid/native NBA, karar/kalibrasyon, read-only NBA/EuroLeague replay ve forward EuroLeague komut/rapor adımları PASS.
- [PR CI 44089311126](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44089311126) ve [push CI 44089298546](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44089298546): **completed / success**, aynı HEAD.
- 11 değişen dosya: üç yeni offline modül, üç yeni test modülü, launcher/runtime-probe/test uzantısı, kapsam belgesi ve yeni native rapor. Faz13, models/distributions/data/live_nba, verified_history, universal_analysis, main ve eski prospective kayıtlarında diff yok.
- Valid gerçek CLI denemesi yeni izole public-source SQLite replay kopyasında **n=1, blocked=0**, DB/WAL değişmedi; yeni forward **n=0**. Native rapor hash ve 27 code pin güncel kaynakla doğrulandı.

**Gerçek yeni özellik UserLAnd / Telegram E2E: BLOCKED, Cloud'dan özel arşiv/test botu erişimi yok.** Kullanıcının önceki /compare ve /accuracy Telegram yanıtları mevcuttur; bunlar yeni challenger akışının testi diye sunulmaz.

**Üretim/default-model geçişi: NO-GO.** Tam lig eğitim kaynağı, orijinal box/PBP/oyuncu-dakika kapsamı, EuroCup doğrulaması, otomatik telefon resmî rapor keşfi, doğrulanmış settlement ve ayrık kalibrasyon/ileri sonuçlar açık. Kodun daha gelişmiş olması, model üstünlüğü kanıtı değildir. Main/Fly/secret/disk/snapshot işlemi yapılmadı.

### UserLAnd — ilk iki adım

İzole poller'ı Ctrl+C ile durdurup sırayla:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-review
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --challenger-plan
```
İlki gerçek özel arşiv üzerinde aynı-girdi karşılaştırmasını yapar; ikincisi yalnız yeni gelecek veriler için plan kaydeder. Eski sonuçları ileri doğrulama saymaz. Sonraki capture/results komutları ve sınırları kapsam belgesinde.

<details><summary>Korunan FAZ 93.2 ve önceki kanıtlar</summary>

Telefon sezon dizininde HTTP 403 alırken aynı resmî CDN PDF'sini indirebiliyor. İzole bot ve offline oyuncu-girdi collector'ı artık yalnız gerçek bir index 403 sonrasında, kullanıcı tarafından açıkça eklenmiş taze resmî PDF bağlantısını kullanabilir. Bu sınırlı opt-in kaynak köprüsüdür; otomatik en güncel rapor keşfi değildir.

**HEAD:** `f86d1f26986e460a4307b48236a55951e4343673`  
**Dal/base:** mevcut PR #89 dalları korunur. Main merge, Fly deploy, secret/disk/snapshot değişikliği yok.

### FAZ 93.2 — resmî PDF bağlantısı, bütünlük ve süre sınırı

- Yeni `--roster-pdf URL`: yalnız izinli HTTPS resmî CDN; tahmin edilmiş dosya adı, timestamp taraması, proxy veya erişim engeli aşma yöntemi yok.
- İndirmeden önce ve kullanımda yayın yaşı en fazla 30 dk. Gerçek PDF byte/SHA, tek tutarlı belge başlığı ve URL'nin Eastern → UTC yayın saati eşleşir. Gelecek/eski/yabancı/başka saate ait belge, parser eksikliği ve içerik değişikliği BLOCKED.
- Salt eklemeli, içerik adresli PDF/link arşivi: ilk erişim ve ilk arşiv saatleri ayrıdır; tekrar ithal ilk kaydı yenilemez. Yayıncı düzeltmesi ayrı kayıt; aynı anlı çelişki keyfî seçilmez.
- Alternatif yalnız gerçek index 403 ve açık yerel kayıtla çalışır; 401/404/429/taşıma hatasında etkinleşmez. Başarılı index önceliklidir. Mevcut cooldown korunur; kaynak önbelleği 30 dk yayın sınırını uzatamaz.
- `latest_report_verified=false` ve index 403 açıkça raporlanır. Maç/oyuncu kimliği, sezon, tipoff ve iki-kaynak yokluk kuralları korunur. Denver replay'deki dört yalnız-NBA Out kaydı hâlâ ESPN corroboration bekler.
- Yeni komut tahmin, dakika projeksiyonu, fit veya kalibrasyon üretmez. Aktif skor/dağılım/Faz13, eski tahminler ve evidence/prospective byte'ları değişmedi.
- Değişen 11 dosya: collector, PDF parser metadata, yeni official_report_link CLI, player/test-bot bağlantısı, launcher/runtime probe, üç test dosyası ve kapsam belgesi.

### Gerçek kaynak deneyi / sınırlar

Cloud'da gerçek resmî sayfanın yayımladığı `Injury-Report_2026-11-17_01_30AM.pdf` bağlantısı doğrulandı ve gerçek bounded parser ile ithal edildi. Yayın 06:30 UTC; erişim/arşiv 06:39:24 UTC. PDF SHA `19888cc0ef1c739c6d7493397383894df11b7610acaba20c93398a570ed6c482`; link SHA `45462e0742731459d36a95e3e8b6afcf20f246edd3c0e2d21267b6930934699e`. `forecast_created=false`, `latest_report_verified=false`. Bu Cloud HTTP/ithal deneyi telefon veya gerçek Telegram E2E değildir.

Yeni testlerdeki eski Denver PDF replay'i, orijinal yakalama saati ve açıkça sentetik index 403 ile yapılır; gerçek telefon akışı diye sunulmaz. İncelenen WordPress sorgusu boş, nba.com/injuryreport 404 ve NBA LiveData endpoints Cloud'da 403 döndü; çalışan alternatif sağlayıcı olarak bağlanmadılar.

[Uygulama kapsamı ve UserLAnd kullanımı](docs/official-report-link-phase932-20261117.md)

### Doğrulama ve karar

- Yeni 23 test; önceki 1268 test korunur. Yerel hedef subset **33/33 PASS**; tam suite **1291/1291 PASS**, 0 failure/error, 86,892 sn. Bash syntax ve diff whitespace kontrolleri PASS.
- Aynı HEAD GitHub unit ve Docker tam suite'leri **1291/1291 PASS**.
- Hard **1 CPU / 256 MiB**, ağ kapalı normal/PDF görüntülerindeki birleşik provider/PTB/player suite'i ayrı ayrı **322/322 PASS**, 0 failure/error. Gerçek native PDF byte replay'i ve bounded parser dahil; canlı Telegram erişimi değildir.
- PR cgroup peak normal/PDF **112.56 / 115.19 MiB**; iki CI'daki en yüksek hard-limit birleşik NBA/karar akışı **166.10 MiB**. Canlı internet/telefon gecikme ölçümü değildir.
- Hibrit/native NBA, karar/kalibrasyon, salt okunur NBA/EuroLeague replay ve ileri EuroLeague komut/rapor adımları PASS.
- [PR CI 44032401961](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44032401961) ve [push CI 44032394485](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44032394485): tam HEAD üzerinde **completed / success**.
- Gerçek yeni-mod UserLAnd / Telegram E2E: **BLOCKED — kullanıcı ortamında henüz doğrulanmadı**. Üretim/default-model geçişi **NO-GO**: otomatik güncel keşif, çift kaynak eksikleri ve ölçülmüş oyuncu-modeli OOS/kalibrasyon kanıtı açık.

UserLAnd'de izole poller Ctrl+C ile durdurulduktan sonra launcher'ın yeni `--roster-pdf 'gerçek_yayımlanmış_taze_resmî_URL'` modu kullanılabilir. URL'nin yayın yaşı her kullanımda en fazla 30 dk; eski 20:30 PDF'si yeniden ithal edilerek tazelenmez. İthal başarı=yalnız kaynak kaydı; dakika toplama/Telegram teslimi değildir. Normal başlatma komutu değişmedi.

<details><summary>Korunan FAZ 93.1 ve önceki kanıtlar</summary>

Resmî NBA PDF'sinin başlıksız devam sayfaları atlanıyordu: gerçek sekiz sayfalık rapordan yalnız sekiz erken satır çıkıyor, beşinci sayfadaki Denver/Phoenix gözlemleri bulunamıyordu. Ayrıştırıcı artık aynı rapor başlığı ve sayfa geometrisiyle doğrulanmış devamları okur; bu raporda 112 satır ve maç için yedi resmî kayıt üretir. Kaynak hataları aşama/HTTP/tanı koduyla ayrılır ve eksik kaynak oyuncu bazında listelenir.

**HEAD:** `a70fb6c3a47d73de49e4bba93bd58b4d676b91e1`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`; mevcut PR #89. Main/Fly/secret/disk/snapshot değişikliği yok.

### FAZ 93.1 — kanıt ve hata ayrımı

- Telefon çıktısı: Strawther ve Mark Williams ESPN Out; resmî extraction=null, genel hata. Bu, PDF bağımlılığı eksik veya kaynak HTTP 403 demek değildir; eski kayıt hata aşamasını kaydetmiyordu.
- Ayrı gerçek Cloud HTTP probe'u resmî sezon sayfasını ve yayımlanmış 16 Kasım 20:30 ET PDF'sini aldı. Bu, telefonun erişim testi değildir. Aynı PDF'de V1=8, V2=112 ayrıştırılmış satır; PHX@DEN için V2=7 satır.
- PDF devamları yalnız aynı rapor başlığı/geometri ile sütun devralır. Doğrulanamayan devam, yöntemler arası çelişen status ve yanlış yeni oyun bağlamı fail-closed. Karışık tablo/koordinat dosyaları benzersiz statülerle birleştirilir.
- Satıra sığmayan neden, açık oyuncu/status kaydını artık düşürmez. Koordinat nedenleri parça olarak etiketlenir; tıbbi neden tamamlanmaz veya oyuncu etkisi hesaplanmaz. Worker'ın 128 MiB / dört CPU sn / timeout sınırı korunur.
- İnceleme ve batch sonuçları INDEX_FETCH / PDF_FETCH / PDF_EXTRACTION / FIXTURE_ROWS ayrımı, güvenli kod, mevcutsa HTTP durumu, satır sayıları ve eksik kaynaklı oyuncuları taşır. Ham exception veya secret yansıtılmaz.
- Yeni `--roster-status ESPN_ID` saklanan incelemeyi salt okunur, hash doğrulamalı ve API isteği olmadan okur. Eski hatalarda `legacy_failure_stage_unknown=true`; geçmişte kaybolmuş HTTP bilgisi uydurulmaz.
- Strawther/Williams iki kaynakta eşleşti. Timme, Holmes, Nembhard, Whitmore için yalnız NBA Out var: **dört eksik ESPN corroboration**. İki kaynak kuralı DEĞİŞMEDİ; yeni dakika arşivi/başarı üretilmiş sayılmaz.

### Değişmez kaynaklar

- Yeni public-source paket: `docs/evidence/roster-phase931-denver-native-20261117.tar.gz`, SHA `b86111bc6ce429c02accaf11677fa885cb14978286ffd3aac13ea965b824a84f`.
- Gerçek index/PDF/roster receipt byte'ları ve ORİJİNAL eksik V1 review korunur. Reprocessing daha sonraki parser replay'dir. Yeni tahmin=0, prospective dakika=0, orijinal tahmin/model bağı=null. Eski paketler değiştirilmedi.
- Önceki native testteki V1 kısmi-liste eşitliği V2'de beklenen ek satırlar nedeniyle kırıldı. Test eski her satırı aynen korur VE güncel kapsamın tam sayı/kimlik kümelerini sabitler (Orlando 4, Chicago/Cleveland 12); önceki kayıt yeniden yazılmaz. Yeni Denver testi ayrıca yedi exact oyuncu/status ve dört kalan engeli doğrular.

### Doğrulama

- Yeni 23 test; mevcut testler korundu. Hedef kaynak/collector/inspector/launcher/native doğrulaması **59/59 PASS**.
- Son HEAD yerel tam suite **1268/1268 PASS**, 0 failure/error, 86,723 sn. Yerel birleşik probe 299/299 PASS (host 8 GiB / 2 CPU; hard limit kanıtı değildir).
- Exact HEAD GitHub unit ve Docker tam suite'leri **1268/1268 PASS**.
- Normal ve opsiyonel PDF görüntüleri: hard **1 CPU / 256 MiB** birleşik kaynak+PTB+player suite'i ayrı ayrı **299/299 PASS**, 0 failure/error. Ağ kapalı/native byte replay; yeni sekiz sayfalık PDF de bounded child'da ayrıştırıldı.
- PR normal/PDF cgroup peak **112,59 / 115,28 MiB**. İki koşuda karar katmanı dahil birleşik NBA akışının en yüksek cgroup ölçümü **165,89 MiB**. Bunlar gerçek Telegram/internet gecikmesi değildir.
- Hibrit/native NBA, karar/kalibrasyon, NBA/EuroLeague salt okunur replay ve ileri EuroLeague komut/raporları PASS.
- [PR CI 44001068363](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44001068363) ve [push CI 44001060564](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/44001060564): tam HEAD üzerinde **completed / success**.

Değişen 13 dosya: current_roster, NBA PDF parser, player_inputs, runtime probe, launcher; üç mevcut player testi ve native roster testi; iki yeni test modülü, kapsam belgesi ve yeni kaynak paketi. Model/dağılım/Faz13, eski tahminler ve sealed karar/kalibrasyon kaynakları değişmedi.

### UserLAnd — tek kısa tanı komutu

İzole poller çalışıyorsa Ctrl+C ile durdurup:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --roster-status 401910001
```
Bu eski telefon incelemesini okur; yeni veri/tahmin veya API isteği üretmez. Sonraki uygun gelecek maç toplama çıktısında roster_diagnostics otomatik yer alır. Başlangıçtan sonra eski maça yeni PREMATCH dakika kaydı eklenmez.

**Yeni HEAD gerçek telefon/Telegram E2E: BLOCKED.** Gerçek public HTTP kaynak erişimi ile gerçek Telegram teslimi farklıdır. Kullanıcıdaki eski hata kesin stage'e geriye dönük çevrilmedi.

**Üretim/model geçişi: NO-GO.** Kanıtlanan gelişme parser kapsamı/teşhistir; yeni oyuncu modeli OOS üstünlüğü veya kalibrasyon/güven artışı değildir. Dört tek-kaynak yokluk ve oyuncu/dakika belirsizliği eksikleri sürüyor. Eski skorlar ve üretim botu korunur.

[Kapsam, güvenlik ve örneklerin ayrımı](docs/roster-source-phase931-20261117.md)

<details><summary>Korunan FAZ 93.0 ve önceki kanıtlar</summary>

`--player-inputs-plan` ilk güncellemede JSON yerine botu başlatıyordu: çalışan eski Bash süreci Git'in değiştirdiği dosyayı yeniden yüklemiyordu ve eski kod tanımadığı bayrağı normal poller'a düşürüyordu. Başlatıcı artık başarılı güncellemeden sonra dosya değişmişse aynı argümanlarla yeniden çalışır; tanınmayan mod ve fazla argüman botu açmadan exit 2 verir.

**HEAD:** `6b6f2a28f47fb8438dfa9541d0ed9eff0e69c88a`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`; PR #89, base değişmedi. Main merge / Fly deploy yok.

### FAZ 93.0 — doğrulanmış güncelleme sınırı hatası

- Kullanıcı çıktısı: 8042f2d → 029f620 fast-forward, ardından Application started; plan/toplama JSON'u yok. Veri toplandı veya sonraki iki yapıştırılan komut çalıştı diye sunulmaz.
- Tam 8042f2d başlatıcı fixture'ı SHA ile sabitlendi. Gerçek yerel Git origin üzerinden dosya çalışırken güncelleniyor: ilk eski çağrı test_bot shim'ine, sonraki yeni çağrı player_inputs'a ulaşıyor. Hiçbir gerçek Telegram poller/API çağrısı yapılmıyor.
- Başlatıcı SHA-256 önce/sonra karşılaştırması; değişimde RESTARTING_UPDATED_LAUNCHER ve exec bash ile aynı argümanlar. Devralınan lock FD kapatılır; yeni çağrı kilidi normal alır. Tek-instance koruması atlanmaz.
- Tanınmayan seçenekler ve fazla argümanlar sabit tanıyla exit 2; token okunmadan dispatch yapılır. Standart argümansız bot açılışı korunur. Eski süreç bu düzeltmeyi geriye dönük uygulayamaz; güncel dosya yeniden çağrılmalıdır.
- Önceki launcher testi yalnız güncel/no-op-update senaryosuydu. Test korunarak gerçek kurulum dosyası eklendi; update sınırı ve gerçek Python CLI + SQLite yolu altı yeni testle kapsandı.
- Dört dosya: launcher, launcher testleri, sabit eski launcher fixture'ı ve [kanıt/kurtarma notları](docs/launcher-update-phase930-20261117.md). Model, skor, kalibrasyon politikaları, SQLite veya eski prospective/evidence dosyaları değişmedi.

### Doğrulama

- Yeni başlatıcı testleri: **7/7 PASS**; önceki bir test korunur, altı yeni regresyon vardır. Bash sözdizimi ve git diff --check PASS.
- Son HEAD yerel tam paket: **1245/1245 PASS**, 0 başarısız/hata, 88,282 sn.
- Aynı HEAD GitHub unit ve Docker tam paketleri: **1245/1245 PASS**.
- Normal ve opsiyonel PDF görüntülerinde hard **1 CPU / 256 MiB** suite: ayrı ayrı **276/276 PASS**. Eski/update sınırı ve gerçek CLI testleri ağ kapalı, salt okunur container'da da çalışır.
- Kaynak suite'i cgroup peak PR normal/PDF **112,34 / 114,88 MiB**; iki koşudaki karar katmanlı birleşik NBA akışının en yüksek cgroup gözlemi **165,44 MiB**. Bunlar gerçek Telegram/internet gecikmesi ölçümü değildir.
- Mevcut hibrit, native NBA, karar/kalibrasyon, NBA/EuroLeague salt okunur replay ve ileri EuroLeague komut/rapor kontrolleri PASS.
- [PR CI 43990478976](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43990478976) ve [push CI 43990472790](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43990472790): tam HEAD üzerinde **completed / success**.

Yerel ilk tam deneme kısıtlı ağ profilinde loopback testini tamamlayamadı; yalnız o test süreci sonlandırıldı (exit 143, tam sonuç değildir). Loopback erişimli yeniden koşu 1245/1245 geçti. Test/validator kaldırılmadı. Yeni tam CLI testi gerçek geçici SQLite'da DRY_RUN ve byte değişmezliğini, token ve çıktı dizini oluşmadığını doğrular.

### UserLAnd — kurtarma

İzole poller'ı Ctrl+C ile durdurup **tek komutu önce tek başına** çalıştırın:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-plan
```
Beklenen çıktı PLAYER_INPUT_BATCH_V1 JSON ve DRY_RUN (veya açık BLOCKED), ardından shell prompt'udur. Application started plan yanıtı değildir. Uygun arşivlenmiş gelecek maç varsa --player-inputs-all, en son argümansız standart komut kullanılabilir.

03:38 TSİ logu Boston–Orlando'nun arşivlenmiş 03:00 TSİ başlangıcından sonradır. Bu maç için sonradan yeni PREMATCH dakika girdisi üretilmez. Bütün kayıtlar başlamışsa eligible_total=0 meşrudur; yeni başlamamış maçların normal /analyze arşivi gerekir.

**Gerçek yeni-head Telegram / özel telefon arşivi denemesi: BLOCKED.** Yerel gerçek Bash/Git/Python/SQLite testleri gerçek Telegram teslimi değildir. Kullanıcıdaki sonraki JSON sonucu henüz alınmadı.

**Üretim/model kararı: NO-GO.** Bu routing hatası düzeltmesidir; oyuncu modeli doğruluğu, kalibrasyon veya güven artışı iddiası yok. Eski skorlar, arşivler, Fly diski/snapshot ve secret değerleri korundu.

<details><summary>Korunan FAZ 92.9 ve önceki kanıtlar</summary>

Maç öncesi oyuncu-dakika verisi toplamak için tek tek uzun komut gereksinimini giderir. İzole UserLAnd arşivindeki uygun gelecek NBA kayıtları için salt okunur plan ve sınırlı çevrimdışı toplama ekler. **Yeni skor tahmini üretmez; aktif modeli veya eski tahminleri değiştirmez.**

**HEAD:** `029f6206e4606de3fbd11d126210cc13e9b48c78`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`; mevcut PR #89.  
Main merge / Fly deploy / secret / disk / snapshot değişikliği yok.

### FAZ 92.9 — toplu dakika girdisi ve sonuç araçları

- `--player-inputs-plan`: yalnız uygunluk planı; API isteği / eğitim / çıktı dizini veya rapor yazımı yok. Launcher mevcut dalı Git ile günceller.
- `--player-inputs-all`: varsayılan en fazla dört kayıt, sırayla; 48 saatlik ufuk ve başlangıca en az 15 dk. Yeni skor üretimi değil, ayrı kaynak/dakika arşividir.
- Başlamış/sonuçlanmış/yakın başlangıçlı/uzak maçlar, birden çok model kaydı, önceki dakika arşivi ve farklı snapshot bağı ayrı sayılır. Önceden arşivlenen ilk kayıtlar sonraki maçların önünü kesmez.
- Her maçtan önce saat ve seçili snapshot SHA tekrar kontrol edilir. İki ardışık kaynak/girdi engelinde yeni sorgular durur. 180 sn bütçe yalnız maçlar ARASINDA kontrol edilir; sert süreç timeout'u diye sunulmaz.
- SQLite `mode=ro` / `query_only` üzerinden okunur. Dosya SHA'sı 512 KiB bloklarla önce/sonra ölçülür. Dış süreç değişikliği varsa raporlanır; dosya geri yüklenmez veya üzerine yazılmaz.
- `--player-shadow-results`: yalnız önceden prospective kaydedilmiş yeni üçlü model tahminlerini sonraki native sonuçlarla inceler. Eski on sonuç yeni adayın maç öncesi performansına dönüştürülmez. Fit tetiklenmez.
- Altı dosya değişti: player_inputs, launcher, resource probe, iki test modülü ve kapsam belgesi. Frozen matematik, sealed karar/kalibrasyon ve eski evidence/prospective kayıtları değişmedi.

### Son HEAD doğrulaması

- Tam unit suite: **1239/1239 PASS**, 0 failure/error; önceki 1218 +21 yeni test.
- Aynı HEAD'in Docker içi tam suite'i: **1239/1239 PASS**.
- Normal/PDF araştırma görüntülerinde hard **1 CPU / 256 MiB** birleşik provider+PTB+player-input suite'i: ayrı ayrı **270/270 PASS**. Yeni launcher testi yerel Git origin kullanır, ağ kapalı container'da da geçer.
- İki CI koşusundaki en yüksek cgroup bellek gözlemi **165.70 MiB** (karar katmanlı birleşik NBA replay); `memory.max=268435456`, `cpu.max=100000 100000`. Bu değer kaynaklı fixture / yerel HTTP replay ölçümüdür; gerçek Telegram/internet gecikmesi değildir.
- Mevcut hibrit, NBA native payload, karar/kalibrasyon, NBA/EuroLeague salt okunur replay ve ileri EuroLeague rapor/komut adımları PASS.
- [PR CI 43963342982](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43963342982) ve [push CI 43963333543](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43963333543): ikisi de tam HEAD üzerinde **completed / success**.
- Yeni SQLite testi gerçek geçici DB'de byte değişmezliği ve ESPN ID lookup'u doğrular; üretim/telefon DB'sine erişim kanıtı değildir.

Yereldeki ilk yeni SQLite testi kendi snapshot'ından erken bir saat kullandığı için doğru biçimde clock guard'a takıldı. Test zamanı gerçek arşivden sonraya alındı; 15 dk altındaki toplama penceresinin atlanması ayrıca doğrulandı. Validator/test kaldırılmadı.

Cloud bağlantısı yeniden koptu. 20 yeni batch testi yerelde geçti; nihai tam yerel koşu iddia edilmez. Korunan kaynaklar aynı PR dalına GitHub üzerinden aktarıldı; nihai tam koşular yukarıdaki exact-head CI kanıtıdır.

### Gerçek veri / kalan engeller

- Önceki gerçek ESPN box probe dosyaları kurtarıldı: 401909976 ve 401909296, 51 oyuncu satırı, beş açık DNP. Görünen dakika toplamları 240/241 ve 240/241; tam saniye değildir. Kaynak erişimi ilk Philadelphia tahmininden sonra olduğundan geçmiş tahmine geri yazılamaz.
- Bu kaynaklar için yerelde oluşturulan 94.124 baytlık yeni paket (SHA `c13228dc3960d20da6f59282c1bff3dbfa80096110467e66079803b6e430425c`) executor kopmadan önce GitHub'a aktarılamadı; bu commit'te native replay paketi/testi var diye sunulmaz. Önceden commit edilmiş tüm kaynak paketleri korunur.
- Özel telefon arşivinde bu yeni toplama akışı: **BLOCKED / UserLAnd doğrulaması gerekli**. Cloud'da özel SQLite kopyası/test botu erişimi yok; kayıt uydurulmadı.
- Gerçek Telegram E2E: **BLOCKED**. Yerel CLI, PTB ve HTTP mock testleri gerçek Telegram teslimi değildir.
- Yeni oyuncu modeli için doğrulanmış gerçek eğitim/OOS çift sayısı mevcut kanıtta **0**. Kalibrasyon / güven endeksi / Faz13 üstünlüğü iddiası yok. Bireysel savunma, tempo ve dakika belirsizliği eksikleri sürüyor.

**Üretim/model geçişi: NO-GO.** Veri toplamayı kolaylaştırmak ölçülmüş doğruluk iyileşmesi değildir. Araştırma kabul eşikleri ve açık üretim onayı korunur.

### UserLAnd — tek terminal

İzole poller'ı Ctrl+C ile durdurup sırayla:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-plan
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --player-inputs-all
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```
Plan selected/skipped/eligible_total; toplama results/remaining_eligible/reason alanlarıyla gerçek durumu gösterir. BLOCKED durumunda dakika veya başarı sayısı uydurulmaz.

[Kapsam, sınırlar ve sonuç komutu](docs/player-input-batch-phase929-20261116.md)

<details><summary>Korunan FAZ 92.8 ve önceki kanıtlar</summary>

Kadro etkisini mevcut NBA skor modelini değiştirmeyen **ayrı araştırma akışına** ekler. İlk tahminler, SQLite, değişmez kaynaklar, aktif model ve üretim botu korunur.

**HEAD:** `8042f2dc27a0b29872f2797b1b5653106d8c20fd`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`  
**Base:** `feature/hybrid-telegram-optin-20261114`; main merge / Fly deploy / secret değişikliği yok.

### FAZ 92.8 — maç öncesi oyuncu dakikaları ve aynı maçta model karşılaştırması

- Altı eski normal süre maçından açık varsayımlarla 240 dakika beklentisi; oyuncu başına en fazla 48 dakika. Hedef maçın gerçekleşen dakikaları kabul edilmez.
- Güncel kadro, takım/oyuncu kimliği, sezon ve maç başlangıcı bağı; çelişen/belirsiz oyuncu durumu ve eksik kaynakta abstain. Yokluk için ESPN + resmî NBA kaynak gözlemi gerekir; bağımsız tıbbi doğrulama iddiası yok.
- Ayrı eklemeli dakika/kaynak arşivi, UTC üretim/ilk kayıt saatleri, SHA ve tanık yeniden hesaplaması. İlk yayın tipoff öncesi; eski kayıt tekrar gösteriminde yeniden oluşturulmaz.
- Mevcut `HierarchicalStrength` değiştirilmeden, aynı uygun geçmiş maçlarda takım modeli ve oyuncu etkili aday birlikte eğitilir. Faz13 aynen referans bileşenidir. Telegram isteğinde eğitim yoktur.
- Eğitim ve tahmin kaydı bayraklarının birlikte kullanılması herhangi bir okuma/eğitim/yazım başlamadan reddedilir; kaynak erişim maksimumu kadro listesi erişimini de içerir.
- Yeni ayrı modellerde skor/periyot tutarlılığı, gerçek RQMC örnek aralıkları ve ileri sonuç karşılaştırması. Aynı maçın farklı fit sürümleri ayrı gruplarda kalır; örnek sayısı şişirilmez.
- Pinned offline model/CLI; `--player-inputs` ve `--player-shadow-review` launcher seçenekleri. Kadro düğmesi kısa araştırma durumunu gösterir; ağır kaynak toplama/eğitim yapmaz.

### Gerçek veri ve kapsam sınırı

**Uygun gerçek prospective oyuncu-dakika eğitim maçı: 0. Yeni aday için gerçek OOS çift: 0.** Önceki incelemede iki prepared artifact'in players alanı boştu. Özel UserLAnd arşivinin tüm içeriği Cloud'da mevcut değil.

Adayın oyuncu bileşeni yalnız kendi takımının skor etkisidir. Bireysel savunma, ölçülmüş tempo, dakika belirsizliği, doğrulanmış ilk beş ve rol bazlı replacement etkisi öğrenilmedi. Gerçek veriyle aday fit'i, kalibrasyon, güven endeksi veya üstünlük iddiası yok.

Varsayılan eşikler: 100 uygun geçmiş fit maçı, 100 yeni ileri denetim maçı ve 8 gün kümesi; bunlar tek başına GO ölçütü değildir. Ayrık kabul/kalibrasyon incelemesi ve açık onay gerekir.

### Doğrulama

- Son HEAD üzerinde Python tam regresyon: **1218/1218 PASS**, 0 başarısız / 0 hata (önceki 1179 + 39 yeni).
- Aynı HEAD üzerinde üretim Docker görüntüsünde tam regresyon: **1218/1218 PASS**.
- Normal görüntü ve isteğe bağlı PDF araştırma görüntüsü: ayrı ayrı **249/249 PASS**, gerçek cgroup `--cpus=1 --memory=256m --memory-swap=256m`, ağ kapalı.
- PR CI kaynak ölçümü: normal/PDF cgroup peak **85.36 / 108.60 MiB**, raporlanan ru_maxrss **103.02 / 110.30 MiB**, probe süresi **19.86 / 20.70 saniye**. Bunlar toplu sentetik test koşusudur; tek gerçek Telegram isteği gecikmesi değildir.
- Karar katmanı dahil birleşik NBA akışının hard-cgroup peak ölçümü PR koşusunda **165.62 MiB**, push koşusunda **166.34 MiB**; ikisinde de 1 CPU / 256 MiB limiti doğrulandı. Sağlayıcı/PDF paketinin peak değeri bütün pipeline'ın maksimumu değildir.
- Karar/kalibrasyon, NBA native payload, NBA+EuroLeague salt okunur replay ve ileri EuroLeague komut denetimleri aynı Docker job'ında geçti.
- [PR CI](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43956672023) ve [push CI](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43956655827). İkisi de son HEAD üzerinde `completed / success`.
- Değişen 11 dosya: `player_minutes.py`, `player_inputs.py`, `player_shadow.py`, üç yeni test modülü, mevcut roster Telegram testi, test botu, launcher, resource probe ve kapsam belgesi. Silinen dosya / değiştirilen geçmiş tahmin arşivi yok.
- Commit'ler: `e2aac1b` (ayrı araştırma katmanı), `20003a1` (kaynak saati ve sürüm sayımı), `8042f2d` (offline komut yan etki sıralaması).

Gerçek Telegram teslimi / özel arşivle yeni sürüm E2E: **BLOCKED**. Yerel HTTP mock ve ağsız Docker testleri gerçek teslim değildir. Önceki kaynaklı UI telefon kanıtları korunur; bu commit için yeni E2E kanıtı olarak sunulmaz.

Cloud executor kurtarma başarısız oldu; son tam yerel test koşusu iddia edilmez. Önceki yerel 40 hedef test başarılıydı; nihai tam koşular GitHub CI'dan raporlanır. Kaybolan kaynaklar konuşmadaki korunmuş değişikliklerden mevcut dala geri alındı.

**Üretim/model geçişi: NO-GO.** Gerçek prospective dakika eğitimi, bağımsız OOS ve kalibrasyon kanıtı yok. Aktif model değişmedi.

[Kapsam, sınırlar ve güvenli komutlar](docs/player-shadow-phase928-20261116.md)

<details><summary>Önceki FAZ 92.7 ve daha eski kanıtlar — korunmuştur</summary>

İzole NBA analizindeki **Kadro / Sakatlık** düğmesi artık maça bağlı güncel ESPN oyuncu durumlarını ve resmî NBA rapor gözlemlerini sorguluyor. İlk tahmin anındaki kanıt ayrı tutuluyor; sonradan alınan bilgiler eski tahminin girdisi olarak eklenmiyor.

**HEAD:** `4f7dc73f1160c2d45040706d33398ce6698d5730`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`  
**Base:** `feature/hybrid-telegram-optin-20261114`; main merge / Fly deploy yok.

### FAZ 92.7 — gerçek kaynaklı güncel kadro katmanı

- Kök eksik: önceki UI `verified_roster_packets` okuyordu, normal başlatma bu depoyu doldurmuyordu. Yeni katman eski deposu/ilk tahmin saatlerini değiştirmek yerine ayrı güncel gözlem oluşturur.
- Kadro düğmesinde güncel kayıtlar önce, ilk tahminin kanıtı ayrı bölümde sonra gösterilir. Ana /analyze ek kaynak beklemez; kaynak sorgusu yetkili buton akışında çalışır. Uzun çıktı aynı mesajda sayfalanır.
- ESPN summary: exact event ID, ev/deplasman team ID/adları, sezon, başlangıç UTC ve scheduled durumu doğrulanır.
- Resmî NBA sezon sayfasındaki gerçekten yayımlanmış PDF seçilir; uydurma URL/yayın saati yok. Gelecek veya 6 saatten eski rapor seçilmez. Mevcut parser ayrı child'da 128 MiB adres alanı / 4 CPU sn / 6 sn timeout ile çalışır; child'a yalnız allowlist ortam değişkenleri aktarılır, API anahtarları aktarılmaz.
- NBA satırlarında tarih, sıralı matchup, takım ve saat kontrolü; AM/PM içermeyen resmî rapor saatinin sınırlılığı açık gösterilir. Oyuncu ID'leri ESPN doğru takım/sezon roster'ına yalnız tam adla bağlanır. Eşleşmeyen satır ham rapor olarak kalır; fuzzy/uydurma ID yoktur.
- Kaynak durum çatışmaları, eski status tarihi, kaynak/API hatası, eksik PDF bağımlılığı, eksik oyuncu kimliği ve açık ceza bildirimi gösterilir. Boş/eksik rapor “tam kadro” veya “ceza yok” sayılmaz.
- Bu kayıtlar **kaynak gözlemidir; bağımsız tıbbi/uygunluk doğrulaması, onaylı ilk beş veya dakika tahmini değildir**. Skor/model/fit, oyuncu etkisi, kalibrasyon ve confidence değişmez.
- Güncel kaynaklar/SHA/gerçek erişim saati/snapshot bağı ayrı `current-roster` dizinine eklemeli yazılır. Beş dk cache, en eski kaynak erişimi geçerliliği, tek eşzamanlı inceleme, HTTP cooldown ve maç başlangıcı engeli vardır. Önceki prospective/evidence paketleri değişmedi.
- Üretim Dockerfile/requirements değişmedi. PDF bağımlılığı yalnız opsiyonel izole setup ve ayrı `Dockerfile.injury-research` CI imajındadır.
- Güncel otomatik sakatlık/ceza hattı bu increment'te NBA kapsamındadır. EuroLeague/EuroCup replay desteği korunur; bu ligler için güncel injury hattı bağlı diye sunulmaz.

### Gerçek kaynak kanıtı

16 Kasım 2026 ücretsiz kamu kaynaklarına gerçek HTTP erişimi yapıldı. Bunlar telefon ledger'ına bağlı yeni tahminler değildir:
- Boston–Orlando 401909994: **4 ESPN kaydı**, seçilen NBA raporundan bu maça ait ayrıştırılabilir satır **0**; yokluk sağlıklı kadro kanıtı değildir.
- Cleveland–Chicago 401909995: **8 ESPN + 7 NBA PDF satırı**. Bir NBA satırında oyuncu ID'si eşleşmedi; sınır açık tutuldu. Satır sayıları benzersiz sakat oyuncu veya kesin kadro sayısı değildir.
- Kaynak erişim paketi `docs/evidence/roster-phase927-native-20261116.tar.gz`, SHA-256 `3cec9af4bf16a1884e26851a6ddc0a973fdd9309bea7500d16b21c29c89191b3`. Probe tahmin saati/original snapshot SHA null, `SOURCE_ACCESS_PROBE_NOT_FORECAST_LINKED`; **yeni PREMATCH tahmini 0**.
- Gerçek PDF child yerel peak RSS yaklaşık **38,85 MiB**; tek child ölçümüdür, birleşik runtime kanıtı diye sunulmaz.

### Testler

[PR CI — 43916258946](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43916258946): **unit-tests SUCCESS, docker-build SUCCESS**, bütün adımlar dahil.
[Dal CI — 43916250552](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43916250552) da **SUCCESS**; aynı HEAD için her iki koşunun tüm işleri geçti.

| Kontrol | Sonuç |
| --- | --- |
| Exact-HEAD unit suite | **1179/1179**, 0 başarısız; 99,641 sn |
| Docker içi aynı suite | **1179/1179**, 99,866 sn |
| Normal imaj, hard cgroup 256 MiB / tek CPU | **210/210**, 0 hata; peak RSS **102,69 MiB** |
| Opsiyonel PDF araştırma imajı, aynı hard limit | **210/210**, 0 hata; peak RSS **109,93 MiB**, cgroup peak **113487872 bayt** |
| Limit doğrulaması | memory.max **268435456**, cpu.max **100000 100000** |
| İzole hibrit + native NBA + karar/kalibrasyon | **PASS**, eski prospective arşiv değişmedi |
| NBA/EuroLeague arşiv replay + forward EL raporları | **PASS**, eski kayıtlar korundu |

PDF destekli kontrol, gerçek yayımlanmış raporun pinned kaynak paketinden ayrı child ile ayrıştırılmasını ve PTB kadro callback testlerini birlikte çalıştırır. Ağ kapalıdır; runtime ölçümleri internet/Telegram gecikmesi değildir. Normal imaj PDF bağımlılığı eksikliğini doğru etiketleyen yolu da doğrular. Kaynak pin, schema, dosya ve eski archive checks kaldırılmadı.

Yerel önceki tam koşu **1178/1178**, 95,426 sn; son env allowlist testi ve aynı kaynakların yeniden oynatılması dahil **38/38**, güncel ekran sıralaması PTB **6/6** geçti. Son HEAD için yukarıdaki CI sonuçları esastır. Önceki 1135 test korunur; kaynak/clock/identity/hash, disk/timeout/authorization/cache/pagination, eski kayıt değişmezliği, kaynak çatışması, optional parser ve gerçek native source replay regresyonları eklendi.

**Gerçek yeni-head Telegram E2E: BLOCKED.** Kamu kaynaklarına gerçek erişim ve PTB/Bot API double testleri gerçek Telegram teslimi değildir. Cloud özel test botuna veya telefon ledger'ına bağlanmadı.

### UserLAnd — tek terminal

Çalışan izole botu Ctrl+C ile durdurup bir kez:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --roster-setup
```
Bu yalnız izole venv'e PDF bağımlılığını kurar ve mevcut botu başlatır. Sonraki açılışlarda normal başlatıcı yeterlidir. Opsiyonel kurulum başarısızsa normal başlatıcı ESPN gözlemi ve eksik PDF doğrulamasını gösterebilir.

Telegram'da doğru tarihli tek /analyze komutu, ardından **Kadro / Sakatlık** düğmesi. Kaynaklar beş dakikaya kadar cache'lidir. İlk skor veya tahmin üretim zamanı değişmez. Maç başladıktan sonra güncel kaynak eski PREMATCH verisine dönüştürülmez.

**Üretim/model kararı: NO-GO.** Bu kaynak/görünüm entegrasyonu, doğruluk veya kalibrasyon iyileşmesi iddiası değildir. İlk beş, oyuncu etkisi, yeterli kalibrasyon örneklemi ve gerçek yeni-head Telegram E2E eksikleri sürüyor. Main/Fly/secret/disk/snapshot değişikliği yok.

Detay: [FAZ 92.7 kaynak, bütçe ve sınırlılıklar](docs/current-roster-phase927-20261116.md).

<details>
<summary>Korunan önceki FAZ 92.6 giriş, FAZ 92.5 görünüm ve FAZ 92.4 doğrulama kanıtları</summary>

İzole test botu tek mesaja yapıştırılan çoklu `/analyze` komutlarını artık model çağrısından önce tek kullanım yanıtıyla durduruyor. Çıplak/geçersiz komutlar anlaşılır Türkçe yardım alıyor; geçerli tek komut mevcut handler'a aynı takımlar ve aynı tarihle devam ediyor.

**HEAD:** `070b2b51bbf60393f19e86508bbb58113d6800d7`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`  
**Base:** `feature/hybrid-telegram-optin-20261114`. PR araştırma taslağıdır; main merge veya Fly deploy yok.

### FAZ 92.6 — Telegram giriş hata ayrımı

Kullanıcının sekiz komutu tek mesaj halinde eski parser'a verildiğinde ilk `vs` sonrasına sonraki yedi komut da katılıyor. Deplasman adı 300 karakteri aşıyor ve `NONEMPTY_BOUNDED_NAME_REQUIRED` yeniden üretiliyor. Gerçek update zarfı Cloud'da yok; tek mesaj teslimi bağımsız doğrulanmış gibi sunulmaz.

- Yeni `AnalyzeInputGuard`, yetkilendirmeden (-100) sonra ve mevcut analizden önce (-60) çalışıyor. Birden çok komutu topluca çalıştırmıyor; model/ledger'a ulaşmadan bir yanıt gönderip `ApplicationHandlerStop` ile duruyor.
- Boş komut, eksik parametre, 300 karakteri aşan/normalize edilemeyen takım adı sabit, sınırlı Türkçe yardım alıyor. Kullanıcı girdisi veya exception içeriği geri yansıtılmıyor.
- Geçerli tek komutun tırnakları/satır devamı korunuyor; bot kullanıcı adı eki destekleniyor. Tarih, takım, model ve snapshot değiştirilmiyor.
- `FIXTURE_LOCAL_DATE_MISMATCH` doğru çalışan ayrı zaman koruması. Kullanıcının ESPN 401909994 çıktısında Boston–Orlando **17 Kasım 00:00 UTC = 03:00 TSİ**. `2026-11-16` otomatik olarak `17` yapılmıyor. Doğru komut `/analyze NBA 2026-11-17 Boston Celtics vs Orlando Magic`; maç başlamışsa yeni PREMATCH engeli sürüyor.
- Main parser, üretim handler'ları, fikstür kimliği/tarih katmanı, sealed karar/kalibrasyon ve model matematiği değişmedi. Eski prospective/evidence dosyalarına dokunulmadı.
- Değişen dosyalar: `hybrid_engine/analyze_input.py`, `hybrid_engine/test_bot.py`, `hybrid_engine/provider_runtime_probe.py`, `tests/test_analyze_input_guard.py`, [kanıt notları](docs/analyze-input-guard-phase926-20261116.md).

### Doğrulama

- Cloud yerel tam suite: **1135 başarılı, 0 başarısız**, 80,759 sn; mevcut 1123 + 12 yeni test.
- Hedef giriş/tarih/tırnak regresyonları: **38/38**.
- Yeni PTB testleri gerçek Application/CommandHandler sırası, bir yardım yanıtı, model çağrısının kesilmesi, yetkisiz sohbet, geçerli komutun tek kez değişmeden iletilmesi ve eski arşiv baytlarının korunmasını doğruluyor.
- Exact HEAD GitHub CI: [PR koşusu 43903326260](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43903326260) ve [dal koşusu 43903309038](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43903309038) **SUCCESS**; unit-tests ve docker-build, bütün runtime adımları dahil geçti.
- PR unit suite **1135/1135** (95,887 sn), Docker suite **1135/1135** (80,879 sn).
- Hard cgroup 256 MiB / tek CPU sağlayıcı+PTB kontrolü **166/166**, 0 hata. Peak RSS **96,96 MiB**; memory.max **268435456**, cpu.max **100000 100000**.
- Karar katmanıyla birleşik native NBA replay **PASS**; peak RSS **103,11 MiB**, cgroup peak **171429888 bayt**; Model / Kaynak callback sağlık kartı doğrulandı, orijinal prospective arşivi değişmedi.
- İzole hibrit, native NBA, karar/kalibrasyon koruması, NBA/EuroLeague salt okunur replay ve ileriye dönük EuroLeague komut/rapor kontrolleri **PASS**. Gerçek Telegram teslimi değildir.

**Yeni HEAD gerçek Telegram E2E: BLOCKED.** Bellek içi veya yerel HTTP Bot API double gerçek Telegram teslimi değildir; Cloud'da özel test botu erişimi kullanılmadı.

UserLAnd'da izole botu Ctrl+C ile durdurup:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```
Telegram'da her komutu ayrı mesaj gönderin. `/nba 2026-11-17` listesindeki doğru TSİ tarihli komutları kullanın. Eski tahminler yeniden üretilmez.

**Üretim kararı: NO-GO.** Giriş ve görünüm düzeltmesi doğruluk/kalibrasyon artışı değildir. Gerçek yeni-head E2E ve mevcut model/veri/kalibrasyon eksikleri devam ediyor. Main merge, production deploy, secret/disk/snapshot değişikliği yapılmadı.

<details>
<summary>Korunan önceki FAZ 92.5 görünüm ve FAZ 92.4 hata/sağlayıcı kanıtları</summary>

İzole NBA `/analyze` görünümü artık skorları ve ham model aralıklarını koruyarak **model yönü → ham olasılık → yönün güvenilirliği → kısa gerekçe** sırasını gösteriyor. Uzun piyasa ve kaynak dökümleri düğmelerin arkasında, aynı mesajda sayfalanıyor.

**HEAD:** `e02be465f3d8fdcbb04233eae870fa9bb80e3b56`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`  
**Base:** `feature/hybrid-telegram-optin-20261114`. Main merge / Fly deploy yok; PR araştırma taslağıdır.

### Son değişiklik — FAZ 92.5

- Skor, toplam, fark ve P25–P75/P05–P95 özgün snapshot'tan gelir. Tam maç toplam baremi için yalnız güncel native kaynakla bağlanmış kart ana ekrana taşınır. Diğer platform/barem/periyotlar Piyasa bölümündedir; olasılık veya EV'ye göre platform seçilmez.
- Ham örnek frekansı güven endeksi sayılmaz. **“Yönün güvenilirliği: Henüz yeterince doğrulanmadı”**, `NOT_CALIBRATED` ve güven endeksi yok bilgileri korunur. Push/eşitlik kütlesi korunur; ortalama ile yön çelişirse yanıltıcı gerekçe kurulmaz.
- Güncel doğrulanmış barem yoksa sayı/yön uydurulmaz. Eski/manual/maç sonrası gözlemler arşiv olarak ayrıntıda gösterilir. Ödeme/OT kapsamı, EV engelleri, sağlık kartı ve kaynak/zaman/SHA izleri Model / Kaynak'ta korunur.
- Önceki/Sonraki düğmeleri aynı mesajı düzenler. 128 piyasa kartı gösterim sınırı açık bildirilir; kayıtlar silinmez. HTML cache 64 rapor / 8 MiB bütçeli; süresi dolan fiyat ve maç başlangıcı callback sırasında arşiv etiketi alır.
- NBA canlı izole premium yol güncellendi. EuroLeague, EuroCup ve tarihsel replay desteği korunur; tüm liglerin yeniden tasarlandığı iddia edilmez.
- Frozen model/fit, skor üretimi, sealed karar/kalibrasyon politikaları, mevcut prospective/evidence kayıtları, üretim botu, disk ve secret'lar değiştirilmedi.

### Doğrulama

[GitHub Actions — e02be46](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43898080119): **unit-tests SUCCESS; docker-build SUCCESS**, bütün adımlar geçti.

| Kontrol | Sonuç |
| --- | --- |
| Tam suite | **1123 başarılı, 0 başarısız**; önceki 1091 korunuyor, 32 yeni test |
| Docker içi aynı suite | **1123/1123** |
| Hard cgroup 256 MiB / 1 CPU sağlayıcı + PTB kontrolü | **154/154**, 0 hata; process peak RSS **96,89 MiB**, cgroup memory.max **268435456**, cpu.max **100000 100000** |
| Native NBA birleşik komut replay | **PASS**; 32 komut, 4 izole snapshot; Model / Kaynak callback **1**, edit **1**, sağlık kartı ayrıntıda doğrulandı |
| Karar/kalibrasyon katmanıyla hard-cgroup native NBA replay | **PASS**; peak RSS **104,56 MiB**, cgroup peak **173506560 bayt (165,47 MiB)**; 5 karar batch'i, 0 seçili piyasa; orijinal prospective arşivi değişmedi |
| NBA + EuroLeague arşiv replay | **PASS**; mevcut arşiv değişmedi, yeni PREMATCH kaydı 0 |
| İleriye dönük EuroLeague komut/rapor replay | **PASS**; mevcut arşiv değişmedi, yeni PREMATCH kaydı 0 |

Bunlar dondurulmuş native/synthetic girdilerle yerel HTTP Bot API double kontrolleridir; internet gecikmesi, gerçek sağlayıcı kimlik doğrulaması veya gerçek Telegram teslimi kanıtı değildir.

İlk `64902db` koşusunda unit ve Docker suite 1123/1123, bounded provider probe 154/154 geçti; birleşik NBA runtime denetimi eski ana mesaj sağlık kartı beklentisinde durdu. `e02be46` bu kontrolü kaldırmadan gerçek PTB Model / Kaynak callback'i ve editMessageText teslimini doğruluyor. Yeni regresyonlar bozuk olasılık reddi, fixture/model/zaman eşleşmesi, kaynak eskimesi, push/handikap işareti, HTML, sayfalama, tek mesaj davranışı, cache sınırı ve değişmezlik kontrollerini kapsıyor.

Cloud çalışma ortamı test sırasında bağlantısını kaybetti; aynı dal GitHub üzerinden atomik commit/ref güncellemesiyle tamamlandı. Yerel son tam test koşusu yapılmış gibi raporlanmaz; yukarıdaki GitHub Actions tam HEAD sonuçları esastır.

**Yeni sürüm gerçek Telegram E2E: BLOCKED.** Cloud'da özel test botuna doğrudan erişim yok. Yerel HTTP/PTB testleri gerçek Bot API teslimi değildir. Kullanıcının önceki sürüm telefon çıktıları yeni HEAD için E2E kanıtı sayılmaz.

UserLAnd'da tek terminalde izole botu Ctrl+C ile durdurup:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Ardından geçerli maçın `/analyze` komutu ve Piyasa / Sonraki / Model–Kaynak / Özet düğmeleri denenmeli. Aynı snapshot yeniden gösterilir; geçmiş tahmin güncellenmez.

**Üretim kararı: NO-GO.** Bu değişiklik sunum iyileştirmesidir; doğruluk veya kalibrasyon artışı iddiası yoktur. Gerçek E2E, sınırlı bağımsız sonuç örneklemi, kadro/tempo ve ödeme kapsamı eksikleri devam eder. Üretim dağıtımı veya ana dal birleştirmesi yapılmadı.

Ayrıntı: [FAZ 92.5 görünüm ve doğrulama notları](docs/telegram-direction-cards-phase925-20261116.md).

<details>
<summary>Korunan önceki FAZ 92.4 ve sağlayıcı/kalibrasyon kanıtları</summary>

İzole araştırma botunda kayıtlı tahminleri değiştirmeden büyük NBA sapmalarını ve donmuş model girdilerini denetleyen katman eklendi. Dondurulmuş geçmişten özellikler/input digest yeniden hesaplanıyor; tutarsız girdiler reddediliyor. `/accuracy` en büyük sapmaları gösteriyor ve Telegram mesajları satır bütünlüğünü koruyor.

**HEAD:** `f19875853ce1fe16e319f03187e75ce704f5171f`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`  
**Base:** `feature/hybrid-telegram-optin-20261114`. Main merge / Fly deploy yapılmadı.

### Son increment — FAZ 92.4

- Kullanıcının gerçek `/predictions NBA` çıktısı: 11 farklı ESPN kimliği, 10 doğrulanmış sonuç, bekleyen Boston–Orlando `401909994`. On finalin resmî ESPN summary belgeleri ve dört periyot/final aritmetiği ayrı, eklemeli sonuç paketinde saklandı.
- Kullanıcının ekranda yuvarlanmış toplamlarıyla MAE **16,801**, RMSE **21,79227**; bu sayılar paylaşılan `/accuracy` ile uyumlu. Washington–Houston, Philadelphia–Indiana ve Toronto–New York toplam kare hatanın **%83,61**'ini oluşturuyor. Bu hata payıdır, güven yüzdesi değildir. Kullanıcı transkripti telefon DB'sinin bağımsız SHA doğrulaması olarak sunulmaz.
- Toronto–New York normal süre **95–95**, OT final **108–112**: 30 uzatma sayısı normal süre performansına girmez.
- Cloud'daki orijinal Philadelphia snapshot `30e32e...a5343` native kaynaklarla denetlendi: toplam **221,788918 → 255**, hata **−33,211082**. Bunun **−30,2842** sayısı ikinci yarıda oluşmuş. Cloud yakalama zamanı 14:14:05 TSİ, kullanıcı telefon kaydı 15:12:17 TSİ; skorlar aynı diye aynı yayın kaydı iddia edilmez.
- Hazırlanmış model **170 maç**, fit sınırı 12 Kasım 23:28:21 UTC. Cloud tahmininde fit yaşı 215.144 sn; iki takımın son-N penceresinde fit sonrası birer yeni maç var. Güncel tarihsel özellikler V1'in çeyrek ağırlıklarını etkiler; tam maç ortalaması donmuş lig/ev/takım hücum/rakip savunma katsayılarından gelir. Katsayı katkıları özgün skoru 1e-8 toleransında yeniden kurar; yeni fit/tahmin/simülasyon yapılmaz.
- Aynı dondurulmuş maç öncesi özelliklerden basit çapraz ortalama toplamı **220,05**, hatası **−34,95**. Bu baseline maç öncesi yayımlanmış gibi gösterilmez, canlı başarı hesabına eklenmez. Tek eşleşmiş native örnek üstünlük kanıtı değildir. Washington/Toronto'nun özgün girdileri Cloud'da yok; nedenleri uydurulmaz.
- Yeni `forecast_error_review`: ilk arşiv / tam model digest / sezon / lig / sonuç erişim zamanı ayrımı; çeyrek toplam hatası, OT dışlama, hata yoğunlaşması, fit yaşı, aynı native altkümede baseline incelemesi. Eksik native girdiler açık BLOCKED; sonuç ölçümü bağımsız devam eder. Sonradan gelen etiket geçmiş zamana sızmaz; aynı maç tekrarları örnek sayısını artırmaz.
- Gerçek bir denetim açığı kapatıldı: özellik dosyasının SHA'sını kontrol etmekle yetinilmiyor; özellikler ve input digest, hash'i sabit orijinal geçmişten yeniden hesaplanıyor. Yeniden hash'lenmiş tutarsız özellik/iz reddediliyor.
- `/accuracy` salt okunur hata özeti ekler. `/predictions` ve rapor mesajları satır sonunda bölünür; kısa “TSİ” satırı parçalanmaz. Aşırı uzun tek satır UTF-16 sınırında kayıpsız bölünür.
- Yeni launcher `--error-review`: Git güncelleme, bot/token bootstrap, ağ, fit, DB veya mevcut snapshot yazması yok. Yalnız ayrı hash'li kalite raporu. Önceden kayıtlı plan varsa salt okunur yüklenir; plan yoksa yeni kayıt/backdate yapılmaz. Sealed kalibrasyon politikasına dokunulmadı.

### Doğrulama — bu HEAD

- Yerel tam suite **1091/1091 PASS**, 0 failure/error; önceki **1056 test +35 yeni test**. Düzeltme sonrası son tam koşu 80,123 sn.
- Yeni native/profile/sonuç/Telegram/plan testleri **35/35 PASS**. Restricted-network ilk hedef koşusu yerel async I/O nedeniyle sonuç vermeden kesildi; loopback izniyle yeniden koşu geçti. Test devre dışı bırakılmadı.
- Birleşik provider + gerçek PTB loopback + hata inceleme probe **122/122 PASS**, yerel peak RSS **95,43 MiB**. Bu host 8 GiB/2 CPU; hard limit kanıtı aşağıdaki CI ile ayrı verilir.
- Cloud'daki var olan tek Philadelphia DB'sinde offline CLI: integrity **ok**, DB byte'ları değişmedi; mevcut DB kopyası henüz sonuç taşımadığından settled=0 raporlandı. Resmî sonuçla ayrı native inceleme DB'ye yazmadan yapıldı. Telefon DB'si güncellendi iddiası yok.
- `main.py`, Faz13, altı frozen kaynak, sealed karar/kalibrasyon kaynakları ve var olan prospective/evidence dosyaları korundu. Yalnız yeni resmî final paketi eklendi.
- İlk `2c0e9fa` push Docker koşusunda 1091/1091 suite geçti; hard-limit probe 122 testte 1 launcher harness error verdi: tmpfs `noexec` üzerinde taklit Python dosyasını yürütme girişimi exit 126. Son commit kurulu yorumlayıcı symlink'i ve plaintext mock modül kullanır; test atlatılmadı, container kısıtları gevşetilmedi. Düzeltme sonrası yerel 1091/1091, 35/35 ve 122/122 geçti.
- **Son HEAD için PR ve push CI tamamı PASS:** [PR run 43873862576](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43873862576), [push run 43873853149](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43873853149). Her iki run'da unit suite ve Docker suite **1091/1091**, 0 failure/error; image build, bounded NBA/EuroLeague forward/replay/decision kontrolleri başarılı.
- Düzeltme sonrası hard-limit birleşik probe **122/122 PASS**, 0 failure/error: `memory.max=268435456`, `cpu.max=100000 100000`, read-only container / noexec tmpfs / network none korunuyor. Peak RSS PR **98.29296875 MiB**, push **97.50390625 MiB**. Gerçek internet veya Telegram E2E performansı olarak sunulmaz.

### Kullanım ve karar

Yeni dal kodu için izole botun kendi terminalinde Ctrl+C sonrasında:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Bot çalışırken ikinci terminalde yerel on maçın native girdilerini incelemek için:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --error-review
```
JSON'daki `error_review_settled`, `native_input_profiles`, `top_total_errors` kapsamı gösterir. Çıktı `data/quality-phase924/reports` altında; mevcut tahmin/DB/plan değişmez.

**Production NO-GO.** Bu yeni HEAD için doğrudan gerçek Telegram E2E **BLOCKED** (Cloud test erişimi yok); kullanıcının önceki gerçek teslimleri bu sürümün teslim makbuzu sayılmaz. On maçta otomatik kalibrasyon yok. Ölçülmüş pace, oyuncu/rotasyon etkisi, periyot belirsizliği ve bookmaker ödeme/OT kapsamı eksikleri sürer. Bu on maçta aynı anda yayımlanmış Faz13 karşı kohortu yok; üstünlük iddia edilmez. Faz13 varsayılanı korunur; main merge / Fly deploy / ücretli servis / üretim secret-disk-snapshot değişikliği yok.

[FAZ 92.4 ayrıntıları](https://github.com/Girayzeynal/zeynal-bot-core/blob/f19875853ce1fe16e319f03187e75ce704f5171f/docs/forecast-error-review-phase924-20261116.md) · [Test/native kanıtı](https://github.com/Girayzeynal/zeynal-bot-core/blob/f19875853ce1fe16e319f03187e75ce704f5171f/docs/forecast-error-review-phase924-evidence-20261116.json) · [Eklemeli resmî sonuç paketi](https://github.com/Girayzeynal/zeynal-bot-core/blob/f19875853ce1fe16e319f03187e75ce704f5171f/docs/evidence/phase924-append-only-official-nba-finals-20261116.tar.gz)

<details>
<summary>Önceki FAZ 92.3 sağlayıcı / Türkçe piyasa / güncel karar kanıtları (33c99f1)</summary>

İzole hibrit araştırma botunda skor tahminleri korunurken gerçek sağlayıcı gözlemleri, Türkçe piyasa satırları ve ayrı güncel değerlendirme arşivi eklendi. Sonradan alınan fiyatlar artık özgün tahmin zamanı değiştirilmeden ayrı bir karar saatinde incelenir. Eksik ödeme/uzatma kuralı veya kalibrasyon, “NO EDGE” ya da yüksek güven olarak sunulmaz.

**HEAD:** `33c99f17906a053f073e79ee49b95e141457945f`  
**Dal:** `feature/hybrid-market-roster-evidence-20261114`  
**Base:** `feature/hybrid-telegram-optin-20261114`. Main merge / Fly deploy yapılmadı.

### Son değişiklik: Türkçe görünüm ve güncel karar kaydı

- FanDuel, BetOnline.ag, LowVig.ag ve DraftKings marka/kimlikleri korunur. Maç/dönem, toplam sayı, takım toplamı, handikap, durum ve hata açıklamaları Türkçedir. Kaynak JSON anahtarları, fiyatlar, bookmaker ID ve SHA değerleri değişmez. `NOT_CALIBRATED` görünür kalır.
- Eski `market_views.assess` fiyatı ilk tahmin zamanına göre denetler; bu politika ve sealed `decision_layer.py` / `calibration_guard.py` değişmedi. Yeni native fiyat adaptörü katalog+detay belgelerini kendi SHA adreslerinden yeniden okuyarak parser üyeliğini doğrular; caller “verified=true” bayrağı kabul edilmez.
- Yeni `current_market_review`: özgün tahmin UTC, gerçek güncel değerlendirme UTC, fiilî ilk kayıt UTC ayrı tutulur. Sonraki fiyat güncel araştırmada kullanılabilir; geçmiş tahminin girdisi veya o andaki avantajı sayılmaz. 10.000 QMC örneği özgün model/input ve sample SHA'larından tekrar doğrulanır; yeni tahmin/eğitim yok.
- Ayrı, içerik adresli `data/current-market-reviews/review-*.json` kayıtları: ilk snapshot/model/örnek SHA, fiyat kaynağı, karar saati, ilk kayıt saati, gerekçeler ve payload SHA. Aynı manifest idempotent; bozuk kayıt üzerine yazılmaz. SQLite açılmaz; sayı/boyut bütçesi dolunca silmek yerine hata verilir. Fiilî kayıt başlangıca yetişmezse `POST_TIPOFF_REVIEW_ONLY`.
- Bu kararlar ilk tahminin başarı/kalibrasyon hesabına girmez; çok sayıda fiyat tek maçın bağımsız örnek sayısını artırmaz. Kalibrasyon/güven endeksi ve seçim kapalıdır.
- Gerçek fiyat için `1 / oran` yalnız iade dışı koşullu başa baş matematiği olarak gösterilir. Ham normal süre kütlesinden ayrı tutulur. Ham EV için platform/lig/dönem/piyasaya özgü, zamanında geçerli ödeme kuralı ve gerekiyorsa gerçek OT örnekleri şarttır. Tamsayı iadeleri korunur; bölünmüş çeyrek baremler kapalıdır.
- **Canlı ödeme/OT kuralı adaptörü henüz bağlı değildir.** Gerçek bookmaker kuralı uydurulmadı; mevcut gerçek satırlarda EV'nin açıldığı veya kalibrasyonun tamamlandığı iddia edilmez. Sentetik kurallar yalnız matematik yolunu sınar.

### Sağlayıcı bağlantısı ve doğrulanmış engeller

- Fly secret'ları UserLAnd/Cloud'a kendiliğinden geçmez. Araştırma anahtarları legacy bootstrap temizliğinden önce yakalanır; private owner-only test dosyası literal/allowlist ve symlink kontrolüyle okunur. URL/log/istisna içinde anahtar yok; redirect ve secret-echo reddedilir.
- İsteğe bağlı Fly importer yalnız zaten **started** olan `zeynal-bot-core / 830932f77d2598` makinesinin çalışan ortamındaki veri anahtarlarını yerel izole dosyaya aktarır. Remote yazma/DB/yeniden başlatma/deploy yok. Staged secret aktive edilmez.
- Kullanıcının gerçek terminal çıktısında Odds spor kataloğu ve API-Basketball hesap durumu authenticated alındı. Bu Cloud'un doğrudan API testi değildir.
- Boston–Orlando ESPN `401909994`: arşiv 17 Kasım 00:00 UTC, native Odds `7c2ac54a119f461bf8fc1a23da536f29` 00:10 UTC. Yalnız NBA'de tekil aynı sıralı takım çifti ve **tam +600 sn** kuralı; genel saat toleransı yok. Çift/reversed/yakın çelişkiler ve katalog-detay kimlik/saat değişimi reddedilir. Maç öncesi sınır en erken **00:00 UTC** kalır.
- Kullanıcı önceki sürümde FanDuel/BetOnline/LowVig/DraftKings gerçek native fiyat ve ham yüzde satırlarının test Telegram botuna ulaştığını paylaştı. Yeni Türkçe/karar arşivi sürümü için doğrudan gerçek Telegram teslimi henüz doğrulanmadı.
- API-Basketball gerçek HTTP 200 içinde `PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED` + `SEASON_ERROR_REPORTED` döndürdü. Kimlik doğrulama geçse de lig/sezon erişimi **BLOCKED**; kod veya staged-secret deploy ile çözüldü sayılmaz. Aynı worker'da lig/sezon reddi bir saat saklanır, gereksiz tekrar sorgusu yapılmaz.
- Günlük istek bütçesi, cache, cooldown, quota-zero, toplam 12 sn provider süresi ve en erken tipoff kontrolü korunur. Varsayılan yalnız h2h/spreads/totals; ek barem/dönemler açık yerel opt-in gerektirir. Tüm platform/piyasa kapsamı iddiası yok.
- Nesine kaynak kimliği ve alternatif çizgiler için kaynak bağımsız manuel kanıt yapısı korunur; native Nesine API adaptörü bağlandı iddiası yok. SportsDataIO/balldontlie research entegrasyonu tamamlanmış sayılmaz.

### Doğrulama

- Yerel Python 3.12 tam suite: **1056 / 1056 PASS**, 0 failure/error; önceki 1021 test +35 yeni test, 72.739 sn.
- Yerel birleşik provider + gerçek PTB/loopback probe: **87/87 PASS**, peak RSS **91.8125 MiB**. Host 8 GiB / 2 CPU; bu yerel ölçüm hard 256 MiB kanıtı değildir.
- Yeni callback testi native kanıttan Türkçe Piyasa ekranına ve ayrı karar SHA arşivine gider; score/snapshot digest ve Telegram 4096 UTF-16 sınırı korunur. HTTP loopback gerçek Telegram değildir.
- `main.py`, Faz13, altı frozen kaynak, iki sealed karar/kalibrasyon kaynağı ve `docs/prospective` / `docs/evidence` değişmedi.
- **Bu HEAD için PR ve push CI tamamı PASS:** [PR run 43836746717](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43836746717), [push run 43836738089](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/43836738089).
- Her iki run'da Python 3.11 unit suite **1056/1056**, Docker içindeki suite **1056/1056** başarılı. Docker build ve kalan NBA/EuroLeague replay/forward/decision kontrolleri de başarılı.
- Hard limit provider + Telegram loopback probe **87/87**, 0 failure/error: `memory.max=268435456`, `cpu.max=100000 100000`, `--memory-swap=256m`, `--network none`, salt okunur container. Peak RSS PR **94.44140625 MiB**, push **93.87109375 MiB**. Bu limit kanıtı sentetik provider + yerel HTTP taşımaya aittir; gerçek internet/Telegram gecikme veya teslim testi değildir.

### Üretim kararı ve kullanım

**Production NO-GO.** İleri/disjoint kalibrasyon, gerçek platform ödeme/OT kapsamı ve bu HEAD'in gerçek Telegram teslim kanıtı eksik. Model üstünlüğü veya güven yüzdesi iddia edilmez. Mevcut tahminler, SQLite, Fly diski/snapshot ve secret'lar korunur. Faz13 varsayılanı değişmez.

Çalışan izole test botunun kendi terminalinde Ctrl+C sonrasında:
```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```
Sonra uygun başlamamış maçın `/analyze` çıktısında **Piyasa** düğmesi: Türkçe satırlar, ilk tahmin/ayrı karar zamanları ve karar SHA'sı.

[Son değişiklik ve sınırlar](https://github.com/Girayzeynal/zeynal-bot-core/blob/33c99f17906a053f073e79ee49b95e141457945f/docs/current-market-turkish-phase923-20261116.md) · [Yerel test kanıtı](https://github.com/Girayzeynal/zeynal-bot-core/blob/33c99f17906a053f073e79ee49b95e141457945f/docs/current-market-turkish-phase923-evidence-20261116.json) · [Önceki provider entegrasyonu](https://github.com/Girayzeynal/zeynal-bot-core/blob/33c99f17906a053f073e79ee49b95e141457945f/docs/provider-integration-phase922-20261116.md)

</details>

</details>

</details>

</details>

</details>

</details>

</details>

</details>

</details>

</details>

</details>
