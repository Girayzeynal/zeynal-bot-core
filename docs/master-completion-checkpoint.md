# Master completion — geliştirme checkpoint'i

Başlangıç: PR #21 `6603d0e2616138aecfd7a9bdab23e73b5089252d`. PR #12/#15/#16/#18/#19 açık taslak; Issue #17/#20 açık. GitHub son SHA CI sonuçları bağımsız okundu; PR #21 push 42225955854 ve PR 42225962760 için unit-tests/docker-build başarılı. Başlangıç 888 test. FAZ13–FAZ42 mevcut kayıtları, modelleri ve kaynak kanıtları korunur. Bu rapor bütün master hedeflerinin tamamlandığı iddiası değildir.

## Bağımlılık sırası

1. Kaynak/izin/kimlik ve tarihsel katalog kapsamı.
2. Periyot, oyuncu, PBP ve yalnızca açıkça doğrulanan oyuncu değişimlerinden rotasyon kanıtı.
3. PIT güvenli özellik/kesit, mevcut 10.000+ Monte Carlo ve ayrı kronolojik değerlendirme.
4. Günlük geliştirme dry-run, immutable tahmin/sonuç bağlantısı; gerçek saklama ve scheduler için Issue #20 onayı.
5. Telegram /analyze geliştirme bağlantısı; polling/webhook/production başlatılmaz.

Her aşama ayrı commit, tam regresyon ve exact SHA push/PR CI ile doğrulanır. Eksik kaynak/izin, kronoloji veya model ABSTAIN üretir. Yeni kaynak politikası kendi kendine PERMITTED yapılmaz. Sentetik başarı gerçek tahmin doğruluğu değildir.

## Aşama 1 — resmî katalog kapsamı

`faz43_catalog.py`, mevcut resmî EuroLeague/EuroCup audit_catalog ayrıştırıcısını kullanır. Her lig için competition, season ve games yanıtlarının gerçek URL/gözlem/ingestion/digest makbuzlarını bağlar. Katalogdan çıkarılan bir satır ayrıca per-game URL sorgulanmış gibi gösterilmez. Geçmiş materialization'ın ingestion'dan eski olmasını engelleyen regresyon önce başarısız oldu, sonra düzeltildi.

6 Kasım 2026 canlı, salt okunur altı GET kontrolü:

| Kaynak | Tamamlanmış periyotlu katalog maçı | Gelecek fixture | Geçersiz satır | Bu toplamada per-game/oyuncu/PBP sorgusu | Modele uygun |
|---|---:|---:|---:|---:|---:|
| EuroLeague 2026/27 | 96 | 284 | 0 | 0 | 0 |
| EuroCup 2026/27 | 96 | 128 | 0 | 0 | 0 |

Önceki salt okunur NBA araştırma arşivi 75 maçtır; bu aşamada NBA kapsamı yeniden taranmadı. Katalog kayıtları eski iki ayrıntılı EL/EC maçına eklenerek 98 diye sayılmaz: örtüşen kimlikler tek maçtır. Oyuncu dakika kanıtı önceki çalışmada her ligde bir maç içindir (19 NBA / 24 EL / 21 EC dakika alanı). Katalog bunu oyuncu/PBP kapsamına dönüştürmez.

Kullanım izinleri UNKNOWN, bağımsız source/time attestation yok, yeni gerçek prospektif tahmin 0, gerçek performans metrikleri null. Katalog istatistikleri tarihsel araştırma envanteridir. TBL/CBA/JAPAN/LEGA için doğrulanmış sağlayıcı adaptörü henüz yoktur; sayılar uydurulmaz.

Yerel tam regresyon 896/896; 8 yeni katalog testi. Canlı kaynak kontrolü sentetik/deterministik regresyondan ayrıdır. Kanıt: docs/evidence/master-catalog-20261106.json. Bu aşamanın commit'i için CI push sonrası ayrıca doğrulanır.

## Güvenlik ve açık blokajlar

Main merge, Fly.io/Telegram production, secret değişikliği, ücretli servis veya geri dönüşü zor işlem yapılmaz. Gerçek kalıcı storage/scheduler etkinleştirilmez. Eğitim/kalibrasyon için izinli ve kesit öncesinde gerçekten erişilebilir yeterli örnek gereklidir; mevcut küçük araştırma verisiyle katsayı optimize edilmez. Yeni Cloud ortamında kalıcılık ve bağımsız kurtarma doğrulanmadı.

