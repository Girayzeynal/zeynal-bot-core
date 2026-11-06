# FAZ45 — oyuncu ve PBP kanıtının skor arşivine bağlanması

Başlangıç: PR #23 / `5feacab0c1e33174045f9429b3ead7564f3089b3`. Başlangıç push 42252682557 ve PR 42252693429 unit-tests/docker-build başarılı; son log'lar 981/OK. Yeni feature dalı `feature/faz45-player-evidence-20261106`, PR tabanı FAZ44 dalıdır. Eski FAZ13–44 modeller, kayıtlar ve kanıtlar değiştirilmez.

## Uygulanan araştırma katmanı

`faz45_support.py`, FAZ42 global kimlik/skor replay kapısını, FAZ41 oyuncu adapter'ını ve `historical_player_features` kapısını, FAZ43 timeline replay'ini yeniden kullanır. Yeni model veya üretim katsayısı eklemez. Oyuncu/PBP gözlemi aynı kanonik maçın skor gözlemiyle bağlanır; normal süre, uzatma, periyot ve final skorları eşit olmalıdır. Doğru toplam dakika, yanlış final skoru taşıyan bir gözlemi geçerli yapmaz.

Hem skor hem yardımcı gözlemin observed/ingested/materialized zamanları cutoff'tan **kesinlikle önce** olmalı; cutoff gerçek saatten sonra ve maç başlangıcında/sonrasında olamaz. Sonradan alınan eski maç verisi eski cutoff'a geri doldurulmaz. Hedef maçın finali, sonraki maçlar, başka sezon/lig, eski kaynak ve izinsiz gözlem kullanım dışıdır. Her iki kaynağın izin politikası cutoff anında geçerli olmalıdır. UNKNOWN yalnızca kapsam envanteri verir; sayısal özellikler `None` kalır.

Aynı maçın tekrar gözlemleri/sağlayıcı alias'ları örnek sayısını artırmaz. Çelişkili oyuncu düzeltmeleri sessizce en son kayıt seçilerek kapatılmaz. Kaynaklar arasında oyuncu kimlikleri eşlenmiş varsayılmaz. Son N maç zaman sırasıyla seçilir; kaynak SHA ve maç kimlikleri özelliklerde tutulur.

Yeterli izinli PIT örneğinde üretilen araştırma özellikleri: oyuncu bazında bildirilen dakika toplamı/ortalaması, görünüm ve geçmiş ilk beş sayısı, sayı toplamı, dakika hassasiyeti ve uzatma kapsamı; PBP için ikinci yarı–ilk yarı fark değişimi, normal süre comeback sayısı ve açık kurala dayanan garbage-time olay sayısı. Bunlar oyuncu gücü, nedensel rotasyon etkisi, eğitilmiş garbage-time modeli, yeni tahmin veya doğruluk ölçümü değildir.

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
