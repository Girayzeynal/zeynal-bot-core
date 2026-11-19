# Tek çalışır izole sürüm — 19 Kasım 2026

Kullanıcının çalışan checkout'ı `feature/hybrid-market-roster-evidence-20261114`
üzerinde kaldığı için #95, #97 ve #98'in tamamlanmış özellikleri o süreçte
yoktu. Ayrı worktree'deki salt-okunur inceleme çalışan botu güncellemez.
Ayrıca model üstünlüğü/terfisi için `NO_GO` ile işlevlerin kullanıma hazır
olması aynı mesajla sunuldu. Bu, mevcut kodu etkinleştirme/entegrasyon açığıdır.

Bu dal #98 `4b4843c`, #95 `bdcf358`, #97 `3de16c3` değişikliklerini merge
commitleriyle birleştirir; diğer PR'ler veya main değiştirilmez. Çekirdek
modeller ve kaynak pinleri korunur. Yeni `/features` gerçek yüklenen
bileşenleri; `/models` kaydedilmiş ayrı adayları gösterir. Fonksiyonel
kullanım, gelecekteki model üstünlüğü kararına bağlanmaz. Kaynak/kimlik/ilk
PREMATCH zamanı ve gerçek veri eksikliği kontrolleri korunur.

Launcher kendi bulunduğu checkout'tan çalışmalı; yeni worktree'den çağrılınca
eski `~/zeynal-hybrid-844` koduna dönmemeli. Mevcut venv, özel test token'ı,
aynı izole veri yolları ve tek-poller kilidi kullanılır. Fonksiyonel sürüm
üretime dağıtılmış sayılmaz. Çalışan Fly sürümü, `zeynal_data`, secrets ve
orijinal tahminler değiştirilmez; önceden belirtilen main/deploy kısıtı
kaldırılmadan üretim işlemi yapılmaz.

Bu teşhis yeni entegrasyon kodundan önce kaydedildi. Doğrulanmış işlevleri
etkinleştirmek model başarısını, yeni aday skorunu veya güven yüzdesini
uydurma yetkisi değildir. Kulüp haberi henüz maça/oyuncuya bağlanmamışsa
oyuncu etkisi diye uygulanmaz; pilotun mevcut opt-in ve erişim kuralları
korunur. Henüz yayımlanmamış aday için skor üretilmez.

## Kullanılabilir tek sürüm

| İşlev | Bu dalda davranış |
|---|---|
| NBA / EuroLeague / EuroCup analiz | Mevcut kaynak ve zaman denetimleriyle aynı yönlendiricide |
| Otomatik erken kayıt | Üç ligde mevcut 36 saatlik hazırlama ve son 15 dakika koruması |
| V2 / V3 araştırma | Hazır veri varsa arka planda ayrı PREMATCH üretimi; terfi kararı buna engel olmaz |
| `/models NBA <kimlik>` | İlk skor ve gerçekten yayımlanmış ayrı V2/V3 skorları; yeni hesaplama yapmaz |
| `/models EUROLEAGUE\|EUROCUP <kimlik>` | Lig arşivindeki bileşenler ve varsa ayrı V2 kayıtları |
| `/features` | Yüklenen bileşenler ve son kontroller; yüklenmiş olmak veri başarısı değildir |
| `/results all` / `/accuracy all` | Üç ligde eşleşmiş resmî sonuç ve model performansı |
| `--settle-results` | #95'in mevcut kolektörüyle yalnız doğrulanmış FINAL ekleme |
| `--results-review` | Aynı arşivin sağlayıcı sorgusuz raporu |
| `--verification-review` | #98'in mevcut salt-okunur cihaz denetimi |
| Kulüp kaynakları | #97'nin isteğe bağlı altı kulüp pilotu; maça/oyuncuya bağlanmamış haber skora eklenmez |

`/test nba`, `/test euroleague` ve `/test eurocup` işlev sürümünü
`INTEGRATED_TEST_20261119` olarak gösterir. Launcher mevcut Git HEAD'ini
`ZEYNAL_RELEASE_SHA` olarak geçirir; `/test runtime` bunu **bildirilen** sürüm
olarak gösterir. Bu bilgi değiştirilmiş dosyalar için bağımsız bir imza değildir.
Eski sürüm mesajı alınırsa entegrasyon süreci çalışmıyordur.

## UserLAnd'de eski checkout'ı koruyarak başlatma

İlk kurulum için Ubuntu terminalinde, aşağıdaki satırları ayrı ayrı çalıştırın.
Komutlar yeni worktree oluşturur; eski klasörü resetlemez veya silmez.

```bash
git -C ~/zeynal-hybrid-844 fetch origin feature/integrated-test-bot-20261119
git -C ~/zeynal-hybrid-844 worktree add --track -b feature/integrated-test-bot-20261119 ~/zeynal-integrated-test origin/feature/integrated-test-bot-20261119
bash ~/zeynal-integrated-test/scripts/run_isolated_test_bot.sh
```