## Aşama 2 — PBP ve açık oyuncu değişim rolleri

`faz43_pbp.py`, ESPN summary kaynağından dört dönem/uzatma, dönem başlangıç-son skorları, son skor, maç saati, takım ve varsa UTC event wallclock alanlarını yeniden denetler. Aynı olay tekrar sayılmaz; çelişkili id, tekrarlı sequence, geriye giden maç saati ve açıklanamayan skor düzeltmesi reddedilir. ESPN sequenceNumber geç eklenen kayıtlar yüzünden zaman sırası değildir: kaynak dizisi korunur ve dönem/maç saati/skorla doğrulanır; sequence'a göre yeniden sıralanmaz. Bunu gerektiren regresyon önce başarısız oldu, sonra düzeltildi.

497 olay içeren eski gerçek ESPN 401909922 dosyası yeni canlı fetch gibi gösterilmedi. İncelemede 10 sequence ters dönüşü, iki skor anomalisi bulundu (Q3 2:48: deplasman 81→79; Q4 10:56: iki takım skoru aynı olayda değişiyor). **ABSTAIN_SCORE_CORRECTION_OR_MISSING_SCORING_EVENT**: bu kayıt modele uygun PBP değildir. 79 substitution satırında incoming/outgoing rolleri bağımsız doğrulanmadı; metinden veya participant sırasından ilk beş/rotasyon uydurulmadı. NBA CDN yeniden kontrolü HTTP 403: gerçek NBA.com/ESPN çapraz teyidi hâlâ yok.

Açık, kaynakla doğrulanmış player_in/player_out rolleri verildiğinde saf rotasyon aritmetiği beş oyuncuyu, eşzamanlı değişim batch'ini ve toplam oyuncu süresini korur. Pozitif doğrulama yalnızca sentetik normalize olaylarla yapıldı; canlı rotasyon adaptörü veya nedensel beşli gücü modeli değildir. Garbage-time alanı Q4/son 180 saniye/20 sayı farkı için açık, betimsel kuraldır; eğitilmiş model veya katsayı düzeltmesi değildir. Comeback göstergesi de geçmiş sonuç betimlemesidir, kalibre edilmiş olasılık değildir.

NBA ve Disney kullanım koşulları referans sayfaları HTTP 200; EuroLeague koşul sayfası adayı HTTP 403 döndürdü. Sayfanın okunabilmesi kullanım hakkı tanınması değildir. Hiçbir izin UNKNOWN'dan PERMITTED'a çevrilmedi; izinli haber feed'i yapılandırılmadı ve haber içeriği toplanmadı. Kaynak URL/zaman/yanıt hash'leri kanıt raporunda, ham sayfa/PBP gövdeleri Git'e yüklenmedi.

Yerel tam regresyon **910/910**; bu aşamada **14 yeni PBP/rotasyon testi**. Katalog aşaması `def2b23af9a13c8151fd868088d24d17d001b87a` için push 42227618369 ve PR 42227670008 unit-tests/docker-build başarılı. Gerçek uygun PBP/rotasyon maçı 0, yeni prospektif tahmin 0, eğitim/kalibrasyon yapılmadı. Kanıt: docs/evidence/master-pbp-20261106.json.

## Aşama 3 — geliştirme /analyze, günlük plan ve son gönderim kapısı

`faz43_development.py` üretim main başlangıcını import etmez, secret okumaz, uygulama/polling/webhook başlatmaz. `register_development_analyze` yalnızca durdurulmuş DEVELOPMENT uygulaması, açık chat allowlist ve mevcut /analyze handler'ı yoksa kayıt yapar. Veri/model beklemesinden sonra scope/chat yeniden kontrol edilir. Snapshot oluşturulduktan sonra kaynak izni sona ererse, cutoff eskirse veya maç başlarsa çıktı gönderilmez. Bu iki son gönderim açığı önce iki başarısız regresyonla yeniden üretildi, sonra kapatıldı.

Takımlar sadece kaynak takım kimliği veya tam alias eşleşmesiyle çözülür; fuzzy eşleşme, belirsiz aynı gün fikstürü, geçmiş tarihe güncel veri veya cross-league kaynak reddedilir. Tarih Europe/Istanbul günü olarak doğrulanır. Yeterli/izinli kaynakta FAZ42 snapshot'ı yeniden kullanılır; 1Q–4Q, 1H/2H, takım toplamları, total, margin, üç normal süre olasılığı, 10.000 Monte Carlo/tohum/model/source SHA gösterilir. Sentetik kullanım açık etiketlidir ve varsayılan kapalıdır. Aynı fixture'ın pozitif snapshot'ı bellek içi cache'de değiştirilmez; cache gerçek kalıcı prospektif kayıt sayılmaz.

