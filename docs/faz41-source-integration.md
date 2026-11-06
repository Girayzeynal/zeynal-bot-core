# FAZ41 kaynak entegrasyonu

PR #18 (`eb471b8d176e180ca48a6d9febea38c7ea546aad`) ve Issue #17 üzerine, ayrı `feature/faz41-source-adapters-20261106` dalı. PR #12/#15/#16 mevcut geliştirme zinciridir; main veya üretim değişikliği yapılmaz.

## Aşama 1 — v2 kanıt sözleşmesi

Başlangıç 800/800; yeni aşama 814/814 test geçti (14 yeni deterministik test). PR #18 push 42217166313 ve PR 42217185850 için unit-tests/docker-build başarılı doğrulandı. Yerel tam test SHA-256 bilgisi `docs/evidence/faz41-v2-20261106.json` içindedir. Bu aşamanın CI sonucu exact commit SHA ile ayrıca doğrulanır.

`faz41_evidence.py`, v1 kaydını değiştirmeden model tüketimi için ayrı v2 sözleşmesi ekler. Sezon, lig, takım yönü, UTC başlangıcı ve kanonik kimlik; kaynak fixture kimliği; yayın/gözlem/ingestion/materialization zamanları; ham JSON ve SHA; veri/kullanım sınıfı ayrı tutulur. Kaynakta yayın saati yoksa `null` kalır, gözlem saati yayın saati diye gösterilmez. Haber/yorum/sakatlık iddialarında yayın saati zorunludur.

Güvenilir registry pin'i, izin kapsamı, sağlayıcının tam HTTPS alan adı/yol sınırlaması ve şirket sahipliği kontrol edilir. Aynı sahibi kullanan iki sağlayıcı adı bağımsız doğrulama sayılmaz. Çelişkiler oylamayla gerçeğe dönüştürülmez. Public API erişimi lisans/kullanım izni değildir: varsayılan tüm resmi kaynaklar **UNKNOWN**; model tüketimi kapalıdır. PERMITTED için pin'lenmiş politika, açık izin referansı ve kesitte geçerli inceleme/son geçerlilik zamanları gerekir. Yerel hash hukuki izin veya bağımsız kaynak tasdiki değildir.

Kesit materialization anından kesinlikle sonra olmalıdır. Gelecek/sırası bozuk zamanlar, eski bilgi, değiştirilmiş ham içerik, izin yükseltme, sezona/maça yanlış bağlama ve sentetik/gerçek karışması reddedilir. V1 yapısal API korunmuştur; yeni v2 tüketicisi v1'i kabul etmez.

Henüz: v2 metaveri doğrulaması tek başına ham JSON'dan iddianın doğru çıkarıldığını kanıtlamaz. Sağlayıcı bazlı semantik replay, haber bağlantılandırması ve FAZ40 bağlantısı sonraki aşamadadır. Gerçek prematch tahmin veya kalibrasyon oluşturulmadı.

## Aşama 2 — sağlayıcı replay, tarihsel dakikalar ve FAZ40 bağlantısı

`faz41_adapters.py`, mevcut ESPN NBA ve EuroLeague/EuroCup dönem ayrıştırıcılarını tekrar kullanır. NBA CDN box-score için ayrı bir sözleşme; açık NBA takım ID → ESPN kanonik takım ID dizini ve tam UTC başlangıç eşleştirmesi eklenir. NBA.com yanıtındaki final durumu, regular-season GameID/sezon, takım yönü, çeyrek toplamları ve uzatma öncesi beraberlik denetlenir. Aynı maçın farklı sağlayıcı fixture kimlikleri aynı kanonik kimliğe bağlanır. İddialar ham JSON'dan yeniden çıkarılır; yeniden hash'lenmiş skor/id/URL değişiklikleri de reddedilir. Yerel hash bağımsız kaynak tasdiki değildir. NBA adaptörünün gerçek yanıt şeması bu oturumda doğrulanamadı: aşağıdaki 403 engeli geçerlidir.

ESPN oyuncu dakika/puanları takım ve maç süresiyle uzlaştırılır; dakika gösterim hassasiyeti korunur. `33` dakikayı kesin 33:00 oynama süresi olarak sunmaz. ESPN oyuncu ID'leri NBA personId değerleriyle eşit varsayılmaz. EuroLeague/EuroCup oyuncu `timePlayed` alanı saniyedir; API integral float (`341.0`) gönderir. İlk smoke'daki ret bu tip farkından kaynaklandı, regresyonla yeniden üretildi ve düzeltildi. Kesirli sayımlar, boolean, negatif ve NaN reddedilir. Oyuncu toplam süre/puanları takım sonucu ve maç süresiyle uzlaştırılır. Hiçbir tarihsel box-score, gelecek maçın kadrosu veya rotasyonu olarak kullanılmaz.

`faz41_news.py` yalnızca açıkça PERMITTED ve pin'lenmiş RSS/API politikasıyla kullanılabilir. Yayın saati, kaynağa/maça açıkça pin'lenmiş tekil bağlantı ve içerik replay zorunludur. Otomatik NLP ile sakatlık/ilk beş doğrulanmaz; yorum COMMENTARY ve UNVERIFIED_SOURCE_CLAIM kalır. XML entity/DOCTYPE, belirsiz eşleştirme, eski/gelecek yayın ve değiştirilmiş başlık reddedilir. İzinli gerçek haber/yorum feed'i yapılandırılmadığı için canlı haber toplanmadı. Bu aşama genel amaçlı web tarayıcı veya çoklu haber doğruluk modeli değildir.

