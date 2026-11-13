# FAZ 84.5 — NBA + EuroLeague Telegram arşiv replay bağlantısı

Mevcut PR #84, `dev/hybrid-possession-research-20261112`; başlangıç `6e1f241`. NBA komutları artık geçmiş arşivden yanıt verir. Yeni NBA tahmini, eğitim, simülasyon veya SQLite tahmin kaydı oluşturulmaz. Main merge ve production deploy yapılmadı.

## Kök neden ve düzeltme

`test_bot`, `--nba-model` verilmediğinde yalnızca EuroLeague `FrozenHybridService` servisini kuruyordu. Paketteki NBA kayıtları komut yönlendirmesine bağlı değildi. `nba_replay.py` adaptörü tar.gz dosyasını salt okunur açar; diske çıkartmaz, indirme yapmaz ve `fit/predict` çağırmaz. Model verilmeyen varsayılan kurulum artık NBA replay + mevcut EuroLeague replay sağlar. CLI açık canlı modelle başlatılsa bile bu dört bilinen NBA eşleşmesinde replay önce gelir.

`--replay-only` canlı NBA modeli/ileri sonuç toplama seçeneklerini reddeder, sonuç poll döngüsünü başlatmaz ve `/nba` için de arşiv fikstür listesini kullanır. Telegram teslimat günlükleri ayrı test dizininde tutulabilir; tahmin arşivi salt okunurdur.

Paket SHA-256: `9e95f0d849f530325ef881e389179796577a82c65c4aa3be798bbaa2bf3700b3`.

Yalnızca doğrulanmış `capture-optimized-b81a02d1194884ccf97356e085bb5931e9f9b64085ecacc7c211b71378ea3118.json` dosyasındaki dört kayıt seçilir. Önceki varyantlar silinmez; dört maç sekiz bağımsız örnek gibi sayılmaz.

Ek kaynak tutarsızlığı: Washington ve Minnesota kayıtlarının `fixture_source_url` alanı `dates=20261113` bölümünü gösterir; gerçek maç, aynı snapshot'a bağlı `dates=20261112` belgelerindedir. İlk manuel adaptör denemesi tek yardımcı URL'ye güvenerek kimlik doğrulamasında durdu. Düzeltme, bağlı ve SHA/zamanı doğrulanmış bütün scoreboard belgelerinde ESPN maç ID'sini, takım ID/adlarını, sezonu ve UTC başlangıcını eşleştirir. Bu durum regresyon testine alındı. Orijinal alan değişmedi; kaydedilmiş URL ve kimliği doğrulanan URL ayrı gösterilir.

## Dört doğrulanmış kayıt

| Maç | ESPN ID | UTC başlangıcı | TSİ başlangıcı | Optimize snapshot SHA başlangıcı |
|---|---|---|---|---|
| Philadelphia 76ers–Toronto Raptors | 401909976 | 13 Kasım 00:00 | 13 Kasım 03:00 | `7085c7f0ef43` |
| Washington Wizards–Detroit Pistons | 401909977 | 13 Kasım 00:00 | 13 Kasım 03:00 | `7631a34a939f` |
| Minnesota Timberwolves–Dallas Mavericks | 401909978 | 13 Kasım 01:00 | 13 Kasım 04:00 | `959ee75565ce` |
| Phoenix Suns–Charlotte Hornets | 401909979 | 13 Kasım 02:00 | 13 Kasım 05:00 | `b736deff32be` |

Komut tarihi TSİ takvim günüdür: **2026-11-13**. `2026-11-12` sessizce düzeltilmez; `FIXTURE_LOCAL_DATE_MISMATCH` ve doğru tarih döner. Başlamış/bitmiş maçta yalnızca eski kaydın replay'i gösterilir. Bilinmeyen veya ters ev/deplasman eşleşmesi yeni tahmine dönüştürülmez.

Çıktı orijinal skor, çeyrek ve yarı projeksiyonlarını; 11 kapsamın QMC P50/P25–P75/P10–P90/P05–P95 bantlarını ve kayıtlı MC/QMC yöntem, seed, örnek sayısı, ham olasılık ve toplam sayı dağılımı karşılaştırmasını gösterir. `snapshot.prediction`, `intervals` ve `mc_qmc` servis raporunda birebir korunur; görünümdeki yuvarlama arşiv değerlerini değiştirmez.

`NOT_CALIBRATED` gizlenmez. Ham normal süre olasılıkları güven yüzdesi değildir; güven endeksi hesaplanmaz. Piyasa çizgisi/edge uydurulmaz. Üretim, snapshot ve veri zamanları hem UTC hem TSİ gösterilir. Tekrar/yanıt zamanı bunlarla karıştırılmaz. Ayrı ilk kalıcı arşiv zamanı bu eski kayıtlarda kanıtlanmadığından bilinmiyor kalır. Snapshot ve paket SHA-256 değerleri gösterilir. HTML mesajlar UTF-16 bütçesine göre bölünür.

## UserLAnd Ubuntu güvenli çalıştırma

Repository kökünde, PR #84 dalının güncel hali ve mevcut Python bağımlılıklarıyla çalıştırın. Dört test ayarını yalnızca izole ortamda sağlayın: `ZEYNAL_TEST_BOT_TOKEN`, `ZEYNAL_TEST_BOT_ID`, `ZEYNAL_TEST_BOT_USERNAME`, `ZEYNAL_TEST_CHAT_ID`. Üretim token'ını kullanmayın; token'ı sohbete/loga yazmayın. Bot kullanıcı adı test/sandbox/research kimliği olmalıdır.

