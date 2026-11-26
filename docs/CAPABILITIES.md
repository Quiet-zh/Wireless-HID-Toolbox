# 能力总览

> 本文是项目能力的**一页速查**。协议细节与逆向过程见
> [AiMouse 语音链路逆向笔记](AiMouse-RE-Notes.md)，版本历史见
> [CHANGELOG.md](../CHANGELOG.md)。

## 1. 核心能力

| 领域 | 能力 | 依赖 |
| --- | --- | --- |
| 电量 | EWEADN 8K、PMO WAVE75、罗技 G304、魔声 AI 垂直鼠标等 | 无 |
| 设备目录 | 登记/删除/恢复/类型、统一字段、托盘逐设备开关 | 无 |
| HID 调试 | Feature / Output / Input 报告、Report ID 探测、手动标定 | 无 |
| 鼠标键盘测试 | 多设备切换、按键/移动/滚轮/点击统计、104 键布局 | 无 |
| **语音解码** | **纯本地**把 33B 加扰 ADPCM 还原成 16kHz WAV | **无**（零第三方运行时依赖） |
| 语音转文字 | sherpa-onnx（流式 Paraformer / SenseVoice）/ Vosk / 云端 ASR / 剪贴板桥接，按设置自动降级 | 可选 |
| 主题 | 白天/黑夜配色 | 无 |
| 打包 | `main.py` 统一入口，onefile / onedir | PyInstaller（可选） |

## 2. 语音链路全景（完全本地）

```
0xFF91 HID 33B 0x1B 帧
        │
        ├─ [5:33] 的 28B 按位置 XOR ADPCM_XOR_MASK（28B 固定密钥）
        │
        ├─ 标准 IMA 解码：低 4 位先，predictor/index 跨帧连续（初始 0/0）
        │
        ├─ 16bit / 16kHz PCM  →  高通 / 归一化（可选） →  WAV
        │
        └─ 本地识别（可选词表约束，仅 Vosk 支持）
              ├─ 前导静音门控 OnsetGate：裁掉 1~1.5s 底噪，句首不再「听出」假字
              ├─ stream_asr=1（默认）：边说边转，实时显示部分结果
              │     └─ 引擎：sherpa streaming-paraformer（默认）/ Vosk
              ├─ stream_asr=0：录音期间不识别，松开后整段识别一次
              │     └─ 引擎：sherpa SenseVoice（默认）/ Vosk
              └─ 可选：voice_typing=1 时把文字键入当前焦点输入框
```

实测（1528 帧 / 5.35s）：RMS **8694**、相邻差中位 **521**、饱和 **0.6%**，
与官方驱动解码的 PCM 波形统计一致。

**不需要**：云端 ASR、官方驱动运行、读取剪贴板、第三方运行时库。

## 3. 识别模式与依赖矩阵

| 设置 | 走的后端 | 联网 | 需要官方驱动 | 备注 |
| --- | --- | --- | --- | --- |
| `local_only=1`（默认） | 仅本地引擎 | ❌ | ❌ | 完全纯本地 |
| `local_only=0, asr_backend=0` | 本地 → 云端 → 剪贴板 | 可能 | 可能 | 自动降级 |
| `asr_backend=1` | 仅本地引擎 | ❌ | ❌ | |
| `asr_backend=2` | 剪贴板桥接 | ❌ | ✅ | 复用官方识别结果 |
| `asr_backend=3` | 云端 ASR | ✅ | 运行时凭据 | 需 `websockets` |

「本地引擎」由 `asr_engine` 决定：**0 自动（sherpa 优先）/ 1 强制 sherpa / 2 仅 Vosk**。
sherpa 缺依赖或模型时自动回退 Vosk，不会静默降级。

可选依赖（**装了才启用，不装不影响其他功能**）：

| 包 | 用途 |
| --- | --- |
| `sherpa-onnx` + 模型 | 本地转文字（**默认推荐**，不依赖 numpy） |
| `vosk` + 中文模型 | 本地转文字（回退方案，支持 runtime 词表） |
| `websockets` | 云端 ASR |
| `noisereduce` + `numpy` | 可选降噪（一般不建议） |

模型目录（`sherpa_model_dir` 下自动探测，无需记目录名）：

