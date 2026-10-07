# medresults.R - write 03_analysis/results/<name>.json with an environment receipt (R side).
#
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medresults.R"))
#   medpaper_seed(20240917)
#   write_results(list(hr = 1.87432198765, n = 1284L, covariates = I("age")), "primary")
#
# Run the script with `wf run-script 03_analysis/code/01_primary.R`. jsonlite is called with
# digits = NA (15 significant digits): its default of 4 would turn 1.87432 into 1.874 and break
# numbers_have_provenance. Wrap length-1 vectors that must stay JSON arrays in I().
# Paper scripts must never call toJSON()/write_json() themselves (paper_scripts_scoped).

.mr_self_file <- local({
  f <- NULL
  for (fr in rev(sys.frames())) if (!is.null(fr$ofile)) { f <- fr$ofile; break }
  if (is.null(f)) stop("medresults.R must be loaded with source(); it records its own engine location", call. = FALSE)
  normalizePath(f, winslash = "/")
})
.mr_self_engine <- normalizePath(file.path(dirname(.mr_self_file), "..", ".."), winslash = "/")
if (!file.exists(file.path(.mr_self_engine, "pipeline/pipeline.toml")))
  stop("medresults.R is not inside a medpaper engine: ", .mr_self_engine, call. = FALSE)

.mr_engines <- function() unique(c(.mr_self_engine,
  if (nzchar(Sys.getenv("MEDPAPER_ROOT"))) normalizePath(Sys.getenv("MEDPAPER_ROOT"), winslash = "/", mustWork = FALSE)))
.mr_norm <- function(x) {
  x <- gsub("\\\\", "/", path.expand(x)); rest <- character(0)
  while (!file.exists(x) && dirname(x) != x) { rest <- c(basename(x), rest); x <- dirname(x) }
  if (any(rest %in% c("..", "."))) stop("path has '.'/'..' below its existing part: ", x, call. = FALSE)
  x <- normalizePath(x, winslash = "/", mustWork = FALSE)
  x <- sub("/+$", "", paste(c(x, rest), collapse = "/"))
  if (.Platform$OS.type == "windows") tolower(x) else x
}
.mr_within <- function(child, parent) {
  a <- .mr_norm(child); b <- .mr_norm(parent)
  identical(a, b) || startsWith(a, paste0(b, "/"))
}
.mr_in_engine <- function(p) any(vapply(.mr_engines(), function(e) .mr_within(p, e) || .mr_within(e, p), logical(1)))

.mr_state <- new.env(parent = emptyenv())
.mr_state$seed <- NULL

medpaper_seed <- function(seed) {
  if (!is.numeric(seed) || length(seed) != 1 || !is.finite(seed) || seed != round(seed))
    stop("medpaper_seed: seed must be a single integer-valued number", call. = FALSE)
  set.seed(seed)
  .mr_state$seed <- seed
  invisible(seed)
}

.mr_paper <- function() {
  p <- Sys.getenv("MEDPAPER_PROJECT")
  if (!nzchar(p)) stop("MEDPAPER_PROJECT is not set; run the script with wf run-script", call. = FALSE)
  if (.mr_in_engine(p)) stop("MEDPAPER_PROJECT points into the medpaper engine and is refused: ", p, call. = FALSE)
  if (!dir.exists(p)) stop("MEDPAPER_PROJECT is not a directory: ", p, call. = FALSE)
  normalizePath(p, winslash = "/")
}

.mr_check_finite <- function(x, where = "$") {
  if (is.list(x)) {
    nm <- names(x)
    for (i in seq_along(x)) .mr_check_finite(x[[i]], if (!is.null(nm) && nzchar(nm[i])) paste0(where, ".", nm[i]) else paste0(where, "[", i - 1, "]"))
  } else if (is.numeric(x)) {
    bad <- is.nan(x) | is.infinite(x)
    if (any(bad)) stop("write_results: ", where, " holds NaN/Inf; replace with NA (written as null)", call. = FALSE)
  } else if (!(is.null(x) || is.character(x) || is.logical(x) || is.factor(x))) {
    stop("write_results: ", where, " has unsupported type ", class(x)[1], call. = FALSE)
  }
}

