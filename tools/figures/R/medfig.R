# medfig.R - the pipeline's R figure toolchain (figure_engine = "R", the default).
#
#   source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/R/medfig.R"))
#   p <- ggplot(...) + ... + theme_medpaper()
#   save_medpaper(p, "05_figures/out/Figure1", width = "single", archetype = "km_survival")
#
# save_medpaper() renders at the exact physical width from the paper's targets, normalises the
# outer ink margins with the same rule tools/figures/qc.py judges, writes PNG + LZW TIFF + a
# vector PDF master and an artist-audit sidecar 05_figures/qc/<stem>.artist.json with the same
# schema style.save() writes, plus provenance (script, script_sha256, source_hashes,
# render_hashes). Outputs are staged and renamed into place only after every render succeeded,
# so a failed render keeps the previous figure. ggplot warnings are errors inside
# save_medpaper (options(warn = 2)). Every measurement in the sidecar is computed from the
# drawn grob tree. Do not hand-tune plot.margin: the outer margin is set here.

suppressPackageStartupMessages({
  library(ggplot2)
  library(grid)
})

.mf_self_file <- local({
  f <- NULL
  for (fr in rev(sys.frames())) if (!is.null(fr$ofile)) { f <- fr$ofile; break }
  if (is.null(f)) stop("medfig.R must be loaded with source(); it records its own engine location", call. = FALSE)
  normalizePath(f, winslash = "/")
})
.mf_self_engine <- normalizePath(file.path(dirname(.mf_self_file), "..", "..", ".."), winslash = "/")
if (!file.exists(file.path(.mf_self_engine, "pipeline/pipeline.toml")))
  stop("medfig.R is not inside a medpaper engine: ", .mf_self_engine, call. = FALSE)

.mf_engines <- function() unique(c(.mf_self_engine,
  if (nzchar(Sys.getenv("MEDPAPER_ROOT"))) normalizePath(Sys.getenv("MEDPAPER_ROOT"), winslash = "/", mustWork = FALSE)))
.mf_norm <- function(x) {
  x <- gsub("\\\\", "/", path.expand(x)); rest <- character(0)
  while (!file.exists(x) && dirname(x) != x) { rest <- c(basename(x), rest); x <- dirname(x) }
  if (any(rest %in% c("..", "."))) stop("path has '.'/'..' below its existing part: ", x, call. = FALSE)
  x <- normalizePath(x, winslash = "/", mustWork = FALSE)
  x <- sub("/+$", "", paste(c(x, rest), collapse = "/"))
  if (.Platform$OS.type == "windows") tolower(x) else x
}
.mf_within <- function(child, parent) {
  a <- .mf_norm(child); b <- .mf_norm(parent)
  identical(a, b) || startsWith(a, paste0(b, "/"))
}
.mf_in_engine <- function(p) any(vapply(.mf_engines(), function(e) .mf_within(p, e) || .mf_within(e, p), logical(1)))
`%||%` <- function(a, b) if (is.null(a)) b else a

medpaper_project <- function() {
  p <- Sys.getenv("MEDPAPER_PROJECT")
  if (!nzchar(p)) stop("MEDPAPER_PROJECT is not set; run the script with wf run-script", call. = FALSE)
  if (.mf_in_engine(p)) stop("MEDPAPER_PROJECT points into the medpaper engine and is refused: ", p, call. = FALSE)
  if (!dir.exists(p)) stop("MEDPAPER_PROJECT is not a directory: ", p, call. = FALSE)
  normalizePath(p, winslash = "/")
}

medpaper_engine <- function() {
  e <- Sys.getenv("MEDPAPER_ROOT")
  if (!nzchar(e)) return(.mf_self_engine)
  e <- normalizePath(e, winslash = "/", mustWork = FALSE)
  if (!file.exists(file.path(e, "pipeline/pipeline.toml"))) stop("MEDPAPER_ROOT is not a medpaper engine: ", e, call. = FALSE)
  e
}

medpaper_path <- function(...) file.path(medpaper_project(), ...)

.mf_read_targets <- function(path) {
  if (!file.exists(path)) return(list())
  lines <- readLines(path, warn = FALSE, encoding = "UTF-8")
  out <- list(); inside <- FALSE
  for (ln in lines) {
    if (grepl("^\\s*\\[", ln)) { inside <- grepl("^\\s*\\[targets\\]\\s*$", ln); next }
    if (!inside) next
    m <- regmatches(ln, regexec("^\\s*([A-Za-z0-9_]+)\\s*=\\s*(.+?)\\s*$", ln))[[1]]
    if (!length(m)) next
    val <- m[3]
    if (!startsWith(val, "\"")) val <- sub("\\s*#.*$", "", val)
    if (grepl("^\".*\"$", val)) out[[m[2]]] <- sub("^\"(.*)\"$", "\\1", val)
    else if (val %in% c("true", "false")) out[[m[2]]] <- identical(val, "true")
    else if (!is.na(suppressWarnings(as.numeric(val)))) out[[m[2]]] <- as.numeric(val)
    else out[[m[2]]] <- val
  }
  out
}

medpaper_targets <- function() {
  t <- .mf_read_targets(file.path(medpaper_engine(), "pipeline", "pipeline.toml"))
  over <- .mf_read_targets(file.path(medpaper_project(), ".wf", "config.toml"))
  for (k in names(over)) t[[k]] <- over[[k]]
  t
}

# 1.11.0 (#2a): provisional (S06/S07) or confirmed (S20) journal presentation parameters,
# exported by `wf run-script` as MEDPAPER_PRESENTATION (widths, font floor, panel label case).
medpaper_presentation <- function() {
  raw <- Sys.getenv("MEDPAPER_PRESENTATION", "")
  if (!nzchar(raw)) return(list())
  tryCatch(jsonlite::fromJSON(raw, simplifyVector = TRUE), error = function(e) list())
}

medpaper_size_mm <- function(width = "single", height_mm = NULL) {
  key <- switch(as.character(width), single = "column_width_mm_single",
                double = "column_width_mm_double", "1.5" = "column_width_mm_1_5",
                stop("width must be one of single, 1.5, double; got ", width, call. = FALSE))
  t <- medpaper_targets()
  if (is.null(t[[key]])) stop("target ", key, " is missing from pipeline.toml [targets]", call. = FALSE)
  w <- as.numeric(t[[key]])
  pw <- medpaper_presentation()$figure_width_mm[[as.character(width)]]
  if (!is.null(pw) && is.finite(as.numeric(pw))) w <- as.numeric(pw)
  h <- if (is.null(height_mm)) w * 0.72 else height_mm
  c(w, h)
}

pt_to_linewidth <- function(pt) pt / (72 / 96) / ggplot2::.pt

# Smallest text at final print size: the journal minimum, never below 8 pt by default.
medpaper_font_floor <- function() {
  f <- suppressWarnings(as.numeric(medpaper_presentation()$font_min_pt))
  if (length(f) == 1 && is.finite(f)) f else 8
}

# Panel tags in the journal's case: patchwork::plot_annotation(tag_levels = mf_tag_levels()).
mf_tag_levels <- function() if (identical(medpaper_presentation()$panel_label_case, "lower")) "a" else "A"

# Clinical label for an internal name, from 01_protocol/display_dictionary.json (1.11.0 #1a).
clinical_label <- function(internal) {
  path <- medpaper_path("01_protocol", "display_dictionary.json")
  if (!file.exists(path)) return(internal)
  d <- tryCatch(jsonlite::fromJSON(path, simplifyVector = FALSE), error = function(e) NULL)
  map <- list()
  for (t in d$terms) for (n in c(t$internal, unlist(t$aliases))) map[[n]] <- t$label
  vapply(internal, function(x) if (!is.null(map[[x]])) map[[x]] else x, "", USE.NAMES = FALSE)
}

