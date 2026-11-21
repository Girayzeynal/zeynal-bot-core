# FAZ 92.7 — İzole NBA güncel kadro gözlemleri

Başlangıç: PR #89 / 070b2b51bbf60393f19e86508bbb58113d6800d7.
Mevcut araştırma dalı; main/Fly/secret/disk/kalıcı tahminler değiştirilmez.

## Kök eksik ve bağlanan akış

Eski ekran yalnız `verified_roster_packets` deposunu okuyordu. Normal başlatma
bu depoyu doldurmuyordu. Yeni akış bu depoyu sonradan gelen bilgilerle doldurmaz:
ilk tahmin anındaki kanıt ile güncel kaynak gözlemi ayrı bölümlerdir.

Canlı NBA premium analizinin Kadro / Sakatlık düğmesi, yetkili sohbet ve rapor
token'ı denetiminden sonra güncel incelemeyi başlatır. Ana /analyze sırasında
ek kaynak çağrısı yoktur. Sayfa değiştirme kaynak sorgulamaz. Aynı gözlem 5 dk
önbelleklidir; geçerlilik en eski kaynak erişimine ve maç başlangıcına bağlıdır.
Maç başladıktan sonra yeni güncel kayıt eski PREMATCH verisi gibi toplanmaz.
İstek sırasında maç başlarsa oyuncu gözlemleri yayımlanmaz.

Kaynaklar:

- ESPN event summary: tam event ID, ev/deplasman provider ID/adları, sezon ve
  başlangıç UTC saati eşleşmelidir. Sadece açık STATUS_SCHEDULED kabul edilir.
- Resmî NBA sezon rapor sayfasından gerçekten yayımlanmış PDF bağlantısı seçilir.
  URL/saat tahmini yapılmaz. Gelecek ve 6 saatten eski raporlar seçilmez.
- NBA PDF metni mevcut ayrıştırıcıyla ayrı, CPU/bellek sınırlandırılmış işlemde
  okunur. Metin ayrıştırılması bağımsız oyuncu durumu doğrulaması değildir.
- NBA satırında gün, sıralı matchup, takım ve rapor saati kontrol edilir.
  07:00(ET) gibi AM/PM içermeyen saatlerin kısıtı ekranda açıkça belirtilir;
  bunlar aynı kesin UTC başlangıç saati kanıtı olarak gösterilmez.
- Oyuncu kimliği ESPN'in doğru takım/sezon roster'ıyla yalnız tam ad eşleşmesi
  üzerinden bağlanır. Bulanık isim eşleştirmesi, sahte ID veya eksik roster'dan
  oyuncu uydurma yoktur. Eşleşmeyen satır ham rapor olarak açıkça işaretlenir.

Kaynak durumu uyuşmazlıkları iki kaynakla birlikte görünür; kazanan kaynak
seçilmez. Eski ESPN durum güncellemesinin tarihi gösterilir ve 24 saatten eski
kayıt bugünkü oynama onayı sayılmaz. Out otomatik olarak tıbbi sakatlık sayılmaz;
ceza yalnız kaynak açıkça suspension/suspended bildiriyorsa etiketlenir.
Boş liste, raporun sunulmaması veya ağ hatası asla tam kadro/ceza yokluğu demek değildir.

## Değişmezlik, kaynak ve bütçe

Güncel kayıt ayrı `current-roster` dizinine içerik hash'i ile eklenir. Kaynak
baytları ve SHA, gerçek erişim saatleri, ilk snapshot SHA/model digest,
tahmin saati ve güncel inceleme saati izlenir. Eski ledger, snapshot, skor,
olasılıklar veya fit değiştirilmez. Model dakika/oyuncu etkisi uygulamaz.
Kalibrasyon ve güven endeksi eklenmez. Kaynak gözlemi bağımsız tıbbi veya
disiplin uygunluğu sertifikası olarak sunulmaz.

