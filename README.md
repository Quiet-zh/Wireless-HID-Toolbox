# Wireless HID Toolbox（2.4G 外设工具箱）

Windows 10/11 的 2.4G 无线外设电量与 HID 调试工具箱。纯 Python 标准库 +
`ctypes` + `tkinter`，**零第三方依赖**。

- **电量**：迈从 EWEADN 8K 鼠标（`3554:F517`）、PMO WAVE75 键盘（`36B0:3002/3009`）
- **三种形态**：双设备电量面板、双数字托盘、完整 HID 调试台
- **鼠标测试**：Raw Input 按键 / 移动 / 滚轮 / 坐标 / 点击统计
- **多厂商协议**：ATK/MCHOSE/罗技/杰理/Endgame/VAXEE/Nordic 等 20+ 设备表
- **系统集成**：开机自启、桌面软连接、上次电量缓存、休眠显示「上次更新」
- **调试**：Feature/Output/Input、探测 Report ID、手动标定

> 协议参考 [`2.4G-battery-viewer`](../2.4G-battery-viewer) 的方法论，
> 针对这两台设备重新逆向并用真机回包验证。设备不在支持列表里的请勿直接套用。

![电量面板](docs/panel.png)

## 已验证的读数（真机抓包）

| 项目 | 值 |
|---|---|
| 设备 | `EWEADN 8K`，`3554:F517`，厂商字符串 `Compx` |
| 协议接口 | HID 顶层集合 `usage page 0xFF02 / usage 0x0002`，`col05` |
| 报告 | Input / Output 均 17 字节（Report ID `0x08` + 16 字节报文） |
| 查询电量 | 发送命令 `0x04` |
| 真机回包 | `08 04 00 00 00 02 5A 00 0F D1 ... 0D` |
| 解析结果 | 电量 90%（设备自报）/ 电压 4049 mV / 未充电 |

按 E-HUB 同款电压曲线换算后，该回包显示 **87%**（UI 优先用电压算电量）。

键盘（PMO HUB 官方固件）：`AA 30` 回包 `aa 30 ... 55 42 ...`，即 **66% / 未充电**；
2.4G dongle 与 USB 有线两种连接都验证过。

## 快速开始

要求：Windows 10/11 + Python 3.10+（官方安装包自带 `tkinter`）。

```bat
:: 两台设备一次读（验收标准 1）
python my_devices.py --once

:: 鼠标 / 键盘分别读
python eweadn_battery.py --once
python keyboard_battery.py --once

:: 输出 JSON
python my_devices.py --json

:: 每 30 秒刷新
python my_devices.py --watch 30

:: 打开双设备电量面板
python battery_panel.py

:: 托盘常驻（两个数字图标）
python tray_app.py
python tray_app.py --status
python tray_app.py --quit

:: 完整调试版
python app.py

:: 多厂商协议扫描（ATK/MCHOSE/罗技/杰理/Endgame/VAXEE/Nordic...）
python generic_scan.py
python generic_scan.py --list
python my_devices.py --scan

:: 列 HID / 一键安装开机自启+桌面链接 / 只开面板
python my_devices.py --list
python my_devices.py --install
python my_devices.py --panel
```

配置保存在 `%APPDATA%\ExtBatteryTray\config.json`；上次电量缓存在同目录
`last_<设备>.json`（设备休眠时用于显示“上次更新 HH:MM”）。

也可以直接双击 `启动面板.cmd`（无控制台窗口）或 `读取电量.cmd`。

命令行输出示例：

```text
EWEADN 8K: 电量 85%（4.040 V，未充电）
PMO WAVE75: 电量 61%（未充电，2.4G）
```

## 电量面板

- 两张卡片：左鼠标（EWEADN 8K）、右键盘（PMO WAVE75），同时显示
- 大号百分比 + 进度条，颜色随电量变化（≥60 绿 / 30–59 黄 / <30 红）
- 鼠标卡片：电压、充电状态、设备自报电量；键盘卡片：连接方式、充电状态、协议
- 设备休眠时显示**上次电量 + 上次更新时间**（灰色），不会直接变成 `--`
- CLI 也一样：`my_devices.py --once` 在休眠时打印 `电量 84%（上次更新 01:36，休眠）`
- 「扫描全部」按钮：后台调用多厂商协议库，弹窗列出所有命中的设备
- 自动刷新（30 秒 / 60 秒 / 2 分钟 / 5 分钟 / 10 分钟 / 30 分钟），可手动刷新
- 「最小化」按钮：缩到任务栏，托盘右键可恢复；读取在后台线程，界面不卡

