# Wireless HID Toolbox（2.4G 外设工具箱）

当前版本：**v1.7.0**（更新记录见 [CHANGELOG.md](CHANGELOG.md)）

Windows 10/11 的 2.4G 无线外设电量与 HID 调试工具箱。纯 Python 标准库 +
`ctypes` + `tkinter`，运行时不依赖任何第三方库。

- **电量**：EWEADN 8K、PMO WAVE75、罗技 G304、Monster AiMouse，以及协议表里的其他设备
- **设备目录**：Monster AiMouse（`248A:60AB`）已登记，可在面板/托盘/测试面板显示，
  并通过 `0xFF91` 私有口读取电量（实验性解析，见「支持的设备与协议」）；
  英菲克 F15 无线鼠标（`1EA7:0064`）与狼蛛 S99 三模键盘（`1A2C:7FFF`）
  也已登记，当前只显示占位、不显示电量
- **语音解码**：Monster AiMouse 长按语音键时，`0xFF91` 会回传 ADPCM 语音，
  `aimouse_voice.py` 可还原成 16kHz WAV（见「语音解码」）
- **语音窗口**：AiMouse 卡片上的「🎤 语音」按钮，支持监测录音、列表播放/删除、
  实时转文字与参数设置（见「语音窗口」）
- **主界面**：可选设备卡片、统一字段、托盘图标逐设备开关、最小化到托盘
- **托盘**：每台勾选的设备一个数字图标，点击打开/恢复面板
- **测试**：鼠标键盘测试，多设备切换监听、按键/移动/滚轮/坐标/点击统计
- **调试**：完整 HID 调试台（Feature / Output / Input / 探 ID / 手动标定）
- **系统集成**：开机自启、桌面入口、上次电量缓存
- **打包**：`main.py` 统一入口，onefile / onedir 可选

## 文档导航

- [更新记录](CHANGELOG.md)
- [打包说明](docs/PACKAGING.md)：onefile 默认、onedir 选择、产物与排错
- [主题说明](docs/THEME.md)：白天/黑夜配色与新增颜色约定
- [测试说明](docs/TESTING.md)：自动化覆盖、GUI 手动验收清单
- [设备配置](docs/DEVICE_CONFIG.md)：设备类型、删除/恢复、配置字段

![黑夜主题](docs/panel.png)

![白天主题](docs/light_panel.png)

![设置](docs/settings.png)

## 支持的设备与协议

| 协议 / 方案 | 识别方式 | 电量位置 |
| --- | --- | --- |
| EWEADN 8K（本机） | `3554:F517`，`0xFF02`，17B | `[5]`，电压曲线 |
| PMO WAVE75（本机） | `36B0:3002/3009`，`0xFF60` | `[8]`，RDR `AA 30` |
| 罗技 G304 / HID++ | `046D:C53F`，HID++ 2.0 | `0x1000/0x1004` |
| ATK / VXE / VGN 协议 1 | `0xFF02`，17B | `[6]`，`0x55` 校验 |
| ATK / VXE 协议 2 | `0xFF05`，64B | `[7]` |
| Dareu A950 / VXE / Imecoo | 同 ATK 1 | `[6]` |
| MCHOSE V9 Turbo / Turbo+ | `0xFF90`，`55 65 01` | `[2]` |
| MCHOSE A5 / AX5 | `0x2023`，Feature 65，MI_02 | `[8]`，cmd `0x83` |
| MCHOSE A7 compatible | `5253:1021`，Feature `0x11` | payload `[9]` |
| MCHOSE gmouse | `0xFF01`，`55 30 A5 0B 2E` | 回复 `AA 30` 后 `+8` |
| MCHOSE Z75S | `258A:01BB`，20B | `[5]` |
| ATK N9V2 耳机 | `0xFF90`，`55 65 01` | `[2]` |
| XIBERIA T7 | `36F9:*`，`0xFF00` | `[3]` |
| Rapoo VT3S | `24AE:1411`，主动上报 | `[8]` |
| Endgame Gear | Feature `0xA1` | `[16]` |
| VAXEE / ZYGEN | Feature `0x0E` | `[5] × 5%` |
| Nordic nRF | Feature `0x05` | `[9]` |
| DARKRIM / 杰理 | `3654:6901`，JL_RCSP | TLV `0x01` |
| ZOWIE DW | `04A5:800A`，双接口 | 电压插值（实验） |
| 标准 HID | Battery Strength Usage | Feature 值 |
| Monster AiMouse（本机） | `248A:60AB`，私有 `0xFF91` 主动上报 | `[5]`，实验性（约 2.5 秒一帧） |
| 抓包协议 | `captured.json` | 任意偏移 |