Eski bot hâlâ çalışıyorsa ortak kilit `TEST_BOT_ALREADY_RUNNING` döndürür ve
mevcut süreci korur. Yeni sürüme geçerken eski botun terminalinde bir kez
Ctrl+C yapıp son satırı yeniden çalıştırın. İkinci bot başlatılmaz, süreçler
otomatik öldürülmez. Sonraki başlatmalarda yalnız son satır gerekir.

Yeni worktree kendi Python ortamı yoksa eski klasörün mevcut venv'ini kullanır;
modüller yeni worktree'den yüklenir. Token, veri, model ve arşiv yolları aynı
izole yollar olarak kalır; özel değerler kopyalanmaz. Git senkronizasyonu yalnız
bu entegrasyon dalını fast-forward eder. Yeni test bağımlılığı pytest, çalışma
ortamının `requirements.txt` dosyasına eklenmedi; CI için ayrı tutuldu.

## Cihazda kalan gerçek Telegram doğrulaması

Cloud ortamında özel test botunun kimlik bilgileri ve UserLAnd diski yok.
Buradaki PTB testleri sentetik sağlayıcı/Bot API kullanır; gerçek Telegram E2E
başarısı olarak gösterilmez. Yeni süreçte Telegram'a ayrı mesajlarla gönderin:

```text
/features
/test runtime
/models NBA 401909994
/results all
/accuracy all
/analyze EUROLEAGUE 2026-11-17 Zalgiris Kaunas vs FC Bayern Munich
/compare EUROLEAGUE E2026_112
```

`/models NBA 401909994` eski ilk kaydı gösterir; V3 planından önceki bir maça
sonradan aday uydurmaz. Yeni V3 skorunu görmek için gelecekte arka plan
kolektörünün gerçekten kaydettiği maç kimliğini kullanın. Kaynak yetersizse
ABSTAIN / kayıt yok açıklaması geçerlidir. Mevcut 100 maç / 20 gün planı
yeniden başlatılmaz; farklı araştırma sürümleri aynı başarı hesabında toplanmaz.

Bu sürümün işlevsel kullanım kararı, model üstünlüğü için `NO_GO` kararından
ayrıdır. Bu entegrasyon mevcut kaynak erişimi, abonelik kapsamı, oyuncu etkisi
doğrulaması veya kalibrasyon eksiklerini çözülmüş göstermez. Main merge veya
Fly.io dağıtımı bu çalışma kapsamında yapılmaz.

## Entegrasyonda yakalanan ek hata

Tam koşuya #95 ve #97'nin pytest fonksiyon testleri de katıldı. Eski unittest
keşfi bunları çalıştırmıyordu. `audit_future_forecast_origins.auto_evidence`
otomatik kontrolün bitiminden 60 saniye sonra arşivlenen bir tahmini de o
kontrol üretmiş gibi işaretleyebiliyordu. İlk geniş koşuda bu test gerçekten
başarısız oldu: `1 failed, 1782 passed in 183.75s`. Aynı cihazdan gelen
zamanlar için gerekçesiz tolerans kaldırıldı; NBA ve Avrupa kökeni yalnız
`evaluated_at <= first_archived_at <= completed_at` aralığında kabul edilir.
Bu düzeltme skor/model/arşiv değiştirmez. Avrupa için iki uç, önce ve sonra
sınırlarını denetleyen ek test yazıldı.

CI, mevcut `test*.py` keşif kapsamını koruyarak pytest üzerinden unittest ve
fonksiyon testlerini birlikte çalıştırır. `tests/faz23_odds_test.py` bağımsız
eski sağlayıcı debug scriptidir; olmayan bir modülü import eder ve import
anında canlı sorgu çağırır. Varsayılan pytest ilk denemede bu dosyayı da
toplayıp collection hatası verdi. `pytest.ini` bu kapsamı eski unittest
keşfiyle aynı yaptı; çalışan bir regresyon testi kaldırılmadı.

Yerel ilk geniş koşu ayrıca Docker VFS katmanları diski doldurduğu sırada
çalıştığı için `497 failed, 1229 passed, 57 errors` verdi; bu koşu kanıt
olarak kullanılmaz. Yalnız bu oturumun geçici test imajı ve derleme önbelleği
temizlendi; mevcut veri/volümler silinmedi. Docker'ın yerel cgroup görünümü
istenen sınırları doğrulayamadı; `--require-cgroup-limits` doğru biçimde
başarısız oldu. İkinci Docker test imajı diske sığmadı. Yerel Docker sınırlı
çalıştırması başarı diye sunulmaz; GitHub CI'da ayrı gerçek sınır denetimi var.
