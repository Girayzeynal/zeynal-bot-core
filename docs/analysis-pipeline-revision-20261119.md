# Aktif analiz zinciri revizyonu — kod öncesi kapsam

Doğrulanan açıklar: V1 tam maç katsayıları dondurulmuş; V1 periyotları
deterministik dağıtılıyor; güncel V2/V3 sonuçları ana analizden ayrı;
sağlayıcı piyasa çağrıları ödeme kurallarını aktarmıyor; normal süre yolları
uzatma dahil kontratları karşılamıyor; model yaşı ile fiyat yaşı ayrı
denetlenmeli; V3, V2 turunun bitmesini bekliyor ve aşama bilgisi görünmüyor.

Bu revizyon eski bilimsel kaynak pinlerini ve mevcut deneyleri değiştirmez.
Yeni, açıkça sürümlenmiş güncel araştırma değerlendirmeleri ayrı arşivlenir:
gerçek erişim zamanı, orijinal tahmin bağı, model varlığı, tam ortak örnek
yolları ve kullanılan/eksik özellikler birlikte saklanır. Son 15 dakikada
yeni hesap/kayıt yok; ilk tahmin hiçbir zaman üzerine yazılmaz. Güncel
değerlendirmeler eski ilk-yayın performansına eklenmez.

İzole Telegram ana analizi kayıtlı güncel değerlendirmeyi görünür gösterir.
Piyasa aynı değerlendirmeye ait gerçek örnek yollarını kullanır; eski skor
ile yeni model olasılığı sessizce karıştırılmaz. Yalnız açıkça yapılandırılmış
ve SHA ile sabitlenmiş ödeme kuralı makbuzları değerlendirmeye alınır. Eksik
kural, uzatma yolları veya fiyat halinde ham normal süre eğilimi açıklanır;
kontrat getirisi/öneri uydurulmaz.

Oyuncu etkisi için önceden doğrulanmış dakika ve eğitilmiş oyuncu modeli
gerekir. 0 uygun örnekten oyuncu katsayısı üretilemez. Kulüp haber pilotu
kadro doğrulaması sayılmaz. Sağlayıcı abonelik kısıtı, EuroCup oran kapsamı
ve HTTP 429 Cloud kod değişikliğiyle çözülmüş gösterilemez. Bu bağımlılıklar
çalışan özellik durumunda açıkça görünmelidir.

Araştırma döngüsünün aşama/başlama/bitiş bilgisi bellekte gözlenir; V3 ayrı
hata izolasyonuyla V2'den önce denenir. Kaynak toplama ve fitler seri kalır;
Telegram handler'ında fit/yeniden tahmin yapılmaz.

Doğrulama: gerçek fit ve native fixture kontrolüyle sentetik bütünleşik
girdiler, tam yolların yeniden okunması/hash kontrolü, ilk kayıt koruması,
güncellik/son 15 dakika, fiyat-kural-model eşleşmesi, normal süre/uzatma
ayrımı, aynı maç/model bazında ayrı sonuç metrikleri ve PTB handler testleri.
Gerçek Telegram cihaz doğrulaması erişim sağlanana kadar NOT_VERIFIED.

## Uygulanan bağlantılar ve kapsam

`CurrentAssessments` NBA için mevcut V3 fitini, Avrupa için mevcut V2
tempo/verimlilik fitini kullanır. Parametre yaşı en fazla altı saat;
maç/strateji/saat başına tek değişmez değerlendirme vardır. Art arda ve
eşzamanlı denemeler ilk kaydı değiştirmez. Ortak integer yollar dtype,
örnek SHA, model ve kaynak varlıklarıyla saklanır. Fiyat değerlendirmesi
bu yolları doğrudan okur; Telegram handler'ında yeni simülasyon/fit yoktur.
Yeni değerlendirme ayrı başlıkla ana analiz ve `/models` görünümüne eklenir.
İlk skor, düğmeler ve eski performans hesapları korunur.
Plan, bilimsel model kaynaklarını ve sayısal politikayı sabitler. Çalışma
zamanı uygulama SHA'sı her değerlendirmede ayrıca saklanır; yalnız sunum
metni değişmesi sayısal modeli değişmiş gibi planı sıfırlatmaz.

