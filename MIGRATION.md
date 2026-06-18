# 结构迁移说明

原单文件程序已拆分为发布项目结构。当前版本采用扁平 `src/` 布局：业务模块直接位于 `src/` 下，不再使用 `src/leuco_blog_manager/` 二级包目录。

## 对应关系

- 顶层工具函数、数据类、内容解析与写入：`src/core.py`
- `GitWorker`：`src/workers.py`
- 各类 `QDialog`：`src/dialogs.py`
- `MainWindow.__init__`：`src/ui/main_window.py`
- `MainWindow` 其余方法：`src/ui/mixins/*.py`
- AI 提示词：`src/prompts/*.txt`
- 运行配置：`src/config/`

## 本轮功能变更

- 一键更新 slug 改为批量编号请求 AI，并按编号校验响应。
- 新增“每批标题”设置，和“AI 并发”共同控制批量请求。
- 新增批量 slug 审核弹窗，默认全选，可取消或编辑。
- 所有提示词已重新整理为更严格的输出格式。
- 按 slug 更改目录前增加目录占用探测，发现占用即禁止批量改名。
- 目录改名前会释放管理器自身可能持有的临时目录引用，减少自身 UI/当前工作目录导致的误报占用。
- 长篇分节改为按一级标题字数自动均衡分配，仍允许手动调整。
- 新增并接入 `src/icon.ico`、`src/icon.svg`、`src/icon.png` 程序图标。
- 默认博客地址固定为 `https://leuco-yuu.github.io/`。

## 个人文件

上传包中的个人配置和 `apikey_data.bin` 不应进入发布包。需要保留本机 API Key 时，请在本地运行程序后重新登录，或手动复制到 `src/config/`。
