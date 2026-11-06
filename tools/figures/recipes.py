"""Chart recipes for the archetypes that have hard mandatory elements.

Two rules distinguish these from a generic plotting helper:

1. **Estimators come from established libraries.** Kaplan-Meier goes through lifelines,
   which gives the confidence band, the median survival and the log-rank test that the
   km_survival archetype demands. Hand-rolling a product-limit estimator for a clinical
   figure is not worth the risk, even when the arithmetic happens to be right.
2. **Statistics are passed as values, not as display strings.** Every recipe takes numbers
   and formats them itself. A `hr_text="HR 1.87"` parameter would let a hand-typed number
   onto a figure, which is exactly what the numeric-provenance gate exists to prevent.
   Read the values out of 03_analysis/results/*.json and pass them in.

Each recipe returns (fig, panels) and is built so the archetype's `requires` elements are
present by construction.
"""
from __future__ import annotations

import matplotlib
import numpy as np
from matplotlib.ticker import ScalarFormatter

from .style import GREY, LIGHT_GREY, figure, significance  # noqa: F401


def _fmt_p(p: float) -> str:
    if p is None:
        return ""
    return "P < 0.001" if p < 0.001 else (f"P = {p:.3f}" if p < 0.01 else f"P = {p:.2f}")


def _fmt_ci(est, lo, hi, dp=2) -> str:
    return f"{est:.{dp}f} ({lo:.{dp}f}\u2013{hi:.{dp}f})"


def _paper_pin_before_1160() -> bool:
    """True when the paper this figure belongs to is pinned to an engine before 1.16.0."""
    import json
    import os
    from pathlib import Path
    raw = os.environ.get("MEDPAPER_PROJECT")
    if not raw:
        return False
    try:
        st = json.loads((Path(raw) / ".wf/state.json").read_text(encoding="utf-8"))
        pin = str(st.get("engine_pin") or st.get("pipeline_version") or "0")
        return tuple(int(x) for x in pin.split(".")[:3] if x.isdigit()) < (1, 16, 0)
    except (OSError, ValueError, AttributeError):
        return False


def _curve_series(curve: dict) -> tuple[list[dict], int]:
    """Series of an exported curve table (R curve_table_km() layout, or the same keys written
    from Python): time, estimate, lower, upper, strata, censor, risk{time, strata, n_risk}, n."""
    need = ("time", "estimate", "strata", "n", "risk")
    if not isinstance(curve, dict) or any(k not in curve for k in need):
        raise ValueError("km_survival: curve must carry time, estimate, strata, n and risk as "
                         "exported by the analysis (curve_table_km in tools/R/medresults.R)")
    t = np.asarray(curve["time"], float)
    est = np.asarray(curve["estimate"], float)
    st = [str(s) for s in curve["strata"]]
    lo = curve.get("lower")
    hi = curve.get("upper")
    cens = curve.get("censor") or [False] * len(t)
    risk = curve["risk"]
    out = []
    for name in dict.fromkeys(st):
        idx = [i for i, s in enumerate(st) if s == name]
        rec = {"name": name, "x": t[idx], "y": est[idx], "lo": None, "hi": None,
               "cens_x": np.asarray([t[i] for i in idx if cens[i]], float),
               "cens_y": np.asarray([est[i] for i in idx if cens[i]], float)}
        if lo is not None and hi is not None:
            lo_v = np.asarray([np.nan if lo[i] is None else lo[i] for i in idx], float)
            hi_v = np.asarray([np.nan if hi[i] is None else hi[i] for i in idx], float)
            if np.all(np.isfinite(lo_v)) and np.all(np.isfinite(hi_v)):
                rec["lo"], rec["hi"] = lo_v, hi_v
        rt = {float(x): int(n) for x, s, n in zip(risk["time"], risk["strata"], risk["n_risk"])
              if str(s) == name}
        rec["risk"] = (lambda x, _rt=rt: _rt.get(float(x)))
        below = [x for x, y in zip(rec["x"], rec["y"]) if y <= 0.5]
        rec["median"] = (float(below[0]), None, None) if below else None
        out.append(rec)
    return out, int(sum(1 for c in cens if c))


