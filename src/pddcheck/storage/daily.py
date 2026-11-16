"""日标记与兑换账本（T08，I10/I12/I13）+ 证据落盘（T63，2026-11-17）。

- 日标记：`<证据根>/.done-<YYYY-MM-DD>` 存在即当天已完成（不重跑、不通知）；
- 账本：一个数字的文件（屏幕上「N天后可兑换」的 N）。口径（10-11 定案）：
  任何值都不挡路——读不到/垃圾/不存在一律当「没记过」，绝不能因此跳过当天。
- 证据落盘（T63）：旧 pdd.sh 每次运行写 `<根>/<日期>/<HHMMSS>/`（run.log+截图），
  重构版丢了这一层——11-14/11-15 连续 rc4 却查不动「点没点中」。EvidenceWriter
  恢复旧口径：失败只记 notes 绝不改业务 rc（I11 同款），写不进也不挡签到。
"""

from __future__ import annotations

import re
from pathlib import Path

from pddcheck.storage.atomic import atomic_write_text

_NUM = re.compile(r"[0-9]+")


class EvidenceWriter:
    """每次运行的证据目录（旧 EVIDENCE_DIR/<date>/<HHMMSS>/ 口径）。

    - run_dir：首次访问时创建并返回（同一 writer 复用同一次运行的目录）；
    - log(line)：追加一行 run.log（时间戳前缀由调用方给或此处补）；
    - shot(png_bytes, name)：落一张截图；
    - 任何 I/O 失败都吞掉并置 self.errors——证据是附属品，绝不挡业务（I11）。
    落盘动作**惰性**：run_dir 在第一次写时才创建，全程没写就不留空目录。
    """

    def __init__(self, evidence_root: Path, business_date: str,
                 run_stamp: str | None = None) -> None:
        self._root = Path(evidence_root)
        self._date = business_date
        self._stamp = run_stamp
        self._dir: Path | None = None
        self._declared = False          # run_dir 已要过（哪怕创建失败也不再重试）
        self.errors: list[str] = []

    def _ensure_dir(self) -> Path | None:
        if self._dir is not None:
            return self._dir
        if self._declared:
            return None
        self._declared = True
        if self._stamp is None:
            from datetime import datetime
            self._stamp = datetime.now().strftime("%H%M%S")
        d = self._root / self._date / self._stamp
        try:
            d.mkdir(parents=True, exist_ok=True)
            self._dir = d
        except OSError as exc:
            self.errors.append(f"mkdir: {exc}")
        return self._dir

    def declare(self) -> str | None:
        """预告本次运行的证据目录（不创建）；返回相对展示路径或 None。

        通知正文里的「证据 <路径>」用这个：目录真的建出来（首条日志/截图写入）
        之前，正文先按约定路径展示——与旧脚本口径一致（旧脚本 mkdir -p 在前）。
        """
        if self._stamp is None:
            from datetime import datetime
            self._stamp = datetime.now().strftime("%H%M%S")
        return str(self._root / self._date / self._stamp)

    def log(self, line: str) -> None:
        d = self._ensure_dir()
        if d is None:
            return
        try:
            with open(d / "run.log", "a", encoding="utf-8") as fh:
                fh.write(line.rstrip("\n") + "\n")
        except OSError as exc:
            self.errors.append(f"log: {exc}")

    def shot(self, png: bytes, name: str) -> None:
        if not png:
            return                                  # 空截图：连目录都不建
        d = self._ensure_dir()
        if d is None:
            return
        try:
            (d / f"{name}.png").write_bytes(png)
        except OSError as exc:
            self.errors.append(f"shot {name}: {exc}")


class DailyStore:
    def __init__(self, evidence_root: Path, ledger_path: Path) -> None:
        self.evidence_root = Path(evidence_root)
        self.ledger_path = Path(ledger_path)

    # ---- 日标记 -------------------------------------------------------
    def marker_path(self, business_date: str) -> Path:
        return self.evidence_root / f".done-{business_date}"

    def marker_exists(self, business_date: str) -> bool:
        return self.marker_path(business_date).exists()

    def write_marker(self, business_date: str) -> None:
        atomic_write_text(self.marker_path(business_date), "")

    # ---- 兑换账本（兼容旧 $HOME/Desktop/pdd-pause）--------------------
    def ledger_read(self) -> int | None:
        """读账本数字；不存在/空/垃圾 → None（不挡路，只当没记过）。"""
        try:
            text = self.ledger_path.read_text(encoding="utf-8")
        except OSError:
            return None
        m = _NUM.search(text)
        return int(m.group()) if m else None

    def ledger_write(self, value: int) -> bool:
        """写账本；返回是否真的写进去（写失败不改业务 rc，但 operational_status 可见）。"""
        try:
            atomic_write_text(self.ledger_path, f"{value}\n")
            return True
        except OSError:
            return False

    def ledger_clear(self) -> bool:
        return self.ledger_write(0)

    # ---- 证据保留（迁移审计 G9：旧 prune_evidence / KEEP_DAYS 口径）----
    def prune_evidence(self, keep_days: int) -> int:
        """删除证据根下 keep_days 天前的**一层日期目录**；返回删除数。

        旧口径（pdd.sh L1491-1494）：`find -mindepth 1 -maxdepth 1 -type d
        -mtime +KEEP_DAYS -exec rm -rf` —— 只删目录，`.done-*` 标记文件
        与证据根本身不动。keep_days<=0 或根不存在时一个都不删。
        """
        if keep_days <= 0:
            return 0
        import shutil
        import time as _time
        cutoff = _time.time() - keep_days * 86400
        removed = 0
        try:
            entries = list(self.evidence_root.iterdir())
        except OSError:
            return 0
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
                if entry.stat().st_mtime <= cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed
