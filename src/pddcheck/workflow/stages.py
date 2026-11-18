"""流程段（T11 扩展）：就绪 → 入口(subsidy) → 福袋(bag)，为完整签到补上点亮前的两段。

设计：逻辑与设备解耦——StageRunner 只依赖两个注入：
  read_page() -> PageView        观察一页（焦点包/activity/OCR 文本）
  act(kind, point) -> receipt    执行一个受护栏的动作（start/tap/back）
动作的真实护栏在 AdbDevice（前台校验）里；这里的每一发 tap 都带 expected_package，
不会对错页发动作（intent 校验兜底）。

失败用 StageFailure(rc) 表达：入口连续进不去 → rc4；福袋/证明失败 → rc5；
与 acceptance §5 的 4/5 语义一致。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from pddcheck.perception import TargetLocateSpec, locate_all
from pddcheck.perception.facts import facts_from_text
from pddcheck.perception.pagekind import PageKind, classify_page


class StageFailure(Exception):
    def __init__(self, rc: int, why: str) -> None:
        super().__init__(why)
        self.rc = rc
        self.why = why


@dataclass(frozen=True, slots=True)
class PageView:
    focus_package: str | None
    focus_activity: str | None
    ocr_text: str
    # 生产路径附带的真实帧（FrameObservation：逐词 TSV + 几何，locate_all 直接收）；
    # 测试老路径为 None。定位必须走真帧——合成单行假框（_Page）的词框是整页文本
    # 拼出来的，拿它产点击点会点到假框中心（2026-11-17 排查：入口假命中点 (200,20)）。
    frame: object | None = None


class StagePolicy:
    def __init__(self, *, pkg: str, home_activity: str, entry_retry: int = 2,
                 prove_max: int = 3, min_conf: int = 40,
                 allow_coord_fallback: bool = True,
                 step_wait_s: float = 4.0, sleep=None,
                 restart_app: bool = True, focus_retry: int = 3,
                 focus_retry_wait_s: float = 1.0) -> None:
        self.pkg = pkg
        self.home_activity = home_activity
        self.entry_retry = entry_retry
        self.prove_max = prove_max
        self.min_conf = min_conf
        # 坐标兜底（旧脚本同款）：入口是图片、字认不到时用标定坐标。
        # 兜底只允许在**主线**（不在恢复链路）用——旧脚本的 I04/I05 口径。
        self.allow_coord_fallback = allow_coord_fallback
        # 点击后等页面跳转（旧脚本 STEP_WAIT=4）——真机实测：不等就判「没进去」
        self.step_wait_s = step_wait_s
        # G6（迁移审计）：RESTART_APP——**启动前** force-stop（旧脚本 launch_app
        # L1423「避免停在旧页面」）。只在「焦点确实是别的应用」时执行：
        # 焦点读不到时绝不 stop（无法排除 PDD 就在前台，am start 幂等、force-stop 不可逆）；
        # 焦点已在 PDD 内时不 stop（11-09 定案：任何 PDD 页都可续跑）。
        self.restart_app = restart_app
        # G7（迁移审计）：FOCUS_RETRY——焦点读不到重试几次再判定（旧脚本 L694-698，
        # 躲过渡动画那一瞬；真读不到 = 不点，重试只为读清）。
        self.focus_retry = focus_retry
        self.focus_retry_wait_s = focus_retry_wait_s
        self._sleep = sleep or (lambda s: __import__("time").sleep(s))

    def wait_step(self) -> None:
        if self.step_wait_s > 0:
            self._sleep(self.step_wait_s)


class StageRunner:
    def __init__(self, read_page, act, policy: StagePolicy) -> None:
        self._read = read_page
        self._act = act
        self.policy = policy

    # ---- 弹窗：清掉挡页面的推广弹窗（用户 11-08 现场指引） ---------------
    def dismiss_popup(self, popup_spec: TargetLocateSpec | None = None,
                      max_rounds: int = 3) -> int:
        """清掉屏幕中间的推广弹窗（「邀请好友抽福袋」这类带「邀请/抽」的）。

        用户口径（2026-11-08 现场）：弹窗在屏幕中间，文本带「邀请」或「抽」。
        处理顺序：
        1. 认到 popup 关闭词（关闭/跳过广告/暂不/以后再说）→ 点它（最安全）；
        2. 认不到关闭词但**整页文本命中弹窗特征**（邀请+抽 同时出现、且页型不是
           activity）→ 点弹窗外缘（右上角惯例位）一次；
        3. 每一轮后重读页面，文本特征消失/页型变了即停。
        返回清除轮数（0=没弹窗）。不做为失败路径：清不掉也只记 notes，由后续段
        按页面事实自然失败（不盲点）。
        """
        closed = 0
        for _ in range(max_rounds):
            v = self._read()
            if v.focus_package != self.policy.pkg:
                break
            # 1) 有关闭词：优先点关闭词（无真帧时 _locate 返回 None，不点假框）
            point = self._locate(v, "popup",
                                 {"popup": popup_spec} if popup_spec is not None else {})
            if point is not None:
                self._act("tap", point)
                self.policy.wait_step()
                closed += 1
                continue
            # 2) 弹窗特征（邀请/抽 同时出现）且不在活动页 → 点右上角惯例关闭位
            text = v.ocr_text
            if ("邀请" in text and "抽" in text) and \
                    classify_page(text) is not PageKind.ACTIVITY:
                # 惯例关闭位：弹窗右上角外缘（点空间 720×1280 的 (614, 385) 一带，
                # 真机多枚弹窗的 × 都落在这一带；非精确标定，命中不了就算了）
                self._act("tap", (614, 385))
                self.policy.wait_step()
                closed += 1
                continue
            break                                   # 没有弹窗特征 → 结束
        return closed

    # ---- 就绪：唤醒/启动到 PDD -----------------------------------------
    def ensure_ready(self, *, back_to_home: int = 2, launch_wait_s: float = 30.0) -> None:
        """把手机带到 PDD（确定性起点）。

        真机教训（T18a 连跑）：残留页会让入口判定漂移 → 先回到首页。
        生产教训：
        1. 11-08：停在点亮活动页时 BACK 只会退到频道页 → rc7 误伤；活动页可直接续跑。
        2. 11-08：PDD 冷启动 >4s，start 后必须轮询等焦点。
        3. 11-09 10:00 过夜锁屏：wake/dismiss/start 三连发无间隔，dismiss 在屏幕
           未亮时被吞、am start 被锁屏拦 → rc7。改旧脚本同款节拍（各等 1s），
           轮询期间重发 dismiss+start（幂等：am start 只把已有 task 带前台）。
        4. 11-09：classify_page 会把活动/浏览页误判成 home（共有「精选/热卖推荐」，
           且横幅 OCR 读不出）→ 不能靠它决定 rc7。**只要焦点是 PDD 就当可续跑**：
           入口/福袋/点亮段都按当前页自行处理；rc7 只留给「焦点真的不是 PDD」。
        """
        # G7：焦点读不到时先重试（躲过渡动画；真读不到 = 不点，重试只为读清）。
        v = self._read()
        for _ in range(max(0, self.policy.focus_retry - 1)):
            if v.focus_package is not None:
                break
            self.policy._sleep(self.policy.focus_retry_wait_s)
            v = self._read()
        if v.focus_package == self.policy.pkg and \
                (v.focus_activity or "").endswith(("HomeActivity", "MainFrameActivity")):
            return                                     # 已在首页（旧 is_home_page 两个组件名都认）
        # 11-10 真机教训：PDD 任务栈会恢复到**陈旧店铺/促销页**（NewPageActivity），
        # 「任何 PDD 页可续跑」会让入口/福袋在错页上跑（entry 假 ok → bag rc5）。
        # 冷启动组件名修好后（T59），改为旧脚本 RESTART_APP 口径：**不在首页就
        # force-stop 再干净拉起**，保证确定性首页起点。force-stop 对陈旧页是 intended。
        if self.policy.restart_app:
            self._act("stop", None)
            self.policy._sleep(1.0)
        self._act("wake", None)
        self.policy._sleep(1.0)
        self._act("dismiss_keyguard", None)
        self.policy._sleep(1.0)
        self._act("start", None)
        deadline = time.monotonic() + launch_wait_s
        launched = False
        n = 0
        while time.monotonic() < deadline:
            self.policy._sleep(2.0)
            v = self._read()
            if v.focus_package == self.policy.pkg:
                launched = True
                break
            n += 1
            if n % 2 == 0:
                # 锁屏可能还没解：重发生命周期（wake/dismiss/start 均幂等，非业务动作）
                self._act("dismiss_keyguard", None)
                self.policy._sleep(1.0)
                self._act("start", None)
        if not launched:
            raise StageFailure(7, f"launch 后焦点不是 PDD（{v.focus_package}）")

    # ---- 入口：回到/进入补贴活动页 --------------------------------------
    def scroll_to_top(self, swipes: int = 3) -> None:
        """滑回页面顶部（旧脚本 TOP_RETRY_KEY 的做法）。坐标按 720×1280 点空间的默认比例。"""
        for _ in range(swipes):
            self._act("swipe", (360, 300, 360, 1000))
        self.policy.wait_step()

    def enter_subsidy(self, spec: TargetLocateSpec, *, scroll_to_top=None,
                      swipes: int = 3, anchor_points=None) -> None:
        """进补贴活动页。

        scroll_to_top：可选回调（滚回页面顶部再认一轮）——旧脚本的做法是
        「认不到字多半页面没在顶端 → 滑到最顶端再认一次」（旧 L1074-1078）。
        没提供该回调时不滚动（纯文本判定环境用）。

        anchor_points：可选供给器 ()->list[(x,y)]，返回**锚点推算**的入口候选
        （11-13 加固：首页「百亿补贴」是艺术字，OCR 读不稳 → 改用可读的图标行文字
        「限时秒杀/充值中心/免费领礼物」+ 偏移推算）。每个候选点下去后用落地校验
        （认到「抽福袋/搜低价/精选+奢品馆」）裁决；点错就 BACK 再试下一个。
        供给器返回空列表 = 没有可信锚点 → 不点（绝不盲点）。
        """
        attempts = self.policy.entry_retry + 1
        for attempt in range(attempts):
            v = self._read()
            if _entered_channel(v, self.policy):
                return                                     # 已在补贴频道
            # **文字定位时禁用坐标兜底**（11-13）：否则 locate_all 会直接给一个
            # CONFIG_COORD 候选当 winner，锚点/坐标分支就永远轮不到。
            # 优先级在这里显式排：文字 → 锚点 → 标定坐标。
            # 定位走**真帧**（生产 read_page 附带）；无真帧（测试老路径）时
            # 合成帧只许判定、产不出坐标 → text_point=None（11-17 假框教训）。
            text_spec = (spec if not spec.allow_coord
                         else replace(spec, allow_coord=False))
            text_point = self._locate(v, spec.key, {spec.key: text_spec})
            tapped = False
            anchors = list(anchor_points()) if anchor_points is not None else []
            anchors = [c for c in anchors if c]
            if text_point is not None:
                self._act("tap", text_point)
                self.policy.wait_step()                   # 等页面跳转（真机实测必需）
                v2 = self._read()
                if _entered_channel(v2, self.policy):
                    return
                # 点错了 → 退掉，让下一轮在干净页面重来（pdd.sh 同款：点错就 BACK）
                self._act("back", None)
                self.policy._sleep(1.0)
                tapped = True
            elif anchors:
                # 锚点推算（11-13 加固，优先于固定坐标）：认到可读图标行文字 →
                # 推算百亿补贴图标位置。每个候选靠落地校验裁决；点错立即 BACK
                # 退掉再试下一个（pdd.sh 的精神：点错就退，不拿盲点冒充成功）。
                for cand in anchors:
                    self._act("tap", (cand[0], cand[1]))
                    self.policy.wait_step()
                    v2 = self._read()
                    if _in_subsidy_channel(v2.ocr_text):
                        return
                    self._act("back", None)               # 点错了 → 退回首页再试下一个
                    self.policy._sleep(1.0)
                tapped = True
            elif spec.coord is not None and self.policy.allow_coord_fallback:
                # 认不到字、又没有锚点 → 退标定坐标点一次（旧脚本同款：入口是图片，
                # 字未必认得到）。护栏：AdbDevice 会校验前台是 pdd，否则拒绝动作。
                pt = (int(spec.coord[0] * 720), int(spec.coord[1] * 1280))
                self._act("tap", pt)
                self.policy.wait_step()                   # 等跳转（真机实测：不等等于没点）
                v2 = self._read()
                if _entered_channel(v2, self.policy):
                    return
                self._act("back", None)                   # 点错了 → 退掉再试
                self.policy._sleep(1.0)
                tapped = True
            if attempt < attempts - 1:
                if scroll_to_top is not None and attempt == 0 and not tapped:
                    scroll_to_top(swipes)               # 滑到顶再认一轮
                elif not tapped:
                    self._act("back", None)                # 退掉遮罩/错页再试
        raise StageFailure(4, "入口连着点还是没进补贴活动页")

    def _locate(self, v: PageView, key: str,
                specs: dict) -> tuple[int, int] | None:
        """页面文本定位一个目标 → 点击点；认不到 → None。

        定位必须来自**真帧**（PageView.frame = FrameObservation，逐词 TSV + 几何）
        ——词框是真字形框，点击点是命中 span 的词框并集中心。没有真帧（测试老路径）
        时合成帧的「词框」是整页文本拼出来的假框，中心坐标毫无意义 → 一律返回 None
        （宁可少一路文字定位，绝不点假框中心；2026-11-17 入口假命中 (200,20)）。
        """
        frame = v.frame
        if frame is None or not specs:
            return None
        res = locate_all(frame, specs, min_conf=self.policy.min_conf)
        r = res[key]
        if r.winning is not None and r.winning.tap_point is not None:
            return r.winning.tap_point
        return None

    # ---- 福袋：点进福袋页并证明（进度/待兑换/已点亮 任一） ---------------
    def open_bag(self, spec: TargetLocateSpec, *, extra_candidates=None) -> None:
        """extra_candidates：可选供给器 ()->tuple[Candidate,...]，返回裁片通道
        （pill/band）的候选——真机实测：频道页「抽福袋」整页认不出，只有 pill 档认得出。

        注意（真机踩过）：一旦提供 extra_candidates，就**禁用整页坐标兜底**——
        bag 的 COORD 是活动页那颗的位置，在频道页盲点它会点到别处。
        """
        for attempt in range(self.policy.prove_max):
            v = self._read()
            # 已在点亮活动页（生产 11-08 补签踩到：手机停在活动页、当天福袋已抽）
            # → open_bag 的目标已达成，直接通过（点亮段在当前页续跑）。
            if classify_page(v.ocr_text) is PageKind.ACTIVITY:
                return
            point = None
            # 顺序：裁片通道优先（真机实测频道页只有 pill 认得出；整页会把零散单字
            # 误配成「抽福袋」→ 点错地方），整页仅在无裁片供给器时使用。
            if extra_candidates is not None:
                for cand in extra_candidates():
                    if cand.key == spec.key and cand.tap_point is not None:
                        point = cand.tap_point
                        break
            if point is None:
                # 整页兜底也走真帧；合成帧产不出坐标（见 enter_subsidy 注释）
                point = self._locate(v, spec.key, {spec.key: spec})
            if point is not None:
                self._act("tap", point)
                self.policy.wait_step()
                v2 = self._read()
                f = facts_from_text(v2.ocr_text)
                # 判据是**页面文字**（旧脚本口径）：进度行 / 待兑换 / 已点亮 任一即证明。
                # 不要求 activity 变化——活动页与频道页常常是同一个 NewPageActivity。
                if f.progress_count is not None or f.pend_text or f.done_text:
                    return                                 # 进对了福袋页
                # 点完还证明不了：**不再盲目 BACK**（真机踩过：BACK 把已进的活动页退回
                # 频道页，形成 点→退→点 的死循环）。只重新观察一轮。
                continue
            if attempt < self.policy.prove_max - 1:
                self._act("back", None)                    # 轮播另一帧，退一步换一帧
        raise StageFailure(5, "福袋页进不去/证明失败")


# 频道特征字（任一命中即算进对页）。11-18 真机实测：频道页顶部横幅读得出
# 「百亿加倍补」「百亿消费券」，页签读得出「精选」；而「奢品馆」被 psm6 读成
# 「Ages IK ga」、「抽福袋」整页一档也读不出——旧判据要求「精选 AND 奢品馆」，
# 会把**正确落地**判成错页（入口点对了也 BACK 出去，三连 rc4）。
_CHANNEL_MARKERS = ("抽福袋", "搜低价", "精选", "奢品馆", "百亿加倍补",
                    "百亿消费券", "天天折扣", "极速达")


def _in_subsidy_channel(text: str) -> bool:
    """落地页是不是「百亿补贴」频道（11-10 加固，11-18 放宽为任一特征字）。"""
    return any(m in text for m in _CHANNEL_MARKERS)


def _entered_channel(v: "PageView", policy: "StagePolicy") -> bool:
    """点完入口之后：这一发到底有没有进对页。

    判据两层（老脚本是第二层，11-10 起加了第一层）：
    1. 页面上认到任一频道特征字 → 进对了；
    2. 否则退回**老脚本口径**：焦点还在 PDD 且已不在首页（MainFrame/Home 之外）
       就算进——`_in_subsidy_channel` 是加固，不是唯一判据。11-18 实测：
       正确落地那页的「奢品馆/抽福袋」都读不出来，只靠第 1 层会自己把正确页
       判成错页、连退三次报 rc4。第 2 层有 11-10 说过的误报面（买菜/店铺也是
       NewPageActivity），但那是老流程一直在用的口径，误报止于下一段 bag 失败，
       不会误点/误报成功。
    """
    if _in_subsidy_channel(v.ocr_text):
        return True
    act = v.focus_activity or ""
    if v.focus_package != policy.pkg or not act:
        return False
    return not act.endswith(("HomeActivity", "MainFrameActivity"))


class _Page:
    """把一段 OCR 文本包成 ParsedFrame 视图——**只许页型/文字判定，不许产坐标**。

    纯文本 → 合成一行 level=5 的 TSV 词行（框是整页文本拼的假框）。生产定位
    必须走 PageView.frame（真帧）；本类只给「这段文本里有没有 X」一类判定用。
    假框中心当点击点的教训见 StageRunner._locate（2026-11-17）。
    """

    def __init__(self, ocr_text: str) -> None:
        self.text = ocr_text

    def frame(self, frame_id: str):
        from pddcheck.domain import CoordinateSource
        from pddcheck.perception.observe import FrameObservation
        tsv = ("5\t1\t1\t1\t1\t1\t0\t0\t400\t40\t92\t"
               + self.text.replace("\t", " ").replace("\n", " ") + "\n")
        return FrameObservation(frame_id, "cap", 1, 720, 1280, xml_text=None,
                                ocr_texts={CoordinateSource.TESSERACT_PAGE: tsv})
