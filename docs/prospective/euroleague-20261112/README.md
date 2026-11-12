# EuroLeague — 12 Kasım 2026 gerçek pre-match araştırma kaydı

Kaynak kod: `1f08765fc2516055d8f50f6424fa7f9ae8c77370`. Resmî kaynak: https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games.
Beş maç da kaynak doğrulamasında başlamamıştı. Kayıt zamanı: **2026-11-12T18:43:06Z**.
Dört mevcut bileşen × beş maç = **20 gerçek model çıktısı**. Tablolar **Bayesian/QMC bileşenini** gösterir; doğrulanmış ensemble çıktısı değildir.
Faz13 kontrolü, possession analitik ve possession MC çıktıları aynı maçın JSON kaydında ayrı saklıdır.
Güncel sezon için doğrulanmış ve bütün bileşenleri erişilebilir ensemble yok; ağırlık uydurulmadı. Ensemble `ABSTAIN`.

Normal süre içindir; uzatma dahil değil. Skorlar beklenen sayılardır. Ev handikabı model farkından türetilir, doğrulanmış bookmaker baremi değildir.
Gerçek bahis çizgisi/odds doğrulanmadığından ALT/ÜST barem olasılığı, edge, güven endeksi ve bahis önerisi üretilmedi.

| # | Maç (ev – deplasman) | Başlangıç UTC | Skor | Toplam | Model ev handikabı | 1H |
|---|---|---|---|---:|---:|---|
| 1 | Maccabi Rapyd Tel Aviv – Hapoel IBI Tel Aviv | 19:05 | 87.04 – 92.45 | 179.49 | +5.40 | 41.90 – 45.96 |
| 2 | Olympiacos Piraeus – Dubai Basketball | 19:15 | 85.36 – 82.81 | 168.16 | -2.55 | 42.22 – 43.41 |
| 3 | Valencia Basket – FC Bayern Munich | 19:30 | 96.33 – 87.35 | 183.68 | -8.98 | 49.18 – 41.87 |
| 4 | Armani Olimpia Milan – Zalgiris Kaunas | 19:30 | 82.52 – 87.32 | 169.84 | +4.80 | 41.26 – 43.66 |
| 5 | Real Madrid – Crvena Zvezda Meridianbet Belgrade | 20:00 | 86.56 – 85.10 | 171.66 | -1.46 | 44.16 – 44.11 |

TSİ = UTC +3 saat. Bütün tarihler 12 Kasım 2026.

| # | 1Q | 2Q | 3Q | 4Q |
|---|---|---|---|---|
| 1 | 21.18 – 24.22 | 20.72 – 21.73 | 22.40 – 22.71 | 22.75 – 23.79 |
| 2 | 22.44 – 22.55 | 19.78 – 20.86 | 21.09 – 20.19 | 22.05 – 19.21 |
| 3 | 25.71 – 20.19 | 23.47 – 21.68 | 22.46 – 22.07 | 24.69 – 23.41 |
| 4 | 20.75 – 21.95 | 20.50 – 21.70 | 21.01 – 21.45 | 20.25 – 22.20 |
| 5 | 22.55 – 22.91 | 21.61 – 21.20 | 22.04 – 20.35 | 20.37 – 20.64 |

| # | Ev kazanır | Normal süre eşitlik | Deplasman kazanır |
|---|---:|---:|---:|
| 1 | %36.35 | %2.20 | %61.45 |
| 2 | %54.84 | %2.32 | %42.84 |
| 3 | %69.24 | %2.15 | %28.61 |
| 4 | %37.60 | %2.44 | %59.96 |
| 5 | %52.24 | %2.39 | %45.37 |

Bunlar QMC ile hesaplanan **ham, kalibre edilmemiş model olasılıklarıdır**; güven endeksi veya bookmaker olasılığı değildir.
Bir maçın toplamı/takım/çeyrek değerleri yuvarlanmamış JSON’da tutarlıdır; tabloda iki ondalık yuvarlama farkı olabilir.

| # | Maç kimliği | Değiştirilmeden korunan tahmin kaydı |
|---|---|---|
| 1 | E2026_103 | [0baa4e2b3cb5](0baa4e2b3cb54554f9b5d0667717cbee61e5cdf0367e99b909139ae4611d6a8f.json) |
| 2 | E2026_107 | [0914956095da](0914956095da0ba9884454b69f8e5bfe6a7599289a5db2ed02670543b497d907.json) |
| 3 | E2026_105 | [1cc7909d262d](1cc7909d262d9ddebf26ec8f4a2b08acdc212b5334d222dcb6f38b5bc819b8c9.json) |
| 4 | E2026_104 | [2aed77cda2f3](2aed77cda2f34fbaed9ed0d378b249eefa2784d36ff285f2ea9dd44c4663ce43.json) |
| 5 | E2026_106 | [4693553816c6](4693553816c60ba15e09e0d34e08504e4e1f076cf706454a1d09f9b0fd063283.json) |

Arşiv politikası: yeni dosyaya atomic insert-only yayın, SHA-256 içerik kimliği, salt-okunur yerel dosyalar ve Git sürüm geçmişi. Fiziksel WORM depolama garantisi değildir.
Model sürümü/digest’i, veri ve UTC saatleri, girdiler, resmî kaynak belgesi, frozen Bayesian parametreleri ve boş piyasa alanları kayıtlardadır.
Telegram test botu/yetkili kullanıcı erişimi yapılandırılmadı: gerçek teslimat **NOT_RUN**. Üretim botuna mesaj gönderilmedi.
Üretim/Fly/SQLite/main/secret erişimi veya değişikliği yok. Önceki arşivler değiştirilmedi.
