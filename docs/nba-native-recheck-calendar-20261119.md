# NBA güncel fikstür yeniden kontrolü: sağlayıcı takvim günü

## Kod düzeltmesinden önce kök neden

Cihazın V3 raporu `ADAPTIVE_EXACT_CURRENT_NATIVE_FIXTURE_REQUIRED` gösteriyor.
`AdaptiveWorker.verify` maçın UTC başlangıcından `dates=YYYYMMDD` üretip
ESPN scoreboard sorgusu yapıyor. Aynı modülün geçmiş yenileme yolu ise
ESPN gününü zaten `America/New_York` üzerinden hesaplıyor. NBA ana analiz
preflight'ı komut gününün komşu günlerini de sorguladığından ilk tahmin
üretilebilirken bu tek günlük yeniden kontrol başarısız olabiliyor.

19 Kasım'da anonim resmî uç noktada doğrulanan gözlem:

- `dates=20261119`: `401910019`–`401910022`, başlangıç
  `2026-11-20T01:00Z`; New York günü 19 Kasım.
- `dates=20261120`: 21 Kasım UTC başlangıçlı ertesi sağlayıcı gününün maçları.

Dolayısıyla 20 Kasım UTC günü sorgulanınca ilk grubun kanonik maç kimliği
listede bulunamıyor. Kaynak gövdeleri ve gerçek erişim saatleri
`docs/evidence/nba-provider-calendar-20261119.json.gz` içinde SHA bağlı
olarak saklandı. Bu bir takvim/kaynak gözlemidir; yeni tahmin veya tarihsel
maç öncesi erişilebilirlik kanıtı değildir. Paket SHA:
`5b9150c5f588280bdaf023d8093a0bf73146b0f6502c48a593007d640b449ec2`.

## Düzeltmenin sınırı

NBA yeniden kontrolü için çalışma zamanı kaynak adaptörü, ESPN gününü
`America/New_York` takviminden seçer. Gerçek sorgu URL'si, belge SHA'sı ve
kaynak zamanları korunur. Mevcut sabit `AdaptiveWorker.verify` doğrulayıcısı
aynen çağrılarak kanonik kimlik, sezon, takım yönü, tam UTC başlangıcı,
sağlayıcı maç kimliği, başlamamış/sıfır skor durumu ve son 15 dakika sınırı
denetlenir. Avrupa sorguları mevcut doğrulayıcıdan aynen geçer.

Bilimsel model dosyaları, eski kaynak pinleri, mevcut deney planları,
admission kayıtları ve tahminler değiştirilmez. Kaynak adaptörü yeni bir
çalışma zamanı bileşenidir; kod SHA'sı/takvim politikası açıkça gösterilir
ve her yeni başarılı kaynak makbuzunda türetilmiş edinim tanığı olarak
saklanır. Bu tanık yerel yöntem metadata'sıdır; ESPN'in imzası veya native
belge alanı gibi sunulmaz. Eski makbuzlara eklenmez.

Bu düzeltme, sonuç görülmeden mevcut uygun gelecek maçların tekrar
kontrolüne olanak verir. Geçmiş maçlara tahmin eklemez; kimlik/saat/durum
uyuşmazlığını kabul etmez. Sayısal skor modeli, oyuncu etkisi, kalibrasyon
ve kabul eşikleri değişmez. 100 geçmiş örnek gerektiren gölge kalibrasyon
engeli ayrı kalır.

## Regresyon doğrulaması

`tests/test_native_fixture_recheck.py` içindeki 9 test, gerçek kaydedilmiş
ESPN cevaplarıyla eski UTC sorgusunun maçı bulamadığını ve yeni kaynak
adaptörünün aynı değişmez doğrulayıcıdan geçtiğini gösterir. Gerçek belge
gözleminin replay'i canlı tahmin veya Telegram teslim kanıtı değildir.

Sentetik negatif örneklerde yanlış kanonik/sağlayıcı kimliği, takım, sezon,
tam saat, kaynak URL'si, belge hash'i, eski/gelecek erişim saati, başlamış
durum, sıfırdan farklı skor ve son 15 dakika reddedilir. Yaz/kış saati ve
UTC ile aynı sağlayıcı günü de kapsanır. Gerçek V2/V3 fit ve capture yolları
sentetik geçmişle çalıştırılarak kalibrasyonsuz gelecek skor kaydı, kaynak
makbuzundaki yeni adaptör tanığı, tekrar/restart mükerrerliği ve maç
başladıktan sonra mevcut kaydın korunması denetlendi.

Odaklı koşu: `148 passed in 37.53s` (takvim, V2/V3, kritik bütünlük,
entegrasyon, Avrupa servis/UI ve runtime testleri). `a5d6b9a` ile dosya
SHA karşılaştırması: V1 27, V2 13, V3 9, Avrupa 6 ve canlı NBA 6 pinin
tamamı aynı; mevcut planları değiştirecek bilimsel dosya düzenlenmedi.
Yeni kaynak edinim politikası ayrıca SHA ile tanımlanır; `/test research`
bu adaptörün sürümünü ve New York takvimini gösterir.

Cihazdaki gerçek V3 yayını henüz doğrulanmadı. Yeniden başlatmadan sonra
`/test research` ve `/models NBA 401910019` ile kaynak kontrolü, varsa ayrı
PREMATCH kaydı ve sonraki gerçek engel kontrol edilmelidir. Eski maçlara
yeni tahmin eklemek veya planı sıfırlamak bu testin parçası değildir.