# ---------------------------------------------------------------------------
def km_survival(groups=None, time_points=None, width="single", height_mm=95.0,
                risk_table_frac=None, ylabel="Overall survival", xlabel="Time (months)",
                hr=None, hr_ci=None, logrank_p=None, show_ci=True, show_median=True,
                colors=None, min_at_risk=None, curve=None, refit=False, analysis_n=None):
    """Kaplan-Meier curves with a number-at-risk table.

    1.16.0 (N8), aligned with the R recipe_km: the default draws the curve table the analysis
    exported (`curve=` - time, estimate, lower, upper, strata, censor, risk, n; R
    curve_table_km() writes it), so the figure shows exactly the analysis population.
    Refitting from `groups` ([{"name", "time", "event"}]) happens only with refit=True and
    analysis_n = the N recorded in results JSON (the rows used must equal it). The log-rank P
    is never computed here: pass logrank_p from the analysis results (required for >= 2
    curves). Censoring marks are drawn only where censoring occurred. min_at_risk (default
    off) optionally truncates the x axis once a risk set falls below it.
    A paper pinned to an engine before 1.16.0 that calls km_survival(groups) keeps the old
    behaviour (refit, log-rank computed, truncation at 10 at risk) with a warning.

    hr, hr_ci, logrank_p: values from your results JSON. Satisfies km_survival's mandatory
    elements: step curves, censoring marks (when any), risk table, legend, in-figure statistics.
    """
    legacy = curve is None and not refit and groups is not None and _paper_pin_before_1160()
    if legacy:
        print("  ! km_survival: this paper is pinned before engine 1.16.0, so the old default "
              "is kept (refit inside the figure, log-rank computed here, axis truncated at 10 "
              "at risk). After `wf migrate --yes` pass curve= (exported by the analysis) or "
              "refit=True with analysis_n, and logrank_p from the results.")
        min_at_risk = 10 if min_at_risk is None else min_at_risk
    elif curve is None and not refit:
        raise ValueError("km_survival: refitting the curve inside the figure is off by default. "
                         "Pass curve = the curve table the analysis exported into results JSON, "
                         "or refit=True with analysis_n = the N recorded in results JSON")

    if curve is not None:
        series, n_censored = _curve_series(curve)
        pop = {"mode": "results", "n_used": int(curve["n"]), "analysis_n": int(curve["n"]),
               "censored": n_censored,
               "na_rule": str(curve.get("na_rule") or "as exported by the analysis script")}
    else:
        try:
            from lifelines import KaplanMeierFitter
            from lifelines.statistics import logrank_test
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "lifelines is required for the km_survival refit path.\n"
                "  uv pip install --python .venv/Scripts/python.exe lifelines"
            ) from exc
        if not groups:
            raise ValueError("km_survival needs at least one group")
        clean = []
        for grp in groups:
            t = np.asarray(grp["time"], float)
            e = np.asarray(grp["event"], float)
            keep = np.isfinite(t) & np.isfinite(e)
            clean.append((grp, t[keep], e[keep].astype(int), int((~keep).sum())))
        n_used = sum(len(t) for _, t, _, _ in clean)
        if not legacy:
            if analysis_n is None or int(analysis_n) != n_used:
                raise ValueError(f"km_survival: the refit would use N = {n_used} complete cases "
                                 f"but analysis_n = {analysis_n}. Plot the population the "
                                 "analysis used (pass analysis_n from results JSON).")
        if logrank_p is None and len(groups) == 2 and legacy:
            (_, ta, ea, _), (_, tb, eb, _) = clean
            logrank_p = float(logrank_test(ta, tb, ea, eb).p_value)
        series = []
        for grp, t, e, _ in clean:
            kmf = KaplanMeierFitter(label=grp["name"]).fit(t, e)
            sf_vals = kmf.survival_function_
            ci = kmf.confidence_interval_
            cens_t = t[e == 0]
            rec = {"name": grp["name"], "x": np.asarray(sf_vals.index, float),
                   "y": np.asarray(sf_vals.iloc[:, 0], float),
                   "lo": np.asarray(ci.iloc[:, 0], float), "hi": np.asarray(ci.iloc[:, 1], float),
                   "ci_x": np.asarray(ci.index, float),
                   "cens_x": cens_t,
                   "cens_y": np.asarray([float(kmf.predict(x)) for x in cens_t], float),
                   "risk": (lambda x, _t=t: int(np.sum(_t >= x)))}
            med = kmf.median_survival_time_
            rec["median"] = None
            if np.isfinite(med):
                try:
                    from lifelines.utils import median_survival_times
                    mci = median_survival_times(kmf.confidence_interval_)
                    rec["median"] = (float(med), float(mci.iloc[0, 0]), float(mci.iloc[0, 1]))
                except Exception:  # noqa: BLE001
                    rec["median"] = (float(med), None, None)
            series.append(rec)
        pop = {"mode": "legacy_refit" if legacy else "refit", "n_used": n_used,
               "analysis_n": int(analysis_n) if analysis_n is not None else n_used,
               "n_dropped_na": sum(d for *_, d in clean),
               "censored": int(sum(int((e == 0).sum()) for _, _, e, _ in clean))}
    if logrank_p is None and len(series) >= 2:
        raise ValueError("km_survival: logrank_p is missing. Export the log-rank P from the "
                         "analysis into results JSON and pass it; the figure does not compute "
                         "its own test.")

    if risk_table_frac is None:
        # Size the table panel to its contents rather than a fixed fraction. A panel
        # taller than its rows leaves dead space below the last row, which shows up as
        # an asymmetric bottom margin in QC.
        row_mm = 1.55 * matplotlib.rcParams["font.size"] / 72.0 * 25.4
        needed_mm = 1.4 * row_mm + len(series) * row_mm
        risk_table_frac = min(0.45, max(0.10, needed_mm / height_mm))

    # One SubFigure holding two axes that SHARE the x axis. Two sibling SubFigures would
    # each solve their own layout, so their axes could not be guaranteed to line up - and a
    # number-at-risk table that is not column-aligned with the curve is worse than none.
    fig, panels = figure(width=width, height_mm=height_mm, panels=(1, 1), letters=False)
    sf_km, _placeholder = panels[0]
    _placeholder.remove()
    ax, ax_tab = sf_km.subplots(
        2, 1, sharex=True,
        # hspace is a fraction of the mean axes height, so a value tuned for equal-sized
        # panels becomes a large void here. 0.10 leaves room for the table header and
        # nothing more; the layout engine floors the gap at roughly 0.03 anyway.
        gridspec_kw={"height_ratios": [1 - risk_table_frac, risk_table_frac], "hspace": 0.10},
    )
    palette = colors or [f"C{i}" for i in range(len(series))]

    for i, rec in enumerate(series):
        c = palette[i % len(palette)]
        ax.step(rec["x"], rec["y"], where="post", color=c, lw=1.1, label=rec["name"])
        if show_ci and rec.get("lo") is not None:
            ax.fill_between(rec.get("ci_x", rec["x"]), rec["lo"], rec["hi"],
                            step="post", color=c, alpha=0.13, lw=0)
        if len(rec["cens_x"]):  # censoring marks only where censoring occurred
            ax.plot(rec["cens_x"], rec["cens_y"], linestyle="None", marker="|", markersize=3.2,
                    markeredgewidth=0.7, color=c)

    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)
    ax.set_ylim(0, 1.02)
    ax.set_xlim(left=0)
    ax.legend(loc="lower left")

    lines = []
    if hr is not None and hr_ci is not None:
        lines.append(f"HR {_fmt_ci(hr, hr_ci[0], hr_ci[1])}")
    if logrank_p is not None:
        lines.append(f"{_fmt_p(logrank_p)}, log-rank")
    if show_median:
        for rec in series:
            med = rec.get("median")
            if med is None:
                lines.append(f"{rec['name']}: median not reached")
            elif med[1] is not None and med[2] is not None:
                lines.append(f"{rec['name']}: median {med[0]:.1f} ({med[1]:.1f}\u2013{med[2]:.1f})")
            else:
                lines.append(f"{rec['name']}: median {med[0]:.1f}")
    if lines:
        ax.text(0.97, 0.97, "\n".join(lines), transform=ax.transAxes,
                ha="right", va="top", color="black", linespacing=1.45)

    # ---- number at risk ----
    if time_points is not None:
        tp = list(time_points)
    elif curve is not None:
        tp = sorted({float(x) for x in curve["risk"]["time"]})
    else:
        tp = list(ax.get_xticks())
    tp = [x for x in tp if x >= 0]

    # Optional truncation where the risk set is too small to interpret (default off).
    if min_at_risk:
        keep = [x for x in tp if min((rec["risk"](x) or 0) for rec in series) >= min_at_risk]
        cutoff = max(keep) if keep else max(float(np.max(rec["x"])) for rec in series)
        ax.set_xlim(0, cutoff)
        tp = [x for x in tp if x <= cutoff]
    elif tp:
        ax.set_xlim(0, max(tp))

    ax_tab.set_ylim(len(series) - 0.5, -0.5)
    for s in ax_tab.spines.values():
        s.set_visible(False)
    ax_tab.tick_params(axis="x", length=0)
    ax_tab.tick_params(axis="y", length=0)
    ax_tab.set_ylabel("")
    # x labels belong to the table (the bottom axes); the curve above shares the scale.
    ax.tick_params(axis="x", labelbottom=False)
    ax.set_xlabel("")
    ax_tab.set_xlabel(xlabel)

    # Group names as y tick labels, not hand-placed text. Constrained layout then reserves
    # room for them, so they cannot run into the count at t=0.
    ax_tab.set_yticks(range(len(series)))
    ax_tab.set_yticklabels([rec["name"] for rec in series])
    for lab, c in zip(ax_tab.get_yticklabels(),
                      [palette[i % len(palette)] for i in range(len(series))]):
        lab.set_fontweight("bold")
        lab.set_color(c)

    ax_tab.set_title("Number at risk", loc="left", fontweight="bold", color="black", pad=3)
    lo_x, hi_x = ax.get_xlim()
    for i, rec in enumerate(series):
        for x in tp:
            n_at = rec["risk"](x)
            if n_at is None:
                continue
            # Centre-align except at the axis ends, where half the number would spill into
            # the row label on the left or past the frame on the right.
            ha = "left" if abs(x - lo_x) < 1e-9 else ("right" if abs(x - hi_x) < 1e-9 else "center")
            ax_tab.text(x, i, str(int(n_at)), ha=ha, va="center", color="black")
    ax_tab.set_xticks(tp)
    fig.medpaper_population = pop
    return fig, (ax, ax_tab)


