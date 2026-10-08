# recipes.R - archetype recipes for the R figure toolchain. Each returns a ggplot/patchwork with
# attr(, "medpaper_archetype") set; render it with save_medpaper().
#
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/recipes.R"))
#   res <- jsonlite::fromJSON(medpaper_path("03_analysis/results/primary.json"))
#   p <- recipe_km(curve = res$km, times = c(0, 12, 24, 36),       # res$km from curve_table_km()
#                  hr = res$hr, hr_ci = c(res$hr_low, res$hr_high), p = res$p)
#   save_medpaper(p, "05_figures/out/Figure1", width = "single")
#
# Every statistic argument must be a number read from results JSON, never a display string;
# the recipe formats it. medfig.R is loaded from next to this file, never via MEDPAPER_ROOT.

.rc_self_file <- local({
  f <- NULL
  for (fr in rev(sys.frames())) if (!is.null(fr$ofile)) { f <- fr$ofile; break }
  if (is.null(f)) stop("recipes.R must be loaded with source()", call. = FALSE)
  normalizePath(f, winslash = "/")
})
if (!exists("save_medpaper", mode = "function")) source(file.path(dirname(.rc_self_file), "medfig.R"))

.rc_num <- function(x, n = NULL, what = deparse(substitute(x))) {
  if (is.null(x)) return(invisible(NULL))
  if (is.character(x) || is.factor(x)) stop("pass numbers read from results JSON, not display strings (", what, ")", call. = FALSE)
  if (is.list(x)) x <- unlist(x)
  if (!is.numeric(x) || !all(is.finite(x))) stop(what, " must be finite numeric", call. = FALSE)
  if (!is.null(n) && length(x) != n) stop(what, " must have length ", n, call. = FALSE)
  invisible(x)
}
.fmt_num <- function(x, dp = 2) formatC(x, format = "f", digits = dp)
.fmt_est <- function(est, lo, hi, dp = 2) sprintf("%s (%s-%s)", .fmt_num(est, dp), .fmt_num(lo, dp), .fmt_num(hi, dp))
.fmt_p <- function(p) if (p < 0.001) "<0.001" else if (p < 0.01) .fmt_num(p, 3) else .fmt_num(p, 2)
.rc_tag <- function(p, archetype) { attr(p, "medpaper_archetype") <- archetype; p }

.rc_risk_leaf <- function(rt, times, levels_, palette) {
  rt$strata <- factor(rt$strata, levels = rev(levels_))
  ggplot(rt, aes(x = time, y = strata, label = n.risk)) +
    geom_text(size = 7 / ggplot2::.pt) +
    scale_y_discrete(expand = expansion(add = 0.25)) +
    scale_x_continuous(breaks = times) +
    coord_cartesian(xlim = range(times)) +
    labs(title = "Number at risk", x = NULL, y = NULL) +
    theme_medpaper() +
    theme(axis.line = element_blank(), axis.ticks = element_blank(), axis.text.x = element_blank(),
          axis.title.y = element_blank(), plot.title = element_text(size = 8))
}

# ---------------------------------------------------------------------------
# Curves come from the confirmed analysis, not from a second fit (1.7.1).
# A figure that re-estimates a survival or cumulative-incidence curve can silently use another
# population (NA rows dropped by the plotting fit, a different filter) than the analysis it
# illustrates. The default path draws a curve table the analysis script exported with
# curve_table_km()/curve_table_cif() (tools/R/medresults.R) into its results JSON:
#
#   res <- jsonlite::fromJSON(medpaper_path("03_analysis/results/primary.json"))
#   p <- recipe_km(curve = res$km, times = c(0, 12, 24), hr = res$hr, ...)
#
# Fitting inside the recipe remains possible only with refit = TRUE and analysis_n = the N
# recorded in results JSON; the complete-case N actually used must equal it. Either way the
# population (n_used, analysis_n, NA rows dropped, mode) is written to the figure sidecar and
# qc.py checks it against the figure's source_results.
.rc_population <- function(p, pop) { attr(p, "medpaper_population") <- pop; p }

