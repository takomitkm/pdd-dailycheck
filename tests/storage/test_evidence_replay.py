"""证据落盘 → replay 闭环：manifest / events / tsv 三项齐了才回放得动。

2026-11-19 迁移补齐：run 以前只落 run.log + PNG，`pddcheck replay` 一律 INCOMPLETE。
"""

from pathlib import Path

from pddcheck.replay.trace import ReplayStatus, exact_replay, load_run
from pddcheck.storage.daily import EvidenceWriter


def test_evidence_writer_feeds_replay(tmp_path: Path):
    w = EvidenceWriter(tmp_path, "2026-11-19", run_stamp="100000",
                       run_id="run-2026-11-19")
    w.manifest({"date": "2026-11-19", "profile_id": "pdd-v1"})
    w.tsv("obs-01-tesseract_page", "level\ttext\n5\t抽福袋\n")
    w.event("step", "check_before", before_count=5)
    w.event("verify", "verify_observation", stage="after_direct", after_count=4,
            done_text=False, prize_text=False, pend_text=False)
    w.event("commit", "outcome", lit=3, rc=0)
    w.log("run done: exit=0")

    run_dir = tmp_path / "2026-11-19" / "100000"
    trace = load_run(run_dir)
    assert trace.complete, trace.missing
    assert trace.manifest["run_id"] == "run-2026-11-19"

    res = exact_replay(trace)
    assert res.status is ReplayStatus.OK
    assert res.derived_lit == 3


def test_evidence_writer_never_raises_on_bad_root(tmp_path: Path):
    """证据写不进只记 errors，绝不抛（I11）。"""
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    w = EvidenceWriter(blocker, "2026-11-19")
    w.event("step", "check_before", before_count=1)   # 不抛即可
    w.tsv("obs-01", "x")
    assert w.errors