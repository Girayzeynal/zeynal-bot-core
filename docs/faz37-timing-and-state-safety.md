# FAZ37 — saat güvenliği ve güvenilir HEAD ile kurtarma

Başlangıç SHA: `b61b1ad3bbf12fab856e1939e06db81e58481fef`.
Dal: `feature/nba-command-20261104`, açık/taslak PR #12. Başlangıç commit,
PR başı ve push/PR unit-tests/docker-build başarıları bağımsız doğrulandı.
FAZ13/FAZ28 katsayıları, geçmiş FAZ24 kayıtları ve FAZ29–36 kanıtları korunur.

## Gerçek saat ve ESPN 401909936

Bağımsız clock.curr_time aracı ilk kontrolde **2026-11-05 11:03:12 UTC**,
aynı kontroldeki host saati de 11:03:12 UTC döndürdü. İkinci gerçek araç
örneklemi 11:18:06 UTC olarak kanıt dosyasına kaydedildi. Bu, gelecekteki host
NTP/UTC doğruluğunun garantisi değildir.

ESPN summary uç noktası HTTP 200 ile yeniden okundu. Ev PHX ID 21, deplasman
ORL ID 19, başlangıç **2026-11-06 02:00 UTC**. Durum SCHEDULED, sezon 2027/type2.
T6H planı **2026-11-05 20:00 UTC / 23:00 Türkiye** olarak doğrulandı.
Kesit penceresi planlanan andan sonraki en çok 300 saniyedir.

İnceleme anında kesit NOT_DUE. Yeni gerçek prospektif kayıt **0**, yeni tahmin
SHA'sı yok. Gerçek saat gelmeden tahmin oluşturulmadı. Erken, DUE, MISSED_CUT
ve ALREADY_RECORDED ayrımı korunur. Hedef karar, FAZ37_TARGET_CUT_STATUS
operasyon olayı olarak kaydedilebilir; bu olay tahmin veya eğitim örneği değildir.
Aynı karar tekrarlandığında gereksiz yeni operasyon olayı oluşturulmaz.

## Kod denetimi ve saat kayması koruması

FAZ36 mevcut yerel CAS, immutable kapsül ve envanter korumasını sağlıyordu;
iki eksik yerel bileşen eklendi:

- İşlem sırasında wall-clock ile monotonic farkının ve geri sıçramanın denetimi.
- Güvenilir son HEAD hash'ine sabitlenmiş, bütün parent zincirini doğrulayan restore.

`ClockGuard` varsayılan iki saniyelik wall/monotonic fark bütçesiyle çalışır;
geri UTC sıçramasını ve monotonic sıfırlanmasını reddeder. Kaynak isteği öncesi
ve hem başarılı hem hatalı yanıt sonrasında kontrol edilir. `CutLedger` isteğe
bağlı callback ile en son SQLite INSERT öncesinde tekrar kontrol eder. Doğrulama
sırasında saat değişirse fixture/kesit transaction'ı geri alınır.

ClockGuard mutlak UTC'nin başlangıçta doğru olduğunu kendi başına kanıtlamaz:
`initial_utc_independently_attested=false` kalır. Kontrol, yerel saate bakarak
bütün sürecin sekiz saat erkene kaydığını tespit edemez. Bu yüzden güvenilir
UTC örneklemi/NTP ve host saatinin ayrıca doğrulanması operasyonel önkoşuldur.
Hiçbir saat değiştirme/ayarlama komutu çalıştırılmadı.

Saat hatasında CLOCK_DISCONTINUITY / UTC_UNTRUSTED raporlanır. Önceden commit
edilmiş kayıt olup olmadığı denetlenmeden yeni kayıt sayısı sıfır varsayılmaz;
AUDIT_REQUIRED anlamındaki null korunur. Mevcut tahminlerin zamanı yeniden
etiketlenmez. Hatalı UTC ile hesaplanan bir yeniden deneme zamanı güvenilir
sayılmaz; saat düzeltilip kayıtlar denetlenmeden kör tekrar yapılmamalıdır.