.rc_refit_data <- function(data, cols, analysis_n, refit, recipe) {
  if (!isTRUE(refit))
    stop(recipe, ": refitting the curve inside the figure is off by default. Pass curve = the ",
         "table exported by curve_table_", sub("recipe_", "", recipe), "() into results JSON, or ",
         "refit = TRUE with analysis_n = the N recorded in results JSON", call. = FALSE)
  .rc_num(analysis_n, 1, "analysis_n")
  keep <- stats::complete.cases(data[, cols, drop = FALSE])
  used <- data[keep, , drop = FALSE]
  if (nrow(used) != analysis_n)
    stop(recipe, ": the refit would use N = ", nrow(used), " complete cases (", sum(!keep),
         " row(s) with NA in ", paste(cols, collapse = "/"), " dropped) but results JSON says ",
         "analysis N = ", analysis_n, ". Plot the same population the analysis used.", call. = FALSE)
  list(data = used, pop = list(mode = "refit", n_input = nrow(data), n_used = nrow(used),
                               n_dropped_na = sum(!keep), analysis_n = analysis_n,
                               na_rule = paste("complete cases on", paste(cols, collapse = ", "))))
}

.rc_curve_df <- function(curve, recipe) {
  need <- c("time", "estimate", "strata")
  if (!is.list(curve) || !all(need %in% names(curve)))
    stop(recipe, ": curve must carry time, estimate, strata (and n, risk) as exported by ",
         "curve_table_*()", call. = FALSE)
  df <- data.frame(time = unlist(curve$time), estimate = unlist(curve$estimate),
                   strata = as.character(unlist(curve$strata)))
  lo <- suppressWarnings(as.numeric(unlist(lapply(curve$lower %||% list(), function(v) if (is.null(v)) NA else v))))
  hi <- suppressWarnings(as.numeric(unlist(lapply(curve$upper %||% list(), function(v) if (is.null(v)) NA else v))))
  # A band is drawn only when the exported table has finite limits at every step.
  if (length(lo) == nrow(df) && length(hi) == nrow(df) && all(is.finite(c(lo, hi)))) {
    df$lower <- lo; df$upper <- hi
  }
  .rc_num(df$time, nrow(df), "curve$time"); .rc_num(df$estimate, nrow(df), "curve$estimate")
  df
}

.rc_curve_plot <- function(curve, recipe, times, ylim, xlab, ylab, palette, legend_xy, legend_just) {
  df <- .rc_curve_df(curve, recipe)
  lv <- unique(df$strata)
  df$strata <- factor(df$strata, levels = lv)
  .rc_num(curve$n, 1, "curve$n")
  pal <- medpaper_palette(palette, length(lv))
  # Same look as the refit path (ggsurvfit draws no band by default); lower/upper stay in the
  # table for the text and for any explicit band a script adds.
  pl <- ggplot(df, aes(time, estimate, colour = strata)) + geom_step()
  cens <- as.logical(unlist(curve$censor %||% list()))
  if (length(cens) == nrow(df) && any(cens, na.rm = TRUE))
    pl <- pl + geom_point(data = df[!is.na(cens) & cens, , drop = FALSE], shape = 3, size = 1.2,
                          show.legend = FALSE)
  pl <- pl + scale_colour_manual(values = pal) +
    scale_x_continuous(breaks = times) + coord_cartesian(xlim = range(times), ylim = ylim) +
    labs(x = xlab, y = ylab, colour = NULL) + theme_medpaper() +
    theme(legend.position = "inside", legend.position.inside = legend_xy, legend.justification = legend_just)
  rk <- curve$risk
  if (!is.list(rk) || !all(c("time", "strata", "n_risk") %in% names(rk)))
    stop(recipe, ": curve$risk (time, strata, n_risk at the axis times) is required", call. = FALSE)
  rt <- data.frame(time = unlist(rk$time), strata = as.character(unlist(rk$strata)),
                   n.risk = unlist(rk$n_risk))
  list(curve = pl, risk = .rc_risk_leaf(rt, times, lv, palette), levels = lv,
       pop = list(mode = "results", n_used = as.numeric(curve$n), analysis_n = as.numeric(curve$n),
                  n_dropped_na = curve$n_dropped_na %||% NULL,
                  na_rule = curve$na_rule %||% "as exported by the analysis script"))
}