.mr_environment <- function(script_abs, script_rel, seed) {
  loadNamespace("jsonlite")   # the writer itself; recorded like every other loaded namespace
  base <- rownames(utils::installed.packages(priority = "base"))
  ns <- setdiff(sort(loadedNamespaces()), base)
  pk <- stats::setNames(lapply(ns, function(p) as.character(utils::packageVersion(p))), ns)
  list(schema = 1L, language = "R",
       version = paste(R.version$major, R.version$minor, sep = "."),
       packages = if (length(pk)) pk else structure(list(), names = character(0)),
       seed = if (is.null(seed)) NULL else as.integer(seed),
       script = script_rel,
       script_sha256 = .mr_sha256(script_abs),
       written_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
       writer = "tools/R/medresults.R")
}

.mr_sha256 <- function(path) {
  if (exists("sha256sum", envir = asNamespace("tools"))) return(unname(tools::sha256sum(path)))
  if (requireNamespace("digest", quietly = TRUE)) return(digest::digest(file = path, algo = "sha256"))
  if (requireNamespace("openssl", quietly = TRUE)) {
    con <- file(path, "rb"); on.exit(close(con))
    return(paste(as.character(openssl::sha256(con)), collapse = ""))
  }
  stop("write_results needs the digest or openssl package to hash the calling script", call. = FALSE)
}

.mr_write_json <- function(obj, path) {
  tmp <- paste0(path, ".tmp")
  on.exit(if (file.exists(tmp)) unlink(tmp), add = TRUE)
  txt <- jsonlite::toJSON(obj, auto_unbox = TRUE, digits = NA, pretty = TRUE, null = "null", na = "null")
  writeLines(enc2utf8(as.character(txt)), tmp, useBytes = TRUE)
  if (!file.rename(tmp, path)) stop("could not move ", tmp, " to ", path, call. = FALSE)
  invisible(path)
}

write_results <- function(payload, name, seed = NULL) {
  if (!is.list(payload) || is.data.frame(payload) || is.null(names(payload)) || any(!nzchar(names(payload))) || anyDuplicated(names(payload)))
    stop("write_results: payload must be a named list with unique, non-empty names", call. = FALSE)
  if ("environment" %in% names(payload))
    stop("write_results: payload must not carry a top-level 'environment'; the writer adds it", call. = FALSE)
  if (!is.character(name) || length(name) != 1) stop("write_results: name must be a string", call. = FALSE)
  name <- sub("\\.json$", "", name)
  if (!grepl("^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$", name)) stop("write_results: invalid results name ", name, call. = FALSE)
  if (!is.null(seed) && (!is.numeric(seed) || length(seed) != 1 || !is.finite(seed) || seed != round(seed)))
    stop("write_results: seed must be NULL or a single integer-valued number", call. = FALSE)
  if (is.null(seed)) seed <- .mr_state$seed
  f <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))
  if (!length(f)) stop("write_results must run from a script via wf run-script", call. = FALSE)
  script <- normalizePath(f[1], winslash = "/")
  paper <- .mr_paper()
  if (!.mr_within(script, paper)) stop("write_results: the calling script is not inside the paper", call. = FALSE)
  rel <- substring(script, nchar(sub("/+$", "", paper)) + 2)
  if (startsWith(tolower(rel), "03_analysis/code/")) {
    if (grepl("/", substring(rel, nchar("03_analysis/code/") + 1), fixed = TRUE))
      stop("only top-level 03_analysis/code scripts may write results; helpers go in subdirectories", call. = FALSE)
    if (length(commandArgs(trailingOnly = TRUE)) > 0)
      stop("S06 re-runs scripts without arguments; put parameters in the script", call. = FALSE)
  } else if (startsWith(tolower(rel), "02_data/acquisition/")) {
    if (name != "dataset_summary")
      stop("acquisition writes raw files verbatim; analysis results come from 03_analysis/code", call. = FALSE)
  } else {
    stop("write_results may be called only from 03_analysis/code/ or 02_data/acquisition/ scripts", call. = FALSE)
  }
  .mr_check_finite(payload)
  out_dir <- file.path(paper, "03_analysis", "results")
  out <- file.path(out_dir, paste0(name, ".json"))
  if (.mr_in_engine(out)) stop("write_results: output inside the engine is refused", call. = FALSE)
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  obj <- c(payload, list(environment = .mr_environment(script, rel, seed)))
  .mr_write_json(obj, out)
  invisible(out)
}
