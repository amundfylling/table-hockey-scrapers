"""Design matrix, symmetric augmentation and evaluation helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import skellam

import features as F

ANTI = ["site_x", "site_edge", "h2h_score", "h2h_gd", "h2h_ewm", "h2h_last"]


def target(df):
    gd = df.goals_player1.to_numpy() - df.goals_player2.to_numpy()
    return np.where(gd > 0, 0, np.where(gd == 0, 1, 2))


def flip(df):
    """The same games seen from player 2's side."""
    out = df.copy()
    for c in F.SIDE_COLS:
        out[f"{c}_a"], out[f"{c}_b"] = df[f"{c}_b"].to_numpy(), df[f"{c}_a"].to_numpy()
    for c in ANTI:
        out[c] = -df[c]
    out["poi_lam_a"], out["poi_lam_b"] = df.poi_lam_b.to_numpy(), df.poi_lam_a.to_numpy()
    out["goals_player1"], out["goals_player2"] = df.goals_player2.to_numpy(), df.goals_player1.to_numpy()
    return out


def design(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    site = F.site_probs(df.site_x.to_numpy(), df.site_edge.to_numpy())
    X["site_pw"], X["site_pd"] = site[:, 0], site[:, 1]
    X["site_z"] = df.site_x + F.H2H_WEIGHT * df.site_edge
    for c in ["site_x", "site_edge", "h2h_n", "h2h_score", "h2h_gd", "h2h_ewm", "h2h_days", "h2h_last",
              "base_goals"]:
        X[c] = df[c]
    for c in F.SIDE_COLS:
        X[f"{c}_a"] = df[f"{c}_a"]
        X[f"{c}_b"] = df[f"{c}_b"]
    for c in ["g_mu", "elo", "elo_gd", "elo_fast", "att", "dfn", "form_short", "form_long",
              "t_resid", "t_gd", "gd_rate"]:
        X[f"d_{c}"] = df[f"{c}_a"] - df[f"{c}_b"]
    X["phi_comb"] = np.sqrt(df.g_phi_a ** 2 + df.g_phi_b ** 2)
    X["min_games"] = np.minimum(df.n_games_a, df.n_games_b)
    X["lam_a"], X["lam_b"] = df.poi_lam_a, df.poi_lam_b
    X["lam_ratio"] = np.log(df.poi_lam_a / df.poi_lam_b)
    la, lb = df.poi_lam_a.to_numpy(), df.poi_lam_b.to_numpy()
    X["poi_pd"] = skellam.pmf(0, la, lb)
    X["poi_pw"] = skellam.sf(0, la, lb)
    # context known before the game
    X["playoff"] = (df.stage_type.fillna("").eq("playoff") | df.playoff_game_number.notna()).astype(int)
    X["po_game"] = df.playoff_game_number.astype("Float64").fillna(0).astype(float)
    X["level"] = pd.to_numeric(df.tournament_level, errors="coerce")
    X["stage_seq"] = df.stage_sequence.astype("Float64").astype(float)
    X["year"] = df.date_dt.dt.year + df.date_dt.dt.dayofyear / 366
    X["src"] = df.src.astype("category").cat.set_categories(
        ["sportscorpion", "bordshockey_results", "trefik_results", "galdahokejs_results",
         "escore_results", "table_hockey_eu_results"]).cat.codes
    return X.astype("float32")


def logloss(p, y):
    p = np.clip(p, 1e-12, 1)
    p = p / p.sum(1, keepdims=True)
    return float(-np.mean(np.log(p[np.arange(len(y)), y])))


def brier(p, y):
    oh = np.eye(3)[y]
    return float(np.mean(((p - oh) ** 2).sum(1)))


def rps(p, y):
    """Ranked probability score (outcomes are ordered win > draw > loss)."""
    oh = np.eye(3)[y]
    cp, co = np.cumsum(p, 1)[:, :2], np.cumsum(oh, 1)[:, :2]
    return float(np.mean(((cp - co) ** 2).sum(1) / 2))


def accuracy(p, y):
    return float(np.mean(p.argmax(1) == y))


def report(name, p, y):
    return dict(model=name, log_loss=logloss(p, y), accuracy=accuracy(p, y), brier=brier(p, y),
                rps=rps(p, y), n=len(y))
