# FAZ 91 — `/predictions NBA` yanıtı ve arşiv denetimi

Başlangıç: `757407c5e85e1a332256a551a780522b22d8e3a1`, mevcut PR
[#89](https://github.com/Girayzeynal/zeynal-bot-core/pull/89),
`feature/hybrid-market-roster-evidence-20261114`.
Yerel temiz dal GitHub HEAD'e fast-forward edildi; iki yeni predictions commit'i
korundu. Main, Fly.io, üretim token'ı ve UserLAnd süreciyle işlem yapılmadı.

## Kanıtlanmış kod hatası

Başlangıç commit'inde gerçek PTB `Application.process_update` ve yerel HTTP Bot
API double ile `/predictions NBA` gönderildi. SQLite'ta bir doğrulanmış arşiv
kaydı vardı. Handler **−50 grubunda kayıtlıydı**, −100 yetkilendirmesi geçti.
Sonuç:

- `COMMAND_RECEIVED`: var.
- Hata: **AttributeError**.
- Handler traceback: `predictions_command` (başlangıç kaynağında satır 375),
  `stamp` (satır 363).
- `sendMessage` çağrısı: **0**.

`LedgerReports` Unix saniyelerini Python `int` olarak verir. Eski `stamp`, bunları
ISO metin sanıp `value.replace('Z', '+00:00')` çağırıyordu:
`AttributeError: 'int' object has no attribute 'replace'`.
İç ve dış except listeleri AttributeError'u kapsamıyordu; genel hata callback'i
sadece `HANDLER_ERROR` yazıyor, kullanıcıya yanıt göndermiyordu.

İlk tekrar üretim değişiklik öncesi checkout'ta yapıldı. Ek traceback kanıtı,
aynı orijinal handler kaynağının `git show 757407c5:...` üzerinden kontrollü
çalıştırılmasıyla alındı; çalışma dalı geri alınmadı. Bu, aynı boş yanıtı üreten
**doğrulanmış kod kök nedenidir**. Kullanıcının 16.47 TSİ oturumunun logları ve
çalışan süreç sürümü Cloud'da olmadığından, o oturumun birebir traceback'i
olarak sunulmaz. Eski sürümün hâlâ çalışması, başka giriş noktası veya teslim
hatası o oturum için ek kanıt olmadan dışlanamaz.

İkinci kayıt boşluğu: eski kod `/predictions` handler'ını yalnızca canlı NBA
servisi varsa ekliyordu. Artık bütün **izole test-botu** modlarında kayıtlıdır;
servis yoksa açık kullanılabilirlik yanıtı verir. Üretim `main.py` değiştirilmedi.

## Düzeltme ve çıktı

Yeni `hybrid_engine/predictions_command.py`:

- Unix saniyelerini doğrudan `Europe/Istanbul` ile dönüştürür; UTC kayıtlarını
  değiştirmez. Ayrı üretim saati eksikse ilk snapshot/arşiv saatiyle doldurmaz.
- Ev/deplasman, ESPN ID, maç TSİ, ilk üretim, ilk snapshot, ilk kalıcı commit,
  skor/toplam, model/sürüm/digest, bekleyen/doğrulanmış durum, gerçek normal süre
  skoru ve `/compare NBA <ESPN_ID>` komutunu gösterir.
- Bir fixture'ın birden fazla model sürümü ayrı kayıt olarak görülebilir;
  birden fazla model keyfî biçimde tek tahmine indirilmez.
- Uzun yanıtları **3.500 UTF-16 birimi** içinde böler. Emoji code point'leri
  bölünmez ve metin kaybolmaz. Sayfa başına 25 tahmin; sonraki sayfa açıkça
  `/predictions NBA 2` biçiminde verilir. On kayıt ilk sayfada tamamen gösterilir.
- SQL/şema/hash/saat/biçim ve beklenmeyen okuma hatalarında sabit, güvenli mesaj
  verir. Okuma timeout'u ayrı kod taşır. Özel hata metni/token/URL yazılmaz.
- Gönderim başarısızlığı ayrı olay olarak kaydedilir. Uygunsa kısa hata bildirimi
  bir kez denenir; tam liste tekrar gönderilmez. `RetryAfter` ve `Forbidden`
  durumlarında otomatik tekrar yapılmaz. Telegram erişimi tamamen yoksa hata
  bildirimi teslim edilemeyebilir; bu durumda günlükte başarısızlık görünür.
- `PREDICTIONS_STARTED`, `READ_OK/FAILED`, `SEND_ATTEMPT/SENT/FAILED` olayları
  update ID ile izlenebilir. Ayrı teslim günlüğü yazılabilir; **tahmin SQLite'ı
  salt okunurdur**. Günlük hatası mümkün olan kullanıcı yanıtını durdurmaz.

`/test nba` artık çalışan handler gruplarını ve
`PHASE91_PREDICTIONS_V1` sürümünü gösterir. Git pull yapılmış olsa bile eski
sürecin çalıştığını anlamaya yardımcı olur; bu tek başına gerçek teslim kanıtı
değildir. Gerçek uygulama yönlendirme testlerinde −100 filtresi ve
`ApplicationHandlerStop` doğrulandı. Yetkisiz sohbet arşiv yanıtı alamaz.

## Arşiv ve canlı performans

`ledger_reports.py` ESPN ID'lerini salt okunur rapora ekler. NBA kanonik kimliği,
takım/UTC/sezon alanlarından tekrar doğrulanır. Varsa üretim saati snapshot'tan
sonra olamaz. Mevcut pre-tipoff snapshot ve kalıcı commit kuralları korunur;
unconfirmed kayıtlar canlı performansa alınmaz. Yerleşik native final
ayrıştırıcısı ve normal süre/uzatma ayrımı değiştirilmedi.

Yeni `hybrid_engine/archive_audit.py`:

- `mode=ro`, `query_only`, bounded SQL ve integrity check kullanır;
  ledger kurucusu çağırıp şema oluşturmaz.
- Kayıt/hash/indeks/ilk commit/zaman/kimlik denetimi yapar. İmkân varsa orijinal
  kaynak asset'lerini de denetler; uzun dosya kontrolünden önce DB read
  transaction'ını kapatır.
- Farklı fixture'lara bağlanmış aynı ESPN ID'sini, yinelenen snapshot hash'ini,
  post-tipoff/çelişkili üretim saatini, eksik makbuzu ve orphan makbuzu raporlar.
  Çoklu model sürümünü otomatik mükerrer maç saymaz.
- Kaynaklar verilmemişse native kaynak denetimini BLOCKED olarak gösterir.
  Hatalı satırlar sessizce silinmez veya gerçek başarı hesabına dönüştürülmez.
- Sonuç çekmez, tahmin üretmez, düzeltmez, silmez, kalibrasyon yapmaz.
  Rapor ayrı bir içerik hash'li dosyaya eklenir.
- Aktif bot başka kayıt ekleyebilir; önce/sonra dosya hash'i değişirse bu tek
  başına denetimin veri değiştirdiğini kanıtlamaz. Her okuma kendi tutarlı
  SQLite snapshot'ını kullanır; eşzamanlı ekleme ihtimali açıkça işaretlidir.

## Gerçek 10 kayıt ve Philadelphia için erişim sınırı

Cloud'da bulunan dört araştırma ledger'ı **1, 1, 4, 4 kayıt** içeriyor. Kullanıcının
**10 maç / 9 bekleyen / 1 sonuç** UserLAnd veritabanı burada yok. On gerçek
kaydın tamamının kimliği, mükerrerliği, ilk saati ve sonucu doğrulandı denmedi.
Bunlar için durum **BLOCKED_REMOTE_LEDGER_NOT_AVAILABLE**.

Cloud'daki tek Philadelphia–Indiana kaydı salt okunur denetlendi:
SQLite **ok**, bulgu **0**, dosya hash'i önce/sonra aynı, snapshot SHA değişmedi:
`30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343`.
Bu önceki Cloud kaydının üretimi **14.14.05 TSİ**'dir; kullanıcının bildirdiği
**15.12 TSİ** UserLAnd kaydıyla aynı kayıt olduğu iddia edilmez. Yerel saat,
kullanıcının saatine uydurulmadı. İki ortamın yuvarlanmış skorlarının
112,5–109,3 / 221,8 olması aynı kayıt veya teslim makbuzu olduğunu kanıtlamaz.
Hiçbir uzak kayıt okunmadı veya değiştirilmedi.

Başlangıçtaki **51 arşiv/kanıt dosyası**, `main.py` ve altı sabitlenmiş model
kaynağı byte düzeyinde korundu. Önceki değişmez paketler yeniden üretilmedi.

## Test sonuçları ve kapsam

**831 test geçti, 0 başarısız** (812 korundu + 19 yeni).
Son handler tanı sürümü ilavesinden sonra 19 hedefli test de geçti. GitHub ve
Docker'ın final head sonuçları PR kontrollerinde ayrıca belirtilir.

- Gerçek PTB dispatch + yerel HTTP double: `/start`, `/nba`, `/predictions NBA`,
  `/accuracy NBA`, `/compare NBA 401000123` ve `/test nba` yanıtları kontrol edildi.
- **Açıkça sentetik** 10 maçlık ledger, 9 bekleyen / 1 native-schema doğrulanmış
  sonuçla test edildi. Bu, kullanıcının gerçek 10 maçının denetimi değildir.
- Sentetik n=1 için team MAE=7, RMSE=sqrt(53), Brier=0,26,
  log loss=−ln(0,6), 1Q toplam MAE=2,5; diğer 9 bekleyen maç metriklere katılmadı.
- Tekrarlanan okumalar öncesi/sonrası SQLite dosyası aynı kaldı. Sayfalama,
  Unicode/emoji sınırı, yanlış parametre ve bot username suffix'i test edildi.
- SQLite locked/corrupt/unexpected error, okuma timeout'u, gönderim hatası,
  rate limit ve forbidden senaryolarında yanıt/olay davranışı doğrulandı.
- Unconfirmed, rehash edilmiş post-tipoff üretim ve çelişen ESPN kimliği için
  silmeden/refit yapmadan bulgu üretildi; geçersiz canlı rapor reddedildi.
- İlk yeni test koşusunda testin kullandığı SQLite trigger adı yanlıştı;
  gerçek `live_analysis_no_update` adı düzeltildi. Test devre dışı bırakılmadı.
- Bounded native NBA komut akışına `/start` ve `/predictions` eklendi:
  yerelde **13 komut/13 yanıt**, tek CPU affinity ve 256 MiB adres alanı
  sınırında PASS, RSS **99,63 MiB**. Bu host cgroup'u 256 MiB diye sunulmaz;
  mevcut Docker CI işi gerçek 1 CPU/256 MiB kontrolünü ayrıca çalıştırır.

## Gerçek Telegram durumu ve çalıştırma

Bu commit için **gerçek Telegram E2E BLOCKED**: Cloud'da ayrı test botu token'ı,
bot ID, username ve chat ID ayarları yok. Yerel HTTP double sonuçları gerçek
Telegram teslimi değildir. Kullanıcının çalışan `/nba`, `/analyze`, `/accuracy`
ve `/compare` gözlemleri kullanıcı tarafından bildirilmiş kanıt olarak korunur.

Mevcut test-botu servisinin normal güncelleme yöntemi kullanılmalı; çalışan
poller'a ek ikinci poller başlatılmamalıdır. Üretim token'ı kullanılmaz.
Ayrı bot ayarları mevcutsa başlangıç ön kontrolü:

```sh
python3 -m hybrid_engine.test_bot --preflight
```

Araştırma dalı güncellendikten ve mevcut izole servis güncellemesi yapıldıktan
sonra, yetkili test sohbetinde:

```text
/test nba
/start
/nba
/predictions NBA
/accuracy NBA
/compare NBA <listede_gösterilen_ESPN_ID>
```

Gerçek 10 kaydı **botu durdurmadan, tahminleri değiştirmeden** denetlemek için,
yollar mevcut izole UserLAnd dizinine ayarlanarak:

```sh
python3 -m hybrid_engine.archive_audit \
  --ledger "$ISOLATED_NBA_LEDGER" \
  --assets-directory "$ISOLATED_NBA_ASSETS" \
  --output-directory "$ISOLATED_AUDIT_DIRECTORY"
```

`/data` veya symlink yoluna izin verilmez. Gerçek dizinler bilinmeden tahmin
edilmez. Bu komut yeni Bot API isteği, sonuç sorgusu veya model çalıştırması yapmaz.
Üretilen JSON'ın kayıt sayısı ve bulguları gerçek 10 maçlık audit'in kanıtıdır;
Cloud'daki sentetik test çıktısı onun yerine kullanılmaz.

## Karar

**Kod ve izole yerel doğrulama: GO. Gerçek 10 kayıt / yeni Telegram E2E:
BLOCKED. Üretim dağıtımı ve model terfisi: NO-GO.**
Yetki sınırları gereği main merge, Fly.io dağıtımı, kayıt silme/sıfırlama,
kalıcı disk/snapshot/secret değişikliği yapılmadı.

[Makine kanıtı, baseline traceback ve korunmuş snapshot](predictions-phase91-evidence-20261115.json).
