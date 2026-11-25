# AiMouse 语音链路逆向笔记

> 本文记录 Monster AiMouse（`248A:60AB`）语音功能的逆向过程与结论，
> 对应代码：`aimouse_voice.py`、`aimouse_voice_capture.py`、
> `aimouse_voice_panel.py`、`aimouse_cloud_asr.py`。
>
> 所有实验均为**本机只读**分析；云端请求只发送用户自己录的测试语音到
> 用户自己设备的官方服务。文中不含任何真实密钥、设备序列号或 MAC 地址。

---

## 1. 设备接口

`248A:60AB` 枚举出 6 个 HID 接口：

| usage_page | 位置 | Input/Output/Feature | 用途 |
| --- | --- | --- | --- |
| `0x0001` | mi_00&col01 | — | 鼠标 |
| `0x000C` | mi_00&col02 | — | Consumer |
| `0x0001/0x0080` | mi_00&col03 | — | System |
| `0x0001/0x0006` | mi_01 | — | 键盘 |
| **`0xFFEF`** | mi_02&col01 | **64 / 64 / 64** | 厂商自定义（双向） |
| **`0xFF91`** | mi_02&col02 | **33 / 33 / 0** | 厂商自定义（电量、按键、语音帧） |

被动监听结果：`0xFF91` 在语音键按下期间上报 `0x1B` 音频帧（约 280 帧/秒）；
`0xFFEF` 全程 0 条 —— 推测驱动先用 Output/Feature 报告切换设备模式。

---

## 2. HID 帧与 ADPCM 解码

### 帧结构（33 字节）

| 偏移 | 内容 |
| --- | --- |
| `[0]` | `0x1B` 帧标识 |
| `[1:3]` | predictor，int16 小端 |
| `[3]` | step_index，`0..88` |
| `[4]` | `0xBE` 保留 |
| `[5:33]` | 28 字节 = 56 个 4-bit nibble，**低 4 位先** |

每帧 56 样本 @16kHz = 3.5ms。

### 反汇编证据

`AiMouse.exe` 的 IMA 解码函数位于 VA `0x4E6890`（file `0xE5C90`），
STEP 表 VA `0x7E0778`（file `0x3DEF78`），引用指令在 `0x4E690C`：

```
predictor = int16 @ buf[0:2]
step_index = buf[2] & 0xff
data = buf[4:]
step = STEP_TABLE[index]
diff = step >> 3
if nib & 4: diff += step
if nib & 2: diff += step >> 1
if nib & 1: diff += step >> 2
predictor += (nib & 8) ? -diff : diff
index = clamp(index + INDEX_TABLE[nib])
```

调用签名 `decode(buf, out, count)`；`buf` 即 `frame[1:]`。
`aimouse_voice.py` 已按此实现（纯标准库，零运行时依赖）。

### 波形验证（重要）

从驱动进程内存抓到官方发往云端的 PCM 后反推：

| | 官方 PCM | 早期每帧重置解码 |
| --- | --- | --- |
| RMS | 8750 ~ 9512 | 21247 |
| 相邻样本差中位 | 459 ~ 728 | 11127 |
| 帧边界跳变 | — | 26426 |

官方 PCM 可被**标准 IMA 完美拟合**（反推误差 0 ~ 4.6，解释率 100%，
稳态 `step_index ≈ 44~54`）。跨帧连续解码 + 每帧重置 index=0 能把帧边界跳变
降到 6、相邻差降到 1521，说明 `0x1B` 帧里确实含有语音信息。

但**配对实验**（同一时钟同时录 HID 帧与官方 PCM）显示两者 nibble 匹配率仅
8.1%（随机水平 6.25%）、波形相关度最高 0.094，排除简单异或加密、μ-law、
A-law、线性 8bit 及 7 种字节重组。结论：**我们旁听的 `0x1B` 流与官方送到云端的
不是同一份音频**，驱动另有数据源或模式切换。详见第 5 节。

---

## 3. 云端 ASR 协议（已打通并实测识别成功）

端点：`ws://asr.miclink.net/ws`（`wss://` 与 `?region=out` 同样可用）。

### 请求帧（每帧一个扁平 JSON，固定 10 字段）

