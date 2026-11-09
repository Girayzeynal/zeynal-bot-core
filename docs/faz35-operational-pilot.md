# FAZ35 — operasyonel pilot ve yerel kurtarma yapılandırması

Taban: `ed312b36012aa5c519c1b5afdf7796224c8f57e0`, geliştirme dalı
`feature/nba-command-20261104`, PR #12. Taban commit, PR başı ve push/PR
unit-tests/docker-build başarıları GitHub'dan doğrulandı. PR taslak ve açık;
merge/dağıtım yapılmadı. FAZ13, FAZ28, Monte Carlo ve FAZ31 model kaynaklarının
hash'leri korundu; model katsayıları veya geçmiş tahminler değiştirilmedi.

## Gerçek plan

5 Kasım 2026 UTC güncel ESPN takviminde 18 yaklaşan NBA normal sezon maçı,
54 kesit durumu doğrulandı: 52 NOT_DUE, 2 MISSED_CUT, 0 DUE. Yeni gerçek
prospektif tahmin ve uygun canlı eğitim örneği sayısı **0**. Henüz özgün bir
yeni tahmin SHA'sı yoktur; plan zamanları tahmin oluşturulma zamanı değildir.

| ESPN ID | Maç başlangıcı UTC | T24H UTC | T6H UTC | T60M UTC |
|---|---|---|---|---|
| 401909936 | 6 Kasım 02:00 | 5 Kasım 02:00 — kaçırılmış | **5 Kasım 20:00** — bekliyor | 6 Kasım 01:00 — bekliyor |
| 401909937 | 6 Kasım 03:00 | 5 Kasım 03:00 — kaçırılmış | 5 Kasım 21:00 — bekliyor | 6 Kasım 02:00 — bekliyor |

İlk sonraki kesit: **5 Kasım 20:00 UTC / 23:00 Türkiye**. Bu bilgi sorgu
anındaki takvime bağlıdır; her çalıştırmada dinamik olarak tekrar kontrol edilir.
Erken tahmin veya geçmişe dönük kesit doldurma yapılmadı. Gerçek kayıt
oluşmadığından yeni MAE/RMSE/olasılık kalibrasyonu sonucu üretilmedi.

## Pilot çalıştırma

`faz35 pilot CONFIG` FAZ34'ün salt planlama turunu kullanır. DUE kesit yoksa
WAITING_FOR_CUT döner ve gerçek toplama turunu başlatmaz. DUE varsa mevcut
FAZ34 run-once mekanizmasını çağırır; bu mekanizma kilit altında takvimi tekrar
sorgular. Planlama ile toplama arasında pencere geçerse eski plan kullanılarak
kayıt yapılamaz. Özgün tahmin verisinin oluşturulma/kaydedilme zamanları aynen
korunur; UTC maç başlangıcı, kaynak gözlem/ingestion zamanı, model SHA,
özellik kapsamı ve kayıt SHA kanıtı FAZ33/34 paketinden raporlanır.

FAZ13/FAZ28 referansı ve FAZ31 durumu aynı transaction'da kalır. Model yoksa
NO_MODEL_AVAILABLE; gölge skor/olasılık uydurulmaz. Sentetik kayıtlar ayrı
modda tutulur; pilot çıktısının gerçek tahmin SHA listesine eklenmez.

Planlama sırasında HTTP 403/429, timeout veya ağ hatası alınırsa bekleme zamanı
operasyon tablosuna yazılır. Yeni süreç önce bu zamanı kontrol eder; engellenen
sağlayıcı hemen tekrar sorgulanmaz. Veri kesiti oluşmamış olması ağ başarısı
sayılmaz. Dosya kilidi ve SQLite kilidi ayrı, açık durumlar olarak raporlanır.

Önceki STARTED olayı yarım kalmışsa, bekleme döneminde bile dosya kilidi altında
INTERRUPTED olarak işaretlenebilir. Bu işlem tahmin üretmez veya değiştirmez.
DUE kesitlerde FAZ34'ün atomik insert, immutable kayıt, kesinti/rollback,
idempotency ve doğrulanmış checkpoint mekanizması tekrar kullanılır.

```sh
# Yapılandırma çalışma alanında, açık mutlak yerel yollarla hazırlanır.
python -m faz35 pilot /ABSOLUTE/PATH/pilot-config.json
```

Şablon: [config/faz35-local.example.json](../config/faz35-local.example.json).
Gerçek kaynak commit'i ve geliştirme dalı temiz olmalıdır. Pilot ve ilgili
kod dosyalarının Git'teki byte içeriği ile çalışma ağacı karşılaştırılır.
Komut sürekli servis kurmaz ve kesit saatine kadar bekleyen görev bırakmaz.

## Kalıcılık: mevcut sınır ve güvenli hazırlık

**Yetkilendirilmiş harici hedef yoktur; kalıcı depolama sorunu çözülmüş
sayılmaz.** Aktif yapılandırma LOCAL_ONLY, external_target=null,
upload_enabled=false durumundadır. Bu sürümde dışarı veri taşıma kodu yoktur;
hedef/yükleme açan yapılandırmalar reddedilir. Kullanılmayan kimlik veya
API anahtarı kurulmaz, gizli anahtar değiştirilmez.

