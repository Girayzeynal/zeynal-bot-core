# FAZ32 — gerçek veri hazırlığı ve araştırma sınırları

FAZ31'in gerçek verilerle eğitilememesinin nedeni yalnızca geçmiş sonuç sayısı
 değildi. Üç özgün referans tahmininin hiçbirinde FAZ31 tarafından o anda
 oluşturulmuş özellik paketi yoktu. FAZ30'daki 36 çeyrek kaydı daha sonra
 materyalize edilmişti; bunları eski tahmin zamanlarına taşımak veri sızıntısı
 yaratırdı. FAZ24 defterleri ve FAZ29/30 kanıtları değiştirilmedi.

## Gerçek veri kapsamı — 5 Kasım 2026 UTC

| Denetim | Sonuç |
|---|---:|
| Önceki FAZ30 geçmiş maçları | 36 |
| Diğer arşivlerden gözlem | 15 + 14 |
| Yeni ESPN özet indirmeleri | 42 |
| Toplam kaynak gözlemi | 107 |
| Farklı tamamlanmış maç | 75 |
| Arşivlerde farklı maç / yeni indirmelerde farklı maç | 54 / 42 |
| İki grubun ortak maçları | 21 |
| Önceki 36'ya göre ek farklı maç | 39 |
| Tam çeyrek / final doğrulaması | 75 / 75 |
| Uzatmalı maç | 3 |
| Kutu skorundan tempo hesaplanabilen gözlem | 107 |
| Gerçek FAZ31 prospektif özellik–etiket çifti | 0 |
| Uygun retrospektif özellik–etiket çifti | 3 |
| Kapsama yetersizliği nedeniyle dışlanan hedef | 72 |
| Hiç maç öncesi gözlemi bulunmayan hedef | 62 |

Maçlar 20 Ekim–5 Kasım 2026 UTC aralığında, ESPN sezon yılı 2027, normal sezon
(type=2) kapsamındadır. Yeni sorgulanan günler: 30 Ekim, 1, 2 ve 4 Kasım.
Son gündeki 14 takvim olayından biri FINAL olarak doğrulanamadı; alınmadı.
Yeni 42 maçın takvimden ayrıştırılmış final bilgisi ve özeti kimlik, başlangıç,
takım ve skor düzeyinde karşılaştırıldı. Bu fazda başka sağlayıcıdan bağımsız
çapraz doğrulama yapılmadı. Mevcut ESPN adaptörünün 403/429 bekleme ve sınırlı
bağlantı denemeleri korundu; erişim engeli aşılmadı.

Her maçın ESPN kimliği, UTC başlangıcı, takım kimlikleri, final/çeyrek/uzatma
skorları ve tüm gözlem/ingestion zamanları
[eşsiz maç dökümünde](evidence/faz32-verified-games-20261105.json) bulunur.
Sonuç/çeyrek toplamları, uzatmadan önce beraberlik, kimlikler ve sezon eşleşmesi
denetlendi. Aynı ESPN kimliği veya aynı takım/başlangıç için çelişkili sağlayıcı
kimliği kabul edilmez. Tekrar aktarımda 42 yeni indirme ve 65 arşiv gözlemi
sıfır ek satır üretti. Farklı gözlem, farklı eğitim örneği değildir.

## Veri katmanı ve zaman kanıtı

`nba_research_store.py` ayrı bir SQLite defterine eklemeli ve UPDATE/DELETE
engelli gözlemler yazar. Eski FAZ24 veritabanına migration veya yazma yapılmaz.
`source_observed_utc`, yanıtın gerçekten gözlendiği/arşivlendiği zamanı;
`ingested_utc`, bu araştırma veritabanına gerçekten alındığı zamanı ifade eder.
Her ikisi de saklanır. Kaynak URL'si, dosya/payload SHA-256 ve kaynak referansı
bulunur. Bunlar yerel bütünlük kanıtıdır; sağlayıcı imzası veya kesin yayın
zamanı değildir. Güncel takım dizini kimlik denetimi sağlar; geçmişte yayımlanmış
takım dizini snapshot'ı olduğu iddia edilmez.