| 字段 | 说明 |
| --- | --- |
| `apiKey` | **运行时动态 32 位值**，静态常量全部无效 |
| `clientId` | 任意 UUID（每个会话一个，所有帧共用） |
| `content` | **base64 编码的 16bit 小端 PCM**，每帧 2016B = 1008 样本 = 63ms |
| `deviceNo` | 本机 MAC |
| `dwa` | `"wpgs"`（讯飞动态修正） |
| `ptt` | `"1"` |
| `language` | `"ZH_CN"` |
| `serialNo` | 设备序列号 |
| `start` | 首帧 `true` |
| `end` | 末帧 `true` |

**关键点：首帧和末帧都带音频**（末帧可短于 2016B），
中间帧 `start=end=false`，帧间隔约 63ms。发空 content 的首/末帧会导致
服务端返回空 `text`。

### 响应

```json
{"data":{"btype":false,"clientId":"...","sn":"iat000...@gz...",
         "text":"测试语音输入1","type":"MID"},"message":"操作成功","status":200}
```

`type=MID` 为流式中间结果，`type=LAST` 为最终结果。

### 实测

原样重放一次录音抓到的 79 帧，返回：

```
次 → 次试 → 次试语 → … → 测试语音输入1 → 【LAST】测试语音输入1。
```

（用户实际说「测试语音输入一二三」。）

### 凭据获取

`apiKey` 不是 exe 里的静态常量，也不能从
`getModelInfo.json?productCode=1048&languageCode=ZH_CN&sno=...` 的
`data.appkey` 得到（那是翻译/语言 API 用的）。

可行方式：**只读扫描 AiMouse.exe 进程内存**，找到驱动运行时构造的
ASR 请求 JSON 并提取凭据。`aimouse_cloud_asr.read_driver_credentials()`
已实现（ctypes + `Toolhelp32Snapshot` / `VirtualQueryEx` / `ReadProcessMemory`，
零第三方依赖），也可由调用方显式传入配置。

---

## 4. 已落地的能力

| 模块 | 能力 |
| --- | --- |
| `aimouse_voice.py` | 33B 帧 → 16kHz PCM、分段、WAV、高通、归一化 |
| `aimouse_voice_capture.py` | 命令行采集（`--list` / `--seconds` / `--filter`） |
| `aimouse_voice_panel.py` | 主界面语音窗口：监测/列表/播放/删除/转文字/实时区域/设置 |
| `aimouse_cloud_asr.py` | 云端 ASR 协议（可选 `websockets`）、凭据读取、帧构造与解析 |

### 识别后端（设置里的 `asr_backend`）

| 值 | 含义 |
| --- | --- |
| 0 | 自动：云端 → Vosk → 剪贴板桥接 |
| 1 | 仅 Vosk（本地离线，需模型） |
| 2 | 剪贴板桥接（复用官方驱动识别结果，零依赖，仅录制后可用） |
| 3 | 仅云端 ASR |

**剪贴板桥接**是兜底方案：官方驱动松开语音键后约 0.4s 会把识别文字写入
剪贴板，窗口监听剪贴板序列号变化即可取到结果，不需要自己解码或模型。

> Vosk 中文小模型（`vosk-model-small-cn-0.22`）对 4-bit ADPCM 量化噪声
> 鲁棒性不足，本地实测只识别出单字；云端大模型可正常识别。
> 因此「自动」把云端放在最前。

---

## 5. 实验记录与未解决问题

### 已排除的假设

- 静态 apiKey / `data.appkey` / exe 里各种 32 位常量 → 服务端回「无效的apiKey」
- 音频为 ADPCM 原始字节 / 8bit PCM / μ-law / A-law → 识别结果为空
- 首帧或末帧 content 为空 → 识别结果为空
- 需要 `format` / `rate` / `FIRST_FRAME` / `LAST_FRAME` 字段 → 实际请求没有
- 音频走 `0xFFEF` Input Report → 全程 0 条
- HID 数据经过简单异或加密 → 异或后无固定 key（单值占比 1.2%）
- HID 字节按行/列/奇偶/半帧重组 → 均找不到官方 ADPCM 的 24 字节探针

### 静态逆向结论（A++）

