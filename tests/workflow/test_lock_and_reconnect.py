"""2026-11-19 迁移补齐：设备掉线重连（旧 ensure_device，rc2）与锁屏 rc3。

两个都是旧 pdd.sh 一直在用、重构版漏掉的闸：
- 掉线：4 轮 `adb connect` + `get-state`，全失败才 rc2 并推一条「PDD ❌ 设备掉线」；
- 锁屏：wake + dismiss-keyguard 之后焦点仍是 keyguard → rc3，一个业务动作都不放。
"""

import pytest

from pddcheck.device.adb import AdbDevice, AdbError, Completed
from pddcheck.workflow.stages import PageView, StageFailure, StagePolicy, StageRunner

PKG = "com.xunmeng.pinduoduo"
HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
SERIAL = "1.2.3.4:5555"


def _fake_adb(script):
    calls = []

    def run(argv, timeout_s):
        calls.append(list(argv[1:]))
        sub = argv[3] if len(argv) > 3 else ""
        return script(sub)

    return run, calls


def test_connect_retries_with_explicit_adb_connect():
    states = ["offline", "device"]

    def script(sub):
        if sub == "connect":
            return Completed(0, b"connected", b"")
        if sub == "get-state":
            st = states.pop(0) if states else "device"
            return Completed(0, st.encode(), b"")
        return Completed(0, b"", b"")

    run, calls = _fake_adb(script)
    dev = AdbDevice(SERIAL, runner=run)
    assert dev.connect(retries=3, retry_wait_s=0) == "device"
    assert ["-s", SERIAL, "connect", SERIAL] in calls


def test_connect_gives_up_with_last_error():
    def script(sub):
        if sub == "get-state":
            return Completed(0, b"offline", b"")
        return Completed(0, b"", b"")

    run, _ = _fake_adb(script)
    dev = AdbDevice(SERIAL, runner=run)
    with pytest.raises(AdbError) as exc:
        dev.connect(retries=2, retry_wait_s=0)
    assert exc.value.code == "offline"


def test_missing_adb_binary_becomes_adb_error(monkeypatch):
    """adb 不在 PATH：FileNotFoundError 收敛成 Completed(127) → AdbError（不崩栈）。"""
    from pddcheck.device import adb as adb_mod

    def boom(*a, **k):
        raise FileNotFoundError("adb")

    monkeypatch.setattr(adb_mod.subprocess, "run", boom)
    dev = AdbDevice(SERIAL)
    with pytest.raises(AdbError) as exc:
        dev.connect()
    assert exc.value.code == "adb_failed"


def test_locked_keyguard_aborts_rc3():
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    seq = [PageView("com.android.systemui", "com.android.systemui.keyguard.Keyguard",
                    "锁屏")]

    class Actor:
        def __init__(self):
            self.calls = []

        def __call__(self, kind, point=None):
            self.calls.append(kind)
            return Completed(0, b"", b"")

    actor = Actor()
    r = StageRunner(lambda: seq[0], actor, pol, focus_kind=lambda: "keyguard")
    with pytest.raises(StageFailure) as exc:
        r.ensure_ready()
    assert exc.value.rc == 3
    assert "tap" not in actor.calls          # 锁屏时一个业务动作都不放