# FAZ47 — sağlayıcı kapsamlı ilk beş kimlik kontrolü

Bu değişiklik, `8291fa4f5d5d4ad1b52b8df2dd0627e726581521` incelemesindeki ilk engeli kapatır. PR #12'deki FAZ39 modülü **entegre edilmedi**. Yalnızca mevcut FAZ41/46 normalleştirilmiş duyuru ve kadro bağlama sınırı düzeltildi; FAZ13/FAZ28 katsayıları, kaynak izinleri ve zamanlama değiştirilmedi.

## Sorun ve düzeltme

Eski sözleşme aynı takımın kadrosunda `1` ve `NBA:1` değerlerini ayrı oyuncular olarak kabul edebiliyordu. Çapraz takım kontrolü ise sağlayıcı önekini zaten çözümlüyordu. Böylece aynı kimliğin aynı takımda iki kez ilk beşe girmesi engellenmiyordu.

Yeni ortak karşılaştırma anahtarı `(doğrulanmış sağlayıcı, oyuncu kimliği)` biçimindedir. Yalnızca bağlı sağlayıcının tam öneki bir kez kaldırılır. Yabancı, boş veya tekrarlanmış önekler, whitespace ve izin verilen ASCII kimlik sözleşmesi dışındaki değerler `CANONICAL_PLAYER_IDS_REQUIRED` ile reddedilir. Gövde sözleşmesi `[A-Za-z0-9_-]{1,64}`; bu bir oyuncunun gerçekten var olduğunu kanıtlamaz, yalnızca belirsiz yerel kimlik biçimlerinin kabulünü engeller. Kaynak ve gerçek kadro kanıtı ayrıca zorunludur.

Kadronun veya ilk beşin kendi içinde aynı kanonik anahtar iki kez varsa `ANNOUNCEMENT_PLAYER_ID_CONFLICT`, farklı takımlarda varsa mevcut `CROSS_TEAM_PLAYER_ID_CONFLICT` reddi kullanılır. Kontrol hem ilk beşteki hem yedek listedeki alias tekrarlarını kapsar. Geçerli payload, oyuncu sırası, kaynak metni veya geçmiş kayıtlar normalize edilip yeniden yazılmaz. İlk beşin özgün kadro listesine birebir üyelik koşulu da korunur; çelişkili iddialar sessizce onarılmaz.

NBA, EuroLeague ve EuroCup için sentetik testler eklendi. EL/EC ham endpoint listing adaptörü değiştirilmedi; unconfirmed listeler resmî veya muhtemel ilk beş sayılmaz. Kayıt kaynağı/fixture/lig/sezon/izin ve observed–ingested–materialized–cutoff kontrolleri mevcut kapıda kalır.

## Kanıt ve test ayrımı

Yeni sekiz test, düzeltme öncesinde 13 test metodu çalıştırıldığında **17 alt senaryo assertion hatası** üretti; beklenen retler gerçekleşmiyordu. Bu sayı 17 ayrı test metodu veya gerçek maç değildir. Düzeltmeden sonra ilgili FAZ46/41/47 grubu **80/80**, tam regresyon **1086/1086** geçti. Test komutları ve log hash'leri eşlik eden [kanıt kaydındadır](evidence/faz47-canonical-lineup-guard-20261107.json). Exact-SHA push/PR CI sonuçları commit sonrasında PR #26 üzerinden doğrulanır; yerel başarı CI sonucu olarak sunulmaz.

Önceki [inceleme raporu](faz47-lineup-safe-review.md), kanıt JSON'u ve pin'li inceleme aracı tarihsel checkpoint olarak korunur. Eski araç kaynak dosyalarının eski SHA-256 değerlerini gerektirir; bu düzeltmeden sonra mevcut ağaçta `REFUSED_CURRENT_REVIEW_BASELINE_CHANGED` vermesi tasarlanan davranıştır. Eski rapordaki 8/9 sonucu yeni sürümün sonucuymuş gibi güncellenmez. Bu değişiklik için ölçüm, yeni deterministik regresyonlar ve tam CI'dır.

## Kalan sınırlar

- FAZ39 DTO'su uygulamaya alınmadı. Sonraki aday adaptör yalnızca FAZ46 otoritesinin arkasında, ayrı değişiklik olarak değerlendirilmelidir.
- Muhtemel ilk beş için izinli, zamanlı gerçek kaynak adaptörü hâlâ yok; eksik veri ABSTAIN/UNAVAILABLE kalır.
- Kanonik biçim kontrolü sağlayıcının gerçek oyuncu sicilini, üyeliği, sakatlığı veya rotasyonu doğrulamış sayılmaz. Yeni sağlayıcı kimlik biçimi desteklenmeden önce açık adapter sözleşmesi gerekir; bilinmeyen biçimler fail-closed reddedilir.
- Bu tur gerçek basketbol veri isteği, yeni prospektif kayıt, model eğitimi veya kalibrasyon yapmadı. Korunan gerçek hazır oluş raporunda eşleşmiş tahmin–sonuç çifti **0**, kalibrasyon **NOT_ESTABLISHED**.
- Yerel hash koruması bağımsız Cloud kalıcılık deneyi değildir. Harici kalıcı depolama ve bağımsız ikinci Cloud kurtarması doğrulanmış değildir.
- PR taslak kalır; main merge, Fly.io/Telegram production, scheduler, secret ve dış veri yükleme işlemi yoktur.
