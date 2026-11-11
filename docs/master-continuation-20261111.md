# Master continuation — UserLAnd referans kurtarma ve geliştirme arşivi

## Korunan checkpoint ve bağımlılık

Başlangıç: PR #80 `3742d05c353d596270f3b67088b1beb80d3c9602`, dal `dev/season-fixture-audit-20261111`. PR #79 `c847b04da89fa14d8771fa544daf44f7ac5852a7`; main `0e634083ccd1da87c7313710a17aa6e63fb5abe2`. İki PR açık/taslak, push ve PR unit-tests/docker-build başarılı olarak yeniden kontrol edildi. Tamamlanan kaynak indirmeleri tekrarlanmadı. Bu devam aynı geliştirme dalındadır; önceki kanıt dosyaları ve kodlar değiştirilmedi.

`git merge-base --is-ancestor` ile #79'un #80 içinde bulunduğu doğrulandı. Ayrı main-merge onayı verilirse sıra **#79 → #80**. #79 squash/rebase ile farklı geçmişe dönüştürülürse #80'in main'e göre farkı ve CI'si yeniden değerlendirilmelidir; otomatik merge yapılmaz. Bu oturumda main merge/deploy/secret işlemi yoktur.

## UserLAnd hatasının kanıtı ve düzeltmesi

Kullanıcı ekranlarında `/home/userland/zeynal-production-deploy` için yalnızca `+refs/heads/main:refs/remotes/origin/main` refspec'i, `origin/HEAD`, `origin/main` ve `M fly.toml` görüldü. Sıradan fetch bu dar refspec ile dev referanslarını oluşturmuyordu. Sadece dal adını fetch etmek de her zaman `origin/dev/...` yaratmaz; sonuç yalnızca FETCH_HEAD'e yazılabilir. Açık kaynak–hedef refspec bu belirsizliği kaldırır.

Kullanıcı açık refspec'li atomik fetch'i uyguladı: iki dev referansı oluşturuldu; tam SHA'lar yukarıdaki #79/#80 checkpoint'leriyle eşleşti. Sonra iki eksik fetch kuralı, main kuralı silinmeden eklendi. Son ekran toplam üç kuralı gösterdi. `fly.toml` SHA-256 değeri ayar eklemeden önce ve sonra aynıydı ve `M fly.toml` korundu. Bu, **kullanıcının paylaştığı terminal kanıtıdır**; Cloud'un Android'e uzaktan eriştiği iddia edilmez.

Kullanıcı tarafından daha önce bildirilmiş 2 tahmin / 2 sonuç ile Fly makinesi `830932f77d2598`, passing sağlık ve volume bilgileri yeniden sorgulanmadı. Paylaşılan sağlık çıktısı passing gösterir; bununla SQLite içerikleri veya kalibrasyon doğrulanmış sayılmaz. Üretim DB'ye erişilmedi.

`tools/sync_review_refs.py` aynı hatayı tek-dal clone'larında düzeltir. Varsayılan dry-run'dır. `--apply`, sadece origin izleme referanslarını atomik fetch eder; checkout/pull/reset/stash/clean yoktur. `--configure-tracking` ayrıca eksik **tam** refspec'leri tekrar eklemeden tamamlar, eski kuralları korur ve negatif fetch politikasını otomatik aşmaz. HEAD, index, tracked diff ve fly.toml hash'i kontrol edilir. Cloud'da gerçek referans kurtarması ve kalıcı ayar ekleme de çalıştırıldı; çalışma dosyaları korunmuştur.

### Android için kurtarma reçetesi — bu oturumda zaten uygulandı

Tekrar çalıştırmaya gerek yoktur. Başka kopyada önce salt okunur tanılama yapılır; çıktı incelenmeden sonraki adıma geçilmez.

```bash
cd /home/userland/zeynal-production-deploy
git status --short
sha256sum fly.toml
git config --get-all remote.origin.fetch
```

Eksik referans varsa, yalnızca doğrulanan dallar fetch edilir:

```bash
p79=dev/archive-calibration-orchestration-20261111
p80=dev/season-fixture-audit-20261111
git fetch --no-tags --atomic origin \
  "+refs/heads/$p79:refs/remotes/origin/$p79" \
  "+refs/heads/$p80:refs/remotes/origin/$p80"
```

SHA ve hash doğrulaması salt okunurdur:

```bash
git rev-parse --verify "origin/$p79"
git rev-parse --verify "origin/$p80"
sha256sum fly.toml
git status --short
```

Kalıcı ayarda eksik iki kural bu oturumda bir kez eklendi; tekrar tekrar `git config --add` çalıştırılmaz. Araçtaki `--apply --configure-tracking` tekrarlı kullanımı idempotenttir. Yeni checkpoint push edildikten sonra normal `git fetch --no-tags origin` artık iki dev referansını da yeniler; çalışma dalını değiştirmez.

## Otomatik arşivleme — yalnızca opt-in geliştirme akışı

