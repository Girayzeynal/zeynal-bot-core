# Tarihsel öğrenme, araştırma replay'i ve gerçek canlı performans

Geçmiş maçlar öğrenme ve kalibrasyon kapsamındadır. Eksik PIT kanıtı geçmiş
veriyi silme gerekçesi değildir; hangi değerlendirmede kullanılabileceğinin
sınırıdır. Bu aşama PR #81 / `b2387fbfa57308ac5ddeaaca66391064f5413190` üzerine
ayrı `dev/historical-research-separation-20261111` dalında geliştirilmiştir.
FAZ13/FAZ28 üretim katsayıları ve mevcut gerçek tahmin/sonuçlar değiştirilmedi.

## Üç kayıt türü

| Tür | İçerik | Zaman anlamı |
|---|---|---|
| HISTORICAL_DATA | Kaynaktan doğrulanan tamamlanmış maç, final/periyot ve mevcut istatistik | Maç başlangıcı, kaynak gözlemi ve ingestion ayrı |
| BACKTEST_SIMULATION | Sonradan yürütülen tarihsel tahmin veya ABSTAIN denemesi | Gerçek oluşturulma zamanı bugün; bilgi kesiti geçmişte |
| LIVE_PREMATCH_PREDICTION | Gerçekten başlamamış maç için oluşturulan tahmin | Depo saati ≤ cutoff < maç başlangıcı |

`research_record_store.py` yalnızca ayrı yerel araştırma SQLite dosyası kullanır;
`/data`, symlink ve yabancı veritabanı şemalarını reddeder. Kayıtlar INSERT-only,
SHA-256 ile mühürlü ve tür bazında ayrıdır. UPDATE/DELETE trigger'larla reddedilir.
SQL tür/JSON eşleşmesi ve canlı zaman kısıtları da uygulama kontrolünden ayrıdır.
Üç tür arasında dönüşüm yapılmaz. Depo oluşturulma saatini kendisi alır; geçmiş
cutoff değerini gerçek oluşturulma zamanı olarak kabul etmez.

Bu yerel bütünlük kanıtıdır; bağımsız zaman damgası otoritesi veya ikinci Cloud
runtime kalıcılık kanıtı değildir. Üretimdeki eski ledger'a bağlanmadı.

## Kaynak keşfi ve kapsam

`season_history_discovery.py`, ESPN'in ilgili sezon için döndürdüğü tam gün
takvimini okur ve kesit gününe kadar bütün listelenen günleri sorgular.
Tek tek örnek maç seçmez; tek bir hatalı range sorgusunu tam sezon saymaz.
EuroLeague'de resmî sezon games uç noktasını ve toplam/satır eşitliğini doğrular.
Varsayılan CLI ağsız dry-run'dır. Gerçek indirme yerel çıktı dizini ister;
ham kaynaklar atomik, içerik adresli ve üzerine yazılmadan yayımlanır.
403/429 sağlayıcıyı durdurur; bilinmeyen kapsam sıfır maç olarak gösterilmez.

| Lig / sezon | Normal sezon final | Periyotlu | Ek veri |
|---|---:|---:|---|
| NBA 2026/2027 | 160 | 160 | 160 maçta kısmi yerel takım istatistikleri |
| EuroLeague 2026/2027 | 100 | 100 | Oyuncu/tam takım boxscore henüz alınmadı |
| EuroLeague 2025/2026 | 380 | 380 | Oyuncu/tam takım boxscore henüz alınmadı |
| Toplam | 640 | 640 | Gerçek maç sayısı; tahmin sürümü sayısı değildir |

Güncel sezon için 36 NBA takvim günü ve bir EuroLeague belgesi alındı; önceki
EuroLeague sezonu için bir ek istek yapıldı: toplam **38 HTTP isteği**.
NBA kaynağındaki 67 sezon öncesi kayıt ham belgelerde korunur; normal sezon
örneklemine katılmaz. E2025 kaynağı 402 kayıt içerir: 380 RS, 3 PI, 16 PO ve 3 FF.
22 diğer aşama ham belgede korunur, normal sezon modellerine karıştırılmaz.
E2025 ilk strict parser denemesi bu aşamalar yüzünden `regular_season_required`
verdi; açık faz filtresi ve regresyon testiyle normal sezon arşivi çıkarıldı.

