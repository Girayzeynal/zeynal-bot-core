# FAZ 92.5 — Sade Telegram özeti ve model yönü

Mevcut PR #89, feature/hybrid-market-roster-evidence-20261114 dalı.
Başlangıç: f19875853ce1fe16e319f03187e75ce704f5171f.
Main merge veya Fly deploy yapılmaz.

## Uygulanan görünüm

İzole canlı NBA /analyze ana ekranı skor/toplam, varsa güncel doğrulanmış
tam maç toplam baremi için model yönü, ham model olasılığı, yönün güvenilirliği
ve kısa gerekçe gösterir. P25–P75/P05–P95 bantları özgün kayıttan gelir.
Uzun model kodu, sağlık kartı, kaynak saatleri, ödeme/OT kapsamı ve fiyat
matematiği Model / Kaynak ayrıntısına taşınır. Kayıtlı skorlar değişmez.

Yön, baremdeki gerçek dondurulmuş simülasyon örnek frekanslarıyla hesaplanır.
Oranla model skoru harmanlanmaz. Tam sayı eşitlik kütlesi korunur; ham
olasılıklar iade/eşitlik dışına yeniden normalize edilmez. Eşit/draw baskın
dağılımda taraf zorlanmaz. Ortalama ile olasılık yönü uyuşmuyorsa ters bir
gerekçe yazılmaz.

Kalibre edilmiş güvenilirlik veya 0–100 endeksi henüz yok:
“Henüz yeterince doğrulanmadı”, NOT_CALIBRATED ve güven endeksi yok bilgileri
korunur. %99,9 ham olasılık bile “yüksek güven” etiketi üretmez. Gösterilen
yön bahis seçimi veya onaylanmış avantaj değildir.

## Piyasa sayfaları ve kaynak izi

Her platform/period/piyasa/barem kendi kartıdır. Farklı platform fiyatları
birleştirilmez. Model yönü → model olasılığı → yönün güvenilirliği → kısa
gerekçe sırası kullanılır. Piyasa düğmesi Önceki / Sonraki ile aynı mesajı
düzenler; bütün satırlar birden yeni mesaj olarak gönderilmez. Kaynak ayrıntıları
da aynı şekilde sayfalanır. Kadro, periyot, aralık ve özet düğmeleri korunur.

Görünüm sırası olasılık/EV sıralaması değildir. Güncel native satırlar önce,
tam maç toplamı önce, sonra sabit sağlayıcı/platform/çizgi sırası uygulanır.
Ana ekran ilk uygun güncel toplam satırının platformunu açıkça yazar.
Güncel native toplam yoksa arşiv/manual barem ana ekrana güncel yön olarak
taşınmaz. Eski fiyatın ham dağılımı ayrıntıda arşiv etiketiyle görülebilir.

128 kartlık gösterim bütçesi aşılırsa toplam sayı ve sınır açıkça belirtilir;
kaynaklar silinmez. Sohbet cache'i 64 rapor / 8 MiB HTML bütçesiyle sınırlıdır.
Süresi dolmuş/maç başlamış cache görünümü arşiv olarak etiketlenir. Callback,
tek rapor token'ı ve yetkili sohbetle sınırlandırılır; geçersiz sayfa açık
uyarı verir. Kaynak API'leri callback ile tekrar sorgulanmaz.

Yeni kartlar yalnız sunum katmanıdır. Aynı dondurulmuş dağılım ve doğrulanmış
kaynak gözlemleri kullanılır. current_market_review ve sealed karar/kalibrasyon
politikaları değiştirilmez. Orijinal snapshot SHA, örnek hash'i, üretim ve
arşiv zamanları yeniden yazılmaz. Güncel karar journal'ı aynı özgün payload
ile tutulur; görünüm kartları eski kayda eklenmez.

## Kapsam ve doğrulama

Sade premium ana ekran mevcut izole canlı NBA yolunda uygulanır. EuroLeague,
EuroCup ve NBA tarihsel replay yolları korunur; bütün liglerde yeni premium
arayüzün bağlandığı iddia edilmez. NBA/EuroLeague manuel piyasa değerlendirme
altyapısı değişmez.

Çalışma sırasında Cloud exec ortamı bağlantısı kesildi; yereldeki ilk hedef
koşusunda 150 testten 4 eski yerleşim beklentisi başarısızdı. Bunlar sağlık/
provider ayrıntılarının ana ekrandan taşınması ve alternatif baremlerin artık
sayfa üzerinden açılmasıyla ilgiliydi. İlgili testler kaldırılmadan yeni
yerleşimi ve gerçek PTB callback sayfalarını denetleyecek şekilde güncellendi.
GitHub bağlantısı üzerinden aynı dalda atomic tree/commit güncellemesiyle
devam edilir; nihai testler GitHub Actions'ta exact HEAD için doğrulanır.
Yerel son tam suite çalışmış gibi gösterilmez.

Yeni regresyonlar: yön/olasılık/gerekçe sırası, sahte güven üretmeme,
eşitlik/handikap işareti, bütün periyot ortalamaları, bozuk olasılık reddi,
çapraz maç/model/zaman/ortalama uyuşmazlığı, eski/manual/post-tipoff kaynaklar,
cache sınırı ve callback sayfa erişimi. Mevcut PTB+HTTP testleri gerçek Telegram
teslimi değildir. Önceki 1091 test korunur; yeni test sayısı ve son CI sonucu
PR üzerinde açıklanır.

Gerçek yeni sürüm Telegram E2E: BLOCKED — Cloud'da özel test botu erişimi yok.
Yalnız UserLAnd'daki test botu güncellendiğinde gerçek yeni görünüm sınanabilir.

## UserLAnd

İzole test botunun kendi terminalinde Ctrl+C ardından:

    bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh

Daha sonra uygun maçın /analyze komutunu açıp Piyasa / Sonraki / Model–Kaynak
düğmelerini kontrol et. Mevcut arşiv yeniden gösteriliyorsa yeni tahmin olarak
sunulmaz. Telefonun aynı anda birden fazla poller başlatması gerekmez.

Üretim modeli için NO-GO sürer. Bu sunum değişikliği doğruluk veya kalibrasyon
artışı iddiası değildir. Faz13 varsayılanı, üretim botu, veritabanı, disk,
snapshot ve secret'lar korunur; üretime dağıtım yapılmaz.

İlk 64902db CI koşusunda unit ve Docker suite 1123/1123, 256 MiB provider
probe 154/154 geçti. Birleşik native NBA replay kontrolü HEALTH_CARD_NOT_DELIVERED
ile durdu: eski ana mesaj beklentisi vardı. live_runtime kontrolü gerçek
Model / Kaynak callback'ini açıp editMessageText teslimini ve sağlık kartının
ayrıntıda bulunmasını doğrulayacak şekilde güncellendi. Güvenlik kontrolü
kaldırılmadı; yeni detail_callbacks/detail_edits telemetrisi ayrı raporlanır.
