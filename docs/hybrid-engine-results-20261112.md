# Hibrit motor araştırma sonucu — 12 Kasım 2026

Güncel arşiv tanığı ve gerçek OOS sonucu: [hybrid-root-cause-20261112.md](hybrid-root-cause-20261112.md).

Sonraki sıkı kabul denetimi: [hybrid-acceptance-20261112.md](hybrid-acceptance-20261112.md).
Bu dosyadaki varsayımlı sonuçlar `962e16d` deneyinin tarihsel kaydıdır.

**Karar: üretim V1 değişmeyecek.** Yeni motor ayrı araştırma dalındadır.
Kabul koşulunu karşılayan, doğrulanmış üstünlük gösterilemedi. Main merge,
Fly deploy, yeni kaynak, secret veya üretim SQLite işlemi yapılmadı.

## Uygulanan bileşenler

- `hybrid_engine/data.py`: pinned arşiv, sezon/lig izolasyonu, hedef etiketini
  çıkaran cutoff, son 10 maçtan en az 6 geçmiş, kaynak saatleri ve input digest.
  Faz13 sayısal referansı mevcut `historical_research.reference_predict` üzerinden
  kullanılır; skor/periyot ve gerçek üretim MC eşdeğerliği test edildi.
- `possession.py`: top kaybı, 2/3 sayılık şut, serbest atış, faul ve hücum ribaundu
  devamını içeren absorbing reward zinciri. Birincil yöntem analitik konvolüsyon;
  ikinci yöntem aynı reward dağılımını örnekleyen 10.000 MC senaryosudur.
  Takımların skorları ortak tempo üzerinden bağımlıdır. Periyotlar tarihsel
  skor profiline göre ayrılır. Possession sayısı box-score tahminidir;
  iki serbest atışlık trip varsayımı and-one/üç serbest atış/teknik faul ayrımı değildir.
- `models.py`: Gaussian empirical Bayes hiyerarşisi, lig intercept'i, ev avantajı,
  takım hücum/savunma etkileri ve posterior kovaryans. Küçük örneklem kısmi
  havuzlamayla, görülmemiş takım prior varyansıyla ele alınır. Oyuncu katsayıları
  yalnızca maç öncesinde gözlenmiş tam projected-minute arşiviyle açılır.
  Sonradan toplanan gerçek oyuncu dakikaları bu amaçla kullanılmaz.
- Semi-Markov adayında çeyrek, skor farkı ve son 120 saniye bağlamı ile reward ve
  holding time bulunur. Gerçek, etiketlenmiş possession sınırları ve yeterli bağlam
  kapsaması yoktur: **gerçek veride eğitilmedi/etkinleştirilmedi**. Sentetik test
  doğruluğu, gerçek maç üstünlüğü sayılmadı. Gözlenen holding-time ortalamaları,
  tam bir sürekli süre dağılımı veya doğrulanmış maç sonu faul stratejisi değildir.
- LightGBM 4.6.0 / CatBoost 1.2.8: 30 tarihsel skor/periyot/zaman-aralığı özelliği,
  60 iterasyon, depth 3, sabit seed, tek thread, yalnızca offline TRAIN eğitimi.
  Test verisiyle hyperparameter veya özellik seçilmedi. Olasılık dağılımı, yalnızca
  geçmiş VALIDATION residual ölçeği yeterliyse açılır; bu kalibrasyon eğitimi değildir.
- `evaluation.py`: etiket erişim gecikmesiyle purged, benzersiz başlangıç saatlerinde
  %60 TRAIN / %20 VALIDATION / %20 TEST. Bayesian/ML parametreleri validation
  başlamadan dondurulur. Per-maç kayan özellikler yalnızca o maçın cutoff'undan
  önceki geçmişi kullanır. Ensemble'ın tek ortak convex ağırlık vektörü yalnızca
  VALIDATION OOS tahminlerinde takım skoru MSE'sinden öğrenilir. Tüm pazar ve
  periyotlar aynı ağırlıkları kullanır. Tahmin sırasında eğitim çalışmaz.

Çeyrek → yarı → maç, takım toplamı, toplam, fark ve ev handikabı aynı skor
yapısından türetilir; integer simülasyon yollarında toplamlar tam eşittir.
Normal süre eşitliği ayrı sınıftır; uzatma dahil değildir. Gaussian çeyrek
senaryoları tarihsel ağırlıklara deterministik ayrılır; bağımsız veya kalibre
edilmiş çeyrek belirsizliği iddiası yoktur.

## Veri ve kanıt sınırı

640 gerçek tamamlanmış maçın 640'ında native takım/oyuncu box score eşleşti:
NBA 2026/27 160, EuroLeague 2026/27 100, EuroLeague 2025/26 380.
Toplam 27 uzatmalı maçın box toplamları normal süre possession eğitimine alınmadı.
Skor modelleri ilk dört periyodu kullanır. Veri, tam bağımsız sezon kapsamı değildir.

