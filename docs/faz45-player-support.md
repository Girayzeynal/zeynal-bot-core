# FAZ45 — oyuncu ve PBP kanıtının skor arşivine bağlanması

Başlangıç: PR #23 / `5feacab0c1e33174045f9429b3ead7564f3089b3`. Başlangıç push 42252682557 ve PR 42252693429 unit-tests/docker-build başarılı; son log'lar 981/OK. Yeni feature dalı `feature/faz45-player-evidence-20261106`, PR tabanı FAZ44 dalıdır. Eski FAZ13–44 modeller, kayıtlar ve kanıtlar değiştirilmez.

## Uygulanan araştırma katmanı

`faz45_support.py`, FAZ42 global kimlik/skor replay kapısını, FAZ41 oyuncu adapter'ını ve `historical_player_features` kapısını, FAZ43 timeline replay'ini yeniden kullanır. Yeni model veya üretim katsayısı eklemez. Oyuncu/PBP gözlemi aynı kanonik maçın skor gözlemiyle bağlanır; normal süre, uzatma, periyot ve final skorları eşit olmalıdır. Doğru toplam dakika, yanlış final skoru taşıyan bir gözlemi geçerli yapmaz.

Hem skor hem yardımcı gözlemin observed/ingested/materialized zamanları cutoff'tan **kesinlikle önce** olmalı; cutoff gerçek saatten sonra ve maç başlangıcında/sonrasında olamaz. Sonradan alınan eski maç verisi eski cutoff'a geri doldurulmaz. Hedef maçın finali, sonraki maçlar, başka sezon/lig, eski kaynak ve izinsiz gözlem kullanım dışıdır. Her iki kaynağın izin politikası cutoff anında geçerli olmalıdır. UNKNOWN yalnızca kapsam envanteri verir; sayısal özellikler `None` kalır.

Aynı maçın tekrar gözlemleri/sağlayıcı alias'ları örnek sayısını artırmaz. Çelişkili oyuncu düzeltmeleri sessizce en son kayıt seçilerek kapatılmaz. Kaynaklar arasında oyuncu kimlikleri eşlenmiş varsayılmaz. Son N maç zaman sırasıyla seçilir; kaynak SHA ve maç kimlikleri özelliklerde tutulur.

Yeterli izinli PIT örneğinde üretilen araştırma özellikleri: oyuncu bazında bildirilen dakika toplamı/ortalaması, boxscore girdi ve geçmiş ilk beş sayısı, sayı toplamı, dakika hassasiyeti ve uzatma kapsamı; PBP için ikinci yarı–ilk yarı fark değişimi, normal süre comeback sayısı ve açık kurala dayanan garbage-time olay sayısı. Bunlar oyuncu gücü, nedensel rotasyon etkisi, eğitilmiş garbage-time modeli, yeni tahmin veya doğruluk ölçümü değildir.

Tarihsel boxscore ilk beşi gelecekteki kadro değildir. Doğrulanmış prematch kadro ve açık incoming/outgoing rolleri yoksa kadro/rotasyon ABSTAIN. ESPN katılımcı sırası veya İngilizce oyuncu değişikliği metni üzerinden rol çıkarılmaz. Tam dakika gösterimi kesin saniye sayılmaz. Oyuncu final skor/dakika toplamları uzatma içeriyorsa normal süre oyuncu özellikleri gibi sunulmaz.

## Açıkça istenen, sınırlı veri toplama

`faz45_collection.py` yalnızca mevcut pin'li FAZ44 skor paketinde bulunan 1–6 açık sağlayıcı maç kimliğini kabul eder. Varsayılan ağ isteği 0; `--live` gerekir. ESPN summary veya EuroLeague/EuroCup stats endpoint'ine birer bounded GET yapar; 403/429/ağ/belge hatasını ayrı saklar, otomatik retry yapmaz. EL/EC stats, hash ile bağlı önceki game belgesiyle birleştirilir ve skorları tekrar uzlaştırılır.

Oyuncu ve PBP sonuçları bağımsız doğrulanır: bozuk PBP iyi dakika kaydını silmez, iyi dakika da bozuk PBP'yi onarmaz. Eksik bilgi üretilmez. ESPN body, replay için gerekli alanlara daraltılır; makale/haber/video metni oyuncu belgesine taşınmaz. Yeni gözlem gerçek toplama zamanı taşır; eski input dosyasına yazılmaz.

