# ZEYNAL production release request — 2026-11-20

Approved scope: production read-only news-source integration and exact club
identity fixes from merged PR #122. Do not alter model coefficients,
calibration, immutable forecasts, DB schema or the persistent `/data` volume.

The existing protected workflow recognizes a historical one-shot commit
subject `ZEYNAL_PRODUCTION_RELEASE_20261119`. This document records why
that compatibility marker is being used for the 2026-11-20 release.

Release gates are mandatory:
- Re-run Python and Docker CI on the exact main commit.
- Confirm existing Fly.io AMS machine + original attached volume.
- Confirm a recoverable existing volume snapshot.
- Update only the existing machine, with a preserved previous image.
- Check /ready release SHA and Telegram polling.
- Roll back to the old image on unsuccessful smoke checks.
- Real Telegram message delivery and live article quality remain separately
  unverified until observed from the actual Telegram interface.

New command: `/injurynews EUROLEAGUE Zalgiris Kaunas vs Panathinaikos AKTOR Athens`
(read-only current news, **not** an official fixture availability certificate).
RotoWire remains disabled, and article text candidates are not model input.
