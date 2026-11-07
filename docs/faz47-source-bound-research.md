# FAZ47 — kaynak kanıtına bağlı araştırma ve eğitim uygunluğu

Başlangıç: PR #25 / `34c6a72f4df9c43c5b1dc3055a552140933e3850`; push 42262513279 ve PR 42262524544 unit-tests/docker-build başarılı, iki unit log 1049/OK. Dal `feature/faz47-source-bound-research-20261106`, PR tabanı FAZ46 dalıdır. FAZ13/FAZ28 katsayıları ve özgün kayıt/kanıtlar korunur.

## Kapatılan araştırma girişleri

`research_with_context`, prematch bağlamını doğruluyor fakat v1 FAZ40 arşivini doğrudan `project` işlevine verebiliyordu. Boş bağlam ve eski `ARCHIVED_SOURCE_CLOCK` seçimi, geçmiş skorlara izin/PIT kanıtı kazandırmıyordu. İki yeni negatif testte gerçek-araştırma etiketli **sahte test verisi**, kaynak kanıtı olmadan sayısal projeksiyon üretti; üçüncü test sentetik/gerçek karışımının ancak model çağrısından sonra reddedildiğini gösterdi. Üç test düzeltmeden önce başarısız oldu. Bu bulgu üretim Telegram yolunda bir dağıtım veya gerçekleşmiş tahmin iddiası değildir.

Gerçek araştırma arşivi artık `history_evidence` v2 kaynak gözlemlerine bağlanır. Kanonik maç evreni, sağlayıcı alias'ı/URL, dört çeyrek, normal süre, uzatma ve final skorları replay edilerek eşleşir. Eksik/fazla gizli maç, değişmiş skor, yanlış alias ve sentetik/gerçek karışımı simülasyon öncesinde reddedilir. Tekrar gözlem/alias örneklem sayısını artırmaz. `INGESTION_TIME` veya `ARCHIVED_SOURCE_CLOCK` isteği, uygulanan **FAZ42_STRICT_PUBLISHED_OBSERVED_INGESTED_MATERIALIZED** kapısını değiştiremez.

V1 sarmalayıcı yeniden üretildiğinde ingestion/materialization bugünün saati olabilir; model uygunluğunu bu yeni sarmalayıcının veya v1 kaynak saatinin değil, özgün v2 kanıtının dört saati ve pin'li izin politikası belirler. Eski kayıtlar yeniden yazılmaz. UNKNOWN veya süresi geçmiş izin sayısal çıktı vermez. Kaynak izni kendiliğinden yükseltilmez.

Doğrudan `faz40_archive_audit` gerçek-veri CLI'sinde de benzer bir giriş vardı: varsayılan çalışma v2 kanıt olmadan backtest başlatabiliyordu. İki ek negatif regresyon bu model çağrısını yakaladı. Varsayılan CLI artık salt okunur kapsam ve **ABSTAIN_SOURCE_BOUND_HISTORY_REQUIRED**, sıfır değerlendirme ve `metrics=None` verir. Açıkça `--synthetic` ile etiketlenmiş deneysel/test yolu korunur. Güvenli gerçek araştırma için yeni pin'li `faz47_readiness` yolu kullanılır. Düşük seviyeli FAZ40 aritmetik primitive'leri değiştirilmedi; bunlar kaynak izni kapısı değildir.

## Gerçek kullanım etiketleri ve Monte Carlo

İzinli ve PIT uygun tarihsel `RETROSPECTIVE_RESEARCH` verisi ile gerçekten maç öncesi alınmış `PROSPECTIVE_EVIDENCE` bağlamı aynı araştırmada kullanılabilir. İki etiket de özgün haliyle korunur; araştırma çıktısı bu nedenle canlı/prospektif performans sayılmaz. Sentetik/gerçek karışımı yine yasaktır. Yeni kadro/oyuncu bağlamı üretim katsayılarına uygulanmaz.

Kaynak kapılı yol mevcut 10.000+ Monte Carlo/çeyrek aritmetiğini kullanır; correlation ve seed taşınır, varsayılan correlation 0.0 değişmez. Boolean, NaN veya −1/+1 sınırındaki geçersiz korelasyon reddedilir. Tüm sentetik kaynaklar izin nedeniyle dışlansa bile boş uygun küme gerçek araştırma örneklemi olarak etiketlenmez. Testteki izinli protokol ve hesaplanan metrikler gerçek maç başarısı değildir.

