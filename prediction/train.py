"""Chronological evaluation: fit on games before 2021, early-stop on 2021, test on 2022+.

python train.py [--train-from 2005] [--test-from 2022-01-01] [--quick]
"""
from __future__ import annotations

import argparse
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize

import model as M

ap = argparse.ArgumentParser()
ap.add_argument("--train-from", default="2005-01-01")
ap.add_argument("--valid-from", default="2021-01-01")
ap.add_argument("--test-from", default="2022-01-01")
ap.add_argument("--quick", action="store_true")
ap.add_argument("--out", default="results.json")
args = ap.parse_args()

t0 = time.time()
df = pd.read_parquet("features.parquet")
df = df[df.date_dt >= args.train_from].reset_index(drop=True)
tr = df[df.date_dt < args.valid_from]
va = df[(df.date_dt >= args.valid_from) & (df.date_dt < args.test_from)]
te = df[df.date_dt >= args.test_from]
if args.quick:
    tr = tr.sample(frac=0.25, random_state=0)
print(f"train {len(tr)}  valid {len(va)}  test {len(te)}")
y_te = M.target(te)
results = []


def sym_predict(fn, d):
    p = fn(d)
    q = fn(M.flip(d))[:, ::-1]
    return (p + q) / 2


# ---- baselines -----------------------------------------------------------
draw = np.mean(M.target(tr) == 1)
results.append(M.report("constant (W/L 50-50, train draw rate)",
                        np.tile([(1 - draw) / 2, draw, (1 - draw) / 2], (len(te), 1)), y_te))
site = M.design(te)[["site_pw", "site_pd"]].to_numpy()
results.append(M.report("site Glicko-2 + H2H (as published)",
                        np.c_[site, 1 - site.sum(1)], y_te))


def ordered_logit(x_tr, y_tr):
    def nll(w):
        z = w[0] * x_tr
        pw = 1 / (1 + np.exp(-(z - w[1])))
        pl = 1 / (1 + np.exp(-(-z - w[1])))
        p = np.c_[pw, 1 - pw - pl, pl]
        return M.logloss(p, y_tr)
    w = minimize(nll, [1.0, 0.3], method="Nelder-Mead").x

    def pred(x):
        z = w[0] * x
        pw = 1 / (1 + np.exp(-(z - w[1])))
        pl = 1 / (1 + np.exp(-(-z - w[1])))
        return np.c_[pw, 1 - pw - pl, pl]
    return pred


fit_on = pd.concat([tr, va])
y_fit = M.target(fit_on)
for name, col, scale in [("Elo K=24, refit draw model", "elo", 1 / 400),
                         ("goal-difference Elo, refit draw model", "elo_gd", 1 / 400),
                         ("site Glicko-2 + H2H, refit draw model", None, 1.0)]:
    if col:
        x_f = (fit_on[f"{col}_a"] - fit_on[f"{col}_b"]).to_numpy() * scale
        x_t = (te[f"{col}_a"] - te[f"{col}_b"]).to_numpy() * scale
    else:
        x_f = (fit_on.site_x + M.F.H2H_WEIGHT * fit_on.site_edge).to_numpy()
        x_t = (te.site_x + M.F.H2H_WEIGHT * te.site_edge).to_numpy()
    results.append(M.report(name, ordered_logit(x_f, y_fit)(x_t), y_te))

# ---- multinomial logistic regression on a few rating features -------------
from sklearn.linear_model import LogisticRegression  # noqa: E402

lin_cols = ["site_z", "d_elo", "d_elo_gd", "d_elo_fast", "lam_ratio", "d_form_short", "d_t_resid"]


def lin_X(d):
    X = M.design(d)[lin_cols].copy()
    X["d_elo"] /= 400
    X["d_elo_gd"] /= 400
    X["d_elo_fast"] /= 400
    return X.fillna(0).to_numpy()


fa = pd.concat([fit_on, M.flip(fit_on)])
lr = LogisticRegression(max_iter=500).fit(lin_X(fa), M.target(fa))
results.append(M.report("logistic regression on ratings + form",
                        sym_predict(lambda d: lr.predict_proba(lin_X(d)), te), y_te))
print(f"baselines done {time.time() - t0:.0f}s")

# ---- gradient boosting ------------------------------------------------------
params = dict(objective="multiclass", num_class=3, learning_rate=0.05, num_leaves=127,
              min_data_in_leaf=400, feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1,
              lambda_l2=10.0, verbose=-1, num_threads=4)
tr2 = pd.concat([tr, M.flip(tr)])
va2 = pd.concat([va, M.flip(va)])
fa2 = pd.concat([fit_on, M.flip(fit_on)])
D_tr, D_va, D_fa = M.design(tr2), M.design(va2), M.design(fa2)
CONTEXT = ["playoff", "po_game", "level", "stage_seq", "year", "src"]
ALL = list(D_tr.columns)
variants = [
    ("site Glicko-2 + H2H, context-aware calibration (GBM on site_z + context)",
     ["site_z", "site_x", "site_edge", "phi_comb"] + CONTEXT),
    ("LightGBM, all features except context", [c for c in ALL if c not in CONTEXT]),
    ("LightGBM, all features", ALL),
]
best = None
for name, cols in variants:
    cat = ["src"] if "src" in cols else "auto"
    dtr = lgb.Dataset(D_tr[cols], M.target(tr2), categorical_feature=cat)
    dva = lgb.Dataset(D_va[cols], M.target(va2), reference=dtr)
    bst = lgb.train(params, dtr, 3000, valid_sets=[dva],
                    callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    it = bst.best_iteration
    bst2 = lgb.train(params, lgb.Dataset(D_fa[cols], M.target(fa2), categorical_feature=cat),
                     int(it * 1.1))
    p = sym_predict(lambda d: bst2.predict(M.design(d)[cols]), te)
    results.append(M.report(name, p, y_te) | {"iterations": int(it * 1.1)})
    print(results[-1], f"{time.time() - t0:.0f}s", flush=True)
booster2, p_gbm2 = bst2, p
imp = pd.Series(booster2.feature_importance("gain"), index=booster2.feature_name()).sort_values(ascending=False)
res = pd.DataFrame(results)
print(res.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print(imp.head(30).round(0).to_string())

# slices: by player experience and by source
te_out = te[["date_dt", "src", "player1_id", "player2_id", "goals_player1", "goals_player2"]].copy()
te_out["site_pw"], te_out["site_pd"] = site[:, 0], site[:, 1]
te_out[["gbm_pw", "gbm_pd", "gbm_pl"]] = p_gbm2
te_out["min_games"] = np.minimum(te.n_games_a, te.n_games_b).to_numpy()
te_out.to_parquet("test_predictions.parquet", index=False)
json.dump(dict(results=results, importance=imp.head(40).round(1).to_dict(), 
               params=params, splits=vars(args)), open(args.out, "w"), indent=1, default=str)
booster2.save_model("lgbm_model.txt")