Yardımcı paket dışarıdan güvenilen SHA, bağlı skor input SHA'sı, registry pin'i, kaynak response digest'i ve tamamlanmış transport receipt'i gerektirir. Manifest hash'i kendi başına sağlayıcı imzası veya bağımsız zaman kanıtı değildir. Metadata değişip hash yeniden hesaplansa da kaynak semantiği tekrar replay edilir.

Yerel yayın FAZ44'ün test edilmiş 0600/temp/fsync/exclusive-link/dizin-fsync mekanizmasını kullanır. İki format/prefix açıkça izinlidir; FAZ44 eski arayüzü korunur. Aynı içerik tekrar yayımlanmaz; farklı içerik üzerine yazılmaz. Dosyalar yalnızca `/tmp` veya `/workspace/scratch` altında tutulur. Bu bir tahmin ledger'ı veya oturumlar arası kalıcı depolama değildir.

```bash
python -m faz45_collection --collect --live \
  --score-inputs /workspace/scratch/faz44-inputs-session.json \
  --trusted-score-sha256 SCORE_PAYLOAD_SHA \
  --identities ESPN:401909936 EUROLEAGUE_LIVE:E2026_87 \
  --output /workspace/scratch/faz45-support-session.json

python -m faz45_collection --audit \
  --score-inputs /workspace/scratch/faz44-inputs-session.json \
  --trusted-score-sha256 SCORE_PAYLOAD_SHA \
  --support-inputs /workspace/scratch/faz45-support-session.json \
  --trusted-support-sha256 SUPPORT_PAYLOAD_SHA \
  --target-canonical-id VERIFIED_CANONICAL_ID
```

İsteğe bağlı gerçekten incelenmiş kaynak politikası kullanılacaksa iki komuta da `--source-policy` / `--trusted-policy-sha256` çifti gerekir; FAZ44 input zaten aynı politikaya bağlı olmalıdır. Varsayılan UNKNOWN değiştirilmez. Geliştirme `/analyze` sayısal modeli bu yeni tanımlayıcı özellikleri otomatik kullanmaz; bu aşama veri ve araştırma bağlantısıdır.

## Doğrulama ve açık sınırlar

Pozitif testler mock/sentetik kaynak sözleşmeleridir, gerçek tahmin performansı değildir. Yeni testler PIT sınırı, skor ve oyuncu/PBP çelişkileri, çoklu sağlayıcı kimliği, duplicate/alias, izin expiry, tarihi hedefin final sızıntısı, OT kapsamı, EL/EC saniye alanları, receipt/pin eksikliği, 403/429 ve eşzamanlı atomik yayını kapsar.

İlk odaklı çalışmada test fixture'ının yanlış elle hesaplanmış yarı-fark beklentisi düzeltildi: 1H 50–55, 2H 47–53, değişim −1. Ardından EL/EC composite belgesinden skor replay'inin `game` alt nesnesini alması gerektiğini regresyon yakaladı; katmanlar arası bağlantı düzeltildi. Guard gevşetilmedi.

Gerçek araştırma sonuçları ve exact SHA test/CI kanıtı sonraki checkpoint'te raporlanır. Kaynak izinleri, NBA resmî çapraz onayı, haber izinleri, doğrulanmış prematch kadro/rotasyon, güncel model kalibrasyonu, bağımsız ikinci Cloud kurtarma ve kalıcı gerçek storage henüz tamamlanmış değildir. Gerçek scheduler, production Telegram/Fly, secrets veya ücretli kaynak etkinleştirilmez. PR'lar taslak kalır; main merge yapılmaz.

Kod aşaması yerel sonuç: **1011/1011**, 30 yeni test; FAZ44 uyumluluk testleri dahil odaklı grup **47/47**, başarısızlık 0. Kanıt: `docs/evidence/faz45-support-tests-20261106.json`.

## Gerçek kaynak denemesi

Toplama kod SHA'sı `4b185bd153d1fb0ed0700a8c18a5d2e46b9a865a`; [push 42256001492](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42256001492) ve [PR 42256093263](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42256093263) unit-tests/docker-build başarılı; iki unit log 1011/OK. PR #24 taslak ve tabanı PR #23 dalı.

2026-11-06 16:49:58–59 UTC'de (19:49:58–59 TSİ) beş public GET, beş oyuncu-dakika gözlemi ve iki PBP gözlemi verdi:

| Lig | Oyuncu-dakika maçları | Boxscore girdisi | Dakika bildirilen satır | Skor/periyot replay geçen PBP |
|---|---:|---:|---:|---:|
| NBA | 3 | 79 | 71 | 2 |
| EuroLeague | 1 | 24 | 24 | 0 |
| EuroCup | 1 | 21 | 21 | 0 |
| Toplam | 5 | 124 | 116 | 2 |

