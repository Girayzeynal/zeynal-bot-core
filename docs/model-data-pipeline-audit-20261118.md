# ZEYNAL model ve veri hattı incelemesi — 18 Kasım 2026

## Sonuç

Tek bir “arşiv modeli bozuyor” nedeni doğrulanmadı. Birbirinden ayrı üç sorun
var: ana çıktının hâlâ sabit parametreli modelden gelmesi, bazı gerekli veri
akışlarının ana skor hesabına bağlı olmaması ve sağlayıcı erişim/kapsam engelleri.
İncelemede bunlardan ayrı, yeniden üretilebilen iki yazılım hatası da düzeltildi.

Bu rapor cihazdaki bütün arşivin sağlam olduğunu veya yeni modelin daha başarılı
olduğunu iddia etmez. UserLAnd veritabanı Cloud ortamında bulunmuyor. Gerçek
Telegram teslimi ve özel sağlayıcı hesabının güncel planı burada doğrulanamadı.

## Kullanıcının son çıktısındaki somut nedenler

Kanıt: 18.11.2026 20:45:19 TSİ kadro kontrolü ve aynı kullanıcı mesajındaki
piyasa denetimi. Bu bir **kullanıcının aktardığı Telegram çıktısıdır**;
bu inceleme sırasında yapılmış bağımsız bir HTTP sorgusu değildir.

| Gözlenen sonuç | Anlamı | Kod düzeltmesiyle kendiliğinden çözülür mü? |
| --- | --- | --- |
| The Odds API aktif listesinde `basketball_eurocup` yok | O anki katalogda EuroCup piyasa kapsamı doğrulanamadı. NBA/EuroLeague kapsamı EuroCup kapsamı değildir. | Hayır; desteklenen bir kaynak/kapsam gerekir. Başka ligin oranı kullanılamaz. |
| API-Basketball: plan/abonelik ve sezon hata sınıfları | `2026` katalogda doğrulansa da maç sorgusu erişimi reddediliyor. Doğru sezonun listelenmesi fikstür/statistik erişimini garanti etmez. | Yerel sezon yazım hatası kanıtlanmadı. Kesin hesap/plan nedeni sağlayıcı hesabından incelenmeli. |
| Resmî EuroCup haber sayfası HTTP 429, 300 sn bekleme | Web sitesi isteği sınırlamış. Bu sayfa iki API anahtarından bağımsızdır. | Anahtar değiştirmek çözüm değildir. Bekleme korunmalı; engel aşılmaya çalışılmadı. |
| İlk tahminin kadro ve piyasa kanıtı yok | O anki değişmez tahminde bu veri kaydedilmemiş. Daha sonra alınan bilgi geçmiş girdiye dönüştürülemez. | Eski kaydı değiştirmek doğru çözüm değildir. |

Bu son örnekte “veri yok” metninin kaynağını açıklamak için arşivin bozulduğunu
varsaymaya gerek yok. Aşağıdaki yerel kapasite hataları bu örneğin nedeni olarak
gösterilmemiştir; cihazda oluşup oluşmadığı ayrıca ölçülmelidir.

## Ana model ile yeni araştırma modelleri aynı yol değil

`scripts/run_isolated_test_bot.sh`, NBA ana servisini belirli SHA ile sabit bir
`nba-prepared` dosyasından başlatıyor. `LiveNBAHybridService` bu hazırlanmış
Bayesian takım modelini kullanıyor. `models.HierarchicalStrength.predict()`
tam maç ortalamasını `x @ coefficients` ile hesaplıyor. Güncel geçmişten
hesaplanan çeyrek ağırlıkları, bu katsayıları yeniden eğitmiyor.

V2 (`adaptive-v2`) ve V3 (`nba-research-v3-integrity-v2`) ayrı araştırma adayları.
Otomatik toplanmaları, `/analyze` ana skorunun otomatik olarak değiştiği anlamına
gelmiyor. Üretim yükseltmesi ve adayın ana model olması ayrı kararlardır.