`faz32_collect.py` ücretsiz ESPN takvim/özet toplamasını ve hash doğrulamalı,
idempotent aktarımı sağlar. `faz32_archives.py`, eski FAZ30 kanıtını Git HEAD
sürümüyle karşılaştırır; 15 eski özetin dosya hash'lerini önceden commit edilmiş
indeksle doğrular. Ek BOS–MIL girdi arşivi salt okunur açılır ve özgün girdi
bütünlüğü doğrulanır. Gözlem zamanları bugünkü indirme zamanı gibi yeniden yazılmaz.

İki seçim politikası ayrı tutulur:

- **PROSPECTIVE:** hem kaynak gözlemi hem sisteme giriş zamanı kesimden önce
  olmalıdır. Yeni dönem kaydı gerçek materyalizasyon zamanını da taşır.
- **RESEARCH_SOURCE_CLOCK:** arşivde kanıtı bulunan eski kaynak gözlemleri,
  tarihsel hedef başlangıcından bir saniye önceki *varsayımsal* kesime göre
  seçilir. Yeni oluşturulma ve ingestion zamanları aynen korunur. Çıktı
  `RETROSPECTIVE_RESEARCH` olarak etiketlenir; özgün canlı tahmin değildir.

Araştırma paketi canlı `replay_features` denetimini geçemez. Araştırma modeli
`research_only` işareti taşır ve prospektif `predict` tarafından reddedilir.
Geçmiş hedefin kendisi, geç gözlenen veri, başka sezon ve 45 günlük pencere
dışındaki veriler özellik olarak kullanılamaz. Gelecek etiketler kronolojik
bölüm sınırlarında purging ile dışlanır. Kaynak sırası tekilleştirilip
normalleştirilir; eş zamanlı maçlar yeniden doğrulamada sıra hatası yaratmaz.

## Eğitim uygunluğu

| Araştırma hedefi | ESPN ID | Öncesinde gözlenmiş farklı kaynak maçı |
|---|---|---:|
| Detroit–Philadelphia | 401909922 | 54 |
| Washington–Atlanta | 401909923 | 54 |
| Brooklyn–Charlotte | 401909925 | 54 |

Bu üç eşleşmede beş takım maçı, en az ikişer ev/deplasman maçı ve her rakip
 için en az iki gözlenmiş maç şartları sağlandı. Hücum/savunma ve rakip formu,
 geçmiş normal süre skorları ve 48 dakikaya normalize kutu skoru temposundan
 hesaplandı. Bunlar kalibre edilmiş lig rating'leri değildir. Ev/deplasman
 farkı gözlemsel bir özellik olup nedensel ev avantajı katsayısı değildir.

**Gerçek model eğitilmedi.** Gerekli asgari eşik zaman temizliğinden sonra
60 eğitim + 20 doğrulama + 20 testtir. Üç hazır eşleşmeye göre en az **97 ek
uygun ve farklı maç** gerekir; eş zamanlı hedefler ve geç gözlenen etiketler
purging sonrasında daha fazla maç gerektirebilir. Bu eşik istatistiksel
 yeterlilik veya üstünlük kanıtı değildir. Gerçek walk-forward fold sayısı 0;
yeni MAE/RMSE/Brier/log-loss/kalibrasyon sonucu veya model karşılaştırması yoktur.
Eski üç maçın FAZ13/FAZ28 betimsel metrikleri değişmedi.

Eksikler: maç öncesinde arşivlenmiş sakatlık, kadro, piyasa ve doğrulanmış
 toparlanma bilgisi. Tempo, `FGA + 0.44*FTA - ORB + TOV` formülüyle, iki takımın
 ortalaması ve uzatma süresi düzeltmesi kullanılarak **tahmin edilir**;
 ölçülmüş pozisyon verisi değildir. Eksik kutu skoru sayıları doldurulmaz.

## Tekrarlanabilir araştırma akışı

