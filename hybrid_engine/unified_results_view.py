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
    lines = [f"{league} | Doğrulanmış FINAL {counters['matched']} | "
             f"Başlamış ama FINAL henüz doğrulanmamış {counters['started_unverified']}"]
    if not all_matches:
        return lines
    for rows in fixtures:
        first = rows[0]
        # Do not place future matches, or started matches with no verified FINAL,
        # in a report that the user requested specifically for finished games.
        paired = [row for row in rows if row.get("actual") is not None]
        if not paired:
            continue
        ts = datetime.fromtimestamp(first["fixture_start_utc"], TSI).strftime("%d.%m %H:%M")
        lines.append(f"{ts} TSİ | {first['home']} – {first['away']} | FINAL")
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


def render_all(reports, *, now, detail=True, source_label="İzole test arşivi, üretim değil"):
    if any(k not in reports for k in LEAGUES):
        raise ValueError("UNIFIED_THREE_LEAGUE_REPORTS_REQUIRED")
    normalized = {league: unwrap(reports[league]) for league in LEAGUES}
    totals = [summary(normalized[league], league, now) for league in LEAGUES]
    lines = ["ZEYNAL | 3 LİG | ORİJİNAL TAHMİN → DOĞRULANMIŞ SONUÇ",
             "Normal süre, Türkiye saati | " + source_label]
    for row in totals:
        lines.append(f"{row['league']}: {row['matched']} doğrulanmış FINAL ile eşleşmiş "
                     f"| {row['started_unverified']} başlamış, FINAL henüz doğrulanmamış")
    lines.append("TOPLAM: "+str(sum(r["matched"] for r in totals))+" eşleşmiş FINAL")
    if detail:
        for league in LEAGUES:
            lines.append("")
            lines.extend(render_league(normalized[league], league, now, all_matches=True))
    lines.append("Başlamış ama FINAL doğrulanmamış maçlar hesaplamaya alınmadı; devam ediyor veya kaynak sonucu eksik olabilir.")
    lines.append("Başlamamış maçlar bu sonuç raporunun kapsamı dışındadır.")
    lines.append("Bu liste yalnız önceden kayıtlı tahminleri içerir. Sonradan PREMATCH üretilmez.")
    return "\n".join(lines)


def render_performance(reports):
    lines = ["ZEYNAL | ÜÇ LİG AYRI MODEL PERFORMANSI | NORMAL SÜRE",
             "Yalnız ilk yayın zamanı kanıtlı prospektif örneklem; karşılaştırmalı üstünlük kanıtı değil"]
    for league in LEAGUES:
        if league not in reports:
            continue
        report = unwrap(reports[league])
        groups = report.get("groups", [])
        lines.append(f"{league}: {len(groups)} model kohortu")
        errors = defaultdict(dict)
        for forecast in report['forecasts']:
            if (forecast.get('actual') is None or forecast.get('legacy_publication_clock_unrecorded')
                    or forecast.get('eligible_for_live_performance') is False):
                continue
            cohort = (forecast['league'], forecast['season'], forecast['model_digest'], forecast['model_version'])
            errors[cohort][forecast['fixture_id']] = sum(forecast['prediction']) - sum(forecast['actual'])
        for row in groups:
            lines.append(f"  {row['model_version']} | N={row['n']} "
                         f"| Takım MAE {row['team_mae']:.2f} | Toplam MAE {row['total_mae']:.2f}")
            cohort = (league, row.get('season'), row.get('model_digest'), row['model_version'])
            residuals = errors[cohort].values()
            if len(residuals) == row['n'] and residuals:
                near = sum(-2 <= error <= 3 for error in residuals)
                large = sum(abs(error) >= 25 for error in residuals)
                lines.append(f"  Toplam (tahmin − sonuç): −2…+3 içinde {near}/{len(residuals)}"
                             f" · 25+ sayı mutlak hata {large}/{len(residuals)}")
    lines.append("Eski EuroLeague arşivi ilk yayın zamanı belirsizse metrik dışıdır.")
    lines.append("NOT_CALIBRATED | Güven yüzdesi ya da bahis başarısı değildir.")
    return "\n".join(lines)



def accuracy_sections(reader, *, candidate=None, market=None, market_directions=None, receipt=None):
    """One league or optional performance section can fail independently."""
    import logging
    import time
    from hybrid_engine.runtime_reports import REPORT_ERRORS, failure
    log = logging.getLogger(__name__)
    verified, unavailable = {}, []
    leagues, optional = {}, {}
    for league in LEAGUES:
        started = time.monotonic()
        try:
            report = unwrap(reader.read(league, None))
            fixtures = normalized_rows(report, league)
            render_performance({league: report})
            settled = [rows for rows in fixtures if any(r.get('actual') is not None for r in rows)]
            eligible = sum(any(r.get('actual') is not None and not r.get('legacy_publication_clock_unrecorded')
                               and r.get('eligible_for_live_performance') is not False for r in rows)
                           for rows in settled)
        except REPORT_ERRORS as exc:
            issue = failure(exc)
            log.warning('Accuracy archive %s unavailable: %s', league, issue)
            unavailable.append(f'{league} · Arşiv okunamadı · {issue}')
            leagues[league] = dict(status='FAILED', error=issue)
        else:
            verified[league] = report
            leagues[league] = dict(status='READ', matched=len(settled), eligible=eligible)
        leagues[league]['elapsed_ms'] = round((time.monotonic()-started)*1000)
    parts = [render_performance(verified), *unavailable]
    for key, label, render, args in (
            ('candidate', 'Güncel aday performansı', candidate, ()),
            ('iddaa', 'İddaa ilk yarı karşılaştırması', market, (verified,)),
            ('market_directions', 'Maç sonucu / Alt-Üst yön denetimi', market_directions, (verified,))):
        if render is None:
            optional[key] = dict(status='UNAVAILABLE')
            continue
        try:
            parts.append(render(*args))
        except REPORT_ERRORS as exc:
            issue = failure(exc)
            log.warning('Accuracy optional section %s unavailable: %s', label, issue)
            parts.append(f'{label} · Okunamadı · {issue}')
            optional[key] = dict(status='FAILED', error=issue)
        else:
            optional[key] = dict(status='RENDERED')
    if receipt is not None:
        receipt.update(leagues=leagues, optional=optional)
    return '\n\n'.join(parts)
