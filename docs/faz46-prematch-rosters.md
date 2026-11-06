# FAZ46 — maç öncesi kaynak listesi ve ilk beş güvenliği

Başlangıç PR #24 / `2267f0525e1bb0a7c718266c8d1efcf1a0299930`. Push 42258077947 ve PR 42258088036 unit-tests/docker-build başarılı, 1016/OK. Dal: `feature/faz46-prematch-roster-evidence-20261106`; PR tabanı FAZ45 dalıdır. Üretim katsayısı, Telegram/Fly, gerçek tahmin ledger'ı ve eski kanıtlar değiştirilmez.

## Güvenlik düzeltmeleri

FAZ41 normalleştirilmiş resmî duyuru sözleşmesinin dört negatif regresyonu önce başarısız oldu: aynı sağlayıcı oyuncusunu iki takımın ilk beşine koymak; `NBA:` önekiyle bu çakışmayı gizlemek; resmî sağlayıcıyı başka lig için kullanmak; başka sezonun maç kimliğini kullanmak. `prematch_context` artık oyuncu–takım üyeliğini sağlayıcı namespace'i içinde denetler. NBA duyuru kimliği `002YY...` sezonuyla, EL/EC `E/Uyyyy_game` kimliği lig/sezonuyla eşleşir. Farklı sağlayıcı oyuncuları eşlenmiş varsayılmaz.

Bu sözleşme hâlâ açıkça normalleştirilmiş duyurudur; gerçek NBA/EL ilk beş endpoint'inin varlığı veya erişimi iddia edilmez. FAZ46 kaynak listesi bu sözleşmeye otomatik dönüştürülmez. Ham kaynak listesine OFFICIAL_LINEUP türü veya ilk beş ekleyip hash yeniden hesaplamak replay kapısını aşamaz.

## Yeni kaynak-listesi katmanı

`faz46_rosters.py`, gerçek EL/EC game/stats DTO alanlarını kullanır: doğrulanmış UNPLAYED maç, UTC, takım, lig/sezon ve oyuncu kimlikleri. Liste boşsa `ABSTAIN_ROSTER_NOT_PUBLISHED`; `team=None` ve boş oyuncu listesi hata veya uydurma kadro üretmez. Liste varsa yalnızca `ROSTER / SOURCE_LISTED_UNCONFIRMED` gözlemi oluşur. `starting_five`, `active_for_target`, sakatlık ve rotasyon alanları `None` kalır. `startFive` veya `active` alanları tek başına resmî ilk beş ilanı sayılmaz.

ESPN pregame header kimliği/zamanı doğrulanır; yayımlanmamış kadro, bilinmeyen roster şeması ve tarihsel boxscore oyuncuları ayrı ABSTAIN nedenleridir. Tarihsel boxscore ilk beşi gelecekteki ilk beşe çevrilmez. NBA resmî CDN erişimi ayrı denetlenir; schedule 200 dönse bile bu kadro kanıtı değildir.

Kayıt anı ve kaynak gözlemi maçtan önce olmalı. Gelecek kaynak zamanı, eski takvim, yanlış endpoint/maç/UTC/takım/sezon, oynanmış skor/dakika, çift oyuncu kimliği ve capture sırasında tipoff aşımı reddedilir. İlk takım bellekte işlense de ikinci takım işlenirken pencere kapanırsa çağırana kısmi liste dönmez; gerçek veritabanına yazılmaz. Özgün pregame gözlem maçtan sonra kendi eski cutoff'unda salt okunur replay edilebilir.

Mevcut FAZ41 `prematch_context` yeni replay adapter'ını kullanır. İzinli sentetik pozitif durumda `unconfirmed_source_rosters` ayrı alandadır; `rosters` doğrulanmış ilk beş sözleşmesine ayrılmış kalır ve HOME/AWAY_CONFIRMED_LINEUP eksikleri silinmez. UNKNOWN kaynak izni model bağlamına giremez. Mevcut sayısal model veya katsayılar bu listelerle otomatik değiştirilmez.

## Toplama ve manifest

`faz46_collection.py --live`, en fazla üç ESPN takvim günü, EL/EC katalogları, NBA resmî takvim erişimi ve her ligde ilk uygun karşılaşmanın kadro kaynağını denetler: en fazla 9 bounded public GET, otomatik retry yok. Varsayılan 0 ağ isteği. Belgeler arası sağlayıcı kimliği ve aynı takım/başlangıç saati çakışmasında keşif bütünüyle reddedilir.

Yerel rapor dışarıdan trusted payload SHA ve registry pin'iyle doğrulanır. Transport receipt'i manifestte bulunmalı; completed status, kaynak URL, sağlayıcı, gözlem zamanı ve kompakt kaynak hash'i eşleşmelidir. **Kadro yok** iddiası bile yalnızca hash'li metadata değildir: kompakt kaynak belgesi saklanır ve sıfır gözlem durumu yeniden türetilir. Boş kaynağın audit zamanı tipoff'u veya manifest saatini aşamaz. Yerel hash sağlayıcı imzası veya bağımsız zaman attestasyonu değildir.

FAZ44'ün 0600, fsync, exclusive-link ve dizin fsync atomik yayın mekanizması korunur; yalnızca yeni format/prefix whitelist'e eklenir. Aynı artefact tekrar yayımlanmaz, farklı içerik üzerine yazılmaz. Sadece `/tmp` ve `/workspace/scratch` kullanılabilir. Harici depolama, gerçek scheduler ve gerçek prediction ledger etkinleştirilmez.