theme_medpaper <- function(base_size = NULL, base_family = "Arial") {
  fl <- medpaper_font_floor()
  if (is.null(base_size)) base_size <- fl
  base_size <- max(base_size, fl)
  theme_classic(base_size = base_size, base_family = base_family) +
    theme(axis.title = element_text(size = base_size + 1),
          axis.text = element_text(size = base_size, colour = "black"),
          plot.tag = element_text(size = base_size + 2, face = "bold"),
          plot.title = element_text(size = base_size + 1),
          legend.text = element_text(size = base_size), legend.title = element_text(size = base_size),
          legend.background = element_blank(), legend.key = element_blank(),
          legend.box.background = element_blank(), strip.background = element_blank(),
          strip.text = element_text(size = base_size, colour = "black"),
          plot.background = element_rect(fill = "white", colour = NA),
          axis.line = element_line(linewidth = pt_to_linewidth(0.6), colour = "black"),
          axis.ticks = element_line(linewidth = pt_to_linewidth(0.6), colour = "black"),
          axis.ticks.length = unit(2.5, "pt"),
          plot.margin = margin(1.3, 1.3, 1.3, 1.3, "mm"),
          geom = element_geom(family = base_family, linewidth = pt_to_linewidth(1.0)))
}

.mf_okabe_ito <- c("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000")
.MF_RISKY <- c("nejm", "lancet", "nature", "npg")
.MF_PALETTES <- c("okabe_ito", "nejm", "lancet", "jama", "jco", "nature", "npg")

medpaper_palette <- function(name = "okabe_ito", n = NULL) {
  if (!name %in% .MF_PALETTES) stop("unknown palette '", name, "'; valid: ", paste(.MF_PALETTES, collapse = ", "), call. = FALSE)
  pal <- if (name == "okabe_ito") .mf_okabe_ito else {
    fn <- switch(name, nejm = ggsci::pal_nejm, lancet = ggsci::pal_lancet, jama = ggsci::pal_jama,
                 jco = ggsci::pal_jco, nature = ggsci::pal_npg, npg = ggsci::pal_npg)
    suppressWarnings(fn()(if (name == "jama") 7 else if (name == "jco") 10 else 8))
  }
  pal <- pal[!is.na(pal)]
  if (name %in% .MF_RISKY)
    warning("the ", name, " palette contains a red/green pair; dual-encode with shape or linetype so the figure survives colour-blind readers and greyscale", call. = FALSE)
  if (!is.null(n)) {
    if (n > length(pal)) stop("palette ", name, " has ", length(pal), " colours; ", n, " requested", call. = FALSE)
    pal <- pal[seq_len(n)]
  }
  pal
}
scale_colour_medpaper <- function(name = "okabe_ito", ...) scale_colour_manual(values = medpaper_palette(name), ...)
scale_fill_medpaper <- function(name = "okabe_ito", ...) scale_fill_manual(values = medpaper_palette(name), ...)

# ---------------------------------------------------------------------------
# helpers: archetypes, leaves, ink margins
# ---------------------------------------------------------------------------
.mf_archetypes <- function() {
  lines <- readLines(file.path(medpaper_engine(), "reference", "archetypes.toml"), warn = FALSE, encoding = "UTF-8")
  m <- regmatches(lines, regexec("^\\[archetype\\.([A-Za-z0-9_]+)\\]", lines))
  unlist(lapply(m, function(x) if (length(x)) x[2] else NULL))
}

.mf_leaves <- function(p) {
  if (inherits(p, "patchwork")) {
    kids <- p$patches$plots
    own <- p; class(own) <- setdiff(class(own), "patchwork"); own$patches <- NULL
    out <- unlist(lapply(kids, .mf_leaves), recursive = FALSE)
    if (length(own$layers) || !inherits(own, "plot_filler")) out <- c(out, list(own))
    return(Filter(function(x) inherits(x, "ggplot"), out))
  }
  if (inherits(p, "ggplot")) return(list(p))
  list()
}

.mf_drawable <- function(p) {
  if (inherits(p, "patchwork")) {
    if (length(p$patches$plots)) p$patches$plots <- lapply(p$patches$plots, .mf_drawable)
    return(p)
  }
  if (inherits(p, "ggsurvfit")) return(ggsurvfit::ggsurvfit_build(p))
  p
}

.mf_face_num <- function(face) {
  if (is.numeric(face)) return(face[1])
  switch(as.character(face[1]), bold = 2, italic = 3, bold.italic = 4, 1)
}

.mf_grob <- function(d) if (inherits(d, "patchwork")) patchwork::patchworkGrob(d) else ggplot2::ggplotGrob(d)

.mf_with_margin <- function(d, m) {
  mar <- margin(unname(m["top"]), unname(m["right"]), unname(m["bottom"]), unname(m["left"]), unit = "mm")
  if (inherits(d, "patchwork")) {
    # Leaves keep a small inner margin (the gap between panels); the outer margin is set on the
    # patchwork annotation so it can be normalised like a single plot's.
    (d & theme(plot.margin = margin(0.6, 0.6, 0.6, 0.6, unit = "mm"))) +
      patchwork::plot_annotation(theme = theme(plot.margin = mar))
  } else d + theme(plot.margin = mar)
}

.mf_decode <- function(nr) {
  # nativeRaster: integer, row-major ABGR; returns a logical ink matrix (any channel < 250)
  d <- dim(nr); h <- d[1]; w <- d[2]
  v <- as.integer(nr)
  r <- bitwAnd(v, 255L); g <- bitwAnd(bitwShiftR(v, 8L), 255L); b <- bitwAnd(bitwShiftR(v, 16L), 255L)
  matrix(r < 250L | g < 250L | b < 250L, nrow = h, ncol = w, byrow = TRUE)
}

.mf_ink_margins <- function(gt, w_mm, h_mm, dpi) {        # same rule as qc.content_bbox
  cap <- ragg::agg_capture(width = w_mm, height = h_mm, units = "mm", res = dpi, background = "white")
  dev <- dev.cur()
  on.exit(if (dev %in% dev.list()) dev.off(dev), add = TRUE)
  grid.newpage(); grid.draw(gt)
  ink <- .mf_decode(cap(native = TRUE))
  rows <- which(rowSums(ink) > 0); cols <- which(colSums(ink) > 0)
  if (!length(rows)) stop("save_medpaper: the figure is blank", call. = FALSE)
  c(top = rows[1] - 1, right = ncol(ink) - max(cols), bottom = nrow(ink) - max(rows), left = cols[1] - 1)
}

.mf_margins_ok <- function(m) {
  pair_ok <- function(a, b) { lo <- min(a, b); hi <- max(a, b); hi <= 6 || (lo > 0 && hi / lo <= 2) }
  all(m >= 2) && pair_ok(m["left"], m["right"]) && pair_ok(m["top"], m["bottom"])
}

# ---------------------------------------------------------------------------
# audit (B1.6 / B1.7): everything measured from the forced grob tree
# ---------------------------------------------------------------------------
.MF_PX <- 150
.MF_PANEL_RE <- "^panel(?:-\\d+){0,2}\\.\\d+-\\d+-\\d+-\\d+$"
.MF_LINE_CLASSES <- c("polyline", "lines", "segments", "rect", "polygon", "pathgrob", "circle")

.mf_split <- function(s) { p <- strsplit(s, "::", fixed = TRUE)[[1]]; p[nzchar(p) & p != "ROOT"] }

.mf_down <- function(parts) {
  upViewport(0)
  if (length(parts)) downViewport(do.call(vpPath, as.list(parts)), strict = TRUE)
  invisible(TRUE)
}

.mf_hjust <- function(g) {
  if (!is.null(g$hjust)) return(g$hjust)
  j <- g$just
  if (is.numeric(j)) return(j[1])
  j <- j[1]; if (is.null(j)) return(0.5)
  switch(j, left = 0, right = 1, 0.5)
}
.mf_vjust <- function(g) {
  if (!is.null(g$vjust)) return(g$vjust)
  j <- g$just
  if (is.numeric(j)) return(if (length(j) > 1) j[2] else 0.5)
  j <- if (length(j) > 1) j[2] else j[1]; if (is.null(j)) return(0.5)
  switch(j, bottom = 0, top = 1, 0.5)
}

