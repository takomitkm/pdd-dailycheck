"""终态收尾计划（T11 2/2）——cmd_run 收尾段（L1589-1674）的纯函数化。

对应 acceptance §5 的效果映射表：lit/rc → 标记/账本/关应用/推送标题。
注意三点（2026-11-18 用户铁律修订）：
- **任何结果都要关 app**（用户 11-18 定：不管成功与失败，跑完之后都关掉拼多多，
  并确保真的关掉）：旧约定「lit2/4 留屏不关」（I02/I13）与「rc≠0 只 HOME」
  （B07）废除——close_policy 恒为 STOP_AND_HOME，且 STOP 后用 pidof 验证
  进程真死（见 flow._apply_close_policy），关不掉要在推送里喊出来；
- 早退（日标记已存在等）由执行器在早退 return 之前另行兜底关一次；
- rc∈{2,3,69,78,73,75} 仍是收尾段之前的早退：零设备动作（75 锁冲突连关都
  不做——另一个实例可能正在跑）、rc2/3 有对应通知，rc69/78 静默（B02）；
  这些不进本函数（执行器直接短路），函数只收「跑完主循环」的 rc。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClosePolicy(StrEnum):
    STOP_AND_HOME = "stop_and_home"   # force-stop（pidof 验证）+ HOME：唯一收尾（11-18 铁律）
    STAY = "stay"                     # 已废除（旧 lit2/4 口径）——保留枚举兼容旧 RunOutcome 字符串
    HOME_ONLY = "home_only"           # 已废除（旧 rc≠0 口径）——同上


def notify_title(*, rc: int, lit: int | None, done_word: str | None) -> str:
    """推送标题五档（她 10-27 定的口径：不带日期）。"""
    if lit == 2:
        return "PDD 需人工"
    if lit == 4:
        return "PDD 💡"
    if rc == 0:
        if done_word and "已使用" in done_word:
            return "PDD 已使用"
        return "PDD ✅"
    if rc == 6:
        return "PDD ⬛ 退出码 6"
    return f"PDD ❌ 退出码 {rc}"


def ledger_plan(*, lit: int | None, rc: int, pend_days: int | None,
                ledger_current: int | None) -> int | None:
    """账本写入值；None=一个字都不写。

    - lit1/lit2：清 0（正常周期 / 倒数走完）；
    - lit4：屏幕 N 照抄 → 账上正数减 1 → 都没有则不写（旧 pend_pause_write 三分支）；
    - rc0 且 lit∈{0,3}：清 0（兑换倒数作废）；
    - rc≠0：不写（不以失败覆盖账本）。
    """
    if lit == 1 or lit == 2:
        return 0
    if lit == 4:
        if pend_days is not None:
            return pend_days
        if ledger_current is not None and ledger_current > 0:
            return ledger_current - 1
        return None
    if rc == 0 and lit in (0, 3):
        return 0
    return None


@dataclass(frozen=True, slots=True)
class TerminalPlan:
    marker_write: bool
    ledger_write: int | None
    close_policy: ClosePolicy
    notify_title: str
    final_scroll: bool        # rc0 且 lit∈{0,3} 的最终 20 次下滑（I06；lit2/4 绝不滑）


def terminal_plan(*, rc: int, lit: int | None, done_word: str | None = None,
                  pend_days: int | None = None, ledger_current: int | None = None,
                  close_app_on_ok: bool = True,
                  no_close_lit: tuple[int, ...] = (2, 4)) -> TerminalPlan:
    """主循环跑完后的收尾计划。rc 必须是「主循环退出码」（0/4/5/6/7…），早退路径不进这里。

    11-18 铁律：不管 rc/lit 是什么都 STOP_AND_HOME。close_app_on_ok 与
    no_close_lit 参数保留（调用方契约不动），但不再改变收尾语义。
    """
    if rc == 0:
        marker = lit in (1, 3, 4) or lit == 0        # rc0&lit0 兼容分支（B05，不可达但保留）
        ledger = ledger_plan(lit=lit, rc=rc, pend_days=pend_days, ledger_current=ledger_current)
        final_scroll = lit in (0, 3)
        title = notify_title(rc=rc, lit=lit, done_word=done_word)
        return TerminalPlan(marker, ledger, ClosePolicy.STOP_AND_HOME, title, final_scroll)
    # rc≠0：不写标记、不写账本；收尾同样 force-stop + HOME（11-18 铁律，废 B07）
    title = notify_title(rc=rc, lit=lit, done_word=done_word)
    return TerminalPlan(False, None, ClosePolicy.STOP_AND_HOME, title, False)
