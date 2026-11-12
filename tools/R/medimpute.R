# 1.23.0 (S8): pool analyses across multiply imputed datasets by default.
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medimpute.R"))
#   imp <- mice::mice(dat, m = 20, seed = 20240917)
#   fit <- with(imp, glm(y ~ x + z, family = binomial))
#   p <- medpaper_pool(fit, exponentiate = TRUE)      # mice::pool, Rubin's rules + Barnard-Rubin df
#   write_results(c(list(or = p$terms), medpaper_imputation_block(p)), "primary")
# medpaper_rubin(est, var, n) pools any estimates without mice. A single imputed dataset needs
# medpaper_single_imputation(reason), which carries the sentence the Methods must state.

medpaper_rubin <- function(est, var, n = NULL, k = 1, conf.level = 0.95, log_scale = FALSE) {
  m <- length(est)
  if (m < 2 || length(var) != m) stop("Rubin's rules need m >= 2 estimates with one variance each", call. = FALSE)
  qbar <- mean(est); ubar <- mean(var); b <- stats::var(est)
  t <- ubar + (1 + 1 / m) * b
  lam <- if (t > 0) (1 + 1 / m) * b / t else 0
  df_old <- if (lam > 0) (m - 1) / lam^2 else Inf
  df <- df_old; method <- "Rubin (1987)"
  if (!is.null(n)) {
    dfc <- n - k
    df_obs <- (dfc + 1) / (dfc + 3) * dfc * (1 - lam)
    df <- if (is.finite(df_old)) 1 / (1 / df_old + 1 / df_obs) else df_obs
    method <- "Barnard-Rubin (1999)"
  }
  crit <- if (is.finite(df)) stats::qt(1 - (1 - conf.level) / 2, df) else stats::qnorm(1 - (1 - conf.level) / 2)
  se <- sqrt(t)
  lo <- qbar - crit * se; hi <- qbar + crit * se
  out <- list(m = m, pooling = "Rubin's rules", df = if (is.finite(df)) df else NULL, df_method = method,
              ci_level = conf.level, fmi = lam)
  if (log_scale) c(out, list(estimate = exp(qbar), ci_low = exp(lo), ci_high = exp(hi), estimate_log = qbar, se_log = se))
  else c(out, list(estimate = qbar, se = se, ci_low = lo, ci_high = hi))
}

medpaper_pool <- function(fit, conf.level = 0.95, exponentiate = FALSE) {
  if (!requireNamespace("mice", quietly = TRUE)) stop("medpaper_pool needs the mice package", call. = FALSE)
  pooled <- mice::pool(fit)
  s <- summary(pooled, conf.int = TRUE, conf.level = conf.level, exponentiate = exponentiate)
  list(terms = lapply(split(s, seq_len(nrow(s))), as.list), m = pooled$m,
       pooling = "Rubin's rules (mice::pool)", df = as.numeric(s$df), df_method = "Barnard-Rubin (1999)",
       ci_level = conf.level)
}

medpaper_imputation_block <- function(pooled) {
  if (is.null(pooled$m) || pooled$m < 2) stop("pass the result of medpaper_pool()/medpaper_rubin()", call. = FALSE)
  list(imputation = list(m = pooled$m, pooling = pooled$pooling, df = pooled$df, df_method = pooled$df_method))
}

medpaper_single_imputation <- function(reason, m_available = NULL, analysis = "This analysis") {
  if (nchar(trimws(reason)) < 20) stop("using one imputed dataset needs a declared reason (>= 20 characters)", call. = FALSE)
  sentence <- paste0(analysis, " was performed in a single imputed dataset",
                     if (!is.null(m_available)) paste0(" of the ", m_available, " generated") else "",
                     " rather than pooled across imputations, because ", sub("\\.$", "", trimws(reason)), ".")
  list(imputation = list(m_used = 1, m_available = m_available, pooling = "none (single imputed dataset)",
                         reason = trimws(reason), methods_sentence = sentence))
}
