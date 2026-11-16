# FAZ 92.4 — Büyük tahmin hatalarının denetimi

PR #89, mevcut `feature/hybrid-market-roster-evidence-20261114` dalı.
Başlangıç commit'i: `33c99f17906a053f073e79ee49b95e141457945f`.

## Gerçek sonuçlar ve kanıt düzeyleri

Kullanıcının paylaştığı Telegram listesi 11 farklı ESPN kimliği içeriyor:
10 sonuçlanmış tahmin, bekleyen Boston–Orlando `401909994`. On tamamlanmış
maçın ESPN summary belgeleri indirilip final durumu, maç kimliği ve periyot/final
toplamı doğrulandı. Yeni sonuç paketi eklemelidir; önceki tahmin arşivleri değişmez.

Kullanıcının **ekranda yuvarlanmış toplamları** ile doğrulanmış normal süre
sonuçları karşılaştırıldığında MAE **16,801**, RMSE **21,79227** bulunur.
Bu, paylaşılan `/accuracy` 16,80 / 21,79 değerleriyle uyumludur. Telefon SQLite'ı
Cloud'da bulunmadığı için on tahminin orijinal SHA/girdi doğrulaması yapılmış
sayılmaz. Ekran toplamı ile iki yuvarlanmış takım skorunun toplamı arasındaki
0,01 farklar ayrı tutulur; eski değerler düzeltilmez veya değiştirilmez.

| ESPN | Maç | Ekran toplamı | Gerçek normal süre toplamı | Tahmin − gerçek |
|---|---|---:|---:|---:|
| 401909991 | Washington–Houston | 220,93 | 266 | −45,07 |
| 401909985 | Philadelphia–Indiana | 221,79 | 255 | −33,21 |
| 401909990 | Toronto–New York | 218,92 | 190 | +28,92 |

Bu üç maç mutlak toplam hatanın **%63,81**, kare hatanın **%83,61**'ini
oluşturuyor. Bunlar hata yoğunlaşması paylarıdır; güven veya başarı yüzdesi
değildir. Maçlar çıkarılarak sonuç iyileştirilmez. Toronto normal süresi 95–95,
uzatmalı finali 108–112: 30 uzatma sayısı normal süre ölçümüne girmez.

## Philadelphia: orijinal girdilerle doğrulanabilen bölüm

Cloud'da bulunan orijinal snapshot:
`30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343`.
Bu kayıt 15 Kasım **14:14:05 TSİ**'de üretilmiştir; telefon kaydındaki
**15:12:17 TSİ** ile aynı yayın kaydı olduğu iddia edilmez. Skorlar örtüşse de
farklı yakalama zamanları birleştirilmez.

- Dondurulmuş tahmin 112,481144–109,307774; toplam **221,788918**.
- Resmî normal süre 131–124; toplam hata **−33,211082**.
- 1Q–4Q toplam hataları: **−8,0991 / +5,1722 / −13,8652 / −16,4190**.
- İlk yarı toplam hatası **−2,9269**, ikinci yarı **−30,2842**.
- Model 170 maç üzerinde hazırlanmış; fit sınırı 12 Kasım 23:28:21 UTC.
  Cloud kaydı üretilirken fit yaşı **215.144 saniye**. Her iki takımın son
  on maçında fit sınırından sonra başlayan birer maç var.
- Katsayılar; lig sabiti, ev etkisi, takım hücumu ve rakip savunması olarak
  ayrıştırıldığında orijinal skorlar 1e-8 toleransında yeniden elde ediliyor.
  Eğitim veya yeni simülasyon yapılmıyor.
- Aynı dondurulmuş maç öncesi özelliklerden basit atılan/yenen çapraz ortalama
  toplamı **220,05**, hatası **−34,95**. Bu sonradan incelenen baseline'ın
  maç öncesinde yayımlandığı iddia edilmez; canlı başarı hesabına eklenmez.

Tek maçta hibritin 1,74 sayı daha yakın olması üstünlük kanıtı değildir.
Yüksek ikinci yarı skorunun sakatlık, tempo, rotasyon veya başka bir etkiden
kaynaklandığı bu verilerden kanıtlanamaz. Washington/Toronto'nun orijinal yerel
girdileri olmadan benzer nedensel açıklamalar uydurulmaz.

## Doğrulanmış model sınırlamaları

V1 takım ortalamaları hazırlanmış empirical-Bayes katsayılarından gelir.
Yeni son-N maç verisi çeyrek ağırlıklarını etkiler; güncel skor ortalamaları
takım gücü katsayılarını otomatik yeniden eğitmez. Bu davranış kodda ve
Philadelphia'nın orijinal parametre/girdi dosyalarında doğrulandı.

