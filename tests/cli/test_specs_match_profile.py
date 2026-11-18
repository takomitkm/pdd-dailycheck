"""生产 spec 与 profile.toml 的一致性护栏。

2026-11-18 的事故就是这里漂移：生产硬编码的 subsidy 别名写成
("百亿补贴", "搜索补贴")，漏了老脚本的「官方补贴」→ 入口文字路永远不命中 → rc4。
这条测试钉住 **别名 / overlap / region** 三项必须与 profile 同值；
坐标是真机标定值，允许生产覆盖（不在此断言）。
"""

from pathlib import Path

from pddcheck.cli.app import _default_specs
from pddcheck.config.profile import load_profile

PROFILE = (Path(__file__).resolve().parents[2]
           / "profiles" / "pdd" / "v1" / "profile.toml")


def test_specs_match_profile_alias_overlap_region():
    prof = load_profile(PROFILE)
    specs = _default_specs()
    assert set(specs) >= {"subsidy", "bag", "light", "popup", "take"}
    for key, spec in specs.items():
        target = prof.target(key)
        assert tuple(spec.labels) == tuple(target.alias), f"{key} alias 漂移"
        assert spec.min_overlap == target.overlap, f"{key} overlap 漂移"
        assert spec.region == target.region, f"{key} region 漂移"
