"""推送正文渲染（T10）——cmd_run L1644-1672 五个分支的纯函数化。

正文是给她看的：措辞逐字保留（「需人工」「不代点」「证据 <路径>」），
字段缺省时也有像样的占位（「读不到」）。标题在 terminal.notify_title（已测）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.workflow.terminal import notify_title


@dataclass(frozen=True, slots=True)
class NotifyInput:
    rc: int
    lit: int | None
    evidence_dir: str
    steps: str = "subsidy bag light"
    done_word: str | None = None
    pend_line: str | None = None       # 整页 OCR 抄下来的那句（lit4 正文用）
    pend_days: int | None = None
    pend_msg: str = ""                 # 账本写入描述（lit4）
    exc_msg: str = ""                  # 账本描述（lit2）
    verify_why: str = ""               # rc6 的原因
    last_activity: str | None = None   # 收尾前最后前台（None/空 → 「读不到」）
    proof_kind: str = ""               # 判定核给的证据档（正文措辞参考）
    app_closed: bool | None = None     # 11-18 铁律：收尾后 pidof 核验（None=没跑核验路径）


def _last_act(last_activity: str | None) -> str:
    return last_activity or "读不到"


def _close_line(app_closed: bool | None) -> str:
    """11-18 铁律的收尾一句：核验过=报平安，核验失败=大声喊。"""
    if app_closed is True:
        return "拼多多已关闭（进程核验过）。"
    if app_closed is False:
        return "⚠️ 拼多多没能关掉（force-stop 后进程还在），需要你手动关一下。"
    return ""


def render_notification(inp: NotifyInput) -> tuple[str, str]:
    """返回 (title, body)。分支与 cmd_run L1644-1672 一致。

    11-18 铁律：每个分支末尾都带 app 关闭核验句（app_closed=None 时无——
    dry-run/未开终态效果的场合不虚报）。
    """
    title = notify_title(rc=inp.rc, lit=inp.lit, done_word=inp.done_word)
    ev = inp.evidence_dir
    close = _close_line(inp.app_closed)
    if inp.lit == 2:
        body = (
            "走到点亮那一步，屏幕上写的是「立即兑换」，脚本不代点。\n"
            "按旧约定这一屏给你留着接手；按 11-18 新约定 app 已统一关掉，\n"
            "明天同一时间照常自己跑。\n"
            f"{inp.exc_msg}\n"
            f"{close}\n"
            f"证据 {ev}"
        )
        return title, body
    if inp.lit == 4:
        line = inp.pend_line or "点亮任务已完成，N天后可兑换"
        body = (
            f"进度那一行（原来写着「N天内点亮X次必得」）没了，现在是：{line}\n"
            f"{inp.pend_msg}\n"
            "今天的完成标记已写。本轮已把拼多多关掉（旧「app 留在屏上等兑换」"
            "口径 11-18 起废除）；等到屏幕上换成「立即兑换」那天，"
            "推送标题换成「需人工」，那一下同样只喊你不代点。\n"
            f"{close}\n"
            f"证据 {ev}"
        )
        return title, body
    if inp.rc == 0:
        if inp.lit == 1:
            first = f"屏幕上写着「{inp.done_word or '已点亮/已使用'}」，没重复点，也没往下点"
        else:
            first = "三步点完，活动页那行进度核实过 + 下滑跑完"
        body = f"{first}\n步骤 {inp.steps}\n{close}\n证据 {ev}"
        return title, body
    if inp.rc == 6:
        why = inp.verify_why or "点完了但屏幕上进度行的次数没变小"
        body = (
            f"{why}\n"
            "当失败处理，没写今天的完成标记，明天会自己再来一遍。\n"
            f"最后停在 {_last_act(inp.last_activity)} 这一屏，{close}\n"
            f"证据 {ev}"
        )
        return title, body
    body = (
        f"最后停在 {_last_act(inp.last_activity)} 这一屏"
        "（登录页/验证码之类也长这样，脚本不代填）。\n"
        f"{close}\n"
        f"看 {ev}/run.log"
    )
    return title, body
