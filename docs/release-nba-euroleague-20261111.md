# NBA / EuroLeague tek sürüm adayı

Bu dal üretim dağıtımı değildir. Gerçek sağlayıcılarla komut yolu, yerel prematch
kaydı ve Telegram biçimlendirmesi sınanır; gerçek Telegram teslimatı, güncel
UserLAnd/Fly volume durumu ve resmî NBA çapraz doğrulaması ayrı kabul kapılarıdır.

## Birleştirilen geliştirme zinciri

| Kaynak | Durum | SHA |
|---|---|---|
| main | İncelenen temel | `0e634083ccd1da87c7313710a17aa6e63fb5abe2` |
| PR #77 | Daha önce main'e merge edilmiş | `ba036cdcdecdc50910a690e326cdbfdc2917f200` |
| PR #79 | Açık taslak; bu dalın atası | `c847b04da89fa14d8771fa544daf44f7ac5852a7` |
| PR #80 | #79'u içerir | `542cec080fda7ef0b05ebe14a269f78ca9b34325` |
| PR #81 | #80'i içerir | `b2387fbfa57308ac5ddeaaca66391064f5413190` |
| PR #82 | #81'i içerir | `ada95c5147b6a9c1f5be2653f9d57274553f7cef` |
| Entegrasyon kod checkpoint'i | Tek release dalı | `fec9ad387bc6a5571097d2c1727c2d121e4daee8` |

#77'nin merge commit'i ve main, dalın ataları olarak Git üzerinden doğrulandı.
Değişiklikleri tekrar cherry-pick etmek veya tamamlanmış işleri yeniden yazmak
gerekmedi. Eski PR'lar değiştirilmedi/merge edilmedi; tek release PR main'i hedefler.

## Gerçek komut yolu

`main.analyze_command` → `VerifiedAnalyzeService` → sezon katılımcı registry'si →
benzersiz takım → doğrulanmış gelecekteki fikstür → native geçmiş → skor modeli →
taze fikstürün tekrar kontrolü → kısa atomik SQLite kaydı → HTML yanıtı.

- NBA: ESPN sezon katılımcıları, gün scoreboard'ları, takım sezon schedule'ı ve
  her kullanılan final için bağımsız endpoint'teki summary karşılaştırılır.
  Takım ID, sezon, tarih, taraflar, final skor ve periyotlar birlikte doğrulanır.
- EuroLeague: resmî `api-live.euroleague.net` kulüp/sezon/games; ESPN geçmişi yok.
- Her takım için en az 6, en fazla son 10 doğrulanmış normal süre maçı.
  Kaynak gözlemi/ingestion zamanı tahmin oluşturulmasından önce olmalıdır.
- FAZ13 skor formülü korunur: `(ev atılan + dep yenilen)/2` ve tersi.
  Çeyrek projeksiyonu gerçek geçmiş çeyrek ortalamalarından gelir; devreler
  bunlardan toplanır. Piyasa handikabı değil, model skor farkı gösterilir.
- Monte Carlo mevcut motorla 10.000 senaryo, seed 20261108, gözlenen takım skor
  standart sapmaları ve açıkça kalibre edilmemiş 0 korelasyon varsayımı kullanır.
  Varyans yetersizse yalnızca Monte Carlo alınamaz; geçerli skor çıktısı engellenmez.
- Tempo, sakatlık, beşli, rotasyon, piyasa veya kalibrasyon eksikliği doğrulanmış
  değerlerle karıştırılmaz. Skor modeli bu olmayan girdilere sahte değer atamaz.
- NBA 48, EuroLeague 40 dakika ve TSİ tarih/saat; uzatma normal süreye katılmaz.
- Kalıcı arşiv yoksa, SHA yapılandırılmamışsa, fikstür değişirse veya commit
  sırasında tipoff geçerse forecast gönderilmez. SQLite kilidi /nba'yı kapatmaz.
- Cache 32 belge / 16 MiB serileştirilmiş kaynakla sınırlı; eski belgeler çıkarılır.

