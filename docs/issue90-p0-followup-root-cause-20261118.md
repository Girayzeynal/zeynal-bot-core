# Issue #90 — ek P0 kök neden raporu

Temel commit: `93f8bbf3637dfb49c58c3ee1a2597acff19db5da` (PR #94).
İncelenen ek not: yorum `6987248173`, 18.11.2026 18:08:38 UTC.
Bu ilk teşhis yeni kod düzeltmelerinden önce hazırlanmıştır.

## Mevcut işlerin korunması

| Konu | Mevcut PR | Bu çalışmadaki işlem |
| --- | --- | --- |
| Sonuç/OT ayrımı ve sonuç kolektörü | #91–92 | Koruma; tekrar yazılmayacak |
| Dinamik V3 ve ortak piyasa dağılımı | #91 | Mevcut çekirdekler kullanılacak |
| Araştırma kabulünde kimlik/kohort | #92 | Protokoller korunacak |
| Avrupa isimleri ve düğmeler | #93 | Değiştirilmeyecek |
| Sağlayıcı kapasitesi ve arşiv model yaşı | #94 | Tekrar yazılmayacak |
| Tamamlayıcı native istatistik çelişkisi | Yeni bulgu | Ayrı araştırma görünümü ve regresyon testi |
| Aynı kronolojik kesitte karşılaştırma | Ek not C–E | Kaynak kanıtlı, çevrimdışı araştırma raporu |

## Kodda doğrulanan model sınırları

`verified_analysis.project_scores()` ve FAZ13 referansı son-N hücum/savunma
ortalamalarını eşit ağırlıkla birleştiriyor. Referans formül değiştirilmeyecek.
Çağrıda korelasyon/ortak tempo sapması sıfır; Gamma(18,1) periyot paylaştırması
gözlenmiş rotasyon veya PBP modeli değildir. 10.000 örnek eksik özellikleri
gidermiyor.

`providers/espn_adapter.py` legacy baseline için `pace=100.0` veriyor. Bu alan
doğrulanmış tempo sayılmayacak. Verified history skor yolu ayrıdır; bütün
skorların bu placeholder'dan üretildiği söylenemez.

Bayes V1 tam maç ortalaması sabit katsayılardan geliyor. `forecast_error_review`
ve `quality_monitor` bu sınırı zaten açıklıyor. Otomatik kalibrasyon/promotion
yapmıyorlar. Eski model/deney kaynak pinleri korunacak.

## Yeni hata: ek istatistik farkı sonuç çelişkisi sayılıyor

Korunmuş `nba-phase843-resource-inputs-20261113.tar.gz` içindeki native skor
tablosu ve maç özeti belgelerini birleştiren `historical_rows()`
`CONFLICTING_HISTORICAL_RESULT` veriyor. Kontrol edilen kanonik kimlik, sezon,
başlangıç, takımlar, final ve periyotlarda gerçek sonuç çelişkisi bulunmadı.

Çelişki karşılaştırmasına `team_statistics` ve alanın bulunma durumu da giriyor.
Özette bulunup skor tablosunda bulunmayan tamamlayıcı alanlar tüm korpusu bloke
edebiliyor. Çözüm: yeni araştırma görünümünde çekirdek sonuç kimliğini sıkı
doğrulamak, her sürümün kaynak SHA'sını ve gerçek erişim saatini ayrı korumak.
Gerçek skor/periyot/kimlik çelişkisi yine reddedilecek. Eski V1/V2 deneyleri ve
arşivleri yeniden imzalanmayacak.

Bu hata birleşik tarihsel replay görünümünde yeniden üretildi. Çalışan V2
`FeatureStore.cohort()` kataloğu zaten tek tek okuyor; bu bulgu V2 işçisinin
veya kullanıcının 23 tahmininin bu nedenle bozulduğunun kanıtı değildir.

## Üretimden gerçekten görülen kanıt

Anonim, salt okunur `https://zeynal-bot-core.fly.dev/ready` GET isteği HTTP 200,
`ready=true` ve bildirilen release SHA
`dacec114341edd08bd54d631f1128f0624eccf2a` döndürdü. Bu commit'in kodu
varsayılan verified service yönlendirmesini içeriyor. Ancak `/ready` gerçek
analiz yanıtındaki model digestini vermiyor. Hazır olma/release bilgisi
görüldü; tam çalışan motor kimliği **NOT_VERIFIED**. Fly komutu, SSH, volume,
secret veya dağıtım işlemi yapılmadı.

`data/baselines` varsayılanı Docker'da `/app/data/baselines` olabilir; mount
`/data`. Bu olası legacy kalıcılık farkı, ayrı verified SQLite arşivinin
kaybolduğu anlamına gelmez. Üretim dosyaları taşınmayacak.

## Deney sınırları

Gerçek native belgeler kullanılacak; sonradan alınmış belge geçmişte erişilmiş
gibi gösterilmeyecek. `AVAILABILITY_ASSUMED_RESEARCH` karşılaştırması açıkça
bu isimle raporlanıp canlı başarı veya kabul kanıtına katılmayacak. İlk yayın
zamanı doğrulanmış özgün örnek ayrıca ayrılacak.

FAZ13, donmuş Bayes V1 çekirdeği ve güncellenen takım çekirdeği aynı maç/kesitte
karşılaştırılacak. Ölçülmüş tempo, önceden doğrulanmış hedef kadrosu veya native
bookmaker/ödeme kanıtı yoksa ilgili sütun ABSTAIN/NOT_VERIFIED kalacak.
Box-score pozisyon tahmini PBP olarak gösterilmeyecek.

Bu rapor aşamasında yeni deney henüz çalıştırılmadı. Üstünlük, kalibrasyon ve
gerçek Telegram teslimi iddiası yok. Test/deney sonuçları ayrıca eklenecek.
Üretim dağıtımı, main merge, veri silme veya `zeynal_data` işlemi yok.

## Devam sırasında okunan ek notlar

Yorumlar `6988657808`, `6989238349`, `6989320277`, `6989518027` de okundu.
Kullanıcının cihaz çıktısı: 39 özgün NBA kayıt, 23 sonuç, 16 bekleyen;
kontrol anında `started_unsettled=0`. Bu Cloud'un cihazda yaptığı yeni bir
ölçüm değildir. 23 sonuçtaki toplam MAE 15.82 / RMSE 20.17 ve ham Brier
0.5363 ayrı bir canlı kohorttur; aşağıdaki tarihsel çalışma ile karıştırılmaz.

`quality_report.report()` zaten özgün native girdilerden
`forecast_error_review.review(..., profiles=...)` ile aynı maçlardaki basit
referansı hesaplıyor. Sorun bu karşılaştırmanın CLI özetinde görünmemesi:
mevcut `--error-review` yalnız ilk üç donmuş model hatasını basıyor. Yeni bir
model/öğrenme zinciri yazmak yerine bu mevcut raporun kısa CLI çıktısına
eşlenmiş MAE/RMSE, üç vakadaki iki hata ve kimlik/zaman/kapsam eklenmeli.
UserLAnd veritabanı bu Cloud ortamında yok; oradaki 23 çiftin gerçek yeni
sayısal sonucu burada tamamlandı diye sunulamaz.

TOR–NYK ve MIN–POR gibi tekrar oynanan eşleşmeler isimden birleştirilmeyecek.
Normal süre 95–95 kaydı, uzatmalı 108–112 finalinden ayrı ve geçerli bir
sonuç olabilir. Eksik finalin, skor modelinin yanlılığıyla aynı sorun olduğu
varsayılmayacak.