recipe_km <- function(data = NULL, time = NULL, status = NULL, group = NULL, times, hr = NULL,
                      hr_ci = NULL, p = NULL, xlab = "Time", ylab = "Survival probability",
                      palette = "okabe_ito", curve = NULL, refit = FALSE, analysis_n = NULL) {
  .rc_num(times, what = "times"); .rc_num(hr, 1, "hr"); .rc_num(hr_ci, 2, "hr_ci"); .rc_num(p, 1, "p")
  hr_txt <- if (!is.null(hr)) paste0("HR ", if (!is.null(hr_ci)) .fmt_est(hr, hr_ci[1], hr_ci[2]) else .fmt_num(hr),
                                     if (!is.null(p)) paste0("; P ", .fmt_p(p)) else "") else NULL
  if (!is.null(curve)) {
    cp <- .rc_curve_plot(curve, "recipe_km", times, c(0, 1), xlab, ylab, palette, c(0.02, 0.02), c(0, 0))
    pl <- cp$curve
    if (!is.null(hr_txt)) pl <- pl + annotate("text", x = max(times), y = 0.98, label = hr_txt, hjust = 1, vjust = 1, size = 7 / ggplot2::.pt)
    out <- patchwork::wrap_plots(pl, cp$risk, ncol = 1, heights = c(3, 1))
    return(.rc_population(.rc_tag(out, "km_survival"), cp$pop))
  }
  rf <- .rc_refit_data(data, c(time, status, group), analysis_n, refit, "recipe_km")
  data <- rf$data
  data[[group]] <- factor(data[[group]])
  lv <- levels(data[[group]])
  fml <- stats::as.formula(sprintf("survival::Surv(%s, %s) ~ %s", time, status, group))
  fit <- ggsurvfit::survfit2(fml, data = data)
  pal <- medpaper_palette(palette, length(lv))
  curve <- ggsurvfit::ggsurvfit(fit) + ggsurvfit::add_censor_mark(size = 1.2) +
    scale_colour_manual(values = pal) +
    scale_x_continuous(breaks = times) + coord_cartesian(xlim = range(times), ylim = c(0, 1)) +
    labs(x = xlab, y = ylab, colour = NULL) + theme_medpaper() +
    theme(legend.position = "inside", legend.position.inside = c(0.02, 0.02), legend.justification = c(0, 0))
  if (!is.null(hr_txt))
    curve <- curve + annotate("text", x = max(times), y = 0.98, label = hr_txt, hjust = 1, vjust = 1, size = 7 / ggplot2::.pt)
  s <- summary(fit, times = times, extend = TRUE)
  rt <- data.frame(time = s$time, strata = sub("^.*=", "", as.character(s$strata)), n.risk = s$n.risk)
  risk <- .rc_risk_leaf(rt, times, lv, palette)
  .rc_population(.rc_tag(patchwork::wrap_plots(curve, risk, ncol = 1, heights = c(3, 1)), "km_survival"), rf$pop)
}

recipe_cif <- function(data = NULL, time = NULL, status = NULL, group = NULL, times, cause = 1,
                       gray_p = NULL, xlab = "Time", ylab = "Cumulative incidence",
                       palette = "okabe_ito", curve = NULL, refit = FALSE, analysis_n = NULL) {
  .rc_num(times, what = "times"); .rc_num(gray_p, 1, "gray_p"); .rc_num(cause, 1, "cause")
  gray_txt <- if (!is.null(gray_p)) paste0("Gray's test P ", .fmt_p(gray_p)) else NULL
  if (!is.null(curve)) {
    cp <- .rc_curve_plot(curve, "recipe_cif", times, NULL, xlab, ylab, palette, c(0.02, 0.98), c(0, 1))
    pl <- cp$curve
    if (!is.null(gray_txt)) pl <- pl + annotate("text", x = max(times), y = Inf, label = gray_txt, hjust = 1, vjust = 1.5, size = 7 / ggplot2::.pt)
    out <- patchwork::wrap_plots(pl, cp$risk, ncol = 1, heights = c(3, 1))
    return(.rc_population(.rc_tag(out, "cumulative_incidence"), cp$pop))
  }
  rf <- .rc_refit_data(data, c(time, status, group), analysis_n, refit, "recipe_cif")
  data <- rf$data
  data[[group]] <- factor(data[[group]])
  lv <- levels(data[[group]])
  if (!is.factor(data[[status]])) stop("status must be a factor whose first level is censoring", call. = FALSE)
  outcome <- levels(data[[status]])[cause + 1]
  fml <- stats::as.formula(sprintf("survival::Surv(%s, %s) ~ %s", time, status, group))
  ci <- tidycmprsk::cuminc(fml, data = data)
  pal <- medpaper_palette(palette, length(lv))
  curve <- ggsurvfit::ggcuminc(ci, outcome = outcome)
  # tidy_cuminc() carries NA estimates past the last event; ggplot drops them with a warning,
  # which save_medpaper treats as an error (warn = 2). Dropping them here draws the same curve.
  if ("estimate" %in% names(curve$data))
    curve$data <- curve$data[!is.na(curve$data$estimate), , drop = FALSE]
  curve <- curve + ggsurvfit::add_censor_mark(size = 1.2) +
    scale_colour_manual(values = pal) +
    scale_x_continuous(breaks = times) + coord_cartesian(xlim = range(times)) +
    labs(x = xlab, y = ylab, colour = NULL) + theme_medpaper() +
    theme(legend.position = "inside", legend.position.inside = c(0.02, 0.98), legend.justification = c(0, 1))
  if (!is.null(gray_txt))
    curve <- curve + annotate("text", x = max(times), y = Inf, label = gray_txt, hjust = 1, vjust = 1.5, size = 7 / ggplot2::.pt)
  td <- tidycmprsk::tidy(ci, times = times)
  td <- td[td$outcome == outcome, , drop = FALSE]
  rt <- data.frame(time = td$time, strata = as.character(td$strata), n.risk = td$n.risk)
  risk <- .rc_risk_leaf(rt, times, lv, palette)
  .rc_population(.rc_tag(patchwork::wrap_plots(curve, risk, ncol = 1, heights = c(3, 1)), "cumulative_incidence"), rf$pop)
}