`/nba` bu çalışma modunda ücretsiz ESPN kaynağını kullanır; API-Sports'a veya
ücretli piyasa uç noktalarına bağımlı değildir. Takım ve analiz mantığı fixture
komutlarına sabitlenmez. Diğer liglerin mevcut registry/araştırma kodu korunur;
bu release yalnızca NBA/EuroLeague canlı motorunu bağlar.

## Depolama ve uyumluluk

`prediction_ledger.sqlite` içinde yalnızca üç ek tablo açılır:
`live_analysis_snapshots`, `live_analysis_commit_receipts` ve `verified_analysis_results`. Eski predictions,
prediction_versions, outcomes ve provenance satırları/schema değiştirilmez.
Üretim yolu yalnızca bağlı /data içindeki zaten var olan, legacy ledger
tablolarını taşıyan dosyadır. Eksik dosya yerine boş veritabanı oluşturulmaz.
Yeni schema additiftir; otomatik DROP/ALTER veya veri dönüşümü yoktur.

Snapshot model/source digest, release SHA, Python sürümü, gerçek UTC oluşturulma,
cutoff, başlangıç, kaynak ID ve gözlem/ingestion zamanlarını içerir. Aynı maç/model
için ilk kayıt korunur; tekrar istek aynı JSON'u döndürür. INSERT-only trigger'lar,
hash ve SQLite integrity kontrolü vardır. Kilit alındıktan sonra ve commit öncesi
gerçek saat tekrar kontrol edilir; ağ işlemi SQL transaction'ı içinde yapılmaz.
Durable snapshot commit'i döndükten sonra ayrı değişmez completion receipt'i
yazılır. Commit gecikmişse veya süreç receipt öncesi kesilmişse kayıt onaysız
intent olarak kalır; canlı örneklem ve sonuç değerlendirmesine alınmaz. Yeniden
başlatma ancak özgün deadline hâlâ geçerliyken teyit edebilir. 20:04:44 başlangıç /
20:05:12 kapı geçişi, 20:05:00 deadline'ında MISSED_CUT regresyonuyla korunur.

Doğrulanmış final, native kaynak fixture'ı ve hash'iyle ayrı sonuç tablosuna
eklenir; snapshot değiştirilmez. Normal süre ve uzatma dahil final ayrıdır.
Geçmiş sonuçlar, yeni analizlerde native geçmiş yenilenirken fırsatçı biçimde
uzlaştırılır. Otomatik postgame zamanlayıcısı bu release ile etkinleştirilmez.
Legacy raporlar eski tabloları okumaya devam eder; yeni snapshot'ları aynı model
performansı gibi otomatik birleştirmez. Gerçek üretim DB'si bu Cloud'da açılmadı;
uyumluluk testi legacy şemanın izole sentetik kopyasında yapıldı.

PR #82'nin HISTORICAL_DATA / BACKTEST_SIMULATION / LIVE_PREMATCH_PREDICTION
ayrımı ve 640 maçlık yerel araştırma arşivi korunur. Kalibrasyon tamamlanmış
değildir; PIT kanıtı olmayan sonuçlar canlı isabet sayılmaz.

## Polling ve başlangıç güvenliği

`entrypoint.sh` yalnızca `exec python -u main.py` çalıştırır. İkinci polling botu
başlatan dynamic_scheduler yan süreci kaldırıldı. Legacy scheduler varsayılan
kapalıdır; release config'inde ENABLE_LEGACY_SCHEDULER=1 kabul edilmez.
Telegram token'ı mevcut Fly secret'tan alınır; secret değişikliği yoktur.
API-Sports key artık ücretsiz komutların başlatılması için zorunlu değildir.
Docker build'e `RELEASE_SHA=<tam SHA>` verilir. /ready bot/polling durumunu ve
release_sha'yı bildirir; /health tek başına analiz başarısı kanıtı değildir.

## Kabul kanıtının sınırları

