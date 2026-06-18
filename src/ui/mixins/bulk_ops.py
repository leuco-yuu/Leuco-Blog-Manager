from core import *
from dialogs import *
from workers import *


class BulkOpsMixin:
    def records_for_kind(self, kind: str) -> List[ContentRecord]:
        return self.posts if kind == "post" else self.projects

    def insert_section_orders(self, kind: str) -> None:
        """
        扫描文章/项目目录中的数字前缀 Markdown 分片，并将排序结果写入 sections。

        例如：
            sections:
              - 0-代码块.md
              - 1-批注.md
              - 2-画廊.md
        """
        records = list(self.records_for_kind(kind))
        fragmented: List[Tuple[ContentRecord, List[Path]]] = []

        for record in records:
            section_files = discover_numbered_section_files(record.bundle_dir)
            if section_files:
                fragmented.append((record, section_files))

        label = "文章" if kind == "post" else "项目"
        if not fragmented:
            self.set_status(f"没有检测到包含数字前缀分片的{label}。")
            return

        changed = 0
        self.begin_bulk_progress(
            f"正在为 {len(fragmented)} 个分片{label}写入 sections……",
            len(fragmented),
        )
        try:
            for index, (record, section_files) in enumerate(fragmented, start=1):
                names = [path.name for path in section_files]
                current = section_name_list(record.meta.get("sections"))
                if current != names:
                    record.meta["sections"] = names
                    record.section_files = section_files
                    record.body = compose_content_body(record.index_body or "", section_files)
                    write_content(record, self.cfg)
                    changed += 1

                self.progress.setValue(index)
                self.set_status(
                    f"正在写入分片顺序：{index}/{len(fragmented)}"
                )
                QApplication.processEvents()
        except Exception as exc:
            QMessageBox.critical(self, "写入分片顺序失败", str(exc))
            return
        finally:
            self.end_bulk_progress()

        if changed:
            self.mark_modified(True)
            self.load_blog()
        self.set_status(
            f"分片顺序处理完成：检测到 {len(fragmented)} 个分片{label}，"
            f"更新 {changed} 个。"
        )

    def default_date_range(self, records: List[ContentRecord]) -> Tuple[date, date]:
        parsed = [value for value in (parse_iso_datetime(record.date) for record in records) if value]
        if parsed:
            start = min(value.date() for value in parsed)
            end = max(value.date() for value in parsed)
        else:
            end = datetime.now().date()
            start = end - timedelta(days=max(30, len(records) * 3))
        if start == end and len(records) > 1:
            end = start + timedelta(days=max(30, len(records) * 2))
        return start, end

    def randomize_creation_times(self, kind: str) -> None:
        records = list(self.records_for_kind(kind))
        if not records:
            self.set_status("没有可随机化的内容。")
            return
        start_default, end_default = self.default_date_range(records)
        dlg = DateRangeDialog(
            "随机化文章创建时间" if kind == "post" else "随机化项目创建时间",
            start_default,
            end_default,
            len(records),
            self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        oldest_first = list(reversed(records))
        try:
            generated = generate_creation_datetimes(oldest_first, dlg.start_date(), dlg.end_date())
            with self.waiting("正在随机化创建时间……"):
                for record, created in zip(oldest_first, generated):
                    record.date = created.replace(microsecond=0).isoformat()
                    current_lastmod = parse_iso_datetime(record.lastmod)
                    if current_lastmod is None or current_lastmod < created:
                        record.lastmod = record.date
                    write_content(record, self.cfg)
            self.mark_modified(True)
            self.load_blog()
            self.set_status(f"已随机化 {len(records)} 个{'文章' if kind == 'post' else '项目'}的创建时间。")
        except Exception as exc:
            QMessageBox.critical(self, "随机化失败", str(exc))

    def randomize_lastmod_times(self, kind: str) -> None:
        records = list(self.records_for_kind(kind))
        if not records:
            self.set_status("没有可随机化的内容。")
            return
        try:
            with self.waiting("正在随机化最近修改时间……"):
                for record in records:
                    created = parse_iso_datetime(record.date) or datetime.now().astimezone()
                    record.lastmod = random_lastmod_after(created).replace(microsecond=0).isoformat()
                    write_content(record, self.cfg)
            self.mark_modified(True)
            self.load_blog()
            self.set_status(f"已随机化 {len(records)} 个{'文章' if kind == 'post' else '项目'}的最近修改时间。")
        except Exception as exc:
            QMessageBox.critical(self, "随机化失败", str(exc))

    def begin_bulk_progress(self, message: str, total: int) -> None:
        self._bulk_busy = True
        self.set_status(message)
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.update_progress_visibility()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()

    def end_bulk_progress(self) -> None:
        QApplication.restoreOverrideCursor()
        self._bulk_busy = False
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.update_progress_visibility()
        QApplication.processEvents()

    def slug_batch_size(self, kind: str) -> int:
        widget = self.post_slug_batch_size if kind == "post" else self.project_slug_batch_size
        return max(1, min(500, int(widget.value())))

    def _slug_batches(self, records: List[ContentRecord], batch_size: int) -> List[List[Tuple[int, ContentRecord]]]:
        indexed = list(enumerate(records, start=1))
        return [indexed[index:index + batch_size] for index in range(0, len(indexed), batch_size)]

    def _format_slug_titles(self, batch: List[Tuple[int, ContentRecord]]) -> str:
        return "\n".join(f"{index}. {record.title}" for index, record in batch)

    def _extract_slug_json(self, raw: str) -> Any:
        text = str(raw).strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        starts = [position for position in (text.find("["), text.find("{")) if position >= 0]
        if starts:
            start = min(starts)
            end = max(text.rfind("]"), text.rfind("}"))
            if end >= start:
                text = text[start:end + 1]
        return json.loads(text)

    def _parse_slug_batch_response(self, raw: str, expected_ids: List[int]) -> Dict[int, str]:
        payload = self._extract_slug_json(raw)
        items: List[Tuple[Any, Any]] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("JSON 数组元素必须是对象。")
                item_id = item.get("id", item.get("index", item.get("number")))
                slug = item.get("slug")
                items.append((item_id, slug))
        elif isinstance(payload, dict):
            nested = payload.get("items") or payload.get("slugs") or payload.get("results")
            if isinstance(nested, list):
                for item in nested:
                    if not isinstance(item, dict):
                        raise ValueError("JSON 数组元素必须是对象。")
                    item_id = item.get("id", item.get("index", item.get("number")))
                    slug = item.get("slug")
                    items.append((item_id, slug))
            else:
                for key, slug in payload.items():
                    items.append((key, slug))
        else:
            raise ValueError("AI 输出不是 JSON 数组或对象。")

        parsed: Dict[int, str] = {}
        invalid_slug_rows: List[str] = []
        for item_id, raw_slug in items:
            try:
                index = int(str(item_id).strip())
            except (TypeError, ValueError):
                raise ValueError(f"存在无法识别的编号：{item_id!r}")
            slug = sanitize_slug_guess(str(raw_slug or ""))
            if not SLUG_RE.match(slug):
                invalid_slug_rows.append(f"{index}: {raw_slug}")
                continue
            parsed[index] = slug

        expected = set(expected_ids)
        actual = set(parsed)
        if expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(
                "编号不匹配。"
                f"期望编号：{', '.join(map(str, expected_ids))}；"
                f"缺少：{', '.join(map(str, missing)) or '无'}；"
                f"多余：{', '.join(map(str, extra)) or '无'}。"
            )
        if invalid_slug_rows:
            raise ValueError("存在无效 slug：" + "; ".join(invalid_slug_rows[:20]))
        return parsed

    def _request_slug_batch(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        system_prompt: str,
        batch: List[Tuple[int, ContentRecord]],
    ) -> Dict[int, str]:
        expected_ids = [index for index, _record in batch]
        titles = self._format_slug_titles(batch)
        warning = ""
        last_error: Optional[Exception] = None
        for attempt in range(1, 4):
            prompt = load_prompt(
                "slug_batch.txt",
                titles=titles,
                warning=warning,
            )
            raw = ai_chat_completion(
                endpoint,
                api_key,
                model,
                system_prompt,
                prompt,
                0.0,
                240,
            )
            try:
                return self._parse_slug_batch_response(raw, expected_ids)
            except Exception as exc:
                last_error = exc
                warning = (
                    "上一轮输出无效，必须重新生成。"
                    f"错误：{exc}\n"
                    "请只返回包含完全相同编号的严格 JSON，不要解释。"
                )
        raise RuntimeError(str(last_error or "AI 未返回有效 slug。"))

    def _unique_proposed_slugs(
        self,
        records: List[ContentRecord],
        raw_results: Dict[int, str],
    ) -> List[str]:
        target_ids = {id(record) for record in records}
        used = {
            record.slug.casefold()
            for record in self.posts + self.projects
            if id(record) not in target_ids
        }
        proposed: List[str] = []
        for index, record in enumerate(records, start=1):
            candidate = sanitize_slug_guess(raw_results[index])
            base_candidate = candidate
            suffix = 2
            while candidate.casefold() in used:
                candidate = f"{base_candidate}-{suffix}"
                suffix += 1
            used.add(candidate.casefold())
            proposed.append(candidate)
        return proposed

    def bulk_update_slugs(self, kind: str) -> None:
        records = list(self.records_for_kind(kind))
        if not records:
            self.set_status("没有需要更新 slug 的内容。")
            return
        api_key = self.read_api_key()
        if not api_key:
            QMessageBox.warning(self, "尚未登录", "请先输入密码并点击“登录”。")
            return

        self.save_api_config()
        base = self.api_base_edit.text().strip().rstrip("/")
        endpoint = base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"
        model = self.api_model_edit.text().strip()
        system_prompt = load_prompt("system.txt")
        concurrency_widget = self.post_slug_concurrency if kind == "post" else self.project_slug_concurrency
        concurrency = max(1, min(100, concurrency_widget.value()))
        batch_size = self.slug_batch_size(kind)
        batches = self._slug_batches(records, batch_size)

        results: Dict[int, str] = {}
        errors: Dict[str, str] = {}
        self.begin_bulk_progress(
            f"正在按批生成 slug：{len(records)} 个标题，{len(batches)} 批，每批最多 {batch_size} 个……",
            len(batches),
        )
        fatal_error: Optional[Exception] = None
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_map = {
                    executor.submit(
                        self._request_slug_batch,
                        endpoint,
                        api_key,
                        model,
                        system_prompt,
                        batch,
                    ): batch
                    for batch in batches
                }
                pending = set(future_map)
                completed = 0
                while pending:
                    done, pending = wait(pending, timeout=0.08, return_when=FIRST_COMPLETED)
                    for future in done:
                        batch = future_map[future]
                        batch_label = f"{batch[0][0]}-{batch[-1][0]}"
                        try:
                            results.update(future.result())
                        except Exception as exc:
                            errors[batch_label] = str(exc)
                        completed += 1
                        self.progress.setValue(completed)
                        self.set_status(f"正在生成 slug：{completed}/{len(batches)} 批")
                    QApplication.processEvents()
        except Exception as exc:
            fatal_error = exc
        finally:
            self.end_bulk_progress()
        if fatal_error is not None:
            QMessageBox.critical(self, "批量更新 slug 失败", str(fatal_error))
            return

        expected = set(range(1, len(records) + 1))
        missing = sorted(expected - set(results))
        if errors or missing:
            parts: List[str] = []
            if missing:
                parts.append("缺少以下编号的 slug：" + ", ".join(map(str, missing[:80])))
            for batch_label, message in list(errors.items())[:20]:
                parts.append(f"批次 {batch_label}：{message}")
            QMessageBox.critical(
                self,
                "批量更新 slug 失败",
                "未能为所有标题生成有效 slug，未写入任何文件。\n\n" + "\n".join(parts),
            )
            return

        proposed = self._unique_proposed_slugs(records, results)
        target_ids = {id(record) for record in records}
        reserved = {
            record.slug.casefold()
            for record in self.posts + self.projects
            if id(record) not in target_ids
        }
        review_rows = [
            (
                index,
                record.title,
                record.slug,
                proposed[index],
                rel_path(record.md_path, self.cfg.root),
            )
            for index, record in enumerate(records)
        ]
        dlg = BulkSlugReviewDialog(review_rows, reserved, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.set_status("已取消批量更新 slug。")
            return

        accepted = dict(dlg.accepted_values())
        final_slugs = [accepted.get(index, record.slug) for index, record in enumerate(records)]
        final_keys: Dict[str, str] = {}
        duplicates: List[str] = []
        for record, slug in zip(records, final_slugs):
            key = slug.casefold()
            if key in reserved or key in final_keys:
                duplicates.append(slug)
            final_keys[key] = record.title
        if duplicates:
            QMessageBox.critical(
                self,
                "slug 冲突",
                "所选 slug 与现有内容或本次最终结果冲突，未写入任何文件：\n"
                + "\n".join(unique(duplicates)[:30]),
            )
            return

        changed = 0
        slug_changes: List[Tuple[str, str, str]] = []
        try:
            with self.waiting("正在写入 slug 并更新引用……"):
                for index, record in enumerate(records):
                    candidate = final_slugs[index]
                    if candidate == record.slug:
                        continue
                    old_slug = record.slug
                    record.slug = candidate
                    record.lastmod = now_iso()
                    write_content(record, self.cfg)
                    slug_changes.append((record.kind, old_slug, candidate))
                    changed += 1

                changed_files = 0
                replacements = 0
                if slug_changes:
                    changed_files, replacements = self.update_slug_references(slug_changes)
        except Exception as exc:
            QMessageBox.critical(self, "批量更新 slug 失败", str(exc))
            return

        if changed:
            self.mark_modified(True)
            self.load_blog()
        self.set_status(
            f"slug 更新完成：写入 {changed} 个；"
            f"同步替换 {changed_files} 个文件中的 {replacements} 处引用。"
        )

    def cover_reference_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        all_items: List[ContentRecord | TaxonomyRecord] = self.posts + self.projects
        all_items += self.taxonomies["category"] + self.taxonomies["series"]
        for item in all_items:
            if not item.cover or is_web_url(item.cover):
                continue
            base = item.bundle_dir if isinstance(item, ContentRecord) else item.folder
            path = local_cover_path(item.cover, self.cfg.root, base)
            if path:
                key = os.path.normcase(str(path.resolve()))
                counts[key] = counts.get(key, 0) + 1
        return counts

    def rename_cover_for_record(self, record: ContentRecord, reference_counts: Dict[str, int]) -> None:
        if not record.cover or is_web_url(record.cover):
            return
        source = local_cover_path(record.cover, self.cfg.root, record.bundle_dir)
        if source is None or not source.is_file():
            return
        suffix = source.suffix.lower() or ".png"
        stem = sanitize_cover_filename_stem(record.slug, record.bundle_dir.name)

        is_static_cover = record.cover.startswith("/")
        directory = ensure_dir(self.cfg.root / "static" / "covers") if is_static_cover else record.bundle_dir
        preferred = directory / f"{stem}{suffix}"
        try:
            same_path = source.resolve() == preferred.resolve()
        except OSError:
            same_path = source == preferred
        if same_path:
            record.cover = f"/covers/{preferred.name}" if is_static_cover else preferred.name
            return

        target = preferred if not preferred.exists() else unique_cover_path(directory, stem, suffix)
        key = os.path.normcase(str(source.resolve()))
        shared = reference_counts.get(key, 0) > 1
        if shared:
            shutil.copy2(source, target)
        else:
            rename_path_with_retry(source, target)
        record.cover = f"/covers/{target.name}" if is_static_cover else target.name

    def stop_hugo_for_directory_operation(self) -> bool:
        """
        在批量重命名目录前停止由本程序启动的 Hugo。

        Windows 下 Hugo 的文件监视器可能短暂锁定 content 目录，
        这是 WinError 32 的常见来源。
        """
        process = self.hugo_process
        if not process or process.state() == QProcess.ProcessState.NotRunning:
            return False

        self.set_status("正在停止 Hugo，以释放文章目录占用……")
        self._hugo_stop_requested = True
        process.terminate()
        if not process.waitForFinished(5000):
            process.kill()
            if not process.waitForFinished(3000):
                raise RuntimeError("无法停止 Hugo 进程，目录重命名已取消。")
        QApplication.processEvents()
        return True

    def restart_hugo_after_directory_operation(self) -> None:
        """目录操作结束后静默恢复此前由本程序启动的 Hugo。"""
        if self.hugo_process and self.hugo_process.state() != QProcess.ProcessState.NotRunning:
            return
        self._suppress_hugo_browser_once = True
        QTimer.singleShot(350, self.toggle_hugo)

    def release_manager_directory_handles(self) -> None:
        """尽量释放管理器自身对内容目录的临时引用，降低目录改名误报占用。

        Windows 的原生文件对话框、当前工作目录、选中项焦点和刚结束的文件扫描
        都可能让目录改名在短时间内返回 WinError 32/5。这里不清空数据模型，
        只释放 UI 焦点、把进程工作目录移出博客目录，并给 Qt 与 GC 一个短暂窗口。
        """
        for widget_name in (
            "post_table",
            "project_table",
            "resource_tree",
            "category_list",
            "series_list",
            "tag_list",
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.clearSelection()
            except Exception:
                pass
            try:
                widget.clearFocus()
            except Exception:
                pass

        try:
            current = Path.cwd().resolve()
            root = Path(self.cfg.root).resolve()
            if current == root or root in current.parents:
                os.chdir(program_dir())
        except Exception:
            try:
                os.chdir(program_dir())
            except Exception:
                pass

        QApplication.processEvents()
        gc.collect()
        time_module.sleep(0.25)
        QApplication.processEvents()

    def probe_content_directories_available(
        self,
        rename_targets: List[ContentRecord],
        root: Path,
    ) -> List[str]:
        """
        通过一次“临时改名再改回”的轻量探测确认目录当前可重命名。

        Windows 下文件被编辑器、资源管理器预览、Hugo watcher 或杀毒软件占用时，
        真正重命名会触发 WinError 32/5。这里在正式改名之前集中探测；
        只要任一目录不可改名，就禁止后续批量操作，避免部分完成后再回滚。
        """
        self.release_manager_directory_handles()
        occupied: List[str] = []
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        for index, record in enumerate(rename_targets):
            source = Path(record.bundle_dir)
            if not source.exists():
                occupied.append(f"{record.title}\n{source}\n原因：源目录不存在。")
                continue
            probe = Path(root) / f".__lbm_probe_{stamp}_{index}"
            suffix = 2
            while probe.exists():
                probe = Path(root) / f".__lbm_probe_{stamp}_{index}_{suffix}"
                suffix += 1
            moved = False
            try:
                rename_path_with_retry(source, probe, timeout=4.0, interval=0.2)
                moved = True
                rename_path_with_retry(probe, source, timeout=4.0, interval=0.2)
                moved = False
            except Exception as exc:
                if moved and probe.exists() and not source.exists():
                    try:
                        rename_path_with_retry(probe, source, timeout=3.0, interval=0.2)
                    except Exception:
                        pass
                occupied.append(f"{record.title}\n{source}\n原因：{exc}")
        return occupied

    def rename_content_directories(self, kind: str) -> None:
        records = list(self.records_for_kind(kind))
        if not records:
            self.set_status("没有需要重命名的目录。")
            return

        label = "文章" if kind == "post" else "项目"
        duplicate_slugs = sorted({
            record.slug
            for record in records
            if sum(
                1
                for other in records
                if other.slug.casefold() == record.slug.casefold()
            ) > 1
        })
        if duplicate_slugs:
            QMessageBox.critical(
                self,
                "无法重命名",
                "存在重复 slug：\n" + "\n".join(duplicate_slugs),
            )
            return

        invalid = [
            record.title
            for record in records
            if not SLUG_RE.match(record.slug)
        ]
        if invalid:
            QMessageBox.critical(
                self,
                "无法重命名",
                "以下条目的 slug 无效：\n" + "\n".join(invalid[:20]),
            )
            return

        root = self.cfg.posts if kind == "post" else self.cfg.projects
        source_keys = {
            os.path.normcase(str(record.bundle_dir.resolve()))
            for record in records
        }
        conflicts: List[str] = []
        for record in records:
            target = root / record.slug
            target_key = os.path.normcase(str(target.resolve()))
            if target.exists() and target_key not in source_keys:
                conflicts.append(str(target))
        if conflicts:
            QMessageBox.critical(
                self,
                "目录冲突",
                "以下目标目录已被其他内容占用：\n"
                + "\n".join(conflicts[:20]),
            )
            return

        rename_targets = [
            record
            for record in records
            if record.bundle_dir.name != record.slug
        ]
        if not rename_targets:
            self.set_status(f"全部{label}目录已经与 slug 一致。")
            return

        reply = QMessageBox.question(
            self,
            f"按 slug 更改{label}目录",
            f"将重命名 {len(rename_targets)} 个{label}目录，"
            "并同步更新其封面文件名。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        staged: List[Tuple[ContentRecord, Path, Path, Path]] = []
        finalized: List[Tuple[ContentRecord, Path, Path]] = []
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        hugo_was_running = False
        operation_error: Optional[Exception] = None

        try:
            hugo_was_running = self.stop_hugo_for_directory_operation()
            self.set_status("正在检测目录是否被占用……")
            QApplication.processEvents()
            occupied = self.probe_content_directories_available(rename_targets, root)
        except Exception as exc:
            if hugo_was_running:
                self.restart_hugo_after_directory_operation()
            QMessageBox.critical(self, "目录占用检测失败", str(exc))
            return

        if occupied:
            if hugo_was_running:
                self.restart_hugo_after_directory_operation()
            QMessageBox.critical(
                self,
                "目录被占用",
                "以下目录当前无法重命名，已禁止更改操作。请关闭正在打开这些目录或其中 Markdown/图片文件的程序后重试：\n\n"
                + "\n\n".join(occupied[:10]),
            )
            return

        references = self.cover_reference_counts()
        self.begin_bulk_progress(
            f"正在重命名 {len(rename_targets)} 个{label}目录……",
            max(1, len(rename_targets) * 2 + len(records)),
        )
        progress_value = 0

        try:
            self.release_manager_directory_handles()
            # 第一阶段：全部移入唯一临时目录，支持两个目录互换名称。
            for index, record in enumerate(rename_targets):
                old = record.bundle_dir
                target = root / record.slug
                temp = root / f".__lbm_tmp_{stamp}_{index}"
                rename_path_with_retry(old, temp)
                staged.append((record, old, temp, target))

                progress_value += 1
                self.progress.setValue(progress_value)
                self.set_status(
                    f"正在暂存目录：{progress_value}/{len(rename_targets)}"
                )
                QApplication.processEvents()

            # 第二阶段：从临时目录移动到最终 slug 目录。
            for record, old, temp, target in staged:
                rename_path_with_retry(temp, target)
                record.bundle_dir = target
                record.md_path = target / "index.md"
                record.section_files = [
                    target / path.name
                    for path in record.section_files
                ]
                finalized.append((record, old, target))

                progress_value += 1
                self.progress.setValue(progress_value)
                self.set_status(
                    f"正在写入最终目录："
                    f"{progress_value - len(rename_targets)}/"
                    f"{len(rename_targets)}"
                )
                QApplication.processEvents()

            # 更新封面名称及 index.md。
            for record in records:
                self.rename_cover_for_record(record, references)
                write_content(record, self.cfg)

                progress_value += 1
                self.progress.setValue(progress_value)
                QApplication.processEvents()

        except Exception as exc:
            operation_error = exc

            # 先回滚已经进入最终目录的项目。
            for record, old, target in reversed(finalized):
                try:
                    if target.exists() and not old.exists():
                        rename_path_with_retry(
                            target,
                            old,
                            timeout=5.0,
                        )
                    record.bundle_dir = old
                    record.md_path = old / "index.md"
                    record.section_files = [
                        old / path.name
                        for path in record.section_files
                    ]
                except Exception:
                    pass

            # 再回滚尚处于临时目录的项目。
            for record, old, temp, _target in reversed(staged):
                try:
                    if temp.exists() and not old.exists():
                        rename_path_with_retry(
                            temp,
                            old,
                            timeout=5.0,
                        )
                    record.bundle_dir = old
                    record.md_path = old / "index.md"
                    record.section_files = [
                        old / path.name
                        for path in record.section_files
                    ]
                except Exception:
                    pass

        finally:
            self.end_bulk_progress()
            if hugo_was_running:
                self.restart_hugo_after_directory_operation()

        if operation_error is not None:
            self.set_status("目录重命名失败，已尝试回滚。")
            QMessageBox.critical(
                self,
                "目录重命名失败",
                str(operation_error),
            )
            return

        self.mark_modified(True)
        self.load_blog()
        self.set_status(
            f"已按 slug 更新 {len(rename_targets)} 个{label}目录及封面名称。"
        )

    def new_content(self, kind: str) -> None:
        dlg = NewContentDialog(
            kind,
            self.all_categories(),
            self.all_tags(),
            self.all_series(),
            self.suggest_slug,
            self.select_file,
            self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        root = self.cfg.posts if kind == "post" else self.cfg.projects
        folder = root / vals["slug"]
        if folder.exists():
            QMessageBox.warning(self, "slug 重复", f"目录已存在：{folder}")
            return
        ensure_dir(folder)
        cover = ""
        if vals["cover_path"]:
            try:
                with self.waiting(
                    "正在压缩并添加封面……"
                    if vals.get("cover_compress")
                    else "正在添加封面……"
                ):
                    cover, before, after = install_cover_to_static(
                        Path(vals["cover_path"]),
                        self.cfg.root,
                        folder.name,
                        compress=bool(vals.get("cover_compress")),
                    )
                if vals.get("cover_compress"):
                    self.set_status(
                        f"封面已添加并优化：{self.compression_result_text(before, after)}"
                    )
            except Exception as exc:
                shutil.rmtree(folder, ignore_errors=True)
                QMessageBox.critical(self, "封面处理失败", str(exc))
                return
        created = now_iso()
        meta = {
            "title": vals["title"],
            "date": created,
            "lastmod": created,
            "draft": True,
            "slug": vals["slug"],
            "description": vals["description"],
            "summary": vals["summary"],
            "tags": vals["tags"],
            "categories": vals["categories"],
            "cover": cover,
        }
        body = ""
        if kind == "post":
            meta["series"] = vals["series"]
            meta["series_order"] = [self.next_series_order(series) for series in vals["series"]]
        else:
            meta["homepage"] = vals["homepage"]
            meta["featured"] = vals["featured"]
            meta["link"] = vals["link"] or None
            meta["status"] = vals["status"]
        md = folder / "index.md"
        rec = parse_content(md, kind) if md.exists() else ContentRecord(
            kind=kind,
            title=vals["title"],
            slug=vals["slug"],
            date=created,
            lastmod=created,
            draft=True,
            homepage=vals["homepage"],
            description=vals["description"],
            summary=vals["summary"],
            tags=vals["tags"],
            categories=vals["categories"],
            series=vals["series"],
            cover=cover,
            md_path=md,
            bundle_dir=folder,
            body=body,
            meta=meta,
            index_body=body,
            section_files=[],
            series_order=parse_series_orders(meta.get("series_order"), len(vals["series"])) if kind == "post" else [],
            featured=vals["featured"],
            link=vals["link"],
            status=vals["status"],
        )
        write_content(rec, self.cfg)
        self.ensure_taxonomies_for_record(rec)
        self.mark_modified(True)
        self.load_blog()

    def ensure_taxonomies_for_record(self, rec: ContentRecord) -> None:
        for kind, values in [("category", rec.categories), ("tag", rec.tags), ("series", rec.series)]:
            for value in values:
                root = self.cfg.taxonomy_root(kind)
                folder = root / value
                ensure_dir(folder)
                index = folder / "_index.md"
                if not index.exists():
                    tax = TaxonomyRecord(kind, value, value, "", "", index, folder, "", {})
                    write_taxonomy(tax)

    def write_record(self, rec: ContentRecord) -> None:
        rec.lastmod = now_iso()
        write_content(rec, self.cfg)
        self.ensure_taxonomies_for_record(rec)
        self.mark_modified(True)
        self.load_blog()