Bunlar sağlayıcının kapsadığı ve native şema/final/periyot kontrollerini geçen
maçlardır. NBA.com ile bağımsız tam sezon evreni çapraz doğrulanmadı; önceki
kontrolün NBA.com 403 engeli çözülmüş sayılmadı. ESPN takvim taraması tamamlandı
diye bağımsız tam sezon kapsamı ilan edilmez. NBA 2025/2026 tam arşivi alınmadı.
Playoff/sezon öncesi için ayrı normalize edilmiş model arşivi de henüz yoktur.

NBA ham istatistiklerinden FGA/FGM, FTA/FTM, üçlük, ribaund ve asist gibi mevcut
alanlar sayısal tutarlılık denetimiyle korunur. İstatistik kapsamı uzatma dahil
finaldir; normal süre skorları ilk dört periyottan ayrı hesaplanır. Eksik ORB/TO
ve süre kanıtından tempo/verimlilik uydurulmaz. Sakatlık, beşli, oyuncu dakikası
ve rotasyon bu adaptörlerde henüz toplanmadı. Veri yokluğu ile henüz normalize
edilmemiş ham alan aynı şey sayılmaz; alan durumları ayrı saklanır.

## Tarihsel simülasyonun iki kanıt sınıfı

`historical_research.py` zaman sırasıyla ilerler. Model yalnızca seçilmiş önceki
maç özelliklerini alır; hedef maçın finali/periyotları tahmin fonksiyonuna
gönderilmez. Etiket, fonksiyon döndükten sonra değerlendirmeye bağlanır.
Takım–başlangıç çakışması, sağlayıcı ID çatışması ve farklı ID ile yinelenen
aynı maç örneklem sayısını artıramaz. Eski kaynak sürümü daha yeni ingestion
ile silinmez; önceki erişilebilir sürüm cutoff için kullanılabilir.

1. Varsayılan `PIT_PROVEN_BACKTEST`: geçmiş girdi maçının kaynak gözlemi **ve**
   ingestion zamanı hedef cutoff'tan önce olmalıdır. Gerçek 640 maç bu görevde
   sonradan toplandığı için uygun değerlendirme **0**, ABSTAIN **640**.
   Arşiv yine korunur. Kaynak snapshot'ı sonraki bir maçtan önce gerçekten
   saklanmışsa, o sonraki tarihsel hedef için kullanılabilir; tüm tarihsel
   veri için kalıcı bir yasak yoktur. Bu yol sentetik zaman testinde sınandı.
2. Açık `assume_availability=True`: sonradan edinilmiş geçmiş sonuçların en az
   24 saat önce başlayan maçlardan erişilebilir olduğu **varsayılır**.
   Bu bekleme süresi erişilebilirlik kanıtı değildir. Çıktı zorunlu olarak
   `AVAILABILITY_ASSUMED_RESEARCH` olur; doğrulanmış geçmiş/canlı performansa,
   kalibrasyon uygunluğu eşiğine veya otomatik model güncellemesine katılmaz.

Bu araştırma referansı `RESEARCH_SCORE_MATCHUP_V1:<kaynak-hash>:w10:n6` olarak
ayrı sürümlenir. Son 10 uygun maç ve en az 6 maçla hücum/savunma skor ortalamalarını
eşleştirir; çeyrekler geçmiş gerçek çeyrek ortalamalarından gelir. Devre, toplam
ve fark aynı projeksiyonlardan türetilir. FAZ13 veya FAZ28 değildir; onların
performansı olarak sunulamaz. Kaynak kod SHA-256'sı kayıtta bulunur.

Yerel son araştırma deposu: **640 HISTORICAL_DATA**, **1280 BACKTEST_SIMULATION**
(640 strict + 640 varsayım denemesi), **0 LIVE_PREMATCH_PREDICTION**.
Varsayım modunda 424 tahmin ve 216 ABSTAIN vardır. 1280 kayıt, 1280 bağımsız maç
veya başarılı tahmin anlamına gelmez. Aynı iki replay yeniden çalıştırıldı;
kayıt sayıları değişmedi ve SQLite integrity_check başarılıydı.

## Araştırma hata ölçümleri — doğrulanmış model başarısı değildir

Aşağıdaki tablo yalnızca erişilebilirlik varsayımına dayanan sabit referansın
tanısal sonuçlarıdır. Gerçek canlı veya kanıtlı tarihsel doğruluk değildir.

