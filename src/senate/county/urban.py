"""Urban / suburban / rural county term (MODEL_FIXES Task 4).

urban_term_i = beta_urban * (delta_class(i) - sum_c nu_c delta_c), nu_c = the state's vote-weighted class shares, so
the term is mean-zero inside each state before calibration. delta_c are the area-type swings from poll crosstabs
(z = poll margin - validated-voter 2024 margin), shrunk toward their precision-weighted mean.
Classification: NCHS 2023 Urban-Rural Classification Scheme if data/manual/nchs_urcs_2023.csv (columns fips, code) is
present (1 = urban, 2-3 = suburban, 4-6 = rural); otherwise terciles of county CVAP (a size proxy; there is no
land-area column in the repo, so population density is not available)."""
from __future__ import annotations

import numpy as np
import pandas as pd

CLASSES = ["urban", "suburban", "rural"]


def classify(geoids: pd.Index, cvap_total: pd.Series, nchs: pd.DataFrame | None = None) -> tuple[pd.Series, str]:
    """County -> urban/suburban/rural and the method used ('nchs2023' or 'cvap_terciles')."""
    if nchs is not None and len(nchs):
        code = nchs.assign(fips=nchs.fips.astype(str).str.zfill(5)).set_index("fips").code.astype(int)
        c = code.reindex(geoids)
        if c.notna().mean() > 0.95:
            lab = pd.cut(c, [0, 1, 3, 6], labels=CLASSES)
            return lab.astype(object).fillna("suburban").set_axis(geoids), "nchs2023"
    t = cvap_total.reindex(geoids).fillna(cvap_total.median())
    q = t.rank(pct=True)
    lab = pd.cut(q, [0, 1 / 3, 2 / 3, 1.0001], labels=["rural", "suburban", "urban"], include_lowest=True)
    return lab.astype(object).set_axis(geoids), "cvap_terciles"


def class_swings(cells: pd.DataFrame, tau0: float = 3.0) -> dict[str, dict]:
    """Area-type swing per class from harmonised cells (columns group, z, var, n_group): precision-weighted mean
    z per class, shrunk toward the pooled mean with prior SD tau0 (pts). Returns {class: {delta, sd, n}}."""
    if cells is None or cells.empty:
        return {}
    out = {}
    pooled = np.average(cells.z, weights=1 / cells["var"])
    for c, g in cells.groupby("group"):
        prec = (1 / g["var"]).sum()
        m = np.average(g.z, weights=1 / g["var"])
        post = (m * prec + pooled / tau0**2) / (prec + 1 / tau0**2)
        out[str(c)] = {"delta": float(post), "sd": float((prec + 1 / tau0**2) ** -0.5), "n": int(g.n_group.sum())}
    return out


def urban_terms(classes: pd.Series, nu: pd.Series, delta: dict[str, float], beta: float = 1.0) -> pd.Series:
    """One state's counties: beta * (delta_class(i) - nu-weighted mean delta). Classes without a delta count as the
    mean (zero term). nu: county vote weights (any scale)."""
    d = classes.map(delta).astype(float)
    w = nu.reindex(classes.index)
    known = d.notna()
    if not known.any():
        return pd.Series(0.0, index=classes.index)
    mean = float((d[known] * w[known]).sum() / w[known].sum())
    return beta * (d.fillna(mean) - mean)