## 托盘常驻

```bat
python tray_app.py              :: 静默驻留（开机自启跑的就是它）
python tray_app.py --debug      :: 前台运行并打印过程
python tray_app.py --status     :: 查看配置 / 自启 / 是否在运行
python tray_app.py --quit       :: 让正在运行的托盘退出
```

- 通知区域两个图标：**EWEADN 8K**、**PMO WAVE75**，图标里就是电量数字
- 颜色：绿 ≥60 / 黄 30–59 / 红 <30；灰色数字 = 设备休眠，正在显示上次缓存
- 左键图标 → 立刻刷新一次
- 右键图标 → 打开/前置电量面板（已开则不重复开）
- 悬停 tooltip：`设备名：电量%（HH:MM:SS 更新）`；
  休眠时是 `设备名：电量%（上次更新 HH:MM）`
- 低 CPU：`SetTimer` 驱动，默认 60 秒；读取在后台线程
- 退出：面板里的「退出托盘」，或 `python tray_app.py --quit`；
  `WM_DESTROY` 里 `PostQuitMessage`，不留僵尸进程

## 多厂商协议扫描

```bat
python generic_scan.py              :: 扫描并读一次
python generic_scan.py --list       :: 只列 VID:PID 命中的协议
python generic_scan.py --protocols  :: 列出内置协议表
python generic_scan.py --json
python generic_scan.py --watch 60
python my_devices.py --scan         :: 同一个入口
```

面板里点「扫描全部」也会在后台跑一遍，结果弹窗显示。

已接入的协议（只读查询）：

| 协议 / 方案 | 识别方式 | 电量位置 | 状态 |
|---|---|---|---|
| ATK / VXE / VGN 协议 1 | `0xFF02`，17B，Report `0x08` | `[6]`，`0x55` 校验 | 公开协议移植 |
| ATK / VXE 协议 2 | `0xFF05`，64B，Report `0x08` | `[7]`，`[1]=0x72/[5]=0x07` | 公开协议移植 |
| Dareu A950 / VXE / Imecoo | 同 ATK 1 | `[6]` | 设备表 |
| MCHOSE V9 Turbo / Turbo+ | `0xFF90`，64B，`55 65 01` | `[2]`，状态 `[3]` | 公开协议移植 |
| ATK N9V2 耳机 | `0xFF90`，64B，`55 65 01` | `[2]`，状态 `[3]` | 公开协议移植 |
| MCHOSE A5 / AX5 | VID `0x2023`，Feature 65，MI_02 | `[8]`，充电 `[7]`，cmd `0x83` | 公开协议移植 |
| MCHOSE A7 compatible | `5253:1021`，Feature `0x11`，整体 XOR | payload `[9]`，充电 `[10]` | 公开协议移植 |
| MCHOSE gmouse（G3/A7e/G7） | `0xFF01`，`55 30 A5 0B 2E` | 回复 `AA 30` 后 `+8` | 公开协议移植 |
| MCHOSE Z75S 键盘 | `258A:01BB`，20B，`0x13/0x4A` | `[5]`，前 19 字节和校验 | 公开协议移植 |
| XIBERIA T7 | `36F9:*`，`0xFF00`，64B | `[3]`，`55 65 00` | 公开协议移植 |
| Rapoo VT3S | `24AE:1411`，`0xFF00`，19B | 主动上报 `[8]`，状态 `[7]` | 公开协议移植 |
| Endgame Gear | VID `0x3367`，Feature `0xA1` | `[16]`，电压 `[17]` | 公开协议移植 |
| VAXEE / ZYGEN | VID `0x3057`，Feature `0x0E` | `[5] × 5%` | 公开协议移植 |
| Nordic nRF | VID `0x1915`，Feature `0x05` | `[9]` | 公开协议移植 |
| 罗技 HID++ 2.0 | VID `0x046D`，Feature `0x1004/0x1000/0x1001` | `[4]`，状态 `[5]/[6]` | 公开协议移植 |
| DARKRIM / 杰理 JL_RCSP | `3654:6901`，`0xFF02`，65B | TLV `0x01` 首字节 | 公开协议移植 |
| ZOWIE DW | `04A5:800A`，`0xFF03` 输出 + `0xFF04` 输入 | 电压插值曲线 | **实验**，双接口未在真机验证 |
| 标准 HID 电量 | Usage `0x06:0x20` / `0x0D:0x3B` / `0x85:0x65` | Feature 值 | 通用 |
| 抓包协议 | `captured.json` 的 requests + offset | 任意偏移 | 手动配置 |

