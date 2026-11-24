# 主题说明

## 使用

主面板右上角：

- 黑夜模式显示 `☀ 白天`，点击切到白天
- 白天模式显示 `🌙 黑夜`，点击切到黑夜

选择写入：

```json
{ "theme": "dark" }
```

默认 `dark`。

## 覆盖范围

- 主面板、设备卡片、底部工具栏
- 设置窗口、内置协议表
- 鼠标键盘测试（鼠标页/键盘页/Canvas 按键图）
- HID 调试台（Treeview、Notebook、输入框、日志区）
- 已打开的独立工具窗口：1 秒内自动跟随

## 实现方式

`theme.py` 保存两套映射：

- `PANEL_LIGHT`：主面板深色 → 浅色
- `PANEL_DARK`：反向
- `TOOL_DARK`：工具窗口浅色 → 深色
- `TOOL_LIGHT`：反向

切换时：

1. 递归遍历 Tk 控件，按 `background` / `foreground` / `active*` 等选项换色
2. Canvas 图元按 `fill` / `outline` 换色
3. ttk 样式单独配置 `Treeview` / `Notebook` / `Combobox` / `Scrollbar`
4. 工具窗口通过 `theme.setup(root, "tool")` 轮询配置，实现打开状态下自动跟随

## 新增颜色时

如果新增了硬编码颜色：

1. 把“浅色 → 深色”加到 `TOOL_DARK`
2. 把“深色 → 浅色”加到 `PANEL_LIGHT`
3. 在 `tests/test_theme.py` 增加主色覆盖断言
4. 两种主题下手工检查文字对比度

不要只改一个方向，否则切回原主题会残留错误颜色。

## 已知取舍

- 原生标题栏由 Windows 控制，不跟随应用主题
- Canvas 中白色文字/白色按键共用同一颜色键，动态重绘逻辑单独处理键盘高亮
- 个别 ttk 原生控件在 Windows 主题下可能保留系统边框
