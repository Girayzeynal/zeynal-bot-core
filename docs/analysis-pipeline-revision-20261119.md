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