`release_acceptance.py --execute --output-dir <izole yerel dizin>` gerçek
kaynaklardan yaklaşan NBA/EuroLeague maçını seçer, gerçek handler'ları çağırır,
SQLite'a zamanında kaydeder, tekrar çağrı ve hash/bütünlük kontrolü yapar.
Telegram reply transport'u yerelde yakalanır; bot başlatılmaz, getUpdates,
webhook, gerçek sendMessage veya üretim secret'ı kullanılmaz.
Ham kaynak yanıtları yerelde korunur; Git'e model çıktısı ve kaynak hash'leri
içeren kanıt raporu eklenir. Bu test üretim Telegram teslimatını doğrulamaz.

İstenen 11 Kasım Paris–Fenerbahçe ve Partizan–Baskonia, başlama sonrası yalnızca
önceden alınmış kaynak kesitinden BACKTEST_SIMULATION olarak çalıştırılır.
Sonradan hesaplama zamanı şimdi olarak kalır; canlı tahmin yaratılmaz. Sonuç
doğrulanıp ayrıca eşleştirilmedikçe gerçek skor/başarı iddiası yapılmaz.

Başlangıç Docker denemelerinde disk doluluğu ve imajda git bulunmaması nedeniyle
6 Git yardımcı testi hatası görüldü. Kod/veri silinmedi; yalnızca bu oturumun
kullanılmayan imaj/cache'i temizlendi. vfs çoğaltmasını azaltmak için mkdir COPY
öncesine taşındı; Git test bağımlılığı eklendi ve testler tekrar çalıştırıldı.
İlk gerçek idempotency denemesi tuple/list JSON dönüşümünü yakaladı; ilk yanıt
da kalıcı JSON'dan döndürülerek düzeltildi ve regresyonla korundu.

## UserLAnd: önce salt okunur kontrol

Aşağıdaki bloklar sırayla değerlendirilir. Sonraki dağıtım bölümünü onaydan
önce çalıştırmayın. Yerel değiştirilmiş fly.toml üzerine checkout/copy yapılmaz.

```bash
cd /home/userland/zeynal-production-deploy
git status --short
sha256sum fly.toml
fly machine status 830932f77d2598 -a zeynal-bot-core
```

Release SHA'sını PR'da CI ile eşleştirdikten sonra yalnızca inceleme ağacı:

```bash
git fetch --no-tags --atomic origin \
  '+refs/heads/dev/release-nba-euroleague-20261111:refs/remotes/origin/dev/release-nba-euroleague-20261111'
git rev-parse --verify origin/dev/release-nba-euroleague-20261111
```

```bash
release_sha=$(git rev-parse origin/dev/release-nba-euroleague-20261111)
release_dir=/home/userland/zeynal-release-${release_sha:0:7}
git worktree add --detach "$release_dir" "$release_sha"
cp -p fly.toml "$release_dir/fly.local.toml"
sha256sum fly.toml "$release_dir/fly.local.toml"
```

```bash
cd "$release_dir"
python3 release_ops.py inspect fly.local.toml
fly config validate --config fly.local.toml
```

TOML incelemesi Python 3.11+ veya tomli ister. Eksikse üretim adımına geçilmez.
Cloud'daki tracked fly.toml /data mount içermiyor; bu yüzden kullanıcı cihazındaki
gerçek config kopyası, gerçek machine/volume ve original hash doğrulanmalıdır.

## Yalnızca son onaydan sonra: dağıtım ve geri dönüş

Ön koşullar: resmî NBA çapraz doğrulama engeli ele alınmış; gerçek config ve
mevcut volume eşleşmiş; tek aktif polling machine'i doğrulanmış; final SHA CI
başarılı; kullanıcı main merge ve production deploy için son onayını vermiştir.
Ücretli/yeni builder kaynağı gerekecekse ayrıca onay olmadan devam edilmez.

Main'e sadece tek release PR merge edilir (GitHub UI veya yetkili gh CLI):

Main arada ilerlemişse önce bu SHA'ya karşı entegrasyon/CI tekrar değerlendirilir.
İncelenmemiş yeni main değişiklikleriyle merge veya deploy yapılmaz.

```bash
gh pr merge RELEASE_PR_NUMARASI \
  --repo Girayzeynal/zeynal-bot-core \
  --merge --match-head-commit "$release_sha"
```

