# tools/ — 独立验证工具

本目录放**不参与运行时、可单独执行**的验证/研究脚本，
项目主程序不会导入它们，也不依赖这里的内容。

| 脚本 | 用途 | 依赖 |
| --- | --- | --- |
| `verify_local_decode.py` | 用 4 条真实 HID 帧验证 XOR 密钥 + 跨帧连续 IMA 解码，打印波形统计 | **零第三方依赖** |

```bat
python tools\verify_local_decode.py
```

输出应包含 `✅ 纯本地解码链路验证通过`，
以及 28 字节 XOR 密钥、224 个解码样本、前 12 个样本的期望值。

## 关于逆向研究脚本

完整逆向过程（Frida API hook、句柄枚举、逐帧配对求密钥、
ETW 采集、云端协议重放）记录在
[docs/AiMouse-RE-Notes.md](../docs/AiMouse-RE-Notes.md)。

那些一次性研究脚本需要 Frida / 管理员权限 / 官方驱动正在运行，
且路径依赖本机临时目录，**不适合放进仓库**，因此只保留方法学与
结论文档；如需复现，按逆向笔记里的步骤重建即可。

项目内等价的可复现验证已由 `verify_local_decode.py` 与
`tests/test_local_decode.py` 覆盖（两者都用同一组真实帧 fixture）。