| 线索 | 结论 |
| --- | --- |
| `0x7D3A60` / `0x7D3A6C` / `0x7D3A50` | `PostMessageW` / `FindWindowW` / `StrToIntW` |
| 调用者 `0x539C7B` | 跨窗口发自定义消息 `0x5FB` + 528B 缓冲的 IPC/测试代码，非音频路径 |
| `0x4D206F` 的 `push 0x2710` ReadFile | `CreatePipe + CreateProcessW` 读子进程 stdout，无关 |
| 真正 HID 读取 | `0x4E39B0` 附近异步封装（`ResetEvent` + overlapped） |
| 两处 `cmp al,0x1B` | 位于 SEH 跳表区，非音频处理 |
| exe 硬编码 HID 路径 | 无，运行时枚举；驱动内存里有全部 6 个接口路径（含 `mi_02&col01`） |

### 动态探测（句柄枚举 + 写设备）

| 实验 | 结果 |
| --- | --- |
| 纯读系统句柄表（`NtQuerySystemInformation(64)` + `DuplicateHandle` + `NtQueryObject`） | 8 个 AiMouse 进程共 ~270k 系统句柄，主进程查询到 1015 个对象名；`NtQueryObject` 正常工作（注册表/文件/命名对象均可见），但**没有任何 `248A` / `hid#` 设备句柄** → 驱动当前未持有该 HID 句柄，可能只在录音瞬间打开即关 |
| `0xFFEF` Feature 读（rid 0~4，长度 8/16/32/64/65） | 全部 `err=87`（无效参数） |
| `0xFFEF` Output 写（长度 32/33/64/65，Report ID 0/1，全零与 `0C 4D 05 61` 帧） | 全部 `err=87`；其中一次回退 WriteFile 得 `err=1` |
| `0xFFEF` Feature 写（64/65B） | `err=87` |
| 写探测期间双接口监听 | `0xFFEF` **0 条**；`0xFF91` 只有每 2 秒一次的电量心跳 `0C 4D 06 69…` / `0C 4D 05 67…` |

**结论：`0xFFEF` 虽然声明 64B 的 Input/Output/Feature 报告，但实际不接受任何
Feature/Output 操作，也没有输入数据 —— 可以排除「另一条 HID 音频通道」假设。**
驱动并未持有该设备的 HID 句柄；官方送到云端的 PCM 来源仍是通过进程间 IPC
或我们尚未观测到的瞬时读取通道。

### Frida 用户态 API hook（最终定论）

ETW 内核文件事件对 HID 无效（13.9 万事件里无任何设备路径），改用
Frida 17 只读附加 8 个 AiMouse 进程（结束自动 detach，不修改逻辑）。

| 观察 | 结论 |
| --- | --- |
| 模块 | 全部加载 `HID.DLL`、**`WINMM.dll`**、**`msc.dll`**（讯飞 SDK），**无 `hidapi.dll`** |
| 12s IO 统计 | `NtDeviceIoControlFile` 4700、`NtReadFile` 2565、`NtWriteFile` 1265 次 |
| `h=0x37C` | `\Device\DeviceApi`，IOCTL `0x470807` 的 inBuf 含 HID 接口 GUID → 设备枚举 |
| `h=0xB0C` / `0x5B4` | `mojo.50012…` 命名管道 → CEF 进程间 IPC |
| `code=0xB01A8` | HID 类 IOCTL，多个**匿名句柄**（对象名为空）轮询，返回 12B 输入状态；这解释了此前"找不到 hid# 路径" |
| `msc!QISRAudioWrite` | **0 次** → 不走本地讯飞 SDK，PCM 直接发云端 WS |

**录音瞬态**（120s 窗口，55455 条记录）：
`0x1B` 音频帧 **1528 条**，集中在按键的 5.35s 内，**全部来自同一句柄
`h=0x1124` 的 `NtReadFile`，长度 33 字节**；控制帧 `0C 4D…` 同句柄同长度。
→ **驱动读的就是我们旁听的同一种 33B 帧，"另一条音频通道"彻底排除。**

**hook 解码函数本身**（`base + 0xE6890`，验证字节 `55 8b ec 83 ec 1c b8 02…`
与反汇编完全一致）：
- 调用 **1512 次，每次 `count=56`**（正好一帧 56 样本）
- `buf` 长 **34 字节**：`predictor(2) + step_index(1) + 长度(1=28) + data(28) + pad(2)`
- `buf[2]` 的 step_index 分布 **46~51**（与官方 PCM 反推的 44~54 吻合）
- **输出 PCM 被完整抓到**

用抓到的 `buf` 跑标准 IMA 与官方输出 PCM 逐样本比对：

