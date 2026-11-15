# FAZ 90 — doğruluk ve kalibrasyon denetimi, 15 Kasım 2026

Başlangıç: PR [#89](https://github.com/Girayzeynal/zeynal-bot-core/pull/89),
`37dc2d3a8c0ccb55e33c5f0ba9a9e827287ec4aa`.
Aynı `feature/hybrid-market-roster-evidence-20261114` dalında devam edildi;
PR'ın hedefi `feature/hybrid-telegram-optin-20261114` olarak korundu.
Tamamlanan fikstür/sonuç/UI işleri yeniden oluşturulmadı.

## Korunan gerçek tahmin

Philadelphia 76ers – Indiana Pacers, ESPN **401909985**.
Başlangıç **15 Kasım 2026 18:00 UTC / 21:00 TSİ**.
Orijinal skor **112.4811443306–109.3077737074**, toplam **221.7889180380**;
Telegram'daki 112,5–109,3 / 221,8 gösterimiyle uyumlu.
10.000 RQMC-Halton örneği, seed 20261112.

Snapshot SHA-256:
`30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343`.
Tahminin skorları, ham olasılıkları, aralıkları, oluşturulma zamanı, kayıt makbuzu,
kaynakları ve hazırlanmış model dosyası değiştirilmedi. Yeni tahmin oluşturulmadı.
Başlangıç commit'indeki **51 arşiv/kanıt dosyası** byte düzeyinde korundu.
Altı sabitlenmiş model/veri kaynağı ve `main.py` değişmedi.

Kullanıcının bu tahmin için bildirdiği gerçek Telegram testi **önceki sürüme ait
kullanıcı doğrulaması** olarak kabul edildi. Yeni kodun gerçek Telegram teslimi
ayrı değerlendirilir; aynı yuvarlanmış skorun görünmesi tek başına yeni commit'in
Bot API makbuzu veya teslim SHA'sı değildir.

## Bulunan ve giderilen sorunlar

### 1. Yanlış kayıtlı fikstür URL'si

Kayıttaki `fixture_source_url`, `dates=20261114` sayfasını gösteriyor ve bu belge
401909985 maçını içermiyor. Aynı değişmez kaynak paketinde `dates=20261115`
belgesi doğru maç, takım, UTC başlangıç ve `STATUS_SCHEDULED` durumunu içeriyor.
Bu, yanlış maçın tahmin edilmesi değil, ilk skor tablosu URL'sinin kaynak alanına
seçilmesinden kaynaklanan bir izlenebilirlik hatasıdır.

Yeni `prediction_audit.py` mevcut alanı **değiştirmeden**, hash'i doğrulanan
orijinal makbuzlardan gerçek fikstür kaynağını bulur. Telegram model/kaynak
ayrıntısında orijinal alan ile doğrulanmış kaynak ayrılır. Geçerli hedef belgesi
yoksa, çelişkiliyse veya zaman/hash/model denetimi geçmezse yanıt yayınlanmaz.
Eski alan geriye dönük düzeltilmiş gibi gösterilmez. Sabitlenmiş V1 üretici
kodunun alan seçimi korunur; düzeltme ayrı denetim/gösterim katmanındadır.

### 2. PDF–satır–zaman bağı

PDF kapısı indirme hash'ini doğruluyordu; fakat ayrıştırılmış satırların aynı
PDF'ye ait olması ve doğrulamanın tahmin öncesi tamamlanması zorunlu değildi.

- Ayrıştırıcı artık `source_pdf_sha256` ve `rows_sha256` taşır.
- Bağımsız doğrulama makbuzu aynı PDF ve aynı satır hash'ine bağlanır.
- Resmî URL'deki yayın zamanı, indirme başlama/bitiş zamanı ve doğrulama zamanı
  kontrol edilir. Sonradan indirilen içerik eski tahmine eklenemez.
- İndirme başlangıcında gerçek saat kontrol edilir; indirme tahmin sınırını
  aşarsa reddedilir. Gelecek tarihli doğrulama da kabul edilmez.
- Altı saatten eski rapor bu kapıda kullanılmaz. Bu muhafazakâr bir veri yaşı
  politikasıdır; istatistiksel olarak öğrenilmiş güven yüzdesi değildir.
- Önceki eksik makbuzlar artık reddedilir; eski raporlara zaman/hash uydurulmaz.

Doğru makbuz bile ilk beş, rotasyon veya dakika etkisini doğrulamaz.
Bu oturumda yeni resmî PDF/oyuncu eşleme paketi bağlanmadı ve skor modeline oyuncu
etkisi uygulanmadı. İzin verilmiş bağımsız operatör doğrulaması hâlâ gerekir;
makbuz bir NBA kriptografik imzası olarak sunulmaz.

### 3. Kalibrasyon ölçümlerinin kapsamı

Önceki periyot MAE'si takım bazındaki çeyrek hatasını ölçüyordu. Artık ayrıca
iki takımın **çeyrek toplamı** ve **devre toplamı** MAE/RMSE/bias değerleri var.
Devre projeksiyonları çeyreklerle kontrol edilir. Geçersiz/sayı olmayan skorlar,
eksik veya normal süreyle çelişen gerçek periyotlar ve normalize edilmeyen
olasılıklar reddedilir.

Galibiyet ölçümleri **ev / normal süre eşitlik / deplasman** sırasını açıklar;
Brier tanımı üç sınıfın kare hataları toplamının ortalamasıdır (0–2).
Üç sınıfın her biri için kalibrasyon hücreleri, gözlenen frekans ve Wilson
aralıkları verilir. Boş hücreler boş kalır. Bunlar kalibrasyon eğitimi değildir.

P25–P75 ve P05–P95 için proper interval score eklenmiştir:
`genişlik + 2/alpha × bant dışı mesafe`, alpha sırasıyla 0,50 ve 0,10.
Böylece çok geniş bant yalnızca kapsadığı için daha iyi sayılmaz.
Aynı sınıf adı altında farklı model digest'leri veya farklı sezonlar birleştirilmez.
100 geçmiş fit / 100 ayrık gelecek değerlendirme / 8 gün kümesi gereksinimleri
mevcut kayıtlı politikadan okunur; bu sayılara ulaşılması otomatik terfi değildir.

### 4. Piyasa ve çok sezonlu sonuçlar

Ev handikabının koşullu yönü artık `OVER/UNDER` yerine `HOME_COVER/AWAY_COVER`
olarak adlandırılır; `ev farkı + ev handikabı > 0` işaret sözleşmesi korunur.
Toplam sayı yönleri ALT/ÜST olmaya devam eder. Uzatma/settlement kapsamı
bilinmeyen gözlem için hâlâ öneri, karşılaştırılabilir edge veya güven yoktur.
Tahmin anında 300 saniyeden eski gözlem ayrıca eski veri olarak işaretlenir.
Yeni barem veya oran üretilmedi.

Sonuç toplayıcı tüm sezonları aynı yerel veritabanında korurken, bir sezonun
skor tablosunu diğer sezon olarak ayrıştırıp döngüyü durdurabiliyordu. Doğrulanmış
belgedeki native sezon alanlarıyla ayrım yapılıyor; sezon alanı eksik içerik
sessizce kabul edilmiyor. Çok sezon, tekrar kontrol, normal süre ve uzatma
sözleşmeleri regresyonla doğrulandı.

## Simülasyon matematiği — ölçülen sonuç

Aynı dondurulmuş model, girdiler ve seed ile **orijinal MC ve QMC örnek hash'leri
aynen yeniden üretildi**; fit, canlı indirme veya yeni PREMATCH kaydı yok.

| Kontrol | Sonuç |
|---|---|
| Ham skor / 1Q–4Q / 1H–2H aritmetiği | Tutarlı, ham tolerans 1e-8 |
| QMC örnek SHA | `68bee56e5eaccdc3835cf0a3240cf7ebb3f5290710a53538d31d91d9eff797a6` |
| QMC / MC maç toplamı P50 | 222 / 222 |
| QMC toplam P05–P95 | 192–252 |
| MC toplam P05–P95 | 192–251 |
| Parametre belirsizliği | x·posterior covariance·xᵀ terimi dahil |
| Sonuç gürültüsü | Empirik eğitim varyansı ayrıca dahil |
| Çeyrek toplamlarının ortalama çapraz korelasyonu | **0,987974** |

Monte Carlo / QMC farkı aynı posteriorun sayısal kontrolüdür; hangi yöntemin
maçları daha iyi tahmin ettiğinin kanıtı değildir. Analitik bağımsız dağılımla
kontrol sadece korelasyon=0 limitinde yapılır; korelasyonlu modele bağımsız
analitik sonuç “gerçek olasılık” diye uygulanmaz.

Mevcut model **empirical-Bayes takım hücum/savunma sayı modeli**dir. Ölçülmüş
pozisyon temposu veya 100 pozisyon başına verimlilik motoru değildir.
Takım skoru yolu çeyreklere deterministik largest-remainder yöntemiyle ayrılır;
çok yüksek çeyrek korelasyonu bu yöntemin sınırlamasıdır. Play-by-play veya
bağımsız çeyrek belirsizliği kalibre edilmiş sayılmaz. P50 veya diğer marjinal
quantile'ların toplamı, toplam dağılımın aynı quantile'ı olmak zorunda değildir;
quantile toplatılarak kayıtlar değiştirilmedi.

Model gürültüsü empirik ham eğitim varyansına dayanır; tam Bayesian noise
posterioru veya maç sonu possession davranışı iddia edilmez. Bu sınırlamaları
kanıtsız bir skor/çeyrek revizyonuyla gizlemek yerine raporladık. Önceki çeyrek
shadow deneyleri yeniden üretilmedi veya üretime yükseltilmedi.

## Kalibrasyon ve gerçek sonuç durumu

Philadelphia–Indiana denetim sırasında henüz başlamadı: `due=0`, `settled=0`,
`pending=1`. Gerçek sonucu veya başarı oranı üretilmedi. Sonuç kontrolü gelecek
maç için ağ isteği yapmadan beklemeye devam eder; orijinal kayıt korunur.

Mevcut üç 13 Kasım EuroLeague kaydına yeni metrikler uygulandı; kayıtlar değişmedi:

| Aynı 3 maç | Bayesian/QMC | Faz13 MC |
|---|---:|---:|
| Takım MAE | 7,8282 | 7,9250 |
| Toplam MAE | 15,6563 | 15,8500 |
| 1Q toplamı MAE | 6,7776 | 6,8000 |
| Toplam P05–P95 interval skoru | 55,6667 | 56,3333 |

Bir gün üzerindeki üç maç üstünlük veya kalibre edilmiş güven kanıtı değildir.
P25–P75 toplam kapsaması 1/3, P05–P95 3/3; Wilson aralıkları geniştir ve maçlar
arası bağımlılık çözülmüş sayılmaz. Önceki walk-forward sonuçları yeni canlı
sonuç gibi karıştırılmadı. Yeni eğitim/kalibrasyon yapılmadı, doğruluk artışı
kanıtlandı denmedi. `NOT_CALIBRATED` ve güven endeksi `None` kaldı.

## Testler ve gerçek Telegram ayrımı

Başlangıçtaki 788 test korunmuştur. Tam son yerel koşu **812 geçti,
0 başarısız**. İlgili **57 test** ve kaynak/model hash denetimi testleri de
geçmiştir. Commit'in tam CI sonuçları PR denetiminde ayrıca raporlanır. Testler devre dışı bırakılmadı. Önceki PDF
pozitif testleri artık açık zaman ve satır/PDF hash'li makbuz kullanıyor;
eski eksik makbuzlara izin vererek yeşil sonuç alınmadı.

Yerel PTB + HTTP Bot API double akışı: **11 komut, 11 yanıt**, tek CPU affinity,
256 MiB adres alanı sınırı, **99,95 MiB RSS**. Bu host'un cgroup'u 256 MiB olarak
sunulmaz; mevcut CI Docker işi gerçek 1 CPU/256 MiB sınırını ayrı ölçer.

Kullanıcının Philadelphia–Indiana için bildirdiği gerçek Telegram testi korunur.
**Bu yeni commit için gerçek Telegram E2E: BLOCKED** — Cloud ortamında dört
ayrı test botu ayarı yok. Yerel HTTP sonuçları gerçek Telegram teslimi değildir.
Üretim token'ına başvurulmadı. Yeni Bot API makbuzu veya kullanıcı mesaj ID'si
uydurulmadı. Yeni kaynak açıklaması ve ayrıntı butonunun gerçek test botunda
görülmesi, erişim sağlandığında ayrıca doğrulanmalıdır.

## Yeniden çalıştırılabilir, çevrimdışı denetim

Mevcut izole dizindeki var olan kaynaklar kullanılarak:

```sh
python3 -m hybrid_engine.prediction_audit \
  --snapshot docs/prospective/handoff-20261115/nba-30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343.json \
  --snapshot-sha 30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343 \
  --assets-directory "$ISOLATED_ASSETS_DIRECTORY" \
  --output-directory "$ISOLATED_AUDIT_DIRECTORY" \
  --replay
```

Bu komut yeni tahmin üretmez; ayrı, hash'li denetim dosyası ekler. Mevcut
sabitlenmiş kaynak kapsülünü yeniden indirmek, canlı fikstür sorgulamak veya
Bot API'ye erişmek gerekmez. Tahmin/kaynak dosyaları üzerinde yazma işlemi yok.

## Değişen bileşenler ve karar

- `prediction_audit.py`: native kaynak, clock, model, aritmetik ve MC/QMC audit;
  `test_bot.py`: izole canlı yanıt kapısı ve kaynak açıklaması.
- `live_metrics.py`, `ledger_reports.py`, `forward_reports.py`: sınıf/çeyrek/devre,
  interval score, model/sezon ayrımı ve görünür rapor kapsamı.
- `nba_injury_capture.py`, `nba_injury_pdf_parser.py`,
  `nba_injury_verification.py`: indirme ve satır/PDF/zaman bağı.
- `nba_ledger_settlement.py`: çok sezonlu sonuç toplama.
- `observed_markets.py`, `market_evidence_report.py`: handikap yönü ve eskilik.
- `test_phase90.py` ve mevcut iki PDF test dosyası: karşı örnek/regresyonlar.

**İzole araştırma doğrulaması: GO. Modelin üretime terfisi: NO-GO.**
Nedenler: bu head için yeni gerçek Telegram teslimi yok; doğrulanmış kadro,
rotasyon, pace ve uygun piyasa settlement girdileri eksik; yeterli ayrık OOS
kalibrasyonu ve periyot belirsizliği kanıtı yok. Üretim modelinin tahmin gücünün
arttığı iddia edilmiyor. Fly.io ana botu, veri diski, snapshot'lar ve secret'lar
ile ilgili işlem yapılmadı; main merge veya deploy yok.

[Ayrıntılı makine kanıtı ve korunan hash'ler](hybrid-phase90-evidence-20261115.json).
