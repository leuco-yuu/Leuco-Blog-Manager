from core import *
from dialogs import *
from workers import *


class ContentActionsMixin:
    def selected_content(self, kind: str, table: QTableWidget, row: Optional[int] = None) -> Optional[ContentRecord]:
        if row is None:
            row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if not item:
            return None
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        for rec in self.posts if kind == "post" else self.projects:
            if rec.md_path == path:
                return rec
        return None

    def boolean_field_for_column(self, kind: str, column: int) -> Optional[str]:
        if kind == "post":
            return {2: "draft", 3: "homepage"}.get(column)
        return {2: "draft", 3: "featured"}.get(column)

    def handle_content_cell_click(
        self,
        kind: str,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> None:
        field_name = self.boolean_field_for_column(kind, column)
        if not field_name:
            return
        rec = self.selected_content(kind, table, row)
        if rec:
            self.toggle_field(rec, field_name)

    def open_selected_content(
        self,
        kind: str,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> None:
        if self.boolean_field_for_column(kind, column):
            return
        rec = self.selected_content(kind, table, row)
        if rec:
            self.open_path(rec.md_path)

    def open_path(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "路径不存在", str(path))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def mark_modified(self, value: bool = True) -> None:
        self.modified = value
        self.setWindowTitle("Leuco Blog Manager" + (" [未提交修改]" if value else ""))

    def set_status(self, text: str) -> None:
        self.status.setToolTip(text)
        visible = text if len(text) <= 180 else text[:177] + "..."
        self.status.setText(visible)

    def long_form_split_content(self, rec: ContentRecord) -> None:
        blocks = collect_record_h1_blocks(rec)
        if len(blocks) < 2:
            QMessageBox.warning(
                self,
                "无法长篇分节",
                "该内容中可识别的一级标题少于 2 个，不能按一级标题拆分。",
            )
            return

        dlg = LongFormSplitDialog(rec, blocks, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        groups = dlg.assignments()
        if len(groups) < 2:
            return

        word_totals = dlg.section_word_totals()

        names_preview = "\n".join(
            f"{index + 1}. {split_part_title(rec.title, index + 1)}："
            f"{len(rows)} 个一级标题，约 {word_totals[index]} 字"
            for index, rows in enumerate(groups)
        )
        reply = QMessageBox.question(
            self,
            "确认长篇分节",
            "将把当前内容拆成以下条目，并重写分片文件、sections 与系列序号：\n\n"
            + names_preview
            + "\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with self.waiting("正在执行长篇分节……"):
                created_count, moved_count, copied_count = self.apply_long_form_split(rec, blocks, groups)
            self.mark_modified(True)
            self.load_blog()
            self.set_status(
                f"长篇分节完成：生成 {created_count} 个条目，"
                f"移动依赖 {moved_count} 个，复制依赖 {copied_count} 个。"
            )
        except Exception as exc:
            QMessageBox.critical(self, "长篇分节失败", str(exc))

    def clone_record_for_split_part(
        self,
        source: ContentRecord,
        title: str,
        slug: str,
        folder: Path,
        section_files: List[Path],
        created: str,
    ) -> ContentRecord:
        meta = dict(source.meta)
        meta["title"] = title
        meta["slug"] = slug
        meta["date"] = created
        meta["lastmod"] = now_iso()
        meta["sections"] = [path.name for path in section_files]
        if source.kind == "post":
            meta["series"] = list(source.series)
        return ContentRecord(
            kind=source.kind,
            title=title,
            slug=slug,
            date=created,
            lastmod=meta["lastmod"],
            draft=source.draft,
            homepage=source.homepage,
            description=source.description,
            summary=source.summary,
            tags=list(source.tags),
            categories=list(source.categories),
            series=list(source.series),
            cover=source.cover,
            md_path=folder / "index.md",
            bundle_dir=folder,
            body="",
            meta=meta,
            index_body="",
            section_files=section_files,
            series_order=list(source.series_order),
            featured=source.featured,
            link=source.link,
            status=source.status,
        )

    def write_split_section_files(
        self,
        folder: Path,
        blocks: List[MarkdownHeadingBlock],
    ) -> List[Path]:
        ensure_dir(folder)
        used: set[str] = set()
        paths: List[Path] = []
        for index, block in enumerate(blocks, start=1):
            name = unique_section_filename(folder, index, block.title, used)
            path = folder / name
            path.write_text(block.text.rstrip() + "\n", encoding="utf-8", newline="\n")
            paths.append(path)
        return paths

    def remove_old_section_files(self, rec: ContentRecord) -> None:
        old_files = {Path(path) for path in rec.section_files}
        old_files.update(discover_numbered_section_files(rec.bundle_dir))
        for path in sorted(old_files, key=lambda item: str(item).casefold()):
            try:
                if path.is_file() and path.name.casefold() not in {"index.md", "_index.md"}:
                    path.unlink()
            except FileNotFoundError:
                pass

    def local_cover_source_for_split(self, rec: ContentRecord) -> Optional[Path]:
        if not rec.cover or is_web_url(rec.cover) or rec.cover.startswith("/"):
            return None
        path = local_cover_path(rec.cover, self.cfg.root, rec.bundle_dir)
        if path and path.is_file() and path_is_inside(path, rec.bundle_dir):
            return path
        return None

    def copy_split_cover_to_targets(self, rec: ContentRecord, target_dirs: List[Path]) -> int:
        source = self.local_cover_source_for_split(rec)
        if not source:
            return 0
        copied = 0
        relative = Path(rec.cover)
        for folder in target_dirs:
            target = folder / relative
            try:
                if source.resolve() == target.resolve():
                    continue
            except OSError:
                if source == target:
                    continue
            ensure_dir(target.parent)
            if not target.exists():
                shutil.copy2(source, target)
                copied += 1
        return copied

    def apply_split_dependencies(
        self,
        rec: ContentRecord,
        grouped_blocks: List[List[MarkdownHeadingBlock]],
        target_dirs: List[Path],
    ) -> Tuple[int, int]:
        entries: Dict[Path, set[Path]] = {}
        original_root = rec.bundle_dir.resolve()
        protected: set[str] = set()
        cover_source = self.local_cover_source_for_split(rec)
        if cover_source:
            protected.add(os.path.normcase(str(cover_source.resolve())))

        for blocks, folder in zip(grouped_blocks, target_dirs):
            for block in blocks:
                for ref in markdown_relative_dependencies(block.text):
                    source = (block.source_path.parent / ref).resolve()
                    if not source.is_file() or not path_is_inside(source, original_root):
                        continue
                    target = folder / ref
                    entries.setdefault(source, set()).add(target)

        moved = 0
        copied = 0
        for source, targets in entries.items():
            normalized_targets = sorted(targets, key=lambda item: str(item).casefold())
            source_key = os.path.normcase(str(source.resolve()))
            if len(normalized_targets) == 1 and source_key not in protected:
                target = normalized_targets[0]
                try:
                    if source.resolve() == target.resolve():
                        continue
                except OSError:
                    if source == target:
                        continue
                ensure_dir(target.parent)
                if not target.exists():
                    shutil.move(str(source), str(target))
                    moved += 1
                continue

            for target in normalized_targets:
                try:
                    if source.resolve() == target.resolve():
                        continue
                except OSError:
                    if source == target:
                        continue
                ensure_dir(target.parent)
                if not target.exists() and source.exists():
                    shutil.copy2(source, target)
                    copied += 1
        return moved, copied

    def apply_series_orders_after_split(self, source: ContentRecord, parts: List[ContentRecord]) -> None:
        if source.kind != "post" or not source.series:
            return

        affected: Dict[str, ContentRecord] = {}
        old_orders = parse_series_orders(source.series_order, len(source.series))
        for series_index, series in enumerate(source.series):
            base_order = old_orders[series_index] if series_index < len(old_orders) else None
            if base_order is None or base_order <= 0:
                base_order = self.next_series_order(series, exclude=source)
            for record in self.posts:
                if record is source:
                    continue
                current = self.series_order_for(record, series)
                if current is not None and current > base_order:
                    self.set_series_order_for(record, series, current + len(parts) - 1)
                    affected[str(record.md_path)] = record
            for offset, part in enumerate(parts):
                self.set_series_order_for(part, series, base_order + offset)

        for record in affected.values():
            record.lastmod = now_iso()
            write_content(record, self.cfg)

    def apply_long_form_split(
        self,
        rec: ContentRecord,
        blocks: List[MarkdownHeadingBlock],
        groups: List[List[int]],
    ) -> Tuple[int, int, int]:
        root = self.cfg.posts if rec.kind == "post" else self.cfg.projects
        grouped_blocks = [[blocks[index] for index in rows] for rows in groups]
        reserved_slugs = {
            record.slug.casefold()
            for record in self.posts + self.projects
            if record is not rec
        }
        reserved_dirs = {
            path.name.casefold()
            for path in root.iterdir()
            if path.is_dir() and path.resolve() != rec.bundle_dir.resolve()
        } if root.exists() else set()
        reserved = reserved_slugs | reserved_dirs

        target_dirs: List[Path] = [rec.bundle_dir]
        slugs: List[str] = [rec.slug]
        for index in range(2, len(groups) + 1):
            slug = unique_content_slug(root, f"{rec.slug}-{index}", reserved)
            slugs.append(slug)
            target_dirs.append(root / slug)

        for folder in target_dirs[1:]:
            if folder.exists():
                raise FileExistsError(f"目标目录已存在：{folder}")
            ensure_dir(folder)

        base_created = parse_iso_datetime(rec.date) or datetime.now().astimezone()
        created_values = [
            (base_created + timedelta(seconds=offset)).isoformat()
            for offset in range(len(groups))
        ]

        self.remove_old_section_files(rec)
        part_records: List[ContentRecord] = []
        for index, (folder, slug, part_blocks, created) in enumerate(
            zip(target_dirs, slugs, grouped_blocks, created_values),
            start=1,
        ):
            section_files = self.write_split_section_files(folder, part_blocks)
            part = self.clone_record_for_split_part(
                rec,
                split_part_title(rec.title, index),
                slug,
                folder,
                section_files,
                created,
            )
            if index > 1:
                part.meta.pop("aliases", None)
            part_records.append(part)

        self.apply_series_orders_after_split(rec, part_records)
        moved, copied = self.apply_split_dependencies(rec, grouped_blocks, target_dirs)
        copied += self.copy_split_cover_to_targets(rec, target_dirs[1:])

        for part in part_records:
            part.body = compose_content_body("", part.section_files)
            write_content(part, self.cfg)
            self.ensure_taxonomies_for_record(part)

        return len(part_records), moved, copied

    def section_action_label(self, path: Path, index: int) -> str:
        try:
            meta, _body = split_front_matter(path.read_text(encoding="utf-8", errors="replace"), path)
            title = scalar(meta.get("title"))
        except Exception:
            title = ""
        label = title or path.stem
        return f"{index}. {label}（{path.name}）"

    def add_sections_submenu(self, menu: QMenu, rec: ContentRecord) -> None:
        if not is_fragmented_record(rec):
            return
        section_menu = menu.addMenu("章节")
        for index, path in enumerate(rec.section_files, start=1):
            section_menu.addAction(
                self.section_action_label(path, index),
                lambda _checked=False, p=path: self.open_path(p),
            )

    def open_content_menu(self, kind: str, table: QTableWidget, pos: QPoint) -> None:
        row = table.rowAt(pos.y())
        if row < 0:
            return
        table.selectRow(row)
        rec = self.selected_content(kind, table, row)
        if not rec:
            return
        menu = QMenu(self)
        menu.addAction("打开文件", lambda: self.open_path(rec.md_path))
        menu.addAction("打开目录", lambda: self.open_path(rec.bundle_dir))
        menu.addAction("复制引用格式", lambda: self.copy_reference_format(self.content_reference_format(rec)))
        self.add_sections_submenu(menu, rec)
        menu.addAction("长篇分节", lambda: self.long_form_split_content(rec))
        if self.has_cover(rec):
            menu.addAction("查看封面", lambda: self.open_cover(rec))
        menu.addSeparator()
        menu.addAction("修改标题", lambda: self.edit_text(rec, "title", "标题"))
        menu.addAction("修改 slug", lambda: self.edit_slug(rec))
        menu.addAction("修改描述", lambda: self.edit_text(rec, "description", "描述", multiline=True))
        menu.addAction("修改摘要", lambda: self.edit_text(rec, "summary", "摘要", multiline=True))
        menu.addAction("修改分类", lambda: self.edit_list(rec, "categories", self.all_categories()))
        menu.addAction("修改标签", lambda: self.edit_list(rec, "tags", self.all_tags()))
        if kind == "post":
            menu.addAction("修改系列", lambda: self.edit_list(rec, "series", self.all_series()))
            menu.addAction("设置系列序号", lambda: self.edit_series_order(rec))
        else:
            menu.addAction("修改状态", lambda: self.edit_project_status(rec))
            menu.addAction("修改外部链接", lambda: self.edit_text(rec, "link", "外部链接"))
            menu.addAction("切换精选", lambda: self.toggle_field(rec, "featured"))
        menu.addAction("切换首页展示", lambda: self.toggle_field(rec, "homepage"))
        menu.addAction("切换草稿", lambda: self.toggle_field(rec, "draft"))
        menu.addAction("设置/替换封面", lambda: self.set_content_cover(rec, compress=False))
        menu.addAction("新增并压缩封面", lambda: self.set_content_cover(rec, compress=True))
        menu.addAction("更新最后修改时间", lambda: self.update_lastmod(rec))
        menu.addSeparator()
        menu.addAction("删除" + ("文章" if kind == "post" else "项目"), lambda: self.delete_content(rec))
        menu.exec(table.viewport().mapToGlobal(pos))

    def edit_text(self, rec: ContentRecord, field_name: str, label: str, multiline: bool = False) -> None:
        ai_callback: Optional[Callable[[], Optional[str]]] = None
        ai_button_text = ""
        if field_name == "summary":
            ai_callback = lambda: self.ai_text_for_record(rec, "summary")
            ai_button_text = "AI 总结摘要"
        elif field_name == "description":
            ai_callback = lambda: self.ai_text_for_record(rec, "description")
            ai_button_text = "AI 生成描述"
        dlg = TextDialog(
            f"修改{label}",
            label,
            scalar(getattr(rec, field_name)),
            multiline,
            self,
            ai_button_text=ai_button_text,
            ai_callback=ai_callback,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        setattr(rec, field_name, dlg.text())
        self.write_record(rec)

    def edit_slug(self, rec: ContentRecord) -> None:
        aliases = listify(rec.meta.get("aliases"))
        dlg = SlugDialog(rec.slug, aliases, lambda: self.ai_slug_for_record(rec), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value, new_aliases = dlg.values()
        all_records = self.posts + self.projects
        if any(r is not rec and r.slug.casefold() == value.casefold() for r in all_records):
            QMessageBox.warning(self, "slug 重复", "已有内容使用该 slug。")
            return
        old_slug = rec.slug
        rec.slug = value
        if new_aliases:
            rec.meta["aliases"] = new_aliases
        else:
            rec.meta.pop("aliases", None)
        rec.lastmod = now_iso()
        write_content(rec, self.cfg)
        self.ensure_taxonomies_for_record(rec)
        changed_files, replacements = self.update_slug_references([(rec.kind, old_slug, value)])
        self.mark_modified(True)
        self.load_blog()
        self.set_status(
            f"slug 已更新：{old_slug} → {value}；同步替换 {changed_files} 个文件中的 {replacements} 处引用。"
        )

    def edit_list(self, rec: ContentRecord, field_name: str, available: List[str], single: bool = False) -> None:
        current = list(getattr(rec, field_name))
        count_ranges = {
            "tags": (3, 5),
            "categories": (1, 2),
            "series": (1, 3),
        }
        count_range = count_ranges.get(field_name, (1, 3))
        field_labels = {"tags": "标签", "categories": "分类", "series": "系列"}
        dlg = ListDialog(
            "修改" + field_labels.get(field_name, field_name),
            available,
            current,
            self,
            count_range=count_range,
            ai_select=lambda count: self.ai_taxonomy_values(rec, field_name, "select", count),
            ai_summarize=lambda count: self.ai_taxonomy_values(rec, field_name, "summarize", count),
            ai_suggest=lambda count: self.ai_taxonomy_values(rec, field_name, "suggest", count),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.values()
        if single:
            values = values[:1]
        if field_name == "series":
            old_series = list(rec.series)
            old_orders = list(rec.series_order)
            order_map = {name.casefold(): old_orders[i] if i < len(old_orders) else None for i, name in enumerate(old_series)}
            rec.series = values
            rec.series_order = [
                order_map.get(name.casefold()) or self.next_series_order(name, exclude=rec)
                for name in values
            ]
        else:
            setattr(rec, field_name, values)
        self.write_record(rec)

    def toggle_field(self, rec: ContentRecord, field_name: str) -> None:
        setattr(rec, field_name, not bool(getattr(rec, field_name)))
        self.write_record(rec)

    def edit_project_status(self, rec: ContentRecord) -> None:
        items = ["planning", "in_progress", "completed", "paused"]
        value, ok = QInputDialog.getItem(self, "修改状态", "状态", items, max(0, items.index(rec.status) if rec.status in items else 0), True)
        if ok:
            rec.status = value.strip()
            self.write_record(rec)

    def series_order_for(self, rec: ContentRecord, series: str) -> Optional[int]:
        key = series.casefold()
        for index, name in enumerate(rec.series):
            if name.casefold() == key:
                return rec.series_order[index] if index < len(rec.series_order) else None
        return None

    def set_series_order_for(self, rec: ContentRecord, series: str, order: int) -> None:
        rec.series_order = parse_series_orders(rec.series_order, len(rec.series))
        key = series.casefold()
        for index, name in enumerate(rec.series):
            if name.casefold() == key:
                rec.series_order[index] = order
                return

    def next_series_order(self, series: str, exclude: Optional[ContentRecord] = None) -> int:
        used = sorted(
            order
            for record in self.posts
            if record is not exclude
            for order in [self.series_order_for(record, series)]
            if order is not None and order > 0
        )
        n = 1
        for value in used:
            if value == n:
                n += 1
            elif value > n:
                break
        return n

    def edit_series_order(self, rec: ContentRecord) -> None:
        if not rec.series:
            QMessageBox.warning(self, "没有系列", "请先把文章加入某个系列。")
            return
        series, ok = QInputDialog.getItem(self, "选择系列", "要修改哪个系列的序号？", rec.series, 0, False)
        if not ok or not series:
            return
        used = sorted(
            order
            for record in self.posts
            if record is not rec
            for order in [self.series_order_for(record, series)]
            if order is not None
        )
        default = self.series_order_for(rec, series) or self.next_series_order(series, exclude=rec)
        value, ok = QInputDialog.getInt(
            self,
            "设置系列序号",
            f"系列：{series}\n已有序号：{', '.join(map(str, used)) or '无'}\n请输入唯一序号：",
            default,
            1,
            999,
        )
        if not ok:
            return
        if value in used:
            QMessageBox.warning(self, "序号重复", f"系列“{series}”中已经存在序号 {value}。")
            return
        self.set_series_order_for(rec, series, value)
        self.write_record(rec)

    def edit_series_members_order(self, taxonomy: TaxonomyRecord) -> None:
        aliases = {taxonomy.title.casefold(), taxonomy.name.casefold()}

        def actual_series_name(record: ContentRecord) -> Optional[str]:
            for name in record.series:
                if name.casefold() in aliases:
                    return name
            return None

        members = [record for record in self.posts if actual_series_name(record) is not None]
        if not members:
            QMessageBox.information(self, "没有文章", f"系列“{taxonomy.title}”中没有文章。")
            return

        members_with_orders: List[Tuple[ContentRecord, int]] = []
        assigned: set[int] = set()
        next_fallback = 1
        sorted_members = sorted(
            members,
            key=lambda item: (
                self.series_order_for(item, actual_series_name(item) or taxonomy.title) or 10**9,
                item.title.casefold(),
            ),
        )
        for record in sorted_members:
            actual_name = actual_series_name(record) or taxonomy.title
            order = self.series_order_for(record, actual_name)
            if order is None or order <= 0 or order in assigned:
                while next_fallback in assigned:
                    next_fallback += 1
                order = next_fallback
            assigned.add(order)
            members_with_orders.append((record, order))

        dlg = SeriesOrderDialog(taxonomy.title, members_with_orders, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path_map = {record.md_path: record for record in members}
        for path, order in dlg.values():
            record = path_map.get(path)
            if not record:
                continue
            actual_name = actual_series_name(record)
            if not actual_name:
                continue
            self.set_series_order_for(record, actual_name, order)
            record.lastmod = now_iso()
            write_content(record, self.cfg)
        self.mark_modified(True)
        self.load_blog()

    def update_lastmod(self, rec: ContentRecord) -> None:
        rec.lastmod = now_iso()
        write_content(rec, self.cfg)
        self.mark_modified(True)
        self.load_blog()

    def compression_result_text(self, before: int, after: int) -> str:
        saved = max(0, before - after)
        percent = (saved / before * 100) if before else 0.0
        return (
            f"处理前 {format_file_size(before)}，处理后 {format_file_size(after)}，"
            f"减少 {format_file_size(saved)}（{percent:.1f}%）"
        )

    def set_content_cover(self, rec: ContentRecord, compress: bool = False) -> None:
        path = self.select_file(self, "选择封面图片", IMAGE_FILTER)
        if not path:
            return
        try:
            action = "正在无损压缩并添加封面……" if compress else "正在添加封面……"
            with self.waiting(action):
                rec.cover, before, after = install_cover_to_static(
                    Path(path),
                    self.cfg.root,
                    rec.bundle_dir.name or rec.slug or rec.title,
                    compress=compress,
                )
                self.write_record(rec)
            if compress:
                self.set_status(
                    f"封面已添加并优化：{self.compression_result_text(before, after)}"
                )
            else:
                self.set_status(f"封面已添加：{rec.cover}")
        except Exception as exc:
            self.set_status("封面处理失败。")
            QMessageBox.critical(self, "封面处理失败", str(exc))

    def open_cover(self, rec: ContentRecord | TaxonomyRecord) -> None:
        if is_web_url(rec.cover):
            QDesktopServices.openUrl(QUrl(rec.cover))
            return
        base = rec.bundle_dir if isinstance(rec, ContentRecord) else rec.folder
        path = local_cover_path(rec.cover, self.cfg.root, base)
        if path is None:
            QMessageBox.warning(self, "封面不存在", "当前条目没有可打开的本地封面。")
            return
        self.open_path(path)

    def delete_content(self, rec: ContentRecord) -> None:
        label = "文章" if rec.kind == "post" else "项目"
        reply = QMessageBox.question(self, f"删除{label}", f"确定删除整个目录吗？\n{rec.bundle_dir}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(rec.bundle_dir)
        self.mark_modified(True)
        self.load_blog()
