# -*- coding: utf-8 -*-
"""app.py —— 完整调试版（纯 ctypes / tkinter）。

功能：
  * 枚举本机所有 HID 接口（VID/PID、usage、报告长度）
  * 读取 / 写入 Feature Report
  * 发送 Output Report
  * 监听 Input Report（后台线程，不阻塞界面）
  * 探测 Feature Report ID
  * 手动标定：Report ID + 字节下标 + 倍率 + 偏移，保存到 calibration.json

启动：python app.py
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import hid_win as hw
import window_behavior as wb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.path.join(BASE_DIR, "calibration.json")


def parse_hex(text: str) -> bytes:
    clean = "".join(ch for ch in text if ch not in " \t\r\n,;:-")
    if not clean:
        return b""
    if len(clean) % 2:
        raise ValueError("十六进制字符个数必须是偶数")
    return bytes.fromhex(clean)


class DebugApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("外设 HID 调试台")
        self.geometry("1220x780")
        self.minsize(1000, 680)
        self.configure(bg="#f4f5f8")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.items: list[hw.HidInterface] = []
        self._queue: queue.Queue = queue.Queue()
        self._monitor_stop = threading.Event()
        self._monitor_thread = None

        self.rid_var = tk.StringVar(value="0")
        self.len_var = tk.StringVar(value="64")
        self.mon_sec = tk.StringVar(value="3")
        self.cal_rid = tk.StringVar(value="0")
        self.cal_idx = tk.StringVar(value="5")
        self.cal_scale = tk.StringVar(value="1")
        self.cal_offset = tk.StringVar(value="0")

        self._build_ui()
        self.after(100, self._pump)
        self.after(200, self.refresh_devices)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=24, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

        top = tk.Frame(self, bg="#f4f5f8")
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="HID 调试台", bg="#f4f5f8", fg="#1f2333",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        self.count_label = tk.Label(top, text="", bg="#f4f5f8", fg="#7b8194",
                                    font=("Microsoft YaHei UI", 9))
        self.count_label.pack(side="left", padx=(12, 0), pady=(4, 0))
        tk.Button(top, text="刷新接口", command=self.refresh_devices,
                  relief="flat", bg="#4f8cff", fg="white", padx=14, pady=4,
                  font=("Microsoft YaHei UI", 9, "bold"),
                  cursor="hand2").pack(side="right")
        tk.Button(top, text="清空日志", command=self._clear_log,
                  relief="flat", bg="#e7e9f0", fg="#333", padx=12, pady=4,
                  font=("Microsoft YaHei UI", 9)).pack(side="right", padx=(0, 8))

        main = tk.PanedWindow(self, orient="horizontal", sashwidth=6,
                              bg="#d8dbe6", bd=0)
        main.pack(fill="both", expand=True, padx=12, pady=4)

        left = tk.Frame(main, bg="white")
        main.add(left, minsize=560, stretch="always")
        cols = ("product", "vidpid", "usage", "io", "path")
        self.tree = ttk.Treeview(left, columns=cols, show="headings",
                                 selectmode="browse")
        for col, text, width in (
                ("product", "产品", 170), ("vidpid", "VID:PID", 90),
                ("usage", "Usage", 110), ("io", "In/Out/Feat", 100),
                ("path", "设备路径", 420)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w", stretch=(col == "path"))
        ys = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = tk.Frame(main, bg="white")
        main.add(right, minsize=440, stretch="always")
        self.detail = tk.Label(right, text="选择一个 HID 接口", bg="#ffffff",
                               fg="#7b8194", font=("Microsoft YaHei UI", 9),
                               anchor="w", justify="left", wraplength=420)
        self.detail.pack(fill="x", padx=10, pady=(8, 4))
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True, padx=8, pady=6)
        self._tab_feature()
        self._tab_output()
        self._tab_probe()

        log_box = tk.Frame(self, bg="#f4f5f8")
        log_box.pack(fill="both", padx=12, pady=(2, 10))
        tk.Label(log_box, text="日志（仅界面显示，不写文件）", bg="#f4f5f8",
                 fg="#7b8194", font=("Microsoft YaHei UI", 8), anchor="w").pack(fill="x")
        self.log_text = tk.Text(log_box, height=9, bg="#10131a", fg="#d7dceb",
                                insertbackground="white", relief="flat",
                                font=("Consolas", 9), wrap="none")
        self.log_text.pack(fill="both", expand=True, pady=(2, 0))
        self.log_text.configure(state="disabled")

    def _tab_feature(self):
        tab = tk.Frame(self.nb, bg="white")
        self.nb.add(tab, text="Feature Report")
        row = tk.Frame(tab, bg="white")
        row.pack(fill="x", padx=10, pady=(12, 4))
        tk.Label(row, text="Report ID", bg="white", font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Spinbox(row, from_=0, to=255, width=5, textvariable=self.rid_var,
                   font=("Consolas", 10)).pack(side="left", padx=(6, 16))
        tk.Label(row, text="长度", bg="white", font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Spinbox(row, from_=0, to=4096, width=6, textvariable=self.len_var,
                   font=("Consolas", 10)).pack(side="left", padx=(6, 0))
        tk.Button(tab, text="读取 Feature Report", command=self._feature_read,
                  relief="flat", bg="#4f8cff", fg="white", padx=12, pady=4,
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=10, pady=6)
        tk.Label(tab, text="写入 Feature Report（十六进制负载，自动补零到报告长度）",
                 bg="white", fg="#7b8194", font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=10)
        self.feature_entry = tk.Text(tab, height=5, font=("Consolas", 10),
                                     bg="#f7f8fc", relief="flat")
        self.feature_entry.pack(fill="x", padx=10, pady=(2, 6))
        tk.Button(tab, text="写入 Feature Report", command=self._feature_write,
                  relief="flat", bg="#e7e9f0", fg="#222", padx=12, pady=4,
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=10, pady=(0, 10))

    def _tab_output(self):
        tab = tk.Frame(self.nb, bg="white")
        self.nb.add(tab, text="Output / Input")
        row = tk.Frame(tab, bg="white")
        row.pack(fill="x", padx=10, pady=(12, 4))
        tk.Label(row, text="Report ID", bg="white", font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Spinbox(row, from_=0, to=255, width=5, textvariable=self.rid_var,
                   font=("Consolas", 10)).pack(side="left", padx=(6, 16))
        tk.Label(row, text="负载（十六进制）", bg="white",
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.output_entry = tk.Text(tab, height=5, font=("Consolas", 10),
                                    bg="#f7f8fc", relief="flat")
        self.output_entry.pack(fill="x", padx=10, pady=(2, 6))
        btns = tk.Frame(tab, bg="white")
        btns.pack(fill="x", padx=10, pady=(0, 8))
        tk.Button(btns, text="发送 Output Report", command=self._output_send,
                  relief="flat", bg="#4f8cff", fg="white", padx=12, pady=4,
                  font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        tk.Label(btns, text="监听秒数", bg="white",
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(18, 4))
        tk.Spinbox(btns, from_=1, to=30, width=4, textvariable=self.mon_sec,
                   font=("Consolas", 10)).pack(side="left")
        tk.Button(btns, text="监听 Input", command=self._monitor_input,
                  relief="flat", bg="#e7e9f0", fg="#222", padx=10, pady=4,
                  font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 0))
        tk.Button(btns, text="停止", command=self._monitor_stop.set,
                  relief="flat", bg="#f3d6d6", fg="#a33", padx=10, pady=4,
                  font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(6, 0))

    def _tab_probe(self):
        tab = tk.Frame(self.nb, bg="white")
        self.nb.add(tab, text="探测 / 标定")
        tk.Button(tab, text="探测 Feature Report ID (0..15)", command=self._probe_ids,
                  relief="flat", bg="#4f8cff", fg="white", padx=12, pady=4,
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=10, pady=(12, 10))

        box = tk.LabelFrame(tab, text="手动标定（抓一帧 Input，取字节换算）", bg="white",
                            font=("Microsoft YaHei UI", 9), padx=8, pady=8)
        box.pack(fill="x", padx=10, pady=4)
        grid = tk.Frame(box, bg="white")
        grid.pack(fill="x")
        for i, (label, var) in enumerate((
                ("Report ID", self.cal_rid), ("字节下标", self.cal_idx),
                ("倍率", self.cal_scale), ("偏移", self.cal_offset))):
            tk.Label(grid, text=label, bg="white",
                     font=("Microsoft YaHei UI", 9)).grid(row=0, column=i * 2, sticky="w",
                                                          padx=(0, 4), pady=3)
            tk.Entry(grid, textvariable=var, width=7,
                     font=("Consolas", 10)).grid(row=0, column=i * 2 + 1, sticky="w",
                                                 padx=(0, 12), pady=3)
        tk.Button(box, text="抓一帧并解析", command=self._cal_capture,
                  relief="flat", bg="#e7e9f0", fg="#222", padx=10, pady=4,
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(6, 0))
        row = tk.Frame(box, bg="white")
        row.pack(fill="x", pady=(6, 0))
        tk.Button(row, text="保存标定 JSON", command=self._cal_save,
                  relief="flat", bg="#e7e9f0", fg="#222", padx=10, pady=3,
                  font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Button(row, text="加载标定 JSON", command=self._cal_load,
                  relief="flat", bg="#e7e9f0", fg="#222", padx=10, pady=3,
                  font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 0))
        tk.Label(box, text="保存位置：" + CAL_PATH, bg="white", fg="#9aa0b0",
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(6, 0))

    # ---------------------------------------------------------------- data
    def refresh_devices(self):
        self.count_label.configure(text="枚举中…")
        self.update_idletasks()
        try:
            items = hw.enumerate_hid()
        except Exception as exc:  # noqa: BLE001
            self._log(f"枚举失败：{exc}")
            return
        self.items = items
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(items):
            self.tree.insert("", "end", iid=str(i), values=(
                it.product or it.manufacturer or "HID 设备",
                f"{it.vid:04X}:{it.pid:04X}",
                f"0x{it.usage_page:04X}:0x{it.usage:04X}",
                f"{it.input_len}/{it.output_len}/{it.feature_len}",
                it.path))
        self.count_label.configure(text=f"{len(items)} 个接口")
        self._log(f"枚举完成：{len(items)} 个 HID 接口")

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.items[int(sel[0])]

    def _on_select(self, _event=None):
        it = self._selected()
        if not it:
            return
        self.detail.configure(
            text=f"{it.product or '(无产品名)'}  |  {it.vid:04X}:{it.pid:04X}  |  "
                 f"usage 0x{it.usage_page:04X}:0x{it.usage:04X}  |  "
                 f"in={it.input_len} out={it.output_len} feature={it.feature_len}\n{it.path}")
        if it.feature_len:
            self.len_var.set(str(it.feature_len))
        self.rid_var.set("0")

    # ------------------------------------------------------------- actions
    def _feature_read(self):
        it = self._selected()
        if not it:
            self._log("先选择一个接口")
            return
        try:
            rid = int(self.rid_var.get())
            length = int(self.len_var.get())
            dev = hw.HidDevice(it.path, write=False)
            try:
                data = dev.get_feature_report(rid, length)
            finally:
                dev.close()
            self._log(f"Feature IN id={rid} len={len(data)}: {data.hex(' ')}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"读取 Feature 失败：{exc}")

    def _feature_write(self):
        it = self._selected()
        if not it:
            self._log("先选择一个接口")
            return
        try:
            rid = int(self.rid_var.get())
            payload = parse_hex(self.feature_entry.get("1.0", "end"))
            dev = hw.HidDevice(it.path, write=True)
            try:
                caps = dev.caps
                total = caps.FeatureReportByteLength
                if total <= 0:
                    raise RuntimeError("该接口没有 Feature Report")
                buf = bytes([rid]) + payload
                buf = (buf + b"\x00" * total)[:total]
                dev.set_feature_report(buf)
            finally:
                dev.close()
            self._log(f"Feature OUT id={rid} len={len(buf)} 已发送")
        except Exception as exc:  # noqa: BLE001
            self._log(f"写入 Feature 失败：{exc}")

    def _output_send(self):
        it = self._selected()
        if not it:
            self._log("先选择一个接口")
            return
        try:
            rid = int(self.rid_var.get())
            payload = parse_hex(self.output_entry.get("1.0", "end"))
            dev = hw.HidDevice(it.path, write=True)
            try:
                caps = dev.caps
                total = caps.OutputReportByteLength
                if total <= 0:
                    raise RuntimeError("该接口没有 Output Report")
                buf = bytes([rid]) + payload
                buf = (buf + b"\x00" * total)[:total]
                dev.write_output(buf)
            finally:
                dev.close()
            self._log(f"Output OUT id={rid} len={len(buf)}: {buf.hex(' ')}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"发送 Output 失败：{exc}")

    def _monitor_input(self):
        it = self._selected()
        if not it:
            self._log("先选择一个接口")
            return
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._log("监听已在运行")
            return
        try:
            seconds = max(1, int(self.mon_sec.get()))
        except ValueError:
            seconds = 3
        self._monitor_stop.clear()
        path = it.path

        def worker():
            self._queue.put(f"开始监听 {seconds}s：{path}")
            try:
                dev = hw.HidDevice(path, write=False)
            except Exception as exc:  # noqa: BLE001
                self._queue.put(f"打开失败：{exc}")
                return
            try:
                end = time.monotonic() + seconds
                while time.monotonic() < end and not self._monitor_stop.is_set():
                    raw = dev.read_input(timeout_ms=100)
                    if raw:
                        self._queue.put(f"IN {raw.hex(' ')}")
            finally:
                dev.close()
                self._queue.put("监听结束")

        self._monitor_thread = threading.Thread(target=worker, daemon=True)
        self._monitor_thread.start()

    def _probe_ids(self):
        it = self._selected()
        if not it:
            self._log("先选择一个接口")
            return
        if not it.feature_len:
            self._log("该接口没有 Feature Report，无法探测")
            return
        path = it.path
        length = it.feature_len

        def worker():
            try:
                dev = hw.HidDevice(path, write=False)
            except Exception as exc:  # noqa: BLE001
                self._queue.put(f"打开失败：{exc}")
                return
            try:
                for rid in range(16):
                    try:
                        data = dev.get_feature_report(rid, length)
                        nz = any(data[1:])
                        self._queue.put(f"Feature id={rid:02d} 可读 len={len(data)}"
                                        f"{'（有数据）' if nz else ''}: {data.hex(' ')}")
                    except Exception:
                        pass
            finally:
                dev.close()
                self._queue.put("探测完成（只列出可读的 ID）")

        threading.Thread(target=worker, daemon=True).start()

    def _cal_capture(self):
        it = self._selected()
        if not it:
            self._log("先选择一个接口")
            return
        try:
            rid = int(self.cal_rid.get())
            idx = int(self.cal_idx.get())
            scale = float(self.cal_scale.get())
            offset = float(self.cal_offset.get())
        except ValueError:
            self._log("标定参数必须是数字")
            return
        try:
            dev = hw.HidDevice(it.path, write=False)
            try:
                raw = dev.read_input(timeout_ms=1500)
            finally:
                dev.close()
            if not raw:
                self._log("1.5 秒内没有收到 Input Report")
                return
            body = raw[1:] if (raw and raw[0] == rid and len(raw) > 1) else raw
            if idx >= len(body):
                self._log(f"字节下标 {idx} 超过报文长度 {len(body)}：{body.hex(' ')}")
                return
            value = body[idx]
            percent = round(value * scale + offset)
            self._log(f"Input {raw.hex(' ')} → body[{idx}]=0x{value:02X} "
                      f"→ {percent}%（倍率 {scale} 偏移 {offset}）")
        except Exception as exc:  # noqa: BLE001
            self._log(f"标定失败：{exc}")

    def _cal_save(self):
        data = {
            "report_id": int(self.cal_rid.get() or 0),
            "byte_index": int(self.cal_idx.get() or 0),
            "scale": float(self.cal_scale.get() or 1),
            "offset": float(self.cal_offset.get() or 0),
        }
        try:
            with open(CAL_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log(f"标定已保存：{CAL_PATH}")
        except OSError as exc:
            self._log(f"保存失败：{exc}")

    def _cal_load(self):
        try:
            with open(CAL_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001
            self._log(f"加载失败：{exc}")
            return
        self.cal_rid.set(str(data.get("report_id", 0)))
        self.cal_idx.set(str(data.get("byte_index", 0)))
        self.cal_scale.set(str(data.get("scale", 1)))
        self.cal_offset.set(str(data.get("offset", 0)))
        self._log(f"已加载标定：{data}")

    # ----------------------------------------------------------------- log
    def _log(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _pump(self):
        try:
            while True:
                self._log(self._queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._pump)


    def _on_close(self):
        wb.handle_close(self)


def main():
    app = DebugApp()
    app.mainloop()


if __name__ == "__main__":
    main()