```bash
python -m faz46_collection --live \
  --output /workspace/scratch/faz46-prematch-session.json
```

İsteğe bağlı gerçekten incelenmiş politika `--source-policy` ve `--trusted-policy-sha256` çiftiyle yüklenir; default UNKNOWN değiştirilmez. Haber RSS/API izni yapılandırılmadığından haber/yorum kanıtı üretilmez. Gerçek DTO listesi bulunması kullanım izni değildir.

## Denetim ve devam

İlk kaynak incelemesi 7 public istek yaptı: NBA CDN HTTP_403; ESPN 401909287 header'ında roster/ilk beş yok; E2026_100 ve U2026_104 stats listeleri boş. Bunlar doğrulanmış kadro veya başarılı NBA resmî çapraz kontrol olarak gösterilmez. Bu ilk inceleme geliştirme öncesidir; yeni CLI'nin gerçek çalışma sonucu ayrıca zaman/hash ile raporlanır.

İlk tam regresyon 1046/1046 geçti. Ardından sıfır gözlem/boş kadro iddiasını da replay edilebilir ham kanıta bağlayan üç ek test eklendi. Son odaklı grup FAZ41 uyumluluk testleri dahil 43/43. Geliştirme sırasında test fixture clock referansı ve yeni erken-ret kontrolünün beklenen nedeni düzeltildi; güvenlik kapısı gevşetilmedi. Son tam regresyon, code SHA ve exact-SHA CI ayrı kanıt/checkpoint'te verilir.

Gerçek ilk beşler, sakatlıklar, izinli haber, oyuncu değişikliği rolleri, eğitim/kalibrasyon ve bağımsız Cloud kalıcılığı açık bağımlılıklar. Bu aşama kaynak ve güvenlik bağlantısıdır; model üstünlüğü veya üretime hazır sistem iddiası değildir. Master kapsamı tamamlanmış değildir. PR taslak kalır; main merge veya production deploy yapılmaz.

Kod checkpoint son yerel sonuç: **1049/1049**, 33 yeni test, başarısızlık 0; odaklı grup 43/43. Kanıt `docs/evidence/faz46-tests-20261106.json`.

## Gerçek CLI checkpoint'i

Kod SHA `62ed7e0f47a058575e4d3ccb6b09db8cda2e375a`: [push 42261846662](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42261846662) ve [PR 42261984718](https://github.com/Girayzeynal/zeynal-bot-core/actions/runs/42261984718) unit-tests/docker-build başarılı; iki unit log 1049/OK. PR #25 taslak ve FAZ45 dalına bağlıdır.

Yeni CLI 2026-11-06 17:27:52–54 UTC'de (20:27:52–54 TSİ) **9 public GET** yaptı. NBA resmî schedule HTTP_403. Üç fixture için hem kadro gözlemi hem doğrulanmış ilk beş hem yeni tahmin kaydı **0**:

| Lig / sağlayıcı ID | Kaynaktaki UTC başlangıç | Endpoint audit sonucu |
|---|---|---|
| NBA / 401909287 | 2026-11-07 00:00 | ABSTAIN_ROSTER_NOT_PUBLISHED |
| EuroLeague / E2026_100 | 2026-11-06 19:15 | ABSTAIN_ROSTER_NOT_PUBLISHED |
| EuroCup / U2026_104 | 2026-11-10 17:00 | ABSTAIN_ROSTER_NOT_PUBLISHED |

ESPN compact header'da roster ve boxscore-player alanları yok; EL/EC iki takımın oyuncu listeleri boş. Üç **kadro yayımlanmamış** sonucu saklanan kompakt kaynaklardan salt okunur `read_audit` ile tekrar türetildi. NBA resmî erişim 403 olduğundan bağımsız NBA.com/ESPN çapraz onayı yapılmış sayılmaz. Haber/yorum kaynağı izni yok; kaynaklar UNKNOWN kalır. Bu sonuçlar model doğruluğu veya kalibrasyon değildir.

Audit payload SHA `b95295ae3df980dda74b287fd87eb34a1930fe22ffb205e1d351e4ed46e9a768`. Aynı artefact'ın tekrar yayını `created=False`; dosya hash'i değişmedi. Önceki **80 kanıt dosyası byte düzeyinde aynı**; FAZ45 yardımcı veri artefact'ı değişmedi. Araştırma SQLite integrity_check salt okunur `ok`, SHA `43adc6de12bc065e38b666dad8ba2cd9a48c5786c1185b396de5a37ebe4dd002`. Kaynak URL/receipt/zaman/fixture/digest ve bütünlük metadatası `docs/evidence/faz46-real-source-audit-20261106.json` içinde; ham sağlayıcı body'leri ve yerel audit artefact'ı harici storage'a/GitHub'a yüklenmedi.

Yerel dosya kalıcı harici yedek değildir; bağımsız ikinci Cloud runtime kurtarması doğrulanmadı. Gerçek toplama orijinal kod SHA'sı ve zamanlarıyla korunur; sonraki dokümantasyon commit'iyle yapılmış gibi yeniden etiketlenmez. Sonraki iş: izinli ve kaynak zamanı doğrulanabilir gerçek prematch kadro/ilk beş kaynağı bulmak, kaynakta bulunmayan alanları geçmiş maç kadrosundan doldurmamak. Bu gerçekleşmeden doğrulanmış lineup veya üretime hazır analiz iddiası yok. Günlük scheduler/harici storage ve üretim aktivasyonu ayrı yetki gerektirir; etkinleştirilmedi.
