# 打包说明

## 环境

```bat
python -m pip install -r requirements-build.txt
```

PyInstaller 只用于打包；程序运行本身仍然零第三方依赖。

## 默认：onefile 单文件

```bat
build_exe.bat
```

无参数运行会提示：

```text
[1] onefile 单文件（默认，分发方便）
[2] onedir 文件夹（启动更快，不需要解压）
```

默认直接回车即 onefile。

产物：

```text
dist\WirelessHIDToolbox.exe
```

首次启动会解压到临时目录，启动比 onedir 稍慢；分发只需这一个 exe。

## 选择模式

```bat
build_exe.bat onefile
build_exe.bat onedir
build_exe.bat 1
build_exe.bat 2
```

### onefile

- 产物：`dist\WirelessHIDToolbox.exe`
- 适合直接发给别人
- 需要系统临时目录可写

### onedir

- 产物：`dist\WirelessHIDToolbox\WirelessHIDToolbox.exe`
- 启动更快，不需要每次解压
- 分发时整个 `dist\WirelessHIDToolbox` 文件夹一起打包

## 打包内容

- `main.py` 统一入口
- `app.ico` 图标
- `version_info.txt` Windows 版本资源（当前 v1.23.1）
- `--optimize 2`
- 排除 unittest/doctest/pydoc/pdb/test
- 隐藏导入：面板、托盘、鼠标键盘测试、HID 调试台、主题、协议模块

## 可选：把识别引擎一起打包

默认打包**不含**任何识别引擎——exe 里没有 vosk / sherpa-onnx 时语音窗口
仍能录音、播放、导出 WAV，只是不转文字（面板会提示原因）。

想把引擎一起打包，先装依赖再打包：

```bat
python -m pip install sherpa-onnx
build_exe.bat
```

注意：

- `sherpa-onnx` 是 C 扩展 + onnxruntime，PyInstaller 需要显式收集：
  `--collect-all sherpa_onnx`（或 `hiddenimports` 里加 `sherpa_onnx`），
  否则 exe 启动时报找不到 `_sherpa_onnx` / onnxruntime 的 dll
- 体积会明显变大（sherpa-onnx 自带 onnxruntime，约 +30~80MB，视平台而定）
- **模型不要打进 exe**：`sherpa_model_dir` 默认指向
  `%APPDATA%\ExtBatteryTray\models`，让用户跑 `tools\download_models.py`
  单独下载即可（流式 226MB + 整段 229MB，打进去会让 exe 变成几百 MB）
- vosk 回退路径同理：只装 `vosk` 不打包模型

## exe 行为

- 双击 exe 默认打开主显示界面
- 工具通过 `exe --tool mouse-test` / `--tool hid-debug` / `--tool tray` 打开
- 开机自启、桌面入口在 exe 模式下指向 exe 本身
- 设置中的测试/调试工具不依赖外部 `.py`

## 验证清单

```bat
dist\WirelessHIDToolbox.exe
dist\WirelessHIDToolbox.exe --tool mouse-test
dist\WirelessHIDToolbox.exe --tool hid-debug
```

- [ ] 标题显示 `外设电量 v1.23.1`
- [ ] 主面板、设置、协议表可打开
- [ ] 鼠标键盘测试和 HID 调试台可打开
- [ ] 托盘启动/退出正常
- [ ] 主题按钮可用

## 常见问题

### onefile 提示 “Could not create temporary directory”

系统临时目录不可写或被安全软件拦截。改用：

```bat
build_exe.bat onedir
```

### 旧版本文件残留

```bat
rmdir /s /q build dist
build_exe.bat
```

或使用脚本自带的 `--clean`。

### 杀毒软件误报

PyInstaller 单文件自解压容易被启发式误报。可改用 onedir，或对 exe 做代码签名。