> 只有 EWEADN 8K、PMO WAVE75 在本机实测；其他协议来自公开仓库/协议文档的移植，
> 建议先用 `generic_scan.py --list` 确认 VID:PID/usage，再用 `--scan` 验证。
> 只发送查询帧，不写设备配置；未知 opcode 不要盲目爆破。

### 抓包协议（可选）

如果某台设备不在表里，但抓到了「请求帧 + 电量字节」，可以手动写
`%APPDATA%\ExtBatteryTray\captured.json`：

```json
{
  "373B:1278": {
    "name": "ATK A9 Air",
    "requests": ["08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49"],
    "offset": 6,
    "invert": false
  }
}
```

`invert: true` 时取 `100 - 原值`。扫描时会自动尝试，不需要改代码。

## 完整调试版

```bat
python app.py
```

![调试台](docs/debug.png)

- 列出本机所有 HID 接口：产品名、VID:PID、usage、Input/Output/Feature 长度、设备路径
- 选中接口后可读 / 写 **Feature Report**、发 **Output Report**
- **监听 Input Report**（后台线程，不卡界面）
- **探测 Feature Report ID 0..15**
- **手动标定**：Report ID + 字节下标 + 倍率 + 偏移；抓一帧 Input 算出百分比，
  保存 / 加载 `calibration.json`
- 日志只显示在窗口里，不写文件

## 开机自启 / 桌面链接

面板底部：

- **开机自启** 勾选框：在「启动」文件夹创建 `电量托盘.lnk`，
  目标是 `pythonw.exe tray_app.py`，不弹黑窗。任务管理器 →「启动」里能看到
  「电量托盘」并启用/禁用；面板勾选状态读的是真实状态，不会自动改用户设置。
- **桌面链接** 按钮：在桌面创建指向项目目录的 **目录符号链接/junction**，
  以及指向 `启动面板.cmd` 的 **文件符号链接/硬链接**，不复制文件。
- **退出托盘**：通知托盘退出。

> 本会话里已创建：启动项 `电量托盘.lnk`（已启用）、桌面 `外设电量`（symlink）、
> 桌面 `启动面板.cmd`（symlink）。

## 命令行调试工具（debug_tool.py）

```bat
python debug_tool.py list          :: 列出本机 EWEADN 的所有 HID 接口
python debug_tool.py read          :: 读电量并打印原始收发报文
python debug_tool.py monitor 10    :: 监听 10 秒 Input Report
python debug_tool.py send 4        :: 发送原始命令 0x04
python debug_tool.py wake 15       :: 连续查询在线状态，确认鼠标是否醒着
```

## 协议细节

### 报文格式

请求（Output Report，Report ID `0x08`，共 17 字节）：

```
08 | cmd | 00 00 | len | payload[0..9] | 00 ... | checksum
```

- `cmd`：`0x03` 查询在线状态，`0x04` 查询电量
- `len`：payload 长度
- `checksum = (0x4D - sum(bytes[0..14])) & 0xFF`
  （等价于厂商代码里的 `0x55 - (ReportId + sum)`）

回复（Input Report，Report ID `0x08`）：

| 偏移 | 含义 |
|---|---|
| `[0]` | `0x08` Report ID（`ReadFile` 读出时带；WebHID 的 `data` 不带） |
| `[1]` | 命令字（与请求相同） |
| `[2]` | 状态：`0x00` 成功，`0x01` 不支持 / 失败 |
| `[5]` | 设备自报电量（0–100） |
| `[6]` | `1` = 正在充电 |
| `[7..8]` | 电池电压，大端，单位 mV |
| `[15]` | 校验和 |

### 电压 → 电量曲线

