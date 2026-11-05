# FAZ39 — PR #14 inceleme düzeltmeleri

Kaynak inceleme: [2026-11-05 teknik incelemesi](https://github.com/Girayzeynal/zeynal-bot-core/pull/14#issuecomment-6668969290).
Başlangıç commit'i `19555088a86b249829e43aa8f3bb1b060fb02d61`.
PR bağımlı ve taslak kalır; üretim zamanlayıcısı, Fly.io, Telegram ve main değişmez.

## Uygulanan değişiklikler

1. **Git bütçesi ve gecikme ölçümleri.** `local_source()` bütün komutlar ve dosya
   okumaları için ortak bir saniyelik bütçe kullanır. Her Git alt süreci kalan
   süreyle sınırlandırılır. Hata/timeout geçerli bir kaynak kimliği sayılmaz.
   Dosya okuması döndükten sonra bütçe, Git kontrolü bittikten sonra UTC tekrar
   denetlenir. Çekirdekte takılmış bir dosya okuması için gerçek zaman garantisi
   verilmez; dönüşte süre dolmuşsa yazma reddedilir.
2. **Çalıştırma ölçümleri.** `timings` alanı Git kontrolü, `cut_proofs`,
   `ledger.has`, uygulama kilidi, SQLite bağlantısı, `BEGIN IMMEDIATE`, INSERT
   ve SQLite içindeki son kapı için count/error/p50/p95/p99/max değerlerini
   verir. Hatalı işlemler de ölçülür. Bellek her aşamada 4096 örnekle sınırlıdır;
   daha sonraki atılan örnek sayısı raporlanır. Yüzdelikler yalnızca tanımlayıcıdır.
3. **Yinelenen kayıt karşılaştırması.** `ALREADY_RECORDED`, yalnızca mevcut
   paket hash'i, fixture/başlangıç/ev-deplasman, horizon, kullanım modu, model
   SHA, receipt SHA ve özgün receipt içeriği aynıysa döner. Başka geçerli bir
   receipt, başka model veya eski FAZ33 kaydı aynı örnek gibi gösterilmez;
   `EXISTING_CUT_BINDING_CONFLICT` ile reddedilir. Karşılaştırma salt okunurdur.
4. **Taşınabilir hazır kayıt.** Yeni schema v2 receipt'leri, SQL ile değişmez
   UUID veritabanı kimliğine ve LOCAL_ONLY politikasına bağlanır. Tüm SQLite
   dosyası doğru hash ile taşındığında yollar değişebilir; eski receipt veya
   tahmin yeniden yazılmaz. Sadece receipt'i başka kimlikli veritabanına
   kopyalamak reddedilir. Schema v1 kayıtlar özgün konfigürasyon hash'iyle
   çalışmaya devam eder; geriye dönük dönüştürülmez.
5. **Yerel kurtarma.** `faz39_recovery`, mevcut güvenli SQLite backup/bundle
   katmanını kullanır. Pinlenmiş SHA, SQLite bütünlüğü, tüketilmemiş hazır
   kayıtlar, ledger kimliği ve tahmin bağları hedefe yayından önce geçici
   alanda doğrulanır. Üzerine yazma yapılmaz. Başarılı FAZ39 yeniden denetimi
   sonrasında `FAZ39_RESTORE_VERIFIED.json` yayımlanır. Kurtarma, kaçırılmış
   bir kesiti yeniden yetkilendirmez.
6. **Kaynak hata sınıfları.** Bozuk UTC JSON/şeması ve resmî NBA HTML şeması
   değişikliği açık ret nedenidir. Eksik saat dilimi, başka tarih, ertelenmiş
   maç, bilinmeyen durum, 403/429 veya kaynak hash'i çelişkisi için fallback yoktur.

## Tekrarlanabilir yerel ölçüm ve kurtarma deneyi

Temiz, commit edilmiş FAZ39 dalında, daha önce var olmayan yerel hedefle:

```sh
python -m faz39_probe /absolute/new-probe-directory --samples 128
```

Bu araçta Git ve `perf_counter` ölçümleri gerçek makinede çalışır; saat, NBA,
UTC ve CI kanıtları açıkça sentetiktir. SQLite son kapısı gerçek bağlantı ve
işlem içinde 128 kez çalışır; ayrıca bir **SYNTHETIC_TEST** tahmini kaydedilir.
Paket yeni dizinde, `python -I` ile başlatılan temiz süreçte geri yüklenir.
`report.json`, SHA ile pinlenmiş yerel paket ve kurtarma kanıtı saklanır.
Hiçbir gerçek tahmin sayısı veya model doğruluğu iddiası oluşturulmaz; ağ veya
harici yükleme kullanılmaz. Yeni Cloud runtime doğrulaması değildir.

```sh
python -m faz39_recovery snapshot /absolute/faz39.sqlite /absolute/new-bundle.tar.gz --source-sha COMMIT_SHA
python -m faz39_recovery restore /absolute/bundle.tar.gz /absolute/new-restore --expected-sha256 TRUSTED_SHA256
```

Güvenilir en yeni bundle SHA'sının oturum dışında korunması hâlâ ayrı bir
operasyonel gereksinimdir. Dosya kilidi farklı makine kopyalarını koordine etmez.
Klonlanmış SQLite'lar bağımsız yazıcı olarak etkinleştirilmemelidir.

## Test ve kanıt kapsamı

- `tests/test_faz39_review.py`, 26 ek regresyon ekler. FAZ39 toplamı 56,
  tüm regresyon paketi 781 testtir. 20:04:44→20:05:12, Git timeout/toplam bütçe,
  ön işlem gecikmeleri, SQLite kilidi, son kapı, farklı receipt/model,
  RTT/saat sapması sınırları, resmî şema bozulması ve kurtarma kapsanır.
- İlk geniş koşudaki 12 hata, yardımcı `IsolatedAsyncioTestCase` temizliğinin
  çalıştırıcı olmadan çağrılmasının saat yamalarını sızdırmasından kaynaklandı.
  Temizlik ana testin çalıştırıcısına taşındı; her test sonunda saat ve uyku
  fonksiyonlarının eski kimliklerine döndüğü denetlenir. Özgün maç fikstürleri
  veya model verileri değiştirilmedi. Son tam koşu: **781 başarılı, 0 hata**.
- Başlangıç commit'inde gerçek Cloud dosya sisteminde 128 örnek: Git kaynak
  kontrolü p95 **19.335377 ms**, p99 **20.889231 ms**. Boş sentetik ledger için
  `cut_proofs` p95 **0.302996 ms**, p99 **2.716057 ms**; `ledger.has` p95
  **0.318790 ms**, p99 **1.711846 ms**. Bunlar mobil/üretim ya da yoğun disk
  koşullarını temsil etmez. Yeni commit'in ölçümleri ayrı probe raporuyla verilir.
- Gerçek UTC servisi, ESPN ve NBA 2026-11-05 kaynakları salt okunur sorgulandı.
  401909936 / NBA 0022600187 başlangıcı 2026-11-06 02:00 UTC olarak eşleşti.
  Gerçek NBA yanıtında `__NEXT_DATA__` kaldırılarak türetilen şema hatası
  `OFFICIAL_SCHEDULE_UNAVAILABLE` ile reddedildi. Bu mutasyon sentetik hata
  enjeksiyonudur; gerçek sağlayıcının o anda bozuk olduğu iddia edilmez.

## Doğrulanmayanlar

Ayrı Codex Cloud runtime oluşturma/bağlanma erişimi ve yetkili harici kalıcı
depolama hedefi yoktur. Oturumlar arası gerçek kalıcılık, makine yeniden
başlatma/disk kaybı ve ayrı Cloud kurtarması **DOĞRULANMADI**. Yeni Python
süreci ve dizin deneyi bunların yerine geçirilmez. İşletim sisteminin gerçek
saatini değiştirme, gerçek sağlayıcıya 403/429 ürettirme ve mobil dosya sistemi
deneyi yapılmadı; bu hatalar regresyonlarda enjekte edildi. Gerçek yeni tahmin
sayısı **0**. Üretime hazır olma iddiası yoktur.
