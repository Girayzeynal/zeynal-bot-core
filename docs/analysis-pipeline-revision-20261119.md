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
gerekir. 0 uygun örnekten oyuncu katsayısı üretilemez. Korunan 82 kulüp
kaynak kataloğu ve ayrı oyuncu senaryo köprüsü, tek başına güncel kadro
doğrulaması sayılmaz. Sağlayıcı abonelik kısıtı, EuroCup oran kapsamı
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
örnek SHA, model ve kaynak varlıklarıyla kayıpsız gzip/binary biçiminde
saklanır. Native kaynak belgeleri de kayıpsız sıkıştırılır; açılan belgenin
ve makbuzun SHA değerleri yeniden doğrulanır. Açılmış boyut sınırları vardır.
V2 depolama dizini `current-assessments-v2` ayrıdır; önceki dosyalar silinmez.
Fiyat değerlendirmesi
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
varlıkların SHA'sını yeniden doğrular. Maç görünümü 36 saatlik hazırlama
aralığındaki en fazla 37 doğrudan yayın anahtarına bakar; her komutta bütün
arşiv taranmaz ve diğer maçların 10.000 örnek yolları çözümlenmez. Depolama
8.192 kayıt / 1 GiB sınırına ulaştığında ABSTAIN olur; kayıt silinmez.
Bunlar bağımsız sağlayıcı imzası değildir.

`/accuracy all` yeni değerlendirmeleri ayrı betimsel kohortta gösterir.
Her maç/stratejinin ilk değerlendirmesi alınır; saatlik güncellemeler örnek
sayısını şişirmez. Sonuçlar mevcut doğrulanmış native sonuç okuyucusundan
orijinal snapshot, model ve tam maç saati eşleşmesiyle gelir. Uzatma puanları
normal süre metriklerine katılmaz. Bu yeni strateji üstünlük kanıtı değildir.

`ResearchCycle` V3 → V2 → güncel değerlendirme sırasıyla seri çalışır.
Bir aşama hatası diğerlerini aç bırakmaz. `/test research` kuyrukta/çalışıyor/
tamamlandı/hata durumunu ve geçen süreyi gösterir. Eski V2/V3 planları ve
bilimsel modül kaynakları düzenlenmez.
Başarısız erken maçlar her turdaki iki deneme yerini sürekli işgal etmez;
en son denenme sırası izlenerek sonraki uygun maçlar da işlenir.

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
Mevcut oyuncu modeli ve ayrı kulüp/rotasyon senaryo çalışması korunur; güncel tempo modeline
oyuncu katsayısı eklenmiş gibi sunulmaz. Ölçülmüş PBP temposu, fizyolojik
dinlenme, gerçek seyahat güzergâhı ve doğrulanmış uzatma yolları halen yoktur.
Bu girdiler için çalışan model/önceki veri olmadan tüm özelliklerin aktif
olduğu veya tahmin başarısının arttığı ileri sürülmez. Üretim/Fly/disk değişmez.

## Nesine: gerçek katalog kanıtı ve oran sınırı

Kullanıcının platformu Nesine olarak bağlandı. Anonim resmî bülten GET
kaynağı `https://cdnbulten.nesine.com/v2/Bulten/GetPreBulten?sportId=2&nsnIds=-1`
HTTP 200 döndürdü. Native cevap NBA ve EuroLeague fikstürleri içeriyor;
bu gözlemde EuroCup maçı doğrulanmadı. Bağımsız ESPN kataloğuyla dört NBA
maçı takım çifti ve tam UTC saati üzerinden eşleşti. Nesine'nin native
milisaniye zamanı ile Türkçe gün/saat alanları da karşılaştırılır.

Bu cevapta tüm `MA` oran dizileri boştu. Resmî native maç ayrıntı isteği
HTTP 503 döndürdü; farklı bülten sorgusu da zaman aşımına uğradı. Oran,
barem ve ödeme kuralı elde edilmiş gibi sunulmaz. Başka sağlayıcı oranı
Nesine adıyla gösterilmez. Bağlanan adaptör yalnız fikstür/katalog denetimi
yapar; başarılı eşleşmede dahi `prices_admitted=false`, `rules_verified=false`.
Beş saniye / 1 MiB istek sınırı, 240 saniyelik tekrar önbelleği, başlamış
maçta sorgu yapmama ve 256 kaynak / 32 MiB silmesiz kanıt sınırı uygulanır.
Hesap veya bahis işlemi, ücretli erişim ve gizli anahtar değişikliği yoktur.

Gerçek native gözlem `docs/evidence/nesine-catalog-20261119.json.gz` içinde
saklanır (payload SHA `09109cc427191fa2821279dbe87f45ad1d21a662ad091208aa3d482f7797f009`).
Testler bu ilk yakalama zamanını açıkça yeniden oynatır; geçmişe maç öncesi
tahmin veya gerçek Telegram teslim kanıtı üretmez.

## Yerel doğrulama kaydı

19 Kasım Cloud çalışmasında ilgili handler, piyasa, model, Avrupa görünümü
ve başlatıcı testleri: `175 passed in 31.29s`. Son eklenen Nesine panel
bağlantısı dahil katalog testleri: `5 passed in 0.69s`. Bunlar sentetik
Bot API / sağlayıcı yanıtları ve açıkça zaman damgalanmış native katalog
replay testleridir; gerçek Telegram uçtan uca teslimi değildir.

`30c9271` ile bilimsel pin karşılaştırması: V1 27, V2 13, V3 9,
Avrupa 6 ve NBA örnekleyici 6 kaynak dosyası değişmedi. Eşzamanlı eklenen
82 kulüp kataloğu, oyuncu senaryoları ve üretim salt-okunur parity çalışması
fast-forward ile korundu; bu görev üretim başlatıcısını veya dağıtımını
çalıştırmadı. Cloud test bot kimlik bilgileri `NOT_CONFIGURED`; gerçek
Telegram `/analyze`, `/accuracy`, `/compare` doğrulaması `NOT_VERIFIED`.
Gerçek maçlarda bu yeni güncel stratejinin üstünlüğü henüz ölçülmedi.
Tam regresyon ve 256 MiB / 1 CPU kontrollerinin son commit sonuçları PR'de
ayrıca raporlanır; önceki commitin geçmesi yeni commitin kanıtı sayılmaz.
