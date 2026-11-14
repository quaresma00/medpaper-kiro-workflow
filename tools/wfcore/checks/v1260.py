"""1.26.0 checks (a paper pinned earlier gets them after `wf migrate --yes` or a journal switch).

package_audit_ready   S24: the user confirms only a package the independent auditor read in
                      full at least once this journal epoch (round 1 = the full audit) and whose
                      last audit round read exactly what is confirmed (a round that changed an
                      upload is re-audited first); a BLOCKED audit waits for the missing fact.
                      S25 (final): additionally the freeze binds that last round, the frozen
                      uploads are what it read, and PASS needs its verdict PASS (the author final
                      copy stays the route around a REVISE). A freeze taken in the earlier order
                      (no audited round in it) keeps the S25 audit and passes here.
"""
from __future__ import annotations

from . import Ctx, Result, check
from ..packageaudit import SINCE, freeze_round, problems, since_1260


def _pinned(name: str) -> Result:
    return Result(True, name, f"applies from engine {SINCE} (`wf migrate --yes`); paper pinned "
                              "earlier: the package audit runs at S25 as before")


@check("package_audit_ready")
def package_audit_ready(ctx: Ctx) -> Result:
    name = "package_audit_ready"
    final = bool(ctx.spec.get("final"))
    if not since_1260(ctx):
        return _pinned(name)
    if final and not freeze_round(ctx.project):
        return Result(True, name, "the package freeze predates the 1.26.0 order (no audited "
                                  "round in it): S25 runs the independent audit "
                                  "(package_review.py audit-start)")
    probs = problems(ctx.project, final=final, state=ctx.state)
    if probs:
        return Result(False, name, "; ".join(probs[:4]),
                      ["Round 1 at S24 is the full audit (`review_round.py start --scope "
                       "package`); after fixes re-audit at once (`start --delta`) until a round "
                       "changes nothing; only then the one confirmation message."])
    from ..reviewrounds import load
    last = load(ctx.project)["package"][-1]
    return Result(True, name, f"last audit round {last['id']} ({last.get('mode')}, verdict "
                              f"{last.get('audit_verdict') or '-'}) read exactly this package")
