# -*- coding: utf-8 -*-
"""鼠标按键映射核心的单元测试（不装钩子、不真实点击）。"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import mouse_events as me
import mouse_remap as mr
import voice_typing as vt


def _cfg_with(button: str = "side1", action: dict | None = None,
              device: str = "3554:F517", enabled: bool = True) -> dict:
    action = action or {"type": "key", "keys": "ctrl+c"}
    return mr.normalize_config({
        "version": 1,
        "enabled": enabled,
        "devices": {
            device: {
                "name": "测试鼠标",
                "enabled": True,
                "bindings": {
                    button: {"button": button, "trigger": "press",
                             "action": action},
                },
            },
        },
    })


class TestDeviceKey(unittest.TestCase):
    def test_parse_vid_pid(self):
        name = (r"\\?\hid#vid_3554&pid_f517&mi_00"
                r"#7&1a2b3c&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}")
        self.assertEqual(mr.device_key_from_name(name), "3554:F517")

    def test_no_match(self):
        self.assertEqual(mr.device_key_from_name(""), "")
        self.assertEqual(mr.device_key_from_name(r"\Device\Foo"), "")

    def test_voice_device(self):
        self.assertTrue(mr.is_voice_device("248A:60AB"))
        self.assertTrue(mr.is_voice_device("248a:60ab"))
        self.assertFalse(mr.is_voice_device("3554:F517"))


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = mr.default_config()
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["devices"], {})

    def test_roundtrip(self):
        path = os.path.join(tempfile.gettempdir(), "mm_test_config.json")
        try:
            cfg = _cfg_with()
            self.assertTrue(mr.save_config(cfg, path))
            again = mr.load_config(path)
            self.assertTrue(again["enabled"])
            self.assertEqual(again["devices"]["3554:F517"]["bindings"]
                             ["side1"]["action"]["keys"], "ctrl+c")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_normalize_uppercases_and_drops_invalid(self):
        raw = {
            "enabled": True,
            "devices": {
                "3554:f517": {
                    "name": "X",
                    "bindings": {
                        "side1": {"button": "side1",
                                  "action": {"type": "key", "keys": "a"}},
                        "bogus": {"action": {"type": "key", "keys": "b"}},
                        "side2": {"action": "not-a-dict"},
                    },
                },
                "not-a-device": "bad",
            },
        }
        cfg = mr.normalize_config(raw)
        self.assertIn("3554:F517", cfg["devices"])
        bindings = cfg["devices"]["3554:F517"]["bindings"]
        self.assertIn("side1", bindings)
        self.assertNotIn("bogus", bindings)
        self.assertNotIn("not-a-device", cfg["devices"])

    def test_set_and_remove_binding(self):
        cfg = mr.default_config()
        cfg["enabled"] = True
        mr.set_binding(cfg, "3554:F517", "测试", "side1", "press",
                       {"type": "key", "keys": "ctrl+c"})
        self.assertEqual(mr.binding_at(cfg, "3554:F517", "side1")
                         ["action"]["type"], "key")
        self.assertTrue(mr.has_any_binding(cfg))
        self.assertTrue(mr.remove_binding(cfg, "3554:F517", "side1"))
        self.assertFalse(mr.has_any_binding(cfg))
        self.assertFalse(mr.remove_binding(cfg, "3554:F517", "side1"))

    def test_disabled_device_bindings_ignored(self):
        cfg = _cfg_with()
        cfg["devices"]["3554:F517"]["enabled"] = False
        self.assertIsNone(mr.binding_at(cfg, "3554:F517", "side1"))
        self.assertFalse(mr.has_any_binding(cfg))

    def test_voice_binding(self):
        cfg = mr.normalize_config({
            "enabled": True,
            "devices": {"248A:60AB": {
                "name": "魔声", "enabled": True,
                "bindings": {mr.VOICE_KEY: {
                    "button": mr.VOICE_KEY, "trigger": "hold",
                    "action": {"type": "voice_input", "mode": "input"},
                }},
            }},
        })
        found = mr.voice_binding(cfg)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], "248A:60AB")


class TestValidation(unittest.TestCase):
    def test_voice_only_on_voice_key_and_device(self):
        ok, _ = mr.validate_binding(
            "248A:60AB", mr.VOICE_KEY, "hold",
            {"type": "voice_input", "mode": "input"})
        self.assertTrue(ok)
        ok, error = mr.validate_binding(
            "3554:F517", mr.VOICE_KEY, "hold",
            {"type": "voice_input", "mode": "input"})
        self.assertFalse(ok)
        ok, error = mr.validate_binding(
            "248A:60AB", "side1", "press",
            {"type": "voice_input", "mode": "input"})
        self.assertFalse(ok)
        self.assertIn("语音键", error)

    def test_voice_key_only_voice_input(self):
        ok, error = mr.validate_binding(
            "248A:60AB", mr.VOICE_KEY, "hold",
            {"type": "key", "keys": "ctrl+c"})
        self.assertFalse(ok)
        self.assertIn("语音输入", error)

    def test_hold_only_voice_key(self):
        ok, error = mr.validate_binding(
            "3554:F517", "side1", "hold",
            {"type": "key", "keys": "ctrl+c"})
        self.assertFalse(ok)
        ok, error = mr.validate_binding(
            "248A:60AB", mr.VOICE_KEY, "press",
            {"type": "voice_input", "mode": "input"})
        self.assertFalse(ok)

    def test_mouse_action(self):
        self.assertTrue(mr.validate_action(
            {"type": "mouse", "function": "left_double"}, "3554:F517",
            "side1")[0])
        self.assertFalse(mr.validate_action(
            {"type": "mouse", "function": "nope"}, "3554:F517",
            "side1")[0])

    def test_key_action(self):
        self.assertTrue(mr.validate_action(
            {"type": "key", "keys": "ctrl+shift+esc"}, "3554:F517",
            "side1")[0])
        self.assertFalse(mr.validate_action(
            {"type": "key", "keys": "ctrl+"}, "3554:F517", "side1")[0])

    def test_app_action(self):
        self.assertFalse(mr.validate_action(
            {"type": "app", "path": ""}, "3554:F517", "side1")[0])
        self.assertTrue(mr.validate_action(
            {"type": "app", "path": r"C:\Windows\notepad.exe"},
            "3554:F517", "side1")[0])

    def test_combo_and_macro_steps(self):
        ok, _ = mr.validate_action(
            {"type": "combo", "steps": [
                {"kind": "key", "value": "ctrl+c"},
                {"kind": "mouse", "value": "left_click"},
                {"kind": "wait", "value": "100"}]}, "3554:F517", "side1")
        self.assertTrue(ok)
        ok, error = mr.validate_action(
            {"type": "combo", "steps": [{"kind": "text", "value": "x"}]},
            "3554:F517", "side1")
        self.assertFalse(ok)
        ok, error = mr.validate_action(
            {"type": "macro", "steps": [{"kind": "text", "value": "x"}]},
            "3554:F517", "side1")
        self.assertTrue(ok)
        ok, error = mr.validate_action(
            {"type": "macro", "steps": [{"kind": "wait", "value": "abc"}]},
            "3554:F517", "side1")
        self.assertFalse(ok)


class TestKeyCombo(unittest.TestCase):
    def test_modifiers(self):
        seq, error = mr.parse_key_combo("ctrl+shift+c")
        self.assertEqual(error, "")
        self.assertEqual(seq, [(0x11, False), (0x10, False), (0x43, False)])

    def test_single_keys(self):
        self.assertEqual(mr.parse_key_combo("f5")[0], [(0x74, False)])
        self.assertEqual(mr.parse_key_combo("f24")[0], [(0x87, False)])
        self.assertEqual(mr.parse_key_combo("a")[0], [(0x41, False)])
        self.assertEqual(mr.parse_key_combo("1")[0], [(0x31, False)])
        self.assertEqual(mr.parse_key_combo("space")[0], [(0x20, False)])

    def test_extended_and_right_modifier(self):
        seq, _ = mr.parse_key_combo("win+r")
        self.assertEqual(seq, [(0x5B, True), (0x52, False)])
        seq, _ = mr.parse_key_combo("rctrl+left")
        self.assertEqual(seq[0], (0xA3, True))
        self.assertEqual(seq[1], (0x25, True))

    def test_errors(self):
        for text in ("", "ctrl+", "ctrl+shift", "ctrl+nope",
                     "ctrl+c+d", "c+ctrl"):
            seq, error = mr.parse_key_combo(text)
            self.assertEqual(seq, [], text)
            self.assertTrue(error, text)

    def test_build_inputs_order_and_flags(self):
        inputs = mr.build_key_inputs("ctrl+shift+c")
        self.assertEqual(len(inputs), 6)
        self.assertEqual(inputs[0].u.ki.wVk, 0x11)
        self.assertEqual(inputs[1].u.ki.wVk, 0x10)
        self.assertEqual(inputs[2].u.ki.wVk, 0x43)
        self.assertEqual(inputs[3].u.ki.wVk, 0x43)
        self.assertEqual(inputs[3].u.ki.dwFlags & vt.KEYEVENTF_KEYUP,
                         vt.KEYEVENTF_KEYUP)
        self.assertEqual(inputs[5].u.ki.wVk, 0x11)

    def test_extended_flag(self):
        inputs = mr.build_key_inputs("win+r")
        self.assertTrue(inputs[0].u.ki.dwFlags
                        & mr.KEYEVENTF_EXTENDEDKEY)


class TestMouseFunctions(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(
            mr.action_summary({"type": "key", "keys": "ctrl+c"}),
            "按键 ctrl+c")
        self.assertEqual(
            mr.action_summary({"type": "mouse", "function": "left_double"}),
            "左键双击")
        self.assertEqual(
            mr.action_summary({"type": "combo", "steps": [{}, {}]}),
            "组合事件（2 步）")

    def test_unknown_function(self):
        ok, msg = mr.send_mouse_function("nope")
        self.assertFalse(ok)

    def test_action_has_mouse(self):
        self.assertTrue(mr.action_has_mouse(
            {"type": "mouse", "function": "left_click"}))
        self.assertTrue(mr.action_has_mouse(
            {"type": "macro", "steps": [{"kind": "mouse",
                                        "value": "left_click"}]}))
        self.assertFalse(mr.action_has_mouse(
            {"type": "combo", "steps": [{"kind": "key",
                                         "value": "ctrl+c"}]}))
        self.assertFalse(mr.action_has_mouse(
            {"type": "voice_input", "mode": "input"}))

    def test_click_inputs(self):
        with mock.patch.object(vt, "send_inputs", return_value=True) as send:
            ok, _ = mr.send_mouse_function("left_click")
        self.assertTrue(ok)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(send.call_args[0][0]), 2)

    def test_double_click_two_sends(self):
        with mock.patch.object(vt, "send_inputs", return_value=True) as send, \
                mock.patch.object(mr.time, "sleep"):
            ok, _ = mr.send_mouse_function("left_double")
        self.assertTrue(ok)
        self.assertEqual(send.call_count, 2)

    def test_long_press_sleeps(self):
        with mock.patch.object(vt, "send_inputs", return_value=True), \
                mock.patch.object(mr.time, "sleep") as sleep:
            ok, _ = mr.send_mouse_function("left_long")
        self.assertTrue(ok)
        sleep.assert_called_once_with(0.6)

    def test_wheel_data(self):
        with mock.patch.object(vt, "send_inputs", return_value=True) as send:
            ok, _ = mr.send_mouse_function("wheel_up")
        self.assertTrue(ok)
        item = send.call_args[0][0][0]
        self.assertEqual(item.u.mi.dwFlags, mr.MOUSEEVENTF_WHEEL)
        self.assertEqual((item.u.mi.mouseData >> 16) & 0xFFFF, 120)


class TestActionExecution(unittest.TestCase):
    def test_unknown(self):
        ok, _ = mr.execute_action({"type": "nope"})
        self.assertFalse(ok)

    def test_key(self):
        with mock.patch.object(mr, "send_key_combo",
                               return_value=(True, "ok")) as send:
            ok, msg = mr.execute_action({"type": "key", "keys": "ctrl+c"})
        self.assertTrue(ok)
        send.assert_called_once_with("ctrl+c")

    def test_steps_order_and_delay(self):
        calls = []

        def fake_key(value):
            calls.append(("key", value))
            return True, "ok"

        with mock.patch.object(mr, "send_key_combo", side_effect=fake_key), \
                mock.patch.object(mr, "send_mouse_function",
                                  return_value=(True, "ok")) as mouse, \
                mock.patch.object(mr.time, "sleep") as sleep:
            ok, _ = mr.execute_steps([
                {"kind": "key", "value": "ctrl+c", "delay_ms": 100},
                {"kind": "mouse", "value": "left_click", "delay_ms": 0},
            ])
        self.assertTrue(ok)
        self.assertEqual(calls, [("key", "ctrl+c")])
        mouse.assert_called_once_with("left_click")
        sleep.assert_called_once_with(0.1)

    def test_launch_app_empty(self):
        ok, _ = mr.launch_app("")
        self.assertFalse(ok)

    def test_launch_batch_uses_cmd(self):
        with mock.patch.object(mr.subprocess, "Popen") as popen:
            ok, _ = mr.launch_app(r"C:\tmp\run.bat", "a b")
        self.assertTrue(ok)
        argv = popen.call_args[0][0]
        self.assertEqual(argv[1:3], ["/c", r"C:\tmp\run.bat"])

    def test_launch_shortcut_uses_startfile(self):
        if not hasattr(os, "startfile"):
            self.skipTest("非 Windows")
        with mock.patch.object(os, "startfile") as startfile:
            ok, _ = mr.launch_app(r"C:\tmp\app.lnk", "--x")
        self.assertTrue(ok)
        startfile.assert_called_once_with(r"C:\tmp\app.lnk")


class TestSystemActions(unittest.TestCase):
    """系统动作：浏览器前进后退、媒体控制、音量、快捷键。"""

    def test_table_is_wellformed(self):
        ids = [key for key, _label, _spec in mr.SYSTEM_ACTIONS]
        self.assertEqual(len(ids), len(set(ids)), "动作 id 不能重复")
        for key, label, spec in mr.SYSTEM_ACTIONS:
            self.assertTrue(key, "id 不能为空")
            self.assertTrue(label, "%s 缺中文名" % key)
            self.assertIn(spec[0], ("vk", "combo", "call"),
                          "%s 的规格类型非法" % key)
            if spec[0] == "vk":
                self.assertTrue(0 < spec[1] <= 0xFF, "%s 虚拟键码越界" % key)
            elif spec[0] == "combo":
                seq, err = mr.parse_key_combo(spec[1])
                self.assertFalse(err, "%s 组合键无法解析：%s" % (key, err))
                self.assertTrue(seq, "%s 组合键为空" % key)

    def test_labels_and_summary(self):
        self.assertEqual(mr.system_action_label("browser_back"), "后退")
        self.assertEqual(mr.system_action_label("not_exists"), "not_exists")
        self.assertEqual(mr.system_action_label(""), "")
        self.assertEqual(
            mr.action_summary({"type": "system", "action": "media_next"}),
            "下一曲")
        self.assertEqual(mr.action_summary({"type": "system"}), "（未选择）")

    def test_validate(self):
        ok, err = mr.validate_action({"type": "system",
                                      "action": "browser_forward"})
        self.assertTrue(ok, err)
        ok, err = mr.validate_action({"type": "system", "action": "nope"})
        self.assertFalse(ok)
        self.assertIn("系统动作", err)
        ok, _ = mr.validate_action({"type": "system"})
        self.assertFalse(ok)

    def test_voice_key_rejects_system_action(self):
        ok, err = mr.validate_action({"type": "system",
                                      "action": "volume_up"},
                                     "248A:60AB", mr.VOICE_KEY)
        self.assertFalse(ok)
        self.assertIn("语音键", err)

    def test_extended_key_has_flag(self):
        """媒体/浏览器/音量键必须带 KEYEVENTF_EXTENDEDKEY，否则收不到。"""
        with mock.patch.object(mr.vt, "send_inputs",
                               return_value=True) as send:
            ok, msg = mr.send_system_action("browser_back")
        self.assertTrue(ok)
        self.assertIn("后退", msg)
        inputs = send.call_args[0][0]
        self.assertEqual(len(inputs), 2)            # down + up
        self.assertEqual(inputs[0].u.ki.wVk, 0xA6)
        self.assertTrue(inputs[0].u.ki.dwFlags
                        & mr.KEYEVENTF_EXTENDEDKEY)
        self.assertTrue(inputs[1].u.ki.dwFlags & vt.KEYEVENTF_KEYUP)
        self.assertTrue(inputs[1].u.ki.dwFlags
                        & mr.KEYEVENTF_EXTENDEDKEY)

    def test_media_action_uses_vk(self):
        with mock.patch.object(mr.vt, "send_inputs",
                               return_value=True) as send:
            ok, _ = mr.send_system_action("media_play_pause")
        self.assertTrue(ok)
        self.assertEqual(send.call_args[0][0][0].u.ki.wVk, 0xB3)

    def test_combo_action_reuses_send_key_combo(self):
        with mock.patch.object(mr, "send_key_combo",
                               return_value=(True, "已发送按键 ctrl+c")) as send:
            ok, msg = mr.send_system_action("copy")
        self.assertTrue(ok)
        send.assert_called_once_with("ctrl+c")
        self.assertEqual(msg, "已发送按键 ctrl+c")

    def test_combo_failure_names_the_action(self):
        with mock.patch.object(mr, "send_key_combo",
                               return_value=(False, "SendInput 被拒绝")):
            ok, msg = mr.send_system_action("paste")
        self.assertFalse(ok)
        self.assertIn("粘贴", msg)

    def test_lock_screen_calls_win32(self):
        with mock.patch.object(mr.ctypes, "windll", create=True) as windll:
            windll.user32.LockWorkStation.return_value = 1
            ok, msg = mr.send_system_action("lock_screen")
        self.assertTrue(ok)
        self.assertIn("锁定", msg)
        windll.user32.LockWorkStation.assert_called_once()

    def test_lock_screen_failure(self):
        with mock.patch.object(mr.ctypes, "windll", create=True) as windll:
            windll.user32.LockWorkStation.return_value = 0
            ok, _ = mr.send_system_action("lock_screen")
        self.assertFalse(ok)

    def test_unknown_action(self):
        ok, msg = mr.send_system_action("nope")
        self.assertFalse(ok)
        self.assertIn("未知", msg)

    def test_execute_action_routes_system(self):
        with mock.patch.object(mr, "send_system_action",
                               return_value=(True, "已发送前进")):
            ok, msg = mr.execute_action({"type": "system",
                                         "action": "browser_forward"})
        self.assertTrue(ok)
        self.assertEqual(msg, "已发送前进")

    def test_sendinput_rejected(self):
        with mock.patch.object(mr.vt, "send_inputs", return_value=False):
            ok, msg = mr.send_system_action("volume_up")
        self.assertFalse(ok)
        self.assertIn("SendInput", msg)


class TestHookParsing(unittest.TestCase):
    def test_buttons(self):
        self.assertEqual(mr._parse_hook_message(mr.WM_LBUTTONDOWN, 0),
                         ("left", "down"))
        self.assertEqual(mr._parse_hook_message(mr.WM_RBUTTONUP, 0),
                         ("right", "up"))
        self.assertEqual(mr._parse_hook_message(mr.WM_MBUTTONDOWN, 0),
                         ("middle", "down"))
        self.assertEqual(
            mr._parse_hook_message(mr.WM_XBUTTONDOWN, 1 << 16),
            ("side1", "down"))
        self.assertEqual(
            mr._parse_hook_message(mr.WM_XBUTTONUP, 2 << 16),
            ("side2", "up"))
        self.assertIsNone(mr._parse_hook_message(0x9999, 0))

    def test_wheel_direction(self):
        self.assertEqual(
            mr._parse_hook_message(mr.WM_MOUSEWHEEL, (120 & 0xFFFF) << 16),
            ("wheel_up", "down"))
        self.assertEqual(
            mr._parse_hook_message(mr.WM_MOUSEWHEEL,
                                   ((-120) & 0xFFFF) << 16),
            ("wheel_down", "down"))


class TestRawEventBuffer(unittest.TestCase):
    def test_match_and_consume(self):
        buffer = mr.RawEventBuffer()
        now = mr._now()
        buffer.push(10, "side1", "down", now)
        event = buffer.wait_match("side1", "down", now, timeout=0.01)
        self.assertIsNotNone(event)
        self.assertEqual(event.handle, 10)
        self.assertIsNone(buffer.wait_match("side1", "down", now,
                                            timeout=0.01))

    def test_no_match_returns_none(self):
        buffer = mr.RawEventBuffer()
        now = mr._now()
        self.assertIsNone(buffer.wait_match("left", "down", now,
                                            timeout=0.01))

    def test_wait_wakes_on_push(self):
        buffer = mr.RawEventBuffer()
        now = mr._now()

        def push_later():
            time.sleep(0.01)
            buffer.push(11, "side2", "down")

        thread = mock.Mock()
        import threading
        thread = threading.Thread(target=push_later)
        thread.start()
        event = buffer.wait_match("side2", "down", now, timeout=0.2)
        thread.join()
        self.assertIsNotNone(event)


class TestRawEventFilter(unittest.TestCase):
    def test_injected_handle_zero_ignored(self):
        engine = mr.RemapEngine(mr.default_config())
        engine._on_raw_event({"type": "button", "handle": 0,
                              "button": "left", "action": "down"})
        self.assertIsNone(engine._rawbuf.wait_match(
            "left", "down", mr._now(), timeout=0.01))

    def test_horizontal_wheel_ignored(self):
        engine = mr.RemapEngine(mr.default_config())
        engine._on_raw_event({"type": "wheel", "handle": 10, "delta": 120,
                              "horizontal": True})
        self.assertIsNone(engine._rawbuf.wait_match(
            "wheel_up", "down", mr._now(), timeout=0.01))


class TestDecision(unittest.TestCase):
    def _engine(self, cfg, mice=None, handles=None):
        engine = mr.RemapEngine(cfg)
        engine._snapshot = engine._build_snapshot()
        engine._mice = mice if mice is not None else [
            {"key": "3554:F517", "label": "X"}]
        engine._handle_keys = handles or {10: "3554:F517"}
        engine._runner = mock.Mock()
        return engine

    def test_no_binding_passes(self):
        engine = self._engine(_cfg_with(enabled=False))
        self.assertFalse(engine._decide("side1", "down", mr._now()))

    def test_matching_device_is_swallowed(self):
        engine = self._engine(_cfg_with())
        raw = mr.RawEvent(mr._now(), 10, "side1", "down")
        with mock.patch.object(engine._rawbuf, "wait_match",
                               return_value=raw):
            swallowed = engine._decide("side1", "down", mr._now())
        self.assertTrue(swallowed)
        engine._runner.submit.assert_called_once()
        self.assertIn("side1", engine._suppressed)
        self.assertTrue(engine._decide("side1", "up", mr._now()))
        self.assertNotIn("side1", engine._suppressed)

    def test_other_device_passes(self):
        cfg = _cfg_with()
        cfg["devices"]["046D:C53F"] = {
            "name": "另一只", "enabled": True, "bindings": {}}
        engine = self._engine(
            cfg, mice=[{"key": "3554:F517"}, {"key": "046D:C53F"}],
            handles={10: "046D:C53F"})
        raw = mr.RawEvent(mr._now(), 10, "side1", "down")
        with mock.patch.object(engine._rawbuf, "wait_match",
                               return_value=raw):
            self.assertFalse(engine._decide("side1", "down", mr._now()))
        engine._runner.submit.assert_not_called()

    def test_single_mouse_fallback(self):
        engine = self._engine(_cfg_with())
        with mock.patch.object(engine._rawbuf, "wait_match",
                               return_value=None):
            self.assertTrue(engine._decide("side1", "down", mr._now()))
        engine._runner.submit.assert_called_once()

    def test_multi_mouse_no_raw_is_conservative(self):
        engine = self._engine(
            _cfg_with(),
            mice=[{"key": "3554:F517"}, {"key": "046D:C53F"}])
        with mock.patch.object(engine._rawbuf, "wait_match",
                               return_value=None):
            self.assertFalse(engine._decide("side1", "down", mr._now()))
        engine._runner.submit.assert_not_called()

    def test_wheel_has_no_up_state(self):
        engine = self._engine(
            _cfg_with("wheel_up",
                      {"type": "mouse", "function": "wheel_down"}))
        raw = mr.RawEvent(mr._now(), 10, "wheel_up", "down")
        with mock.patch.object(engine._rawbuf, "wait_match",
                               return_value=raw):
            self.assertTrue(engine._decide("wheel_up", "down", mr._now()))
        self.assertNotIn("wheel_up", engine._suppressed)


class TestStatusFiles(unittest.TestCase):
    def test_write_read(self):
        path = os.path.join(tempfile.gettempdir(), "mm_status_test.json")
        try:
            mr.write_status({"running": True, "pid": 123}, path)
            self.assertEqual(mr.read_status(path)["pid"], 123)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_daemon_pid_dead(self):
        with mock.patch.object(mr, "read_status",
                               return_value={"pid": 999999}), \
                mock.patch.object(mr.tc, "pid_alive", return_value=False):
            self.assertEqual(mr.daemon_pid(), 0)

    def test_daemon_pid_rejects_unrelated_image(self):
        with mock.patch.object(mr, "read_status",
                               return_value={"pid": 123}), \
                mock.patch.object(mr.tc, "pid_alive", return_value=True), \
                mock.patch.object(mr.tc, "process_image",
                                  return_value=r"C:\x\evil.exe"):
            self.assertEqual(mr.daemon_pid(), 0)

    def test_daemon_pid_accepts_python(self):
        with mock.patch.object(mr, "read_status",
                               return_value={"pid": 123}), \
                mock.patch.object(mr.tc, "pid_alive", return_value=True), \
                mock.patch.object(mr.tc, "process_image",
                                  return_value=r"C:\Python\pythonw.exe"):
            self.assertEqual(mr.daemon_pid(), 123)


if __name__ == "__main__":
    unittest.main()
