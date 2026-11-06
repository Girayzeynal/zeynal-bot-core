# FAZ41 kaynak entegrasyonu

PR #18 (`eb471b8d176e180ca48a6d9febea38c7ea546aad`) ve Issue #17 üzerine, ayrı `feature/faz41-source-adapters-20261106` dalı. PR #12/#15/#16 mevcut geliştirme zinciridir; main veya üretim değişikliği yapılmaz.

## Aşama 1 — v2 kanıt sözleşmesi

Başlangıç 800/800; yeni aşama 814/814 test geçti (14 yeni deterministik test). PR #18 push 42217166313 ve PR 42217185850 için unit-tests/docker-build başarılı doğrulandı. Yerel tam test SHA-256 bilgisi `docs/evidence/faz41-v2-20261106.json` içindedir. Bu aşamanın CI sonucu exact commit SHA ile ayrıca doğrulanır.

`faz41_evidence.py`, v1 kaydını değiştirmeden model tüketimi için ayrı v2 sözleşmesi ekler. Sezon, lig, takım yönü, UTC başlangıcı ve kanonik kimlik; kaynak fixture kimliği; yayın/gözlem/ingestion/materialization zamanları; ham JSON ve SHA; veri/kullanım sınıfı ayrı tutulur. Kaynakta yayın saati yoksa `null` kalır, gözlem saati yayın saati diye gösterilmez. Haber/yorum/sakatlık iddialarında yayın saati zorunludur.

Güvenilir registry pin'i, izin kapsamı, sağlayıcının tam HTTPS alan adı/yol sınırlaması ve şirket sahipliği kontrol edilir. Aynı sahibi kullanan iki sağlayıcı adı bağımsız doğrulama sayılmaz. Çelişkiler oylamayla gerçeğe dönüştürülmez. Public API erişimi lisans/kullanım izni değildir: varsayılan tüm resmi kaynaklar **UNKNOWN**; model tüketimi kapalıdır. PERMITTED için pin'lenmiş politika, açık izin referansı ve kesitte geçerli inceleme/son geçerlilik zamanları gerekir. Yerel hash hukuki izin veya bağımsız kaynak tasdiki değildir.

Kesit materialization anından kesinlikle sonra olmalıdır. Gelecek/sırası bozuk zamanlar, eski bilgi, değiştirilmiş ham içerik, izin yükseltme, sezona/maça yanlış bağlama ve sentetik/gerçek karışması reddedilir. V1 yapısal API korunmuştur; yeni v2 tüketicisi v1'i kabul etmez.

Henüz: v2 metaveri doğrulaması tek başına ham JSON'dan iddianın doğru çıkarıldığını kanıtlamaz. Sağlayıcı bazlı semantik replay, haber bağlantılandırması ve FAZ40 bağlantısı sonraki aşamadadır. Gerçek prematch tahmin veya kalibrasyon oluşturulmadı.
