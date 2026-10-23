"""Load the trained xG model and score shots, with a per-feature explanation.

The model is the scikit-learn pipeline saved by the training notebook
(notebooks/explore_shots.ipynb) as models/xg_model.joblib:
{"model": Pipeline(prep -> LogisticRegression), "numeric": [...], "boolean": [...], "categorical": [...]}.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .features import shot_features

PENALTY_XG = 0.76
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "xg_model.joblib"

# Plain-English names used in explanations (agents turn these into commentary).
FEATURE_LABELS = {
    "distance": "distance to goal",
    "angle": "shooting angle",
    "nearest_defender_dist": "space from the nearest defender",
    "n_defenders_in_cone": "defenders between the ball and the goal",
    "gk_distance_to_goal": "goalkeeper position",
    "under_pressure": "pressure on the shooter",
    "shot_first_time": "first-time finish",
    "shot_one_on_one": "one-on-one with the keeper",
    "shot_aerial_won": "contested header",
    "shot_body_part": "body part",
    "shot_type": "shot type",
    "shot_technique": "technique",
    "assist_type": "type of assist",
}


class XGModel:
    def __init__(self, path: str | Path = DEFAULT_MODEL_PATH):
        import joblib

        bundle = joblib.load(path)
        self.pipeline = bundle["model"]
        self.numeric = bundle["numeric"]
        self.boolean = bundle["boolean"]
        self.categorical = bundle["categorical"]
        self.columns = self.numeric + self.boolean + self.categorical
        self._prep = self.pipeline.named_steps["prep"]
        self._clf = self.pipeline.named_steps["model"]
        self._names = list(self._prep.get_feature_names_out())
        self._coef = dict(zip(self._names, self._clf.coef_[0]))
        # reference = a typical real shot: frequency-weighted weight of each categorical
        # group and average rate of each flag (see xg/reference.py)
        from .reference import REFERENCE
        self._bool_rate = REFERENCE["boolean"]
        self._cat_mean = {}
        for c in self.categorical:
            freqs = REFERENCE["categorical"].get(c, {})
            pairs = [(self._coef[f"cat__{c}_{v}"], f) for v, f in freqs.items() if f"cat__{c}_{v}" in self._coef]
            total = sum(f for _, f in pairs)
            self._cat_mean[c] = sum(w * f for w, f in pairs) / total if total else 0.0

    def predict_features(self, feats: dict) -> float:
        row = pd.DataFrame([{c: feats[c] for c in self.columns}])
        return float(self.pipeline.predict_proba(row)[0, 1])

    def explain_features(self, feats: dict, top: int = 4) -> list[dict]:
        """Contribution of each input to the shot's log-odds, relative to an average shot.

        Logistic regression is additive in log-odds, so each feature's push up or down
        can be read directly: weight x standardized value for numbers, weight of the
        active category minus the average weight of its group for categories.
        """
        row = pd.DataFrame([{c: feats[c] for c in self.columns}])
        z = self._prep.transform(row)
        z = z.toarray()[0] if hasattr(z, "toarray") else z[0]
        values = dict(zip(self._names, z))
        out = []
        for c in self.numeric:
            n = f"num__{c}"
            out.append((c, self._coef[n] * values[n], feats[c]))
        for c in self.boolean:
            n = f"bool__{c}"
            out.append((c, self._coef[n] * (float(feats[c]) - self._bool_rate.get(c, 0.0)), bool(feats[c])))
        for c in self.categorical:
            n = f"cat__{c}_{feats[c]}"
            if n in self._coef:
                out.append((c, self._coef[n] - self._cat_mean[c], feats[c]))
        out.sort(key=lambda t: -abs(t[1]))
        return [
            {"feature": c, "label": FEATURE_LABELS.get(c, c), "value": _round(v),
             "effect": "increases" if w > 0 else "decreases", "log_odds": round(float(w), 3)}
            for c, w, v in out[:top]
        ]

    def score_shot(self, shot: dict, explain: bool = True) -> tuple[float, dict, list]:
        """Return (xG, features, explanation) for a StatsBomb-style shot dict."""
        feats = shot_features(shot)
        if shot["shot_type"] == "Penalty":
            return PENALTY_XG, feats, [{"feature": "shot_type", "label": "penalty", "value": "Penalty",
                                         "effect": "increases", "log_odds": 0.0}]
        xg = self.predict_features(feats)
        return xg, feats, (self.explain_features(feats) if explain else [])


def _round(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return v


@lru_cache(maxsize=1)
def load_default_model() -> XGModel | None:
    """The repo's model, or None when it is missing (the engine then falls back to a formula)."""
    try:
        return XGModel(DEFAULT_MODEL_PATH)
    except Exception:
        return None


def fallback_xg(feats: dict) -> float:
    """Simple geometric xG used only if the trained model file is unavailable."""
    logit = -1.4 + 0.035 * feats["angle"] - 0.09 * feats["distance"] - 0.35 * (feats["n_defenders_in_cone"] or 0)
    if feats["shot_body_part"] == "Head":
        logit -= 0.9
    return 1 / (1 + math.exp(-logit))
