# Leuco Blog Manager

Leuco Blog Manager 是用于管理 Hugo 博客内容的 PyQt6 桌面程序。当前版本把原来的单文件程序整理为可发布项目结构，并将应用代码直接放在 `src/` 下，不再额外嵌套 `src/leuco_blog_manager/` 包目录。

## 直接运行

在项目根目录执行：

```powershell
python .\run.py
```

也可以执行：

```powershell
python run
```

`run.py` 会自动把 `src/` 加入 Python 模块搜索路径。

## 安装运行

```powershell
python -m pip install -r requirements.txt
python .\run.py
```

开发模式安装：

```powershell
python -m pip install -e .
leuco-blog-manager
```

## Kali / Linux 适配

本项目已针对 Kali（及一般 Debian 系 Linux）做过深度适配，主要解决：

- 深色桌面主题下文字与背景同为白色（白字白底）的问题：启动时强制使用 Fusion 样式 + 浅色调色板，并为表格、输入框、下拉框、菜单、滚动条、进度条等所有常用控件补充显式前景/背景色；
- 中文显示为方块：Linux 下自动优先使用 Noto Sans CJK / 文泉驿等中文字体；
- 配置文件位置：Linux 下优先使用 XDG 配置目录（`~/.config/leuco-blog-manager`），已有旧配置时自动沿用，避免丢失设置与密钥；
- Hugo 端口检测：lsof 不可用时自动回退 `ss` / `fuser`，并通过 `/proc` 验证进程身份，避免误杀；
- 打开文件/网页：QDesktopServices 失败时自动回退 `xdg-open`；
- 缺少 git / hugo 时给出 Kali 的 apt 安装提示；
- 一键安装脚本会补齐 PyQt6 运行所需的 XCB、GL、DBus、中文字体等系统依赖。

在 Kali 上执行一键安装：

```bash
chmod +x scripts/install_kali.sh
./scripts/install_kali.sh
```

安装完成后开发运行：

```bash
./scripts/run_kali.sh
```

也可以直接使用虚拟环境中的命令：

```bash
source .venv/bin/activate
leuco-blog-manager
```

构建 Linux 单文件程序：

```bash
./scripts/build_linux.sh
```

产物位于 `dist/leuco-blog-manager`。安装脚本还会在应用菜单中注册 “Leuco Blog Manager” 桌面入口。

## 项目结构

```text
leuco_blog_manager_project/
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
├─ run.py
├─ run
├─ packaging/
│  ├─ LeucoBlogManager.spec
│  ├─ LeucoBlogManager_linux.spec
│  └─ leuco-blog-manager.desktop
├─ scripts/
│  ├─ run_dev.bat
│  ├─ run_dev.ps1
│  ├─ build_windows.ps1
│  ├─ install_kali.sh
│  ├─ run_kali.sh
│  └─ build_linux.sh
└─ src/
   ├─ __main__.py
   ├─ main.py
   ├─ core.py
   ├─ dialogs.py
   ├─ workers.py
   ├─ icon.ico
   ├─ icon.svg
   ├─ icon.png
   ├─ ui/
   │  ├─ main_window.py
   │  └─ mixins/
   │     ├─ ai_tools.py
   │     ├─ blog_data.py
   │     ├─ bulk_ops.py
   │     ├─ content_actions.py
   │     ├─ git_hugo.py
   │     ├─ references.py
   │     ├─ taxonomy_resources.py
   │     └─ ui.py
   ├─ prompts/
   └─ config/
```

## 模块说明

- `core.py`：常量、路径、YAML/front matter、Markdown 分片、数据模型、内容读写等公共逻辑。
- `dialogs.py`：独立弹窗、列表选择、系列排序、长篇分节、批量 slug 确认弹窗。
- `workers.py`：后台 Git worker。
- `ui/main_window.py`：`MainWindow` 主类，只保留初始化与 mixin 组合。
- `ui/mixins/*.py`：按功能域拆分主窗口方法，包括博客数据加载、引用检查、AI、批量操作、内容操作、分类资源、Git/Hugo 等。
- `prompts/`：AI 提示词资源。
- `config/`：运行时配置目录。发布包默认不包含个人 `apikey_data.bin`。

## 一键更新 slug

批量 slug 生成功能现在按“批次”向 AI 请求：

- 主界面“AI 并发”控制同时请求的批次数。
- 主界面“每批标题”控制单次请求最多包含的标题数量。
- 每批标题会带全局编号发送给 AI，程序会校验返回编号必须完全一致；编号不匹配时自动带警告重问。
- 只有所有标题都拿到有效 slug 后，才会弹出确认列表。
- 确认列表默认全部接受；可以取消勾选，也可以直接编辑新 slug。
- 通过校验后才写入 front matter 并同步替换站内 slug 引用。

## 按 slug 更改目录

执行目录重命名前，程序会先停止由本程序启动的 Hugo，并释放管理器自身可能持有的 UI 焦点、当前工作目录和短暂文件扫描引用，再通过临时改名探测检查目标内容目录是否可重命名。若目录或其中的文件被编辑器、预览窗口、Hugo watcher、资源管理器或其他外部进程占用，程序会提示被占用目录并取消整个批量更改，避免部分改名后再回滚。

## 长篇分节

长篇分节弹窗会统计每个一级标题的字数，并在用户设置分节数量后自动按一级标题顺序做字数均衡分配，尽量让各节总字数接近。用户仍可在弹窗中手动调整每个一级标题所属节。

## 默认博客地址

默认博客地址为 `https://leuco-yuu.github.io/`。新选择博客目录时也会自动回到该地址；仍可在主界面手动修改并保存。

## 图标

项目内置简约深色程序图标，资源位于 `src/icon.ico`、`src/icon.svg` 和 `src/icon.png`。打包 Windows EXE 时会使用 `src/icon.ico` 作为应用图标。

## 打包 Windows EXE

```powershell
.\scripts\build_windows.ps1
```

产物会生成在 `dist/` 目录。PyInstaller spec 会把 `src/prompts`、`src/config/config.example.json` 和图标资源打进程序。

## 配置与密钥

- 开发运行时配置文件位置：`src/config/config.json`。
- 示例配置：`src/config/config.example.json`。
- `apikey_data.bin` 不应提交到仓库或发布包。

## 检查

重组版本已通过 Python 语法编译检查。GUI 完整运行仍依赖本地 PyQt6、Hugo、Git、AI 接口以及你的博客目录环境。
