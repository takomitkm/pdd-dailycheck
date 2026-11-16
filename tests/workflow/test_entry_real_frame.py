"""T63（2026-11-17）：入口文字定位必须走真帧；合成假框绝不产坐标。

2026-11-17 排查实锤：stages 用 _Page 把整页 OCR 文本拼成单行假词框做文字定位，
「百亿补贴」可读的日子里假命中 → 点假框中心 (200,20)（屏幕顶端状态栏）→ 必 rc4。
修复后：
- PageView.frame（真帧）存在 → 文字定位用它（词框是真字形框）；
- PageView.frame 缺失（测试老路径）→ 文字定位产不出点 → 直接走锚点/坐标分支。
"""

from __future__ import annotations

from pddcheck.domain import CoordinateSource
from pddcheck.perception import TargetLocateSpec
from pddcheck.perception.observe import FrameObservation
from pddcheck.workflow.stages import PageView, StagePolicy, StageRunner

PKG = "com.xunmeng.pinduoduo"
HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
ACT = "com.xunmeng.pinduoduo.activity.NewPageActivity"

SUBSIDY = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                           coord=(0.125, 0.46875))


def _real_frame(words: list[tuple[int, int, str]]) -> FrameObservation:
    """把 (x, y, text) 词表转成一张真帧（TSV 逐词、真实坐标，geometry (1,1,0,0)）。"""
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


def _runner(seq):
    pages = list(seq)

    def read():
        return pages.pop(0) if len(pages) > 1 else pages[0]
    return StageRunner(read, Actor(), StagePolicy(
        pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
        step_wait_s=0, sleep=lambda s: None)), pages


def test_text_locate_uses_real_frame_word_box():
    """有真帧：文字命中 → 点击点是**命中词框**的中心（不是整页假框中心）。"""
    # 「百亿补贴」真实词框 (30,610) 起（11-16 真机 XML 实测 30,610..114,634）；
    # 本帧词框 60×20 → 中心 (60,620)，与假框中心 (200,20) 完全不同。
    frame = _real_frame([(30, 610, "百亿补贴"), (178, 313, "充值中心")])
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    seq = [PageView(PKG, HOME, "充值中心 百亿补贴", frame=frame),
           PageView(PKG, ACT, "抽福袋")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    r.enter_subsidy(SUBSIDY)
    assert r._act.calls == [("tap", (60, 620))]


def test_text_locate_without_frame_never_taps_fake_box():
    """无真帧（老测试路径）：文字「命中」也不点——假框中心不可信，落坐标兜底。"""
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    seq = [PageView(PKG, HOME, "百亿补贴 搜索补贴"),      # 文字可读但无 frame
           PageView(PKG, ACT, "抽福袋")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    r.enter_subsidy(SUBSIDY)
    # 没有锚点供给器 → 直接落标定坐标 (90,600)，绝不点合成假框中心 (200,20)
    assert r._act.calls == [("tap", (90, 600))]


def test_entry_no_text_no_anchor_no_coord_never_taps():
    """无真帧、无锚点、无坐标 → 一个点都不放（原有不变量，修复后仍成立）。"""
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=None, allow_coord=False)
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    seq = [PageView(PKG, HOME, "限时秒杀 免费领礼物")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    try:
        r.enter_subsidy(spec, anchor_points=lambda: [])
        raised = False
    except Exception:
        raised = True
    assert raised and r._act.calls == []


def test_open_bag_without_frame_falls_to_pill_only():
    """open_bag 无真帧时整页文字定位产不出点 → 只信裁片候选/直接退（不盲点）。"""
    from pddcheck.perception import TargetLocateSpec as S
    bag = S(key="bag", labels=("抽福袋",), min_overlap=3, coord=(0.13889, 0.69922))
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    seq = [PageView(PKG, ACT, "抽福袋 9天内点亮4次必得")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    # 整页文本里有「抽福袋」，但无真帧 → 文字路不出点；无裁片供给器 → 不点，
    # 直接靠「已在活动页」判定通过（classify_page ACTIVITY 短路）。
    r.open_bag(bag)
    assert r._act.calls == []


def test_open_bag_with_real_frame_taps_word_box():
    """open_bag 有真帧：文字命中 → 点词框中心。"""
    from pddcheck.perception import TargetLocateSpec as S
    bag = S(key="bag", labels=("抽福袋",), min_overlap=3, coord=(0.13889, 0.69922))
    frame = _real_frame([(435, 524, "抽福袋")])
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    seq = [PageView(PKG, ACT, "消费券页 抽福袋入口", frame=frame),  # 第一帧：非活动页
           PageView(PKG, ACT, "9天内点亮4次必得")]           # 点完证明成功
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    r.open_bag(bag)
    assert ("tap", (465, 534)) in r._act.calls              # 词框中心 (435+30, 524+10)