# FAZ 92 — kanıta bağlı tahmin sağlığı ve araştırma adayları

PR [#89](https://github.com/Girayzeynal/zeynal-bot-core/pull/89), başlangıç
`43971086a8993321599542b09eda62ef045f937d`. GitHub HEAD ve yerel dal eşleşti.
Çalışma aynı `feature/hybrid-market-roster-evidence-20261114` dalındadır;
PR'ın hedefi `feature/hybrid-telegram-optin-20261114` olarak korunmuştur.
Main birleştirmesi veya Fly.io işlemi yapılmadı.

## Eklenen işlevler

- İzole NBA `/analyze` özetine **tahmin sağlık kartı** eklendi. Kart orijinal
  skorları, örnekleri, aralıkları veya zamanları değiştirmez. Maç kaynağının
  tahmin üretilirkenki yaşını, aynı fit SHA için o anda bilinen sonuç sayısını,
  geçmiş MAE varsa onu, eksikleri ve periyot belirsizliği sınırlamasını gösterir.
  Kaynak/kimlik/zaman bütünlüğü, güncellik veya önceki drift kontrolü başarısızsa
  analiz yayını durur. Önceden yazılmış kayıt silinmez. Kaynak kesintisinde
  bugünün verisi eski tahmine eklenmez.
- **`/health NBA`**, aynı izole SQLite arşivini salt okunur inceler. Lig, sezon,
  model sürümü ve tam fit SHA ayrı tutulur. İlk arşivlenmiş tahmin esas alınır;
  sonraki revizyon veya aynı kaydın tekrar gösterilmesi örnek sayısını artırmaz.
  Yanıtlar UTF-16 sınırında bölünür; en çok 10 kohort gösterilir. Tam rapor
  aşağıdaki CLI ile alınır. Yanlış sohbet, eksik arşiv, hatalı parametre, bozuk
  kaynak ve zaman aşımı senaryoları test edilmiştir.
- **Zaman kontrollü kalite izleme:** sonuç tahmin anından sonra öğrenildiyse
  geçmiş sağlık kartına katılmaz. Maç başladıktan sonra arşivlenmiş veya üretim
  saati kanıtlanamayan kayıt kalite hesabına alınmaz. Aynı anda çelişen ilk
  kayıtlar sessizce seçilmez. Bekleyen maçlar başarı sayılmaz.
- Drift incelemesi için en az **100 önceki + 100 sonraki olasılıklı maç** ve her
  pencerede **8 TSİ günü** gerekir. Önceki pencerenin bütün sonuçları, sonraki
  pencerenin ilk tahmininden önce bilinmelidir. Brier değişimi >0,05 yalnızca
  **inceleme uyarısıdır**; istatistiksel değişim kanıtı, yeniden eğitim emri veya
  kalibre güven değildir. Az veri varsa “stabil” yazılmaz.
- **Native kalibrasyon inceleme adaptörü**, gerçek kaynak/model denetiminden
  geçmiş, ilk arşiv zamanı ve kesinleşmiş resmî sonucu bulunan kayıtları mevcut
  mühürlü `calibration_guard` akışına bağlar. Fit eğitim kimlikleri gerçek
  hazırlanmış dosyadan okunur; hedef etiketini içeren model reddedilir. Plan
  şimdi kaydedilmişse eski maçlar yeni ileriye dönük OOS kanıtı sayılmaz.
  Kalibrasyon yalnızca isteğe bağlı çevrimdışı gölge incelemedir; hiçbir profile
  canlı otomatik uygulanmaz. Normal süre üç sınıfı HOME / TIE / AWAY'dir.
- **Possession/periyot araştırma kapısı** mevcut `PossessionModel` ve
  `quarter_shadow` bileşenlerini kullanır; motorlar yeniden yazılmadı. Yalnızca
  zamanında erişilebilir, kaynak hash'i olan, doğru maça bağlanmış normal süre
  box-score girdileri kabul edilir. `FGA + 0,44 FTA − ORB + TOV` tahmininden
  hücum/savunma verimliliği ve tempo özetleri hesaplanır. Bunlar ölçülmüş PBP
  temposu diye adlandırılmaz. Saklanan possession hesabı, sayı/periyot toplamı,
  takım eşleşmesi, OT ve veri sızıntısı kontrolleri vardır. Analitik modelin
  gerçek örnekleri yoksa QMC/MC bantları uydurulmaz. MC tekrar üretilebilirliği
  10.000 örnek üzerinde test edilir. Bu adaylar botta varsayılan yapılmadı.

Olay olasılığı, nominal aralık kitlesi, gözlenen kapsama ve model güven endeksi
ayrı tutulur. **NOT_CALIBRATED korunur; güven endeksi hesaplanmadı.** Kartın
`LIMITED_RESEARCH` durumu yüksek güven, kalibrasyon veya üretime hazır demek
değildir.

## Yedi önceliğin gerçek durumu

| Katman | Yapılan / mevcut | Kalan kanıt |
|---|---|---|
| Gerçek arşiv ve Telegram | `/predictions` düzeltmesi korundu; sağlık komutu gerçek PTB dispatch ile yerel HTTP üzerinde test edildi | UserLAnd'daki asıl 10 kayıt ve bu HEAD'in gerçek Telegram teslimi BLOCKED |
| Kronolojik kalibrasyon | Native arşiv → mühürlü koruma adaptörü, gerçek saatli ileri plan, fit SHA ayrımı | Yeterli bağımsız sonuç yok; kalibrasyon uygulanmadı |
| Periyot belirsizliği | Var olan gölge aday ve toplam koruma yaklaşımı korundu; sağlık kartı yüksek korelasyonu gösteriyor | Yeni bağımsız ileri doğrulama gerekli; NBA'de üstünlük yok |
| Possession / verimlilik | Geçerli box-score kapısı ve mevcut MC/analitik aday bağlantısı eklendi | Korunan Cloud tahmininde iki takım için de uygun box sayısı 0; ABSTAIN |
| Kadro / sakatlık | Önceki resmî PDF yakalama, SHA ve bağımsız eşleştirme kontrolleri korundu | Doğrulanmış maç öncesi dakika, rotasyon, oyuncu etki katsayıları ve sürekli kaynak bağlantısı eksik |
| Piyasa kapsamı | Önceki quote/rule/OT/push kontrolleri korundu; bilinmeyen kapsamda edge seçilmez | Tam kapsamı ve zamanı doğrulanmış piyasa + yeterli OOS kalibrasyonu eksik |
| Kalite / drift | Yeni salt okunur izleme ve yayın durdurma nedeni görünür | İstatistiksel drift/üstünlük için yeterli ileri örnek henüz yok |

Bu tablo yedi katmanın tamamı için doğruluk iyileşmesi kanıtlandığı anlamına
gelmez. Doğrulanamayan canlı veri, ücretli abonelik veya sahte kayıt eklenmedi.

## Arşiv ve performans kanıtı

Cloud taramasında dört ayrı araştırma veritabanı bulundu: **1, 1, 4 ve 4**
snapshot. Bunlar eski/optimize varyantları da kapsar; toplanıp kullanıcının
**10 bağımsız kayıtlık UserLAnd arşivi** gibi sunulmadı. Kullanıcı asıl arşivin
UserLAnd'da bulunduğunu bildirdi; bu dosya Cloud'da erişilebilir değil.

Cloud Philadelphia–Indiana kaydı: **112,5–109,3; toplam 221,8** korundu.
SHA `30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343`.
Yerel kayıt saati **14.14.05 TSİ**; kullanıcının bildirdiği yaklaşık **15.12 TSİ**
saatiyle aynı kayıt olduğu iddia edilmez. Salt okunur tam kaynak denetimi:
SQLite **ok**, dosya hash'i önce/sonra aynı, ilk tahminin içerik SHA'sı aynı.
Maç kaynağı üretim anında 0 saniye yaşında; o model için tahmin anında
doğrulanmış önceki sonuç **0**. Sonuç: **LIMITED_RESEARCH / NOT_CALIBRATED**.

Başlangıçtaki **51 arşiv/kanıt dosyası**, altı sabitlenmiş veri/model kaynağı,
Faz13 ve `main.py` değişmedi. Eski hazırlanmış `8029ba…` artefaktının daha önce
belgelenen kaynak pini uyumsuzluğu devam eder; yeni kod bunu yüklenebilir diye
göstermez. Aktif optimize `ae4e57…` artefaktı yükleme kontrolünden geçmektedir.

Değişmeyen OOS hesaplarını gereksiz yere yeniden çalıştırmadım. Kaynaklar:
`hybrid-phase845-walk-forward-20261113.json.gz` ve
`hybrid-phase845-quarter-shadow-20261113.json.gz`.

| Lig | Katı tarihsel OOS | Gölge periyot %90 interval score: eski → aday |
|---|---:|---:|
| EuroLeague | 77 maç / 24 gün | 48,31 → 32,44; keşifsel fark GA −20,91…−10,88 |
| NBA | 7 maç / 2 gün | 32,50 → 33,43; kötüleşti, yeterli gün yok |
| EuroCup | 0 | Hesaplanamaz |

Bu periyot karşılaştırması yeniden kullanılan tarihsel test kümesindedir;
bağımsız doğrulama veya Faz13'e karşı genel skor üstünlüğü değildir. Önceki
Faz13 karşılaştırmasının kabulü değişmedi: güvenilir genel üstünlük kanıtlanmadı.
Ham bantlara nominal %50 / %90 yazılması, gerçek kapsamanın bu olduğu anlamına
gelmez. Yeni kalibrasyon planı geçmiş maçları yeniden sınıflandırmaz.

## Testler ve kaynak kullanımı

- Son tam yerel tur: **886 geçti / 0 başarısız**. Ardından eklenen iki kontrol ve
  son kod değişiklikleri için **76 hedefli test geçti / 0 başarısız**.
- Son ağacın keşfedilen toplamı **888 test**; kesin HEAD'in tam sayısı ve CI
  sonucu PR kontrollerinde ayrıca doğrulanır. Önceki 831 test korundu.
- Gerçek PTB + yerel Bot API HTTP double, native NBA kaynak gövdesi replay'i:
  **14 komut / 14 yanıt**, dört değişmez test snapshot'ı. `/start`, `/nba`,
  `/predictions NBA`, `/health NBA`, `/accuracy NBA`, `/compare` ve analiz/replay
  akışları dahil; yanlış tarih kontrolü ve SQLite bütünlüğü geçti.
- Yerel ölçüm **100,34 MiB peak RSS**, tek CPU affinity ve **256 MiB adres alanı
  limiti** altında. Host cgroup 256 MiB değildir; bunu gerçek container sınırı
  gibi raporlamıyorum. Son HEAD Docker CI gerçek `--memory=256m --cpus=1`
  kontrolü ayrıca PR'da doğrulanır.
- Bu ölçüm gerçek Telegram ağı veya Android teslim gecikmesi değildir.

Somut JSON: [hybrid-phase92-evidence-20261115.json](hybrid-phase92-evidence-20261115.json).
Dosya CI öncesinde hazırlandı; final CI kanıtı PR gövdesi/kontrollerinde verilir.

## UserLAnd'da kalan son salt okunur doğrulama

Koddan doğrulanan yol: test botunun mevcut `--data-directory` kökünün altında
`live-nba/nba-hybrid.sqlite` ve `live-nba/assets`. Cloud kökünü UserLAnd'ın kökü
gibi kullanma. Aşağıdaki değişken mevcut izole test botunun **gerçek** veri
dizinine işaret etmelidir; boşsa komut durur. Kaynak dosya yoksa yaratılmaz.

```bash
test -f "${ISOLATED_TEST_DATA:?Mevcut test botunun veri dizini gerekli}/live-nba/nba-hybrid.sqlite" &&
python3 -m hybrid_engine.quality_report \
  --ledger "$ISOLATED_TEST_DATA/live-nba/nba-hybrid.sqlite" \
  --assets-directory "$ISOLATED_TEST_DATA/live-nba/assets" \
  --calibration-plan-directory "$ISOLATED_TEST_DATA/quality-phase92/calibration-plan" \
  --output-directory "$ISOLATED_TEST_DATA/quality-phase92/reports"
```

Bu işlem tahmin üretmez, sonuç indirmez, tablo açmaz/sıfırlamaz; yalnızca
content-addressed denetim raporu ve yerel ileri inceleme planı ekler. Plan eski
maçlara geri tarihlenmez. Dosya hash'inin değişmemesi eşzamanlı WAL append'inin
olmadığını tek başına kanıtlamaz; rapor bu sınırlamayı belirtir.

Mevcut izole test botu aynı veri/model/SHA seçenekleriyle güncellendikten sonra
yetkili insan sohbetinden `/start`, `/nba`, `/predictions NBA`, `/health NBA`,
`/accuracy NBA`, `/compare NBA <arşivdeki ESPN kimliği>` çalıştırılmalı. İkinci
bir polling süreci başlatılmamalı. Token/API anahtarı istenmedi; üretim botuna
erişilmedi. Gerçek teslim makbuzu ve gerçek 10 kayıt denetimi **UserLAnd'a
bırakıldı**, taklit edilmedi.

## Üretim kararı

**NO-GO**: gerçek 10 kayıt denetimi ve bu HEAD'in gerçek Telegram E2E testi
bekliyor; genel model üstünlüğü, kalibrasyon ve kadro/piyasa/possession girdileri
henüz yeterli değil. Faz13 varsayılan kalır. Sağlık/raporlama geliştirmesi
araştırma dalındadır; Fly.io, diskler, snapshot'lar ve secret'lar değiştirilmedi.
