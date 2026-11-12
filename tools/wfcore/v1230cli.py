"""1.23.0 command-line entry points (wired into tools/wf.py by cli.build_parser).

    wf publishability record|answer|value|show      S1 publishability checkpoints
    wf data licence NAME ... | wf data availability   S6 verified data availability (via cmd_data)
"""
from __future__ import annotations

import json
from pathlib import Path


def _load():
    from .cli import _load as load
    return load()


def _kv(items: list[str]) -> dict:
    out = {}
    for it in items:
        k, sep, v = str(it).partition("=")
        if not sep or not k.strip():
            raise ValueError(f"expected METRIC=VALUE, got {it!r}")
        try:
            out[k.strip()] = int(v) if v.strip().lstrip("-").isdigit() else float(v)
        except ValueError as exc:
            raise ValueError(f"{k}: not a number ({v})") from exc
    return out


def cmd_publishability(args) -> int:
    _pipe, st, proj = _load()
    from . import publishability as pb
    try:
        if args.action == "record":
            ev: dict = {}
            if args.evidence:
                ev = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
                if not isinstance(ev, dict):
                    raise ValueError("--evidence must hold a JSON object")
            if args.design:
                ev["design"] = args.design
            if args.count:
                ev.setdefault("counts", {}).update(_kv(args.count))
            if args.recommend:
                ev["recommendation"] = args.recommend
            entry = pb.record(proj, args.stage, args.verdict, args.article_type, ev,
                              args.summary or "")
            st.event("publishability", f"{args.stage}={args.verdict} ({args.article_type})")
            st.save()
            print("Send the user these lines now (Chinese, unchanged):")
            print("\n".join(f"  {x}" for x in pb.message_zh(args.stage, entry)))
            if entry["verdict"] != "GO":
                print(f"STOP: wait for the user's one answer, then `wf publishability answer "
                      f"--stage {args.stage} --choice continue|change|stop --words \"<原话>\"`.")
            return 0
        if args.action == "answer":
            entry = pb.answer(proj, args.stage, args.choice, args.words or "")
            st.event("publishability_answer", f"{args.stage}: {args.choice}")
            st.save()
            print(f"已记录 {args.stage} 用户选择：{pb.CHOICE_ZH[args.choice]}（“{args.words}”）。"
                  + ("请停止本论文的后续工作。" if args.choice == "stop" else ""))
            return 0
        if args.action == "value":
            row = pb.value(proj, args.analysis or "", args.could_change or "", args.cost or "",
                           args.benefit or "")
            print(pb.value_line_zh(row))
            return 0
        data = pb.load(proj)
        if not data["checkpoints"]:
            print("尚无可发表性检查记录。")
        for stage, e in sorted(data["checkpoints"].items()):
            dec = e.get("user_decision") or {}
            print(f"{stage}: {e['verdict']} / {e['article_type']} ({e['at'][:10]})"
                  + (f"; 用户：{dec.get('choice')}" if dec else ""))
        for row in data["additional"][-5:]:
            print("  " + pb.value_line_zh(row))
        return 0
    except (OSError, ValueError) as exc:
        print(f"publishability refused: {exc}")
        return 2


def data_availability(proj: Path, args) -> int:
    """`wf data licence NAME ...` and `wf data availability` (1.23.0, S6)."""
    from . import dataavail as da
    from .state import State
    try:
        if args.action == "licence":
            if not args.path:
                raise ValueError("wf data licence NAME --licence L --access A --url U [--doi D] "
                                 "--source <public page> [--checked YYYY-MM-DD]")
            rec = da.record(proj, args.path, args.licence, args.access, args.url or "",
                            args.source, args.doi, args.checked, args.label or "")
            st = State(proj, ".wf").load()
            st.event("data_licence", f"{args.path}: {rec['access']} ({rec['licence']}); "
                                     f"{rec['source']}")
            st.save()
            print(f"recorded {args.path}: {rec['access']}, {rec['licence']}, checked "
                  f"{rec['checked']} at {rec['source']}")
            return 0
        text = da.statement(proj)
        print("Data availability statement (from the verified records; paste it under the Data "
              "availability heading of statements.md):")
        print(f"  {text or '(no data source recorded yet: wf data licence ...)'}")
        for prob in da.problems(proj):
            print(f"  TODO {prob}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2


def add_parsers(sub) -> None:
    p = sub.add_parser("publishability", help="1.23.0 publishability checkpoints at S02/S04/S06: "
                                              "record --stage S02|S04|S06 --verdict GO|CONDITIONAL|"
                                              "NO-GO --article-type T [--evidence F.json] "
                                              "[--design KEY --count M=V ...] | answer --stage S "
                                              "--choice continue|change|stop --words W | value "
                                              "--analysis A --could-change C --cost X --benefit "
                                              "low|medium|high | show")
    p.add_argument("action", choices=("record", "answer", "value", "show"))
    p.add_argument("--stage", choices=("S02", "S04", "S06"))
    p.add_argument("--verdict", choices=("GO", "CONDITIONAL", "NO-GO"))
    p.add_argument("--article-type", dest="article_type",
                   choices=("original_article", "brief_report", "research_letter",
                            "not_publishable"))
    p.add_argument("--evidence", type=Path, default=None, help="JSON evidence object")
    p.add_argument("--design", default="", help="S04: key of reference/publishability.toml")
    p.add_argument("--count", action="append", default=[], help="S04: METRIC=VALUE")
    p.add_argument("--recommend", choices=("continue", "change", "stop"), default=None)
    p.add_argument("--summary", default="", help="one Chinese line for the user")
    p.add_argument("--choice", choices=("continue", "change", "stop"))
    p.add_argument("--words", default="")
    p.add_argument("--analysis", default="")
    p.add_argument("--could-change", dest="could_change", default="")
    p.add_argument("--cost", default="")
    p.add_argument("--benefit", choices=("low", "medium", "high"), default=None)
    p.set_defaults(fn=cmd_publishability)