## Salt okunur hazır oluş raporu

`faz47_readiness.py` ayrı dış pin'lerle FAZ44 skor girdisini, isteğe bağlı FAZ45 oyuncu/PBP paketini ve FAZ46 prematch audit'ini okur. Kaynak izni/kapsam envanteri, kanonik skor bağlaması, kronolojik validation/test ve son tarihsel hedef için katmanlar arası ret nedenleri raporlanır. Üçten az farklı başlangıç grubu varsa train/validation/test ayrımı zorlanmaz; metrikler `None` kalır. Aynı başlangıç zamanındaki maçlar aynı zaman bölümünde kalır. Varsayılan minimum ölçüm örneği 30; katsayı veya hiperparametre eğitimi/seçimi yapılmaz.

Yan paketler skor modelini sessizce değiştirmez. Oyuncu/PBP araştırması ayrıca gösterilir; başka fixture'ın kadrosu hedefe taşınmaz. İncelenen eski kaynakların tamamı son hedef tipoff'undan sonra materialize edildiyse bu da açıkça işaretlenir. İzin ve PIT eksikliği birbirinin yerine başarılı gösterilmez.

CLI gerçek/sentetik ayrımını zorunlu tutar; gerçek-data CLI'si sentetik skor girdisini kabul etmez. Çalışan temiz feature HEAD ve module hash manifest'i hesap öncesi ve sonrası doğrulanır. Input dosyalarının byte hash'leri sabit kalmalıdır. Sayısal model adı aynı kalırken çalıştıran SHA ayrıca kaydedilir; eski input üretim SHA'sı yeni çalıştırma SHA'sı gibi gösterilmez.

```bash
python -m faz47_readiness \
  --score-inputs /workspace/scratch/faz44-inputs-session.json \
  --trusted-score-sha256 SCORE_PAYLOAD_SHA \
  --support-inputs /workspace/scratch/faz45-support-session.json \
  --trusted-support-sha256 SUPPORT_PAYLOAD_SHA \
  --prematch-audit /workspace/scratch/faz46-prematch-session.json \
  --trusted-prematch-sha256 PREMATCH_PAYLOAD_SHA \
  --output /workspace/scratch/faz47-readiness-session.json
```

Varsayılan kaynak politikaları UNKNOWN. Gerçekten incelenmiş politika kullanılacaksa `--source-policy` / `--trusted-policy-sha256` çifti ve aynı politikaya bağlı input paketleri gerekir. Source-policy dosyası da salt okunur hash kontrolüne dahildir. Yeni rapor yalnızca yerel, izinli prefix/format ve 0600/fsync/exclusive-link yayımlayıcısıyla oluşturulur. Bu bir tahmin ledger'ı, harici kalıcılık veya ikinci Cloud kurtarma kanıtı değildir. Ağ isteği, Telegram/Fly, scheduler, secret veya ücretli kaynak yok.

## Doğrulama sınırları

Odaklı grup eski FAZ40/41/42 uyumluluğuyla 54/54: 29 yeni test. Başlangıç üç kaynak/karışım ve iki doğrudan CLI negatif testi önce başarısız oldu; yeni kapılarla geçti. Yanlış pin, kaynak zamanı, alias/skor çelişkisi, izin expiry, duplicate, runtime SHA değişimi, correlation ve sentetik sınıflandırma test edildi. Son tam regresyon ve gerçek yerel veri denemesi ayrı checkpoint'te raporlanır.

Üretim katsayıları, özgün FAZ24/29 kayıtları, önceki kanıt dosyaları ve gerçek veri artefact'ları değiştirilmez. Yeni model üstünlüğü, eğitim/kalibrasyon başarısı veya üretime hazır sistem ilan edilmez. Main merge, production deploy, harici yükleme ve gerçek scheduler/storage aktivasyonu yok. PR taslak kalır.

Kod checkpoint son tam yerel regresyon: **1078/1078**, 29 yeni test, başarısızlık 0; odaklı grup 54/54. Kanıt: `docs/evidence/faz47-tests-20261106.json`.