> Monster AiMouse 的 `0xFF91` 接口会主动上报两种帧：带电量帧
> `0C 4D ?? 69 00 <电量> 04 01 00 4C`（偏移 5 为百分比）和不带电量的心跳帧
> `0C 4D 05 67 00 4C ...`（已排除，避免误报 76%）。当前按用户实测约 100%
> 校准，属实验性解析，只在 `248A:60AB` 上启用；休眠时回退到上次缓存。
>
> 英菲克 F15 无线鼠标（`1EA7:0064`，VID `0x1EA7` SHARKOON / PID `0x0064`）与
> 狼蛛 S99 三模键盘（`1A2C:7FFF`，VID `0x1A2C` China Resource Semico /
> PID `0x7FFF`，产品名 `2.4G Wireless Device`）已登记到设备目录，面板、托盘和
> 测试面板都能按名称/类型识别。两者尚未收录私有电量协议，当前只显示占位卡片、
> 不显示百分比；若设备暴露标准 Battery Strength Usage 会自动读到，否则需抓包
> 确认报文后写入 `captured.json` 或新增协议读取函数（见「设备配置」）。
>
> EWEADN、PMO、罗技 G304、Monster AiMouse 在本机实测；其他协议来自公开协议文档/仓库的移植，
> 已做单元测试，但建议接上设备后用 `generic_scan.py --list` / `--scan` 验证。
> 只发送只读查询，不写设备配置；未知 opcode 不要盲目爆破。

## 快速开始（源码）

```bat
cd D:\zh\DeepSeekHarness\HUB\Wireless-HID-Toolbox

python main.py                    :: 主界面（默认）
python main.py --version          :: 版本号
python main.py --tool tray        :: 托盘
python main.py --tool mouse-test  :: 鼠标键盘测试
python main.py --tool hid-debug   :: HID 调试台

python my_devices.py --once       :: 两台本机设备读一次
python my_devices.py --scan       :: 所有已收录协议
python generic_scan.py --list     :: 看本机设备命中了哪些协议
```

源码运行也可以直接双击 `启动面板.cmd` / `启动托盘.cmd`。

## 打包成 exe

```bat
python -m pip install -r requirements-build.txt

:: 默认：onefile 单文件
build_exe.bat

:: 选择文件夹模式
build_exe.bat onedir

:: 显式选择单文件
build_exe.bat onefile
```

也可以不带参数运行 `build_exe.bat`，按提示选择 `[1] onefile` 或 `[2] onedir`。

产物：

```text
onefile: dist\WirelessHIDToolbox.exe
onedir:  dist\WirelessHIDToolbox\WirelessHIDToolbox.exe
```

- **默认 onefile**，分发只需要一个 exe；首次启动会解压到临时目录，稍慢
- onedir 文件夹模式启动更快，分发时把整个 `dist\WirelessHIDToolbox` 一起打包
- **双击 exe 直接打开主界面**；
- 设置里的鼠标键盘测试、HID 调试台、托盘通过 `exe --tool ...` 打开，
  不依赖外部 `.py` 文件；
- 开机自启/桌面入口在 exe 模式下指向 exe 本身；
- 打包启用 `--optimize 2`、无用的标准库排除、`app.ico` 图标和
  `version_info.txt` 版本资源；
- PyInstaller 只用于打包，运行程序本身仍然零第三方依赖。

更完整的模式选择、产物与常见问题见 [docs/PACKAGING.md](docs/PACKAGING.md)。

## 主界面

- 卡片按设备动态生成，不再写死；右上角 **⚙ 设置** 逐设备选择
- 所有卡片统一字段：**连接 / 充电 / 电压 / 数据源**
- 大号百分比 + 进度条；休眠时显示灰色上次电量 + 上次更新时间
- 底部：**立即刷新 / 自动刷新 / 常驻托盘**
- 右上角：**☀ 白天 / 🌙 黑夜** 主题切换，配置持久化；已打开的工具窗口自动跟随
  （实现与配色约定见 [docs/THEME.md](docs/THEME.md)）
