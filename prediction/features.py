"""Pre-game features for every game, computed in one pass in playing order.

Every value for game i uses only games before i in playing order, so nothing leaks from the
game itself or later games. Rating systems included:
  * the H2H site's Glicko-2 with goal difference and its head-to-head forecast (exact port of
    table-hockey-h2h-cloudflare/scripts/ratings.py), used as the main baseline
  * plain Elo, goal-difference Elo and a fast (high K) Elo
  * an online Poisson attack/defence model (expected goals for each side)
plus activity, form, draw tendency, head-to-head and in-tournament stats.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from numba import njit

# Site Glicko-2 settings (ratings.py)
SCALE = 173.7178
START_RD = 350.0
START_VOL = 0.3
TAU = 1.5
PERIOD_DAYS = 7.0
GOAL_SCALE = 0.4
FORECAST_BETA = 2.1396
FORECAST_CUT = 0.2933
H2H_WEIGHT = 1.0947
H2H_PRIOR = 20.0
PHI_MAX = START_RD / SCALE
PI2 = math.pi ** 2

SIDE_COLS = [
    "g_mu", "g_phi", "g_sigma", "elo", "elo_gd", "elo_fast", "att", "dfn",
    "n_games", "days_since", "activity", "form_short", "form_long", "draw_rate",
    "goals_rate", "gd_rate", "t_games", "t_resid", "t_gd", "upset_rate",
]
PAIR_COLS = [
    "site_x", "site_edge", "h2h_n", "h2h_score", "h2h_gd", "h2h_ewm", "h2h_days",
    "h2h_last", "poi_lam_a", "poi_lam_b", "base_goals",
]


@njit(cache=True)
def _g(phi):
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / PI2)


@njit(cache=True)
def _new_vol(sigma, phi, v, delta):
    a = math.log(sigma * sigma)
    tau2 = TAU * TAU
    phi2 = phi * phi
    d2 = delta * delta

    def f(x):
        ex = math.exp(x)
        den = phi2 + v + ex
        return ex * (d2 - phi2 - v - ex) / (2.0 * den * den) - (x - a) / tau2

    low = a
    if d2 > phi2 + v:
        high = math.log(d2 - phi2 - v)
    else:
        k = 1
        while f(a - k * TAU) < 0:
            k += 1
        high = a - k * TAU
    fl = f(low)
    fh = f(high)
    for _ in range(60):
        if abs(high - low) <= 1e-6:
            break
        mid = low + (low - high) * fl / (fh - fl)
        fm = f(mid)
        if fm * fh <= 0:
            low, fl = high, fh
        else:
            fl /= 2.0
        high, fh = mid, fm
    return math.exp(low / 2.0)


@njit(cache=True)
def _run(pa, pb, ga, gb, day, tour, pair, n_players, n_pairs):
    n = pa.shape[0]
    S = 20
    side = np.full((n, 2, S), np.nan)
    pf = np.full((n, 11), np.nan)

    mu = np.zeros(n_players)
    phi = np.full(n_players, PHI_MAX)
    sig = np.full(n_players, START_VOL)
    last = np.full(n_players, -1)
    elo = np.full(n_players, 1500.0)
    elo_gd = np.full(n_players, 1500.0)
    elo_f = np.full(n_players, 1500.0)
    att = np.zeros(n_players)
    dfn = np.zeros(n_players)
    ng = np.zeros(n_players)
    act = np.zeros(n_players)
    form_s = np.zeros(n_players)
    form_l = np.zeros(n_players)
    draw_r = np.full(n_players, 0.1)
    goals_r = np.full(n_players, 5.0)
    gd_r = np.zeros(n_players)
    upset = np.zeros(n_players)
    cur_t = np.full(n_players, -1)
    t_n = np.zeros(n_players)
    t_res = np.zeros(n_players)
    t_gd = np.zeros(n_players)

    p_tot = np.zeros(n_pairs)  # site pair edge numerator, low-id side
    p_n = np.zeros(n_pairs)
    p_sc = np.zeros(n_pairs)   # low-id side points minus high-id side
    p_gd = np.zeros(n_pairs)
    p_ewm = np.zeros(n_pairs)
    p_last = np.full(n_pairs, -1)
    p_lastres = np.zeros(n_pairs)
    base = math.log(2.7)

    for i in range(n):
        a = pa[i]
        b = pb[i]
        d = day[i]
        t = tour[i]
        k = pair[i]
        lo_is_a = a < b
        sgn = 1.0 if lo_is_a else -1.0

        pre = np.empty(2)
        for j in range(2):
            p = a if j == 0 else b
            ph = phi[p]
            if last[p] >= 0:
                el = max(0, d - last[p])
                ph = min(PHI_MAX, math.sqrt(ph * ph + sig[p] * sig[p] * (1.0 + el / PERIOD_DAYS)))
            pre[j] = ph
            if cur_t[p] != t:
                cur_t[p] = t
                t_n[p] = 0.0
                t_res[p] = 0.0
                t_gd[p] = 0.0
            el2 = (d - last[p]) if last[p] >= 0 else 10000
            s = side[i, j]
            s[0] = mu[p]
            s[1] = ph
            s[2] = sig[p]
            s[3] = elo[p]
            s[4] = elo_gd[p]
            s[5] = elo_f[p]
            s[6] = att[p]
            s[7] = dfn[p]
            s[8] = ng[p]
            s[9] = el2
            s[10] = act[p] * math.exp(-max(el2, 0) / 365.0)
            s[11] = form_s[p]
            s[12] = form_l[p]
            s[13] = draw_r[p]
            s[14] = goals_r[p]
            s[15] = gd_r[p]
            s[16] = t_n[p]
            s[17] = t_res[p]
            s[18] = t_gd[p]
            s[19] = upset[p]

        # site forecast (ratings + pair edge)
        x = _g(math.sqrt(pre[0] * pre[0] + pre[1] * pre[1])) * (mu[a] - mu[b])
        edge = sgn * p_tot[k] / (p_n[k] + H2H_PRIOR)
        pf[i, 0] = x
        pf[i, 1] = edge
        pf[i, 2] = p_n[k]
        pf[i, 3] = sgn * p_sc[k]
        pf[i, 4] = sgn * p_gd[k]
        pf[i, 5] = sgn * p_ewm[k]
        pf[i, 6] = (d - p_last[k]) if p_last[k] >= 0 else 10000
        pf[i, 7] = sgn * p_lastres[k]
        la = math.exp(base + att[a] - dfn[b])
        lb = math.exp(base + att[b] - dfn[a])
        pf[i, 8] = la
        pf[i, 9] = lb
        pf[i, 10] = math.exp(base)

        # ---- outcome
        g1 = ga[i]
        g2 = gb[i]
        gd = g1 - g2
        res = 1.0 if gd > 0 else (0.0 if gd < 0 else 0.5)
        win = 1.0 / (1.0 + math.exp(-(FORECAST_BETA * x - FORECAST_CUT)))
        loss = 1.0 / (1.0 + math.exp(-(-FORECAST_BETA * x - FORECAST_CUT)))
        exp_a = win + 0.5 * (1.0 - win - loss)
        surprise = res - exp_a

        # pair stats
        p_tot[k] += sgn * surprise
        p_n[k] += 1
        p_sc[k] += sgn * (2 * res - 1)
        p_gd[k] += sgn * gd
        p_ewm[k] = 0.8 * p_ewm[k] + 0.2 * sgn * surprise
        p_last[k] = d
        p_lastres[k] = sgn * (2 * res - 1)

        # Glicko-2 GD update (site)
        score_a = 1.0 / (1.0 + math.exp(-GOAL_SCALE * gd))
        nm = np.empty(2)
        nphi = np.empty(2)
        nsig = np.empty(2)
        for j in range(2):
            p = a if j == 0 else b
            o = b if j == 0 else a
            sc = score_a if j == 0 else 1.0 - score_a
            ph = pre[j]
            gg = _g(pre[1 - j])
            e = 1.0 / (1.0 + math.exp(-gg * (mu[p] - mu[o])))
            v = 1.0 / (gg * gg * e * (1.0 - e))
            delta = v * gg * (sc - e)
            nsig[j] = _new_vol(sig[p], ph, v, delta)
            nphi[j] = 1.0 / math.sqrt(1.0 / (ph * ph) + 1.0 / v)
            nm[j] = mu[p] + nphi[j] * nphi[j] * gg * (sc - e)

        # Elo variants
        ee = 1.0 / (1.0 + 10.0 ** ((elo[b] - elo[a]) / 400.0))
        elo[a] += 24.0 * (res - ee)
        elo[b] -= 24.0 * (res - ee)
        eg = 1.0 / (1.0 + 10.0 ** ((elo_gd[b] - elo_gd[a]) / 400.0))
        mult = 1.0 + math.log(1.0 + abs(gd))
        elo_gd[a] += 16.0 * mult * (res - eg)
        elo_gd[b] -= 16.0 * mult * (res - eg)
        ef = 1.0 / (1.0 + 10.0 ** ((elo_f[b] - elo_f[a]) / 400.0))
        elo_f[a] += 64.0 * (res - ef)
        elo_f[b] -= 64.0 * (res - ef)

        # Poisson attack/defence (capped goals to limit odd scores)
        c1 = min(g1, 15)
        c2 = min(g2, 15)
        lr_a = 0.06 / math.sqrt(1.0 + ng[a] / 20.0) + 0.01
        lr_b = 0.06 / math.sqrt(1.0 + ng[b] / 20.0) + 0.01
        r1 = c1 - la
        r2 = c2 - lb
        att[a] += lr_a * r1 / max(la, 1.0)
        dfn[b] -= lr_b * r1 / max(la, 1.0)
        att[b] += lr_b * r2 / max(lb, 1.0)
        dfn[a] -= lr_a * r2 / max(lb, 1.0)
        base += 0.0005 * ((r1 / max(la, 1.0)) + (r2 / max(lb, 1.0)))

        for j in range(2):
            p = a if j == 0 else b
            r = res if j == 0 else 1.0 - res
            sp = surprise if j == 0 else -surprise
            el2 = (d - last[p]) if last[p] >= 0 else 0
            mu[p] = nm[j]
            phi[p] = nphi[j]
            sig[p] = nsig[j]
            act[p] = act[p] * math.exp(-max(el2, 0) / 365.0) + 1.0
            last[p] = d
            ng[p] += 1
            form_s[p] = 0.9 * form_s[p] + 0.1 * sp
            form_l[p] = 0.98 * form_l[p] + 0.02 * sp
            draw_r[p] = 0.97 * draw_r[p] + 0.03 * (1.0 if gd == 0 else 0.0)
            goals_r[p] = 0.97 * goals_r[p] + 0.03 * (g1 + g2)
            gd_r[p] = 0.95 * gd_r[p] + 0.05 * (gd if j == 0 else -gd)
            exp_p = exp_a if j == 0 else 1.0 - exp_a
            upset[p] = 0.97 * upset[p] + 0.03 * abs(r - exp_p)
            t_n[p] += 1
            t_res[p] += sp
            t_gd[p] += gd if j == 0 else -gd
    return side, pf


def compute(games: pd.DataFrame) -> pd.DataFrame:
    """games must be in playing order. Returns a frame of pre-game features (same index)."""
    ids = pd.concat([games.player1_id, games.player2_id]).unique()
    idx = pd.Series(np.arange(len(ids)), index=ids)
    pa = idx.loc[games.player1_id].to_numpy(np.int64)
    pb = idx.loc[games.player2_id].to_numpy(np.int64)
    lo = np.minimum(pa, pb)
    hi = np.maximum(pa, pb)
    pair = pd.factorize(lo * len(ids) + hi)[0].astype(np.int64)
    tkey = games.tournament_id.astype("Float64").fillna(-1).astype(str) + "|" + games.date_dt.dt.strftime("%Y%m%d").where(games.tournament_id.isna(), "")
    tour = pd.factorize(tkey)[0].astype(np.int64)
    day = ((games.date_dt - pd.Timestamp("1970-01-01")).dt.days).to_numpy(np.int64)
    side, pf = _run(pa, pb, games.goals_player1.to_numpy(np.int64), games.goals_player2.to_numpy(np.int64),
                    day, tour, pair, len(ids), int(pair.max()) + 1)
    out = {}
    for j, s in enumerate("ab"):
        for c, name in enumerate(SIDE_COLS):
            out[f"{name}_{s}"] = side[:, j, c]
    for c, name in enumerate(PAIR_COLS):
        out[name] = pf[:, c]
    return pd.DataFrame(out, index=games.index)


def site_probs(x, edge):
    """The site's published forecast (win, draw, loss) from its Glicko-2 term and pair edge."""
    z = x + H2H_WEIGHT * edge
    w = 1 / (1 + np.exp(-(FORECAST_BETA * z - FORECAST_CUT)))
    l = 1 / (1 + np.exp(-(-FORECAST_BETA * z - FORECAST_CUT)))
    return np.stack([w, 1 - w - l, l], axis=1)
