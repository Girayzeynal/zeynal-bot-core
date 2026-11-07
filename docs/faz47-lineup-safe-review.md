# FAZ47 güvenli devam — FAZ39/FAZ46 ilk beş sözleşmesi incelemesi

Bu checkpoint **inceleme ve entegrasyon planıdır**. PR #12 kodu PR #26'ya alınmadı; merge/cherry-pick veya üretim değişikliği yapılmadı. Tahmin motorları, kadro kapıları ve mevcut veri dosyaları bu incelemede değiştirilmedi.

## Kurtarma ve CI

İnceleme başlangıcında yerel dal `feature/faz47-source-bound-research-20261106`, HEAD `c3684df35e0eadf53285ea6743aaf141b28fd80d`; çalışma ağacı temizdi. Kaydedilmemiş çekirdek değişiklik veya çalışan test süreci yoktu. Listelenen eski git süreçleri `Zs` durumundaydı; çalışan/takılmış iş değiller, sonlandırılmaları gerekmedi. Bekleyen izin bulunmadı.

Son başarılı kod checkpoint'i **c3684df**. PR #26 açık/taslak ve uzak HEAD eşleşiyor:

| İş akışı | unit-tests | docker-build | Log |
|---|---|---|---|
| [push 42281947617](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42281947617) | success | success | 1078 test / OK |
| [PR 42282129330](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42282129330) | success | success | 1078 test / OK |

Yerel `/workspace/scratch/faz47-full.log` da 1078/1078 / OK. Son görünen gerçek veri komutu, eski arşiv CLI'sinin beklenen `ABSTAIN_SOURCE_BOUND_HISTORY_REQUIRED` sonucuyla başarılı tamamlanmasıydı. FAZ47 hazır oluş raporu ve boş stderr dosyası da korunmuş durumda. Mevcut Cloud runtime connected/running ve güncel sağlık gözlemi olumlu.

**Uzak turun kesilmesinin kesin servis nedeni bu ortamdan doğrulanamadı.** CI, git commit veya yerel test başarısızlığına dair kanıt bulunmadı. Servis/kota/model-capacity hatasını, geçmişte benzer olay yaşanmış olsa bile bu kesintinin kesin nedeni olarak göstermiyoruz. CI yeşil olduğu için üretim/çekirdek hata düzeltmesi veya kör CI retry yapılmadı.

## Sabitlenen PR #12 kaynakları

- İncelenen HEAD: `d7fb5bf25aafe504a158b564f2e4d99a84f68c89`, dal `feature/nba-command-20261104`.
- `lineup_uncertainty.py`: ilk ekleyen commit `08ca281fcfe584bdbe35b71592accc599c53b3fa`, SHA-256 `fec7a45a469b252e4753c1004c9f4eb12fd2119f253c92a0af02df0b551ff09b`.
- `tests/test_lineup_uncertainty.py`: `d7fb5bf` commit'inde eklenmiş; SHA-256 `d90c5be4427b26f3ae367701decf912a0d19b0e99a11d2c2bd6e4c8beef4149c`.

Dosyalar GitHub'dan SHA'ya bağlı okundu, git blob byte'larıyla eşleştirildi ve sadece ayrı scratch dizinine kondu. Tam d7fb5bf ağacında `git grep` sonucu yardımcı yalnızca kendi tanımı ve test dosyasından çağrılıyor; tahmin motoruna/üretim akışına bağlı olduğu doğrulanmadı. Mevcut c3684df ağacında bu iki dosya yok.

## Tekrar, fark ve çelişki

