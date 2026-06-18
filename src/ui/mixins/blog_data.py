from core import *
from dialogs import *
from workers import *


class BlogDataMixin:
    def last_browse_dir(self) -> Path:
        raw = self.app_config["last_browse_dir"] or str(Path.home())
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            candidate = candidate.parent
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate if candidate.is_dir() else Path.home()

    def remember_browse_path(self, selected: str | Path) -> None:
        path = Path(selected).expanduser()
        folder = path if path.is_dir() else path.parent
        if folder.is_dir():
            self.app_config["last_browse_dir"] = str(folder.resolve())

    def select_file(self, parent: QWidget, title: str, file_filter: str) -> str:
        path, _ = QFileDialog.getOpenFileName(
            parent,
            title,
            str(self.last_browse_dir()),
            file_filter,
        )
        if path:
            self.remember_browse_path(path)
        return path

    def select_directory(self, parent: QWidget, title: str) -> str:
        path = QFileDialog.getExistingDirectory(
            parent,
            title,
            str(self.last_browse_dir()),
        )
        if path:
            self.remember_browse_path(path)
        return path

    def choose_blog_root(self) -> None:
        path = self.select_directory(self, "选择 Leuco Blog 根目录")
        if not path:
            return
        self.root_edit.setText(path)
        self.app_config["blog_root"] = path
        self.cfg.root = Path(path)
        self.blog_url_edit.setText(BLOG_SITE_URL)
        self.app_config["blog_url"] = BLOG_SITE_URL
        self.load_blog()

    def normalized_blog_url(self) -> str:
        raw = self.blog_url_edit.text().strip()
        if not raw:
            raise ValueError("请输入博客地址。")
        url = QUrl.fromUserInput(raw)
        if not url.isValid() or not url.scheme() or not url.host():
            raise ValueError("博客地址无效，请输入完整的 http:// 或 https:// 地址。")
        normalized = url.toString()
        if not normalized.endswith("/"):
            normalized += "/"
        return normalized

    def save_blog_url(self) -> None:
        try:
            url = self.normalized_blog_url()
            with self.waiting("正在更新 Hugo 博客地址……"):
                write_hugo_base_url(Path(self.root_edit.text().strip()), url)
                self.blog_url_edit.setText(url)
                self.app_config["blog_url"] = url
            self.mark_modified(True)
            self.set_status(f"博客地址已更新：{url}")
        except Exception as exc:
            QMessageBox.critical(self, "博客地址保存失败", str(exc))

    def open_blog_url(self) -> None:
        try:
            url = self.normalized_blog_url()
        except ValueError as exc:
            QMessageBox.warning(self, "博客地址无效", str(exc))
            return
        QDesktopServices.openUrl(QUrl(url))

    def save_slug_concurrency(self, value: int) -> None:
        value = max(1, min(100, int(value)))
        self.app_config["slug_concurrency"] = value
        other = getattr(self, "project_slug_concurrency", None)
        sender = self.sender()
        if other is not None and sender is not other and other.value() != value:
            other.blockSignals(True)
            other.setValue(value)
            other.blockSignals(False)
        other = getattr(self, "post_slug_concurrency", None)
        if other is not None and sender is not other and other.value() != value:
            other.blockSignals(True)
            other.setValue(value)
            other.blockSignals(False)

    def save_slug_batch_size(self, value: int) -> None:
        value = max(1, min(500, int(value)))
        self.app_config["slug_batch_size"] = value
        other = getattr(self, "project_slug_batch_size", None)
        sender = self.sender()
        if other is not None and sender is not other and other.value() != value:
            other.blockSignals(True)
            other.setValue(value)
            other.blockSignals(False)
        other = getattr(self, "post_slug_batch_size", None)
        if other is not None and sender is not other and other.value() != value:
            other.blockSignals(True)
            other.setValue(value)
            other.blockSignals(False)

    def validate_root(self) -> bool:
        root = Path(self.root_edit.text().strip())
        if not (root / ".git").exists() or not (root / "hugo.yaml").exists() or not (root / "content" / "posts").exists():
            QMessageBox.warning(self, "目录不正确", f"这不像 Leuco Blog 根目录：\n{root}")
            return False
        self.cfg.root = root
        self.app_config["blog_root"] = str(root)
        return True

    def refresh_blog(self) -> None:
        self.load_blog(cleanup_unused_tags=True)

    def cleanup_unused_tags(self) -> int:
        """删除没有被任何文章或项目引用的标签目录。"""
        used = {
            tag.casefold()
            for record in self.posts + self.projects
            for tag in record.tags
            if tag.strip()
        }
        root = self.cfg.taxonomy_root("tag")
        if not root.exists():
            return 0

        removed = 0
        for folder in list(root.iterdir()):
            if not folder.is_dir():
                continue
            record = parse_taxonomy(folder, "tag")
            keys = {record.name.casefold(), record.title.casefold()}
            if used.isdisjoint(keys):
                shutil.rmtree(folder)
                removed += 1
                if self.active_filter and self.active_filter[0] == "tag" and self.active_filter[1].casefold() in keys:
                    self.active_filter = None
        return removed

    def load_blog(self, cleanup_unused_tags: bool = False) -> None:
        if not self.validate_root():
            return

        removed_tags = 0
        self.content_load_warnings = []
        FRONT_MATTER_AUTO_REPAIRS.clear()

        try:
            with self.waiting("正在读取博客内容……"):
                self.posts = self.discover_content("post")
                self.projects = self.discover_content("project")

                # 如果存在无法解析的内容，不能清理标签，否则可能把错误文件仍在使用的标签误删。
                if cleanup_unused_tags and not self.content_load_warnings:
                    removed_tags = self.cleanup_unused_tags()
                    if removed_tags:
                        self.mark_modified(True)

                for kind in ["category", "series", "tag"]:
                    self.taxonomies[kind] = self.discover_taxonomies(kind)

                self.populate_all()
                branch = run_cmd(
                    ["git", "branch", "--show-current"],
                    cwd=self.cfg.root,
                    timeout=30,
                ).strip() or "main"
                dirty = (
                    "；存在未提交修改"
                    if run_cmd(
                        ["git", "status", "--porcelain"],
                        cwd=self.cfg.root,
                        timeout=30,
                    ).strip()
                    else ""
                )

            cleanup_text = (
                f"；已清理 {removed_tags} 个未使用标签"
                if cleanup_unused_tags and removed_tags
                else ""
            )
            repair_text = (
                f"；自动修复 {len(FRONT_MATTER_AUTO_REPAIRS)} 个含 Tab 的头数据"
                if FRONT_MATTER_AUTO_REPAIRS
                else ""
            )
            warning_text = (
                f"；跳过 {len(self.content_load_warnings)} 个头数据错误文件"
                if self.content_load_warnings
                else ""
            )
            cleanup_skipped_text = (
                "；因存在头数据错误，已跳过未使用标签清理"
                if cleanup_unused_tags and self.content_load_warnings
                else ""
            )

            self.set_status(
                f"已读取：{len(self.posts)} 篇文章，{len(self.projects)} 个项目，"
                f"分支 {branch}{dirty}{cleanup_text}{repair_text}"
                f"{warning_text}{cleanup_skipped_text}。"
            )

            if self.content_load_warnings:
                shown = self.content_load_warnings[:8]
                remaining = len(self.content_load_warnings) - len(shown)
                message = (
                    "下列文件的 YAML 头数据存在语法错误，程序已跳过这些文件，"
                    "其余内容仍可正常使用。\n\n"
                    + "\n\n".join(shown)
                )
                if remaining > 0:
                    message += f"\n\n另外还有 {remaining} 个错误文件未在此处展开。"
                QMessageBox.warning(self, "部分内容读取失败", message)

        except Exception:
            self.set_status("读取博客失败。")
            QMessageBox.critical(self, "读取失败", safe_traceback())

    def discover_content(self, kind: str) -> List[ContentRecord]:
        root = self.cfg.posts if kind == "post" else self.cfg.projects
        records: List[ContentRecord] = []
        for path in sorted(root.glob("*/index.md"), key=lambda item: str(item).casefold()):
            if path.parent.name.startswith(".__lbm_tmp_"):
                continue
            try:
                records.append(parse_content(path, kind))
            except FrontMatterParseError as exc:
                self.content_load_warnings.append(str(exc))
        records.sort(key=lambda r: (r.date, r.title), reverse=True)
        return records

    def discover_taxonomies(self, kind: str) -> List[TaxonomyRecord]:
        root = self.cfg.taxonomy_root(kind)
        if not root.exists():
            return []
        out: List[TaxonomyRecord] = []
        for folder in sorted(
            (path for path in root.iterdir() if path.is_dir()),
            key=lambda item: item.name.casefold(),
        ):
            try:
                out.append(parse_taxonomy(folder, kind))
            except FrontMatterParseError as exc:
                self.content_load_warnings.append(str(exc))
        out.sort(key=lambda r: r.title.casefold())
        return out

    def populate_all(self) -> None:
        self.populate_content("post")
        self.populate_content("project")
        self.populate_taxonomies()
        self.populate_resources()

    def content_records(self, kind: str) -> List[ContentRecord]:
        records = self.posts if kind == "post" else self.projects
        if not self.active_filter:
            return records
        filter_kind, value = self.active_filter
        key = value.casefold()
        if filter_kind == "category":
            return [r for r in records if any(x.casefold() == key for x in r.categories)]
        if filter_kind == "tag":
            return [r for r in records if any(x.casefold() == key for x in r.tags)]
        if filter_kind == "series":
            return [r for r in records if any(x.casefold() == key for x in r.series)]
        return records

    def format_series_orders(self, rec: ContentRecord) -> str:
        orders = parse_series_orders(rec.series_order, len(rec.series))
        parts = []
        for index, name in enumerate(rec.series):
            order = orders[index] if index < len(orders) else None
            parts.append(f"{name}({order if order is not None else '-'})")
        return "；".join(parts)

    def populate_content(self, kind: str) -> None:
        table = self.post_table if kind == "post" else self.project_table
        records = self.content_records(kind)
        table.setRowCount(0)
        for row, rec in enumerate(records):
            table.insertRow(row)
            icons = []
            if is_fragmented_record(rec):
                icons.append("🧩")
            if self.has_cover(rec):
                icons.append("🖼")
            title = rec.title + (("  " + " ".join(icons)) if icons else "")
            if kind == "post":
                values = [
                    title,
                    rec.slug,
                    "是" if rec.draft else "否",
                    "是" if rec.homepage else "否",
                    ", ".join(rec.categories),
                    self.format_series_orders(rec),
                    ", ".join(rec.tags),
                    rec.summary,
                    rec.rel_display(self.cfg.root),
                    rec.date,
                    rec.lastmod,
                ]
            else:
                values = [
                    title,
                    rec.slug,
                    "是" if rec.draft else "否",
                    "是" if rec.featured else "否",
                    rec.status,
                    ", ".join(rec.categories),
                    ", ".join(rec.tags),
                    rec.summary,
                    rec.rel_display(self.cfg.root),
                    rec.date,
                    rec.lastmod,
                ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(rec.md_path))
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                if value == "是":
                    item.setForeground(QColor("#15803d"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setToolTip("点击可切换为“否”")
                elif value == "否":
                    item.setForeground(QColor("#dc2626"))
                    item.setToolTip("点击可切换为“是”")
                table.setItem(row, col, item)

        table.resizeColumnsToContents()
        for col in range(table.columnCount()):
            table.setColumnWidth(col, min(table.columnWidth(col), 360))
        if table.columnCount() > 0:
            table.setColumnWidth(0, max(220, table.columnWidth(0)))
        summary_col = 7
        if table.columnCount() > summary_col:
            table.setColumnWidth(summary_col, max(240, table.columnWidth(summary_col)))

    def taxonomy_usage(self, rec: TaxonomyRecord) -> Tuple[int, int]:
        keys = {rec.name.casefold(), rec.title.casefold()}
        post_count = 0
        project_count = 0
        for item in self.posts:
            values = item.categories if rec.kind == "category" else item.series if rec.kind == "series" else item.tags
            if any(value.casefold() in keys for value in values):
                post_count += 1
        if rec.kind != "series":
            for item in self.projects:
                values = item.categories if rec.kind == "category" else item.tags
                if any(value.casefold() in keys for value in values):
                    project_count += 1
        return post_count, project_count

    def populate_taxonomies(self) -> None:
        tab_indexes = {"category": 0, "series": 1, "tag": 2}
        tab_labels = {"category": "分类", "series": "系列", "tag": "标签"}
        for kind, lw in [("category", self.category_list), ("series", self.series_list), ("tag", self.tag_list)]:
            records = self.taxonomies[kind]
            self.tax_tabs.setTabText(tab_indexes[kind], f"{tab_labels[kind]}（{len(records)}）")
            lw.clear()
            for rec in records:
                post_count, project_count = self.taxonomy_usage(rec)
                suffix = "  🖼" if self.has_cover(rec) else ""
                if kind == "series":
                    usage_text = f"{post_count} 篇文章"
                else:
                    usage_text = f"{post_count} 篇文章，{project_count} 个项目"
                item = QListWidgetItem(f"{rec.title}{suffix}  （{usage_text}）")
                item.setData(Qt.ItemDataRole.UserRole, rec.name)
                description = rec.description or rec.name
                item.setToolTip(f"{description}\n{usage_text}")
                if self.active_filter == (kind, rec.name):
                    item.setBackground(QColor("#dbeafe"))
                lw.addItem(item)

    def populate_resources(self) -> None:
        self.resource_tree.clear()
        for rel in RESOURCE_ROOTS:
            root = self.cfg.root / rel
            if not root.exists():
                continue
            top = QTreeWidgetItem([rel, rel])
            top.setData(0, Qt.ItemDataRole.UserRole, str(root))
            self.resource_tree.addTopLevelItem(top)
            self.add_resource_children(top, root, 0)
        self.resource_tree.resizeColumnToContents(0)

    def add_resource_children(self, parent: QTreeWidgetItem, path: Path, depth: int) -> None:
        if depth > 4:
            return
        ignored = {".git", "public", "resources", ".hugo-cache", "node_modules", "__pycache__"}
        try:
            children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except Exception:
            return
        for child in children:
            if child.name in ignored:
                continue
            item = QTreeWidgetItem([child.name, rel_path(child, self.cfg.root)])
            item.setData(0, Qt.ItemDataRole.UserRole, str(child))
            parent.addChild(item)
            if child.is_dir():
                self.add_resource_children(item, child, depth + 1)

    def all_categories(self) -> List[str]:
        return unique([r.title for r in self.taxonomies["category"]] + [x for p in self.posts + self.projects for x in p.categories])

    def all_tags(self) -> List[str]:
        return unique([r.title for r in self.taxonomies["tag"]] + [x for p in self.posts + self.projects for x in p.tags])

    def all_series(self) -> List[str]:
        return unique([r.title for r in self.taxonomies["series"]] + [x for p in self.posts for x in p.series])

    def cover_status(self, rec: ContentRecord | TaxonomyRecord) -> str:
        cover = rec.cover.strip()
        if not cover:
            return "无"
        if is_web_url(cover):
            return "URL"
        base = rec.bundle_dir if isinstance(rec, ContentRecord) else rec.folder
        path = local_cover_path(cover, self.cfg.root, base)
        return "有" if path and path.is_file() else "缺失"

    def has_cover(self, rec: ContentRecord | TaxonomyRecord) -> bool:
        return self.cover_status(rec) in {"有", "URL"}
