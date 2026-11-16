"""T63（2026-11-17）：证据落盘——每次运行留 run.log + 截图（旧 EVIDENCE_DIR 口径回归）。

旧 pdd.sh：`<证据根>/<日期>/<HHMMSS>/`（run.log + 截图 + summary）；重构版丢了这层，
11-14/11-15 连续 rc4 却查不动「点没点中」。EvidenceWriter 恢复旧口径，语义：
- 惰性建目录：第一条日志/截图写入才创建；
- 任何 I/O 失败只记 errors，绝不挡业务（I11）；
- declare() 给通知正文用（先按约定路径展示，与旧脚本 mkdir -p 在前同口径）。
"""

from __future__ import annotations

from pddcheck.storage import EvidenceWriter


def test_evidence_writer_lazy_dir_and_log(tmp_path):
    w = EvidenceWriter(tmp_path, "2026-11-17", run_stamp="101500")
    # declare 不创建目录（通知正文先按约定路径展示）
    declared = w.declare()
    assert declared.endswith("2026-11-17\\101500") or declared.endswith("2026-11-17/101500")
    assert not (tmp_path / "2026-11-17").exists()
    w.log("stage ready:ok")
    d = tmp_path / "2026-11-17" / "101500"
    assert d.is_dir()
    assert "ready:ok" in (d / "run.log").read_text(encoding="utf-8")
    w.log("stage entry:ok")
    lines = (d / "run.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                      # 追加不覆盖


def test_evidence_writer_shot_writes_png(tmp_path):
    w = EvidenceWriter(tmp_path, "2026-11-17", run_stamp="101500")
    w.shot(b"\x89PNG-fake", "stage-01")
    assert (tmp_path / "2026-11-17" / "101500" / "stage-01.png").read_bytes() == b"\x89PNG-fake"


def test_evidence_writer_never_raises_on_io_error(tmp_path):
    # 把 stamp 目录做成**文件** → mkdir(parents) 必失败 → errors 记录、log/shot 静默
    (tmp_path / "2026-11-17").write_text("blocker", encoding="utf-8")
    w = EvidenceWriter(tmp_path, "2026-11-17", run_stamp="101500")
    w.log("no raise here")                      # 不抛
    w.shot(b"png", "x")                         # 不抛
    assert w.errors                             # 失败可见
    assert w.declare()                          # 正文路径照给


def test_evidence_writer_empty_shot_is_noop(tmp_path):
    w = EvidenceWriter(tmp_path, "2026-11-17", run_stamp="101500")
    w.shot(b"", "empty")                        # 空截图不建目录不留文件
    assert not (tmp_path / "2026-11-17").exists()
    assert not w.errors