- ⚙ 设置 → **标题栏按钮**：
  - 最小化（-）：最小化到托盘 / 正常收起窗口（任务栏仍保留应用图标）
  - 关闭（×）：仅关闭主界面 / 关闭所有可见窗口 / 完全退出应用（含托盘）
- 完全退出会弹窗确认，并结束本应用打开的测试/调试工具与托盘
- **每个界面**的 × 都读取同一设置：设置窗口、鼠标键盘测试、HID 调试台同样生效
- 托盘未运行且 × 不是“完全退出”时，会先询问是否启动常驻托盘
- 没有托盘且关闭的是最后一个应用窗口时，视为完全退出
- 标题栏最小化按设置执行；缩到托盘前先标记状态并加启动锁，不会重复启动托盘/重复图标

### 设置窗口

- 设备卡片 / 托盘图标：每台设备独立勾选
- 设备类型：鼠标 / 键盘下拉选择，写入设备配置
- 删除此设备；「恢复已删除」可找回，扫描不会自动恢复已删设备
- 扫描并刷新设备列表
- 常驻托盘：启动 / 退出
- 标题栏按钮：最小化（-）/ 关闭（×）行为
- 开机自启、创建桌面链接
- 刷新间隔：30 秒–30 分钟
- 工具：扫描全部、协议表、鼠标键盘测试、HID 调试台、项目目录、配置目录

设备类型、删除/恢复与配置字段见 [docs/DEVICE_CONFIG.md](docs/DEVICE_CONFIG.md)。

## 托盘常驻

```bat
python tray_app.py --status
python tray_app.py --debug
python tray_app.py --quit
```

- 每台勾选「托盘」的设备一个图标，数字即电量
- 绿 ≥60 / 黄 30–59 / 红 <30；灰色数字表示休眠缓存
- **点击图标打开/恢复面板**（左键/右键均可），同时刷新一次
- tooltip：`设备名：电量%（更新时间）`
- 低 CPU：`SetTimer` 驱动，默认 60 秒
- 退出走 `WM_DESTROY -> PostQuitMessage`，不留僵尸进程

## 鼠标键盘测试

```bat
python mouse_test_gui.py
python mouse_test_gui.py --demo
```

![鼠标键盘测试](docs/mouse_test.png)

- 鼠标页 / 键盘页各自有「监听设备」下拉框
- 按物理设备（VID:PID）归入一个主类别，接收器的 Consumer/键盘集合
  不会串到鼠标列表，也不会把鼠标集合串到键盘列表
- 系统里同类设备 **大于 1 台** 时出现下拉框，可切换「全部」或指定设备；
  点「刷新」重新枚举
- 切换设备会重启 Raw Input 监听并清空旧事件
- 鼠标：通用 5 键示意图、每键计数/按下状态、滚轮、坐标、点击统计、双击判定
  - **回报率**：当前/峰值/平均 Hz（基于 Raw Input 移动报告）
  - 可选 **绘制轨迹**，统计轨迹点数
  - 示意图目前不按型号自动变形；不同型号的 DPI/宏键通常不走标准 Raw Input，
    需要厂商协议才能单独识别，因此不伪造额外按键
- 键盘：**104 键全配列**（含功能行、导航区、数字小键盘）
  - 按下亮起、松开熄灭；支持同时按下/最大 rollover、Caps/Num/Scroll 锁定
  - 显示按键名、VK、扫描码、最近按键、按键次数，可一键重置
- 只显示，不记录、不落盘

![键盘全配列测试](docs/keyboard_test.png)

## 语音解码（Monster AiMouse）

`0xFF91` 私有口除了电量，还会在长按语音键时回传 **IMA ADPCM 压缩语音**。
`aimouse_voice.py` 可把它还原成 16kHz / 16bit 单声道 WAV：

```python
import aimouse_voice as av

frames = [...]                        # 从 0xFF91 读到的 33 字节帧
samples = av.decode_frames(frames)    # -> 16bit 样本
av.save_wav("voice.wav", av.normalize(samples))
```

帧结构（反汇编 `AiMouse.exe` 0x4E6890 处的解码函数确认）：

| 偏移 | 内容 |
| --- | --- |
| `[0]` | `0x1B` 帧标识 |
| `[1:3]` | predictor，int16 小端（每帧重置） |
| `[3]` | step_index，0–88（越界截断） |
| `[4]` | `0xBE` 保留字节 |
| `[5:33]` | 28 字节 = 56 个 4-bit nibble，**低 4 位先** |

每帧 56 样本 @16000Hz = 3.5ms，与实测约 280 帧/秒吻合。

**降噪建议**：4-bit ADPCM 量化噪声接近白噪声，理论 SNR 约 20dB。

- **人耳试听**：可用 `noisereduce`（可选依赖，不在运行时依赖内）做谱减，
  `prop_decrease≈0.75` 在"沙沙"与"回音"之间较平衡
- **送 ASR 转文字**：建议只用 `av.highpass()` 轻度高通，**不要重度降噪** ——
  谱减产生的"音乐噪声"是非自然伪影，反而更容易让语音识别出错

> 官方驱动的做法正是把 ADPCM 原样发往云端 ASR、不做本地降噪，原因就在这里。

## 语音窗口（Monster AiMouse 卡片）

主界面 Monster AiMouse 卡片右上角的 **🎤 语音** 按钮打开语音窗口：

- **开始监测 / 结束监测**：长按鼠标语音键开始录音，松开自动保存一条 WAV
- **录音列表**：点击选中，支持 **播放 / 停止 / 删除 / 转文字**
- **实时区域**：录音中显示音量条与实时识别文字
- **设置（⚙）**：每个参数一行，含参数名、中文描述、输入框与左右加减按钮，
  **点「保存」才生效**

可调参数（存放于 `%APPDATA%\ExtBatteryTray\voice_config.json`）：

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `highpass` | 高通截止频率（Hz）；0 关闭 | 150 |
| `peak` | 归一化峰值；越小越不易削波 | 26000 |
| `denoise` | 降噪强度 0–100（需 noisereduce） | 0 |
| `auto_transcribe` | 录制结束后自动识别（1/0） | 1 |
| `max_seconds` | 单次最长录制（秒） | 30 |
| `save_dir` | 音频保存目录 | `%APPDATA%\ExtBatteryTray\voice` |
| `model_dir` | Vosk 中文模型目录 | `…\models\vosk-model-small-cn-0.22` |

### 语音识别（可选）

识别使用 Vosk 离线引擎，**装了就启用，没装则自动降级为「仅录音」**，
不影响其他功能，项目本身仍保持零第三方运行时依赖：

```bat
python -m pip install vosk
```

中文小模型（约 42MB）下载后解压到 `model_dir`：

```text
https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
```

## HID 调试台

```bat
python app.py
```

![HID 调试台](docs/debug.png)

- 枚举 HID 接口、Feature/Output/Input 报告
- 探测 Report ID 0..15
- 手动标定：Report ID + 字节下标 + 倍率 + 偏移，保存 `calibration.json`
- 日志只在窗口里显示，不写文件

## 开机自启 / 桌面链接

- 开机自启：启动文件夹 `电量托盘.lnk`
  - 源码版目标 `pythonw.exe tray_app.py`
  - exe 版目标 `WirelessHIDToolbox.exe --tool tray`
  - 任务管理器「启动」里可见/可禁用
- 桌面入口：
  - 源码版：项目目录 symlink/junction + `启动面板.cmd` symlink/hardlink
  - exe 版：`外设电量.lnk` 指向 exe
- 配置读取真实状态，不自动改用户系统设置

## 配置 / 缓存

```text
%APPDATA%\ExtBatteryTray\config.json
%APPDATA%\ExtBatteryTray\last_<key>.json
```

`config.json` 的 `devices`：

```json
"devices": {
  "3554:F517": {"name": "EWEADN 8K", "show": true, "tray": true, "order": 10},
  "36B0:WAVE75": {"name": "PMO WAVE75", "show": true, "tray": true, "order": 20},
  "248A:60AB": {"name": "Monster AiMouse", "show": true, "tray": true, "order": 25},
  "1EA7:0064": {"name": "英菲克 F15 无线鼠标", "show": true, "tray": true, "order": 30},
  "1A2C:7FFF": {"name": "狼蛛 S99 三模键盘", "show": true, "tray": true, "order": 40},
  "046D:C53F": {"name": "罗技 G304 / Lightspeed", "show": true, "tray": true, "order": 50}
}
```

`show` = 面板卡片，`tray` = 托盘图标。运行期还会写
`tray_pid.txt`、`panel_hwnd.txt`、`panel_show.req`，都不是日志。

## 命令行