`faz41_faz40.py`, açık `EXPLICIT_TEAM_ANNOUNCEMENT_V1` sözleşmesini eski FAZ40 roster gate'ine bağlar. Bu normalize sözleşme gerçek bir NBA/EuroLeague prematch endpoint'inin var olduğu iddiası değildir. Maç öncesi kaynak/yayın/materialization, kullanım izni, beş benzersiz oyuncu ve takım yönü doğrulanır. Çelişkili duyurular reddedilir; tekrar kayıt bağlamın hash'ini değiştirmez. Tarihsel dakika özellikleri ayrı kesitte, kanonik tekilleştirme ve takım-başlangıç çakışma kontrolüyle hazırlanabilir. `research_with_context` referans FAZ40 araştırma çıktısını değiştirmeden kaynak bağlamına bağlar; hiçbir yeni üretim katsayısı veya kalibre edilmiş düzeltme uygulanmaz.

Prospektif etiketleme için iki ayrı kontrol eklendi: kayıt oluşturulurken gerçekten başlangıç öncesinde olmak ve sonradan replay yapılırken özgün materialization saatini kullanmak. Maç başladıktan sonra yeni kanıtı geçmişe dönük prematch etiketlemek reddedilir; gerçekten önceden kaydedilmiş kanıtın daha sonra denetlenmesi engellenmez. İki davranış da önce başarısız regresyonlarla yeniden üretildi.

## Canlı erişim deneyi ve sınırlar

Opt-in `python -m faz41_source_smoke --live`; varsayılan çalıştırma ağa bağlanmaz. Salt okunur, en fazla 8 saniye istek zaman aşımı, 4 MB yanıt sınırı, izinli kaynak/yol, yönlendirme reddi; 403/429/bağlantı ve içerik hataları ayrı durumlarda raporlanır. Otomatik retry, zamanlayıcı veya ledger yazımı yoktur. Retry-After yalnızca kaydedilir. HTTP Date farkı tanı bilgisidir; güvenilir bağımsız UTC tasdiki değildir. Canlı test, sentetik unittest başarısından ayrı tutulur.

| Kaynak | Canlı erişim | Yapısal sonuç | Model tüketimi |
|---|---|---|---|
| ESPN 401909922 | HTTP 200 | Final/periyot ve oyuncu dakika/puan alanları ayrıştırıldı | UNKNOWN izin nedeniyle kapalı |
| EuroLeague E2026_87 + stats | İki endpoint HTTP 200 | Final/periyot ve oyuncu saniye/puan toplamları uzlaştırıldı | UNKNOWN izin nedeniyle kapalı |
| EuroCup U2026_91 + stats | İki endpoint HTTP 200 | Final/periyot ve oyuncu saniye/puan toplamları uzlaştırıldı | UNKNOWN izin nedeniyle kapalı |
| NBA CDN sezon takvimi | HTTP 403 | Veri alınamadı | Kapalı; ESPN ile gerçek bağımsız çapraz doğrulama yapılamadı |
| Haber/yorum | Çalıştırılmadı | Açık izinli kaynak yapılandırılmadı | Kapalı |
| Gerçek prematch ilk beş/rotasyon | Kayıt yok | Yalnızca sentetik sözleşme/kapı testleri | Eksik |

Bunlar üç tarihsel maçın yeni gözlemleridir. Yeni gerçek prospektif tahmin sayısı **0**; eğitim örneklemi veya kalibrasyon başarısı diye sayılmaz. Başlangıçta bildirilen 75 NBA / 2 EuroLeague / 2 EuroCup arşivinin kapsamı bu smoke ile yeniden ölçülmedi. Özgün FAZ24/FAZ29 kayıtlarına veya araştırma SQLite dosyasına yazılmadı.

## Test kanıtı, açık riskler ve sonraki aşama

Son yerel tam regresyon: **851 geçti, 0 başarısız**, PR #18 başlangıcına göre 51 yeni test. Odaklı FAZ41 grubu: eski 12 dahil **63 geçti**. İlk aşama `df8abe47f0ea1e56f7bba70b410089d28be111cc` için push 42218340679 ve PR 42218397532 unit-tests/docker-build başarılı. İkinci aşama commit'inin exact SHA CI durumu PR #19 üzerinde ayrıca doğrulanır; commit öncesi başarı varsayılmaz.

Kaynak sözleşmesi testleri sentetik; HTTP 200 ve yerel toplam uzlaşması bağımsız gerçeklik, kullanım izni, takımın gelecek kadrosu veya model doğruluğu kanıtı değildir. NBA.com 403 nedeniyle gerçek çok sağlayıcılı final mutabakatı henüz yoktur. Oyuncu takım üyeliği yalnızca kaynak box-score bloğuna bağlıdır; bağımsız resmi kadro tarihi sağlanmadı. Dakika toplamları beşli stintlerini/rotasyon etkisini kanıtlamaz. İzinli haber kaynakları, gerçek resmi prematch duyuruları, oyuncu ID crosswalk'ı ve gerçek play-by-play/rotasyon verisi sonraki aşamanın blokajlarıdır.

Ham yanıtlar Git'e veya harici depolamaya yüklenmedi. Canlı rapor kaynak URL/zaman/hash, alan kapsamı ve ret nedenlerini içerir; yeni bir bağımsız arşiv tasdiki değildir. Scratch verilerinin yeni Cloud oturumunda kalıcılığı doğrulanmadı. API rate-limit ve kullanım koşulları sağlayıcı tarafından teyit edilmedi; 429/Retry-After davranışı sentetik testle sınırlıdır. Üretime hazır veya kalibre edilmiş model iddiası yoktur.
