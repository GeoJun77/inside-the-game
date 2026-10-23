"""matchsim - synthetic, Premier League-calibrated football match generator."""
from .engine import MatchSimulator, simulate_match
from .ratings import player_match_stats
from .stats import team_stats
from .stream import areplay, replay
from .teams import LEAGUE_NAME, PLAYER_OF_THE_SEASON_AWARD, build_league, get_team, select_matchday_squad

__all__ = ["MatchSimulator", "simulate_match", "player_match_stats", "team_stats", "areplay", "replay",
           "LEAGUE_NAME", "PLAYER_OF_THE_SEASON_AWARD", "build_league", "get_team", "select_matchday_squad"]