FAZ37 pilotu mevcut FAZ35 planlama ve FAZ34 atomik toplamasını kullanır. Eski
komutlar silinmedi; yeni koruma için `faz37 pilot` giriş noktası kullanılmalıdır.
Yeni service taslağı `.example` olarak ops/faz37 altındadır; kurulmadı.

```sh
python -m faz37 pilot /ABS/PILOT/pilot-config.json
```

Gerçek kayıt oluştuğunda FAZ33 immutable paketi kaynak gözlem ve ingestion,
gerçek özellik kesimi, tahmin üretim/kayıt zamanı, başlangıç UTC, kaynak
kimlikleri, model SHA ve kapsamı içerir. FAZ34 FINISHED olayındaki özgün kayıt
SHA'sı bu pakete bağlanır. ClockGuard raporu ayrıca çalışma çıktısına eklenir.
Yeni gerçek kayıt yoksa bir tahmin SHA'sı üretilmiş gibi raporlanmaz.
FAZ31 eğitilmemişse NO_MODEL_AVAILABLE ve null sayısal gölge tahmin korunur.

## Kalıcı durum mekanizmaları

| Bileşen | Durum |
|---|---|
| Sürümlü manifest, SHA-256, fsync ve atomik yerel HEAD | FAZ36 altyapısı korunuyor |
| Beklenen parent ile koşullu güncelleme ve yerel süreç kilidi | Yerelde test edildi; dağıtık garanti değil |
| Özgün satır envanteriyle eski/eksik/değişmiş geçmiş reddi | Korunuyor |
| Bütün parent zinciri, ardışık generation ve envanter devamlılığı | FAZ37'de eklendi |
| Dışarıdan beklenen son HEAD SHA'sına karşı eski geçerli HEAD reddi | FAZ37'de eklendi |
| Restore sonrası dosyaların yeni dizinden hash/SQLite doğrulaması | FAZ37'de eklendi |
| Yetkili harici hedef, dış CAS ve gerçek Cloud failover | **Yok / doğrulanmadı** |

Beklenen HEAD hash'i kapsül içinden otomatik güvenilir kabul edilmez. Güvenilir
son hash bilinmiyorsa eski bir yedeğin gerçekten son durum olduğu kanıtlanamaz.
Yerel kullanıcı aynı eski HEAD'i yeniden verirse sistem global güncelliği
kendiliğinden bilemez. Bu nedenle yetkili dış HEAD/makbuz hâlâ gereklidir.

`restore-state` yayın kilidini alır, beklenen HEAD'i kontrol eder, parent
zincirini ve ardışık sürümleri doğrular, son kapsül envanterini tekrar hesaplar.
Sadece yeni dizine restore eder. Her SQLite dosyası yeni konumdan açılır;
SHA-256 ve integrity_check kontrol edilir. Başarılı son durum ayrıca
FAZ37_VERIFIED_STATE.json ile işaretlenir. Kaynak HEAD değişmişse başarı
onayı verilmez. Eski dosyaların üzerine yazılmaz.

```sh
python -m faz37 restore-state /LOCAL/PUBLICATION /NEW/PILOT \
  --expected-head-sha256 TRUSTED_LATEST_HEAD_SHA256
python -m faz37 verify-recovery-child /LOCAL/PUBLICATION \
  --expected-head-sha256 TRUSTED_LATEST_HEAD_SHA256
```

Gerçek altı veritabanlı kapsül, temiz kaynak dizininde Python `-I` alt sürecinde
kurtarıldı. Kopya modülün kullanıldığı doğrulandı ve altı SQLite yeni konumdan
tekrar açılıp kontrol edildi. Bu **ayrı süreç ve ayrı kaynak dizini** kanıtıdır;
gerçek yeni Codex Cloud makinesi değildir. Aynı Cloud ortam ID'si kullanılıyor;
yeni Cloud runtime/oturumlar arası restore **DOĞRULANMADI** olarak kalır.
Gizli anahtar, ücretli hizmet veya harici yükleme oluşturulmadı.

