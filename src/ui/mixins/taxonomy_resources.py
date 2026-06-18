from core import *
from dialogs import *
from workers import *


class TaxonomyResourceMixin:
    def selected_taxonomy(self, kind: str, lw: QListWidget) -> Optional[TaxonomyRecord]:
        item = lw.currentItem()
        if not item:
            return None
        name = item.data(Qt.ItemDataRole.UserRole)
        for rec in self.taxonomies[kind]:
            if rec.name == name:
                return rec
        return None

    def open_taxonomy_menu(self, kind: str, lw: QListWidget, pos: QPoint) -> None:
        item = lw.itemAt(pos)
        menu = QMenu(self)
        menu.addAction("新增条目", lambda: self.add_taxonomy(kind))
        if kind == "tag":
            menu.addAction("合并标签", self.merge_similar_tags)
        if item:
            lw.setCurrentItem(item)
            rec = self.selected_taxonomy(kind, lw)
            if rec:
                menu.addSeparator()
                menu.addAction("按此筛选/取消筛选", lambda: self.toggle_filter(kind, rec.name))
                menu.addAction("打开目录", lambda: self.open_path(rec.folder))
                if kind in {"category", "series"}:
                    menu.addAction("复制引用格式", lambda r=rec: self.copy_reference_format(self.taxonomy_reference_format(r)))
                menu.addAction("编辑标题", lambda: self.edit_taxonomy_text(rec, "title", "标题"))
                menu.addAction("编辑描述", lambda: self.edit_taxonomy_text(rec, "description", "描述", multiline=True))
                if kind == "series":
                    menu.addAction("系列文章排序", lambda: self.edit_series_members_order(rec))
                if kind in {"category", "series"}:
                    menu.addAction("设置/替换封面", lambda: self.set_taxonomy_cover(rec, compress=False))
                    menu.addAction("新增并压缩封面", lambda: self.set_taxonomy_cover(rec, compress=True))
                    if self.has_cover(rec):
                        menu.addAction("查看封面", lambda: self.open_cover(rec))
                    if rec.cover:
                        menu.addAction("移除封面", lambda: self.remove_taxonomy_cover(rec))
                menu.addSeparator()
                menu.addAction("删除条目", lambda: self.delete_taxonomy(rec))
        menu.exec(lw.viewport().mapToGlobal(pos))

    def add_taxonomy(self, kind: str) -> None:
        label = {"category": "分类", "series": "系列", "tag": "标签"}[kind]
        value, ok = QInputDialog.getText(self, "新增" + label, label + "名称")
        if not ok or not value.strip():
            return
        name = value.strip()
        folder = self.cfg.taxonomy_root(kind) / name
        ensure_dir(folder)
        rec = TaxonomyRecord(kind, name, name, "", "", folder / "_index.md", folder, "", {})
        write_taxonomy(rec)
        self.mark_modified(True)
        self.load_blog()

    def edit_taxonomy_text(self, rec: TaxonomyRecord, field_name: str, label: str, multiline: bool = False) -> None:
        ai_callback: Optional[Callable[[], Optional[str]]] = None
        ai_button_text = ""
        if field_name == "description" and rec.kind in {"category", "series"}:
            ai_callback = lambda: self.ai_taxonomy_description(rec)
            ai_button_text = "AI 总结该" + ("分类" if rec.kind == "category" else "系列")
        dlg = TextDialog(
            f"编辑{label}",
            label,
            scalar(getattr(rec, field_name)),
            multiline,
            self,
            ai_button_text=ai_button_text,
            ai_callback=ai_callback,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            setattr(rec, field_name, dlg.text())
            write_taxonomy(rec)
            self.mark_modified(True)
            self.load_blog()

    def set_taxonomy_cover(self, rec: TaxonomyRecord, compress: bool = False) -> None:
        path = self.select_file(self, "选择封面图片", IMAGE_FILTER)
        if not path:
            return
        try:
            action = "正在无损压缩并添加封面……" if compress else "正在添加封面……"
            with self.waiting(action):
                rec.cover, before, after = install_cover_to_static(
                    Path(path),
                    self.cfg.root,
                    rec.folder.name or rec.name or rec.title,
                    compress=compress,
                )
                write_taxonomy(rec)
                self.mark_modified(True)
                self.load_blog()
            if compress:
                self.set_status(
                    f"封面已添加并优化：{self.compression_result_text(before, after)}"
                )
            else:
                self.set_status(f"封面已添加：{rec.cover}")
        except Exception as exc:
            self.set_status("封面处理失败。")
            QMessageBox.critical(self, "封面处理失败", str(exc))

    def remove_taxonomy_cover(self, rec: TaxonomyRecord) -> None:
        rec.cover = ""
        write_taxonomy(rec)
        self.mark_modified(True)
        self.load_blog()

    def delete_taxonomy(self, rec: TaxonomyRecord) -> None:
        label = {"category": "分类", "series": "系列", "tag": "标签"}[rec.kind]
        reply = QMessageBox.question(
            self,
            "删除" + label,
            f"确定删除“{rec.title}”吗？会从所有文章/项目中移除该引用，并删除目录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        key = rec.title.casefold()
        for content in self.posts + self.projects:
            changed = False
            if rec.kind == "category":
                new = [x for x in content.categories if x.casefold() != key]
                changed = new != content.categories
                content.categories = new
            elif rec.kind == "tag":
                new = [x for x in content.tags if x.casefold() != key]
                changed = new != content.tags
                content.tags = new
            elif rec.kind == "series":
                old_series = list(content.series)
                old_orders = parse_series_orders(content.series_order, len(old_series))
                kept = [(name, old_orders[i] if i < len(old_orders) else None) for i, name in enumerate(old_series) if name.casefold() != key]
                new = [name for name, _ in kept]
                changed = new != content.series
                content.series = new
                content.series_order = [order for _, order in kept]
            if changed:
                content.lastmod = now_iso()
                write_content(content, self.cfg)
        if rec.folder.exists():
            shutil.rmtree(rec.folder)
        self.mark_modified(True)
        self.load_blog()

    def toggle_filter(self, kind: str, name: str) -> None:
        if self.active_filter == (kind, name):
            self.active_filter = None
        else:
            self.active_filter = (kind, name)
        self.populate_all()

    def open_resource_item(self, item: QTreeWidgetItem) -> None:
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if path.is_file():
            self.open_path(path)

    def open_resource_menu(self, pos: QPoint) -> None:
        item = self.resource_tree.itemAt(pos)
        if not item:
            return
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        menu.addAction("打开", lambda: self.open_path(path))
        menu.addAction("打开所在目录", lambda: self.open_path(path if path.is_dir() else path.parent))
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            menu.addAction("预览图片", lambda: self.open_path(path))
        if path.is_file() and path.suffix.lower() in TEXT_EXTS:
            menu.addAction("编辑文本", lambda: self.edit_resource_text(path))
        menu.addAction("复制/替换资源", lambda: self.replace_resource(path))
        menu.addAction("重命名", lambda: self.rename_resource(path))
        menu.addSeparator()
        menu.addAction("删除", lambda: self.delete_resource(path))
        menu.exec(self.resource_tree.viewport().mapToGlobal(pos))

    def edit_resource_text(self, path: Path) -> None:
        dlg = TextDialog("编辑资源", rel_path(path, self.cfg.root), path.read_text(encoding="utf-8", errors="replace"), True, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            path.write_text(dlg.text() + "\n", encoding="utf-8", newline="\n")
            self.mark_modified(True)
            self.populate_resources()

    def replace_resource(self, path: Path) -> None:
        src = self.select_file(self, "选择资源文件", "All Files (*)")
        if not src:
            return
        target = path if path.is_file() else path / Path(src).name
        if target.exists():
            reply = QMessageBox.question(self, "替换资源", f"确定覆盖？\n{target}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        with self.waiting("正在复制资源……"):
            shutil.copy2(src, target)
            self.mark_modified(True)
            self.populate_resources()
        self.set_status(f"资源已复制到：{target}")

    def rename_resource(self, path: Path) -> None:
        name, ok = QInputDialog.getText(self, "重命名", "新名称", text=path.name)
        if ok and name.strip():
            path.rename(path.with_name(name.strip()))
            self.mark_modified(True)
            self.populate_resources()

    def delete_resource(self, path: Path) -> None:
        reply = QMessageBox.question(self, "删除资源", f"确定删除？\n{path}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        self.mark_modified(True)
        self.populate_resources()
