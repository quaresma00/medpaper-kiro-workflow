# 1.23.0 (S7): units and plausibility of derived variables (R twin of tools/analysis/units.py).
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medunits.R"))
#   x <- medpaper_per_body_weight(daily_mg, "mg/day", weight_kg)       # list(values, unit)
#   rec <- medpaper_derived("dose_mg_kg_day", x$values, x$unit,
#                           "daily dose divided by body weight", plausible = c(0.01, 50))
#   write_results(c(list(...), medpaper_derived_block(rec)), "dosing")
# medpaper_per_body_weight() refuses a dose already per kg (double division by body weight);
# medpaper_derived() stops on values outside the plausible range. Factors only from
# reference/conversion_factors.json (each with a citable source); never invent one.

.mu_table <- function() {
  root <- Sys.getenv("MEDPAPER_ROOT")
  if (!nzchar(root)) stop("MEDPAPER_ROOT is not set (run the script with wf run-script)", call. = FALSE)
  jsonlite::fromJSON(file.path(root, "reference", "conversion_factors.json"), simplifyVector = FALSE)
}

medpaper_convert <- function(values, key) {
  tab <- .mu_table()
  f <- tab[[key]]
  if (is.null(f) || startsWith(key, "_"))
    stop("no conversion factor '", key, "' in reference/conversion_factors.json; never invent one", call. = FALSE)
  list(values = values * f$factor + (if (is.null(f$offset)) 0 else f$offset), unit = f$to,
       source = tab[["_meta"]]$sources[[f$source]])
}

medpaper_per_body_weight <- function(dose, dose_unit, weight_kg, weight_unit = "kg") {
  u <- tolower(gsub(" ", "", dose_unit))
  if (grepl("/kg|perkg|kg-1", u))
    stop("dose unit '", dose_unit, "' is already per kilogram: dividing by body weight again gives a value about 50-100 times too small", call. = FALSE)
  if (tolower(weight_unit) != "kg") stop("body weight must be in kg", call. = FALSE)
  if (any(weight_kg[!is.na(weight_kg)] <= 0)) stop("body weight must be > 0 kg", call. = FALSE)
  parts <- strsplit(dose_unit, "/", fixed = TRUE)[[1]]
  unit <- paste0(parts[1], "/kg", if (length(parts) > 1) paste0("/", paste(parts[-1], collapse = "/")) else "")
  list(values = dose / weight_kg, unit = unit)
}

medpaper_derived <- function(name, values, unit, derivation, plausible, inputs = list()) {
  if (!nzchar(unit) || nchar(derivation) < 10) stop(name, ": declare the unit and the derivation", call. = FALSE)
  v <- values[!is.na(values)]
  bad <- v[v < plausible[1] | v > plausible[2]]
  if (length(bad))
    stop(name, ": ", length(bad), " of ", length(v), " value(s) outside the plausible range ",
         plausible[1], "-", plausible[2], " ", unit, " (a double division by body weight is the usual cause)", call. = FALSE)
  list(name = name, unit = unit, derivation = derivation, plausible_range = as.numeric(plausible),
       observed_range = if (length(v)) c(min(v), max(v)) else NULL, n = length(v),
       range_check = "passed", inputs = inputs)
}

medpaper_derived_block <- function(...) {
  recs <- list(...)
  list(derived_variables = stats::setNames(lapply(recs, function(r) r[names(r) != "name"]),
                                           vapply(recs, function(r) r$name, character(1))))
}