与 E-HUB 前端一致，按 mV 做 5% 一档的分段线性插值：

```
3050, 3420, 3480, 3540, 3600, 3660, 3720, 3760, 3800, 3840, 3880,
3920, 3940, 3960, 3980, 4000, 4020, 4040, 4060, 4080, 4110
```

`4049 mV → 87%`。设备同时会给一个自报百分比（`[5]`），电压为 0 时才用它兜底。

## 为什么和 E-HUB 显示差 1~3%？

同一时刻其实有三个口径：

| 口径 | 数值示例 | 来源 |
|---|---|---|
| 设备自报电量 | 90% | 电量回复 `[5]` 字节，设备自己的电量计 |
| 当前电压估算 | 87% | `4049 mV` 按厂商曲线即时换算 |
| E-HUB 卡片 | 89% | 官方显示层的「平滑 + 缓存」结果 |

E-HUB 的显示不是即时值：它的 `batteryHandleInit` 在 60 秒内会保持上次的显示值，
之后把变化限制在大约 `-0.014%/s ~ +0.028%/s`；另有 10 秒定时器每次最多降 1%。
设备休眠、或窗口缩到托盘导致定时器被节流时，它会继续停在旧值上。
所以 89% 通常是「之前更高、还没降下来」的显示值，87% 是当前电压的即时换算，
两者都不是硬件故障。设备自报的 90% 则是电量计的粗粒度结果。

本工具默认显示即时值（87%），面板里同时保留「设备自报 90%」作为参考。

> 实测验证：退出并重启 E-HUB 后，官方卡片显示的正是 **87%**，与本工具一致；
> 之前的 89% 是上一会话缓存 / 平滑后的旧值。

## 实现要点

1. **独立异步读句柄**：Windows 上同一 HID 句柄并发「阻塞 ReadFile + WriteFile」
   可能直接杀掉进程，所以读用一个单独的 `FILE_FLAG_OVERLAPPED` 句柄 + 事件超时。
2. **E-HUB 可以同时开着**：本工具只读状态，不写配置；实测与 E-HUB 同时访问
   `col05` 互不影响。两条通道都会收到 Input Report，按命令字过滤即可。
3. **鼠标休眠**：2.4G 鼠标静置几分钟后会休眠，dongle 仍能回 `0x03`，但 `[5] = 0`。
   此时动一下鼠标或按一下按键即可；工具会给出明确提示并自动重试。
4. **不写日志**：默认不产生任何日志文件，`--debug` 才打印原始报文。
5. **面板/托盘并发**：两个进程可能在同一秒刷新，键盘的 `AA 10/30/11` 是会话协议，
   用 `Local\ExtBatteryHidReadLock` 命名互斥体把整次读取串行化；实测两个进程
   各读 10 次，20/20 成功。
6. **上次电量**：每次成功读取写一份 `%APPDATA%\ExtBatteryTray\last_*.json`；
   休眠/超时时面板和托盘显示灰色上次电量 + 上次更新时间，而不是直接变 `--`。

## 鼠标测试面板（可视化）

```bat
python mouse_test_gui.py
python mouse_test_gui.py --demo    :: 自动生成演示事件，预览界面
```

![鼠标测试面板](docs/mouse_test.png)

- 左侧测试区域：移动时实时显示 `X/Y`，点击位置有波纹反馈，鼠标图会高亮按下的键
- 五个按键指示：左键 / 中键 / 右键 / 后退 / 前进，按下即变色
- 右侧滚轮计数、坐标面板（Client / Page / Screen / Offset / Movement）
- 点击统计：总点击、双击次数、每秒点击、双击判定延时（可调）、两次点击间隔、重置
- 键盘页签：显示按键名、VK、扫描码和最近按键；只显示，不记录、不落盘
- 鼠标事件只统计 EWEADN 设备；键盘页签为了方便测试，接收所有键盘

## 监控按键 / 移动（Raw Input）

```bat
python mouse_events.py --list              :: 列出 Raw Input 设备
python mouse_events.py --seconds 20        :: 只监视 EWEADN（默认）
python mouse_events.py --stats             :: 每秒打印速率
python mouse_events.py --all --seconds 5   :: 调试：显示所有鼠标/键盘
```

输出示例（真机）：