FrozenInputsBackend yalnızca dışarıdan trusted pin'i verilen salt okunur geliştirme bundle'ını kabul eder; bundle kaynak kullanım izni vermez ve başka tarih verisine fallback yapmaz. Manuel prepare_day üç destekli ligde fixture'ı tekilleştirir; scheduler kurmaz veya gerçek ledger açmaz. Pozitif uçtan uca testler sentetiktir. Gerçek geliştirme backend'i henüz izinli kaynakla yapılandırılmadı.

Legacy /analyze'da Faz13CoreOutput ismi kullanılıp import edilmediği için gerçek çıktı tipiyle NameError oluştuğu yeni testle yeniden üretildi. main.py'ye yalnızca eksik tip importu eklendi; FAZ13/22/23 katsayıları, eski kayıtlar ve production çalışma ortamı değiştirilmedi.

Yerel tam regresyon **936/936**, bu aşamada **26 yeni test**; geliştirme/legacy odaklı grupta 33/33. Eski PBP checkpoint `b44708724a2a2e5646ddacdf883f200a10c40085` için push 42229035414 ve PR 42229043590 unit-tests/docker-build başarılı. Gerçek komut satırı smoke sonucu: DEVELOPMENT_SOURCE_NOT_CONFIGURED / DEVELOPMENT_DAY_SOURCE_UNAVAILABLE; kalıcı tahmin, Telegram mesajı ve scheduler 0. Kaynak izinleri/gerçek backend yokken skor uydurulmadı.

```sh
python -m faz43_development --request '/analyze NBA 2026-11-07 Detroit Pistons vs Philadelphia 76ers'
python -m faz43_development --day 2026-11-06
# İzinli hazırlanmış geliştirme bundle'ı varsa:
python -m faz43_development --request '/analyze NBA YYYY-MM-DD HOME vs AWAY' \
  --inputs /path/to/bundle.json --trusted-bundle-sha256 TRUSTED_SHA256
```

Bu komutlar Telegram botunu çalıştırmaz. Üretimde legacy /analyze yerine yeni akış etkinleştirilmedi; bu adım ayrıca review/onay/deploy gerektirir. Kanıt: docs/evidence/master-development-20261106.json.

## Aşama 4 — sınırlı NBA arşiv yenilemesi ve eski gerçek kayıtların yeniden denetimi

`faz43_nba_refresh.py`, en fazla üç ABD takvim günü ve 12 eksik summary isteğiyle sınırlıdır; varsayılan ağ kapalıdır. Bu oturumdaki iki scoreboard + iki summary GET'i iki eksik tamamlanmış maç buldu: ESPN 401909936 ve 401909937. Summary/scoreboard kimlik, UTC başlangıcı, ev/deplasman, final skorları ve periyotlar uzlaştırıldı. Eski arşiv 75, yeni özgün maç 2, birleşik normalleştirilmiş periyot kapsamı **77**. Bu, bütün NBA sezonunun tamamlandığı iddiası değildir. Yeni iki maç için oyuncu satırı sayısı 28/25, dakika alanı sayısı 27/25; dakika alanı bulunması oyuncunun kesin oynadığı veya resmi kadro üyeliğinin bağımsız doğrulandığı anlamına gelmez.

Eski SQLite'a yazılmadı; SHA `43adc6de12bc065e38b666dad8ba2cd9a48c5786c1185b396de5a37ebe4dd002` aynı. Yeni kayıtlar ayrı, bugünün observed/ingested/materialized zamanlarıyla RETROSPECTIVE_RESEARCH kanıtıdır. Ham makale/odds/PBP gövdeleri yayımlanmaz; minimal kaynak skor/periyot projeksiyonu, yanıt digest'i ve kaynak URL'si tutulur. İzinler UNKNOWN, yeni modele uygun örnek/prospektif kayıt 0. Kimlik alias'ları, aynı takım/başlangıç, değiştirilmiş kaynak/forecast etiketleri ve çelişkili dönemler reddedilir. Aynı final/çeyrek skoruna rağmen farklı uzatma sayısını kabul eden açık önce regresyonla yeniden üretildi, sonra kapatıldı.

