# Basketbol analiz geliştirmesi — 6 Kasım 2026

Bu çalışma ayrı `feature/analytics-pit-hardening-20261106` dalında ve taslak PR #16'dadır. Üretim modeli veya zamanlayıcısı etkinleştirilmedi. Yeni projeksiyonlar araştırma çıktısıdır; özgün FAZ24/FAZ29 tahminleri değildir.

## Bağımlılıklar ve başlangıç doğrulaması

| Bileşen | Doğrulanan SHA | Durum |
|---|---|---|
| PR #12 | `2f24acb6e8f569b35c9ee1c241d8fe672da848d0` | Açık, taslak; unit-tests ve docker-build başarılı |
| PR #15 | `d899e0d3bdcc3ac520a40cd02103f9e309837d3e` | Açık, taslak; push ve PR CI başarılı |
| FAZ40 dalı | `b4cdd6358a5f55c4973b13adbb90b54820ce4c24` | Push CI başarılı |

FAZ40 ve PR #15'in ortak atası PR #12'dir. PR #15'in yeniden hash'lenmiş normal süre/uzatma kapsamı değiştirmesini reddeden düzeltmesi, yeni feature dalına `82145b1` ile dahil edildi. Main dalına merge yapılmadı. FAZ39 çalışma ağacındaki mevcut iş korunmuştur. Entegre başlangıçta 751 test geçti.

## P0: uzlaştırma, kaynak kökeni ve kanonik arşiv

`b5ffa68dd10f47edab9aa5243fe6a62b22b6daea` commit'i 767 testle doğrulandı. Push CI: [42212683873](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42212683873); PR CI: [42212728976](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42212728976). Her iki çalıştırmada unit-tests/docker-build başarılıdır.

- Sayısal FAZ13 uzlaştırmasında negatif skor ve sıfır/negatif tempo artık reddedilir. Üç hata önce regresyonlarla yeniden üretildi. Mevcut skor katsayıları değiştirilmedi.
- `faz40_archive.py`, ESPN NBA ve resmi EuroLeague Live EuroLeague/EuroCup verilerini mevcut ayrıştırıcılarla yeniden doğrular. JSON, takım dizini ve semantik maç özeti SHA-256 ile bağlanır. Hash doğrulaması bağımsız kaynak veya zaman tasdiki değildir.
- Kanonik maç kimliği lig, sezon, UTC başlangıcı ve iki takım kimliğinden oluşur. Sağlayıcı kimliği farklı olan aynı maç bir kez sayılır. Aynı takım/aynı başlangıçtaki çakışmalar, değişen sağlayıcı kimliği eşleştirmeleri ve çelişkili sonuçlar reddedilir.
- Dört çeyrek, normal süre ve uzatma periyotları ayrı tutulur. Yeni araştırma modeli REGULATION_ONLY'dir; FAZ13/FAZ28 FINAL_WITH_OT sonuçlarıyla tek performans havuzunda birleştirilmez.
- `INGESTION_TIME`, bu yeni arşiv nesnesinin gerçekten oluşturulduğu zamanı da kesite dahil eder. `ARCHIVED_SOURCE_CLOCK` yalnızca sonradan oluşturulan araştırmadır. İki moddan da canlı/prematch kayıt üretilmez.
- NBA 2026/27 normal sezon sınırı resmi sezon modülünden ayrıca kontrol edilir; yalnızca sağlayıcının regular-season bayrağına güvenilmez. Önce reddedilmeyen 1 Ekim örneği regresyonla yakalandı.

## P1/P2: açıklanabilir araştırma ve değerlendirme

`faz40_research.py`, `FAZ40_REGULATION_QUARTER_MEAN_V1` deneysel referansını ekler. Takımın geçmiş çeyrek hücum ortalaması ile rakibin yediği sayı ortalamasını birleştirir. 1Q–4Q, 1H–2H, takım toplamları, toplam sayı ve ev sahibi farkı tutarlıdır. Bu basit ortalama modeli eğitilmiş gelişmiş model olarak sunulmaz.