```text
[00:10:43.424] mouse   move  dx=+40 dy=-25  (1 包)
[00:10:44.433] mouse   left   down
[00:10:44.498] mouse   left   up
[00:10:46.336] mouse   wheel  up (+120)
[00:10:50.102] key     VolumeUp   down  (scan=0x30)
```

- 能监控：左 / 右 / 中键、侧键 1/2、滚轮、横滚、相对移动 `dx/dy`，
  以及设备键盘接口上出现的按键（多媒体键、DPI 键等如果走键盘 HID 就能看到）。
- 按 VID/PID 过滤，只接收这只 EWEADN 鼠标/接收器的事件；`--all` 才显示其它设备。
- 鼠标 / 键盘顶层集合被系统独占，不能直接 `ReadFile`；这里用 Windows Raw Input
  （`WM_INPUT` + `RIDEV_INPUTSINK`），不需要驱动，也不需要管理员权限。
- 移动事件按 50 ms 聚合打印，避免 8K 回报率刷屏；`--stats` 可以看真实包速率。
- 纯厂商自定义、不映射到标准 HID 的按键（例如只在 `0xFF06/0x0002` 私有集合里上报的
  配置态数据），还需要像电量一样对私有报文做逆向；标准键鼠事件已经覆盖。

## 键盘电量（PMO WAVE75）

```bat
python keyboard_battery.py --once
python keyboard_battery.py --json
python keyboard_battery.py --watch 30
```

协议与 PMO HUB 2.1.1 / Linux `hid-rdmctmzt` 驱动一致：`AA 10` 开会话、
`AA 30` 读电量、`AA 11` 结束；回复第 8 字节是电量、第 9 字节是充电状态。

**前提：PMO HUB 官方固件（键盘 + 接收器都要升级）。**

- 官方固件下 **2.4G dongle 会转发厂商命令**：实测 `AA 10` / `AA 30` 返回
  `status=0x55`，读到 63–66%，有线模式同样可用。
- QMK/VIA 固件不行：VIA 可以用 usevia.app 改键，但固件里没有主机侧电量命令
  （`get_keyboard_value` id 5 返回 `0xFF`，custom 通道 2/3 只是灯效），
  只能用 `Fn+Backspace` 看数字键灯。
- 当前如果检测到 QMK/VIA 固件，`keyboard_battery.py` 会直接说明原因，不会误报 100%。

## 目录结构

| 文件 | 说明 |
|---|---|
| `eweadn_proto.py` | 协议常量、校验和、报文构造 / 解析、设备发现、`read_battery()` |
| `eweadn_battery.py` | 鼠标命令行入口（`--once` / `--json` / `--watch` / `--debug`） |
| `my_devices.py` | 两台设备统一入口（验收标准 1 的 `--once` 两行输出） |
| `battery_panel.py` | Tkinter 双设备电量面板（鼠标 + 键盘 / 自启 / 桌面链接 / 退出托盘） |
| `tray_app.py` | 托盘常驻（两个数字图标 + SetTimer + 单实例） |
| `tray_common.py` | 托盘配置、开机自启、桌面链接、IPC、僵尸清理 |
| `device_lock.py` | 跨进程命名互斥体，串行化面板/托盘同时读取 |
| `last_state.py` | 上次电量缓存（设备休眠时显示上次更新） |
| `generic_protocols.py` | 多厂商协议表 / 标准 HID / 抓包协议读取 |
| `generic_scan.py` | 多厂商设备扫描 CLI（`--list` / `--json` / `--watch`） |
| `win_icon.py` / `win_link.py` / `win_shell.py` | 纯 ctypes 图标 / 软连接 / .lnk |
| `app.py` | 完整调试版（Feature/Output/Input、探测 Report ID、手动标定） |
| `debug_tool.py` | 枚举 / 监听 / 发原始命令 / 唤醒检查 |
| `mouse_events.py` | Raw Input 事件监控（按键 / 移动 / 滚轮 / 键盘） |
| `mouse_test_gui.py` | 可视化鼠标测试面板（测试区域 / 按键指示 / 坐标 / 点击统计） |
| `pmo_proto.py` | PMO WAVE75 键盘电量协议（USB / PMO 固件） |
| `keyboard_battery.py` | 键盘电量命令行入口 |
| `hid_win.py` | 纯 ctypes 的 Windows HID 访问层（沿用 `2.4G-battery-viewer`） |
| `tests/test_proto.py` | 纯协议单元测试（不访问硬件） |
| `tests/test_generic.py` | 多厂商协议帧/校验/解析单元测试 |