Ölçülmüş possession temposu, oyuncu dakika etkisi veya doğrulanmış rotasyon bu
modelin girdileri değildir. Çeyrekler deterministik dağıtıldığı için yaklaşık
0,988 ortak hareket vardır. Bunlar önceki FAZ 90 bulgularını koruyan sınırlamalar;
her büyük hatanın kesin nedeni olarak sunulmaz. Parametre varyansı ve artık
varyansı ayrı raporlanır; hiçbirine doğrulanmış güven etiketi verilmez.

Yeni rolling-fit/tempo veya periyot modeli ancak önceden belirlenmiş kronolojik
OOS karşılaştırmasında değerlendirilmelidir. Bu on maçı görüp model ya da bant
ayarı değiştirerek iyileşme iddiası oluşturulmaz. Aynı on maç için yayımlanmış
Faz13 karşı tahminleri bulunmadığından Faz13 üstünlük karşılaştırması tamamlandı
denmez. Faz13 varsayılanı ve mevcut skorlar/bantlar korunur.

## Giderilen denetim ve görüntüleme eksikleri

1. `prediction_audit`: SHA doğrulamasına ek olarak, özellikler ve input digest
   orijinal dondurulmuş geçmişten yeniden hesaplanır. Kaynağa göre tutarsız,
   tekrar hash'lenmiş bir özellik artık kabul edilmez. Gelecek etiketler ve
   hedef maçın kendi sonucu kullanılamaz. Native kaynak/clock kapısı korunur.
2. `forecast_error_review`: aynı fit/sezon/lig ve ilk yayımlanan kayıtlar üzerinde
   en büyük sapmalar, çeyrek hata toplamları, hata yoğunlaşması, model yaşı ve
   eşleşen altkümede basit baseline incelemesi. Eksik girdi dosyası açık BLOCKED;
   native sonuçların ölçümü devam eder. Sonradan gelen sonuç geçmiş zamana sızmaz.
3. `/accuracy`: en büyük üç toplam sapması ve kare hata payını gösterir.
   Kalibrasyon veya model üstünlüğü iddiası eklenmez.
4. Mesajlar mümkünse satır sınırından bölünür; “TSİ” gibi kısa satırlar iki
   mesaj arasında parçalanmaz. Çok uzun tek satır UTF-16 sınırında kayıpsız bölünür.
5. Kalite raporu kayıtlı kalibrasyon planını salt okunur yükleyebilir. İnceleme
   modu planı yeniden kaydetmez veya kayıp planın yerine yenisini üretmez.

## UserLAnd son doğrulaması

Yeni dal kodunu almak için izole botun kendi terminalinde Ctrl+C, ardından:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Bot çalışırken ikinci terminalde de uygulanabilen, internetsiz ve token istemeyen
salt okunur hata/girdi incelemesi:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --error-review
```

Bu mod Git güncellemez, botu başlatmaz/durdurmaz, sonuç indirmez, DB/plan/snapshot
yazmaz. Yalnız `data/quality-phase924/reports` altına yeni hash'li rapor ekler.
Var olan `quality-phase92/calibration-plan/plan-*.json` okunur; yeniden kayıt yok.
Çıktıdaki `error_review_settled`, `native_input_profiles`, `top_total_errors`
yerel on kaydın denetim kapsamını gösterir. Başka bir dizinde tutulan plan veya
eksik kaynak dosyaları otomatik keşfedilmiş/uygulanmış sayılmaz.

Yeni kodun gerçek Telegram E2E teslimi **BLOCKED**: Cloud'da özel bot erişimi yok.
Önceki kullanıcının gerçek `/accuracy` ve `/predictions` kanıtları korunur;
yeni hata özeti/mesaj bölme sürümü için gerçek teslim kanıtı sayılmaz.

**Üretim NO-GO.** Kaynak/tempo/oyuncu eksikleri, periyot belirsizliği ve yeterli
ileri OOS kalibrasyon kanıtı yok. Merge/deploy, Fly diski/snapshot/secret veya
üretim DB değişikliği yapılmadı. Test ve hash kanıtı aynı adlı evidence JSON'dadır.

İlk `2c0e9fa` Docker koşusunda tam 1091 test geçti, fakat 122 testlik kaynak
probe'unda başlatıcı testinin `/tmp` içindeki çalıştırılabilir Python taklidi
`noexec` mount nedeniyle exit 126 verdi (1 error). Test gerçek kurulu yorumlayıcı
symlink'i ve yalnız okunarak çalıştırılan mock modülle düzeltildi. Test
atlatılmadı; container izinleri/256 MiB sınırı değiştirilmedi. Düzeltme sonrası
35 hedef test ve 122 yerel probe testi geçti. Son HEAD'in tam GitHub/Docker
sonuçları PR üzerinde ayrı raporlanır.
