"""1.23.0 (S8): pool analyses across multiply imputed datasets by default.

    from analysis.imputation import rubin, imputation_block, single_imputation
    pooled = rubin(estimates, variances, n=len(df), k=n_params, log_scale=True)  # ORs/HRs
    write_results("primary", {"or": pooled["estimate"], "ci_low": pooled["ci_low"],
                              "ci_high": pooled["ci_high"], **imputation_block(pooled)})

`rubin` implements Rubin's rules (Rubin 1987) with the Barnard-Rubin small-sample degrees of
freedom (Barnard & Rubin, Biometrika 1999;86:948-55) when `n` is given; `bootstrap_within`
bootstraps inside each imputed dataset and pools the bootstrap variances with Rubin's rules.
The results JSON records m, the pooling method and df (`imputation` block). Using a single
imputed dataset needs `single_imputation(reason)`, which also writes the sentence the Methods
must carry. The S05/S06 check `imputation_pooled` reads these blocks; R: tools/R/medimpute.R.
"""
from __future__ import annotations

import math
import random

METHOD = "Rubin's rules"


def _tq(p: float, df: float | None) -> float:
    """t quantile (scipy when available, else the normal quantile with a Cornish-Fisher step)."""
    from statistics import NormalDist
    z = NormalDist().inv_cdf(p)
    if df is None or df == math.inf:
        return z
    try:
        from scipy import stats
        return float(stats.t.ppf(p, df))
    except ImportError:
        g1 = (z ** 3 + z) / 4
        g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
        return z + g1 / df + g2 / df ** 2


def rubin(estimates, variances, n: int | None = None, k: int = 1, ci_level: float = 0.95,
          log_scale: bool = False) -> dict:
    """Pool m estimates and their within-imputation variances (Rubin's rules).

    log_scale=True: estimates/variances are on the log scale (log OR, log HR); the pooled
    estimate and interval are returned exponentiated, `estimate_log`/`se_log` on the log scale."""
    q = [float(x) for x in estimates]
    u = [float(x) for x in variances]
    m = len(q)
    if m < 2 or len(u) != m:
        raise ValueError("Rubin's rules need m >= 2 estimates with one variance each")
    if any(x < 0 for x in u):
        raise ValueError("variances must be >= 0 (pass squared standard errors)")
    qbar = sum(q) / m
    ubar = sum(u) / m
    b = sum((x - qbar) ** 2 for x in q) / (m - 1)
    t = ubar + (1 + 1 / m) * b
    se = math.sqrt(t)
    lam = (1 + 1 / m) * b / t if t > 0 else 0.0
    riv = (1 + 1 / m) * b / ubar if ubar > 0 else math.inf
    df_old = (m - 1) / lam ** 2 if lam > 0 else math.inf
    df, df_method = df_old, "Rubin (1987)"
    if n is not None:
        dfc = n - k
        if dfc <= 0:
            raise ValueError("n must exceed the number of model parameters k")
        df_obs = (dfc + 1) / (dfc + 3) * dfc * (1 - lam)
        df = 1 / (1 / df_old + 1 / df_obs) if df_old != math.inf else df_obs
        df_method = "Barnard-Rubin (1999)"
    crit = _tq(1 - (1 - ci_level) / 2, None if df == math.inf else df)
    lo, hi = qbar - crit * se, qbar + crit * se
    out = {"m": m, "pooling": METHOD, "df": None if df == math.inf else round(df, 3),
           "df_method": df_method, "ci_level": ci_level,
           "fmi": round(lam, 4), "riv": None if riv == math.inf else round(riv, 4),
           "between_variance": b, "within_variance": ubar, "total_variance": t}
    if log_scale:
        out.update(estimate=math.exp(qbar), ci_low=math.exp(lo), ci_high=math.exp(hi),
                   estimate_log=qbar, se_log=se, scale="exponentiated from the log scale")
    else:
        out.update(estimate=qbar, se=se, ci_low=lo, ci_high=hi)
    return out


def bootstrap_within(datasets, statistic, n_boot: int = 200, seed: int = 20240917,
                     ci_level: float = 0.95) -> dict:
    """Bootstrap inside each imputed dataset, then pool with Rubin's rules (the bootstrap
    variance is the within-imputation variance). `statistic(sample) -> float`; datasets are
    lists of rows or pandas DataFrames."""
    rng = random.Random(seed)
    ests, vars_ = [], []
    for d in datasets:
        n = len(d)
        take = (lambda idx, d=d: d.iloc[idx]) if hasattr(d, "iloc") else (
            lambda idx, d=d: [d[i] for i in idx])
        ests.append(float(statistic(d)))
        boots = [float(statistic(take([rng.randrange(n) for _ in range(n)])))
                 for _ in range(n_boot)]
        mu = sum(boots) / n_boot
        vars_.append(sum((x - mu) ** 2 for x in boots) / (n_boot - 1))
    out = rubin(ests, vars_, ci_level=ci_level)
    out.update(pooling=f"{METHOD} with bootstrap variance within each imputation",
               n_boot=n_boot, seed=seed)
    return out


def imputation_block(pooled: dict, software: str = "", n_imputed_variables: int | None = None) -> dict:
    """{"imputation": {...}} for a write_results() payload: m, pooling method and df."""
    if int(pooled.get("m", 0)) < 2 or not pooled.get("pooling"):
        raise ValueError("pass the result of rubin()/bootstrap_within()")
    blk = {"m": int(pooled["m"]), "pooling": pooled["pooling"], "df": pooled.get("df"),
           "df_method": pooled.get("df_method", "")}
    if software:
        blk["software"] = software
    if n_imputed_variables is not None:
        blk["n_imputed_variables"] = n_imputed_variables
    return {"imputation": blk}


def single_imputation(reason: str, m_available: int | None = None, analysis: str = "") -> dict:
    """{"imputation": ...} when only ONE imputed dataset is analysed: a declared reason and the
    sentence the Methods must carry (added to the S08 writer bundle)."""
    if len(str(reason).strip()) < 20:
        raise ValueError("using one imputed dataset needs a declared reason (>= 20 characters)")
    what = analysis.strip() or "This analysis"
    sentence = (f"{what} was performed in a single imputed dataset"
                + (f" of the {m_available} generated" if m_available else "")
                + f" rather than pooled across imputations, because {reason.strip().rstrip('.')}.")
    return {"imputation": {"m_used": 1, "m_available": m_available, "pooling": "none (single "
                           "imputed dataset)", "reason": reason.strip(),
                           "methods_sentence": sentence}}