## 测试

```bat
python -m unittest discover -s tests -v
```

8 个用例覆盖：真机抓包帧的校验和、报文归一化、电量解析、电压曲线、单调性；
另外 5 个用例覆盖 Raw Input 的移动 / 按键 / 滚轮 / 键盘事件解析；
再加 4 个用例覆盖 PMO 键盘报文构造与电量数据；
最后 12 个用例覆盖多厂商协议的请求帧 / 校验 / 解析（ATK、MCHOSE、JL、Zowie 等），共 29 个。

## 验收自检（本机实测）

| 验收项 | 结果 |
|---|---|
| `python my_devices.py --once` | 两行：鼠标 85% / 键盘 61%（2.4G） |
| 面板两张卡片 + 颜色 | 绿（≥60），鼠标/键盘均正常 |
| 任务管理器启动项 | 启动文件夹 `电量托盘.lnk`，`autostart_status()` 显示「已启用」 |
| 桌面入口 | `外设电量` 目录 **symlink** + `启动面板.cmd` **symlink**（非复制） |
| 无日志文件 | 配置/上次电量在 `%APPDATA%\ExtBatteryTray`，项目目录无日志 |
| 休眠显示 | 灰色上次电量 + 上次更新 HH:MM（面板 / 托盘 tooltip） |
| 多厂商扫描 | `generic_scan.py` 命中 EWEADN/PMO；其他协议待真机验证 |
| 托盘连续启停 3 次 | 3 次均成功，最后 `pythonw` 进程数 = 0 |
| 空闲 CPU | 10 秒内 `0.000` 秒（SetTimer 60 秒） |

复验命令：

```bat
python my_devices.py --once
python tray_app.py --status
python tray_app.py --quit
python -c "import tray_common as tc; print(tc.autostart_status()); print(tc.desktop_link_status())"
```

## 逆向过程（简述）

E-HUB 是 Electron 应用，设备页通过 WebHID 直接与 dongle 通信。它的前端 bundle
（`new-hub.eweadn.cn` 的 `main.sdk-mouse-jiangmeng` / `mouse-hid-jiangmeng-device`
chunk）里保留了完整的「匠盟」协议实现：16 字节报文、命令表、校验和、电量字段偏移
和电压曲线。按这些常量在本机 HID 接口上复现后，第一次发送 `0x04` 就拿到了
`08 04 ... 5A 00 0F D1` 的真实回包，与代码解析完全吻合。

## 限制

- 鼠标只支持 `3554:F517`（以及同协议的 EWEADN 8K 系列；其它 VID/PID 需要自行改常量）。
- 键盘只支持 `36B0:3002`（2.4G dongle）/ `36B0:3009`（USB 有线），且必须是
  PMO HUB 官方固件；QMK/VIA 固件没有主机侧电量命令。
- 只支持 Windows（依赖 `setupapi` / `hid` / `kernel32`）。
- 接收器必须插在 USB 口上；鼠标/键盘需开机并与接收器配对。
- 不做设置写入、不改 DPI / 灯效 / 按键，只读取电量与在线状态。

## 致谢

HID 访问层 `hid_win.py` 与托盘/快捷方式基础模块来自
[2.4G-battery-viewer](../2.4G-battery-viewer)；托盘图标、上次电量缓存、
`--list/--install/--panel` 等交互参考了
[EZ2.4G](https://github.com/Ap0LoG1zE/EZ2.4G)（MIT）。

多厂商协议参数来自公开资料：
[sdparklab/Voltide](https://github.com/sdparklab/Voltide)（MIT）、
[aliezzzz/mchose-battery](https://github.com/aliezzzz/mchose-battery)（MIT）、
[Techxey/atk-mouse-battery](https://github.com/Techxey/atk-mouse-battery)、
[HifumiDaisuki01/MchoseBatteryTray](https://github.com/HifumiDaisuki01/MchoseBatteryTray)
以及 `EZ2.4G/c/PROTOCOLS.md` 的整理。协议部分仅供学习与个人使用。