```sh
# Yeni, boş hedef dizin; canlı zamanlayıcı kurulmaz.
python -m faz32_collect collect NEW_DIRECTORY 20261030 20261101 20261102 20261104
python -m faz32_collect import NEW_DIRECTORY/fetch-manifest.json NEW_RESEARCH.sqlite

# Arşiv ham dosyaları/özgün ledger mevcutsa, salt okunur kaynaklardan aktarım.
python -m faz32_archives NEW_RESEARCH.sqlite NEW_DIRECTORY/fetch-manifest.json \
  --raw-root OLD_VALIDATION_DIRECTORY --input-ledger ORIGINAL_BOS_MIL_LEDGER

# Araştırma uygunluğu; yeterliyse yalnızca temiz kaynak commit'inde araştırma eğitimi.
python -m faz32 NEW_RESEARCH.sqlite

# Yalnızca daha sonraki FAZ31 yakalamaları için; eski kesimlerde kullanılamaz.
python -m faz32 NEW_RESEARCH.sqlite --export-live-periods NEW_PERIOD_EXPORT.json
# Bu dosya mevcut FAZ24 --shadow-periods seçeneğiyle kullanılabilir.
```

Eğitim/normalizasyon yalnızca eğitim kümesini, ceza seçimi ve hata varyansı
 doğrulama kümesini kullanır. Test etiketleri model seçmez. Araştırma
 walk-forward sonuçları canlı sonuç diye raporlanmaz. Bu faz yeni bir
 üretim model dosyası veya üretim zamanlayıcısı kurmaz.

## SQLite kalıcılığı ve geri yükleme

SQLite dosyaları şu an `/workspace/scratch` altında; Git'e eklenmedi.
Önceki dosyaların erişilebilir olması yeni bir Codex Cloud oturumunda kalıcılık
 garantisi değildir. Yeni oturum/makine değişimi **test edilmedi**; harici
 depoya yükleme veya otomatik kalıcılık yapılandırılmadı.

`research_recovery.make_bundle` mevcut SQLite online backup işlevini kullanır:
 salt okunur kaynak, tutarlı snapshot, integrity_check, SHA-256 manifesti,
 yalnızca sahibine erişim (0600), var olan hedefin üzerine yazmama.
 `verify_bundle` yol geçişi/link/tekrar dosya adlarını reddeder, hash'leri ve
 SQLite bütünlüğünü denetler; geri yüklenmiş FAZ24 tahminlerini ve araştırma
 gözlemlerini anlamsal olarak yeniden doğrular. Gerçek dört veritabanı için
 yerel geri yükleme başarılı; iki FAZ24 defterindeki üç özgün tahmin doğrulandı.
 Kaynak dosyaların byte hash'leri değişmedi. Başka makineye aktarım yapılmadı.

Kullanıcı kurtarma paketini oturum dışında güvenli bir yere indirmeli;
 yeni çalışma alanında önce checksum ve restore denetimi yapılmalıdır.
 Git'teki JSON kanıtları tek başına bütün SQLite geçmişinin yedeği değildir.
 Kurtarma kanıtındaki kaynak SHA, test sırasında henüz commit edilmemiş FAZ32
 çalışma ağacının **taban commit**'idir; ayrıca uygulama dosya hash'leri kaydedildi.

## Testler ve kalan engeller

24 yeni FAZ32 regresyonu: zaman sınırı, kaynak/ingestion ayrımı, aynı maç/saate
 ait kimlik çakışmaları, tekrar aktarım, eksik tempo, sezon/takım/final/çeyrek
 uyuşmazlığı, SQL değişiklik engeli, hash yeniden hesaplanmış anlamsal bozulma,
 kaynak sırası, araştırma/canlı ayrımı, kronolojik purging, 403/429, FINAL
 olmayan kayıt, manifest/özet çelişkisi, güvenli yedek ve ileriye dönük export.
 Başarılı araştırma eğitimi yalnızca açıkça sentetik 100 maçlık test verisidir.
 Gerçek üç eşleşme üzerinde eğitim yapılmadı.

Üretime geçiş engelleri: yeterli zaman kanıtlı özellik/etiket birikimi,
 kronolojik bağımsız test kapsamı, doğrulanmış ek veri, kalibrasyon,
 bağımsız sağlayıcı erişimi ve oturum dışı yedek/geri yükleme sürekliliği.
 FAZ13/FAZ28 üretim katsayıları değiştirilmedi; merge veya dağıtım yapılmadı.

Yerel son tam regresyon koşusu: **646 test başarılı**, 31.463 saniye.
`compileall` ve `git diff --check` başarılı. Docker derlemesi ve commit'e bağlı
uzak CI sonuçları GitHub Actions üzerinden ayrıca doğrulanır; yerel Docker
başarısı iddia edilmez.