| Lig / sezon | Araştırma tahmini | Takım skoru MAE | Toplam MAE | Fark MAE |
|---|---:|---:|---:|---:|
| NBA 2026/2027 | 64 | 9,302 | 13,413 | 12,547 |
| EuroLeague 2026/2027 | 40 | 8,892 | 15,029 | 9,757 |
| EuroLeague 2025/2026 | 320 | 8,194 | 13,294 | 9,703 |

Lig, sezon, takım, model sürümü ve kanıt sınıfları ayrı raporlanır. Ev/deplasman,
toplam ve fark için MAE/RMSE/bias; 1Q–4Q ve 1H/2H hata ölçümleri hesaplanır.
Bu skor referansı kazanma olasılığı üretmez; gerçek araştırma çıktılarında
Brier/log-loss **null**, kalibrasyon kutularının örneklemi **0**'dır. Olasılık
metriklerinin hesaplaması yalnızca ayrı sentetik testlerle sınandı. Tempo yokken
tempo sınıfları veya güvenilirlik yüzdesi uydurulmaz.

## Kronolojik ayrım ve kalibrasyon güvenliği

`chronological_evaluation` eğitim/doğrulama/test sınırlarının artan UTC olmasını
ve test bitişinin gerçek saatten ileri olmamasını zorunlu tutar. Aynı başlangıç
zamanı sınırda iki bölüme bölünmez. Bu çalışmanın kronolojik raporu 1 Kasım 2026,
6 Kasım 2026 ve kaynak taramasının gerçek kesitini kullanır; eski sezon bu planda
yalnızca TRAIN dönemine düşer, bağımsız eski sezon test sonucu sayılmaz.
Sabit rolling referansın katsayıları öğrenilmedi/ayarlanmadı. Bir kalibrasyon
modelinin eğitimi veya üretimde iyileşmesi tamamlanmış değildir.

Uygunluk eşiği lig/sezon/model başına yalnızca PIT kanıtlı tahminleri sayar;
varsayılan 100 eğitim, 30 doğrulama, 30 test örneği bir politika eşiğidir,
istatistiksel yeterlilik garantisi değildir. Gerçek uygun örneklem **0**.
Üretim terfisi her durumda kapalıdır; bağımsız dönem iyileşme kanıtı gerekir.

## Test ve kanıt

Önceki 333 test korundu; 24 yeni regresyonla **357/357 başarılı**.
İlk yeni metrik testinde, sabit sentetik eşleşmenin hatası yanlışlıkla 6
beklenmişti; bu örnekte referans skoru aynen buluyordu. Test, kontrollü +2/−1
hatalarıyla MAE/fark/Brier beklentilerini bağımsız sayısal olarak sınayacak
şekilde düzeltildi. Son testlerde başarısızlık yok.

Üç türün karışması, geçmiş cutoff'un canlı oluşturulma zamanına dönüştürülmesi,
aynı maçın iki sayılması, gelecek etiketinin önceki tahminlere etkisi, geç ingestion,
normal süre/uzatma ayrımı, olasılık yokluğu, sıralı dönemler, 403/429, atomik
yayının yarıda kalması, yeniden yayın, yanlış hash, eşzamanlı tekrarlar ve değişmez SQLite kayıtları
test edildi. Derleme ve diff-check başarılıdır. CI tam commit SHA ile PR'da raporlanır.

[Makine okunur kanıt](evidence/historical-learning-scope-20261111.json).
Ham kaynak JSON'ları ve araştırma SQLite'ı yalnızca yerel araştırma alanında
korundu; GitHub'a toplu ham arşiv veya DB yüklenmedi. Ayrı Cloud oturumunda
kalıcılık doğrulanmadı. Önceki UserLAnd `542cec0 --live` çıktısı da hâlâ bekleniyor.
Main merge, Fly.io/Telegram üretim değişikliği, secret işlemi veya ücretli servis yok.

Sıradaki işler: bağımsız sezon kapsamı; oyuncu/boxscore ve possession verisi;
kaynak izinleri ve tarihsel erişim kanıtları; düzenli yerel snapshot birikimi ve
kalıcı kurtarma; daha uzun bağımsız dönemlerde model karşılaştırması ve kalibrasyon.
