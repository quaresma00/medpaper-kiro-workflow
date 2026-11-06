# Join log (1.16.0, N7): counts of every step of a join declared complex (repeated visits,
# many-to-many, aggregation), checked for internal consistency at S04 (02_data/join_log.json;
# wfcore/dataproof.join_problems). One row per patient needs none of this. Python:
# tools/analysis/joinlog.py.
#
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medjoin.R"))
#   log <- join_log_step(NULL, "labs", pts, merged, unit_key = "patient_id",
#                        kind = "repeated_visits", key = "patient_id")
#   log <- join_log_step(log, "first lab", merged, one, unit_key = "patient_id", kind = "aggregation",
#                        key = "patient_id", aggregation = "first laboratory value after the index date")
#   write_join_log(log)

join_log_step <- function(log, name, before, after, unit_key, kind, key, aggregation = "",
                          unmatched = 0L, excluded = 0L) {
  kinds <- c("many_to_one", "repeated_visits", "many_to_many", "aggregation", "filter")
  if (!kind %in% kinds) stop("join_log_step: kind must be one of ", paste(kinds, collapse = ", "), call. = FALSE)
  units <- function(d) length(unique(stats::na.omit(d[[unit_key]])))
  if (is.null(log)) log <- list(unit_key = unit_key, steps = list())
  log$steps[[length(log$steps) + 1L]] <- list(
    name = name, kind = kind, key = key, aggregation = aggregation,
    rows_before = nrow(before), rows_after = nrow(after),
    units_before = units(before), units_after = units(after),
    unmatched_units = as.integer(unmatched), excluded_units = as.integer(excluded))
  log
}

write_join_log <- function(log, path = "02_data/join_log.json") {
  paper <- Sys.getenv("MEDPAPER_PROJECT")
  if (!nzchar(paper)) stop("write_join_log: run the script with wf run-script (MEDPAPER_PROJECT)", call. = FALSE)
  out <- file.path(paper, path)
  dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)
  writeLines(enc2utf8(as.character(jsonlite::toJSON(log, auto_unbox = TRUE, pretty = TRUE))), out,
             useBytes = TRUE)
  invisible(out)
}
