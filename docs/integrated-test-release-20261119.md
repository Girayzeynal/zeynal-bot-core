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
