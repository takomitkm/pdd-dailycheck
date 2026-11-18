"""从一次共享观察里抽取流程事实（事实层，纯函数）。

进度行口径（旧 light_count）：屏幕上「N天内点亮M次必得」/「M天内点亮X次」里的
**剩余次数**；以及 done/exchange/pend/prize 的字样存在性。全部基于 perception 的
规范化文本，不改写 OCR 原文，只产出结构化事实。

词表口径（2026-11-18 迁移补齐，逐条对应旧 pdd.sh 的 ALIAS_*）：
  ALIAS_done     = 已点亮|明日再来|明天再来|已使用          （L97）
  ALIAS_exchange = 立即兑换|去兑换                          （L98）
  ALIAS_prize    = 翻倍券|提前锁定                          （L104）
  ALIAS_pend     = 任务已完成|天后可兑换|待兑换             （L115，另加「券已放进口袋」）
旧版这里只认「今日已点亮 / 立即兑换 / 恭喜提前锁定」，是词表窄化：
「已使用 / 明日再来 / 明天再来」一个都不认，导致「PDD 已使用」那档标题不可达
（10-25/10-26 连报两天假失败就是这一类）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pddcheck.perception.normalize import normalize

# 10-16 措辞变更两种都认；抓「点亮」前后的数字
_COUNT = re.compile(r"(\d+)天内点亮(\d+)次|点亮(\d+)次必得|再点亮(\d+)次")

DONE_LABELS = ("已点亮", "明日再来", "明天再来", "已使用")
EXCHANGE_LABELS = ("立即兑换", "去兑换")
PEND_LABELS = ("任务已完成", "天后可兑换", "待兑换", "券已放进口袋")
PRIZE_LABELS = ("翻倍券", "提前锁定")


@dataclass(frozen=True, slots=True)
class ScreenFacts:
    progress_count: int | None
    done_text: str | None
    exchange_text: str | None
    pend_text: str | None
    prize_text: str | None
    pend_days: int | None
    pend_line: str | None


def read_progress_count(text: str) -> int | None:
    """从整帧 OCR 文本里读「剩余次数」；读不到 → None（不是 0）。"""
    clean = normalize(text)
    m = _COUNT.search(clean)
    if not m:
        return None
    for g in (m.group(2), m.group(3), m.group(4)):
        if g is not None:
            return int(g)
    return None


def read_pend_days(text: str) -> int | None:
    clean = normalize(text)
    m = re.search(r"(\d+)天后可兑换", clean)
    return int(m.group(1)) if m else None


def _first_present(clean: str, labels: tuple[str, ...]) -> str | None:
    """返回第一个在规范化文本里出现的词（按词表顺序，与旧 case 分支同序）。"""
    for lb in labels:
        norm = normalize(lb)
        if norm and norm in clean:
            return lb
    return None


def facts_from_text(ocr_text: str, *, done_labels: tuple[str, ...] = DONE_LABELS,
                    exchange_labels: tuple[str, ...] = EXCHANGE_LABELS,
                    pend_labels: tuple[str, ...] = PEND_LABELS,
                    prize_labels: tuple[str, ...] = PRIZE_LABELS) -> ScreenFacts:
    clean = normalize(ocr_text)
    return ScreenFacts(
        progress_count=read_progress_count(ocr_text),
        done_text=_first_present(clean, done_labels),
        exchange_text=_first_present(clean, exchange_labels),
        pend_text=_first_present(clean, pend_labels),
        prize_text=_first_present(clean, prize_labels),
        pend_days=read_pend_days(ocr_text),
        pend_line=None,
    )