| 模型 | 体积 | 用途 |
| --- | --- | --- |
| `sherpa-onnx-streaming-paraformer-bilingual-zh-en` | 226MB | 流式，边说边出字，中英混说 |
| `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | 229MB | 整段，中文准确率更高，带标点与 ITN |

一键下载：`python tools/download_models.py`（走 hf-mirror，多线程分段；
单连接被限速时加 `--jobs 8`；`.tmp`/`.partN` 校验通过才改名，可重跑续传）。

Vosk 方案：`vosk-model-small-cn-0.22`（42MB）。
更强的 `vosk-model-cn-0.22`（1.3GB）可直接把 `model_dir` 指过去；
大模型通用识别更准，但**不支持 runtime grammar**，词表只在 small 系列生效。

### 3.1 前导静音门控（准确率的最大杠杆）

设备按下语音键后有 1~1.5 秒纯底噪。这段静音喂给模型会让它在句首「听出」
不存在的字——实测同一段音频（真值「测试语音输入一二三」）：

| 配置 | 结果 |
| --- | --- |
| Vosk 小模型 原始 | 此事语音输入与啊上 ❌ |
| Vosk 小模型 + 门控 | 去是语音输入与啊上 ❌ |
| Vosk 大模型 原始 | 是语音输入一二三 |
| Vosk 大模型 + 门控 | **测试语音输入一二三** ✅ |
| sherpa 流式 原始 | 请世是语音输入与二 ❌ |
| sherpa 流式 + 门控 | 刺试语音输入语二三（7/8 字）✅ |

参数：20ms 窗口、**阈值自适应**（底噪最小能量 × 3.5，下限 400）、连续 2 窗口
超标才认定起点、起点回退 120ms（保住弱起辅音）、2.5 秒仍未检测到起点则先按
0.4 倍阈值重找、再找不到才全放行。

**为什么必须自适应**：同一台设备不同录音的底噪实测差 160 倍（窗口 RMS 7~1152）。
35 条真实录音对比（SenseVoice 作伪真值，Levenshtein 字错率）：
固定阈值 3000 → CER 0.279；自适应 2.0 倍 → 0.154；2.5 倍 → 0.163；
3.5 倍（选定）→ 0.163；4.5 倍 → 0.165。选 3.5 是因为长静音样本
（1.46s 底噪）只有在 3.5 倍时才裁得够。

## 4. 语音窗口参数速查

设置（⚙）里共 **18 项**，每项都有输入框；数值项另有左右加减按钮，
**点「保存」才生效**。配置文件：`%APPDATA%\ExtBatteryTray\voice_config.json`。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `highpass` | 150 | 高通截止 Hz，0 关闭 |
| `peak` | 26000 | 归一化峰值 |
| `denoise` | 0 | 降噪强度 0–100 |
| `auto_transcribe` | 1 | 录完自动转文字 |
| `max_seconds` | 30 | 单次最长录制 |
| `save_dir` | `…\voice` | WAV 保存目录 |
| `model_dir` | `…\vosk-model-small-cn-0.22` | Vosk 模型目录 |
| `asr_engine` | 0 | 0 自动（sherpa 优先）/ 1 强制 sherpa / 2 仅 Vosk |
| `sherpa_model_dir` | `%APPDATA%\ExtBatteryTray\models` | sherpa 模型根目录，自动探测子目录 |
| `asr_backend` | 0 | 0 自动 / 1 本地 / 2 剪贴板 / 3 云端 |
| `local_only` | **1** | 1 = 只用本地引擎，完全不联网/不读剪贴板 |
| `asr_grammar` | 空 | 逗号分隔候选词，启用词表约束（仅 Vosk） |
| `stream_asr` | **1** | 1 = 边说边转（流式）；0 = 松开后整段识别一次 |
| `asr_refine` | **1** | 1 = 松手后再用 SenseVoice 定稿（约 0.17s） |
| `onset_gate` | **1** | 1 = 启用前导静音门控；0 = 原样送引擎 |
| `onset_factor` | 35 | 门控灵敏度（0.1 倍单位，35 = 底噪的 3.5 倍） |
| `voice_typing` | 0 | 1 = 识别结果自动键入当前焦点输入框 |

**词表实测**（`local_decoded.wav`，用户说「测试语音输入一二三」）：

| 配置 | 结果 |
| --- | --- |
| 小模型通用 | 「此事 语音 输入 与 啊 上」 |
| 小模型 + `测试,语音,输入,一二三` | **「测试 语音 输入 一二三」** |
| 大模型 通用 | **「是 语音 输入 一 二 三」** |
| 大模型 + 词表 | 「是 语音 输入 一 二 三」（词表被忽略） |
| 小模型 + 前导静音门控 | 「去是语音输入与啊上」（仍不行，小模型能力上限） |
| 大模型 + 前导静音门控 | **「测试语音输入一二三」**（无需词表） |
| sherpa 流式 + 前导静音门控 | 「刺试语音输入语二三」（7/8 字，0.25s） |

窗口顶部绿色徽标会实时显示当前模式，例如
`🟢 纯本地解码 · 仅本地 sherpa-onnx · 通用识别`；
实时区域下方显示解码方式、识别后端、模式与当前模型名。

## 5. 关键文件索引

| 文件 | 职责 |
| --- | --- |
| `aimouse_voice.py` | 帧解析、`ADPCM_XOR_MASK`、`decode_frames_local()`、`LocalStreamDecoder`（增量流式解码）、`OnsetGate`/`find_onset`（前导静音门控）、WAV/滤波 |
| `aimouse_voice_capture.py` | 命令行 HID 采集（`--list` / `--seconds`） |
| `aimouse_voice_panel.py` | 语音窗口、录制线程、Vosk 封装、`make_asr_engine()` 引擎工厂、剪贴板桥接、设置 UI |
| `aimouse_sherpa_asr.py` | sherpa-onnx 引擎（流式 Paraformer + 整段 SenseVoice），接口对齐 Vosk 封装 |
| `aimouse_cloud_asr.py` | 官方云端 ASR 协议（可选，`websockets`） |
| `hid_win.py` | Windows HID 枚举/读写（ctypes） |
| `ui_common.py` | 按需滚动条（`AutoScrollbar`）：纵/横向仅在内容超出时显示 |
| `voice_typing.py` | 焦点捕获 + `SendInput` Unicode 键入（语音输入到任意输入框）、退格 |
| `tools/verify_local_decode.py` | 独立验证纯本地解码链路（零依赖） |
| `tools/download_models.py` | 下载 sherpa-onnx 中文模型（hf-mirror，可重跑续传） |
| `tools/compare_asr.py` | 用真实抓包对比 sherpa / Vosk 的识别结果与耗时 |
| `docs/AiMouse-RE-Notes.md` | 完整逆向过程、反汇编证据、协议细节 |
| `tests/` | 357 个自动化用例 |

## 6. 验证与自检

```bat
:: 解码链路回归（零依赖）
python tools\verify_local_decode.py

