"""2020 -> 2024 shift EI: regional group swing patterns (plan §6.6 'Shift EI')."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings, load_config
from ..ingest._base import processed_dir, stamp, write_parquet
from . import inputs as I
from .diagnostics import diagnose
from .groups import build_county_groups
from .model_rxc import logit


def build_shift_model(g: dict):
    """Joint level + change model.

    logit theta20_ig = mu_g + x_i.beta_g + u_{r(i)g} + eps_ig
    logit theta24_ig = logit theta20_ig + delta_g + d_{r(i)g} + x_i.gamma_g + nu_ig
    V^D,20_i ~ N(sum n20 theta20, phi20 V20), V^D,24_i ~ N(sum n24 theta24, phi24 V24).
    """
    import pymc as pm

    I_, G = g["n24"].shape
    J = g["x"].shape[1]
    coords = {"county": g["geoid"], "group": g["groups"], "region": g["regions"]}
    with pm.Model(coords=coords) as m:
        mu = pm.Normal("mu", logit(g["mu_prior"]), g["sd_prior"], dims="group")
        beta = pm.Normal("beta", 0.0, 0.5, shape=(G, J))
        tau_u, tau_e = pm.HalfNormal("tau_u", 0.5), pm.HalfNormal("tau_e", 0.5)
        u = pm.Normal("u_raw", 0.0, 1.0, dims=("region", "group")) * tau_u
        eps = pm.Normal("eps_raw", 0.0, 1.0, dims=("county", "group")) * tau_e
        eta20 = mu[None, :] + u[g["region_idx"]] + pm.math.dot(g["x"], beta.T) + eps
        dg = pm.Normal("delta_g", 0.0, 0.5, dims="group")
        tau_d, tau_n = pm.HalfNormal("tau_d", 0.3), pm.HalfNormal("tau_n", 0.3)
        dr = pm.Normal("delta_r_raw", 0.0, 1.0, dims=("region", "group")) * tau_d
        gam = pm.Normal("gamma", 0.0, 0.3, shape=(G, J))
        nu = pm.Normal("nu_raw", 0.0, 1.0, dims=("county", "group")) * tau_n
        delta = dg[None, :] + dr[g["region_idx"]] + pm.math.dot(g["x"], gam.T) + nu
        th20 = pm.Deterministic("theta20", pm.math.sigmoid(eta20), dims=("county", "group"))
        th24 = pm.Deterministic("theta24", pm.math.sigmoid(eta20 + delta), dims=("county", "group"))
        pm.Deterministic("delta_rg", dg[None, :] + dr, dims=("region", "group"))
        ph20, ph24 = pm.HalfNormal("phi20", 25.0), pm.HalfNormal("phi24", 25.0)
        pm.Normal("vd20", (g["n20"] * th20).sum(axis=1), pm.math.sqrt(ph20 * g["v20"]), observed=g["vd20"])
        pm.Normal("vd24", (g["n24"] * th24).sum(axis=1), pm.math.sqrt(ph24 * g["v24"]), observed=g["vd24"])
    return m


def shift_summary(idata, g: dict, draws_kept: int = 200, seed: int = 0) -> pd.DataFrame:
    """Region x group margin-point swing (D margin 2024 minus 2020, n24-weighted over counties) from posterior draws."""
    post = idata.posterior
    t20 = post["theta20"].stack(s=("chain", "draw")).transpose("county", "group", "s").values
    t24 = post["theta24"].stack(s=("chain", "draw")).transpose("county", "group", "s").values
    rng = np.random.default_rng(seed)
    keep = rng.choice(t20.shape[2], size=min(draws_kept, t20.shape[2]), replace=False)
    t20, t24 = t20[:, :, keep], t24[:, :, keep]
    n = g["n24"][:, :, None]
    rows = []
    for ri, r in enumerate(g["regions"]):
        sel = g["region_idx"] == ri
        w = n[sel].sum(axis=0)  # group x 1
        d20 = (n[sel] * t20[sel]).sum(axis=0) / w
        d24 = (n[sel] * t24[sel]).sum(axis=0) / w
        dm = 200.0 * (d24 - d20)  # margin points = 100*(2*th24-1) - 100*(2*th20-1)
        for gi, grp in enumerate(g["groups"]):
            rows.append({"region": r, "group": grp, "delta_mean": float(dm[gi].mean()),
                         "delta_sd": float(dm[gi].std(ddof=1)), "n_group": float(w[gi, 0]),
                         "theta24": float(d24[gi].mean())})
    return pd.DataFrame(rows)


def run_shift(cfg: Settings | None = None, states: list[str] | None = None, thin_draws: int | None = None) -> pd.DataFrame:
    """`make ei` second stage: fit the shift model on all race-state counties, write processed/ei_shift_2024.parquet."""
    import pymc as pm

    cfg = cfg or load_config()
    inp = I.load_inputs(cfg, states)
    gt24 = I.build_group_table(inp, cfg, 2024)
    gt20 = I.build_group_table(inp, cfg, 2020)
    geoid = inp["v24"].geoid.to_numpy()
    grp = cfg.ei.groups
    n24 = gt24.pivot(index="geoid", columns="group", values="n_group")[grp].reindex(geoid).to_numpy()
    n20 = gt20.pivot(index="geoid", columns="group", values="n_group")[grp].reindex(geoid).to_numpy()
    gg = inp["geo"].set_index("geoid").reindex(geoid)
    regions = sorted(gg.region.unique())
    x = inp["cov"].reindex(geoid)
    x = x.sub(x.mean()).div(x.std(ddof=0).replace(0, 1))
    pr = I.group_priors(I.load_validated(), grp)
    g = {"geoid": geoid, "groups": grp, "regions": regions, "n24": n24, "n20": n20, "x": x.to_numpy(float),
         "region_idx": gg.region.map({r: i for i, r in enumerate(regions)}).to_numpy(),
         "vd24": inp["v24"].votes_d.to_numpy(float), "v24": (inp["v24"].votes_d + inp["v24"].votes_r).to_numpy(float),
         "vd20": inp["v20"].votes_d.to_numpy(float), "v20": (inp["v20"].votes_d + inp["v20"].votes_r).to_numpy(float),
         "mu_prior": pr.mu.to_numpy(), "sd_prior": pr.sd.to_numpy()}
    s = cfg.ei.sampler
    with build_shift_model(g):
        try:
            import numpyro  # noqa: F401
            kw = {"nuts_sampler": "numpyro", "cores": 1, "nuts_sampler_kwargs": {"chain_method": "vectorized"}}
        except ImportError:
            kw = {"cores": s.chains}
        idata = pm.sample(draws=thin_draws or s.draws, tune=s.tune, chains=s.chains, target_accept=s.target_accept,
                          random_seed=s.seed, progressbar=False, **kw)
    dg = diagnose(idata, ["mu", "tau_u", "tau_e", "tau_d", "tau_n", "phi20", "phi24", "delta_g"])
    out = shift_summary(idata, g)
    out["rhat_max"], out["ess_min"] = dg.rhat_max, min(dg.ess_bulk_min, dg.ess_tail_min)
    out["divergences"] = dg.divergences
    out = stamp(out, "ei:shift_ei", "phase3-0", "ok" if dg.passes(cfg.ei.rhat_max, cfg.ei.ess_min) else "manual")
    write_parquet(out, processed_dir() / "ei_shift_2024.parquet")
    return out


def group_pattern(shift: pd.DataFrame, reg_w: pd.DataFrame) -> pd.DataFrame:
    """pattern_{r,g} = delta_{r,g} - sum_g' w_{r,g'} delta_{r,g'}: deviations from the regional average swing.

    Groups that moved more than average 2020->2024 in a region are assumed to move more than average again. Returns
    region x group; the persistence factor ei.pattern_persistence is applied by the caller (hier_model prior)."""
    d = shift.pivot(index="region", columns="group", values="delta_mean")
    w = reg_w.reindex(index=d.index, columns=d.columns)
    return d.sub((w * d).sum(axis=1), axis=0)