# ---------------------------------------------------------------------------
def forest_plot(rows, width="double", height_mm=None, null_value=1.0, log_x=True,
                effect_label="Hazard ratio (95% CI)", left_label="Favours treatment",
                right_label="Favours control", summary=None, heterogeneity=None):
    """Forest plot for subgroups or a meta-analysis.

    rows: [{"label": str, "estimate": float, "ci": (lo, hi), "n": int|None,
            "p_interaction": float|None, "weight": float|None}, ...]
    summary: {"estimate": float, "ci": (lo, hi)} draws the pooled diamond.
    heterogeneity: {"i2": float, "p": float} printed under the summary.

    Satisfies forest_plot's mandatory elements: null line, error bars, in-figure statistics.
    """
    n = len(rows) + (1 if summary else 0)
    height_mm = height_mm or max(45.0, 8.0 * n + 24.0)
    fig, panels = figure(width=width, height_mm=height_mm, panels=(1, 1), letters=False)
    _, ax = panels[0]

    ys = list(range(len(rows)))[::-1]
    weights = [r.get("weight") for r in rows]
    wmax = max([w for w in weights if w] or [1.0])

    for y, r in zip(ys, rows):
        lo, hi = r["ci"]
        est = r["estimate"]
        size = 16.0 if not r.get("weight") else 8.0 + 34.0 * (r["weight"] / wmax)
        # errorbar rather than three plot() calls: it is the semantic artist for an
        # interval, so the CI is machine-detectable rather than three anonymous lines.
        ax.errorbar(est, y, xerr=[[est - lo], [hi - est]], fmt="s", markersize=np.sqrt(size),
                    color="C0", ecolor="black", elinewidth=0.7, capsize=2.0,
                    capthick=0.7, zorder=3)

    if summary:
        lo, hi = summary["ci"]
        est = summary["estimate"]
        y = -1
        ax.fill([lo, est, hi, est], [y, y + 0.16, y, y - 0.16],
                color="C1", zorder=3, lw=0.5, edgecolor="black")
        ys = ys + [y]
        rows = rows + [{"label": summary.get("label", "Overall"), "estimate": est, "ci": (lo, hi)}]

    ax.axvline(null_value, color=GREY, lw=0.6, ls="--", zorder=1)

    lows = [r["ci"][0] for r in rows]
    highs = [r["ci"][1] for r in rows]
    if log_x:
        ax.set_xscale("log")
        # Default log ticks render as 10^0 / 2x10^0, which no clinician reads. Force plain
        # numbers at the decade and minor positions.
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.xaxis.set_minor_formatter(ScalarFormatter())
        ax.ticklabel_format(axis="x", style="plain")
        span = max(highs) / min(min(lows), null_value)
        ax.set_xlim(min(min(lows), null_value) / span ** 0.18,
                    max(highs) * span ** 0.10)
    else:
        pad = 0.12 * (max(highs) - min(min(lows), null_value))
        ax.set_xlim(min(min(lows), null_value) - pad, max(highs) + pad)

    ax.set_yticks(ys)
    ax.set_yticklabels([r["label"] for r in rows])
    ax.set_ylim(min(ys) - 0.8, max(ys) + 0.8)
    ax.set_xlabel(effect_label)
    ax.set_ylabel("Subgroup")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    # Direction labels at the axes corners, not both hung off the null line, where they
    # collide whenever the null sits near an edge.
    for frac, txt, ha in ((0.0, f"\u2190 {left_label}", "left"),
                          (1.0, f"{right_label} \u2192", "right")):
        ax.annotate(txt, xy=(frac, 0), xycoords="axes fraction",
                    xytext=(0, -26), textcoords="offset points",
                    ha=ha, va="top", color="black", annotation_clip=False)

    trans = ax.get_yaxis_transform()
    for y, r in zip(ys, rows):
        lo, hi = r["ci"]
        parts = [_fmt_ci(r["estimate"], lo, hi)]
        if r.get("n"):
            parts.insert(0, f"n={r['n']}")
        if r.get("p_interaction") is not None:
            parts.append(_fmt_p(r["p_interaction"]) + " (interaction)")
        ax.text(1.02, y, "   ".join(parts), transform=trans, ha="left", va="center", color="black")
    if heterogeneity:
        ax.text(1.02, min(ys) - 0.6, f"I\u00b2 = {heterogeneity['i2']:.0f}%, "
                                     f"{_fmt_p(heterogeneity.get('p'))}",
                transform=trans, ha="left", va="center", color="black")
    return fig, ax