recipe_forest <- function(rows, null_value = 1, log_x = TRUE, xlab = "Hazard ratio (95% CI)",
                          ylab = "Subgroup", stat_title = "HR (95% CI)", dp = 2) {
  if (!is.data.frame(rows) || !all(c("label", "estimate", "ci_low", "ci_high") %in% names(rows)))
    stop("rows must be a data.frame with label, estimate, ci_low, ci_high", call. = FALSE)
  for (k in c("estimate", "ci_low", "ci_high")) .rc_num(rows[[k]], nrow(rows), k)
  .rc_num(null_value, 1, "null_value")
  rows$label <- factor(rows$label, levels = rev(unique(as.character(rows$label))))
  rows$txt <- .fmt_est(rows$estimate, rows$ci_low, rows$ci_high, dp)
  plot <- ggplot(rows, aes(x = estimate, y = label)) +
    geom_vline(xintercept = null_value, linetype = "dashed") +
    geom_linerange(aes(xmin = ci_low, xmax = ci_high)) +
    geom_point(shape = 15, size = 1.6) +
    labs(x = xlab, y = ylab) + theme_medpaper()
  if (isTRUE(log_x)) plot <- plot + scale_x_log10()
  text <- ggplot(rows, aes(x = 0, y = label, label = txt)) +
    geom_text(hjust = 0, size = 7 / ggplot2::.pt) +
    scale_x_continuous(limits = c(0, 1), expand = c(0, 0)) +
    labs(title = stat_title, x = NULL, y = NULL) + theme_medpaper() +
    theme(axis.line = element_blank(), axis.ticks = element_blank(), axis.text = element_blank())
  text_mm <- max(nchar(c(rows$txt, stat_title))) * 1.1 + 0.5
  .rc_tag(patchwork::wrap_plots(plot, text, nrow = 1, widths = unit(c(1, text_mm), c("null", "mm"))),
          "forest_plot")
}

recipe_roc <- function(curves, auc = NULL, auc_ci = NULL, palette = "okabe_ito",
                       xlab = "1 - specificity", ylab = "Sensitivity") {
  if (!is.list(curves) || is.null(names(curves)) || !all(vapply(curves, inherits, logical(1), "roc")))
    stop("curves must be a named list of pROC::roc objects", call. = FALSE)
  .rc_num(auc, length(curves), "auc")
  if (!is.null(auc_ci)) .rc_num(auc_ci, 2 * length(curves), "auc_ci")
  nm <- names(curves)
  lab <- if (is.null(auc)) nm else if (is.null(auc_ci)) sprintf("%s (AUC %s)", nm, .fmt_num(auc, 3)) else
    sprintf("%s (AUC %s)", nm, .fmt_est(auc, auc_ci[seq(1, length(auc_ci), 2)], auc_ci[seq(2, length(auc_ci), 2)], 3))
  df <- do.call(rbind, lapply(seq_along(curves), function(i) {
    r <- curves[[i]]
    d <- data.frame(fpr = 1 - r$specificities, tpr = r$sensitivities, model = lab[i])
    d[order(d$fpr, d$tpr), ]
  }))
  df$model <- factor(df$model, levels = lab)
  p <- ggplot(df, aes(fpr, tpr, colour = model)) +
    geom_abline(slope = 1, intercept = 0, linetype = "dashed", colour = "#4D4D4D") +
    geom_path() + scale_colour_manual(values = medpaper_palette(palette, length(lab))) +
    coord_equal(xlim = c(0, 1), ylim = c(0, 1)) + labs(x = xlab, y = ylab, colour = NULL) +
    theme_medpaper() + theme(legend.position = "inside", legend.position.inside = c(0.98, 0.02), legend.justification = c(1, 0))
  .rc_tag(p, "roc_curve")
}