Takım hücum/savunma ortalamaları, ikinci yarı farkı, devre gerisinden normal sürede galibiyet oranı, yeterli iç/dış saha örneğinde ev avantajı betimlemesi, rakip skor formu, önceki başlangıçtan saat farkı ve son yedi gündeki maç sayısı hesaplanır. Rakip gücü ve yorgunluk alanları betimsel vekillerdir; nedensel veya öğrenilmiş düzeltme katsayısı değildir.

Mevcut Monte Carlo motoru uygun maç başına en az 10.000 çekilişle yeniden kullanılır. Tohum maç kimliğinden deterministik türetilir. Varyans gözlenen takım skor dağılımından alınır; artık hata kalibrasyonu değildir. Varsayılan korelasyon sıfırdır ve açık parametredir. Sıfır varyansta uydurma taban değer yerine abstention uygulanır. Normal süre ev galibiyeti/deplasman galibiyeti/beraberliği üç ayrı olaydır. Motorun eşit dönem dağıtımları çeyrek tahmini olarak kullanılmaz.

Walk-forward, her maçın başlangıcından önceki bir saniyede erişilebilir geçmişi kullanır. Kendi sonucu ve sonraki maçlar özelliklere girmez. Eğitim veya katsayı araması yapılmaz. Aynı model/lig/sezon/kapsam/kullanım grubunda ev, deplasman, toplam ve fark MAE/RMSE; üç sınıflı Brier/log-loss ve betimsel ev galibiyeti kalibrasyon kutuları/ECE hesaplayabilir. Varsayılan en az 30 uygun değerlendirme maçı yoksa toplu metrikler `null` kalır. 30 eşiği istatistiksel güvenilirlik garantisi değildir.

## Gerçek yerel arşiv denetimi (canlı kaynak sorgusu değildir)

`faz40_archive_audit.py` veri tabanını salt okunur açar; şema oluşturan store constructor'ını çağırmaz. `/data` altı, WAL/SHM/journal yan dosyası olan veya WAL başlıklı dosyalar reddedilir. Başlangıç/bitiş dosya hash'i ve SQLite bütünlüğü kontrol edilir. Bu araç aktif yazıcılı üretim veritabanı için kullanılmaz; onaylı statik araştırma snapshot'ı gerektirir.

| Lig | Kaynak gözlemleri | Özgün tam periyotlu maç | Gerçek materialization kesitinde değerlendirme | Tarihsel kaynak saatiyle araştırma tahmini |
|---|---:|---:|---:|---:|
| NBA | 107 | 75 | 0 | 5 |
| EuroLeague | 2 | 2 | 0 | 0 |
| EuroCup | 2 | 2 | 0 | 0 |

EuroLeague/EuroCup kataloglarındaki 90/85 tamamlanmış maç sayısı tam periyotlu araştırma örneklemi sayılmadı: yeniden doğrulanabilir ayrıntılı kaynak snapshot'ı yalnızca ikişer maç için mevcut. Arşiv dosyalarının SHA'ları değişmedi. Kaynak zamanları bağımsız tasdik edilmedi. Bu oturumda güncel ESPN/NBA final sorgusu veya yeni gerçek prospektif tahmin kaydı yapılmadı.

NBA'deki beş araştırma tahmini yalnızca sonradan yeniden oluşturulmuştur. Bunlar eski prematch kayıtlarının yerine geçmez:

| ESPN kimliği | Ev/deplasman kimliği | Araştırma normal süre tahmini | Arşiv normal süre sonucu | Toplam hata (tahmin−sonuç) |
|---|---|---|---|---:|
| 401909923 | 27 / 1 | 111,7143 / 111,3393 | 105 / 120 | −1,9464 |
| 401909922 | 8 / 20 | 108,4911 / 105,5804 | 106 / 112 | −3,9286 |
| 401909924 | 2 / 15 | 119,0000 / 109,6429 | 109 / 102 | 17,6429 |
| 401909926 | 18 / 4 | 114,4000 / 106,7000 | 135 / 105 | −18,9000 |
| 401909925 | 17 / 30 | 106,5982 / 105,1875 | 114 / 104 | −6,2143 |