# ---------------------------------------------------------------------------
def roc_curve(curves, width="single", height_mm=None, diagonal=True,
              xlabel="1 - specificity", ylabel="Sensitivity", operating_points=None):
    """ROC curve(s) with the chance diagonal and AUC with CI in the legend.

    curves: [{"name": str, "fpr": array, "tpr": array, "auc": float,
              "auc_ci": (lo, hi)|None}, ...]
    operating_points: [{"fpr": float, "tpr": float, "label": str}, ...]

    Satisfies roc_curve's mandatory elements: reference diagonal, legend, in-figure
    statistics, equal axis spans.
    """
    fig, panels = figure(width=width, height_mm=height_mm or 90.0, panels=(1, 1), letters=False)
    _, ax = panels[0]
    if diagonal:
        ax.plot([0, 1], [0, 1], ls="--", lw=0.6, color=GREY, zorder=1)
    for c in curves:
        label = c["name"]
        if c.get("auc") is not None:
            ci = c.get("auc_ci")
            label += (f" (AUC {c['auc']:.3f}, 95% CI {ci[0]:.3f}\u2013{ci[1]:.3f})"
                      if ci else f" (AUC {c['auc']:.3f})")
        ax.plot(np.asarray(c["fpr"], float), np.asarray(c["tpr"], float), lw=1.1, label=label)
    for op in operating_points or []:
        ax.scatter([op["fpr"]], [op["tpr"]], s=18, zorder=4, color="black")
        ax.annotate(op.get("label", ""), xy=(op["fpr"], op["tpr"]),
                    xytext=(6, -8), textcoords="offset points", color="black")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend(loc="lower right")
    return fig, ax


