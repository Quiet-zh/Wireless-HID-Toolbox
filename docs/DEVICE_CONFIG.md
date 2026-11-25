# 设备配置与删除

配置文件：

```text
%APPDATA%\ExtBatteryTray\config.json
```

## devices 字段

```json
{
  "devices": {
    "3554:F517": {
      "name": "EWEADN 8K",
      "kind": "mouse",
      "show": true,
      "tray": true,
      "order": 10
    },
    "36B0:WAVE75": {
      "name": "PMO WAVE75",
      "kind": "keyboard",
      "show": true,
      "tray": true,
      "order": 20
    },
    "248A:60AB": {
      "name": "魔声 AI 垂直鼠标",
      "kind": "mouse",
      "show": true,
      "tray": true,
      "order": 25
    },
    "1EA7:0064": {
      "name": "英菲克 F15 无线鼠标",
      "kind": "mouse",
      "show": true,
      "tray": true,
      "order": 30
    },
    "1A2C:7FFF": {
      "name": "狼蛛 S99 三模键盘",
      "kind": "keyboard",
      "show": true,
      "tray": true,
      "order": 40
    }
  }
}
```

`248A:60AB` 是本机实测的魔声 AI 垂直鼠标（2.4G，VID `0x248A` Maxxter /
PID `0x60AB`，旧显示名 Monster AiMouse）。它已登记在设备目录里，面板、托盘和
鼠标测试面板都能识别；已有配置里的旧名字会在启动时自动迁移为新名字。

电量通过私有 `0xFF91` 接口被动监听（约 2.5 秒一帧）：带电量帧
`0C 4D ?? 69 00 <电量> 04 01 00 4C` 的偏移 5 即百分比；心跳帧
`0C 4D 05 67 00 4C ...` 不含电量，解析时必须排除。该协议为**实验性**，
按当前实测约 100% 校准，仅在 `248A:60AB` 上启用；鼠标休眠时回退到上次缓存。

`1EA7:0064` 是英菲克 F15 无线鼠标（VID `0x1EA7` SHARKOON Technologies GmbH /
PID `0x0064`），`1A2C:7FFF` 是狼蛛 S99 三模键盘（VID `0x1A2C` China Resource
Semico Co., Ltd / PID `0x7FFF`，产品名 `2.4G Wireless Device`，2.4G 连接）。
两台设备已登记到设备目录，面板、托盘和鼠标键盘测试面板都能按名称和类型识别；
但尚未收录私有电量协议，HID 在线时显示「在线 · 无电量协议」和 `--`，不再误报
「未连接」。如果设备暴露标准 Battery Strength Usage，`generic_protocols.py`
的 `read_standard()` 会自动读到；
否则需要在官方驱动开启时用 HID 调试台抓包，把报文偏移写入 `captured.json`
或新增协议读取函数后再显示电量。加入 `SPECS` 之前不会尝试读取这两台设备。

- `kind`：`mouse` / `keyboard`，设置界面显示为“鼠标/键盘”
- `show`：主面板是否显示卡片
- `tray`：是否显示托盘图标
- `order`：列表排序

## 修改类型

设置 → 设备列表 → 下拉选择“鼠标/键盘”。

保存后 `kind` 写入配置，用于明确设备归类；不会改变实际 HID 扫描到的接口。

## 删除设备

设置 → 设备列表 → 删除。

删除采用软删除：

```json
"046D:C53F": {
  "deleted": true,
  "show": false,
  "tray": false
}
```

- 设置列表不再显示
- 主面板卡片和托盘图标同步移除
- 扫描时不会自动恢复
- 点「恢复已删除」清除 `deleted`，并恢复 `show/tray`

删除不会卸载驱动，也不会写入设备固件。
