"""Run the EI model per state (small states pooled by census division) with joblib, caching and retry (plan §6.6)."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ingest._base import processed_dir, stamp, write_parquet
from . import inputs as I
from .diagnostics import diagnose
from .groups import DIVISION
from .model_rxc import SCALAR_VARS, EIData, logit, posterior_summary, sample

log = structlog.get_logger()
CODE_VERSION = "phase3-0"
CACHE = ROOT / "data" / "cache" / "ei"
Z10 = 1.2815515655446004


@dataclass
class Job:
    name: str
    states: list[str]


@dataclass
class JobResult:
    name: str
    table: pd.DataFrame
    status: str
    diag: dict = field(default_factory=dict)
    seconds: float = 0.0
    cached: bool = False


def make_jobs(counts: dict[str, int], min_counties: int) -> list[Job]:
    """One job per state; states with < min_counties counties are pooled with their census division."""
    jobs, small = [], {}
    for st, n in sorted(counts.items()):
        if n < min_counties:
            small.setdefault(DIVISION[st], []).append(st)
        else:
            jobs.append(Job(st, [st]))
    jobs += [Job(f"div_{div}", sts) for div, sts in sorted(small.items())]
    return jobs


def build_data(job: Job, groups_tbl: pd.DataFrame, votes: pd.DataFrame, geo: pd.DataFrame, cov: pd.DataFrame,
               validated: pd.DataFrame | None, cfg: Settings) -> EIData:
    v = votes[votes.state_po.isin(job.states)].sort_values("geoid").reset_index(drop=True)
    g = cfg.ei.groups
    gt = groups_tbl[groups_tbl.geoid.isin(set(v.geoid))]
    n = gt.pivot(index="geoid", columns="group", values="n_group")[g].reindex(v.geoid).to_numpy()
    gg = geo.set_index("geoid").reindex(v.geoid)
    regions = sorted(gg.region.unique())
    ridx = gg.region.map({r: i for i, r in enumerate(regions)}).to_numpy()
    pr = I.group_priors(validated, g, region=regions[0], state=job.states[0] if len(job.states) == 1 else None)
    x = cov.reindex(v.geoid)
    x = x.sub(x.mean()).div(x.std(ddof=0).replace(0, 1))
    sidx = gg.state_po.map({s: i for i, s in enumerate(job.states)}).to_numpy() if len(job.states) > 1 else None
    return EIData(v.geoid.to_numpy(), v.state_po.to_numpy(), v.votes_d.to_numpy(float),
                  (v.votes_d + v.votes_r).to_numpy(float), n, x.to_numpy(float), ridx, regions,
                  pr.mu.to_numpy(), pr.sd.to_numpy(), g, list(x.columns), sidx, list(job.states))


def input_hash(d: EIData, cfg: Settings) -> str:
    h = hashlib.sha1()
    for a in (d.vd, d.v, d.n, d.x, d.region_idx, d.mu_prior, d.sd_prior):
        h.update(np.ascontiguousarray(a).tobytes())
    h.update(json.dumps(cfg.ei.model_dump(), sort_keys=True, default=str).encode())
    h.update(CODE_VERSION.encode())
    return h.hexdigest()[:16]


def reconcile(theta: np.ndarray, n: np.ndarray, vd: np.ndarray) -> np.ndarray:
    """Per-county logit shift c_i so that sum_g n_ig invlogit(logit theta_ig + c_i) equals the actual D votes.

    Enforces the accounting identity (plan §6.6 acceptance: reproduce each county's D votes within 0.5%) without
    changing the between-group pattern. Bisection on c_i in [-8, 8]; returns c (I,)."""
    lg = logit(theta)
    lo, hi = np.full(len(vd), -8.0), np.full(len(vd), 8.0)
    for _ in range(60):
        mid = (lo + hi) / 2
        pred = (n / (1 + np.exp(-(lg + mid[:, None])))).sum(axis=1)
        up = pred < vd
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return (lo + hi) / 2


def _finish(d: EIData, summ: pd.DataFrame, status: str, diag: dict, reconciled: bool) -> pd.DataFrame:
    s = summ.set_index(["geoid", "group"]).reindex(
        pd.MultiIndex.from_product([d.geoid, d.groups], names=["geoid", "group"])).reset_index()
    c = np.zeros(len(d.geoid))
    if reconciled:
        c = reconcile(s.theta_mean.to_numpy().reshape(len(d.geoid), -1), d.n, d.vd)
        for col in ("theta_mean", "theta_p10", "theta_p90"):
            a = s[col].to_numpy().reshape(len(d.geoid), -1)
            s[col] = (1 / (1 + np.exp(-(logit(a) + c[:, None])))).ravel()
    s["n_group"] = d.n.ravel()
    s["ei_status"] = status
    s["rhat_max"] = diag.get("rhat_max", np.nan)
    s["ess_min"] = min(diag.get("ess_bulk_min", np.nan), diag.get("ess_tail_min", np.nan))
    s["ei_shift_c"] = np.repeat(c, len(d.groups))
    return s


def prior_only(d: EIData) -> pd.DataFrame:
    """Fallback (plan §6.6): priors-only distribution, the same group shares for every county."""
    mu = np.tile(d.mu_prior, (len(d.geoid), 1))
    z = Z10 * d.sd_prior
    return pd.DataFrame({
        "geoid": np.repeat(d.geoid, len(d.groups)), "group": np.tile(d.groups, len(d.geoid)),
        "theta_mean": mu.ravel(),
        "theta_p10": (1 / (1 + np.exp(-(logit(mu) - z)))).ravel(),
        "theta_p90": (1 / (1 + np.exp(-(logit(mu) + z)))).ravel(),
    })


def fit_job(d: EIData, name: str, cfg: Settings, use_cache: bool = True, cache_dir=None) -> JobResult:
    """sample -> diagnose -> retry (target_accept 0.97, tune 2000) -> priors-only fallback."""
    t0 = time.time()
    cache = (cache_dir or CACHE) / f"{name}_{input_hash(d, cfg)}"
    if use_cache and cache.with_suffix(".parquet").exists():
        meta = json.loads(cache.with_suffix(".json").read_text())
        return JobResult(name, pd.read_parquet(cache.with_suffix(".parquet")), meta["status"], meta["diag"],
                         time.time() - t0, True)
    s = cfg.ei.sampler
    attempts = [("ok", s.tune, s.target_accept), ("retry", 2 * s.tune, cfg.ei.retry_target_accept)]
    status, diag, summ = "fallback", {}, None
    for st, tune, ta in attempts:
        try:
            idata = sample(d, s.chains, tune, s.draws, ta, s.seed)
            dg = diagnose(idata, SCALAR_VARS)
            diag = dg.as_dict()
            log.info("ei_attempt", job=name, status=st, **diag)
            if dg.passes(cfg.ei.rhat_max, cfg.ei.ess_min):
                status, summ = st, posterior_summary(idata, d)
                break
        except Exception as e:  # noqa: BLE001 - a sampler failure counts as a failed attempt
            log.warning("warning", code="EI_SAMPLER_ERROR", job=name, error=str(e)[:200])
    if summ is None:
        log.warning("warning", code="EI_FALLBACK", job=name, note="priors-only distribution")
        tbl = _finish(d, prior_only(d), "fallback", diag, reconciled=False)
    else:
        tbl = _finish(d, summ, status, diag, reconciled=True)
    tbl["job"] = name
    cache.parent.mkdir(parents=True, exist_ok=True)
    tbl.to_parquet(cache.with_suffix(".parquet"), index=False)
    cache.with_suffix(".json").write_text(json.dumps({"status": tbl.ei_status.iloc[0], "diag": diag}))
    return JobResult(name, tbl, tbl.ei_status.iloc[0], diag, time.time() - t0)


def run_all(cfg: Settings | None = None, states: list[str] | None = None, workers: int | None = None,
            use_cache: bool = True) -> pd.DataFrame:
    """`make ei`: fit every job, write processed/ei_group_vote.parquet and output/ei/run_report.json."""
    from joblib import Parallel, delayed

    cfg = cfg or load_config()
    inp = I.load_inputs(cfg, states)
    gt = I.build_group_table(inp, cfg)
    validated = I.load_validated()
    counts = inp["v24"].groupby("state_po").size().to_dict()
    jobs = make_jobs(counts, cfg.ei.min_counties_for_state_run)
    data = [build_data(j, gt, inp["v24"], inp["geo"], inp["cov"], validated, cfg) for j in jobs]
    res = Parallel(n_jobs=workers or cfg.ei.workers)(
        delayed(fit_job)(d, j.name, cfg, use_cache) for j, d in zip(jobs, data, strict=True))
    tbl = pd.concat([r.table for r in res], ignore_index=True).drop(columns=["job"])
    tbl["group"] = tbl.group.astype("category")
    tbl["ei_status"] = tbl.ei_status.astype("category")
    out = stamp(tbl, "ei:model_rxc", CODE_VERSION, "ok")
    write_parquet(out, processed_dir() / "ei_group_vote.parquet")
    report = {r.name: {"status": r.status, "seconds": round(r.seconds, 1), "cached": r.cached, **r.diag} for r in res}
    rd = ROOT / "output" / "ei"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "run_report.json").write_text(json.dumps(report, indent=2))
    return out