# ---------------------------------------------------------------------------
def volcano_plot(log2fc, neg_log10_p, labels=None, width="single", height_mm=None,
                 fc_cutoff=1.0, p_cutoff=0.05, adjusted=True, annotate=None,
                 up_color="C1", down_color="C0", ns_color=LIGHT_GREY):
    """Volcano plot with both cutoffs drawn and repelled gene labels.

    Satisfies volcano_plot's mandatory elements: threshold lines, individual points.
    `annotate` is a list of label strings to mark; adjustText is used if available.
    """
    fig, panels = figure(width=width, height_mm=height_mm or 90.0, panels=(1, 1), letters=False)
    _, ax = panels[0]
    x = np.asarray(log2fc, float)
    y = np.asarray(neg_log10_p, float)
    thr = -np.log10(p_cutoff)

    sig_up = (x >= fc_cutoff) & (y >= thr)
    sig_dn = (x <= -fc_cutoff) & (y >= thr)
    ns = ~(sig_up | sig_dn)
    ax.scatter(x[ns], y[ns], s=3, color=ns_color, alpha=0.6, lw=0, rasterized=True)
    ax.scatter(x[sig_dn], y[sig_dn], s=5, color=down_color, alpha=0.85, lw=0, rasterized=True)
    ax.scatter(x[sig_up], y[sig_up], s=5, color=up_color, alpha=0.85, lw=0, rasterized=True)

    ax.axhline(thr, ls="--", lw=0.6, color=GREY)
    ax.axvline(fc_cutoff, ls="--", lw=0.6, color=GREY)
    ax.axvline(-fc_cutoff, ls="--", lw=0.6, color=GREY)

    ax.set_xlabel("log\u2082 fold change")
    ax.set_ylabel(("-log\u2081\u2080 adjusted " if adjusted else "-log\u2081\u2080 ") + "P")

    if annotate and labels is not None:
        labels = list(labels)
        idx = [labels.index(a) for a in annotate if a in labels]
        texts = [ax.text(x[i], y[i], labels[i], color="black") for i in idx]
        try:
            from adjustText import adjust_text
            adjust_text(texts, ax=ax,
                        arrowprops=dict(arrowstyle="-", color=GREY, lw=0.4))
        except ImportError:
            print("  note: adjustText not installed; gene labels may overlap. "
                  "uv pip install adjustText")
    return fig, ax