İlk paralel toplamada 350, kontrollü devamda 1 HTTP 429 gözlendi. Kalıcı provider
cooldown ve yavaş, tek worker devamla son eksik sayısı sıfırlandı. Bu geçmiş
rate-limit hataları gizlenmedi. Ağır toplama/eğitim Telegram isteğinde yapılmaz.

**PIT_PROVEN_BACKTEST: 0 uygun tahmin.** Arşiv gözlem/ingestion zamanları sonradandır.
Aşağıdaki sonuçlar yalnızca `AVAILABILITY_ASSUMED_RESEARCH` sınıfındadır:
önceki maç start+24h erişilebilir varsayılmıştır; bu, eski gözlem saatlerinin
değiştirilmesi veya gerçek prospective başarı değildir. Kaynak eğitim izni
`NOT_ESTABLISHED` olarak korunur. Yeni kaynak provenansı veya hak sahipliği
attestasyonu uydurulmadı.

424 hedefte geçmiş yeterliydi; 216 hedefte model abstain etti. Fold etiket
gecikmesi sonrası sayılar:

| Lig / sezon | Train | Validation | Test |
|---|---:|---:|---:|
| EuroLeague 2025/26 | 188 | 60 | 66 |
| EuroLeague 2026/27 | 20 | 7 | 8 |
| NBA 2026/27 | 36 | 4 | 10 |

Güncel sezonlarda ML için 100 TRAIN, ensemble/residual ölçeği için 30 VALIDATION
alt sınırı sağlanmadı; bu bileşenler abstain etti. Başlangıç arşivindeki geçmişi
yetersiz maçlar, Bayesian takım gücü için geçmiş label olarak kullanılabilir;
ML eğitim örneği sayısıyla ham Bayesian eğitim maçı sayısı aynı değildir.

## EuroLeague 2025/26 — aynı 66 test maçı

| Model | Takım MAE | Takım RMSE | Toplam MAE | Fark MAE | Brier | Log loss | Ev kazanır ECE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Faz13 / gerçek V1 MC | **7.7473** | 9.9650 | 12.5568 | 9.1689 | .5492 | .9120 | .1471 |
| Faz13 analitik | 7.7473 | 9.9650 | 12.5568 | 9.1689 | .5465 | .9045 | .1427 |
| Faz13 RQMC | 7.7473 | 9.9650 | 12.5568 | 9.1689 | .5465 | .9044 | .1428 |
| Possession analitik | 7.8997 | 10.2901 | 13.3136 | 9.2834 | .5522 | .9178 | .1342 |
| Bayesian | 7.7613 | **9.7529** | **12.5020** | 8.5899 | .5093 | .8795 | .0681 |
| LightGBM | 8.2466 | 10.4243 | 13.2254 | 9.0739 | .5350 | .9067 | .1916 |
| CatBoost | 8.1201 | 10.2029 | 13.2348 | 8.8109 | .5241 | .8834 | .1363 |
| Validation ensemble | 7.7789 | 9.7673 | 12.5883 | **8.4592** | **.5067** | **.8722** | **.0584** |
| Geçmiş lig ortalaması | 8.4193 | 10.7664 | 14.3193 | 9.4697 | .5712 | .9468 | .0875 |
| Son maçlar atılan sayı | 8.3144 | 10.4269 | 13.1500 | 9.3106 | .5642 | .9302 | .1558 |

Brier üç sınıflı normal süre ev/eşitlik/deplasman toplam kare hatasıdır;
log loss doğal log kullanır. ECE yalnızca evin normal sürede kazanması için
10 eşit genişlikli bin üzerindedir. ECE'nin küçük değeri tek başına kalibrasyon
kanıtı değildir; bin sayımları JSON raporundadır.

Ensemble ağırlıkları yaklaşık Bayesian %68.79, CatBoost %29.56, lig ortalaması
%1.66; diğerleri sıfırdır. Bu ağırlıklar **test hatalarından seçilmedi**.
Validation'da en düşük ortak-maç takım MAE adayı CatBoost'tu; testte Faz13'ten
kötü çıktı. Gözlenen test sıralaması yeni seçim/eğitim için kullanılmadı.

Ensemble Brier farkı −.04256; paired-game %95 bootstrap aralığı
**[−.10568, +.02742]**. Log loss farkı −.03976 aralığı
**[−.10891, +.03666]**. İkisi de sıfırı içerir. Bunlar IID maç bootstrap'idir;
ortak takımlar ve zamansal bağımlılık için tam sağlamlık iddiası yoktur.
Hiçbir pazarda kanıtlanmış genel üstünlük ilan edilmez.

