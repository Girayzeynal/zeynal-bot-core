"""Operational timing for prospective NBA and European research.

Publication must finish before the five-minute tipoff boundary. This does not
alter historical forecasts or permit post-tipoff fitting. A missing or expired
source still abstains independently of these upper time budgets.
"""

PREMATCH_MINIMUM_LEAD_SECONDS = 5 * 60
V3_REFRESH_SECONDS = 30 * 60
V3_FRESHNESS_SECONDS = 45 * 60
MAXIMUM_V3_MODEL_AGE_SECONDS = 24 * 3600
MODEL_AGE_WARNING_SECONDS = 6 * 3600
RESEARCH_POLL_SECONDS = 60

assert 0 < PREMATCH_MINIMUM_LEAD_SECONDS < V3_REFRESH_SECONDS
assert V3_REFRESH_SECONDS < V3_FRESHNESS_SECONDS <= MAXIMUM_V3_MODEL_AGE_SECONDS
