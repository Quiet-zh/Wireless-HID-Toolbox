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
      "name": "Monster AiMouse",
      "kind": "mouse",
      "show": true,
      "tray": true,
      "order": 25
    }
  }
}
```

`248A:60AB` 是本机实测的 Monster 人体工学鼠标（2.4G，VID `0x248A` Maxxter /
PID `0x60AB`，产品名 AiMouse）。它已登记在设备目录里，面板、托盘和鼠标测试
面板都能识别。

电量通过私有 `0xFF91` 接口被动监听（约 2.5 秒一帧）：带电量帧
`0C 4D ?? 69 00 <电量> 04 01 00 4C` 的偏移 5 即百分比；心跳帧
`0C 4D 05 67 00 4C ...` 不含电量，解析时必须排除。该协议为**实验性**，
按当前实测约 100% 校准，仅在 `248A:60AB` 上启用；鼠标休眠时回退到上次缓存。

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