| 方案 | 完全一致 | 平均误差 |
| --- | --- | --- |
| **低 4 位先 + 帧内 index 自适应** | **30/30** | **0.0** |
| 低 4 位先 + 每 nibble 重置 index | 0/30 | 1142.7 |
| 高 4 位先 + 自适应 | 0/30 | 679.7 |
| 高 4 位先 + 重置 | 0/30 | 1279.3 |

→ **`aimouse_voice.py` 的解码算法 100% 正确**（它就是「低 4 位先 + 帧内
index 自适应」）。唯一差异在于**驱动喂给 decode 的 28 字节数据 ≠ HID 帧
`[5:33]` 的 28 字节**：

| | 官方 buf 数据 | 我们 HID 帧数据 |
| --- | --- | --- |
| 字节数 | 42336 | 42784 |
| 均值 | 104.2 | 122.7 |
| 低 4 位分布 | 递减型 `5248,4648,3886,2900,1802,947…`（标准语音 ADPCM） | 平台型 `3540,3438,3783,3643,1819,1651…`（2:1:2:1） |

直方图相关度仅 0.709；`^0xBE`、`^0xFF`、位反转、高低 nibble 交换均不能
对齐（相关度 -0.54 ~ 0.71）。→ 设备上报的 ADPCM 经过**非线性编码/加扰**，
驱动在送 decode 前做了还原。

### 私有加扰已定位为「按位置固定 XOR」

对**两次不同录音**的数据流按 28 个位置分别做字节直方图匹配，
每个位置都找到一个稳定的 XOR mask，相关度 **0.835~0.903**
（不异或时平均仅 0.233）。用这组近似 mask 还原 HID 数据后再解码：

| | 官方 PCM | 原始解码 | XOR 还原 |
| --- | --- | --- | --- |
| RMS | 8750~9512 | 20628 | **12010** |
| 相邻差中位 | 459~728 | 4095 | **503** ✅ |
| 饱和率 | ~1% | 24.4% | **2.2%** ✅ |
| Vosk | 可识别 | 「法」 | 「饭」 |

→ 波形统计**已还原到官方水平**，证明「XOR + 每帧独立解码」方向正确；
但直方图推得的 mask 有少量位误差，还不足以让本地 ASR 正确识别。

nibble 级精细搜索（高/低 4 位分别求 mask）得到另一组密钥，
统计同样对齐（差中位 503、饱和 2.0%），Vosk 仍为「法」——
说明仅靠边际分布无法唯一确定密钥。

**精确密钥只需一次配对采集**：同一次录音里同时抓
`NtReadFile` 的 33B 帧与 `decode()` 的 buf，逐帧算
`mask[j] = hid[5+j] XOR buf[4+j]`，看 28 个位置是否各自恒定。
采集器 `%TEMP%\frida_pair_capture.py` 已备好（JS 端用队列顺序配对，
保证帧与 buf 严格对应），随时可运行。

### 最终状态

- ✅ 云端 ASR 协议、认证、帧序列、音频格式**已完全打通并实测识别成功**
- ✅ 本地解码算法**经 Frida 逐样本验证 100% 正确**（30/30 零误差）
- ✅ 数据源已定位：`0xFF91` 的 33B `0x1B` 帧，`NtReadFile` 句柄 `0x1124`
- ✅ 私有加扰结构已定位：**按 28 位置固定的 XOR 密钥**，还原后波形统计对齐官方
- ⚠️ 精确密钥待一次配对采集（同一次录音逐帧 XOR）；拿到后即可把还原函数
  写进 `aimouse_voice.py`，实现**完全纯本地解码 + 本地 ASR**，
  不依赖云端、官方驱动或剪贴板
- 当前窗口的「云端 ASR / Vosk / 剪贴板桥接」自动降级仍是可用兜底

---

## 6. 复用方式

```python
# 本地解码
import aimouse_voice as av
samples = av.decode_frames(frames)      # list[bytes] -> list[int]
av.save_wav("voice.wav", av.normalize(samples))

# 云端识别（可选）
import aimouse_cloud_asr as ca
text = ca.transcribe_wav("voice.wav")   # 不可用时返回 None，调用方应降级

# 窗口（主界面「🎤 语音」按钮）
# python main.py -> Monster AiMouse 卡片 -> 🎤 语音
```

`websockets` 未安装时 `transcribe_wav()` 返回 `None`，窗口会自动降级到
Vosk / 剪贴板桥接，不影响录制、播放、删除与设置功能。