Piyasa düğmesi güncel oranı eski dağılımla ayrı değerlendiriyor. Kadro düğmesi
güncel gözlemi ayrı gösteriyor. Bu iki düğme mevcut skorun katsayılarını veya
geçmiş tahminin başarı hesabını değiştirmiyor.

Avrupa kadro bağlantısı ise `europe_data.article_rows()` üzerinden yapılandırılmış
resmî **haber metni** arıyor. Gerçek oyuncu durumu/ilk beş/dakika/ceza uygunluğu
akışı üretmiyor; `verified_player_records=[]` dönüyor. HTTP 200 alınması bile
doğrulanmış oyuncu etkisi elde edildiği anlamına gelmez. API-Basketball mevcut
köprüde fikstür ve takım istatistikleri için sorgulanıyor; doğrulanmış sakatlık
etkisi bu yoldan hesaplanmıyor. Panel artık bu sınırı başta açıkça belirtiyor.

## Korunmuş gerçek NBA kaydındaki hesap incelemesi

`docs/evidence/handoff-nba-prospective-20261115.tar.gz` ve korunmuş snapshot
üzerinden ESPN `401909985` kaydı incelendi. Snapshot SHA:
`30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343`.

- Eğitim maçı: **170**. Parametrelerin tahmin anındaki yaşı: **215144 sn**, yaklaşık **59,76 saat**.
- Tam maç ortalaması: sabit lig/ev etkisi/takım hücumu/rakip savunması katsayıları.
- `current_scoring_average_updates_full_game_mean=False`, `verified_pace=False`, `player_effects=False`.
- Çeyrekler arası ortalama korelasyon: **0,9879739**. Sabit tam maç dağılımının deterministik çeyrek paylaştırılması yüksek ortak hareket üretiyor.
- Skor bu katsayılardan aynen yeniden oluştu; snapshot değiştirilmedi.

Bu, kayıttaki skorun arşiv açılırken kaymadığına ilişkin tek kayıtlık kanıttır.
Bütün maçların girdilerinin doğru olduğunu veya hataların nedeninin tek başına
bu eksikler olduğunu kanıtlamaz. Oyuncu/tempo bilgisi yokken modelin bunları
kullanıyormuş gibi yorumlanması yanlış olur.

## Düzeltildi: yerel kanıt deposu hataları

`ProviderBridge._save()` 256 belge / 32 MiB sınırını, aynı SHA ile zaten bulunan
belgeyi kontrol etmeden uyguluyordu. Depo dolunca **aynı belgeyi tekrar kullanmak
bile** hata veriyordu. Ayrıca koleksiyonun son rapor kaydı hata yakalama dışında
kalıyordu; bu yerel kapasite hatası bütün düğme çağrısını düşürebiliyordu.

Artık mevcut belge önce SHA ile doğrulanıp yeniden kullanılıyor. Depo doluysa
yeni sağlayıcı isteği yapılmadan `LOCAL_EVIDENCE_STORAGE_FULL` dönüyor. API
abonelik hatasıyla karıştırılmıyor. Gerçek dosya boyutu hesabına sarmalayıcı da
dahil edildi. Eski dosyalar silinmedi; sınırlar artırılmadı.

Avrupa kaynak ve inceleme depolarında da ayrı 64/256 belge ve 16 MiB sınırları
var. Bunlar artık açık yerel kapasite durumlarıyla ayrılıyor. Yeni inceleme
arşivlenemediğinde görünüm bunu açıkça bildiriyor; mevcut HTTP hata bilgisi
korunuyor. Büyük yanıtların bellek sınırları korunuyor.

## Düzeltildi: eski dağılımı yeniden üretirken yanlış model yaşı kontrolü

Avrupa piyasa paneli arşivdeki parametreleri tekrar yüklerken canlı tahmin
hazırlayıcısının **bugüne göre üç günlük yaş kuralını** kullanıyordu. Örnek:
model ilk tahmin anında 71 saatlikken geçerli; iki saat sonra maç hâlâ başlamamış
ama model 73 saatlik. Aynı donmuş dağılımın tekrar üretimi yanlışlıkla reddediliyordu.