```bat
python my_devices.py --once
python my_devices.py --json
python my_devices.py --watch 30
python my_devices.py --scan
python my_devices.py --list
python my_devices.py --install
python my_devices.py --panel

python generic_scan.py
python generic_scan.py --list
python generic_scan.py --protocols
python generic_scan.py --json
python generic_scan.py --watch 60

python tray_app.py --status
python tray_app.py --quit
```

## 实现要点

- **HID 访问**：`setupapi` / `hid.dll` / `kernel32`，读用独立 overlapped 句柄
- **多厂商协议**：协议表 + 标准 HID + 抓包协议；按 VID/PID/usage 匹配
- **并行扫描**：各设备分组并行读；面板用 `fast=True` 短超时，先展示缓存
- **跨进程锁**：键盘会话 `Local\ExtBatteryHidReadLock`；整轮扫描
  `Local\ExtBatteryHidScanLock`（短等待）
- **上次电量**：成功读取写 `last_state`；休眠时回退缓存
- **面板恢复**：隐藏时写 HWND + 显示请求文件，托盘点击恢复，不重复开窗
- **不写日志**：默认不产生日志文件，`--debug` 只打印到控制台

## 测试

```bat
python -m unittest discover -s tests -v
```

共 **78** 个用例：

- 8 个鼠标协议/电压曲线
- 5 个 Raw Input 事件解析
- 4 个 PMO 键盘
- 12 个多厂商协议帧/校验/解析
- 5 个 AiMouse 0xFF91 帧解析与设备匹配
- 16 个 AiMouse 语音解码/分段/WAV 输出
- 6 个语音窗口参数与配置读写
- 8 个设备目录/类型/删除恢复
- 3 个 104 键布局数据
- 4 个配置默认值/合并/主题回退
- 4 个主题配色映射
- 3 个版本号/Windows 版本资源/打包模式

详细覆盖矩阵与 GUI 手动验收清单见 [docs/TESTING.md](docs/TESTING.md)。

## 验收自检（本机实测）

| 项目 | 结果 |
| --- | --- |
| `my_devices.py --once` | 鼠标 84%（缓存/唤醒后即时）+ 键盘 58% |
| `generic_scan.py --json` | AiMouse `248A:60AB` 读到 100%（0xFF91 实验性协议） |
| 主界面 | EWEADN / PMO / 罗技 G304 / Monster AiMouse 卡片，字段统一 |
| 每设备托盘开关 | G304 关→`NIM_DELETE`，开→`NIM_ADD` |
| 最小化设置 | 托盘模式隐藏到托盘；任务栏模式保持 `iconic`/任务栏图标 |
| 关闭设置 | 仅主界面 / 所有可见窗口 / 完全退出（含托盘）均已验证 |
| 托盘连续启停 3 次 | 3/3 成功，最终 `pythonw` 进程数 = 0 |
| 开机自启 | `电量托盘.lnk`，任务管理器状态「已启用」 |
| 桌面入口 | 源码版 symlink，exe 版 `.lnk` |
| 空闲 CPU | 10 秒内 `0.000` 秒 |

## 限制

- 仅 Windows 10/11；依赖 Win32 HID / Raw Input
- 未知厂商协议仍需抓包确认；加密/私有握手需要逆向
- ZOWIE 双接口、MCHOSE A5/A7/gmouse 等尚未逐台真机验证
- 不做设置写入、不改 DPI / 灯效 / 按键，只读查询

## 致谢

HID 访问层与托盘/快捷方式基础模块来自
[2.4G-battery-viewer](../2.4G-battery-viewer)；托盘图标、上次电量缓存、
`--list/--install/--panel` 等交互参考了
[EZ2.4G](https://github.com/Ap0LoG1zE/EZ2.4G)（MIT）；`app.ico` 也来自该仓库。

多厂商协议参数来自公开资料：
[sdparklab/Voltide](https://github.com/sdparklab/Voltide)（MIT）、
[aliezzzz/mchose-battery](https://github.com/aliezzzz/mchose-battery)（MIT）、
[Techxey/atk-mouse-battery](https://github.com/Techxey/atk-mouse-battery)、
[HifumiDaisuki01/MchoseBatteryTray](https://github.com/HifumiDaisuki01/MchoseBatteryTray)
以及 `EZ2.4G/c/PROTOCOLS.md` 的整理。协议部分仅供学习与个人使用。
