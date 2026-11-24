# NBA integrated release candidate — 24 November 2026

Base: #160 f4598b377509a4835898ba7e812c0637385c60fa (includes #158/#159 branch ancestry). Three-axis files imported from #161 860fdb8c183a34e7796fd1678a944762522d5817 without replacing unrelated base files. Main is not changed. This is a staging candidate, not a production deployment.

## Gates
- Existing frozen first forecasts unchanged; read-only audit from n=1. 74/71/3 user-reported; generic shadow MAE 16.43 → 16.64 rejected.
- Team-specific research MAE approximately 16.434 → 16.205 on historical replay (about 1.39% improvement; margin regressed). Total-only improvement cannot conceal margin or team degradation. Screening guard checks 2% relative total MAE plus component MAE/RMSE, always keeps production disabled; not an automatic promotion.
- Quarters and player paired sample reported as 0; no evidence of improvement. No invented minutes, no backfill after forecast.
- Player evidence at T−300 or later cannot enter prospective candidate; T−301 only passes time gate and still requires source replay. Existing five-minute publication policy remains unchanged.
- Required: combined unit/Docker CI at exact SHA, native UserLAnd audit with pinned frozen assets/player directory, actual Telegram staging delivery, Fly deployment SHA/mount/restart/cutoff verification. No main merge or Fly deployment until gates pass. Historical replay cannot establish independent prospective model validity.