| Konu | FAZ39 aday sözleşme | FAZ46/FAZ41 kaynak kapısı | Karar |
|---|---|---|---|
| İlk beş yok | UNAVAILABLE, boş tuple | Yayımlanmamış/boş listede ABSTAIN; teyitli ilk beş eksik | Uyumlu; eksik kadro sahte beş ile doldurulmaz |
| Muhtemel ilk beş | Sağlanan beş oyuncuyla PROJECTED | Kaynak listesi SOURCE_LISTED_UNCONFIRMED; starting_five=None | Aynı şey değil. Liste ilk beş tahmini sayılmaz |
| Resmî ilk beş | `official=True`, beş uygun oyuncu, kaynak metni ve gözlem zamanı | Kaynak/izin, fixture/lig/sezon, v2 replay ve resmî duyuru sözleşmesi | OFFICIAL enum'u tek başına resmî kanıt değildir |
| PIT | İki saat verilirse observed <= prediction | observed/ingested/materialized < cutoff; cutoff gerçek saatten ileri ve tipoff'ta/sonrasında olamaz | FAZ46 kapıları korunmalı; sadece aday kontrolüyle değiştirilemez |
| Oynama/ilk beş belirsizliği | excluded/uncertain açıkça ayrılır; uncertain resmî starter olamaz | Doğrulanmış sakatlık/oynama kaynağı yoksa bilinmiyor; aktif/startFive geçmişi resmî beş yapılmaz | Aday temsil katmanında yararlı; gerçek kaynak adaptörü eksik |
| Kimlik/kardinalite | Tam string eşitliği ile duplicate ve beş oyuncu kontrolü | Whitespace reddi; sağlayıcı namespace'i içinde çapraz takım kontrolü | Aynı doğrulamayı kopyalamak yerine kanonik kimlik sınırı tek yerde tanımlanmalı |

Aday bir **DTO/sınıflandırıcıdır**, kaynak doğrulayıcısı veya tahmin/rotasyon motoru değildir. Kaynak alanının herhangi bir metin olabilmesi ve prediction_utc'nin isteğe bağlı olması bu rol için anlaşılabilir; fakat gerçek model girdisinin tek güvenlik kapısı olmasına yetmez. Bu eksik dış kontrolleri adayın mevcut altı testinin başarısızlığı diye raporlamıyoruz.

## Test sonuçları ve açık engel

- Adayın değişmemiş özgün testleri ayrı dizinde: **6/6 başarılı**.
- Mevcut FAZ46/FAZ41 ve FAZ47 ilgili regresyonları: **72/72 başarılı**.
- Ek sentetik karşılaştırma: üç durum/sıralama kontrolü **3/3** uyumlu. Gerçek modele kabul için gereken dokuz olumsuz girişin aday DTO tarafından tek başına reddedilmesi **0/9**; bunlar DTO kapsamı dışında kalan entegrasyon şartlarıdır, model doğruluk oranı değildir. Mevcut FAZ46 bu dokuz girdinin **8'ini reddetti**, bir ortak kanonik kimlik boşluğu bulundu.

| Ek kabul ölçütü | Adayın tek başına sonucu | FAZ46 sonucu |
|---|---|---|
| Kaynak metni `provider`, doğrulanmış URI/kanıt yok | OFFICIAL | SOURCE_ORIGIN_NOT_ALLOWED |
| Kaynak kullanım izni UNKNOWN | OFFICIAL | SOURCE_USAGE_NOT_ESTABLISHED |
| Prediction/cutoff yok | OFFICIAL | PREMATCH_CONTEXT_REQUIRED |
| Cutoff tipoff'ta/sonrasında | OFFICIAL | PREMATCH_CONTEXT_REQUIRED |
| Cutoff/gözlem gerçek saatten ileri | OFFICIAL | PREMATCH_CONTEXT_REQUIRED |
| observed == prediction, v2 ingestion/materialization kanıtı yok | OFFICIAL | EVIDENCE_NOT_AVAILABLE_AT_CUTOFF |
| `1` ve ` 1` farklı oyuncu sayılıyor | OFFICIAL | CANONICAL_PLAYER_IDS_REQUIRED |
| Aynı sağlayıcı oyuncusu iki takımda | OFFICIAL/OFFICIAL | CROSS_TEAM_PLAYER_ID_CONFLICT |
| Aynı takımda `1` ve `NBA:1` iki oyuncu sayılıyor | OFFICIAL | **CONFIRMED — açık engel** |

Son satır mevcut **normalleştirilmiş resmî duyuru sözleşmesinin** de eksiğidir: çapraz takımda sağlayıcı öneki çözümleniyor, aynı takım içindeki alias duplicate'i ise beş farklı oyuncu sayısına girebiliyor. Bu örnek sentetiktir; gerçek bir maçta yanlış ilk beş veya üretim tahmini oluştuğu gösterilmedi. Ham EL/EC listing adapter'ı ile normalleştirilmiş resmî duyuru sözleşmesi aynı katman değildir. Varsayılan gerçek kaynak izinleri UNKNOWN ve gerçek doğrulanmış ilk beş 0 olmaya devam ediyor.

