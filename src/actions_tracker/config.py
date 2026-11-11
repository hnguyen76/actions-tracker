"""Project-wide settings and thresholds (see spec §2, §3, §7)."""

LEAGUES: dict[str, bool] = {
    "nfl": True,
    "ncaaf": True,
    "nba": True,
    "mlb": False,
    "nhl": False,
    "ncaab": False,
}

PICKS_URL = "https://www.actionnetwork.com/{league}/picks"
BYGAME_URL = "https://www.actionnetwork.com/{league}/picks/game?id={game_id}"

MIN_EXPERTS = 3
MIN_SAMPLE = 20
HEAVY_PUBLIC = 65
MONEY_TICKET_GAP = 15
DEFAULT_ODDS = -110
BUCKETS = [(50, 60, "50-60"), (60, 75, "60-75"), (75, 90, "75-90"), (90, 100.01, "90-100")]
TZ = "America/New_York"
FORM_UNITS = 3.0  # expert is "dang xanh" at >= +3u (or "dang do" at <= -3u) over the league's last 30 days
FORM_STREAK_LONG = 3  # a win/loss streak of 3+ counts as long

# Action Network pick `type` -> (market, side)
KEEP_TYPES: dict[str, tuple[str, str]] = {
    "spread_home": ("spread", "home"),
    "spread_away": ("spread", "away"),
    "ml_home": ("ml", "home"),
    "ml_away": ("ml", "away"),
    "over": ("total", "over"),
    "under": ("total", "under"),
}
