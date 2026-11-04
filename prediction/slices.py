"""Log loss / accuracy of the published site forecast vs the final model, by slice."""
import numpy as np, pandas as pd, model as M
p = pd.read_parquet("test_predictions.parquet")
f = pd.read_parquet("features.parquet", columns=["date_dt", "stage_type", "playoff_game_number", "h2h_n"])
f = f[f.date_dt >= "2022-01-01"].reset_index(drop=True)
assert len(f) == len(p)
y = M.target(p)
site = np.c_[p.site_pw, p.site_pd, 1 - p.site_pw - p.site_pd]
gbm = p[["gbm_pw", "gbm_pd", "gbm_pl"]].to_numpy()
sl = {
    "playoff": (f.stage_type.fillna("").eq("playoff") | f.playoff_game_number.notna()).map({True: "playoff", False: "group/round-robin"}),
    "fewer games of the two players": pd.cut(p.min_games, [-1, 0, 9, 49, 199, 1e9], labels=["debut", "1-9", "10-49", "50-199", "200+"]),
    "earlier meetings": pd.cut(f.h2h_n, [-1, 0, 4, 19, 1e9], labels=["0", "1-4", "5-19", "20+"]),
    "source": p.src,
    "year": p.date_dt.dt.year,
}
rows = []
for name, key in sl.items():
    for k in key.dropna().unique():
        m = (key == k).to_numpy()
        rows.append(dict(slice=name, value=str(k), n=int(m.sum()),
                         site_ll=M.logloss(site[m], y[m]), model_ll=M.logloss(gbm[m], y[m]),
                         site_acc=M.accuracy(site[m], y[m]), model_acc=M.accuracy(gbm[m], y[m])))
r = pd.DataFrame(rows).sort_values(["slice", "value"])
print(r.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
r.to_csv("slices.csv", index=False)
