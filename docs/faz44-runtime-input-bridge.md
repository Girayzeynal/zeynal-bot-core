# FAZ44 — çalışan model kanıtı ve geliştirme veri bağlantısı

Başlangıç PR #22 / `e195fcccb4a9bb0c8eab3eefa99d486a3d5e91a3`; push 42246126702 ve PR 42246136747 unit-tests/docker-build başarılı doğrulandı. Mevcut modeller, araştırma/prospektif kayıtlar ve FAZ13–43 kanıtları korunur. Yeni dal `feature/faz44-runtime-input-bridge-20261106`.

## Aşama 1 — model yürütme ve son gönderim kontrolleri

Dört yeni negatif regresyon eski davranışta başarısız oldu:

- Non-synthetic snapshot, yalnızca biçimi geçerli olan uydurma Git/model manifest'iyle sayısal çıktı üretebiliyordu.
- Kayıttan sonra servisin DEVELOPMENT modu değiştiğinde callback cevap verebiliyordu.
- Sentetik mod kapatıldıktan sonra cache'deki sentetik snapshot kullanılabiliyordu.
- Takvim capture anında taze olsa da teslim anında 300 saniyelik sınırı aşabiliyordu.

Non-synthetic sayısal çıktı için artık çalışan temiz feature HEAD'i, commit zamanı ve tüm model modülü SHA'ları hesap öncesinde ve sonrasında eşleşmelidir. Sonradan eski snapshot denetlenirken bugünün koduna yeniden bağlanmaz; orijinal kayıt/tahmin değiştirilmez. Kaynak izni yoksa önceki izin kapısı ABSTAIN vermeye devam eder; bu özellik kullanım izni veya CI/provider attestation üretmez.

Son gönderimde uygulama ve servis modu, sentetik kullanım izni, kaynak kullanım izni/expiry, UTC saatinin snapshot'tan geriye gitmemesi, maç başlangıcı, cutoff ve takvim tazeliği denetlenir. Maç başladıysa ALREADY_STARTED ret nedeni, diğer eskime nedenlerinden önce gelir. Bu öncelik değişikliğini eski regresyon yakaladı; ret kontrolleri gevşetilmeden düzeltildi.

Başlangıç 946/946. Son yerel tam regresyon **954/954**, bu aşamada **8 yeni test**; ilgili odaklı grup 53/53. İlk dört negatif test önce başarısız oldu; orijinal snapshot'ların daha sonra okunabilmesi ayrıca test edildi. Pozitif sahte kaynak/izin/model senaryoları yalnızca açıkça etiketli sentetik testlerdir. Gerçek sayısal tahmin veya prospektif kayıt 0; kaynak politikaları UNKNOWN kalır.

Kanıt: docs/evidence/faz44-runtime-20261106.json. Her yeni commit için exact SHA push ve PR CI ayrıca doğrulanır. Main merge, Fly.io/Telegram production, secret/ücretli kaynak veya gerçek scheduler/storage etkinleştirme yok.