FAZ29'un iki özgün yerel veritabanı ayrıca mevcut read-only audit ile yeniden denetlendi: üç farklı maç (401909922/401909923/401909925), üç FAZ13 çıktı çifti ve bir FAZ28 Monte Carlo çıktı çifti. Aynı maçın iki modeli dört farklı maç diye sayılmadı. Dosya SHA'ları önce/sonra aynı; özgün tahmin veya simülasyon yeniden üretilmedi. Bu, yeni modelin kalibrasyonu veya bugünkü kaynak izinlerinin tarihsel onayı değildir; yerel orijinal kayıt/sonuç kanıt zinciri denetimidir, bağımsız NBA.com teyidi değildir.

| Eski model/sürüm | Kapsam | N | Takım skor MAE / RMSE | Toplam MAE | Fark MAE |
|---|---|---:|---:|---:|---:|
| FAZ13 / 9bd8ab49… | FINAL_WITH_OT | 2 | 6.0700 / 6.4699 | 2.9400 | 12.1400 |
| FAZ13 / 2bbe3c39… | FINAL_WITH_OT | 1 | 4.3300 / 5.0353 | 5.1400 | 8.6600 |
| FAZ28_NORMAL_V1/MC / 2bbe3c39… | REGULATION_ONLY | 1 | 4.2469 / 4.9738 | 5.1779 | 8.4937 |

Bu sayılar yalnızca küçük örneklem betimlemesidir; modeller/sürümler tek performans havuzuna karıştırılmaz, üstünlük veya güvenilir doğruluk oranı ilan edilmez. FAZ13 olasılık çıktısı yoktur; kalibrasyon NOT_ESTABLISHED. Yeni motorun izinli/PIT uygun değerlendirme sayısı hâlâ 0, MAE/RMSE/Brier/log-loss null'dır. Eski üç maçın varlığı yeni üretilmiş prospektif örnek anlamına gelmez.

Yerel tam regresyon **946/946**, bu aşamada **10 yeni test**. Önceki geliştirme checkpoint'i `7eb0f014b7d02b620c3ddf880837004f9b0626d8` push 42244346157 / PR 42244358970 CI başarılı. Yeni canlı ve eski read-only denetim kanıtları: docs/evidence/master-nba-refresh-20261106.json ve docs/evidence/master-legacy-audit-20261106.json.

## Devam planı ve dürüst tamamlanma sınırı

- Kaynakta doğrulanan periyot kapsamı: NBA 77 normalleştirilmiş araştırma maçı; EL 96 ve EC 96 resmî katalog maçı. Oyuncu/PBP kapsamı bunlarla aynı değildir. TBL/CBA/JAPAN/LEGA için doğrulanmış kaynak adaptörü ve sezon/takım dizini eksiktir.
- Yeni gerçek prospektif kayıt 0; yeniden denetlenen eski gerçek maç 3. Gerçek günlük scheduler/storage ve üretim Telegram bağlantısı kapalıdır. Yeni Cloud oturumunda gerçek harici kalıcılık/kurtarma doğrulanmadı.
- İzinli haber/yorum feed'i ve hukuki kullanım politikası kanıtı yok. NBA resmi CDN 403; bağımsız cross-provider sonuç teyidi eksik. PBP skor düzeltmelerinin kaynakta çözülmesi ve açık substitution rolleri/ilk beş/stint kanıtları gerekir.
- Mevcut FAZ13/FAZ28 katsayıları korunur. FAZ31 gerçek eğitim modeli bu geliştirme akışına bağlanmadı; yeterli izinli/PIT örnek ve bağımsız holdout olmadan eğitim veya kalibrasyon zorlanmaz.
- Sonraki güvenli teknik işlem: izin/kaynak manifesti doğrulandıktan sonra yeni tarihsel gözlemleri yalnızca ileri kesitlere bağlamak; izinli PBP/roster adaptörünü doğrulamak; geliştirme input bundle backend'ini yapılandırıp pozitif gerçek dry-run yapmak. Gerçek kayıt saklama/scheduler ve production ayrı onay gerektirir.

Master görev bütün kapsamıyla tamamlandı denmez. Bu checkpoint, geçen kod/test/CI aşamalarını ve gerçek erişim/veri/izin blokajlarını devralınabilir şekilde bırakır. Son commit SHA ve exact-head CI durumları taslak PR #22 üzerinde raporlanır.