Toplu MAE/Brier/kalibrasyon raporlanmadı: 5 < 30. Tek maç hataları nedensel açıklama veya üstünlük kanıtı değildir. FAZ31 mevcut özellik kurallarıyla ayrıca denetlendi: 3 uygun örnek, 72 reddedilen hedef; `NOT_TRAINED / MIN_100_TIMESTAMPED_EXAMPLES`. Mevcut 60 eğitim/20 doğrulama/20 test eşiği korunmuştur. En az 97 ek uygun örnek gerekir; kronolojik boşluk/purge sonrası ihtiyaç artabilir. Beş çeyrek modeli örneği ile üç FAZ31 örneği farklı uygunluk kurallarından gelir.

## Testler ve yeniden çalıştırma

Son yerel tam regresyon: **788 geçti, 0 başarısız** (başlangıca göre 37 yeni test). Son odaklı test grubu: 34 geçti. Regresyonlar dönem tutarlılığı, deterministik 10.000 çekiliş, gelecek verinin etkisizliği, yinelenen maç, sentetik/gerçek ayrımı, karma kapsam/lig retleri, bozuk kaynak, salt okunur SQLite, WAL yan dosyası oluşturmadan ret ve sezon sınırını kapsar. Sentetik testler gerçek maç doğruluğu değildir.

```sh
python -m unittest discover -s tests -v
python -m faz40_archive_audit /path/to/static-research.sqlite \
  --euro-evidence docs/evidence/euroleague-eurocup-audit-20261104.json
```

CI son commit SHA'sıyla ayrıca kontrol edilmelidir; bu raporun commit'lenmesinden önce gelecekteki CI sonucu varsayılmaz. Güncel doğrulama PR #16 üzerinde raporlanır.

## Açık veri ve üretim engelleri

1. Oyuncu dakika/verimlilik arşivi, doğrulanmış sakatlıklar, beşli stintleri, rotasyon ve garbage-time play-by-play verisi mevcut araştırma snapshot'larında yok. Eksik alanlar açıkça işaretlenir; sayı uydurulmaz. Tempo kaynak doğrulaması mevcut bileşenlerde bulunabilir ancak yeni çeyrek modeli tempo girdisini kullanmaz.
2. Yeni maçlar için zamanında gözlenmiş ve kalıcı saklanmış tam özellik kesitleri gerekir. Sonradan indirilen geçmiş kaynaklarla canlı performans iddiası yapılamaz. Diğer sezonların resmi sınırları ve NBA/EuroLeague/EuroCup dışındaki liglerin doğrulanmış dönem ayrıştırıcıları henüz eklenmedi; bu yeni hat üzerinde diğer ligler reddedilir.
3. Yerel scratch SQLite oturumlar arası kalıcılık kanıtı değildir. Dosya Git'e veya harici depolamaya yüklenmedi; ikinci Cloud ortamında kurtarma ve bağımsız kaynak zamanı tasdiki yapılmadı.
4. Gölge eğitim için yeterli PIT güvenli örnek, zaman sıralı ayrım; kalibrasyon için ayrıca ayrılmış yeterli değerlendirme dönemi gerekir. Üç/beş maça göre üretim katsayıları optimize edilmedi.

Sonraki teknik aşama oyuncu/periyot/play-by-play kaynaklarını gözlem ve ingestion zamanlarıyla ayrı araştırma sözleşmelerine bağlamak; yeterli özgün tarihsel kesit oluştuğunda kronolojik eğitim/kalibrasyon deneyi yapmaktır. Main merge, Fly.io/Telegram değişikliği, ücretli servis veya secret değişikliği yapılmamıştır.
