def __init__(
    self,
    api_sports_key: str,
    api_sports_base: str,
    baseline_store: Optional[TeamBaselineStore] = None,
    min_baseline_games: int = 6,
):
    self.api_key = (api_sports_key or "").strip()
    self.base = (api_sports_base or "https://v1.basketball.api-sports.io").rstrip("/")
    self.session: Optional[aiohttp.ClientSession] = None
    self.cache = _TTLCache()

    # baseline store entegrasyonu (GERÇEK PROD)
    self.baseline_store = baseline_store
    self.min_baseline_games = min_baseline_games
    self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None

    if self.baseline_store is not None:
        self.baseline_bootstrapper = TeamBaselineBootstrapper(
            self.baseline_store, None
        )

    # BallDontLie
    self._bdl_api_key = (os.getenv("BALLDONTLIE_API_KEY") or "").strip()
    self._bdl_team_map: Optional[Dict[str, int]] = None 
