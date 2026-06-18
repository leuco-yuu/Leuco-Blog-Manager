from core import *
from dialogs import *
from workers import *


class UiMixin:
    def build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        self.setCentralWidget(central)

        header_row = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel("Leuco Blog 内容工作台")
        title.setObjectName("Title")
        subtitle = QLabel("文章、项目、分片正文、分类法、资源、AI、Hugo 与 Git 的统一管理。")
        subtitle.setObjectName("Subtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_row.addLayout(header_text)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        top = self.card()
        grid = QGridLayout(top)
        grid.setContentsMargins(5, 4, 5, 4)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        self.root_edit = QLineEdit(str(self.cfg.root))
        browse_btn = QPushButton("选择目录")
        reload_btn = QPushButton("刷新")
        self.hugo_btn = QPushButton("启动 Hugo")
        self.hugo_btn.setMinimumWidth(76)

        configured_url = self.app_config["blog_url"].strip() or BLOG_SITE_URL
        self.blog_url_edit = QLineEdit(configured_url or BLOG_SITE_URL)
        self.blog_url_edit.setPlaceholderText(BLOG_SITE_URL)
        save_url_btn = QPushButton("保存地址")
        open_url_btn = QPushButton("打开博客")

        self.api_base_edit = QLineEdit(self.app_config["api_base_url"])
        self.api_model_edit = QLineEdit(self.app_config["api_model"])
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("apikey_data.bin 的解密密码")
        self.api_key_edit.setClearButtonEnabled(True)
        login_btn = QPushButton("登录")

        self.git_remote_edit = QLineEdit(self.app_config["git_remote"] or "origin")
        self.git_branch_edit = QLineEdit(self.app_config["git_branch"] or "main")
        self.git_rebase_check = QCheckBox("rebase")
        self.git_rebase_check.setChecked(self.app_config.get_bool("git_rebase", True))
        self.git_autostash_check = QCheckBox("autostash")
        self.git_autostash_check.setChecked(self.app_config.get_bool("git_autostash", True))
        pull_btn = QPushButton("拉取远端")
        commit_content_btn = QPushButton("提交内容")
        commit_all_btn = QPushButton("提交整站")

        browse_btn.clicked.connect(self.choose_blog_root)
        reload_btn.clicked.connect(self.refresh_blog)
        self.hugo_btn.clicked.connect(self.toggle_hugo)
        save_url_btn.clicked.connect(self.save_blog_url)
        open_url_btn.clicked.connect(self.open_blog_url)
        login_btn.clicked.connect(self.login_api_key)
        self.api_key_edit.returnPressed.connect(self.login_api_key)
        pull_btn.clicked.connect(self.pull_remote)
        commit_content_btn.clicked.connect(lambda: self.commit("commit-content"))
        commit_all_btn.clicked.connect(lambda: self.commit("commit-all"))

        grid.addWidget(QLabel("博客目录"), 0, 0)
        grid.addWidget(self.root_edit, 0, 1, 1, 5)
        grid.addWidget(browse_btn, 0, 6)
        grid.addWidget(reload_btn, 0, 7)
        grid.addWidget(self.hugo_btn, 0, 8)

        grid.addWidget(QLabel("博客地址"), 1, 0)
        grid.addWidget(self.blog_url_edit, 1, 1, 1, 5)
        grid.addWidget(save_url_btn, 1, 6)
        grid.addWidget(open_url_btn, 1, 7, 1, 2)

        grid.addWidget(QLabel("AI Base"), 2, 0)
        grid.addWidget(self.api_base_edit, 2, 1, 1, 2)
        grid.addWidget(QLabel("Model"), 2, 3)
        grid.addWidget(self.api_model_edit, 2, 4)
        grid.addWidget(QLabel("登录密码"), 2, 5)
        grid.addWidget(self.api_key_edit, 2, 6, 1, 2)
        grid.addWidget(login_btn, 2, 8)

        grid.addWidget(QLabel("Git Remote"), 3, 0)
        grid.addWidget(self.git_remote_edit, 3, 1)
        grid.addWidget(QLabel("远程分支"), 3, 2)
        grid.addWidget(self.git_branch_edit, 3, 3)
        grid.addWidget(self.git_rebase_check, 3, 4)
        grid.addWidget(self.git_autostash_check, 3, 5)
        grid.addWidget(pull_btn, 3, 6)
        grid.addWidget(commit_content_btn, 3, 7)
        grid.addWidget(commit_all_btn, 3, 8)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(4, 2)
        grid.setColumnStretch(6, 1)
        layout.addWidget(top)

        status_row = QHBoxLayout()
        self.status = QLabel("准备读取博客……")
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.setVisible(False)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.progress)
        layout.addLayout(status_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.tabs = QTabWidget()
        self.post_table = self.make_content_table("post")
        self.project_table = self.make_content_table("project")
        self.resource_tree = QTreeWidget()
        self.resource_tree.setHeaderLabels(["资源", "路径"])
        self.resource_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.resource_tree.customContextMenuRequested.connect(self.open_resource_menu)
        self.resource_tree.itemDoubleClicked.connect(lambda item, col: self.open_resource_item(item))
        self.tabs.addTab(self.wrap_table(self.post_table, "post"), "文章列表")
        self.tabs.addTab(self.wrap_table(self.project_table, "project"), "项目列表")
        self.tabs.addTab(self.resource_tree, "资源/主题")
        splitter.addWidget(self.tabs)

        side = self.card()
        side.setMinimumWidth(220)
        side_layout = QVBoxLayout(side)
        self.tax_tabs = QTabWidget()
        self.category_list = self.make_taxonomy_list("category")
        self.series_list = self.make_taxonomy_list("series")
        self.tag_list = self.make_taxonomy_list("tag")
        self.tax_tabs.addTab(self.category_list, "分类")
        self.tax_tabs.addTab(self.series_list, "系列")
        self.tax_tabs.addTab(self.tag_list, "标签")
        side_layout.addWidget(self.tax_tabs)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([820, 220])

    def compact_action_button(self, text: str, tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("CompactButton")
        if tooltip:
            button.setToolTip(tooltip)
        return button

    def wrap_table(self, table: QTableWidget, kind: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 1)
        toolbar.setSpacing(3)

        add_btn = self.compact_action_button("新建文章" if kind == "post" else "新建项目")
        random_date_btn = self.compact_action_button("随机化创建时间")
        random_lastmod_btn = self.compact_action_button("随机化最近修改")
        slug_btn = self.compact_action_button("一键更新 slug")
        section_order_btn = self.compact_action_button(
            "写入分片顺序",
            "扫描数字开头的 Markdown 分片，并按序号写入 sections 字段",
        )
        rename_btn = self.compact_action_button("按 slug 更改目录")
        check_refs_btn = self.compact_action_button("检查引用")

        add_btn.clicked.connect(lambda: self.new_content(kind))
        random_date_btn.clicked.connect(lambda: self.randomize_creation_times(kind))
        random_lastmod_btn.clicked.connect(lambda: self.randomize_lastmod_times(kind))
        slug_btn.clicked.connect(lambda: self.bulk_update_slugs(kind))
        section_order_btn.clicked.connect(lambda: self.insert_section_orders(kind))
        rename_btn.clicked.connect(lambda: self.rename_content_directories(kind))
        check_refs_btn.clicked.connect(self.check_references)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(random_date_btn)
        toolbar.addWidget(random_lastmod_btn)
        toolbar.addWidget(slug_btn)
        toolbar.addWidget(section_order_btn)
        toolbar.addWidget(rename_btn)
        toolbar.addWidget(check_refs_btn)
        toolbar.addSpacing(2)
        toolbar.addWidget(QLabel("AI 并发"))
        concurrency = QSpinBox()
        concurrency.setRange(1, 100)
        try:
            concurrency.setValue(max(1, min(100, int(self.app_config["slug_concurrency"] or "20"))))
        except ValueError:
            concurrency.setValue(20)
        concurrency.setMinimumWidth(76)
        concurrency.valueChanged.connect(self.save_slug_concurrency)
        if kind == "post":
            self.post_slug_concurrency = concurrency
        else:
            self.project_slug_concurrency = concurrency
        toolbar.addWidget(concurrency)

        toolbar.addWidget(QLabel("每批标题"))
        batch_size = QSpinBox()
        batch_size.setRange(1, 500)
        try:
            batch_size.setValue(max(1, min(500, int(self.app_config["slug_batch_size"] or "40"))))
        except ValueError:
            batch_size.setValue(40)
        batch_size.setMinimumWidth(76)
        batch_size.valueChanged.connect(self.save_slug_batch_size)
        if kind == "post":
            self.post_slug_batch_size = batch_size
        else:
            self.project_slug_batch_size = batch_size
        toolbar.addWidget(batch_size)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        layout.addWidget(table, 1)
        return box

    def make_content_table(self, kind: str) -> QTableWidget:
        if kind == "post":
            headers = ["标题", "slug", "草稿", "首页", "分类", "系列（序号）", "标签", "摘要", "路径", "日期", "最后修改"]
        else:
            headers = ["标题", "slug", "草稿", "精选", "状态", "分类", "标签", "摘要", "路径", "日期", "最后修改"]
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, k=kind, t=table: self.open_content_menu(k, t, pos))
        table.cellClicked.connect(
            lambda row, col, k=kind, t=table: self.handle_content_cell_click(k, t, row, col)
        )
        table.cellDoubleClicked.connect(
            lambda row, col, k=kind, t=table: self.open_selected_content(k, t, row, col)
        )
        return table

    def make_taxonomy_list(self, kind: str) -> QListWidget:
        lw = QListWidget()
        lw.setSpacing(0)
        lw.setUniformItemSizes(False)
        lw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lw.customContextMenuRequested.connect(lambda pos, k=kind, w=lw: self.open_taxonomy_menu(k, w, pos))
        lw.itemDoubleClicked.connect(lambda item, k=kind: self.toggle_filter(k, item.data(Qt.ItemDataRole.UserRole)))
        return lw

    def card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        return frame

    def apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background: #f8fafc; }
            QLabel#Title { font-size: 18px; font-weight: 800; color: #0f172a; }
            QLabel#Subtitle { color: #64748b; }
            QFrame#Card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; }
            QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: white; }
            QTabBar::tab { padding: 4px 8px; margin-right: 3px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: white; color: #1d4ed8; font-weight: 700; }
            QTabBar::tab:!selected { background: #e2e8f0; color: #475569; }
            QHeaderView::section { background: #f1f5f9; color: #334155; border: 0; border-bottom: 1px solid #dbe3ef; padding: 3px 5px; font-weight: 700; }
            QTableWidget, QListWidget, QTreeWidget, QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {
                background: white; border: 1px solid #dbe3ef; border-radius: 6px; padding: 2px; selection-background-color: #dbeafe; selection-color: #0f172a;
            }
            QPushButton { background: #2563eb; color: white; border: 0; border-radius: 6px; padding: 4px 7px; font-weight: 600; }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton#CompactButton { padding: 3px 5px; }
            QMenu { background: white; border: 1px solid #dbe3ef; border-radius: 8px; }
            QMenu::item { padding: 4px 18px 4px 12px; }
            QMenu::item:selected { background: #dbeafe; color: #1d4ed8; }
        """)

    def update_progress_visibility(self) -> None:
        active = self._sync_busy_depth > 0 or self._git_busy or self._hugo_starting or self._bulk_busy
        self.progress.setVisible(active)

    @contextmanager
    def waiting(self, message: str):
        """为同步等待操作显示主界面不定进度条和等待光标。"""
        self._sync_busy_depth += 1
        self.set_status(message)
        self.update_progress_visibility()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()
            self._sync_busy_depth = max(0, self._sync_busy_depth - 1)
            self.update_progress_visibility()
            QApplication.processEvents()
