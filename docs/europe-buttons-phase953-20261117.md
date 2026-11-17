# Phase 95.3 — European analysis buttons matching the NBA test UI

Continue PR #89, branch `feature/hybrid-market-roster-evidence-20261114`, from `9a6cbdf6cbf6722dd909a2ccdc9ef53aa03c4fa1`.

## Root cause

NBA's isolated dispatch prepares a compact summary, an authenticated report-cache entry, and a `zui:` inline keyboard. The European services returned their full HTML blocks directly. Reusing NBA's detail extractor alone would also fail because European ranges/headings differ. The callback handler already supports all six sections, session expiration, paging, authorization and after-tipoff archive banners.

## Change

- `europe_premium_ui.py` builds the compact summary and five detail sections from the existing **SHA-bound archived Bayesian/QMC projection**, actual stored intervals and publication receipt. It never fits or runs a model, downloads a source, creates a prediction or writes a forecast.
- The shared summary template now accepts a validated league argument. NBA remains the default, including its existing 48-minute text. EuroLeague and EuroCup show 40 minutes.
- Normal isolated European services now attach the same six buttons as NBA: **Periyotlar, Aralıklar, Piyasa, Model / Kaynak, Kadro / Sakatlık, Özet**. The existing callback handler and bounded cache are reused.
- Periyotlar shows the original four quarters and halves, totals and existing sample bands. Aralıklar shows original P50/P25–P75/P10–P90/P05–P95 values for every available market/period. No synthetic intervals or score rebalancing.
- Model / Kaynak shows actual model/version, native source, fixture ID, sample count, original generation/publication times and forecast SHA. Unknown clocks in the original five-game archive remain unknown.
- Existing verified manual EuroLeague market panels are retained as **archive observations**, with no claim that they were freshly fetched. When no verified market is bound to the response, Piyasa explicitly explains missing data and produces no line, direction, odds or edge.
- Kadro / Sakatlık can display only trusted fixture/time-bound roster evidence already loaded in the test bot. There is **no connected live European injury-query adapter in this panel**. It states this limitation, explains that no record does not mean no injuries, and does not call the NBA-specific current-roster adapter or alter player impacts.
- After-tipoff requests can display an existing full-name archive replay; buttons never create retrospective PREMATCH forecasts. Expired sessions, invalid pages and unauthorized chats use the existing protected callback behavior.
- If presentation construction fails, the original analysis text/forecast remains available with `EUROPE_UI_UNAVAILABLE`; a UI error cannot erase or regenerate the forecast.
- NBA outputs and dispatch are preserved. Replay-only/older opt-in installations without the new European services retain their previous presentation. The normal UserLAnd launcher already supplies the European service directory.

## Archive and model safety

No changes to `europe_live.py`, `europe_models.py`, `models.py`, `data.py`, `distributions.py`, `intervals.py`, the prepared model pins, NBA ledger/sampler or the 27-file challenger protocol. Existing European models **do not require re-preparation solely for this UI change**. Cache entries are session views tied to the original forecast SHA; they are not prediction publications.

## Validation scope

Ten new tests exercise both leagues, all six actual PTB callbacks, genuine analyze-handler keyboard attachment, original five-game replay, immutable archive bytes, no button inference/downloads, after-tipoff displays, expired/unauthorized sessions, invalid pages, long-section pagination, incorrect SHA binding, UI-failure fallback and unchanged NBA dispatch/template. Existing tests are retained; the mixed-league routing assertion now expects the new European compact headings. The hard-resource probe includes the new suite.

This task's Cloud terminal failed to start. Code review and commits were performed through the connected GitHub tools; no local test run is claimed. **Exact-head GitHub Actions test and Docker/resource outcomes are reported on PR #89 after completion.** In-memory/loopback callback tests are not real external Telegram E2E.

## UserLAnd and Telegram verification

Stop only the isolated test bot with Ctrl+C, then run:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

No special UI option or model re-preparation is needed for this patch. Send these as separate Telegram messages to replay existing user-confirmed forecasts:

```text
/analyze EuroLeague 2026-11-17 Zalgiris Kaunas vs FC Bayern Munich
/analyze EuroCup 2026-11-17 Roma Basketball vs Bahcesehir College Istanbul
```

For each response, click all six buttons and any page-navigation arrows. Period/interval values, original timestamps and hashes must match the stored forecast. Repeat /analyze to reopen an expired session without creating a new prediction. Confirm /predictions still shows the same fixture publications and NBA's /analyze retains its current buttons.

Actual Telegram delivery/clicks for **this UI patch** remain unverified until the user runs the isolated bot. Prior user transcripts establish European prediction/listing success, not the new callback feature.

**NO-GO for production promotion.** The UI does not calibrate probabilities or prove model superiority. No main merge, Fly.io deployment, secret change or archive deletion.
