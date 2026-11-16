"""弹窗清除段（用户 2026-11-08 现场口径）：屏幕中间「邀请/抽」推广弹窗挡页面。

2026-11-17 语义修订（T63）：关闭词定位走真帧（PageView.frame）；无真帧时文字路
不出点 → 只有「邀请+抽」惯例位那一路（坐标是常量、不依赖 OCR 框）还能点。
"""

from __future__ import annotations

from pddcheck.domain import CoordinateSource
from pddcheck.perception import TargetLocateSpec
from pddcheck.perception.observe import FrameObservation
from pddcheck.workflow.stages import PageView, StagePolicy, StageRunner

PKG = "com.xunmeng.pinduoduo"
HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
ACT = "com.xunmeng.pinduoduo.activity.NewPageActivity"

POPUP_SPEC = TargetLocateSpec(key="popup", labels=("关闭", "暂不", "以后再说"),
                              min_overlap=2)


def frame_with(words: list[tuple[int, int, str]]) -> FrameObservation:
    rows = "".join(
        f"5\t1\t{i}\t1\t{i}\t1\t{x}\t{y}\t60\t20\t92\t{t}\n"
        for i, (x, y, t) in enumerate(words, start=1))
    return FrameObservation("t", "cap", 1, 720, 1280, xml_text=None,
                            ocr_texts={CoordinateSource.TESSERACT_PAGE: rows},
                            geometries={CoordinateSource.TESSERACT_PAGE: (1.0, 1.0, 0.0, 0.0)})


class Actor:
    def __init__(self):
        self.calls = []

    def __call__(self, kind, point):
        self.calls.append((kind, point))
        return None


def runner(pages):
    seq = list(pages)
    act = Actor()

    def _act(kind, point):
        return act(kind, point)

    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0)
    return StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[-1], _act, pol), act


def test_no_popup_text_means_zero_rounds():
    r, act = runner([PageView(PKG, HOME, "推荐 食品 女装 限时秒杀")])
    assert r.dismiss_popup(POPUP_SPEC) == 0
    assert act.calls == []


def test_close_word_tapped():
    """认到「暂不」（真帧词框）→ 点它，且点后弹窗特征消失即停（1 轮）。"""
    r, act = runner([PageView(PKG, ACT, "邀请好友抽福袋 暂不 9天内点亮4次必得",
                              frame=frame_with([(300, 500, "暂不")])),
                     PageView(PKG, ACT, "9天内点亮4次必得 今日已点亮")])
    n = r.dismiss_popup(POPUP_SPEC)
    assert n == 1
    assert act.calls and act.calls[0][0] == "tap"
    assert act.calls[0][1] == (330, 510)          # 词框中心，不是假框中心


def test_close_word_without_frame_never_taps():
    """无真帧：关闭词「命中」不出点（假框中心不可信）→ 不点关闭词这一路。"""
    r, act = runner([PageView(PKG, ACT, "邀请好友抽福袋 暂不 9天内点亮4次必得"),
                     PageView(PKG, ACT, "9天内点亮4次必得 今日已点亮")])
    n = r.dismiss_popup(POPUP_SPEC)
    assert n == 0                                 # 也没有「邀请+抽」惯例位（在活动页）
    assert act.calls == []


def test_invite_feature_without_close_word_taps_corner():
    """无关闭词但「邀请+抽」同现、非活动页 → 点右上角惯例关闭位。"""
    r, act = runner([PageView(PKG, HOME, "邀请好友抽福袋 立即邀请 推荐食品女装"),
                     PageView(PKG, HOME, "推荐 食品 女装 限时秒杀")])
    n = r.dismiss_popup(None)
    assert n == 1
    assert act.calls[0] == ("tap", (614, 385))


def test_popup_on_activity_page_not_touched():
    """活动页上出现「抽」字是正常文案（去抽奖/抽福袋）→ 不当弹窗。"""
    r, act = runner([PageView(PKG, ACT, "邀请好友抽福袋 去抽奖 9天内再点亮5次必得")])
    assert r.dismiss_popup(None) == 0
    assert act.calls == []


def test_max_rounds_cap():
    """弹窗反复出现 → 最多 max_rounds 轮，不死循环（关闭词走真帧）。"""
    pages = [PageView(PKG, ACT, "邀请好友抽福袋 暂不",
                      frame=frame_with([(300, 500, "暂不")]))] * 9
    r, act = runner(pages)
    n = r.dismiss_popup(POPUP_SPEC, max_rounds=3)
    assert n == 3
    assert len([c for c in act.calls if c[0] == "tap"]) == 3
