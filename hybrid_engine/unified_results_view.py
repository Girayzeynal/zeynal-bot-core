"""Read-only, one-format comparison of immutable, published forecasts and native finals.

For isolated Telegram only. Read from existing report services; never fetch,
settle, refit, fabricate historical predictions or combine incompatible cohorts.
"""
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

TSI = ZoneInfo("Europe/Istanbul")
LEAGUES = ("NBA", "EUROLEAGUE", "EUROCUP")


def unwrap(value):
    while isinstance(value, dict) and isinstance(value.get("report"), dict):
        value = value["report"]
    if not isinstance(value, dict) or not isinstance(value.get("forecasts"), list):
        raise ValueError("UNIFIED_VERIFIED_REPORT_REQUIRED")
    return value


def normalized_rows(report, league):
    if report.get("status") != "VERIFIED_LIVE_REPORT":
        raise ValueError("UNIFIED_NATIVE_REPORT_UNAVAILABLE")
    groups = defaultdict(list)
    for row in report["forecasts"]:
        if row["league"] != league:
            raise ValueError("UNIFIED_LEAGUE_IDENTITY_CONFLICT")
        identity = (row["league"], row["season"], row["fixture_id"])
        groups[identity].append(row)
    return sorted(groups.values(),
                  key=lambda rows: (rows[0]["fixture_start_utc"], rows[0]["fixture_id"]))


def summary(report, league, now):
    fixtures = normalized_rows(report, league)
    matched = sum(any(row.get("actual") is not None for row in rows) for rows in fixtures)
    unverified_started = sum(rows[0]["fixture_start_utc"] <= now and
                            not any(row.get("actual") is not None for row in rows)
                            for rows in fixtures)
    pending = len(fixtures) - matched - unverified_started
    return dict(league=league, archived=len(fixtures), matched=matched,
                started_unverified=unverified_started, not_started=pending)


def render_league(report, league, now, *, all_matches=False):
    fixtures = normalized_rows(report, league)
    counters = summary(report, league, now)
    lines = [f"{league} | Kayıtlı {counters['archived']} | FINAL eşleşmiş "
             f"{counters['matched']} | Başlamış/FINAL kanıtı yok "
             f"{counters['started_unverified']} | Başlamamış {counters['not_started']}"]
    if not all_matches:
        return lines
    for rows in fixtures:
        first = rows[0]
        ts = datetime.fromtimestamp(first["fixture_start_utc"], TSI).strftime("%d.%m %H:%M")
        paired = [row for row in rows if row.get("actual") is not None]
        state = ("FINAL" if paired else
                 "BAŞLAMADI" if first["fixture_start_utc"] > now else
                 "BAŞLADI; FINAL KANITI YOK")
        lines.append(f"{ts} TSİ | {first['home']} – {first['away']} | {state}")
        if not paired:
            continue
        for row in paired:
            p = row["prediction"]
            a = row["actual"]
            lines.append(f"  {row['model_version']}: {p[0]:.1f}–{p[1]:.1f} "
                         f"→ {a[0]}–{a[1]} | Toplam hata {sum(p)-sum(a):+.2f}")
            q = row.get("predicted_quarters")
            periods = row.get("actual_periods")
            if q is not None and periods is not None:
                if len(q) != 4 or any(len(periods.get(s, [])) < 4 for s in ("home", "away")):
                    raise ValueError("UNIFIED_REGULATION_PERIOD_REQUIRED")
                errors = [sum(q[i]) - periods["home"][i] - periods["away"][i]
                          for i in range(4)]
                lines.append("  Periyot hatası: " +
                             " ".join(f"{i+1}Q {e:+.1f}" for i, e in enumerate(errors)) +
                             f" | 1H {sum(errors[:2]):+.1f} | 2H {sum(errors[2:]):+.1f}")
            if row.get("legacy_publication_clock_unrecorded"):
                lines.append("  ESKİ ARŞİV: ilk yayın zamanı kanıtlanmadı; canlı doğruluk hesabına dahil değil")
            if row.get("final_with_ot") is not None and row["final_with_ot"] != a:
                lines.append(f"  Uzatma dahil: {row['final_with_ot']} (normal süre hesabına dahil değil)")
    return lines


def render_all(reports, *, now, detail=True):
    if any(k not in reports for k in LEAGUES):
        raise ValueError("UNIFIED_THREE_LEAGUE_REPORTS_REQUIRED")
    normalized = {league: unwrap(reports[league]) for league in LEAGUES}
    totals = [summary(normalized[league], league, now) for league in LEAGUES]
    lines = ["ZEYNAL | 3 LİG | ORİJİNAL TAHMİN → DOĞRULANMIŞ SONUÇ",
             "Normal süre, Türkiye saati | İzole test arşivi, üretim değil"]
    for row in totals:
        lines.append(f"{row['league']}: {row['matched']}/{row['archived']} "
                     f"eşleşmiş; {row['started_unverified']} başlamış/FINAL eksik; "
                     f"{row['not_started']} başlamamış")
    lines.append("TOPLAM: "+str(sum(r["matched"] for r in totals))+" eşleşmiş / "+
                 str(sum(r["archived"] for r in totals))+" kayıt")
    if detail:
        for league in LEAGUES:
            lines.append("")
            lines.extend(render_league(normalized[league], league, now, all_matches=True))
    lines.append("Eksik FINAL = devam ediyor veya kaynakta kesin sonuç henüz doğrulanmadı.")
    lines.append("Bu liste yalnız önceden kayıtlı tahminleri içerir. Sonradan PREMATCH üretilmez.")
    return "\n".join(lines)


def render_performance(reports):
    lines = ["ZEYNAL | ÜÇ LİG AYRI MODEL PERFORMANSI | NORMAL SÜRE",
             "Yalnız ilk yayın zamanı kanıtlı prospektif örneklem; karşılaştırmalı üstünlük kanıtı değil"]
    for league in LEAGUES:
        report = unwrap(reports[league])
        groups = report.get("groups", [])
        lines.append(f"{league}: {len(groups)} model kohortu")
        for row in groups:
            lines.append(f"  {row['model_version']} | N={row['n']} "
                         f"| Takım MAE {row['team_mae']:.2f} | Toplam MAE {row['total_mae']:.2f}")
    lines.append("Eski EuroLeague arşivi ilk yayın zamanı belirsizse metrik dışıdır.")
    lines.append("NOT_CALIBRATED | Güven yüzdesi ya da bahis başarısı değildir.")
    return "\n".join(lines)