Ücretsiz seçeneklerin FAZ34'te doğrulanan karşılaştırması geçerlidir:

| Seçenek | Güçlü tarafı | Kalan koşul/sınır |
|---|---|---|
| Kullanıcının mevcut disk/NAS'ına kapsülü indirmesi | Yeni servis/anahtar gerekmez; checksum ile kontrol edilebilir | Kullanıcı gerçekten oturum dışında saklamalı; ikinci kopya tercih edilir |
| Mevcut GitHub Actions artifact | Mevcut public depo ve standart Actions çerçevesi | Saklama süresi dolabilir; tek kalıcı kopya sayılmaz; kota/politika doğrulanmalı |
| GitHub Release asset | Sürümlenebilir, açık süre dolumu olmadan saklama adayı | Dosya 2 GiB altında; public depoda veriyi yayımlar; açık hedef/yayın yetkisi gerekli |

Kaynaklar:
https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts
ve https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases.
Bu fazda artifact/release/başka dış hedefe SQLite paketi yüklenmedi. Harici
hedef seçilirse sağlayıcı, tam hedef, erişim/görünürlük, ücretsiz kota sınırı,
saklama/silme politikası ve açık kullanıcı yetkisi ayrı doğrulanmalıdır.
Bir JSON alanına hedef yazılması tek başına yükleme yetkisi değildir.

## Taşınabilir kapsül ve yeni konumda kurtarma

```sh
python -m faz35 capsule /ABSOLUTE/PATH/pilot-config.json /NEW/LOCAL/recovery.tar.gz
python -m faz35 restore-pilot /PATH/recovery.tar.gz /NEW/EMPTY/PILOT --sha256 EXPECTED_SHA256
python -m faz35 pilot /NEW/EMPTY/PILOT/pilot-config.json
```

Kapsül mevcut FAZ34 yedekleme altyapısını kullanır: ortak kaynak kilidi,
süre sınırlı SQLite online backup, SHA-256 manifesti, bütünlük ve anlamsal
doğrulama, 0600 dosyalar ve üzerine yazmama. Yönetilen tahmin/geçmiş/operasyon
veritabanlarına isteğe bağlı `legacy-*.sqlite` haritasındaki eski defterler
salt okunur eklenir. Yapılandırma içine kimlik bilgisi konulmaz.

Kurtarmada beklenen hash paket dışında saklanmış değerle karşılaştırılır.
Eksik/uygunsuz kapsül reddedilir. Veri yalnızca yeni dizine geri yüklenir;
eski dosyalar değiştirilmez. `pilot-config.json` yeni mutlak yollarla yeniden
oluşturulur; eski Cloud çalışma alanının yolları taşınmış gibi kullanılmaz.
Yeni yapılandırma yine LOCAL_ONLY olur. Defterin SYNTHETIC_TEST/PROSPECTIVE
modu korunur; sentetik veri canlı moda dönüştürülemez.

Yeni Cloud ortamında: bu commit'in geliştirme checkout'u ve requirements.txt
bağımlılıkları hazırlanmalı, kapsül ile dışarıda saklanmış hash erişilebilir
olmalı, restore-pilot ve doğrulama çalıştırılmalıdır. Aynı makinede yeni dizine
restore yapmak, gerçek yeni Codex Cloud oturumları arası deney değildir.
Bu deney **DOĞRULANMADI**; oturum dışında bir kopya henüz yapılandırılmadı.

## Doğrulama ve açık riskler

**699 test başarılı**, 38.585 saniye; **12 yeni FAZ35 testi**. Kesit erken/
kaçırılmışken kayıt reddi, DUE kesitte atomik referans/NO_MODEL_AVAILABLE,
tekrar çalıştırma, beklerken yarım günlük toparlama, çift süreç, SQLite kilidi,
403/429/timeout/ağ hatası ve süreçler arasında bekleme süresi, yetkisiz hedef
reddi, kapsül bütünlüğü, yeni yollar ve sentetik mod korunması test edildi.
Pozitif tahmin örnekleri sentetiktir; gerçek performans iddiası yoktur.

Yedi eski korunan dosyanın hash'leri ve dört model kaynak dosyasının hash'leri
saklandı. Eski kanıt dosyaları değiştirilmedi. Compileall ve diff kontrolleri
başarılı; son commit'in CI sonuçları GitHub'dan ayrıca doğrulanır. Nihai temiz
commit'te gerçek pilot ve kapsül sonuçları çalışma çıktısında ayrıca raporlanır.

Açık durumlar: henüz yeni gerçek tahmin yok; kesit saatinde pilot çağrılmalı;
ücretsiz/yetkili harici hedef ve yeni Cloud restore deneyi yok; sakatlık,
kadro, piyasa ve toparlanma verileri doğrulanmış değil; tempo kutu skoru
tahmini, FAZ31 eğitilmemiş ve olasılık kalibrasyonu kurulmamış. FAZ13/FAZ28
modeli değiştirilmedi. Merge, Fly.io veya Telegram üretim değişikliği yapılmadı.