Yalnız sabit, ücretsiz HTTPS kaynakları; redirect, credential URL, kontrolsüz
body, tekrar denemeler veya ücretli API çağrısı yoktur. Kaynak cache 8 MiB/16
belge, review cache 32 giriş, tek eşzamanlı inceleme; HTTP/429 cooldown vardır.
PDF child: 128 MiB adres alanı, 4 CPU saniyesi, 6 sn subprocess timeout.
Ana handler 20 sn bekler; geç kalan işlem başka eşzamanlı inceleme başlatmaz.
Telegram uzun metni aynı mesajda sayfalar. Eskiyen/maç sonrası sayfalar arşivdir.

## Gerçek kaynak denemesi ve test sınırları

16 Kasım 2026'da ücretsiz kamu kaynaklarına gerçek HTTP erişimi yapıldı:

- Boston–Orlando 401909994: 4 ESPN oyuncu durum kaydı; seçilen NBA raporunda
  bu maça ait ayrıştırılabilir satır yok. Bu, sakat oyuncu yok demek değildir.
- Cleveland–Chicago 401909995: 8 ESPN + 7 NBA rapor satırı. Bir NBA satırının
  oyuncu ID'si eşleşmedi; bu durum gizlenmedi. İki kaynak satır sayıları benzersiz
  sakat oyuncu sayısı veya kesinleşmiş maç kadrosu değildir.
- Yerel gerçek PDF worker peak RSS: yaklaşık 38,85 MiB. Bu tek worker ölçümüdür;
  tek başına birleşik Telegram belleği kanıtı değildir.

Yeni paket: `docs/evidence/roster-phase927-native-20261116.tar.gz`,
SHA-256 `3cec9af4bf16a1884e26851a6ddc0a973fdd9309bea7500d16b21c29c89191b3`.
Yalnız kamu kaynak belgeleri ve gözlem denemesi içerir; tahmin/üretim saati
uydurulmadı. Probe prediction time ve original snapshot SHA alanları null'dır.
Yeni PREMATCH tahmini yoktur. Bu paket bağımsız medical verification veya
gerçek Telegram E2E kanıtı değildir.

Kaynak hatası, hash/saat/sezon/kimlik uyuşmazlığı, snapshot değişmezliği,
cache, ceza etiketi, belirsiz oyuncu ID'si, kaynak çatışması, Telegram yetki/
timeout/sayfalama ve maç başlangıcı sınırları test edilir. Native paket testleri
internet olmadan aynı belgeleri yeniden oynatır; opsiyonel PDF kütüphanesi
kuruluysa gerçek child çalışır, yoksa açık eksik bağımlılık yolu doğrulanır.
Üretim Dockerfile/requirements değişmeden ayrı Dockerfile.injury-research CI
imajında gerçek PDF child + PTB testleri 256 MiB / tek CPU altında çalıştırılır.
Son exact-HEAD CI sayıları PR'de raporlanır. Gerçek yeni-head Telegram E2E: BLOCKED.

## UserLAnd

Tek terminalde çalışan izole botu Ctrl+C ile durdur. PDF ayrıştırıcısını da
yalnız izole venv'e kurup botu başlatmak için bir kez:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --roster-setup
```

Sonraki açılışlarda normal başlatıcı yeterlidir. Opsiyonel kurulum yapılamazsa
normal başlatıcı ESPN gözlemlerini ve eksik PDF doğrulamasını gösterebilir.
Telegram'da doğru tarihli tek /analyze komutu ardından Kadro / Sakatlık düğmesi.
İlk tahmin skorunun değişmesi beklenmez. EUROLeague/EuroCup güncel sakatlık/
ceza hattı henüz bağlı değildir; mevcut replay desteği korunur.

Üretim/model kararı NO-GO sürer. Sakatlık ekranının doldurulması doğruluk,
kalibrasyon veya bahis avantajı artışı kanıtı değildir.