`season_archive_collect.py` önceki #80 native katalog doğrulamasını kullanır. Desteklenmeyen çoklu tarih query'si yerine, en fazla 31 ayrı NBA sağlayıcı günü ve isteğe bağlı tek EuroLeague E2026 kataloğu planlanır. Plan tamamen doğrulanmadan HTTP başlamaz; varsayılan dry-run'da HTTP ve dosya yazımı yoktur. `--live` açıkça verilmelidir. Üretim scheduler'ına veya Telegram'a bağlanmadı.

- 401/403/429 aynı sağlayıcı için sonraki istekleri durdurur; başka lig sağlayıcısı devam edebilir. Beklenen istek ve gerçek deneme sayıları ayrıdır. Başarısız veya atlanan günün maç sayısı None kalır; yalnızca başarılı boş belgede 0 kullanılır. Redirect/retry ile erişim engeli aşılmaz.
- Bağlantı/okuma timeout'ları, akış parçaları arasında toplam süre kontrolü, 4 MiB belge limiti ve JSON/digest/URI/HTTP bağlama kontrolleri vardır. Süre kontrolü read timeout ile birlikte çalışır; kesintisiz akan yanıtın sınırsız süre sürmesi engellenir.
- Mevcut `audit_scoreboard_identity` tekrar kullanılır: NBA sağlayıcı günü US Eastern takvimidir; UTC gece yarısı maçları yanlış güne taşınmaz. Farklı gün belgesi sessizce kabul edilmez. Native sezon/lig/final/periyot/uzatma kontrolleri #80'de kalır.
- Yerel yayın isteğe bağlıdır. Var olan kullanıcı dizinine, içerik hash'li `archive-collection-*.json`, 0600 izin, geçici dosya+fsync ve atomik exclusive link ile yazılır. Aynı envelope yeniden yazılmaz; bozuk mevcut dosya ezilmez. Disk doluluğu/izin hatası yarım tamamlanmış manifest bırakmaz. `/data` ve symlink dizinleri reddedilir.
- Saklanan çıktı native belgeden yeniden oynatılır; yalnızca yeniden hesaplanmış hash ile sahte sayaç veya eğitim uygunluğu kabul edilmez. Oluşturma saati ile özgün observed/ingested saatleri ayrıdır. Her çıktı retrospektif araştırmadır; yeni maç öncesi tahmin veya model eğitimi değildir.

Güvenli başlangıç yalnızca planı gösterir:

```bash
python3 season_archive_collect.py \
  --nba-date 20261110 --euroleague
```

Bu komut yeni geliştirme dosyalarının bulunduğu ayrı review kopyasında kullanılır; üretim kopyasını güncellemek/checkout yapmak için talimat değildir. Canlı toplama veya yerel yayın bu dry-run komutuyla etkinleşmez. Aynı fixture'ın farklı toplama raporlarındaki sayaçları toplanarak örneklem üretilmez; model girişinde kanonik tekilleştirme ve ayrıca PIT/model kanıtı gerekir.

## Gerçek doğrulama düzeyi ve testler

Önceki pin'li gerçek belgeler yeni HTTP yapılmadan akıştan geçirildi: NBA 6 maç/6 final/periyot; EuroLeague 380 fikstür/100 tamamlanmış ve periyotlu maç. Kaynak gözlem/ingestion saatleri korunmuştur. İki kez yerel yayın, aynı artifact için created=True ardından False döndürdü; dosyadan tekrar okuma/replay doğrulandı. Bu yeni canlı veri, yeni tahmin, yeni örneklem artışı veya bağımsız ikinci Cloud kalıcılık deneyi değildir.

Source HTTP transport hata senaryoları sentetik regresyonlarla doğrulandı. Bu tur yeni canlı HTTP toplayıcısı üretimde çalıştırılmadı. Önceki NBA.com 403 ve ESPN range-query 400 sorunları aşılmış/giderilmiş gösterilmez. Veri kullanım izni, bağımsız sezon tamlığı, oyuncu/tempo/kadro, model/source digest'i ve tahmin öncesi özellik erişilebilirlik kanıtı eksikleri devam ediyor.

22 yeni deterministik test ile **303/303 tam regresyon**, **22/22 odaklı test** geçti; son başarısız test 0. Testler dar Git refspec, değişmiş/staged fly.toml, atomik fetch, kalıcı ayar idempotency, 403/429/timeout, yanlış gün, sahte digest/sayaç, eksik veri, disk doluluğu, izin, eşzamanlı yayın ve bozuk artifact retlerini kapsar. Son SHA için push/PR unit-tests ve docker-build ayrıca doğrulanır. Metrikler hesaplanmadı; kalibrasyon NOT_ESTABLISHED ve model güncellemesi engelli.

Kanıt metadatası: [master-continuation-20261111.json](evidence/master-continuation-20261111.json). Ham kaynak belgeleri ve kullanıcı ekran görüntüleri GitHub'a yüklenmedi. Fly /data, üretim makinesi/volume, üretim botu ve secrets değiştirilmedi.
