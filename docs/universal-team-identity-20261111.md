# Evrensel takım kimliği: ilk doğrulanmış geliştirme aşaması

Bu aşama bütün liglerde çalışan bir tahmin sistemi teslim etmez. Ortak kimlik sözleşmesini,
üç sezon katılımcı adaptörünü, lig bazında yönlendirmeyi ve güvenli ret davranışını ekler.
Üretim botu çalıştırılmadı; `/data` açılmadı; eski tahminler veya model katsayıları değiştirilmedi.

## Korunan checkpoint ve bağımlılıklar

- Main: `0e634083ccd1da87c7313710a17aa6e63fb5abe2`.
- PR #79: `c847b04da89fa14d8771fa544daf44f7ac5852a7`, açık taslak.
- PR #80: `542cec080fda7ef0b05ebe14a269f78ca9b34325`, açık taslak; geliştirme başlangıcı.
- Yeni dal: `dev/universal-team-identity-20261111`; yeni PR, #80 dalını hedefler.
- Bağımlılık sırası: #79 → #80 → bu aşama. Birleştirme yapılmadı, yetkilendirilmedi.

UserLAnd'deki `origin/dev/...` hatasının nedeni yalnızca main'i getiren fetch refspec'iydi.
Kullanıcının ekran çıktıları iki uzak referansın oluştuğunu, normal fetch ile #80'in
`542cec0`'a ilerlediğini ve değiştirilmiş `fly.toml` hash'inin korunduğunu gösterdi:
`218f33c6aa9032ae2ad73ccafa9dfc213ddd27e23d9d98df914aff5a8b600b73`.
Telefonun dosya sistemi bu Cloud ortamına bağlı değil.
`/home/userland/zeynal-review-542cec0` inceleme ağacındaki arşiv komutu yalnızca dry-run
olarak doğrulandı. Önerilen `--live` çalıştırmanın kullanıcı çıktısı hâlâ bekleniyor;
bu görev o sonucu tamamlanmış saymaz.

## Kök neden ve yapılan değişiklik

`main.py` bütün ligler için aynı ESPN geçmişi bootstrapper'ını çağırıyordu.
EuroLeague/EuroCup'a özel sezon katılımcısı ve sağlayıcı kapısı yoktu; bu yüzden
kimlik, sağlayıcı erişimi ve gerçekten eksik geçmiş aynı `missing` mesajına dönüşebiliyordu.
Kullanılmayan iki takımlık eski NBA kimlik tablosu da genel bir kayıt sistemi değildi.

- `core/league_identity.py`: yapılandırılmış ligler ve açık sağlayıcı yetenekleri;
  EuroLeague `E`, EuroCup `U`; diğer liglere ESPN tahmini yapılmaz.
- `core/team_identity.py`: sezon üyeliği ve değişmez UUID; sağlayıcı ad alanı,
  kaynak hash'leri, gözlem/ingestion zamanları, zaman aralıklı alias'lar.
  İsim benzerliğine göre birleşme yapılmaz; belirsizlik reddedilip günlüğe alınır.
- `providers/season_participants.py`: örnek maçlardan değil, sezon katılımcı uç
  noktalarından tam liste; toplam/sayfalama, sezon ve sağlayıcı kimliği doğrulaması.
  Geçmiş NBA sezonlarında güncel ad listesi eski sezona etiketlenmez; her sezon
  üyesinin kendi takım detay kaydı gerekir.
- `universal_analysis.py`: lig → sezon katılımcıları → benzersiz takım → gerçek
  fikstür → başlangıç kapısı → geçmiş → model girdisi sıralaması.
  Kaynak gözlemi 300 saniyeden eski veya gelecek tarihliyse analiz durur.
- `main.py`: yeni servisle sağlayıcı yönlendirmesi; NBA referans motoru korunur,
  diğer liglerde uygun olmayan model veya ESPN geçmişi çağrılmaz.
- `season_archive_inventory.py`: EuroCup için ayrı `U` sözleşmesi; eski NBA ve
  EuroLeague kataloglarının hash/replay biçimi korunur.
- `team_identity_audit.py`: bütün ligleri raporlayan, varsayılanı ağsız dry-run olan CLI.
- GitHub Actions: `dev/**` hedefli bağımlı PR'lar da unit-tests/docker-build alır.
  Zamanlayıcı veya dağıtım eklenmez.

## 2026/2027 gerçek kaynak kapsamı

| Lig | Katılımcı | Resmî adla benzersiz çözümleme | Kaynak |
|---|---:|---:|---|
| NBA | 30 | 30/30 | ESPN sezon 2027 üyeliği + aynı sezon ad dizini |
| EuroLeague | 20 | 20/20 | Resmî E2026 sezon ve kulüp uç noktaları |
| EuroCup | 32 | 32/32 | Resmî U2026 sezon ve kulüp uç noktaları |
| NBL, CBA, KBL, LBA, LNB, GBL, SBL | Bilinmiyor | Ölçülmedi | Adaptör yapılandırılmadı |
| FIBA Europe Cup, BCL, ACB, BSL, BBL | Bilinmiyor | Ölçülmedi | Adaptör yapılandırılmadı |

EuroCup'taki 32 değeri alınan kaynağın `total` ve satır sayısıdır; beklenen bir sayı
kod içine sabitlenmedi. U2026 fikstüründeki takım kimlikleri kulüp listesiyle
karşılaştırıldı. Bu sayılar maç veya tahmin sayısı ve model doğruluğu değildir.
Başlangıçtaki hatalı NBA `/types/2/teams` denemesi HTTP 404 döndü; boş sezon sayılmadı.
Doğru `/seasons/2027/teams` uç noktası 30 üyeyi sağladı.

