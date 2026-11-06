# FAZ39 — Offline ret gerekçesi ve istisna kökeni

Görev: [PR #14 / 6681815753](https://github.com/Girayzeynal/zeynal-bot-core/pull/14#issuecomment-6681815753).
Başlangıç: `5ff028f4abc6f4f2683aea263d6e809bd80b8c77`.
Bu değişiklik yalnızca offline test düzeneğini ve regresyonlarını genişletir;
üretim runtime/config, gerçek veriler veya harici sağlayıcı üzerinde işlem yoktur.

## Makine tarafından okunabilir ret kanıtı

CLI'nin başarısızlık çıktısı mevcut `error_type` bilgisini değiştirmez. Ek alanlar:

- `reason_code`: yalnızca bilinen güvenlik/assertion kodlarından türetilir. Serbest
  exception metni, stack veya sağlayıcı mesajı çıktıya yazılmaz.
- `rejection_stage`: exception oluştuğunda gerçekten yürütülen kontrol grubu.
  Aşama, `--fault` adına bakılarak seçilmez; grup başlamadan önce işaretlenir.
- `rejection_origin`: gerçek `Refused` için `CONTRACT_POLICY_REFUSAL`, gerçek
  `AcceptanceFailure` için `ACCEPTANCE_ASSERTION`, diğer türler için
  `UNEXPECTED_RUNTIME_ERROR`.
- `recognized_rejection`: yalnızca gerçek sınıf + aşama + izinli kod imzası
  eşleştiğinde true. Bu alan fault adına göre tahmin yapmaz; fault ile tam
  eşleşmeyi bağımsız beklenti tablosu kullanan regresyonlar ayrıca denetler.
- `checks`/`check_count`: exception öncesinde tamamlanan gerçek kontrol grupları.
  Bir çalıştırmanın trace'i yeniden kullanılarak sayılar artırılamaz.

Her iki temel exception sınıfı ValueError'dan türese de birbirinin yerine
kullanılmaz. `exercise()` orijinal exception'ı yükseltmeye devam eder; CLI onu
yalnızca raporlar. Benzer mesajlı `ValueError`/`KeyError`/`TypeError`, alt sınıf
veya yanlış aşamada görülen bir kod, beklenen guard kanıtı sayılmaz.

## Dokuz negatif senaryonun kesin çıktıları

Tümü exit 1, `OFFLINE_ACCEPTANCE_FAIL` ve `NOT_VERIFIED` döndürür.

| Fault | error_type | reason_code | rejection_stage |
|---|---|---|---|
| overwrite | AcceptanceFailure | IMMUTABLE_CONDITIONAL_CREATE | immutable_create |
| unbounded-read | AcceptanceFailure | UNBOUNDED_STREAM_ACCEPTED | bounded_stream |
| missing-durable-proof | Refused | DURABLE_ACK_EVIDENCE_MISSING | durable_ack |
| unconditional-cas | AcceptanceFailure | DISTRIBUTED_CAS_MODEL_VIOLATION | pin_cas |
| same-runtime | Refused | SAME_RUNTIME_OR_FILESYSTEM | runtime_isolation |
| same-trust-admin | AcceptanceFailure | INDEPENDENT_ADMIN_BOUNDARIES_MISSING | trust_roots |
| false-verified | AcceptanceFailure | FAKE_PROVIDER_CANNOT_VERIFY | runtime_isolation |
| swapped-trust-root | AcceptanceFailure | TRUST_ROOT_SUBSTITUTION | trust_roots |
| unsafe-lost-ack | AcceptanceFailure | LOST_ACK_WAS_FALSE_SUCCESS | lost_ack |

Sonuç **7 AcceptanceFailure + 2 Refused** olarak korunur. Aksi bir toplamı elde
etmek için exception sınıfları yeniden etiketlenmez. CAS writer sırası çıktıda
yer almaz; dokuz senaryonun tekrarlanan çalıştırmaları aynı JSON tanısını verir.

## İki Refused yolunun nedensel regresyonları

`missing-durable-proof` için spy, gerçek `attested()` çağrısının
FAZ39_DURABLE_ACK payload'unu kabul ettiğini kaydeder. Payload'un sadece zorunlu
`provider_receipt_sha256` alanı eksiktir. Gerçek `require()` üzerinden bu aşamada
görülen tek false guard, **DURABLE_ACK_EVIDENCE_MISSING** olur. İki önceki grup
tamamlanmıştır; eksik alana erişimden doğan KeyError ret nedeni değildir.

`same-runtime` için gerçek FAZ39_RUNTIME_EVIDENCE attestation'ı kabul edilmiştir.
Kaynak/hedef runtime ID'leri aynıdır; run ID, filesystem ve storage ID'leri
birbirinden farklıdır. Bu aşamanın tek false guard'ı
**SAME_RUNTIME_OR_FILESYSTEM** olur. Önceki sekiz grup tamamlanmıştır.

Her iki gerçek guard noktasına ayrıca tesadüfi runtime hataları enjekte edilir:
makbuz kontrolünde KeyError, kimlik kontrolünde TypeError. CLI bunları özgün
`error_type`, aynı gerçek aşama, `reason_code=UNEXPECTED_EXCEPTION` ve
`recognized_rejection=false` ile raporlar. Böylece sırf exit 1 üretmek testi
geçirmeye yetmez. Bilinen koda benzeyen hata mesajları da sınıflandırmayı kandıramaz.

Bilinmeyen gerçek Refused/AcceptanceFailure mesajları sırasıyla
UNEXPECTED_CONTRACT_REFUSAL/UNEXPECTED_ACCEPTANCE_ASSERTION olarak temizlenir;
orijinal exception türü korunur ve recognized_rejection false kalır. Bunlar
incidental runtime hatalarından ayrı raporlanır.

## Tekrarlama ve doğrulama sınırı

```sh
python -I tests/faz39_offline_acceptance.py
python -I tests/faz39_offline_acceptance.py --fault missing-durable-proof
python -I tests/faz39_offline_acceptance.py --fault same-runtime
python -m unittest tests.test_faz39_offline_acceptance -v
python -m unittest discover -s tests -v
```

Negatif CLI komutlarının exit 1 üretmesi beklenir. Pozitif akış 11 grubu geçer;
bu gruplar gerçek sağlayıcı/kriptografik attestation/bağımsız Cloud kanıtı değildir.
Sahte backend ve trust root, `LOCAL_ONLY`, sıfır gerçek prospektif kayıt,
durable_storage_verified=false ve separate_cloud_runtime_verified=false korunur.
Harici kalıcılık ve bağımsız Cloud kurtarması **NOT_VERIFIED** kalır.
