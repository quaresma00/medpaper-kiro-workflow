# 1.13.0: read the paper's declared datasets in place, read-only - never copy them.
#
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/R/medsources.R"))
#   demo <- read.delim(medpaper_unz("faers", "aers_ascii_2004q1.zip", "ascii/DEMO04Q1.TXT"),
#                      sep = "$", quote = "")
#
# Declare a dataset once with `wf data add <absolute path> --name faers`. In the S06 sandbox the
# same calls resolve to the same original files, so nothing is copied.

medpaper_source_path <- function(name, ...) {
  project <- Sys.getenv("MEDPAPER_PROJECT")
  if (!nzchar(project)) stop("MEDPAPER_PROJECT is not set: run the script with `wf run-script`")
  f <- file.path(project, ".wf", "data_sources.json")
  if (!file.exists(f)) stop("no data sources declared: wf data add <path> --name <name>")
  sources <- jsonlite::fromJSON(f, simplifyVector = FALSE)$sources
  for (s in sources) {
    if (identical(s$name, name)) {
      parts <- c(...)
      if (length(parts)) return(do.call(file.path, c(list(s$path), as.list(parts))))
      return(s$path)
    }
  }
  stop(sprintf("data source '%s' is not declared: wf data add <path> --name %s", name, name))
}

# A connection to one member of a zip data source, streamed without extraction.
medpaper_unz <- function(name, archive, member) {
  base::unz(medpaper_source_path(name, archive), member)
}
