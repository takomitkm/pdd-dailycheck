"""run 编排（T14 2/2）：把判定核与端口装配成一条可测的端到端管线。

顺序固定（契约/acceptance）：
  预检→锁→读日标记（--force 只跳标记）→读屏事实→点前终态→点亮→核实→
  终态效果（marker/ledger/close）→通知→（证据由调用方落）

设计：所有副作用都从构造期注入，没有任何全局/环境读取；因此可用 FakeClock/
FakeDevice/FakeScreen 在毫秒内跑完整管线。业务失败绝不因通知失败而改写（I11）。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Protocol

from pddcheck.exits import ExitCode, exit_for_outcome
from pddcheck.domain import ActionKind, ActionIntent, ExecutionStatus, WindowKind
from pddcheck.notify import NotificationSender, NotifyInput, render_notification
from pddcheck.storage import DailyStore, Journal, LockBusy
from pddcheck.workflow.check_before import CheckBeforeKind, check_done_before_decision
from pddcheck.workflow.terminal import terminal_plan
from pddcheck.workflow.verify import (
    VerifyObservation,
    VerifyStage,
    verify_light_decision,
)


class ScreenPort(Protocol):
    """读屏事实（生产里 = 采集+OCR+感知的组合；测试里 = 脚本）。"""

    def light_facts(self) -> dict: ...

    def post_tap_observations(self, stage: VerifyStage = VerifyStage.AFTER_DIRECT
                              ) -> tuple[VerifyObservation, ...]:
        """核实观察。stage=本次读屏属于 verify 阶梯的哪一级（G1 接线）；
        阶梯关（47 案基线）时调用方不传参，实现按 AFTER_DIRECT 标注。"""
        ...

    def locate_target(self, key: str) -> tuple[int, int] | None:
        """G1/G2/G5：当前帧上定位某目标（bag 胶囊/popup 关闭词），没有则 None。

        语义协议（生产 ScreenPort 必须真实现）：纯观察帧定位，绝不点、绝不盲点
        坐标兜底——认不到字就 None（旧 text_present 口径）。
        测试 Screen 可不实现（getattr 鸭子判断会跳过）。
        """
        ...


@dataclass(frozen=True, slots=True)
class RunOutcome:
    exit_code: ExitCode
    lit: int | None
    rc: int
    title: str
    body: str
    delivered: str | None = None
    marker_written: bool = False
    ledger_written: int | None = None
    close_policy: str | None = None
    skipped: str | None = None         # daily_marker / force 等跳过原因
    notes: tuple[str, ...] = field(default=())


@dataclass(slots=True)
class RunDeps:
    device: object                       # DevicePort
    screen: ScreenPort
    store: DailyStore
    journal: Journal | None
    notifier: NotificationSender
    endpoint: str | None
    evidence_dir: str
    business_date: str
    run_id: str
    now_ns: object                        # () -> int
    lease_factory: object | None = None  # () -> RunLease（可空=不取锁）
    force: bool = False
    close_app_on_ok: bool = True
    steps_label: str = "subsidy bag light"
    # 流程段（就绪/入口/福袋）失败时由调用方带进来的 rc（4/5/7）：
    # 一旦非空，run_once 直接按该 rc 收尾，不再执行点亮段（真机教训：
    # 阶段失败后继续跑点亮会拿错页的事实做弱证明 → 误报 lit3）。
    stage_failure_rc: int | None = None
    stage_failure_why: str | None = None
    # 纯观察（--dry-run）：识别与决策照做，但**不执行任何业务动作、不写标记/账本、不推送**。
    # 用途：并行观察期只取证，确认新流程的判断与旧流程一致，而不代替签到。
    dry_run: bool = False
    # 点亮后的浏览任务段（生产 11-08 实测必需：点「立即点亮」后是「滑动浏览10秒」页）。
    # 默认 False：47 案行为基线不包含浏览段；CLI 真机路径显式开启。
    browse_after_light: bool = False
    browse_sleep: object | None = None   # 注入 sleep（测试用）；默认 time.sleep
    # 关闭核验的观察窗（11-20 复盘）：force-stop 后不能只看 3s——`:titan` 的 wakeup
    # alarm 可能等到 ~7s 才把主进程拉活（11-20 00:11:16 实证）。默认空 = 只验一次
    # （47 案基线/单测零等待）；生产由 PipelineConfig.close_waits_s=(3,6) 灌两段窗口。
    close_waits_s: tuple[float, ...] = ()
    # 终态效果执行（G4/G8 迁移审计补上）：final_scroll（I06 最终 20 次下滑）、
    # close_policy 下发（rc0 force-stop+HOME / rc≠0 HOME / lit2/4 不动）、
    # last_activity 采集。默认 False 保持 47 案基线；CLI 真机路径显式开启。
    execute_terminal_effects: bool = False
    # 证据保留天数（G9：旧 KEEP_DAYS=7；None/0=不清理）
    keep_days: int | None = 7
    # G1/G2/G3/G5（迁移审计）：verify 四阶段阶梯真执行——浏览滑完 BACK 回落点核实、
    # 落频道页认到 bag 再点回活动页、清浮层复读、重进福袋页兜底、奖励浮层点「开心收下」。
    # 默认 False（47 案基线只喂 AFTER_DIRECT）；CLI 真机路径显式开启。
    verify_ladder: bool = False
    # 证据 run.log 追加回调（T63，2026-11-17）：None=不落（47 案基线/测试）。
    # 业务动作与收尾的关键事件逐行落 run.log——11-14/15 连续 rc4 无法定位的教训。
    # 回调内部自己的 I/O 失败由实现方吞掉；这里绝不因落盘失败改业务 rc（I11）。
    evidence_log: object | None = None


def _exit(rc: int, lit: int | None) -> ExitCode:
    return exit_for_outcome(rc=rc, lit=lit)


def _evlog(deps: RunDeps, line: str) -> None:
    """证据 run.log 追加（evidence_log=None 时空操作）；失败绝不外抛（I11）。

    落盘失败本身就是 evidence.errors 里的事实，这里不需要再记——
    证据是附属品，任何异常都不允许污染业务 rc（I11 的证据版）。
    """
    log = getattr(deps, "evidence_log", None)
    if log is None:
        return
    try:
        log(line)
    except Exception as _exc:                        # noqa: BLE001 — 证据不挡业务（I11）
        print(f"evidence log failed (ignored): {_exc}", file=sys.stderr)


def run_once(deps: RunDeps) -> RunOutcome:
    notes: list[str] = []

    # 1) 锁（早退：75）
    lease = None
    if deps.lease_factory is not None:
        try:
            lease = deps.lease_factory()
        except LockBusy:
            return RunOutcome(ExitCode.LOCK_BUSY, None, 75, "PDD ⛔ 并发抢锁", "",
                              skipped="lock_busy", notes=("另一个实例持锁",))
    try:
        # 2) 日标记（--force 只跳过它，不跳锁/焦点/人工兑换边界——I10）
        if not deps.force and deps.store.marker_exists(deps.business_date):
            # 11-18 铁律：早退也要关 app——昨天 10:00 就是这条路径把 PDD 留在前台的
            #（凌晨成功写标记后，定时跑进这里直接 return，前面 ready 段已把 PDD 拉起）。
            _force_close_quiet(deps, notes, why="早退（标记已存在）")
            return RunOutcome(ExitCode.OK, None, 0, "PDD 已完成（今日）", "标记已存在",
                              skipped="daily_marker",
                              notes=tuple(notes) + ("日标记已存在，未动作",))
        if deps.force and deps.store.marker_exists(deps.business_date):
            notes.append("--force：跳过日标记，其它边界照旧")

        # 3) 点前终态（含就绪/入口/福袋段；阶段失败→rc4/5 直接收尾）
        from pddcheck.workflow.stages import StageFailure
        stage_rc: int | None = getattr(deps, "stage_failure_rc", None)
        facts: dict = {}
        pre = None
        if stage_rc is not None:
            notes.append(f"阶段失败 rc={stage_rc}：{getattr(deps, 'stage_failure_why', '')}")
            _evlog(deps, f"stage_failure rc={stage_rc}: {getattr(deps, 'stage_failure_why', '')}")
        else:
            try:
                facts = deps.screen.light_facts()
                _evlog(deps, f"light_facts: done={facts.get('done_text')} "
                       f"exchange={facts.get('exchange_text')} pend={facts.get('pend_text')} "
                       f"before={facts.get('before_count')} tap={facts.get('tap_point')}")
            except StageFailure as exc:
                stage_rc = exc.rc
                notes.append(f"阶段失败 rc={exc.rc}：{exc.why}")
                _evlog(deps, f"stage_failure rc={exc.rc}: {exc.why}")

        lit: int | None = None
        rc = 0
        if stage_rc is None:
            pre = check_done_before_decision(
                done_text=facts.get("done_text"),
                exchange_text=facts.get("exchange_text"),
                pend_text=facts.get("pend_text"),
                before_count=facts.get("before_count"))
            if pre.kind is CheckBeforeKind.DONE:
                lit = 1
            elif pre.kind is CheckBeforeKind.EXCHANGE:
                lit = 2
            elif pre.kind is CheckBeforeKind.PENDING:
                lit = 4                  # pend 是 lit=4，进程码 0（acceptance §5）
            elif deps.dry_run:
                # 纯观察：本来会点这一枪，但**不点**（也不核实、不写标记）。
                lit = 0
                notes.append(f"dry-run：本来会点 {pre.before_count} 那一枪"
                             f"（method={pre.kind.value}），本次不执行")
            elif facts.get("tap_point") is None:
                # 整页+裁片都定位不到「立即点亮」：两种可能——
                # a) 已在**浏览任务页**（点完立即点亮后；该页横幅 OCR 读不出，
                #    pdd.sh L243 实测「四档全瞎」，不能靠文本判定）；
                # b) 页面被弹窗/其他覆盖。
                # 滑动是**无害动作**（在 pdd 页面内滚动），滑满 10s 后再诚实核实：
                # 点亮了 → lit3；没点亮 → rc6 不写标记（旧弱证明口径已废除）。
                if deps.dry_run:
                    notes.append("dry-run：定位不到「立即点亮」，本来会滑 15s 再核实，本次不滑")
                    lit = 0
                else:
                    # 先读一帧判「是不是真的浏览任务页」（旧 text_present browse）；
                    # 是才滑——不是就白滑 15s，还会把页面滚走。
                    pre_obs = deps.screen.post_tap_observations()
                    raw = getattr(deps.screen, "_last_raw_text", "")
                    swipe_ok = False
                    if _browse_present(raw):
                        notes.append("定位不到「立即点亮」→ 浏览任务页，滑 15s 后核实")
                        _evlog(deps, "light target not found -> browse page, swipe")
                        swipe_ok = _browse_after_light(deps, notes)
                        pre_obs = None            # 滑完必须重新观察
                    else:
                        notes.append("定位不到「立即点亮」且没认到浏览任务页 → 不滑，直接核实")
                        _evlog(deps, "light not found, not browse page -> verify only")
                    obs = _verify_after_light(deps, notes, browsed=swipe_ok,
                                              verify_ladder=getattr(deps, "verify_ladder", False),
                                              pre_obs=pre_obs)
                    decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                    rc, lit = decision.rc, decision.lit
                    notes.append(f"核实：{decision.proof_kind.value} — {decision.why}"
                                 + ("（浏览滑动已执行）" if swipe_ok else ""))
                    _evlog(deps, f"verify: {decision.proof_kind.value} {decision.why}")
            else:
                # 4) 点亮一枪 + 核实
                intent = _make_tap_intent(deps, facts)
                _evlog(deps, f"tap light at {facts.get('tap_point')}")
                receipt = deps.device.execute(intent, facts.get("tap_point"))
                if deps.journal is not None:
                    deps.journal.record_intent(intent.action_id, "tap",
                                               {"target": "light", "state_epoch": deps.device.state_epoch,
                                                "before_count": pre.before_count})
                    deps.journal.record_receipt(intent.action_id, receipt.status.value, receipt.error_code)
                if receipt.status is ExecutionStatus.UNKNOWN_EXECUTION:
                    notes.append(f"动作执行状态未知（{receipt.error_code}），不重发按无法核实")
                    rc, lit = 1, None
                else:
                    # 4.5) 点亮后的**浏览任务段**（生产 11-08 晚实测：点「立即点亮」
                    # 后跳到浏览页「滑动浏览当前页面10秒即可点亮」——必须滚动才算点亮。
                    # 旧脚本 I06 同款：最终 20 次下滑）。做完再核实。
                    swipe_ok = False
                    pre_obs = None
                    if getattr(deps, "browse_after_light", False):
                        pre_obs = deps.screen.post_tap_observations()
                        raw = getattr(deps.screen, "_last_raw_text", "")
                        if _browse_present(raw):
                            _evlog(deps, "browse page present -> swipe")
                            swipe_ok = _browse_after_light(deps, notes)
                            pre_obs = None
                        else:
                            notes.append("点亮后没认到浏览任务页 → 不滑")
                            _evlog(deps, "not a browse page -> skip swipe")
                    obs = _verify_after_light(deps, notes, browsed=swipe_ok,
                                              verify_ladder=getattr(deps, "verify_ladder", False),
                                              pre_obs=pre_obs)
                    decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                    rc, lit = decision.rc, decision.lit
                    _evlog(deps, f"verify: {decision.proof_kind.value} {decision.why}")
                    if decision.tap_point is not None and not deps.dry_run:
                        # G3：奖励浮层在场=点着了的凭据，顺手把「开心收下」点掉
                        #（契约 L197：只有奖励浮层证明分支允许 take；判定核给点才许点）
                        _take_prize(deps, decision.tap_point, notes)
                    notes.append(f"核实：{decision.proof_kind.value} — {decision.why}"
                                 + ("（浏览段已执行）" if swipe_ok else ""))

        # 内部 verify 的 rc=1（未过）对用户是 6（LIGHT_NOT_APPLIED）——acceptance §5
        business_rc = stage_rc if stage_rc is not None else (6 if rc == 1 else rc)
        done_word = pre.done_word if pre is not None else None

        # 5) 终态效果
        plan = terminal_plan(rc=business_rc, lit=lit, done_word=done_word,
                             pend_days=facts.get("pend_days"),
                             ledger_current=deps.store.ledger_read(),
                             close_app_on_ok=deps.close_app_on_ok)
        marker_written = False
        ledger_written = None
        operational_failed = False
        if deps.dry_run:
            # 纯观察：不写标记、不写账本（否则会把今天标成「已签到」而实际没点）
            notes.append("dry-run：跳过标记/账本写入与推送（只留证据）")
        else:
            try:
                if plan.marker_write:
                    deps.store.write_marker(deps.business_date)
                    marker_written = True
                    _evlog(deps, f"marker written: .done-{deps.business_date}")
                if plan.ledger_write is not None:
                    ok = deps.store.ledger_write(plan.ledger_write)
                    if not ok:
                        raise OSError("账本写入失败")
                    ledger_written = plan.ledger_write
                    _evlog(deps, f"ledger written: {ledger_written}")
            except OSError as exc:
                # D04：业务成功但状态落盘失败 → 进程码 73，业务 rc 另存，绝不虚称已写
                operational_failed = True
                notes.append(f"状态写入失败（operational）：{exc}")
                _evlog(deps, f"state write FAILED: {exc}")

        # 6) 终态效果执行（生产教训：terminal_plan 早就算出 close/final_scroll，
        #    但执行器只把它当字符串写进 RunOutcome、从不真正下发 → 跑成功既不关 app、
        #    也不做 I06 要求的最终 20 次下滑。这里补上。
        #    11-18 用户铁律：不管成功与失败都关掉拼多多并**确保关掉**——
        #    STOP 后用 pidof 验证进程真死，关不掉在推送里喊出来；lit2/4 旧「留屏」
        #    约定废除（等「立即兑换」那天来的时候，脚本反正自己会再开 app）。）
        last_activity = None
        app_closed_ok: bool | None = None
        if getattr(deps, "execute_terminal_effects", False) and not deps.dry_run:
            if plan.final_scroll and business_rc == 0:
                _final_scroll(deps, notes)
            # last_activity 必须在关 app 之前读（pdd.sh L1622：按完 HOME 就只剩桌面了）。
            last_activity = _read_last_activity(deps)
            _apply_close_policy(deps, plan, notes)
            _evlog(deps, f"close: {plan.close_policy.value} last_activity={last_activity}")
            # 证据保留（G9：旧 prune_evidence；失败只记 notes，不改业务 rc）
            if getattr(deps, "keep_days", None):
                try:
                    pruned = deps.store.prune_evidence(deps.keep_days)
                    if pruned:
                        notes.append(f"证据清理：删 {pruned} 个过期目录（keep_days={deps.keep_days}）")
                except Exception as exc:
                    notes.append(f"证据清理失败（忽略）：{exc}")

        # 7) 关闭核验（11-18 铁律的第二道闸：上面任何路径没关成，这里再兜一次；
        #    dry-run/未开终态效果/锁冲突 75 不进——75 另一个实例可能正在跑）
        if (not deps.dry_run and getattr(deps, "execute_terminal_effects", False)
                and business_rc != 75):
            app_closed_ok = ensure_app_closed(deps, notes)
            _evlog(deps, f"close_verify: closed={app_closed_ok}")

        # 8) 通知（失败不改业务 rc——I11）
        title, body = render_notification(NotifyInput(
            rc=business_rc, lit=lit, evidence_dir=deps.evidence_dir,
            steps=deps.steps_label, done_word=done_word,
            pend_days=facts.get("pend_days"),
            pend_line=facts.get("pend_line"),
            pend_msg="", exc_msg="", verify_why="",
            last_activity=last_activity,
            app_closed=app_closed_ok))
        if deps.dry_run:
            from pddcheck.notify import DeliveryResult, DeliveryStatus
            delivery = DeliveryResult(DeliveryStatus.SKIPPED, 0, None, "dry-run")
        else:
            delivery = deps.notifier.send(deps.endpoint, title, body)
        _evlog(deps, f"notify: {delivery.status.value} title={title}")

        if operational_failed:
            return RunOutcome(ExitCode.STATE_DIR_FAILED, lit, business_rc, title, body,
                              delivered=delivery.status.value,
                              marker_written=False, ledger_written=None,
                              close_policy=str(plan.close_policy),
                              notes=tuple(notes) + ("business_rc=" + str(business_rc),))
        return RunOutcome(_exit(business_rc, lit), lit, business_rc, title, body,
                          delivered=delivery.status.value,
                          marker_written=marker_written,
                          ledger_written=ledger_written,
                          close_policy=str(plan.close_policy),
                          notes=tuple(notes))
    finally:
        if lease is not None:
            lease.release()


def _verify_after_light(deps: RunDeps, notes: list, *, browsed: bool,
                        verify_ladder: bool,
                        pre_obs: tuple[VerifyObservation, ...] | None = None
                        ) -> tuple[VerifyObservation, ...]:
    """点亮后的核实观察收集。

    - verify_ladder=False（47 案基线）：照旧单次 post_tap_observations；
    - verify_ladder=True（G1/G2/G5 迁移）：跑旧 verify_light 的阶梯——
      1. browsed 时先 BACK 离开浏览/消费券页，落点读进度（AFTER_BACK）；
      2. 进度读不到且认到「抽福袋」胶囊 → 点它回活动页再读（AFTER_REENTER）；
      3. 仍读不到 → 清浮层（认到关闭词才点）再读（AFTER_POPUP）。
    未接线：AFTER_REENTER_BAG（重进福袋页兜底）要跨 StageRunner 层，本版不跑；
    不跑这条救场路的失败形态仍是 rc6（旧脚本这条路线失败也是 rc6）——
    只少一条救场路，不会多一次误报成功。每步动作失败只记 notes，
    观察交给 verify_light_decision 按旧阶梯判。
    """
    if not verify_ladder:
        return pre_obs if pre_obs is not None else deps.screen.post_tap_observations()

    obs: list[VerifyObservation] = []
    if browsed:
        # G2：BACK 离开浏览页（旧 L1316-1319「滑完必按 BACK」）
        _stage_back(deps, notes, "浏览完，按 BACK 离开消费券页")
        obs.extend(deps.screen.post_tap_observations(VerifyStage.AFTER_BACK))
        if _obs_count(obs) is None:
            # 落频道页且认到「抽福袋」胶囊 → 点回活动页（旧 L1322-1327）
            bag_point = _locate_on_screen(deps, notes, "bag")
            if bag_point is not None:
                _tap_point(deps, bag_point, "BACK 落在频道页，点「抽福袋」胶囊回活动页", notes)
                obs.extend(deps.screen.post_tap_observations(VerifyStage.AFTER_REENTER))
    else:
        # 已经为「是不是浏览任务页」读过一次 → 直接当 AFTER_DIRECT 用，省一次整页 OCR
        if pre_obs is not None:
            obs.extend(pre_obs)
        else:
            obs.extend(deps.screen.post_tap_observations())          # AFTER_DIRECT

    if _obs_count(obs) is None:
        # G5：进度行读不到，可能是浮层盖着——清浮层（认到关闭词才点）再读（旧 L1353-1358）
        popup_point = _locate_on_screen(deps, notes, "popup")
        if popup_point is not None:
            _tap_point(deps, popup_point, "进度行读不到，先点掉浮层再读", notes)
        obs.extend(deps.screen.post_tap_observations(VerifyStage.AFTER_POPUP))
    return tuple(obs)


def _obs_count(obs: tuple[VerifyObservation, ...]) -> int | None:
    """已收观察里是否已有进度数字（任一阶段）；没有则 None。"""
    for o in obs:
        if o.after_count is not None:
            return o.after_count
    return None


def _locate_on_screen(deps: RunDeps, notes: list, key: str) -> tuple[int, int] | None:
    """给 verify 阶梯用：当前帧上认某目标（bag 胶囊 / popup 关闭词）。

    ScreenPort 可实现 locate_target(key)->(x,y)|None；没实现就跳过这一路
    （绝不盲点——10-11 的 rc=5 就是盲点坐标惹的）。
    """
    locate = getattr(deps.screen, "locate_target", None)
    if locate is None:
        return None
    try:
        return locate(key)
    except Exception as exc:
        notes.append(f"落点认 {key} 失败（跳过这一路）：{exc}")
        return None


def _stage_back(deps: RunDeps, notes: list, reason: str) -> None:
    try:
        intent = ActionIntent(
            action_id=f"{deps.run_id}-back-{deps.now_ns()}",
            run_id=deps.run_id, kind=ActionKind.BACK,
            source_capture_id="verify", state_epoch=getattr(deps.device, "state_epoch", 0),
            geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
            reason=reason, source_candidate_id="verify-back", target_key="verify",
            expected_package="com.xunmeng.pinduoduo", required_window_kind=WindowKind.APP)
        deps.device.execute(intent, None)
    except Exception as exc:
        notes.append(f"BACK 被拒（继续核实）：{exc}")


def _tap_point(deps: RunDeps, point: tuple[int, int], reason: str, notes: list) -> None:
    try:
        intent = ActionIntent(
            action_id=f"{deps.run_id}-tap-{deps.now_ns()}",
            run_id=deps.run_id, kind=ActionKind.TAP,
            source_capture_id="verify", state_epoch=getattr(deps.device, "state_epoch", 0),
            geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
            reason=reason, source_candidate_id="verify-tap", target_key="verify",
            expected_package="com.xunmeng.pinduoduo", required_window_kind=WindowKind.APP)
        receipt = deps.device.execute(intent, point)
        # 成功/拒绝都留痕（真机查因需要「这一枪到底打没打成」）
        notes.append(f"{reason}（{point}，{receipt.status.value}）")
    except Exception as exc:
        notes.append(f"点 {point} 被拒（继续核实）：{exc}")


def _take_prize(deps: RunDeps, point: tuple[int, int], notes: list) -> None:
    """G3：奖励浮层在场 + 判定核给了 take 点 → 点「开心收下」收奖（旧 take_prize_overlay）。"""
    _tap_point(deps, point, "奖励浮层在场，点「开心收下」收下", notes)


def _browse_present(raw: str) -> bool:
    """这一帧是不是「浏览任务页」（旧脚本 text_present browse）。

    旧口径只看这一页有没有「浏览当前页面 / 即可点亮 / 滑动浏览」之一；
    没有就不滑——亮了但没跳到浏览任务页时，滑 15s 纯属白烧，还会把页面滚走。
    """
    return any(k in raw for k in ("浏览当前页面", "即可点亮", "滑动浏览"))


def _browse_after_light(deps: "RunDeps", notes: list) -> bool:
    """点亮后的浏览任务（生产 11-08 实测：点「立即点亮」后进入
    「滑动浏览当前页面10秒即可点亮」页面，必须滚动 10 秒才真正点亮）。

    手势按**屏幕比例**现算（用户口径 2026-11-08：不写死像素，跟随真实 tap 空间），
    数值来自旧脚本 browse_page 的比例口径（pdd.sh L1227-1252 / L81-95）：
    - x = 0.75 × tap_w（720 宽上是 540）；
    - 单次 y1 = 0.8 × tap_h → y2 = y1 − 半屏（不超过半屏，滑过头进度卡甩出屏幕）；
    - **按压 800ms**（这才是计入浏览时长的部分；300ms 无效——11-08 实测）；
    - 两次之间不留空档；按秒表滑满 15s（给 10s 计时留富余），保险丝 60 下。
    返回是否滑满时长。
    """
    from pddcheck.domain.errors import InvalidDomain
    sleep = getattr(deps, "browse_sleep", None) or time.sleep
    tw = int(getattr(deps.device, "tap_width", 0) or 720)
    th = int(getattr(deps.device, "tap_height", 0) or 1280)
    if tw <= 0 or th <= 0:
        tw, th = 720, 1280
    bx = int(tw * 0.75)
    y1 = int(th * 0.8)
    y2 = max(2, y1 - th // 2)          # 单次不超过半屏
    dur_ms = 800
    t0 = time.monotonic()
    ok = 0
    max_swipes = 60
    while time.monotonic() - t0 < 15.0 and ok < max_swipes:
        try:
            intent = ActionIntent(
                action_id=f"{deps.run_id}-browse-{ok}-{deps.now_ns()}",
                run_id=deps.run_id, kind=ActionKind.SWIPE,
                source_capture_id="cap", state_epoch=getattr(deps.device, "state_epoch", 0),
                geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
                reason=f"浏览任务滑动 {ok + 1}（比例 x=0.75 y=0.8→0.3 {dur_ms}ms）",
                source_candidate_id="browse-cand",
                target_key="browse",
                expected_package="com.xunmeng.pinduoduo",
                required_window_kind=WindowKind.APP)
            deps.device.execute(intent, (bx, y1, bx, y2, dur_ms))
            ok += 1
        except InvalidDomain as exc:
            notes.append(f"浏览段第 {ok + 1} 次滑动被拒：{exc}")
            break
    elapsed = round(time.monotonic() - t0, 1)
    notes.append(f"浏览任务段：{ok} 次滑动 / {elapsed}s（目标 ≥10s，比例口径 {tw}x{th}）")
    return elapsed >= 10.0


def _make_tap_intent(deps: RunDeps, facts: dict) -> ActionIntent:
    return ActionIntent(
        action_id=f"{deps.run_id}-light-{deps.now_ns()}",
        run_id=deps.run_id,
        kind=ActionKind.TAP,
        source_capture_id=facts.get("capture_id", "cap"),
        state_epoch=getattr(deps.device, "state_epoch", 0),
        geometry_revision=facts.get("geometry_revision", 0),
        deadline_ns=deps.now_ns() + 15_000_000_000,
        reason="点亮",
        source_candidate_id="light-cand",
        target_key="light",
        expected_package="com.xunmeng.pinduoduo",
        required_window_kind=WindowKind.APP,
        allow_coord=facts.get("tap_method") == "coord",
    )


def _stage_intent(deps: RunDeps, kind: ActionKind, reason: str) -> ActionIntent:
    """终态收尾动作（STOP/HOME 是生命周期动作：不带候选依据、不带业务坐标）。"""
    return ActionIntent(
        action_id=f"{deps.run_id}-{kind.value}-{deps.now_ns()}",
        run_id=deps.run_id, kind=kind, source_capture_id="terminal",
        state_epoch=getattr(deps.device, "state_epoch", 0), geometry_revision=0,
        deadline_ns=deps.now_ns() + 15_000_000_000, reason=reason)


def _read_last_activity(deps: RunDeps) -> str | None:
    """关 app 前读一次焦点 activity（pdd.sh L1622：按完 HOME 就只剩桌面了）。

    读不到不阻塞收尾（旧口径：`last_act=读不到` 也照发推送）。
    """
    try:
        fs = deps.device.focus()
    except Exception:
        return None
    return getattr(fs, "focused_activity", None) or None


def _apply_close_policy(deps: RunDeps, plan, notes: list) -> None:
    """下发 close_policy（迁移审计 G4：terminal_plan 早就算好却从未执行）。

    11-18 铁律（用户定）：不管成功与失败都关掉拼多多，**并确保关掉**——
    - STOP（force-stop）→ pidof 验证进程消失 → 没死再 stop 一次 → 还不行记 notes；
    - 收尾 HOME 回桌面（关不关得掉都回，别把桌面留在 PDD 上）；
    - close_policy 现恒为 STOP_AND_HOME；STAY/HOME_ONLY 枚举只剩兼容意义。
    单个动作失败只记 notes，不改业务 rc（终态收尾不影响判定，I11 同理）。
    """
    closed_ok = _force_close_verified(deps, notes, reason="收尾关 app")
    if closed_ok:
        notes.append("收尾：force-stop（pidof 验证进程已死）+ HOME")
    else:
        notes.append("收尾：force-stop 后进程仍存活——**没关掉**，下一轮会再关")
    try:
        deps.device.execute(_stage_intent(deps, ActionKind.HOME, "关 app 后回桌面"))
    except Exception as exc:                      # 收尾失败不污染业务结果
        notes.append(f"收尾 HOME 失败（忽略）：{exc}")


def _force_close_verified(deps: RunDeps, notes: list, *, reason: str,
                          tries: int = 2, wait_s: float = 1.5) -> bool:
    """force-stop + pidof 验证（11-18 铁律「确保关掉了」的核心）。

    返回 True=进程确认死亡；False=重试后仍在（或不肯回答）。设备不支持
    pid_of（FakeDevice/老适配器）时退化为「stop 动作被执行过」。
    """
    pid_of = getattr(deps.device, "pid_of", None)
    for attempt in range(1, tries + 1):
        try:
            deps.device.execute(_stage_intent(deps, ActionKind.STOP, f"{reason}（第 {attempt} 次）"))
        except Exception as exc:
            notes.append(f"{reason}：stop 被拒（{exc}）")
        if pid_of is None:
            return True                           # 无验证原语：按已执行处理
        try:
            alive = pid_of()
        except Exception as exc:
            notes.append(f"{reason}：pidof 验证失败（{exc}）")
            return False
        if alive is None:
            return True
        if attempt < tries:
            time.sleep(wait_s)                    # 给系统一点杀进程的时间再验
    return False


def _force_close_quiet(deps: RunDeps, notes: list, *, why: str) -> None:
    """早退路径的兜底关 app（不发通知、不改 rc；11-18 铁律覆盖早退）。

    dry-run / 未开终态效果 / 设备不支持 stop 时静默跳过。
    """
    if deps.dry_run or not getattr(deps, "execute_terminal_effects", False):
        return
    try:
        closed = ensure_app_closed(deps, notes)
        _evlog(deps, f"early_exit_close: {why} closed={closed}")
        notes.append(f"早退兜底：app {'已关闭' if closed else '关闭失败（进程仍在）'}")
    except Exception as exc:
        notes.append(f"早退兜底关 app 失败（忽略）：{exc}")


def ensure_app_closed(deps: RunDeps, notes: list, *, waits_s=None) -> bool:
    """关闭核验 + 兜底（收尾段之后的第二道闸）：pidof 还活着就再 stop 一轮。

    03:04 真机复盘（0.1.50）：force-stop 后 pidof 空、核验过，但 1~2s 后 PDD 的
    `:titan` 常驻子进程用排好的 wakeup alarm（ALARM_ACTION）把主进程**重新拉活**——
    收尾关进程与 alarm 触发存在竞态。

    11-20 复盘（本函数原来只等 3s 再验一次，漏了）：`PDD 主进程 STIME=00:11:16`
    在 close_verify=closed 之后仍活了 4 小时 → alarm 出手在 3s 窗口之外（≈+7s）。
    现在按 `close_waits_s` 走**两段观察窗**（默认 +3s、再 +6s，共 ~9s）：
    每段结束都验一次，活着就再杀一轮（`_force_close_verified`，内含 1.5s 重试）。
    仍活着才认输（推送喊话，app_closed=False）。

    返回 True=观察窗全过仍死；False=反复兜底后仍被拉活/读不到。
    """
    pid_of = getattr(deps.device, "pid_of", None)
    if pid_of is None:
        return True                               # 无验证原语：无可核验
    waits = waits_s if waits_s is not None else getattr(
        deps, "close_waits_s", ())
    for round_no, wait in enumerate(waits, 1):
        try:
            alive = pid_of()
        except Exception as exc:                  # noqa: BLE001 — 读失败=如实报没关成
            notes.append(f"关闭核验：pidof 读失败（{exc}）")
            return False
        if alive is not None:
            closed = _force_close_verified(
                deps, notes, reason=f"关闭核验第 {round_no} 轮兜底再关", tries=2)
            if not closed:
                return False
        time.sleep(max(0.0, float(wait)))         # 观察窗：给 titan alarm 出手机会
    try:
        alive = pid_of()
    except Exception as exc:                      # noqa: BLE001
        notes.append(f"关闭核验：pidof 读失败（{exc}）")
        return False
    if alive is None:
        return True
    # 观察窗全过又活了：最后一轮再杀一次，仍活就如实报 False（推送里会喊话）
    _force_close_verified(deps, notes, reason="关闭核验最终兜底再关", tries=2)
    try:
        return pid_of() is None
    except Exception:                             # noqa: BLE001
        return False


def _final_scroll(deps: RunDeps, notes: list) -> None:
    """成功后的最终 20 次下滑（I06；pdd.sh scroll_phase L1458-1467）。

    比例口径同旧脚本 SWIPE_* 常量：x=0.75×w、y1=0.9375×h → y2=0.546875×h、
    300ms 按压、20 次、次间隔 1s。与浏览段的 800ms/15s 是两件事，不合并。
    失败只记 notes，不改业务 rc（收尾动作，判定早已完成）。
    """
    sleep = getattr(deps, "browse_sleep", None) or time.sleep
    tw = int(getattr(deps.device, "tap_width", 0) or 720)
    th = int(getattr(deps.device, "tap_height", 0) or 1280)
    if tw <= 0 or th <= 0:
        tw, th = 720, 1280
    bx, y1 = int(tw * 0.75), int(th * 0.9375)
    y2 = int(th * 0.546875)
    ok = 0
    for i in range(20):
        try:
            intent = ActionIntent(
                action_id=f"{deps.run_id}-final-scroll-{i}-{deps.now_ns()}",
                run_id=deps.run_id, kind=ActionKind.SWIPE,
                source_capture_id="terminal", state_epoch=getattr(deps.device, "state_epoch", 0),
                geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
                reason=f"最终下滑 {i + 1}/20（x=0.75 {y1}→{y2} 300ms）",
                source_candidate_id="final-scroll", target_key="final_scroll",
                expected_package="com.xunmeng.pinduoduo", required_window_kind=WindowKind.APP)
            deps.device.execute(intent, (bx, y1, bx, y2, 300))
            ok += 1
        except Exception as exc:
            notes.append(f"最终下滑第 {i + 1} 次被拒（忽略）：{exc}")
            break
        sleep(1.0)
    notes.append(f"最终下滑：{ok}/20（I06）")