.mf_audit <- function(gt, w_mm, h_mm, dpi, src_leaves, archetype, figure_name, font_family) {
  aud <- tempfile(fileext = ".png")
  ragg::agg_png(aud, width = w_mm, height = h_mm, units = "mm", res = dpi, background = "white")
  dev <- dev.cur()
  on.exit({ if (dev %in% dev.list()) dev.off(dev); unlink(aud) }, add = TRUE)
  grid.newpage(); grid.draw(gt); grid.force()
  ls <- grid.ls(grobs = TRUE, viewports = TRUE, print = FALSE)
  d <- data.frame(name = ls$name, gPath = ls$gPath, vpPath = ls$vpPath, type = ls$type, stringsAsFactors = FALSE)
  W <- w_mm / 25.4 * .MF_PX; H <- h_mm / 25.4 * .MF_PX
  loc <- function(x, y) { l <- deviceLoc(x, y, valueOnly = TRUE); c(l$x * .MF_PX, l$y * .MF_PX) }

  # panels: innermost viewports named like ggplot panels, addressed by full path
  pv <- d[d$type == "vpListing" & grepl(.MF_PANEL_RE, d$name, perl = TRUE), , drop = FALSE]
  full <- if (nrow(pv)) vapply(seq_len(nrow(pv)), function(i) paste(c(.mf_split(pv$vpPath[i]), pv$name[i]), collapse = "::"), "") else character(0)
  full <- unique(full)
  inner <- full[!vapply(full, function(f) any(startsWith(full, paste0(f, "::"))), logical(1))]
  panels <- list()
  for (f in inner) {
    ok <- tryCatch({ .mf_down(strsplit(f, "::", fixed = TRUE)[[1]]); TRUE }, error = function(e) FALSE)
    if (!ok) next
    a <- loc(unit(0, "npc"), unit(0, "npc")); b <- loc(unit(1, "npc"), unit(1, "npc"))
    panels[[length(panels) + 1]] <- list(path = f, bbox = c(min(a[1], b[1]), min(a[2], b[2]), max(a[1], b[1]), max(a[2], b[2])))
  }
  upViewport(0)

  gcache <- new.env(parent = emptyenv())
  get_grob <- function(parts) {
    key <- paste(parts, collapse = "::")
    if (!is.null(gcache[[key]])) return(gcache[[key]])
    g <- tryCatch(grid.get(do.call(gPath, as.list(parts)), strict = TRUE), error = function(e) NULL)
    assign(key, if (is.null(g)) FALSE else g, envir = gcache)
    if (is.null(g)) FALSE else g
  }
  ancestors_gp <- function(gparts) {
    out <- list()
    if (length(gparts)) for (k in seq_along(gparts)) {
      g <- get_grob(gparts[seq_len(k)])
      if (!isFALSE(g) && !is.null(g$gp)) out[[length(out) + 1]] <- g$gp
    }
    out
  }
  pick <- function(field, own, anc, cur) {
    v <- own[[field]]
    if (!is.null(v)) return(v)
    if (length(anc)) for (k in rev(seq_along(anc))) if (!is.null(anc[[k]][[field]])) return(anc[[k]][[field]])
    cur[[field]]
  }
  prodf <- function(field, own, anc) {
    v <- if (is.null(own[[field]])) 1 else own[[field]][1]
    for (a in anc) if (!is.null(a[[field]])) v <- v * a[[field]][1]
    v
  }

  labels <- list(); line_pts <- numeric(0); text_grobs <- list(); raster_seen <- FALSE; colorbar_seen <- FALSE
  rows <- which(d$type == "grobListing")
  for (i in rows) {
    nm <- d$name[i]
    if (grepl("raster", nm, ignore.case = TRUE)) raster_seen <- TRUE
    if (grepl("colou?r(bar|steps)", nm, ignore.case = TRUE)) colorbar_seen <- TRUE
    gparts <- .mf_split(d$gPath[i])
    g <- get_grob(c(gparts, nm))
    if (isFALSE(g)) next
    cls <- class(g)
    is_text <- inherits(g, "text")
    is_line <- any(cls %in% .MF_LINE_CLASSES)
    if (!is_text && !is_line) next
    if (inherits(g, "rastergrob")) raster_seen <- TRUE
    vparts <- .mf_split(d$vpPath[i])
    ok <- tryCatch({ .mf_down(vparts); TRUE }, error = function(e) FALSE)
    if (!ok) next
    cur <- get.gpar()
    anc <- ancestors_gp(gparts)
    own <- g$gp %||% gpar()
    if (is_line) {
      col <- pick("col", own, anc, cur); lty <- pick("lty", own, anc, cur)
      lwd <- pick("lwd", own, anc, cur); lex <- (cur$lex %||% 1) * prodf("lex", own, anc)
      visible <- !is.null(col) && any(!is.na(col) & col != "transparent") &&
        !(is.character(lty) && all(lty == "blank")) && !(is.numeric(lty) && all(lty == 0))
      eff <- suppressWarnings(min(lwd, na.rm = TRUE)) * lex
      if (visible && is.finite(eff) && eff > 0) line_pts <- c(line_pts, eff * 72 / 96)
      next
    }
    lab <- g$label
    if (is.null(lab) || is.language(lab) || is.expression(lab)) next
    lab <- as.character(lab)
    keep <- which(!is.na(lab) & nzchar(trimws(lab)))
    if (!length(keep)) next
    fs <- pick("fontsize", own, anc, cur)
    cex <- prodf("cex", own, anc)
    fam <- pick("fontfamily", own, anc, cur); face <- pick("fontface", own, anc, cur) %||% 1
    lh <- pick("lineheight", own, anc, cur) %||% 1.2
    n <- length(lab)
    fs <- rep(as.numeric(fs %||% 12), length.out = n)
    fam <- rep(as.character(fam %||% ""), length.out = n)
    face <- rep(face, length.out = n)
    lh <- rep(lh, length.out = n)
    eff_all <- fs * (cur$cex %||% 1) * cex
    xs <- rep(g$x, length.out = n); ys <- rep(g$y, length.out = n)
    hj <- rep_len(.mf_hjust(g), n); vj <- rep_len(.mf_vjust(g), n); rot <- rep_len(g$rot %||% 0, n)
    is_tick <- any(grepl("^axis-[lrtb]", gparts))
    set_id <- length(text_grobs) + 1
    members <- integer(0)
    for (k in keep) {
      tg <- textGrob(lab[k], x = xs[k], y = ys[k], hjust = hj[k], vjust = vj[k], rot = rot[k],
                     gp = gpar(fontsize = fs[k], cex = cex, fontfamily = fam[k], fontface = face[k], lineheight = lh[k]))
      bb <- tryCatch({
        a <- loc(grobX(tg, "west"), grobY(tg, "south")); b <- loc(grobX(tg, "east"), grobY(tg, "north"))
        ax <- loc(xs[k], ys[k])
        list(bbox = c(min(a[1], b[1]), min(a[2], b[2]), max(a[1], b[1]), max(a[2], b[2])), anchor = ax)
      }, error = function(e) NULL)
      if (is.null(bb)) next
      labels[[length(labels) + 1]] <- list(text = lab[k], bbox = bb$bbox, anchor = bb$anchor, size = eff_all[k],
        family = if (!nzchar(fam[k])) font_family else fam[k], face = .mf_face_num(face[k]), tick = is_tick,
        gparts = gparts, vparts = vparts, vpath = paste(vparts, collapse = "::"), set = set_id)
      members <- c(members, length(labels))
    }
    text_grobs[[set_id]] <- members
  }
  upViewport(0)

  # assignments: panel subtree, legend, else nearest panel
  centre <- function(b) c((b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
  owner <- integer(length(labels)); legend <- logical(length(labels))
  cell_re <- "^(axis|xlab|ylab)-([lrtb])(?:-\\d+)*\\.\\d+-\\d+-\\d+-\\d+$"
  for (j in seq_along(labels)) {
    L <- labels[[j]]
    in_legend <- any(grepl("^guide-box", c(L$vparts, L$gparts)))
    legend[j] <- in_legend
    hit <- which(vapply(panels, function(P) startsWith(paste0(L$vpath, "::"), paste0(P$path, "::")), logical(1)))
    if (length(hit)) { owner[j] <- hit[1]; next }
    if (in_legend || !length(panels)) { owner[j] <- 0L; next }
    cl <- centre(L$bbox)
    dist <- vapply(panels, function(P) sum((centre(P$bbox) - cl)^2), 0)
    # axis cells (tick labels, axis titles) belong to the nearest panel on the side the axis
    # faces: axis-l / ylab-l -> the panel to its right, axis-b / xlab-b -> the panel above it.
    ci <- which(grepl(cell_re, L$gparts, perl = TRUE))
    if (length(ci)) {
      m <- regmatches(L$gparts[ci[length(ci)]], regexec(cell_re, L$gparts[ci[length(ci)]], perl = TRUE))[[1]]
      side <- m[3]; b <- L$bbox; cy <- (b[2] + b[4]) / 2; cx <- (b[1] + b[3]) / 2
      gap <- vapply(panels, function(P) {
        pb <- P$bbox
        switch(side,
          l = if (cy >= pb[2] - 1 && cy <= pb[4] + 1 && b[3] <= pb[1] + 1) pb[1] - b[3] else Inf,
          r = if (cy >= pb[2] - 1 && cy <= pb[4] + 1 && b[1] >= pb[3] - 1) b[1] - pb[3] else Inf,
          b = if (cx >= pb[1] - 1 && cx <= pb[3] + 1 && b[4] <= pb[2] + 1) pb[2] - b[4] else Inf,
          t = if (cx >= pb[1] - 1 && cx <= pb[3] + 1 && b[2] >= pb[4] - 1) b[2] - pb[4] else Inf, Inf)
      }, 0)
      if (any(is.finite(gap))) { owner[j] <- which.min(gap); next }
    }
    owner[j] <- which.min(dist)
  }
  units <- lapply(seq_along(panels), function(p) {
    b <- panels[[p]]$bbox
    for (j in which(owner == p & !legend)) { lb <- labels[[j]]$bbox; b <- c(min(b[1], lb[1]), min(b[2], lb[2]), max(b[3], lb[3]), max(b[4], lb[4])) }
    b
  })
  overlaps <- list()
  if (length(units) > 1) for (a in 1:(length(units) - 1)) for (b in (a + 1):length(units)) {
    A <- units[[a]]; B <- units[[b]]
    dx <- min(A[3], B[3]) - max(A[1], B[1]); dy <- min(A[4], B[4]) - max(A[2], B[2])
    if (dx > 1 && dy > 1) overlaps[[length(overlaps) + 1]] <- list(axes = I(c(a - 1L, b - 1L)), overlap_px = round(dx * dy, 1))
  }
  if (isTRUE(getOption("medpaper.debug"))) {
    for (p in seq_along(panels)) message("panel ", p, " ", panels[[p]]$path, " bbox ", paste(round(panels[[p]]$bbox), collapse = ","), " unit ", paste(round(units[[p]]), collapse = ","))
    for (j in seq_along(labels)) message("  label '", labels[[j]]$text, "' owner ", owner[j], if (legend[j]) " legend" else "", " bbox ", paste(round(labels[[j]]$bbox), collapse = ","))
  }
  legend_boxes <- lapply(which(legend), function(j) labels[[j]]$bbox)
  voids <- .mf_voids(units, legend_boxes, W, H)

  clipped <- list()
  for (L in labels) {
    b <- L$bbox
    if (b[1] < -1 || b[2] < -1 || b[3] > W + 1 || b[4] > H + 1)
      clipped[[length(clipped) + 1]] <- list(text = substr(L$text, 1, 40), bbox = I(round(b, 1)))
  }

  collisions <- list()
  for (set in text_grobs) {
    if (length(set) < 2) next
    L <- labels[set]
    ys <- vapply(L, function(l) l$anchor[2], 0); xs <- vapply(L, function(l) l$anchor[1], 0)
    own_axes <- max(0L, owner[set[1]] - 1L)
    if (max(ys) - min(ys) <= 0.5) {
      o <- order(vapply(L, function(l) l$bbox[1], 0))
      for (k in seq_len(length(o) - 1)) {
        gap <- L[[o[k + 1]]]$bbox[1] - L[[o[k]]]$bbox[3]
        if (gap < -1) collisions[[length(collisions) + 1]] <- list(axes = own_axes, axis = "x",
          labels = I(c(substr(L[[o[k]]]$text, 1, 12), substr(L[[o[k + 1]]]$text, 1, 12))), overlap_px = round(-gap, 1))
      }
    } else if (max(xs) - min(xs) <= 0.5) {
      o <- order(vapply(L, function(l) l$bbox[2], 0))
      for (k in seq_len(length(o) - 1)) {
        gap <- L[[o[k + 1]]]$bbox[2] - L[[o[k]]]$bbox[4]
        if (gap < -1) collisions[[length(collisions) + 1]] <- list(axes = own_axes, axis = "y",
          labels = I(c(substr(L[[o[k]]]$text, 1, 12), substr(L[[o[k + 1]]]$text, 1, 12))), overlap_px = round(-gap, 1))
      }
    }
  }

  glyphs <- .mf_glyph_warnings(labels, font_family)
  elements <- .mf_elements(src_leaves, labels, panels, owner, legend, raster_seen, colorbar_seen, d)
  sizes <- vapply(labels, function(l) l$size, 0)
  list(figure = figure_name, archetype = archetype, engine = "R", n_axes = length(panels),
       min_font_pt = if (length(sizes)) round(min(sizes), 2) else NULL,
       max_font_pt = if (length(sizes)) round(max(sizes), 2) else NULL,
       min_line_pt = if (length(line_pts)) round(min(line_pts), 3) else NULL,
       text_clipped_at_edge = clipped, axes_tightbbox_overlaps = overlaps,
       glyph_warnings = I(glyphs), tick_label_collisions = collisions, interior_voids = voids,
       elements = elements,
       figure_text = I(sort(unique(trimws(vapply(labels, function(l) l$text, ""))))))
}

.mf_voids <- function(boxes, legend_boxes, W, H, max_frac = 0.10) {
  out <- list()
  n <- length(boxes)
  if (n < 2) return(out)
  occupants <- c(boxes, legend_boxes)
  occ_v <- function(a, b, lo, hi, skip) {
    for (j in seq_along(occupants)) {
      if (j %in% skip) next
      bj <- occupants[[j]]
      if (min(a[3], b[3]) - max(a[1], b[1]) <= 1) next
      if (min(bj[3], max(a[3], b[3])) - max(bj[1], min(a[1], b[1])) <= 1) next
      if (bj[4] > lo && bj[2] < hi) return(TRUE)
    }
    FALSE
  }
  occ_h <- function(a, b, lo, hi, skip) {
    for (j in seq_along(occupants)) {
      if (j %in% skip) next
      bj <- occupants[[j]]
      if (min(bj[4], max(a[4], b[4])) - max(bj[2], min(a[2], b[2])) <= 1) next
      if (bj[3] > lo && bj[1] < hi) return(TRUE)
    }
    FALSE
  }
  for (i in 1:(n - 1)) for (k in (i + 1):n) {
    a <- boxes[[i]]; b <- boxes[[k]]
    if (min(a[3], b[3]) - max(a[1], b[1]) > 1) {
      gap <- max(a[2] - b[4], b[2] - a[4]); lo <- min(a[4], b[4]); hi <- max(a[2], b[2])
      if (gap > max_frac * H && !occ_v(a, b, lo, hi, c(i, k)))
        out[[length(out) + 1]] <- list(axes = I(c(i - 1L, k - 1L)), direction = "vertical", gap_px = round(gap, 1), gap_pct = round(100 * gap / H, 1))
    }
    if (min(a[4], b[4]) - max(a[2], b[2]) > 1) {
      gap <- max(a[1] - b[3], b[1] - a[3]); lo <- min(a[3], b[3]); hi <- max(a[1], b[1])
      if (gap > max_frac * W && !occ_h(a, b, lo, hi, c(i, k)))
        out[[length(out) + 1]] <- list(axes = I(c(i - 1L, k - 1L)), direction = "horizontal", gap_px = round(gap, 1), gap_pct = round(100 * gap / W, 1))
    }
  }
  out
}

.mf_glyph_warnings <- function(labels, default_family) {
  out <- character(0)
  if (!length(labels)) return(out)
  fam <- vapply(labels, function(l) as.character(l$family %||% default_family), "")
  face <- vapply(labels, function(l) as.numeric(l$face %||% 1)[1], 0)
  for (key in unique(paste(fam, face, sep = "\r"))) {
    parts <- strsplit(key, "\r", fixed = TRUE)[[1]]; f <- parts[1]; fc <- as.numeric(parts[2])
    sel <- which(fam == f & face == fc)
    chars <- unique(unlist(strsplit(paste(vapply(labels[sel], function(l) l$text, ""), collapse = ""), "")))
    chars <- chars[!grepl("^\\s$", chars)]
    if (!length(chars)) next
    lookup <- if (f %in% c("", "sans")) "" else f
    info <- tryCatch(systemfonts::glyph_info(chars, family = lookup, italic = fc %in% c(3, 4),
                                             weight = if (fc %in% c(2, 4)) "bold" else "normal"),
                     error = function(e) NULL)
    if (!is.null(info)) {
      idx <- info$index
      for (k in which(idx == 0)) out <- c(out, sprintf("Glyph U+%04X (%s) missing from font '%s'", utf8ToInt(chars[k]), chars[k], f))
    }
    if (nzchar(lookup)) {
      got <- tryCatch(systemfonts::font_info(family = lookup)$family[1], error = function(e) NA)
      if (!is.na(got) && tolower(got) != tolower(lookup))
        out <- c(out, sprintf("font '%s' is not installed; text falls back to '%s'", lookup, got))
    }
  }
  unique(out)
}

.mf_has_geom <- function(leaf, geoms) any(vapply(leaf$layers, function(l) any(vapply(geoms, function(g) inherits(l$geom, g), logical(1))), logical(1)))
.mf_layer_rows <- function(leaf, geoms) {
  b <- tryCatch(ggplot_build(leaf), error = function(e) NULL)
  if (is.null(b)) return(list())
  out <- list()
  for (i in seq_along(leaf$layers)) if (any(vapply(geoms, function(g) inherits(leaf$layers[[i]]$geom, g), logical(1)))) out[[length(out) + 1]] <- b$data[[i]]
  out
}

.mf_elements <- function(leaves, labels, panels, owner, legend, raster_seen, colorbar_seen, d) {
  E <- function(found, evidence) list(found = isTRUE(found), evidence = as.character(evidence))
  texts <- vapply(labels, function(l) l$text, "")
  has_digit <- grepl("[0-9]", texts)
  tick <- vapply(labels, function(l) isTRUE(l$tick), logical(1))
  any_geom <- function(geoms) any(vapply(leaves, .mf_has_geom, logical(1), geoms = geoms))
  builds <- lapply(leaves, function(l) tryCatch(ggplot_build(l), error = function(e) NULL))
  data_leaves <- vapply(leaves, function(l) length(l$layers) > 0, logical(1))
  out <- list()

  xl <- any(vapply(labels, function(l) any(grepl("^xlab-", l$gparts)), logical(1)))
  yl <- any(vapply(labels, function(l) any(grepl("^ylab-", l$gparts)), logical(1)))
  out$axis_labels <- E(!any(data_leaves) || (xl && yl), sprintf("x title drawn: %s, y title drawn: %s", xl, yl))
  bars <- any_geom(c("GeomBar", "GeomCol"))
  out$bar_artist <- E(bars, if (bars) "GeomBar/GeomCol layer" else "no bar layer")

  bad <- character(0); checked <- 0
  for (k in seq_along(leaves)) {
    leaf <- leaves[[k]]; b <- builds[[k]]
    if (is.null(b)) next
    for (i in seq_along(leaf$layers)) {
      if (!(inherits(leaf$layers[[i]]$geom, "GeomBar") || inherits(leaf$layers[[i]]$geom, "GeomCol"))) next
      dat <- b$data[[i]]; checked <- checked + 1
      flipped <- isTRUE(any(dat$flipped_aes))
      lo <- if (flipped) dat$xmin else dat$ymin; hi <- if (flipped) dat$xmax else dat$ymax
      origin <- ifelse(abs(lo) <= abs(hi), lo, hi)
      rng <- max(abs(c(lo, hi)), 1)
      for (pp in seq_along(b$layout$panel_params)) {
        r <- if (flipped) b$layout$panel_params[[pp]]$x.range else b$layout$panel_params[[pp]]$y.range
        if (is.null(r)) next
        if (any(abs(origin) > 1e-9 * rng) || r[1] > 0 || r[2] < 0)
          bad <- c(bad, sprintf("value axis %.3g..%.3g, bars from %.3g", r[1], r[2], min(origin)))
      }
    }
  }
  out$baseline_zero <- E(!length(bad), if (!checked) "no bar chart present" else if (length(bad)) paste("truncated baseline:", paste(unique(bad), collapse = "; ")) else sprintf("%d bar layer(s) start at 0 and the axis includes 0", checked))

  pts <- sum(vapply(leaves, function(l) sum(vapply(.mf_layer_rows(l, "GeomPoint"), nrow, 0)), 0))
  out$individual_points <- E(pts >= 1, sprintf("%d point(s)", pts))
  eb <- any_geom(c("GeomErrorbar", "GeomErrorbarh", "GeomLinerange", "GeomPointrange", "GeomCrossbar"))
  out$error_bars <- E(eb, if (eb) "error-bar/linerange layer" else "no interval layer")
  bx <- any_geom("GeomBoxplot"); vi <- any_geom("GeomViolin")
  out$box_artist <- E(bx, if (bx) "GeomBoxplot layer" else "no box layer")
  out$violin_artist <- E(vi, if (vi) "GeomViolin layer" else "no violin layer")

  pairs <- 0
  for (l in leaves) {
    for (dat in .mf_layer_rows(l, c("GeomLine", "GeomPath"))) {
      for (g in split(dat, dat$group)) if (nrow(g) == 2 && diff(g$x) != 0 && diff(g$y) != 0) pairs <- pairs + 1
    }
    for (dat in .mf_layer_rows(l, "GeomSegment")) pairs <- pairs + sum(dat$x != dat$xend & dat$y != dat$yend)
  }
  out$connected_pairs <- E(pairs >= 3, sprintf("%d two-point connecting line(s)", pairs))

  step_leaves <- vapply(leaves, .mf_has_geom, logical(1), geoms = "GeomStep")
  out$step_curve <- E(any(step_leaves), sprintf("%d leaf/leaves with a step layer", sum(step_leaves)))
  cens <- any(vapply(seq_along(leaves), function(k) step_leaves[k] && sum(vapply(.mf_layer_rows(leaves[[k]], "GeomPoint"), nrow, 0)) >= 1, logical(1)))
  out$censoring_marks <- E(cens, if (cens) "point marks on a step-curve leaf" else "no point marks on a step-curve leaf")

  rt <- FALSE; rt_ev <- "no frameless numeric table found"
  for (k in seq_along(leaves)) {
    b <- builds[[k]]
    if (is.null(b) || !.mf_has_geom(leaves[[k]], c("GeomText", "GeomLabel"))) next
    labs <- unlist(lapply(.mf_layer_rows(leaves[[k]], c("GeomText", "GeomLabel")), function(x) as.character(x$label)))
    disc <- tryCatch(b$layout$panel_scales_y[[1]]$is_discrete(), error = function(e) FALSE)
    if (sum(grepl("[0-9]", labs)) >= 3 && isTRUE(disc)) { rt <- TRUE; rt_ev <- sprintf("text leaf with %d numeric labels on a discrete y", sum(grepl("[0-9]", labs))); break }
  }
  if (!rt) for (p in seq_along(panels)) {
    sel <- which(owner == p & !legend & has_digit & !tick &
                 vapply(labels, function(l) startsWith(paste0(l$vpath, "::"), paste0(panels[[p]]$path, "::")), logical(1)))
    if (length(sel) < 3) next
    ys <- round(vapply(labels[sel], function(l) l$anchor[2], 0) * 2) / 2
    rowsz <- table(ys)
    if (sum(rowsz[rowsz >= 3]) < 3) next
    sub <- d[startsWith(paste0(vapply(d$vpPath, function(v) paste(.mf_split(v), collapse = "::"), ""), "::"), paste0(panels[[p]]$path, "::")) & d$type == "grobListing", ]
    drawn <- sub[grepl("polyline|points|segments|GRID.lines", sub$name) & !grepl("^(grill|panel\\.grid|panel\\.background)", sub$name), ]
    if (!nrow(drawn)) { rt <- TRUE; rt_ev <- sprintf("panel %d holds a numeric grid (%d labels) and no curves", p, length(sel)); break }
  }
  if (!rt && any(vapply(leaves, function(l) inherits(l, "ggsurvfit"), logical(1))))
    rt_ev <- "ggsurvfit risk table not recognised; build the figure with recipe_km()/recipe_cif()"
  out$risk_table <- E(rt, rt_ev)

  nodes <- sum(vapply(leaves, function(l) sum(vapply(.mf_layer_rows(l, c("GeomRect", "GeomTile", "GeomLabel")), nrow, 0)), 0))
  out$box_nodes <- E(nodes >= 3 && length(labels) >= 3, sprintf("%d box(es), %d text label(s)", nodes, length(labels)))
  # 1.11.0: flow-diagram arrows (a segment/path/curve layer drawn with arrow = arrow()).
  n_arrow <- sum(vapply(leaves, function(l) tryCatch(sum(vapply(l$layers, function(ly)
    !is.null(ly$geom_params$arrow) || !is.null(ly$aes_params$arrow), logical(1))), error = function(e) 0), 0))
  out$arrows <- E(n_arrow > 0, sprintf("%d arrow layer(s)", n_arrow))
  vl <- as.numeric(unlist(lapply(leaves, function(l) unlist(lapply(.mf_layer_rows(l, "GeomVline"), function(x) x$xintercept)))))
  out$null_line <- E(length(vl) > 0, sprintf("%d vertical reference line(s), %d at 0 or 1", length(vl), sum(abs(vl) < 1e-9 | abs(vl - 1) < 1e-9)))
  diag <- FALSE
  for (l in leaves) {
    for (x in .mf_layer_rows(l, "GeomAbline")) if (any(abs(x$slope - 1) < 1e-9 & abs(x$intercept) < 1e-9)) diag <- TRUE
    for (x in .mf_layer_rows(l, c("GeomLine", "GeomPath"))) if (nrow(x) >= 2 && isTRUE(all(abs(x$x - x$y) < 1e-6))) diag <- TRUE
    for (x in .mf_layer_rows(l, "GeomSegment")) if (any(abs(x$x - x$y) < 1e-6 & abs(x$xend - x$yend) < 1e-6 & x$x != x$xend)) diag <- TRUE
  }
  out$reference_diagonal <- E(diag, if (diag) "y = x reference line" else "no y = x reference line")
  hl <- any_geom("GeomHline")
  out$reference_lines_horizontal <- E(hl, if (hl) "GeomHline layer" else "no horizontal reference line")
  out$threshold_lines <- E(hl && length(vl) > 0, "horizontal + vertical cutoff lines")
  out$colorbar <- E(colorbar_seen, if (colorbar_seen) "colourbar guide drawn" else "no colourbar guide")
  eqa <- any(vapply(leaves, function(l) inherits(l$coordinates, "CoordFixed") && isTRUE(abs((l$coordinates$ratio %||% 0) - 1) < 1e-9), logical(1)))
  out$equal_aspect <- E(eqa, if (eqa) "coord_fixed/coord_equal ratio 1" else "aspect not fixed at 1")
  eql <- FALSE
  for (b in builds) if (!is.null(b)) for (pp in b$layout$panel_params) {
    if (!is.null(pp$x.range) && !is.null(pp$y.range) && abs(diff(pp$x.range) - diff(pp$y.range)) < 1e-6) eql <- TRUE
  }
  out$equal_axes_limits <- E(eql, if (eql) "a panel with equal x and y spans" else "no panel with matching x and y spans")
  sb_lab <- grepl("[0-9]+\\s*(\u00b5m|\u03bcm|um|nm|mm|cm|kb|bp)\\b", texts, ignore.case = TRUE, perl = TRUE)
  out$scale_bar <- E(any(sb_lab) && any_geom(c("GeomSegment", "GeomRect")), sprintf("%d unit label(s)", sum(sb_lab)))
  rast <- raster_seen || any_geom("GeomRaster")
  out$bitmap_panel <- E(rast, if (rast) "raster layer/grob" else "no raster")
  out$legend_present <- E(any(legend), sprintf("%d legend label(s)", sum(legend)))
  stat <- texts[has_digit & nchar(trimws(texts)) > 2 & !tick]
  out$figure_statistics <- E(length(stat) > 0, sprintf("%d non-tick numeric label(s): %s", length(stat), paste(utils::head(stat, 4), collapse = " | ")))
  out$repelled_labels <- E(any_geom(c("GeomTextRepel", "GeomLabelRepel")), "ggrepel layer")
  logs <- FALSE
  for (l in leaves) for (s in l$scales$scales) {
    nm <- tryCatch(s$get_transformation()$name, error = function(e) tryCatch(s$trans$name, error = function(e) ""))
    if (is.character(nm) && length(nm) && grepl("log", nm[1])) logs <- TRUE
  }
  out$log_axis <- E(logs, if (logs) "log-transformed position scale" else "linear scales")
  out
}

.mf_write_json <- function(obj, path) {
  tmp <- paste0(path, ".tmp")
  on.exit(if (file.exists(tmp)) unlink(tmp), add = TRUE)
  txt <- jsonlite::toJSON(obj, auto_unbox = TRUE, digits = I(17), pretty = TRUE, null = "null", na = "null")
  writeLines(enc2utf8(as.character(txt)), tmp, useBytes = TRUE)
  if (!file.rename(tmp, path)) stop("could not move ", tmp, " to ", path, call. = FALSE)
  invisible(path)
}

.mf_sha256 <- function(path) {
  if (!file.exists(path)) stop("cannot hash a missing file: ", path, call. = FALSE)
  if (requireNamespace("digest", quietly = TRUE)) return(toupper(digest::digest(file = path, algo = "sha256")))
  if (requireNamespace("openssl", quietly = TRUE)) {
    con <- file(path, "rb"); on.exit(close(con), add = TRUE)
    return(toupper(as.character(openssl::sha256(con))))
  }
  if (requireNamespace("cli", quietly = TRUE)) return(toupper(cli::hash_file_sha256(path)))
  stop("save_medpaper needs one of the R packages digest, openssl or cli to hash its provenance", call. = FALSE)
}

.mf_rel <- function(path, paper) {
  a <- gsub("\\\\", "/", normalizePath(path, winslash = "/", mustWork = FALSE))
  b <- sub("/+$", "", gsub("\\\\", "/", paper))
  if (.Platform$OS.type == "windows") {
    if (startsWith(tolower(a), paste0(tolower(b), "/"))) return(substring(a, nchar(b) + 2))
  } else if (startsWith(a, paste0(b, "/"))) return(substring(a, nchar(b) + 2))
  a
}

# The plotting script, paper-relative. wf run-script exports MEDPAPER_SCRIPT; a direct Rscript
# call falls back to --file=. Empty when neither identifies a script inside the paper.
.mf_script_rel <- function(paper) {
  s <- Sys.getenv("MEDPAPER_SCRIPT")
  if (!nzchar(s)) {
    f <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
    if (!length(f)) return("")
    s <- sub("^--file=", "", f[1])
  }
  abs <- if (grepl("^([A-Za-z]:)?[/\\\\]", s)) s else file.path(paper, s)
  if (!file.exists(abs) || !.mf_within(abs, paper)) return("")
  .mf_rel(abs, paper)
}

# source_results the artifact plan declares for the figure rendered to `png_rel`.
.mf_plan_sources <- function(paper, png_rel) {
  plan_file <- file.path(paper, "01_protocol", "artifact_plan.json")
  if (!file.exists(plan_file)) return(character(0))
  plan <- tryCatch(jsonlite::fromJSON(plan_file, simplifyVector = FALSE), error = function(e) NULL)
  if (is.null(plan)) return(character(0))
  for (group in c("main_figures", "supp_figures")) for (e in plan[[group]] %||% list()) {
    if (identical(gsub("\\\\", "/", as.character(e$file %||% "")), png_rel)) {
      src <- unlist(e$source_results %||% list(), use.names = FALSE)
      src <- as.character(src[nzchar(src)])
      return(src[file.exists(file.path(paper, src))])
    }
  }
  character(0)
}

# During a scoped revision round (tools/rework.py, 1.7.0) only the sealed dependency closure may
# be rebuilt: re-rendering one figure must not silently rewrite another. While feedback is still
# being collected nothing is rendered at all. Mirrors wfcore.revision.guard_outputs.
.mf_revision_guard <- function(paper, rels) {
  sf <- file.path(paper, ".wf", "state.json")
  if (!file.exists(sf)) return(invisible(TRUE))
  st <- tryCatch(jsonlite::fromJSON(sf, simplifyVector = FALSE), error = function(e) NULL)
  rid <- st$active_revision_round
  if (is.null(rid) || !nzchar(rid)) return(invisible(TRUE))
  rv <- tryCatch(jsonlite::fromJSON(file.path(paper, ".wf", "revisions", paste0(rid, ".json")),
                                    simplifyVector = FALSE), error = function(e) NULL)
  if (is.null(rv)) return(invisible(TRUE))
  if (identical(rv$status, "collecting"))
    stop("feedback for revision ", rid, " is still being collected; seal the batch (tools/rework.py seal) before rendering", call. = FALSE)
  if (!identical(as.integer(rv$schema_version %||% 0L), 2L) || !identical(rv$status, "active")) return(invisible(TRUE))
  bad <- setdiff(rels, as.character(unlist(rv$allowed_files %||% list())))
  if (length(bad))
    stop("out-of-scope render during revision ", rid, ": ", paste(bad, collapse = ", "),
         " - only the planned dependency closure may be rebuilt (tools/rework.py status)", call. = FALSE)
  invisible(TRUE)
}

# ---------------------------------------------------------------------------
# 1.9.0: overwrite the PDF CreationDate/ModDate values in place (same length, so the xref
# table stays valid) with a fixed stamp; wfcore/determinism.py applies the identical rule.
.mf_pdf_stable <- function(path) {
  if (!file.exists(path)) return(invisible(FALSE))
  b <- readBin(path, "raw", file.info(path)$size)
  for (key in c("/CreationDate", "/ModDate")) {
    for (p in grepRaw(key, b, fixed = TRUE, all = TRUE)) {
      open <- grepRaw("(", b, offset = p, fixed = TRUE)
      if (!length(open) || open - p > nchar(key) + 4) next
      close <- grepRaw(")", b, offset = open, fixed = TRUE)
      if (!length(close)) next
      n <- close - open - 1
      if (n > 0) b[(open + 1):(close - 1)] <- charToRaw(substr(paste0("D:20000101000000Z", strrep(" ", n)), 1, n))
    }
  }
  writeBin(b, path)
  invisible(TRUE)
}

# 1.9.0: journal number style (P-value spacing, minus sign, thousands separator, interval
# dash) and spelling, decided once per paper. `wf run-script` exports MEDPAPER_NUMFMT from
# tools/wfcore/numfmt.py (target_journal.json number_format / spelling, else the paper config).
medpaper_numfmt <- function() {
  d <- list(p_space = FALSE, minus = "hyphen", thousands = "", interval = "-", spelling = "american")
  raw <- Sys.getenv("MEDPAPER_NUMFMT", "")
  if (nzchar(raw)) {
    got <- tryCatch(jsonlite::fromJSON(raw, simplifyVector = TRUE), error = function(e) NULL)
    for (k in names(got)) d[[k]] <- got[[k]]
  }
  d
}
mf_fmt_num <- function(x, dp = 2, style = medpaper_numfmt()) {
  s <- formatC(abs(x), format = "f", digits = dp, big.mark = style$thousands)
  neg <- if (identical(style$minus, "unicode")) "\u2212" else "-"
  ifelse(x < 0, paste0(neg, s), s)
}
mf_fmt_p <- function(p, style = medpaper_numfmt()) {
  lt <- if (isTRUE(style$p_space)) "< 0.001" else "<0.001"
  if (p < 0.001) lt else if (p < 0.01) mf_fmt_num(p, 3, style) else mf_fmt_num(p, 2, style)
}
mf_fmt_est <- function(est, lo, hi, dp = 2, style = medpaper_numfmt())
  sprintf("%s (%s%s%s)", mf_fmt_num(est, dp, style), mf_fmt_num(lo, dp, style), style$interval,
          mf_fmt_num(hi, dp, style))
# Label spelling follows the paper's spelling system (British -> American or back).
mf_label <- function(text, style = medpaper_numfmt()) {
  pairs <- list(c("haemoglobin", "hemoglobin"), c("anaemia", "anemia"), c("oedema", "edema"),
                c("artefact", "artifact"), c("standardised", "standardized"), c("randomised", "randomized"),
                c("colour", "color"), c("tumour", "tumor"), c("paediatric", "pediatric"),
                c("oesophag", "esophag"), c("haemorrhage", "hemorrhage"), c("analysed", "analyzed"),
                c("leukaemia", "leukemia"), c("ischaemi", "ischemi"), c("centre", "center"),
                c("behaviour", "behavior"), c("organisation", "organization"), c("characterised", "characterized"))
  american <- !identical(tolower(style$spelling), "british")
  for (pr in pairs) {
    from <- if (american) pr[1] else pr[2]; to <- if (american) pr[2] else pr[1]
    text <- gsub(from, to, text, fixed = TRUE)
    text <- gsub(paste0(toupper(substr(from, 1, 1)), substring(from, 2)),
                 paste0(toupper(substr(to, 1, 1)), substring(to, 2)), text, fixed = TRUE)
  }
  text
}

save_medpaper <- function(plot, stem, width = "single", height_mm = NULL, dpi = 600,
                          archetype = NULL, tiff = TRUE, pdf = TRUE) {
  # A ggplot warning while building the figure ("Removed 3 rows containing missing values")
  # means data were silently dropped from what the reader sees. Treat it as an error here,
  # where the figure is built and drawn; the previous render is kept (see staging below).
  old_warn <- options(warn = 2)
  on.exit(options(old_warn), add = TRUE)
  if (!(inherits(plot, "ggplot") || inherits(plot, "patchwork")))
    stop("save_medpaper measures ggplot/patchwork objects; build the figure with ggplot2 (+ patchwork), not a gtable, survminer list or base graphics", call. = FALSE)
  if (!is.character(stem) || length(stem) != 1 || !nzchar(stem) || grepl("\\.(png|tiff?|pdf)$", stem, ignore.case = TRUE))
    stop("stem must be a non-empty path without extension, e.g. 05_figures/out/Figure1", call. = FALSE)
  if (grepl("^project[/\\\\]", stem, ignore.case = TRUE))
    stop("stems are paper-relative, e.g. 05_figures/out/Figure1 (no project/ prefix)", call. = FALSE)
  if (!is.null(height_mm) && (!is.numeric(height_mm) || length(height_mm) != 1 || !is.finite(height_mm) || height_mm <= 0 || height_mm > 240))
    stop("height_mm must be NULL or a number in (0, 240]", call. = FALSE)
  tg <- medpaper_targets()
  dpi_min <- as.numeric(tg$figure_dpi_min %||% 300)
  if (!is.numeric(dpi) || length(dpi) != 1 || dpi != round(dpi) || dpi < dpi_min)
    stop("dpi must be an integer >= figure_dpi_min (", dpi_min, ")", call. = FALSE)
  if (is.null(archetype)) archetype <- attr(plot, "medpaper_archetype")
  if (!is.null(archetype) && !archetype %in% .mf_archetypes())
    stop("unknown archetype '", archetype, "'; see `wf archetype`", call. = FALSE)
  size <- medpaper_size_mm(width, height_mm)
  w_mm <- size[1]; h_mm <- size[2]

  paper <- medpaper_project()
  abs_stem <- if (grepl("^([A-Za-z]:)?[/\\\\]", stem)) stem else file.path(paper, stem)
  if (.mf_in_engine(abs_stem)) stop("refusing to write a figure inside the medpaper engine: ", abs_stem, call. = FALSE)
  if (!.mf_within(abs_stem, paper)) stop("figure stem must stay inside the paper: ", stem, call. = FALSE)
  out_dir <- normalizePath(dirname(abs_stem), winslash = "/", mustWork = FALSE)
  is_out <- identical(.mf_norm(out_dir), .mf_norm(file.path(paper, "05_figures", "out")))
  is_tmp <- .mf_within(out_dir, file.path(paper, "temp"))
  if (!is_out && !is_tmp) stop("figures go to 05_figures/out/ (or temp/ for scratch renders); got ", stem, call. = FALSE)
  name <- basename(abs_stem)
  if (is_out) {
    stem_rel <- paste0("05_figures/out/", name)
    .mf_revision_guard(paper, c(paste0(stem_rel, c(".png", if (isTRUE(tiff)) ".tiff", if (isTRUE(pdf)) ".pdf")),
                                paste0("05_figures/qc/", name, ".artist.json")))
  }

  # Grob construction measures strings on the current device. Without an open device Rscript
  # would open its default pdf() device (writing Rplots.pdf into the cwd) and measure with
  # PostScript metrics; a scratch ragg device keeps both the metrics and the filesystem right.
  holder <- ragg::agg_capture(width = w_mm, height = h_mm, units = "mm", res = dpi, background = "white")
  holder_dev <- dev.cur()
  on.exit(if (holder_dev %in% dev.list()) dev.off(holder_dev), add = TRUE)

  src <- plot
  leaves <- .mf_leaves(src)
  drawable <- .mf_drawable(src)

  # step 2b: outer ink margins equalised with qc.content_bbox's rule
  target_px <- 1.3 / 25.4 * dpi
  m_mm <- c(top = 1.3, right = 1.3, bottom = 1.3, left = 1.3)
  d2 <- .mf_with_margin(drawable, m_mm)
  gt <- .mf_grob(d2)
  measured <- .mf_ink_margins(gt, w_mm, h_mm, dpi)
  dbg <- isTRUE(getOption("medpaper.debug"))
  if (dbg) message("margins pass 0: mm ", paste(round(m_mm, 2), collapse = "/"), " -> px ", paste(measured[names(m_mm)], collapse = "/"))
  passes <- 0
  near <- function(m) all(abs(m - target_px) <= 0.25 * target_px)
  while ((!.mf_margins_ok(measured) || !near(measured)) && passes < 3) {
    nm <- names(m_mm)
    m_mm <- stats::setNames(pmax(m_mm + (target_px - measured[nm]) / dpi * 25.4, 0), nm)
    d2 <- .mf_with_margin(drawable, m_mm)
    gt <- .mf_grob(d2)
    measured <- .mf_ink_margins(gt, w_mm, h_mm, dpi)
    passes <- passes + 1
    if (dbg) message("margins pass ", passes, ": mm ", paste(round(m_mm, 2), collapse = "/"), " -> px ", paste(measured[names(m_mm)], collapse = "/"))
  }
  if (!.mf_margins_ok(measured))
    message("! outer margins could not be equalised: t/r/b/l = ", paste(measured[c("top", "right", "bottom", "left")], collapse = "/"), " px")

  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  # Stage every output next to its final name and publish only after all of them rendered and
  # the audit succeeded. A failed render leaves the previous approved figure untouched.
  png <- paste0(abs_stem, ".png")
  tif <- if (isTRUE(tiff)) paste0(abs_stem, ".tiff") else NULL
  pdf_out <- if (isTRUE(pdf)) paste0(abs_stem, ".pdf") else NULL
  finals <- c(png, tif, pdf_out)
  stage_of <- function(f) sub("(\\.[A-Za-z]+)$", ".render-tmp\\1", f)
  staged <- vapply(finals, stage_of, character(1))
  on.exit(for (s in staged) if (file.exists(s)) unlink(s), add = TRUE)
  .mf_draw_to <- function(open_device) {
    open_device()
    dev <- dev.cur()
    on.exit(if (dev %in% dev.list()) dev.off(dev), add = TRUE)
    grid.newpage(); grid.draw(gt)
  }
  .mf_draw_to(function() ragg::agg_png(stage_of(png), width = w_mm, height = h_mm, units = "mm", res = dpi, background = "white"))
  if (!is.null(tif))
    .mf_draw_to(function() ragg::agg_tiff(stage_of(tif), width = w_mm, height = h_mm, units = "mm", res = dpi, background = "white", compression = "lzw"))
  if (!is.null(pdf_out)) {
    # Vector master for typesetting. Device font-database notices are not data warnings.
    use_cairo <- isTRUE(capabilities("cairo"))
    suppressWarnings(.mf_draw_to(function() {
      if (use_cairo) grDevices::cairo_pdf(stage_of(pdf_out), width = w_mm / 25.4, height = h_mm / 25.4, bg = "white")
      else grDevices::pdf(stage_of(pdf_out), width = w_mm / 25.4, height = h_mm / 25.4, bg = "white", useDingbats = FALSE)
    }))
    .mf_pdf_stable(stage_of(pdf_out))  # 1.9.0: same figure -> same bytes (no render timestamp)
  }

  base_family <- tryCatch(as.character(theme_get()$text$family %||% "Arial"), error = function(e) "Arial")
  fam <- tryCatch({ th <- if (length(leaves)) leaves[[1]]$theme$text$family else NULL; if (is.null(th) || !nzchar(th)) base_family else th }, error = function(e) base_family)
  audit <- .mf_audit(gt, w_mm, h_mm, dpi, leaves, archetype, name, fam)
  qc_dir <- if (is_tmp) file.path(paper, "temp", "qc") else file.path(paper, "05_figures", "qc")
  dir.create(qc_dir, recursive = TRUE, showWarnings = FALSE)
  sidecar <- file.path(qc_dir, paste0(name, ".artist.json"))
  if (.mf_in_engine(sidecar)) stop("refusing to write a sidecar inside the engine", call. = FALSE)

  # Provenance: which script drew this, from which results, into which bytes. qc.py refuses
  # the figure once any of them changes, so a stale render cannot reach the package.
  rel_of <- function(f) .mf_rel(f, paper)
  script_rel <- .mf_script_rel(paper)
  audit$script <- script_rel
  audit$script_sha256 <- if (nzchar(script_rel)) .mf_sha256(file.path(paper, script_rel)) else ""
  src_rels <- .mf_plan_sources(paper, rel_of(png))
  audit$source_hashes <- stats::setNames(lapply(src_rels, function(r) .mf_sha256(file.path(paper, r))), src_rels)
  if (!length(src_rels)) audit$source_hashes <- structure(list(), names = character(0))
  audit$render_hashes <- stats::setNames(lapply(staged, .mf_sha256), vapply(finals, rel_of, character(1)))
  # Which population the drawn curve represents (recipe_km/recipe_cif, 1.7.1); qc.py compares
  # it with the figure's source_results.
  pop <- attr(plot, "medpaper_population")
  audit$population <- if (is.list(pop)) pop else structure(list(), names = character(0))
  for (i in seq_along(finals)) {
    # file.rename replaces an existing target, so the old file is never removed first.
    if (!file.rename(staged[i], finals[i])) stop("could not publish ", finals[i], call. = FALSE)
  }
  keys <- c("figure", "archetype", "engine", "n_axes", "min_font_pt", "max_font_pt", "min_line_pt",
            "text_clipped_at_edge", "axes_tightbbox_overlaps", "glyph_warnings",
            "tick_label_collisions", "interior_voids", "elements", "figure_text",
            "script", "script_sha256", "source_hashes", "render_hashes", "population")
  .mf_write_json(audit[keys], sidecar)

  px <- c(floor(w_mm / 25.4 * dpi), floor(h_mm / 25.4 * dpi))
  cat(sprintf("wrote %s.png%s%s  %sx%s mm @ %d dpi\n", name, if (!is.null(tif)) paste0(" + ", name, ".tiff") else "",
              if (!is.null(pdf_out)) paste0(" + ", name, ".pdf") else "",
              format(round(w_mm, 2)), format(round(h_mm, 2)), as.integer(dpi)))
  if (length(audit$axes_tightbbox_overlaps)) cat("  ! ", length(audit$axes_tightbbox_overlaps), " panel bounding-box overlap(s) - fix the layout, not the labels\n", sep = "")
  if (length(audit$text_clipped_at_edge)) cat("  ! ", length(audit$text_clipped_at_edge), " text element(s) clipped at the figure edge\n", sep = "")
  if (length(audit$glyph_warnings)) cat("  ! ", length(audit$glyph_warnings), " missing-glyph warning(s)\n", sep = "")
  if (length(audit$tick_label_collisions)) cat("  ! ", length(audit$tick_label_collisions), " tick-label collision(s)\n", sep = "")
  invisible(list(png = png, tiff = tif, width_class = width, size_mm = c(w_mm, h_mm), dpi = dpi,
                 pixels = px, artist_audit = sidecar, engine = "R", margins_px = measured))
}
