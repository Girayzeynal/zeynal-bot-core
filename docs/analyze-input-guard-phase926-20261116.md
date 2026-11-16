# FAZ 92.6 — /analyze çoklu komut ve tarih hatası ayrımı

Başlangıç: PR #89, e02be465f3d8fdcbb04233eae870fa9bb80e3b56.
Yalnız mevcut araştırma dalı; main/üretim değişmez.

## Yeniden üretilen kök neden

Kullanıcının paylaştığı sekiz `/analyze NBA 2026-11-16 ...` satırı tek
Telegram mesajı olduğunda `main.parse_analyze` yalnız ilk `vs` ayırıcısını
kullanır. İlk ev sahibi Boston Celtics olur; deplasman ise Orlando Magic
ile başlayıp sonraki yedi komutu da içerir. Bu alan 300 karakteri aşar.
`core.league_identity.normalize_name` dolayısıyla
`NONEMPTY_BOUNDED_NAME_REQUIRED` verir. Kullanıcının gerçek mesaj zarfı
Cloud'da olmadığı için sekiz satırın gerçekten tek update olarak alındığı
bağımsız doğrulanmadı; aynı metinle hata yolu otomatik testte yeniden üretildi.

Çıplak `/analyze` ise mevcut parser'da `Eksik parametre` yoludur.
`FIXTURE_LOCAL_DATE_MISMATCH` ayrı, doğru çalışan zaman korumasıdır:
kullanıcının kaynak çıktısı Boston–Orlando / ESPN 401909994 için
2026-11-17T00:00:00Z = 17 Kasım 03:00 TSİ gösteriyor.
2026-11-16 komutunu otomatik olarak 17'ye çevirmek doğru değildir.
Yeni maç öncesi tahmin koşulları hâlâ mevcut doğrulama katmanında uygulanır.

## İzole bot düzeltmesi

Yetkilendirmeden (-100) sonra ve mevcut analiz handler'ından önce (-60)
`AnalyzeInputGuard` çalışır. Bir mesajdaki birden çok `/analyze` komutu,
bot kullanıcı adı son eki dahil, tek sabit kullanım yanıtıyla durur.
Toplu model çalıştırma, tarih düzeltme, tahmin oluşturma veya arşiv yazma yoktur.
Eksik/geçersiz komut, uzun veya normalize edilemeyen takım adı açık Türkçe
yardım alır. Kullanıcı girdisi/URL veya exception metni yanıta eklenmez.
Geçerli tek komut aynı parser ve mevcut handler'a değişmeden geçer.
Tek komutun satıra bölünmüş takım adları ve yapıştırılmış tırnakları korunur.

Main parser, takım kimliği, fikstür/tarih doğrulaması, model, kalibrasyon,
eski snapshot'lar ve üretim botu değiştirilmedi. Tarih düzeltmesi gerektiğinde
`/nba 2026-11-17` listesindeki tek komutlar ayrı mesajlar olarak gönderilmelidir.

## Kanıt ve sınırlar

Yeni test modülü eski hata yolunu sekiz satırla yeniden üretir. Gerçek PTB
Application/CommandHandler zinciri, bellek içi Bot API double ile giriş
korumasının bir yanıt verdiğini, ApplicationHandlerStop'un eski handler'ı
durdurduğunu, geçerli komutun yalnız bir kez ve orijinal tarihle ulaştığını,
yetkisiz sohbetin yanıt alamadığını ve eski arşiv baytlarının değişmediğini
denetler. Bu gerçek Telegram teslimi değildir.

38 hedef test geçti (yeni giriş testleri, FAZ 84.3 tarih regresyonları ve
tırnaklı takım adı regresyonları). Tam suite/CI nihai sonuçları PR'de
exact HEAD ile raporlanır. Yeni test modülü 256 MiB / tek CPU provider
runtime kontrolüne de eklenir. Yeni sürüm gerçek Telegram E2E: BLOCKED;
Cloud test botunun token'ını veya özel sohbetini kullanmaz.

UserLAnd'da izole botu Ctrl+C ile durdurup mevcut başlatıcıyı çalıştır:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Komutları tek tek gönder. Boston–Orlando için doğru TSİ günü:

```text
/analyze NBA 2026-11-17 Boston Celtics vs Orlando Magic
```

Maç başlamışsa yeni PREMATCH üretilemez; mevcut değişmez arşiv kullanılır.
Kalibrasyon/üretim kararı değişmez: NO-GO, main merge veya deploy yok.
