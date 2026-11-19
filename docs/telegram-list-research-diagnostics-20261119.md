# Telegram liste gönderimi ve V3 deneme tanısı

## Cihazdan bildirilen durum

Kullanıcı `ae8381d` sürümünde `/predictions EUROLEAGUE` için
`PREDICTIONS_SEND_FAILED` yanıtını paylaştı. Bu mesaj tek başına gerçek Bot API
hata sınıfını belirtmiyor. Terminaldeki hata sınıfı istendi; özgül cihaz
hatasının kesin nedeni henüz bağımsız doğrulanmadı.

V2 raporu NBA için 191 geçmiş / 171 box-score, EuroLeague için 120 / 113
bildiriyor. Oyuncu bileşeninde iki kaynak doğrulaması ve yeterli ileriye dönük
dakika geçmişi yok. V3 dört kabul, sıfır ayrı yayın gösteriyor; eski `render`
skor denemesinin `captures` nedenlerini göstermeyip yalnız gelecekteki kabul
ve kalibrasyon kapısını gösteriyordu. Bu veriler kullanıcı mesajıdır; Cloud
tarafından kendi cihaz arşivinde yeniden ölçülmüş sayılmaz.

## Testle doğrulanan hatalar ve düzeltmeler

1. İzole bot tek varsayılan executor kullanıyordu. Arka plan fit'i bu işçiyi
   tuttuğunda Telegram teslim günlüğü, komut günlüğü, arşiv okumaları ve DNS
   işleri aynı kuyrukta bekleyebiliyordu. Sentetik kabul edilmiş HTTP yanıtı
   ile test, eski sürümde zaman aşımını yeniden üretti.
2. Bot API 200/ok döndükten sonra yerel teslim günlüğü hatası dışarı taşınıp
   çağırana gönderim hatası gibi görünüyordu. SQLite yazma hatasıyla eski
   sürümde bu da yeniden üretildi. İki regresyon eski `ae8381d` üzerinde hata
   verdi; yeni kodda geçti.
3. İzole giriş noktası artık bir seri arka plan işçisi ve ayrı bir komut/DNS
   işçisi kullanır. Bağlam, scheduler/collector/araştırma görevleri
   oluşturulurken işaretlenir. Arka plan işleri birbiriyle seri kalır.
   V2/V3 fit sırası, model kodu ve kabul politikaları değiştirilmedi.
4. Teslim günlüğü ayrı tek işçide, iki saniyelik bekleme sınırıyla yazılır.
   Yazılamazsa `UNAVAILABLE` ve yalnız hata sınıfı kaydedilir/loglanır;
   başarılı sunucu yanıtı korunur. Gerçek taşıma hatası aynen çağırana gider.
   Eksik günlükten teslim kanıtı uydurulmaz; kayıt ve iletişim durumu ayrılır.
5. Liste açıkça düz metin gönderir. Başarısızlık sabit hata sınıfını ve
   tamamlanan bölüm sayısını gösterir; önceki liste bölümleri yeniden
   gönderilmez. RetryAfter/Forbidden otomatik yeniden denenmez.
   `/test predictions` son liste gönderimini gösterir; ham hata metni,
   token, sohbet kimliği veya dosya yolu göstermez.
6. Yeni, yalnız gözlem yapan V3 sarmalayıcısı son skor ve kalibrasyon
   denemelerini ayrı tutar. Daha sonraki boş/backoff kontrolü son skor
   engelini gizlemez. Hata nedeni/kategorisi `/test research` içinde görünür.
   Sarmalayıcı orijinal sonuç nesnesini döndürür; bilimsel kaynak pinleri ve
   planlar değişmez. Tanı önbelleği bellektedir; yeniden başlatmada yeniden
   gözlem bekler. Eski rapor/snapshot dosyaları güncellenmez.

## Sınırlar ve cihazda tekrar kontrol

Gerçek `/predictions` cihaz hatasının bu kuyruk veya günlük hatalarından
kaynaklandığı henüz kanıtlanmadı. Format, ağ, sunucu veya başka bir hata
olursa yeni sabit sınıf bunun ayrılmasını sağlar. Düzeltmenin gerçek Telegram
sonucu cihazda yeniden denenmelidir; yerel HTTP çiftleri gerçek Telegram
E2E başarısı değildir.

Eski botun terminalinde Ctrl+C, ardından Ubuntu terminalinde:

```bash
bash ~/zeynal-integrated-test/scripts/run_isolated_test_bot.sh
```

`Application started` sonrası Telegram'da ayrı mesajlar:

```text
/predictions EUROLEAGUE
/test predictions
/test research
```

Araştırma ilk kontrolünü tamamlayana kadar V3 denemesi `henüz gözlenmedi`
görünebilir. `PARTIAL_ABSTAIN` tek başına tüm modellerin kapalı olduğunu
göstermez. Oyuncu doğrulaması eksik diye veriler uydurulmaz; yayımlanmış ana
skorlar, eski kabul planları ve mevcut arşivler değiştirilmez.

`/test runtime` içindeki boş `last_analysis`, bu süreçte kullanıcı `/analyze`
yanıtının henüz gözlenmediği anlamına gelir. Otomatik arka plan üretimlerinin
yok olduğu anlamına gelmez. `data_mount_present=false` UserLAnd için bir Fly
disk hatası olarak yorumlanmaz. Bu çalışma Fly.io/main/anahtar/üretim diski
işlemi içermez.