Bu nedenle altı aday testi veya mevcut 1078 testin yeşil olması entegrasyon kabulü değildir. Yeni sınır durumları mevcut regresyon setinde henüz yok; **entegrasyon bu incelemede uygulanmadı**. Özellikle aynı-takım namespace alias'ı çözülmeden kaynak/ilk beş güvenliği tamamlandı denemez.

## Önerilen entegrasyon sırası — henüz uygulanmadı

1. Önce yeni regresyonlar: whitespace, aynı takımda bare/prefixed alias, çapraz takım alias, yabancı namespace ve aynı-saniye/eksik saat sınırları. Kanonik kimlikte sağlayıcı bilinmeli; bilinmeyen önekler körlemesine silinmemeli. Whitespace sessizce trim edilerek çelişki saklanmamalı. Sonra mevcut FAZ46 normalleştirilmiş duyuru sınırındaki aynı-takım duplicate engeli ayrı, küçük commit ile kapatılmalı.
2. FAZ46 kaynak/fixture/izin/dört-saat kapısı yetkili kalmalı. Aday ancak bu kapının arkasında sunum/geliştirme DTO'su olabilir; kendi `official=True` bayrağı kaynak otoritesi üretmemeli. Kaynak digesti, fixture/team/league/season, cutoff ve model sürümü dış immutable kayıtla bağlanmalı.
3. Durum eşleme: yayımlanmamış veya unconfirmed liste -> UNAVAILABLE + ayrı kaynak listesi; kaynağı ve zamanı kanıtlı, açıkça tahmini beş -> PROJECTED; yalnızca replay edilmiş OFFICIAL_LINEUP -> OFFICIAL. İlk beş rostering sırasından, geçmiş starter'dan, dakika sıralamasından veya haber başlığından üretilmemeli. PROJECTED için henüz uygun gerçek kaynak adaptörü yoksa ABSTAIN devam etmeli.
4. excluded/uncertain kimlikleri de aynı tarihli takım/kadro/sakatlık kanıtına bağlanmalı. Bunlar eksikse gelecekteki oynama süresi veya rotasyon etkisi uydurulmamalı. İlk adapter yalnızca read-only/geliştirme çıktısı üretmeli; referans skorlar ve FAZ24/29 kayıtları değişmemeli.
5. Aday 6 testi + yeni canonical/PIT/source kabul matrisi + mevcut tüm regresyonlar ve exact-SHA push/PR unit-tests/docker-build birlikte geçmeli. Gerçek kaynak örneği ayrıca gösterilmeli; sentetik başarı gerçek lineup veya model performansı sayılmamalı. Bundan sonra ayrı bir entegrasyon değişikliği değerlendirilebilir; bu rapor merge uygulaması değildir.

Yeniden üretim için `tools/review_faz39_lineup_contract.py` yalnızca iki dosyanın yukarıdaki hash'leri ve mevcut kaynak-kapısı baseline hash'leri eşleşirse incelenmiş DTO'yu **ayrı CLI sürecinde** yükler. Aday pin'i değiştirilmiş bir dosya yürütülmeden reddedildi; sonuç dosyası oluşturulmadı. Betik uygulamaya import/install etmez; bulunmuş engelleri raporlar ve sıfır çıkış kodu incelemenin tamamlandığı anlamına gelir, entegrasyon kabulü anlamına gelmez.

```bash
# Aday dosyalar ayrı dizinde, d7fb5bf SHA'sındaki byte'larla bulunmalıdır.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python tools/review_faz39_lineup_contract.py \
  --candidate-root /workspace/scratch/faz47-lineup-review \
  --output /workspace/scratch/faz47-lineup-review-new-result.json
```

## Gerçek performans ve kalıcılık

Korunan c3684df hazır oluş artefact'ında gerçek tahmin–sonuç çifti **0**, yeni prospektif tahmin **0**, kalibrasyon **NOT_ESTABLISHED**. Bu inceleme yeni basketbol veri isteği veya gerçek tahmin üretmedi. Hiçbir güvenlik kabul oranı MAE/Brier/log-loss veya model doğruluğu değildir. Harici kalıcılık ve bağımsız ikinci Cloud kurtarması hâlâ doğrulanmadı. Main merge, Fly.io/Telegram production, scheduler, secret veya harici ham veri yüklemesi yok.