Mevcut image/mount bilgisi özel yerel dosyada tutulur; ham machine JSON'u
chat'e göndermeyin. Burada `machine list --json` kullanılır; status'ta bu flag yoktur.

```bash
umask 077
mkdir -p .release-checkpoints
fly machine list -a zeynal-bot-core --json \
  > .release-checkpoints/machines-before.json
```

```bash
python3 - <<'PY'
import json
from pathlib import Path
rows=json.loads(Path('.release-checkpoints/machines-before.json').read_text())
m=next(r for r in rows if r['id']=='830932f77d2598')
Path('.release-checkpoints/rollback-image.txt').write_text(m['config']['image'])
Path('.release-checkpoints/rollback-release-sha.txt').write_text(m['config'].get('env',{}).get('ZEYNAL_RELEASE_SHA','UNKNOWN'))
if len([r for r in rows if r['state'] in ('started','starting')])!=1:
    raise SystemExit('Tek aktif machine doğrulanmadı; dağıtım durduruldu')
if not any(v.get('path')=='/data' and v.get('volume') for v in m['config'].get('mounts',[])):
    raise SystemExit('Mevcut /data volume doğrulanmadı; dağıtım durduruldu')
init=json.dumps(m['config'].get('init',{}))
if 'dynamic_scheduler' in init or '&' in init:
    raise SystemExit('Machine başlangıç komutu ayrıca incelenmeli; dağıtım durduruldu')
print('machine:',m['id'],'state:',m['state'])
print('mounts:',m['config'].get('mounts',[]))
PY
```

Eski image içindeki aktif WAL yazıcısını durdurmadan bounded SQLite checkpoint:

```bash
fly ssh sftp put release_ops.py /tmp/zeynal_release_ops.py \
  --machine 830932f77d2598 -a zeynal-bot-core
```

```bash
fly ssh console --machine 830932f77d2598 -a zeynal-bot-core \
  -C 'python /tmp/zeynal_release_ops.py checkpoint --execute --production'
```

Çıktıdaki integrity, legacy counts, backup SHA ve manifest doğrulanmadan ilerlenmez.
Yerel volume backup'ı harici/bağımsız felaket kurtarma kanıtı sayılmaz.
Builder'ın mevcut/yetkili ve maliyetinin uygun olduğu ayrıca doğrulandıktan sonra
yalnızca image build/push; bu komut app'i dağıtmaz:

```bash
fly deploy --build-only --push --config fly.local.toml \
  --image-label "rc-$release_sha" \
  --build-arg "RELEASE_SHA=$release_sha"
```

Üretilen image adını çıktıyla eşleştirin. Yeni builder/ücretli kaynak istenirse
durun. Mevcut tek machine'in image'ını güncellemek config, secret ve volume'u korur:

```bash
fly machine update 830932f77d2598 -a zeynal-bot-core \
  --image "registry.fly.io/zeynal-bot-core:rc-$release_sha" \
  --env "ZEYNAL_RELEASE_SHA=$release_sha" --yes
```

```bash
fly machine status 830932f77d2598 -a zeynal-bot-core
curl --fail --max-time 15 https://zeynal-bot-core.fly.dev/ready
```

Release SHA, aynı volume, tek polling, /nba ve iki ligde gelecekteki gerçek
fikstürle /analyze mesajları ve arşiv kaydı doğrulanır. Telegram yanıtı gerçek
hesapta görülmeden uçtan uca üretim teslimatı tamamlanmış sayılmaz.

Başarısızlıkta aynı machine'in önceki image'ına dönülür; DB eski backup ile
otomatik değiştirilmez, böylece dağıtım sonrası yeni kayıtlar da korunur:

```bash
previous_image=$(cat .release-checkpoints/rollback-image.txt)
previous_sha=$(cat .release-checkpoints/rollback-release-sha.txt)
fly machine update 830932f77d2598 -a zeynal-bot-core \
  --image "$previous_image" --env "ZEYNAL_RELEASE_SHA=$previous_sha" --yes
```

Volume silme/oluşturma, machine ölçekleme, ikinci polling, secret değişikliği
ve otomatik SQLite restore bu prosedürde yoktur.
