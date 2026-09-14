# astrbot_plugin_file_explorer

在 AstrBot WebUI 里提供类似 [NapCat](https://github.com/NapNeko/NapCatQQ) 的可视化文件管理器。

灵感来自 NapCat WebUI 的 File Management 页面，用 AstrBot 插件 Pages / Dashboard 路由实现，不修改 AstrBot 本体。

## 功能

- 浏览目录、面包屑导航、当前目录筛选
- 上传（按钮 / 拖拽）、下载（支持选中文件夹打包为 .zip 下载）
- 新建文件夹、新建文本文件
- 重命名、复制、剪切、粘贴、删除
- 文本在线预览与保存，图片预览
- 快捷目录：数据目录、插件、配置、日志、临时文件、工作区
- 默认沙盒在 AstrBot `data/` 内，可配置额外根目录；可选放开整个文件系统

## 打开方式

1. 先登录 AstrBot WebUI。
2. 浏览器打开：`http://<WebUI主机>:<端口>/file-manager/`
3. 管理员也可发指令 `/文件管理` 获取地址。
4. AstrBot 新版本若已支持插件 Pages：`插件 → 文件管理器 → Pages → explorer`

当前 AstrBot 4.3.x 没有官方 Pages 入口，插件会把页面挂到 `/file-manager/`，并复用你登录 WebUI 时保存在浏览器里的 Token。

## 配置

在 WebUI 插件配置中：

| 项 | 说明 |
| --- | --- |
| 额外允许访问的根目录 | 绝对路径列表 |
| 允许浏览整个文件系统 | 危险。开启后可从盘符 / 系统根目录进入 |
| 显示隐藏文件 | 显示以 `.` 开头的文件 |
| 单文件上传大小上限 | 同时受 Dashboard 最大请求体限制（默认 128MB） |
| 在线预览大小上限 | 超限的文本请下载后查看 |

## 安全

- 所有路径都会解析后校验，禁止逃出允许的根目录
- WebUI 接口走 Dashboard 鉴权（需登录）
- 删除根目录本身会被拒绝
- 不建议在公网暴露 WebUI 时开启「整个文件系统」

## 安装

把本目录放到 `AstrBot/data/plugins/astrbot_plugin_file_explorer/`，然后在 WebUI 重载插件。

无第三方 Python 依赖。

## 作者

Elara · https://github.com/ElaraKaya