NBA 10 test maçında takım MAE: Faz13 10.6302, possession 10.5462, Bayesian
10.8575. Güncel EuroLeague 8 maçta: Faz13 10.2813, possession 9.7661,
Bayesian 10.2040. Bu küçük örnekler üstünlük kanıtı değildir.

1Q–4Q, 1H/2H, takım toplamları, spread ve toplamlar için MAE/RMSE ile
dağılımın desteklediği under/push/over Brier/log loss raporlanır. **Tarihsel
bookmaker çizgileri yoktur.** Değerlendirme çizgileri tahmin öncesi Faz13
projeksiyonlarıdır; piyasa kazanma oranı, bahis getirisi veya edge değildir.
Mevcut V1 sampler yalnızca winner/total karşılaştırmasına açılır; yeni yöntemlerin
periyot olasılıkları V1'le doğrulanmış üstünlük gibi sunulmaz.

## Hız ve bellek

Tek CPU affinity + `prlimit --as=268435456` altında, 20 tekrar, tek BLAS thread,
çekirdek modeller ve gerçek arşiv yüklüyken tepe RSS **107.5 MiB**.
Her çağrı 2 saniyelik bütçenin altında kaldı. Kesin zamanlar ve kaynak hash'leri
`hybrid-engine-evidence-20261112.json` içindedir.

| Aynı bağımsız rounded-normal skor varsayımı | p95 yaklaşık | Analitik yasaya olasılık RMSE |
|---|---:|---:|
| MC 10.000 | 12 ms | .00410 |
| Random-shift Halton QMC 10.000 | 20 ms | .00072 |
| Analitik | 0.5 ms | 0 |

QMC bu deneyde sayısal entegrasyon hatasını azalttı; MC'den hızlı değildi.
Bu tablo gerçek maç doğruluğu veya kalibrasyon üstünlüğü değildir. Gerçek veri
çekirdek ölçümünde Faz13 yaklaşık 116–126 ms, possession analitik 9–11 ms,
possession MC 34 ms, Bayesian QMC 10–11 ms p95 düzeyindedir.

Docker ile aynı ölçüm yerel diskte vfs katman kopyalama alanı yetmediği için
başlamadı; sonuç konteyner ölçümü diye gösterilmez. Süreç için 256 MiB adres
alanı sınırı uygulandı. **Tam Telegram süreci ve optional ML inference 256 MB
altında doğrulanmadı.** Bunlar üretim öncesi açık kontrollerdir. Araştırma
bağımlılıkları production requirements'a eklenmedi, ağır eğitim offline kaldı.

## Doğrulama ve yeniden üretim

411 yerel regresyon kontrolü geçti; optional ML paketleri kurulu ortamda iki
backend gerçekten fit/predict edildi. Sentetik testler model doğruluğu için
performans örneği sayılmadı. CI çalışma durumu PR'da ayrıca belirtilir.

```sh
python -m pip install -r requirements.txt -r requirements-hybrid-research.txt
# Pinned, yerel arşiv/box dosyalarına işaret eden HYBRID_DATASET_MANIFEST_V1:
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m hybrid_engine \
  /absolute/path/enriched-manifest.json --output-directory /absolute/path/reports
# Yalnızca açık varsayımlı retrospektif araştırma:
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m hybrid_engine \
  /absolute/path/enriched-manifest.json --output-directory /absolute/path/reports \
  --assume-historical-availability
python -m unittest discover -s tests -v
```

Kaynak dosyalarındaki SHA pin'leri kontrol edilir; değiştirilmiş arşiv veya
`/data` path'i reddedilir. CLI otomatik download/deploy yapmaz; JSON'u yeni,
content-addressed dosyaya atomik yazar. Tam yerel raporda hedef başına input
digest, tahmin/gerçek, role, çizgiler, training artifact ve cutoff vardır.
Git'teki kanıt özeti ham oyuncu/source payload'larını içermez; tam raporların
dosya SHA'ları ve bütün aggregate metrikler korunur.

Kabul kapısı şu an BLOCKED: strict PIT örneği yok; validation ile seçilen aday
en az 50 test maçında önceden tanımlı %2 takım MAE iyileşmesini güven aralığıyla
kanıtlayamadı; veri erişim izin durumu doğrulanmadı. Ayrıca gelecekte etiketli
possession/maç öncesi rotation verisi, daha geniş NBA ve EuroLeague dış örnekleri,
zamansal bağımlılığa dayanıklı değerlendirme ve tam süreç RAM ölçümü gerekir.
Mevcut test dönemine tekrar tekrar model ayarlayıp bağımsız test denmeyecek.
Bu araştırma hiçbir durumda otomatik üretim modeli değişikliği yapmaz.