Yeni arşiv yükleyicisi yaş kuralını **ilk tahmin zamanında** doğruluyor. Native
eğitim kaynağı, bütün SHA’lar, takım/lig/sezon, parametreler, kaynak kodu pinleri,
orijinal saatler ve hedefin eğitimde bulunmaması ayrıca doğrulanıyor. İlk
tahminden sonra hazırlanmış bir model kabul edilmiyor. Son örnek SHA’sı ve skor
ilk tahminle eşleşmedikçe piyasa hesabına geçilmiyor.

Canlı `PreparedEurope` üç günlük sınırı aynen duruyor. Geçmiş maç için yeni
tahmin yok; global saat değiştirme, yeniden eğitim veya eski kayıt yazımı yok.
Kaynak düğmesinin kayıt çözümlemesinde gereksiz bütün-arşiv taraması da kaldırıldı.

## Diğer ölçülen sınırlamalar

- Yerel sağlayıcı sınırı varsayılan olarak **sağlayıcı başına süreçte izlenen 24 istek/UTC gün**. Sınıra gelinmesi API anahtarının bozulduğu anlamına gelmez. Yeniden başlatma bu yerel sayacı sıfırlayabilir; sağlayıcının gerçek kotasını sıfırlamaz.
- Ödeme/uzatma kapsamı doğrulanmamış fiyat, oran görünse bile karşılaştırılabilir beklenen getiri üretmez. Bu, fiyatın hiç alınamamasından ayrı bir engeldir.
- Maç başladıktan sonra güncel fiyat/kadro sorgusunun geçmiş tahmine eklenmemesi bilinçli bir zaman korumasıdır.
- Erken otomatik tahmin gece komut ihtiyacını azaltır; daha sonra açıklanan kadronun ilk tahmin anında bilindiği varsayılamaz.

## Cihaz için tek komutluk denetim

Bu dal: `feature/model-data-pipeline-audit-20261118`. İzole test checkout’u bu
dala güncellendikten sonra Ubuntu’da:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --pipeline-audit
```

Bu mod botu başlatmaz/durdurmaz, Git güncellemez, API isteği yapmaz, anahtar
yazdırmaz ve arşivi değiştirmez. NBA kaynak/snapshot/sonuç denetimini, seçili
modelin yaşını, mevcut Avrupa arşivlerini ve yerel kanıt kapasitesini özetler.
Avrupa sayımı bu motorun güncel kayıtları içindir; ayrı eski beş maçlık depoyu
tek sayıya katmaz. Eşzamanlı bot yazımı varsa “bayt değişti” tek başına bozulma
diye yorumlanmaz.

Telegram’da **`/test data`** çalışan süreçteki yerel istek sayacını ve veri-model
bağlantısını sorgular; sağlayıcıya yeni istek yapmaz. Diskteki kayıtla çalışan
sürecin durumu ayrı gösterilir.

## Doğrulama ve sonraki adım

Temel commit `3e1ff7c25c1aeb16a43b820a912181fca998a800` üzerinde üç regresyon
senaryosu hata veriyor: dolu depoda belge tekrar kullanımı, dolu depoda düğme
yanıtı ve model yaşı sınırından sonra donmuş dağılım tekrar üretimi. Düzeltilmiş
kodda bu senaryolar ve ek koruma testleri geçiyor. Gerçek çıktılar PR ve kanıt
dosyalarında tutuluyor; sentetik sağlayıcı testleri gerçek Telegram teslimi
olarak sunulmuyor.

Öncelik sırası: cihaz arşivini bu denetimle doğrulamak; EuroCup için gerçekten
erişilebilir piyasa kapsamını ve oyuncu durumu kaynağını doğrulamak; yeni
dinamik modeli ana V1 ile ayrı, görülmemiş maçlarda karşılaştırmak. Veri veya
erişim yokken oyuncu etkisi/fiyat/güven yüzdesi uydurmak çözüm değildir.

Bu çalışmada ana modele otomatik geçiş, `main` birleştirmesi, Fly.io dağıtımı,
gizli anahtar değişikliği, kota yükseltmesi veya yeni ücretli servis kullanımı yok.