```sh
python3 -m hybrid_engine.nba_replay
python3 -m hybrid_engine.test_bot --preflight
python3 -m hybrid_engine.test_bot --replay-only --archive-directory "$PWD/docs/prospective/euroleague-20261112" --nba-replay-packet "$PWD/docs/evidence/nba-phase843-prospective-native-20261113.tar.gz" --data-directory "$HOME/zeynal-isolated-replay"
```

Bu komuta `--nba-model` eklemeyin. İlk komut ağ/Telegram olmadan dört kaydın bütünlüğünü kontrol edip komutlarını listeler. İkinci komut token değerini açığa çıkarmadan eksik ayarları raporlar. Üçüncü komut izole test botunu çalıştırır; sonuç toplayıcıyı ve canlı NBA tahmin yolunu açmaz.

Telegram test kullanıcısının göndereceği komutlar:

```text
/analyze NBA 2026-11-13 Philadelphia 76ers vs Toronto Raptors
/analyze NBA 2026-11-13 Washington Wizards vs Detroit Pistons
/analyze NBA 2026-11-13 Minnesota Timberwolves vs Dallas Mavericks
/analyze NBA 2026-11-13 Phoenix Suns vs Charlotte Hornets
/analyze EUROLEAGUE 2026-11-12 Real Madrid vs Crvena Zvezda Meridianbet Belgrade
```

## Test sonucu ve güvenlik

İlk bağlantı teslimatı (`26c5f34`): **663 başarılı / 0 başarısız**; önceki 642 test + 21 yeni regresyon. Dört NBA komutu parser → test-bot dispatch → replay → Telegram reply handler yolunda ayrı ayrı test edildi. Bu testlerde `requests.get`, Bayesian `fit/predict` ve canlı NBA ledger kurucusu çağrılırsa hata verecek biçimde kapatıldı: hiçbirine gidilmedi. Bozuk paket/snapshot SHA, geç kaynak, tipoff sınırı, sahte kalibrasyon, yanlış isim/tarih, HTML bütçesi, mutasyonsuz tekrar ve EuroLeague dispatch koruması denetlendi.

Yerel birleşik PTB/HTTP taklit akışı **PASS**: 29 komut, dört NBA kaydı, bir EuroLeague replay isteği, tekrarlar ve tarih hatası; yeni PREMATCH=0. Tek CPU / 256 MiB process adres alanında tepe RSS **88,13 MiB**. Yetkisiz chat reddedildi. Paket doğrulama başlangıcı RSS'ye dahildir; gecikme ölçümü başlatılmış yerel akışa aittir. Bu host cgroup testi veya gerçek Telegram teslimatı değildir.

GitHub Actions'a aynı NBA + EuroLeague replay yolunu `--cpus=1 --memory=256m --memory-swap=256m`, salt okunur root ve ağ kapalı Docker içinde çalıştıran kontrol eklendi. Son HEAD CI sonucu PR açıklaması ve tamamlanma raporunda verilir.

Önceden izlenen arşiv/paket dosyaları başlangıç commit'iyle bayt düzeyinde karşılaştırıldı; SHA'lar [makine kanıtında](nba-archive-replay-evidence-20261113.json). Üretim motorları, skor matematiği, geçmiş tahminler, disk/snapshot/secret ve Fly yapılandırması değiştirilmedi.

**Karar:** NBA + EuroLeague izole replay bağlantısı testlerde çalışıyor. Gerçek Telegram E2E bu ortamda test kimlikleri bulunmadığından yeniden çalıştırılmadı; kullanıcı bildirimi API/chat/mesaj kanıtı yerine geçmez. Üretim geçişi hâlâ **NO-GO**.

## CLI başlangıcı devam denetimi

Yeni `test_test_bot_bootstrap.py`, doğrudan `test_bot.main()` komut satırı yolunu gerçek PTB builder/servis kurulumu ve yalnızca loopback HTTP Bot API taklidiyle çalıştırır. Uzun süren `run_polling` döngüsü kontrollü bir sürücüyle değiştirilir; gerçek ağ polling akışı önceki ayrı kaynak testinde sınanmıştır. Bu yeni testler gerçek Telegram E2E değildir.

- CLI kurulumu ve `post_init` sonrasında dört NBA + bir EuroLeague komutu doğru handler'a gider.
- Bot ID/kullanıcı adı doğrulaması başarısızsa hiçbir mesaj gönderilmez.
- Mevcut webhook varsa silinmez, üzerine yazılmaz ve komutlar başlatılmaz.
- `--replay-only --nba-model ...` API çağrısı yapılmadan reddedilir.
- Replay modunda kaynak/sonuç indirmesi ve tahmin-ledger dosyası oluşturma gerçekleşmez.
- Başlangıç hata çıktısı yalnızca sabit, izin verilen hata kodlarını gösterir; keyfî API hata metni veya token içeren URL stdout'a geçirilmez.

Yeni hata kodları: `TEST_BOT_SERVER_IDENTITY_MISMATCH`, `TEST_BOT_HAS_WEBHOOK_POLLING_NOT_STARTED`, `NBA_REPLAY_PACKET_SHA256`. Diğer açıklanmaması gereken hatalar `ISOLATED_TEST_BOT_FAILED` olur. Webhook korumasını geçmek için otomatik silme eklenmedi; doğru ayrı test botu kullanılmalıdır.

Bu devam aşamasının güncel koşu sonucu ve kaynak hash'leri [CLI başlangıç kanıtında](nba-replay-bootstrap-evidence-20261113.json) bulunur. Önceki 663 testlik rapor tarihsel kanıt olarak korunur; yeni koşu onun yerine geçirilmez.