NBA kaynakları: ESPN 401909922/401909936/401909937; EL: E2026_87; EC: U2026_91. Tüm dakika ve sayı toplamları kendi maç skor kanıtına bağlanarak replay edildi. NBA'nin 8 açık DNP satırına dakika uydurulmadı. NBA dakika gösterimi tam dakika hassasiyetinde; EL/EC saniye alanı kullanıldı. EuroCup'ta bir 0 saniyelik satır var. EL/EC payload'ında açık oynadı/DNP bayrağı olmadığı için boxscore girdisi kesin maç görünümü sayılmadı. Son iyileştirme bunu `boxscore_entries`, `explicit_played_status_entries`, `positive_reported_minutes_entries` ve `zero_reported_minutes_entries` ile ayırır; iki yeni regresyon eklendi.

401909936 ve 401909937 timeline'ları sırasıyla 478 ve 505 olay içerir; periyot sınırları ve final skorları uzlaştı. Toplam 151 oyuncu değişikliği olayının incoming/outgoing rolleri doğrulanmamış olduğundan rotasyon **ABSTAIN**. İki akışta wallclock alanı mevcut olması bağımsız olay tamlığı veya kaynak zamanı attestasyonu sayılmadı. 401909922 PBP'si `SCORE_CORRECTION_OR_MISSING_SCORING_EVENT` ile reddedildi; olay/skor onarımı yapılmadı. İyi oyuncu verisi bu ret nedeniyle silinmedi.

NBA/EL/EC ileriye dönük araştırma hedeflerinde izin kapısı usable player/PBP sayısını **0** tuttu; sayısal özellikler üretilmedi. 401909937'nin tarihsel cutoff denemesinde bugünkü gözlemler `AUXILIARY_NOT_AVAILABLE_AT_CUTOFF` ile dışlandı; hedef ve sonraki sonuçlar ayrıca reddedildi. Hiçbir gözlem eski prematch kaydı olarak etiketlenmedi. Yeni prospektif tahmin 0; yeni MAE/RMSE/Brier/log-loss veya kalibrasyon iddiası yok.

Paket payload SHA `45b5d8143a3eb49de5b989ce52d9ab980fcf647bc0bef8ccb9da3a496cb0bce6`, salt okunur skor input SHA `243c7b571128ec55fd8172b02ff29119847687a754ac9294afbc11589f176f1e`. Aynı yardımcı paketin tekrar yayını `created=False`; iki dosya hash'i değişmedi. SQLite salt okunur integrity_check `ok`, SHA `43adc6de12bc065e38b666dad8ba2cd9a48c5786c1185b396de5a37ebe4dd002`. Önceki 76 kanıt dosyası byte düzeyinde aynı kaldı. Ayrıntılar: `docs/evidence/faz45-real-support-20261106.json`. Ham sağlayıcı body'leri ve araştırma paketi harici storage'a/GitHub'a yüklenmedi; yalnızca durum, sayılar, kaynak URL/zaman/digest ve ret metadatası raporlandı.

Son dakika/oynama ayrımı düzeltmesi sonrası tam regresyon **1013/1013**, toplam 32 yeni test; FAZ44 uyumluluğu dahil odaklı grup **49/49**. Son SHA CI ayrıca doğrulanır. Gerçek toplama önceki code SHA'sıyla kalır; yeni commit'te yeniden yapılmış gibi etiketlenmez.

### Sonraki bağımlılıklar

Gerçek izin kanıtları ve yeterli takım/oyuncu zaman serisi olmadan bu beş maça göre katsayı/eğitim/kalibrasyon ayarlanmaz. İlk iş izinli PIT oyuncu/kadro kaynaklarının kapsamını büyütmek ve fixture duyurularını mevcut açık prematch sözleşmesine bağlamaktır. Ardından yeterli kronolojik eğitim/validasyon/test örnekleriyle aynı maçlarda referans/gölge model karşılaştırması yapılabilir. PBP score replay'i ikame oyuncu rolleri, lineup effect, bağımsız NBA resmî çapraz onayı veya gerçek model üstünlüğü kanıtı değildir.

Yerel dosya oturumlar arası kalıcılık sağlamaz. İkinci Cloud runtime/harici storage doğrulaması yok; kalıcı tahmin ledger'ı ve production zamanlayıcı OFF. Sonraki oturumda yerel paket yoksa yeni toplama yeni zaman damgasıyla yapılmalı; eski SHA ve gözlem zamanları yeniden üretilmemelidir. Master kapsamı tamamlanmış değildir.