:: 下载 / 核对识别模型
python tools\download_models.py

:: 用真实抓包对比各引擎准确率与耗时
python tools\compare_asr.py

:: 全量测试
python -m unittest discover -s tests

:: 版本
python main.py --version
```

## 7. 语音能力版本演进

| 版本 | 里程碑 |
| --- | --- |
| 1.4.0 | 0xFF91 电量协议 |
| 1.5.0 | ADPCM 解码（旧版，每帧独立） |
| 1.6.0 | 语音窗口（录制/播放/转文字/设置） |
| 1.9.2 | Frida 逐样本验证解码算法 100% 正确 |
| 1.9.3 | 定位按位置固定 XOR 加扰 |
| **1.10.0** | **纯本地解码打通**（精确密钥 + 跨帧连续 IMA） |
| 1.11.0 | Vosk 识别词表约束（固定命令 100% 正确） |
| 1.12.0 | 纯本地模式开关、界面模式徽标、能力文档整理 |
| 1.12.1 | 全局按需滚动条组件；语音列表/设置对话框/调试台滚动条改为按需显示 |
| 1.12.2 | 大模型检测与词表兼容性处理、四组识别实测入档 |
| 1.12.3 | 按 Git 提交记录整理文档与版本声明，推送 GitHub |
| **1.13.0** | **语音输入：识别结果自动键入当前焦点输入框** |
| 1.13.1 | 修复松开键卡在「处理中…」、模型缓存/预热、消除重复识别 |
| **1.14.0** | **流式 / 整段转文字模式开关（默认流式）** |
| 1.14.1 | 静音 Vosk/Kaldi 模型加载日志 |
| 1.14.2 | 修复事件轮询异常导致语音功能整体失效；协议兜底与抓帧诊断工具 |
| 1.14.3 | 修复设置对话框 `bind_all` 滚轮绑定泄漏导致的 TclError 刷屏 |
| **1.14.4** | **修复流式转文字喂未解扰噪声、识别不出文字** |
| 1.14.5 | 识别结果中文词间空格规整，流式/整段/语音输入一致 |
| **1.15.0** | **一键打开录音保存目录 / 设置路径按钮** |
| 1.15.1 | 「转文字」按钮文字修正并加 📝 图标 |
| **1.16.0** | **启动首屏缓存秒开 + HID 在线不再误报休眠** |
| 1.17.0 | 刷新间隔可输入秒数（1s~60min），>60s 自动转分钟显示，新增 10 秒选项 |
| **1.18.0** | **未连接设备默认不显示（面板 + 托盘），设置可开启** |
| 1.18.1 | Ctrl+C 撞上 vosk 导入锁时安静退出、不刷 traceback |
| **1.19.0** | **保存语音开关（默认开），关闭后不写 WAV 但仍能转文字** |
| 1.20.0 | 流式转写时同步流式键入焦点输入框（增量 + 退格纠正） |
| 1.20.1 | 修复流式输入完成后最终结果重复输入一次 |
| **1.21.0** | **前导静音门控（准确率最大杠杆）+ 集成 sherpa-onnx 引擎（流式 Paraformer / 整段 SenseVoice），Vosk 保留可回退** |
| **1.22.0** | **收尾高精度校正：流式实时出字 + SenseVoice 定稿（实测 7/8 字 → 全对），下载工具改多线程分段** |
| **1.23.0** | **门控改自适应（固定阈值实测不可用）+ 门控开关与灵敏度可调；流式结果再提升到只错 1 字** |