recipe_calibration <- function(curve, brier = NULL, slope = NULL, intercept = NULL,
                               xlab = "Predicted probability", ylab = "Observed probability") {
  if (!is.data.frame(curve) || !all(c("predicted", "observed") %in% names(curve)))
    stop("curve must be a data.frame with predicted and observed", call. = FALSE)
  .rc_num(curve$predicted, nrow(curve), "predicted"); .rc_num(curve$observed, nrow(curve), "observed")
  .rc_num(brier, 1, "brier"); .rc_num(slope, 1, "slope"); .rc_num(intercept, 1, "intercept")
  p <- ggplot(curve, aes(predicted, observed)) +
    geom_abline(slope = 1, intercept = 0, linetype = "dashed", colour = "#4D4D4D") +
    geom_line() + geom_point(size = 1.2)
  if (all(c("lower", "upper") %in% names(curve))) p <- p + geom_errorbar(aes(ymin = lower, ymax = upper), width = 0.01)
  p <- p + geom_rug(sides = "b", alpha = 0.4) + coord_equal(xlim = c(0, 1), ylim = c(0, 1)) +
    labs(x = xlab, y = ylab) + theme_medpaper()
  bits <- c(if (!is.null(brier)) paste("Brier", .fmt_num(brier, 3)),
            if (!is.null(slope)) paste("slope", .fmt_num(slope, 2)),
            if (!is.null(intercept)) paste("intercept", .fmt_num(intercept, 2)))
  if (length(bits)) p <- p + annotate("text", x = 0.02, y = 0.98, hjust = 0, vjust = 1, label = paste(bits, collapse = "; "), size = 7 / ggplot2::.pt)
  .rc_tag(p, "nomogram_calibration")
}

recipe_dca <- function(nb, palette = "okabe_ito", xlab = "Threshold probability", ylab = "Net benefit") {
  if (!is.data.frame(nb) || !all(c("threshold", "label", "net_benefit") %in% names(nb)))
    stop("nb must be a data.frame with threshold, label, net_benefit", call. = FALSE)
  .rc_num(nb$threshold, nrow(nb), "threshold"); .rc_num(nb$net_benefit, nrow(nb), "net_benefit")
  nb$label <- factor(nb$label, levels = unique(as.character(nb$label)))
  p <- ggplot(nb, aes(threshold, net_benefit, colour = label)) +
    geom_hline(yintercept = 0, colour = "#4D4D4D") + geom_line() +
    scale_colour_manual(values = medpaper_palette(palette, nlevels(nb$label))) +
    labs(x = xlab, y = ylab, colour = NULL) + theme_medpaper()
  .rc_tag(p, "decision_curve")
}

recipe_volcano <- function(data, log2fc, neg_log10_p, label = NULL, fc_cut = 1, p_cut = -log10(0.05),
                           xlab = "log2 fold change", ylab = "-log10 P") {
  .rc_num(data[[log2fc]], nrow(data), log2fc); .rc_num(data[[neg_log10_p]], nrow(data), neg_log10_p)
  .rc_num(fc_cut, 1, "fc_cut"); .rc_num(p_cut, 1, "p_cut")
  data$.sig <- abs(data[[log2fc]]) >= fc_cut & data[[neg_log10_p]] >= p_cut
  p <- ggplot(data, aes(.data[[log2fc]], .data[[neg_log10_p]], colour = .sig)) +
    geom_point(size = 0.8) +
    geom_hline(yintercept = p_cut, linetype = "dashed") + geom_vline(xintercept = c(-fc_cut, fc_cut), linetype = "dashed") +
    scale_colour_manual(values = c(`FALSE` = "#BFBFBF", `TRUE` = "#D55E00"), guide = "none") +
    labs(x = xlab, y = ylab) + theme_medpaper()
  if (!is.null(label)) p <- p + ggrepel::geom_text_repel(data = data[data$.sig, , drop = FALSE], aes(label = .data[[label]]), size = 6 / ggplot2::.pt, max.overlaps = 20)
  .rc_tag(p, "volcano_plot")
}