Yeni katılımcı/endpoint incelemesinde 9 HTTP isteği: 8 adet 200, 1 adet 404.
Yerel orijinal kayıtlarla kapsam replay'i ek HTTP yapmadı. Ardından iki gerçek
komut için güncel tazelik kapısıyla 4 ayrı HTTP isteği yapıldı; sonuç ve kaynak
zamanları [kanıt dosyasında](evidence/universal-team-identity-20261111.json).
Ham kulüp iletişim/adres alanları Git'e yüklenmedi; hash ve gerekli kimlik metadata'sı raporlandı.

## İki gerçek komutun sonucu

| Komut takımları | Kaynak kimlikleri | Geçmiş maç, ev/deplasman | Sonuç |
|---|---|---:|---|
| Paris Basketball / Fenerbahce Beko | PRS / ULK | 10 / 10 | MODEL_INPUTS aşamasında ABSTAIN |
| Partizan Belgrade / Baskonia | PAR / BAS | 10 / 10 | MODEL_INPUTS aşamasında ABSTAIN |

İki fikstür de kaynakta bulundu. Fenerbahçe'nin kaynak resmî adı ile Beko içeren
kalıcı adı ayrı alanlardan gelir. Partizan'ın şehirli adı, doğrulanmış kaynak
adı ve şehir alanından genel kuralla türetilir. Bu dört takım üretim kodunda
sabitlenmedi. Gerçek NBA/EuroLeague kaynaklarında alias anahtarı belirsizliği
gözlenmedi; sentetik çakışma testinde ilk eşleşme seçilmez.

Ret gerekçesi: `VERIFIED_PACE_AND_PROSPECTIVE_MODEL_ARCHIVE_NOT_CONFIGURED`.
Doğrulanmış normal süre geçmişi bulunması tempo, kadro veya kullanılabilir lig
modeli olduğu anlamına gelmez. Tempo, sakatlık, oyuncu dakikaları ve rotasyon
bilinmiyor olarak kalır. Yeni gerçek tahmin ve sonuç kaydı **0**.

## Güvenlik ve doğrulama sınırları

- UUID ad alanı ligle sınırlı sağlayıcı kimliğinden türetilir. EuroLeague'in E/U
  kulüp kodları ortak kaynak ad alanını kullanır. Farklı sağlayıcı kimlikleri
  isimden otomatik birleştirilmez; kanıtlı çapraz kimlik eşlemesi henüz yoktur.
- Alias için başlangıç, kaynakta ilk gözlem zamanıdır; gerçek sponsor sözleşmesi
  başlangıcı veya geçmiş Türkçe/İngilizce resmî çeviri uydurulmaz. Dil bilinmiyorsa
  `und` tutulur. Açık dil ve geçerlilik aralığı alanları desteklenir.
- Hash bozulmayı saptar; sağlayıcı imzası, bağımsız noter veya kullanım/eğitim
  izni değildir. `LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION` açıkça saklanır.
- Registry bu aşamada süreç içi snapshot deposudur. Kalıcı registry yedekleme ve
  bağımsız oturumda kurtarma doğrulanmadı. Üretim SQLite şeması değiştirilmedi.
- Geçmiş NBA fallback sentetik olarak sınandı; bir sezon-takım detay uç noktası
  gerçek istekle incelendi. Tam geçmiş sezonun gerçek fallback indirmesi yapılmadı.
- NBA sonucuna kimlik/source metadata'sı eklenir. Bütün ligler için yeni merkezi
  kimliklerle atomik immutable prediction/sonuç arşivi henüz bağlanmadı.
- Normal süre geçmişi ilk dört periyottur; uzatma toplamı buna karıştırılmaz.
  Başlamış/tarihsel maç için güncel veriden prematch tahmin oluşturulmaz.
- Kullanıcının daha önce bildirdiği 2 tahmin / 2 sonuç bu aşamada yeniden
  sorgulanmadı. Gerçek uygun tahmin–sonuç eşleşme sayısı bilinmiyor;
  MAE/RMSE/bias/Brier veya kalibrasyon başarısı ileri sürülmüyor.

## Testler ve kalan işler

Önceki 303 test korundu; 30 yeni testle **333/333 başarılı**. Odaklı takım ve
analiz testleri **30/30 başarılı**. Kimlik/alias/sezon değişimi, sponsor adları,
çakışma, yanlış sağlayıcı, HTTP erişim hatası, ağ kesintisi, PIT, fikstür kimliği,
başlamış maç, 300/301 saniye tazelik sınırı, gelecek saat ve eski katalog replay'i kapsanır.
Test log hash'leri kanıt dosyasında; CI sonucu PR'da tam commit SHA ile raporlanır.

İlk test denemesinde bu Cloud sandbox'ının iç socket kısıtı nedeniyle art arda
`asyncio.to_thread` çağrıları takıldı. Uygulamadan bağımsız küçük örnekte de
yeniden üretildi. Ağ/socket izniyle aynı testler normal tamamlandı; testlerin
sağlayıcıları mock'tur. Ayrıca bir test saati Türkiye'de ertesi güne taşıyordu;
aynı günün maç sonrası saatine düzeltilince beklenen güvenlik ret yolu sınandı.
Bu başarısız/bekleyen ilk denemeler başarılı gerçek tahmin sayılmadı.

Sıradaki bağımlılıklar: kalan 12 lig için doğrulanmış tam sezon katılımcı
adaptörleri ve o liglerin gerçek sezon sınırları; izin/PIT kanıtlı istatistik
ve oyuncu katmanı; kalıcı registry ve kimlik çapraz eşlemesi; lig bazında
immutable tahmin–sonuç entegrasyonu; uygun gerçek örneklemle kalibrasyon.
Bu aşama bu eksikleri tamamlanmış göstermez ve otomatik model ayarı yapmaz.
