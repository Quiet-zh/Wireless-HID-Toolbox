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
PID `0x60AB`）。它已经登记在设备目录里，面板、托盘和鼠标测试面板都能识别；
但电量走私有 `0xFF91` 接口，没有标准电量 Usage，当前只显示设备占位，
不会显示百分比。需要抓包确认报文后，才能通过 `captured.json` 或新增协议
读取函数接上电量。

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