Yayın tamamlandıktan sonra ayrı commit makbuzu yazılır. Tamamlama son
15 dakika sınırını aşarsa yeni değerlendirme korunur fakat kullanılmaz.
Eksik commit makbuzu doğrulanmış yayın sayılmaz. Okuyucu taramada yalnız
imzalı yerel yayın metadata'sını okur, kullanılan değerlendirmedeki tüm
varlıkların SHA'sını yeniden doğrular; her komutta bütün maçların 10.000
örnek yolları çözümlenmez. Bunlar bağımsız sağlayıcı imzası değildir.

`/accuracy all` yeni değerlendirmeleri ayrı betimsel kohortta gösterir.
Her maç/stratejinin ilk değerlendirmesi alınır; saatlik güncellemeler örnek
sayısını şişirmez. Sonuçlar mevcut doğrulanmış native sonuç okuyucusundan
orijinal snapshot, model ve tam maç saati eşleşmesiyle gelir. Uzatma puanları
normal süre metriklerine katılmaz. Bu yeni strateji üstünlük kanıtı değildir.

`ResearchCycle` V3 → V2 → güncel değerlendirme sırasıyla seri çalışır.
Bir aşama hatası diğerlerini aç bırakmaz. `/test research` kuyrukta/çalışıyor/
tamamlandı/hata durumunu ve geçen süreyi gösterir. Eski V2/V3 planları ve
bilimsel modül kaynakları düzenlenmez.

## Ödeme kuralı yapılandırması

NBA ve Avrupa piyasa çağrıları artık `RuleBook` üzerinden açıkça verilen
kural makbuzlarını değerlendirmeye geçirir. Yapılandırma isteğe bağlıdır:
`ZEYNAL_TEST_RULE_MANIFEST` (yerel JSON dosyası) ve
`ZEYNAL_TEST_RULE_MANIFEST_SHA256` (payload için dışarıdan verilen sabit SHA).
Manifest sarmalı `{payload, sha256}`, payload biçimi
`CONFIGURED_RULE_RECEIPTS_V1`, entries alanı ise her kayıt için `receipt`,
`expected_url`, `document_sha256` içerir. Makbuz, mevcut `RuleEvidence.admit`
yapılandırılmış girdi sözleşmesini karşılamalıdır; bir haber veya HTML
sayfasına elle "doğrulandı" yazmak bu sözleşmenin yerine geçmez. Makbuzların
kökeni operatör yapılandırmasıdır; bağımsız bahis platformu imzası iddiası yoktur.

URL/hash, zaman, yürürlük aralığı ve platform/lig/periyot/piyasa eşleşir;
çakışan kapsamlar reddedilir. Yapılandırma yoksa kural varsayılmaz.
Eski/bilinmeyen model parametreleriyle güncel kontrat getirisi hesaplanmaz.
Gerçek barem mevcutsa ham normal süre eğilimi gösterilebilir. Uzatma
yolları yoksa uzatma dahil kontratın getirisi açıkça bloke edilir.

## Halen gerçek veri gerektiren işler

Bu çalışma sağlayıcı planını yükseltmez, EuroCup oran kapsamı yaratmaz,
HTTP 429'u aşmaz, eksik oyuncu dakika geçmişini veya tıbbi durumu uydurmaz.
Mevcut oyuncu modeli ve haber pilotu bağımsızdır; güncel tempo modeline
oyuncu katsayısı eklenmiş gibi sunulmaz. Ölçülmüş PBP temposu, fizyolojik
dinlenme, gerçek seyahat güzergâhı ve doğrulanmış uzatma yolları halen yoktur.
Bu girdiler için çalışan model/önceki veri olmadan tüm özelliklerin aktif
olduğu veya tahmin başarısının arttığı ileri sürülmez. Üretim/Fly/disk değişmez.