## Zamanlayıcı karşılaştırması

| Seçenek | Teknik özellik | Risk / bu görevdeki durum |
|---|---|---|
| GitHub Actions hosted cron | En küçük aralık 5 dakika; default branch; concurrency grubu | Gecikme/düşen işler; disk ephemeral; başka makinelerdeki writer'ı kilitlemez; etkinleştirilmedi |
| Mevcut Codex Cloud | UTC araçları ve yerel çalıştırma mevcut | Oturum/süreç kesilebilir; workspace kalıcılığı ve sürekli timer doğrulanmadı |
| Fly.io | Machine + bağlı yerel persistent volume kurulabilir | Volume tek server/region ve tek Machine'e bağlıdır; otomatik volume replikasyonu yok; ayrıca host/backup/maliyet/yetki gerekir |

Fly.io'nun public volume belgesi HTTP 200 ile okundu:
https://fly.io/docs/volumes/overview/. Bu sadece teknik incelemedir. Mevcut
Fly/Telegram üretimine erişim/değişiklik veya yeni app/volume kurulumu yapılmadı.
Fly.io ücretsiz/garantili alternatif diye sunulmaz. GitHub cron için FAZ36'da
kaydedilen resmî gecikme/default-branch riskleri geçerlidir. Hiçbir seçenek
20:00 UTC kesitini zamanında çalıştırma garantisi vermez.

## Testler ve koruma kanıtı

**725 regresyon testi başarılı**, 43.710 saniye; **13 yeni FAZ37 testi**.
Beklenmeyen başarısızlık yok. Saatin ileri/geri sıçraması, monotonic reset,
nonfinite saat, son INSERT guard'ı, 403 durumunun korunması, 429 sırasında
saat sıçraması, eski HEAD, bozuk/eksik parent, atlayan generation, kilitli
publisher ve temiz süreçte pinned restore test edildi. Önceki yarış,
tekrar çalıştırma, SQLite kilidi, kesinti, 403/429/ağ ve bozuk yedek testleri
tam pakette tekrar geçti. Ret senaryoları beklenen test başarısıdır.
Sentetik tahmin veya test başarısı gerçek model doğruluğu değildir.

36 önceki FAZ29–36 doküman/kanıt/taslak dosyası byte seviyesinde Git HEAD ile
karşılaştırıldı. Yedi eski dosyanın ve dört model kaynak dosyasının hash'leri
korundu. Değişiklikler tahmin katsayılarına veya eski satırlara uygulanmadı.
Derleme/diff kontrolleri başarılı; son commit'in GitHub CI sonucu ayrıca
doğrulanır. Yerel Docker başarısı iddia edilmez.

Kritik açıklar: harici kalıcı hedef yetkisi ve dış CAS yok; gerçekten ayrı
runtime restore testi yok; başlangıç UTC doğruluğu/host uptime sorumluluğu var;
kesit saatinde aktif çalıştırıcı yok. Sakatlık/kadro/piyasa/toparlanma verileri
doğrulanmış değil, tempo tahmin ve olasılık kalibrasyonu kurulmamış.

FAZ38 önceliği: 20:00 UTC'de bağımsız UTC kontrolüyle FAZ37 pilotunu çağırıp
ilk uygun gerçek kesitin SHA/zaman/kaynak kanıtını almak; kalıcılık içinse açık
hedef yetkisi, dış HEAD/CAS ve gerçekten ayrı runtime kabul testini tamamlamak.
Bu koşullar sağlanmadan sistem kalıcı veya zamanı garantili diye sunulmamalıdır.
PR merge, Fly.io veya Telegram üretim değişikliği yapılmadı.
