from core import *


class SuggestionDialog(QDialog):
    def __init__(self, title: str, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("AI 返回结果，可在接收前继续修改："))
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(text.strip())
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        accept_btn = QPushButton("接收")
        reject_btn = QPushButton("拒绝")
        accept_btn.clicked.connect(self.accept)
        reject_btn.clicked.connect(self.reject)
        row.addWidget(accept_btn)
        row.addWidget(reject_btn)
        layout.addLayout(row)

    def text(self) -> str:
        return self.editor.toPlainText().strip()


class TextDialog(QDialog):
    def __init__(
        self,
        title: str,
        label: str,
        text: str = "",
        multiline: bool = False,
        parent: Optional[QWidget] = None,
        ai_button_text: str = "",
        ai_callback: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 360 if multiline else 150)
        self.ai_callback = ai_callback
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
        self.multiline = multiline
        self.editor: QLineEdit | QPlainTextEdit
        if multiline:
            self.editor = QPlainTextEdit()
            self.editor.setPlainText(text)
        else:
            self.editor = QLineEdit(text)
        layout.addWidget(self.editor)
        row = QHBoxLayout()
        if ai_callback:
            ai_btn = QPushButton(ai_button_text or "AI 生成")
            ai_btn.clicked.connect(self.run_ai)
            row.addWidget(ai_btn)
        row.addStretch(1)
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def run_ai(self) -> None:
        if not self.ai_callback:
            return
        suggestion = self.ai_callback()
        if not suggestion:
            return
        preview = SuggestionDialog("AI 建议", suggestion, self)
        if preview.exec() == QDialog.DialogCode.Accepted:
            if self.multiline:
                self.editor.setPlainText(preview.text())  # type: ignore[union-attr]
            else:
                self.editor.setText(preview.text())  # type: ignore[union-attr]

    def text(self) -> str:
        if self.multiline:
            return self.editor.toPlainText().strip()  # type: ignore[union-attr]
        return self.editor.text().strip()  # type: ignore[union-attr]


class BrokenReferencesDialog(QDialog):
    def __init__(
        self,
        refs: List[BrokenReference],
        root: Path,
        opener: Callable[[Path], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("引用检查结果")
        self.resize(820, 460)
        self.refs = refs
        self.opener = opener
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"发现 {len(refs)} 处无效引用。双击行或点击按钮可打开所在文件。"))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["类型", "无效 slug", "所在文件", "行号", "打开"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda row, _col: self.open_ref(row))
        layout.addWidget(self.table, 1)

        for row, ref in enumerate(refs):
            self.table.insertRow(row)
            values = [
                "文章" if ref.kind == "post" else "项目",
                ref.slug,
                rel_path(ref.path, root),
                str(ref.line),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(ref.context if col == 2 else value)
                self.table.setItem(row, col, item)
            button = QPushButton("打开")
            button.clicked.connect(lambda _checked=False, r=row: self.open_ref(r))
            self.table.setCellWidget(row, 4, button)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

    def open_ref(self, row: int) -> None:
        if 0 <= row < len(self.refs):
            self.opener(self.refs[row].path)


class MergeTagsDialog(QDialog):
    def __init__(
        self,
        suggestions: List[TagMergeSuggestion],
        all_tags: List[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("合并相似标签")
        self.resize(860, 500)
        self.suggestions = suggestions
        self.checks: List[QCheckBox] = []
        self.targets: List[QComboBox] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选要合并的标签组，并选择或输入最终保留的标签名。"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["合并", "相似标签", "合并为", "原因"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        tag_pool = unique(all_tags)
        for row, suggestion in enumerate(suggestions):
            self.table.insertRow(row)
            check = QCheckBox()
            check.setChecked(True)
            self.checks.append(check)
            self.table.setCellWidget(row, 0, check)

            tags_text = "；".join(suggestion.tags)
            tags_item = QTableWidgetItem(tags_text)
            tags_item.setToolTip(tags_text)
            tags_item.setFlags(tags_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, tags_item)

            combo = QComboBox()
            combo.setEditable(True)
            candidates = unique([suggestion.target] + suggestion.tags + tag_pool)
            combo.addItems(candidates)
            combo.setCurrentText(suggestion.target or (suggestion.tags[0] if suggestion.tags else ""))
            self.targets.append(combo)
            self.table.setCellWidget(row, 2, combo)

            reason_item = QTableWidgetItem(suggestion.reason)
            reason_item.setToolTip(suggestion.reason)
            reason_item.setFlags(reason_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, reason_item)

        buttons = QHBoxLayout()
        select_all = QPushButton("全选")
        select_all.clicked.connect(lambda: self.set_all(True))
        clear_all = QPushButton("全不选")
        clear_all.clicked.connect(lambda: self.set_all(False))
        buttons.addWidget(select_all)
        buttons.addWidget(clear_all)
        buttons.addStretch(1)
        ok = QPushButton("执行合并")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def set_all(self, checked: bool) -> None:
        for check in self.checks:
            check.setChecked(checked)

    def accept_checked(self) -> None:
        if not self.values():
            QMessageBox.warning(self, "没有选择", "请至少选择一个要合并的标签组。")
            return
        self.accept()

    def values(self) -> List[Tuple[List[str], str]]:
        result: List[Tuple[List[str], str]] = []
        for suggestion, check, combo in zip(self.suggestions, self.checks, self.targets):
            if not check.isChecked():
                continue
            target = combo.currentText().strip()
            tags = unique(suggestion.tags)
            if target and tags:
                result.append((tags, target))
        return result


class CheckableListDelegate(QStyledItemDelegate):
    """为可勾选列表绘制高对比度复选框，避免系统主题下勾选状态不明显。"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator

        opt.palette.setColor(QPalette.ColorRole.Highlight, QColor("#bfdbfe"))
        opt.palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0f172a"))
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        state = index.data(Qt.ItemDataRole.CheckStateRole)
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)

        painter.save()
        box_size = 18
        box = QRect(
            option.rect.left() + 8,
            option.rect.center().y() - box_size // 2,
            box_size,
            box_size,
        )

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if checked:
            painter.setPen(QPen(QColor("#1e3a8a"), 1))
            painter.setBrush(QColor("#2563eb"))
        else:
            painter.setPen(QPen(QColor("#64748b"), 2))
            painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(box, 4, 4)

        if checked:
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawLine(box.left() + 4, box.center().y(), box.left() + 8, box.bottom() - 4)
            painter.drawLine(box.left() + 8, box.bottom() - 4, box.right() - 3, box.top() + 4)

        text_rect = QRect(
            box.right() + 10,
            option.rect.top(),
            max(0, option.rect.right() - box.right() - 14),
            option.rect.height(),
        )
        font = option.font
        font.setBold(checked)
        painter.setFont(font)
        painter.setPen(QColor("#0f172a"))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # type: ignore[override]
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 32))
        return size


class ListDialog(QDialog):
    def __init__(
        self,
        title: str,
        available: List[str],
        selected: List[str],
        parent: Optional[QWidget] = None,
        count_range: Tuple[int, int] = (1, 3),
        ai_select: Optional[Callable[[int], List[str]]] = None,
        ai_summarize: Optional[Callable[[int], List[str]]] = None,
        ai_suggest: Optional[Callable[[int], List[str]]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 600)
        self.ai_select = ai_select
        self.ai_summarize = ai_summarize
        self.ai_suggest = ai_suggest
        self._moving_item = False
        layout = QVBoxLayout(self)

        select_row = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        clear_all_btn = QPushButton("全不选")
        select_all_btn.clicked.connect(lambda: self.set_all_checked(True))
        clear_all_btn.clicked.connect(lambda: self.set_all_checked(False))
        select_row.addWidget(select_all_btn)
        select_row.addWidget(clear_all_btn)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        self.list = QListWidget()
        self.list.setItemDelegate(CheckableListDelegate(self.list))
        self.list.setSpacing(2)
        layout.addWidget(self.list, 1)

        self.collapsed_button = QToolButton()
        self.collapsed_button.setCheckable(True)
        self.collapsed_button.setChecked(False)
        self.collapsed_button.setArrowType(Qt.ArrowType.RightArrow)
        self.collapsed_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.collapsed_button.toggled.connect(self.toggle_collapsed)
        layout.addWidget(self.collapsed_button)

        self.collapsed_list = QListWidget()
        self.collapsed_list.setItemDelegate(CheckableListDelegate(self.collapsed_list))
        self.collapsed_list.setSpacing(2)
        self.collapsed_list.setVisible(False)
        self.collapsed_list.setMaximumHeight(220)
        self.collapsed_list.itemChanged.connect(self.on_collapsed_item_changed)
        layout.addWidget(self.collapsed_list)

        selected_values = unique(selected)
        selected_keys = {value.casefold() for value in selected_values}
        for value in selected_values:
            self.list.addItem(self.make_item(value, True))
        for value in unique(available):
            if value.casefold() not in selected_keys:
                self.collapsed_list.addItem(self.make_item(value, False))
        self.update_collapsed_label()

        if ai_select or ai_summarize or ai_suggest:
            ai_row = QHBoxLayout()
            ai_row.addWidget(QLabel("AI 数量"))
            self.ai_count = QSpinBox()
            self.ai_count.setRange(1, 2_147_483_647)
            self.ai_count.setValue(max(1, count_range[1]))
            ai_row.addWidget(self.ai_count)
            if ai_select:
                btn = QPushButton("AI 选取")
                btn.clicked.connect(lambda: self.run_ai("select"))
                ai_row.addWidget(btn)
            if ai_summarize:
                btn = QPushButton("AI 总结")
                btn.clicked.connect(lambda: self.run_ai("summarize"))
                ai_row.addWidget(btn)
            if ai_suggest:
                btn = QPushButton("AI 建议")
                btn.clicked.connect(lambda: self.run_ai("suggest"))
                ai_row.addWidget(btn)
            ai_row.addStretch(1)
            layout.addLayout(ai_row)
        else:
            self.ai_count = QSpinBox()

        row = QHBoxLayout()
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("新增条目，回车添加")
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self.add_value)
        self.add_edit.returnPressed.connect(self.add_value)
        row.addWidget(self.add_edit, 1)
        row.addWidget(add_btn)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def make_item(self, value: str, checked: bool) -> QListWidgetItem:
        item = QListWidgetItem(value)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def toggle_collapsed(self, expanded: bool) -> None:
        self.collapsed_list.setVisible(expanded)
        self.collapsed_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def update_collapsed_label(self) -> None:
        self.collapsed_button.setText(f"未选择条目（{self.collapsed_list.count()}）")
        self.collapsed_button.setVisible(self.collapsed_list.count() > 0)
        if self.collapsed_list.count() == 0:
            self.collapsed_list.setVisible(False)
            self.collapsed_button.setChecked(False)

    def on_collapsed_item_changed(self, item: QListWidgetItem) -> None:
        if self._moving_item or item.checkState() != Qt.CheckState.Checked:
            return
        row = self.collapsed_list.row(item)
        self._moving_item = True
        moved = self.collapsed_list.takeItem(row)
        moved.setCheckState(Qt.CheckState.Checked)
        self.list.insertItem(0, moved)
        self.list.setCurrentItem(moved)
        self._moving_item = False
        self.update_collapsed_label()

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        if checked:
            hidden_values = [self.collapsed_list.item(i).text() for i in range(self.collapsed_list.count())]
            for value in reversed(hidden_values):
                self.promote_value(value, checked=True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        if not checked:
            for i in range(self.collapsed_list.count()):
                self.collapsed_list.item(i).setCheckState(state)

    def run_ai(self, mode: str) -> None:
        callback = {
            "select": self.ai_select,
            "summarize": self.ai_summarize,
            "suggest": self.ai_suggest,
        }.get(mode)
        if not callback:
            return
        values = unique(callback(self.ai_count.value()))
        if not values:
            return
        title = {"select": "AI 选取结果", "summarize": "AI 总结结果", "suggest": "AI 建议结果"}[mode]
        reply = QMessageBox.question(
            self,
            title,
            "是否把以下条目加入并勾选？\n\n" + "\n".join(f"• {x}" for x in values),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.apply_values(values)

    def find_row(self, widget: QListWidget, value: str) -> int:
        key = value.casefold()
        for i in range(widget.count()):
            if widget.item(i).text().casefold() == key:
                return i
        return -1

    def promote_value(self, value: str, checked: bool = True) -> None:
        main_row = self.find_row(self.list, value)
        if main_row >= 0:
            item = self.list.takeItem(main_row)
        else:
            hidden_row = self.find_row(self.collapsed_list, value)
            if hidden_row >= 0:
                self._moving_item = True
                item = self.collapsed_list.takeItem(hidden_row)
                self._moving_item = False
            else:
                item = self.make_item(value, checked)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.insertItem(0, item)
        self.list.setCurrentItem(item)
        self.update_collapsed_label()

    def apply_values(self, values: List[str]) -> None:
        # 逆序插入，保证 AI/用户返回的第一个条目最终位于最前面。
        for value in reversed(unique(values)):
            self.promote_value(value, checked=True)

    def add_value(self) -> None:
        value = self.add_edit.text().strip()
        if not value:
            return
        self.apply_values([value])
        self.add_edit.clear()

    def values(self) -> List[str]:
        out = []
        for widget in (self.list, self.collapsed_list):
            for i in range(widget.count()):
                item = widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    out.append(item.text())
        return unique(out)


class SeriesOrderDialog(QDialog):
    def __init__(
        self,
        series_name: str,
        members: List[Tuple[ContentRecord, int]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"系列文章排序：{series_name}")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("可以直接修改序号，也可以选择文章后使用上移/下移。序号必须为互不重复的正整数。"))

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["序号", "文章标题"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        layout.addWidget(self.table, 1)

        for rec, order in members:
            row = self.table.rowCount()
            self.table.insertRow(row)
            order_item = QTableWidgetItem(str(order))
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            title_item = QTableWidgetItem(rec.title)
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            title_item.setData(Qt.ItemDataRole.UserRole, str(rec.md_path))
            self.table.setItem(row, 0, order_item)
            self.table.setItem(row, 1, title_item)

        move_row = QHBoxLayout()
        up_btn = QPushButton("上移")
        down_btn = QPushButton("下移")
        normalize_btn = QPushButton("按当前顺序重新编号")
        up_btn.clicked.connect(lambda: self.move_selected(-1))
        down_btn.clicked.connect(lambda: self.move_selected(1))
        normalize_btn.clicked.connect(self.normalize_orders)
        move_row.addWidget(up_btn)
        move_row.addWidget(down_btn)
        move_row.addWidget(normalize_btn)
        move_row.addStretch(1)
        layout.addLayout(move_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("保存排序")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def swap_rows(self, first: int, second: int) -> None:
        for col in range(self.table.columnCount()):
            first_item = self.table.takeItem(first, col)
            second_item = self.table.takeItem(second, col)
            self.table.setItem(first, col, second_item)
            self.table.setItem(second, col, first_item)

    def move_selected(self, direction: int) -> None:
        row = self.table.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        self.swap_rows(row, target)
        self.normalize_orders()
        self.table.selectRow(target)

    def normalize_orders(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setText(str(row + 1))

    def accept_checked(self) -> None:
        seen: set[int] = set()
        for row in range(self.table.rowCount()):
            try:
                value = int(self.table.item(row, 0).text().strip())
            except (TypeError, ValueError):
                QMessageBox.warning(self, "序号无效", f"第 {row + 1} 行的序号不是整数。")
                return
            if value <= 0:
                QMessageBox.warning(self, "序号无效", "系列序号必须为正整数。")
                return
            if value in seen:
                QMessageBox.warning(self, "序号重复", f"序号 {value} 被重复使用。")
                return
            seen.add(value)
        self.accept()

    def values(self) -> List[Tuple[Path, int]]:
        result: List[Tuple[Path, int]] = []
        for row in range(self.table.rowCount()):
            path = Path(self.table.item(row, 1).data(Qt.ItemDataRole.UserRole))
            order = int(self.table.item(row, 0).text().strip())
            result.append((path, order))
        return result


class SlugDialog(QDialog):
    def __init__(
        self,
        current_slug: str,
        aliases: List[str],
        ai_callback: Callable[[], Optional[str]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改 slug")
        self.resize(560, 210)
        self.ai_callback = ai_callback
        self.aliases = unique(aliases)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.slug_edit = QLineEdit(current_slug)
        self.alias_label = QLabel(self.alias_text())
        self.alias_label.setWordWrap(True)
        form.addRow("当前 slug", self.slug_edit)
        form.addRow("Hugo aliases", self.alias_label)
        layout.addLayout(form)
        row = QHBoxLayout()
        ai_btn = QPushButton("AI 生成 slug")
        ai_btn.clicked.connect(self.generate_ai_slug)
        row.addWidget(ai_btn)
        row.addStretch(1)
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def alias_text(self) -> str:
        return "、".join(self.aliases) if self.aliases else "无"

    def generate_ai_slug(self) -> None:
        candidate = self.ai_callback()
        if not candidate:
            return
        candidate = sanitize_slug_guess(candidate)
        box = QMessageBox(self)
        box.setWindowTitle("AI slug 建议")
        box.setText(f"AI 建议：{candidate}")
        box.setInformativeText("可替换当前 slug，或保留当前 slug 并把新值加入 Hugo aliases。")
        replace_btn = box.addButton("替换原 slug", QMessageBox.ButtonRole.AcceptRole)
        alias_btn = box.addButton("新增为别名", QMessageBox.ButtonRole.ActionRole)
        box.addButton("拒绝", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace_btn:
            self.slug_edit.setText(candidate)
        elif clicked is alias_btn:
            alias = f"/{candidate}/"
            self.aliases = unique(self.aliases + [alias])
            self.alias_label.setText(self.alias_text())

    def accept_checked(self) -> None:
        value = self.slug_edit.text().strip()
        if not SLUG_RE.match(value):
            QMessageBox.warning(self, "slug 无效", "只能使用英文小写、数字和短横线。")
            return
        self.accept()

    def values(self) -> Tuple[str, List[str]]:
        return self.slug_edit.text().strip(), self.aliases


class NewContentDialog(QDialog):
    def __init__(
        self,
        kind: str,
        categories: List[str],
        tags: List[str],
        series: List[str],
        slug_generator: Callable[[str], str],
        file_picker: Callable[[QWidget, str, str], str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.slug_generator = slug_generator
        self.file_picker = file_picker
        self.cover_path = ""
        self.setWindowTitle("新建文章" if kind == "post" else "新建项目")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.slug_edit = QLineEdit()
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(70)
        self.summary_edit = QPlainTextEdit()
        self.summary_edit.setFixedHeight(70)
        self.cat_edit = QLineEdit()
        self.tag_edit = QLineEdit()
        self.series_edit = QLineEdit()
        self.featured_check = QCheckBox("精选项目")
        self.homepage_check = QCheckBox("首页展示")
        self.status_combo = QComboBox()
        self.status_combo.addItems(["planning", "in_progress", "completed", "paused"])
        self.link_edit = QLineEdit()
        self.cover_label = QLabel("未选择")
        self.cover_compress_check = QCheckBox("无损压缩封面")
        slug_row = QHBoxLayout()
        slug_row.addWidget(self.slug_edit, 1)
        ai_btn = QPushButton("AI 生成 slug")
        ai_btn.clicked.connect(self.generate_slug)
        slug_row.addWidget(ai_btn)
        cover_row = QHBoxLayout()
        cover_row.addWidget(self.cover_label, 1)
        cover_btn = QPushButton("选择封面")
        cover_btn.clicked.connect(self.choose_cover)
        cover_row.addWidget(cover_btn)
        self.cat_edit.setToolTip("已有分类：" + ", ".join(categories))
        self.tag_edit.setToolTip("已有标签：" + ", ".join(tags))
        self.series_edit.setToolTip("已有系列：" + ", ".join(series))
        form.addRow("标题", self.title_edit)
        form.addRow("英文 slug", slug_row)
        form.addRow("描述", self.desc_edit)
        form.addRow("摘要", self.summary_edit)
        form.addRow("分类", self.cat_edit)
        form.addRow("标签", self.tag_edit)
        if kind == "post":
            form.addRow("系列", self.series_edit)
        else:
            form.addRow("状态", self.status_combo)
            form.addRow("外部链接", self.link_edit)
            form.addRow("", self.featured_check)
        form.addRow("", self.homepage_check)
        form.addRow("封面", cover_row)
        form.addRow("", self.cover_compress_check)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("创建")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def generate_slug(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "缺少标题", "请先输入标题。")
            return
        self.slug_edit.setText(self.slug_generator(title))

    def choose_cover(self) -> None:
        path = self.file_picker(self, "选择封面图片", IMAGE_FILTER)
        if path:
            self.cover_path = path
            self.cover_label.setText(path)

    def accept_checked(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "缺少标题", "请输入标题。")
            return
        if not SLUG_RE.match(self.slug_edit.text().strip()):
            QMessageBox.warning(self, "slug 无效", "slug 只能使用英文小写、数字和短横线，例如 linear-regression。")
            return
        self.accept()

    def values(self) -> Dict[str, Any]:
        return {
            "title": self.title_edit.text().strip(),
            "slug": self.slug_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "summary": self.summary_edit.toPlainText().strip(),
            "categories": listify(self.cat_edit.text()),
            "tags": listify(self.tag_edit.text()),
            "series": listify(self.series_edit.text()),
            "homepage": self.homepage_check.isChecked(),
            "featured": self.featured_check.isChecked(),
            "status": self.status_combo.currentText(),
            "link": self.link_edit.text().strip(),
            "cover_path": self.cover_path,
            "cover_compress": self.cover_compress_check.isChecked(),
        }


class BulkSlugReviewDialog(QDialog):
    def __init__(
        self,
        rows: List[Tuple[int, str, str, str, str]],
        reserved_slugs: set[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.reserved_slugs = {str(value).casefold() for value in reserved_slugs}
        self.setWindowTitle("确认批量更新 slug")
        self.resize(1020, 640)

        layout = QVBoxLayout(self)
        note = QLabel(
            "AI 已为全部条目生成 slug。默认全部接受；可取消勾选，或直接修改“新 slug”列后再应用。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["接受", "标题", "当前 slug", "新 slug", "路径"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        for row_index, (record_index, title, old_slug, new_slug, path_text) in enumerate(rows):
            self.table.insertRow(row_index)

            check_item = QTableWidgetItem("")
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Checked)
            check_item.setData(Qt.ItemDataRole.UserRole, int(record_index))
            self.table.setItem(row_index, 0, check_item)

            title_item = QTableWidgetItem(title)
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            title_item.setToolTip(title)
            self.table.setItem(row_index, 1, title_item)

            old_item = QTableWidgetItem(old_slug)
            old_item.setFlags(old_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 2, old_item)

            new_item = QTableWidgetItem(new_slug)
            new_item.setToolTip("只能使用英文小写、数字和短横线。")
            self.table.setItem(row_index, 3, new_item)

            path_item = QTableWidgetItem(path_text)
            path_item.setFlags(path_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            path_item.setToolTip(path_text)
            self.table.setItem(row_index, 4, path_item)

        row = QHBoxLayout()
        select_all = QPushButton("全选")
        clear_all = QPushButton("全不选")
        select_all.clicked.connect(lambda: self.set_all_checked(True))
        clear_all.clicked.connect(lambda: self.set_all_checked(False))
        row.addWidget(select_all)
        row.addWidget(clear_all)
        row.addStretch(1)
        ok = QPushButton("应用所选 slug")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def accepted_values(self) -> List[Tuple[int, str]]:
        values: List[Tuple[int, str]] = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            slug_item = self.table.item(row, 3)
            if check_item is None or slug_item is None:
                continue
            if check_item.checkState() != Qt.CheckState.Checked:
                continue
            record_index = int(check_item.data(Qt.ItemDataRole.UserRole))
            values.append((record_index, slug_item.text().strip()))
        return values

    def accept_checked(self) -> None:
        values = self.accepted_values()
        if not values:
            QMessageBox.warning(self, "没有选择", "请至少勾选一个要更新的 slug。")
            return

        unchecked_old_slugs: set[str] = set()
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            old_item = self.table.item(row, 2)
            if check_item is None or old_item is None:
                continue
            if check_item.checkState() != Qt.CheckState.Checked:
                unchecked_old_slugs.add(old_item.text().strip().casefold())

        seen: Dict[str, int] = {}
        invalid: List[str] = []
        duplicated: List[str] = []
        reserved: List[str] = []
        for record_index, slug in values:
            key = slug.casefold()
            if not SLUG_RE.match(slug):
                invalid.append(f"第 {record_index + 1} 行：{slug or '(空)'}")
                continue
            if key in seen:
                duplicated.append(slug)
            else:
                seen[key] = record_index
            if key in self.reserved_slugs or key in unchecked_old_slugs:
                reserved.append(slug)

        if invalid:
            QMessageBox.warning(
                self,
                "slug 无效",
                "以下 slug 无效，只能使用英文小写、数字和短横线：\n"
                + "\n".join(invalid[:30]),
            )
            return
        if duplicated:
            QMessageBox.warning(
                self,
                "slug 重复",
                "以下新 slug 在所选列表中重复：\n" + "\n".join(unique(duplicated)[:30]),
            )
            return
        if reserved:
            QMessageBox.warning(
                self,
                "slug 冲突",
                "以下新 slug 已被未参与本次更新的内容使用：\n" + "\n".join(unique(reserved)[:30]),
            )
            return
        self.accept()


class DateRangeDialog(QDialog):
    def __init__(
        self,
        title: str,
        start_default: date,
        end_default: date,
        item_count: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(470, 220)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            f"将按当前列表顺序为 {item_count} 个条目重新分配创建时间。\n"
            "列表最下方对应最早时间，最上方对应最新时间；每天只使用 09:00—23:00。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.start_edit = QDateEdit(QDate(start_default.year, start_default.month, start_default.day))
        self.end_edit = QDateEdit(QDate(end_default.year, end_default.month, end_default.day))
        for editor in (self.start_edit, self.end_edit):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd")
        form.addRow("开始日期", self.start_edit)
        form.addRow("结束日期", self.end_edit)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("开始随机化")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def accept_checked(self) -> None:
        if self.end_date() < self.start_date():
            QMessageBox.warning(self, "日期范围无效", "结束日期不能早于开始日期。")
            return
        self.accept()

    def start_date(self) -> date:
        value = self.start_edit.date()
        return date(value.year(), value.month(), value.day())

    def end_date(self) -> date:
        value = self.end_edit.date()
        return date(value.year(), value.month(), value.day())


class LongFormSplitDialog(QDialog):
    def __init__(
        self,
        rec: ContentRecord,
        blocks: List[MarkdownHeadingBlock],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.blocks = blocks
        self.block_word_counts = [markdown_word_count(block.text) for block in blocks]
        self.setWindowTitle("长篇分节")
        self.resize(900, 620)

        layout = QVBoxLayout(self)
        label = QLabel(
            f"将“{rec.title}”按一级标题拆成多个文章/项目。"
            "先选择分为几节，程序会按字数自动均分；你仍可手动调整每个一级标题所属节。"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        form = QFormLayout()
        self.count_spin = QSpinBox()
        self.count_spin.setRange(2, max(2, len(blocks)))
        self.count_spin.setValue(min(2, max(2, len(blocks))))
        form.addRow("分节数量", self.count_spin)
        layout.addLayout(form)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["所属节", "一级标题", "字数", "来源文件"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        for row, block in enumerate(blocks):
            self.table.insertRow(row)
            combo = QComboBox()
            combo.currentIndexChanged.connect(lambda _index, self=self: self.update_section_totals())
            self.table.setCellWidget(row, 0, combo)
            title_item = QTableWidgetItem(block.title)
            title_item.setToolTip(block.title)
            words_item = QTableWidgetItem(str(self.block_word_counts[row]))
            words_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            source_item = QTableWidgetItem(block.source_path.name)
            source_item.setToolTip(str(block.source_path))
            self.table.setItem(row, 1, title_item)
            self.table.setItem(row, 2, words_item)
            self.table.setItem(row, 3, source_item)

        self.total_label = QLabel("")
        self.total_label.setWordWrap(True)
        layout.addWidget(self.total_label)

        helper = QLabel("提示：每一节至少要包含一个一级标题；拆分后会自动重编号分片文件并写入 sections。")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        buttons = QHBoxLayout()
        rebalance_btn = QPushButton("按字数均分")
        rebalance_btn.clicked.connect(self.rebalance_assignments)
        buttons.addWidget(rebalance_btn)
        buttons.addStretch(1)
        ok = QPushButton("开始分节")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept_checked)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self.count_spin.valueChanged.connect(self.rebalance_assignments)
        self.rebalance_assignments()

    def update_combo_items(self) -> None:
        count = self.count_spin.value()
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            if not isinstance(combo, QComboBox):
                continue
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for index in range(1, count + 1):
                combo.addItem(f"第 {index} 节", index)
            if isinstance(current, int) and 1 <= current <= count:
                combo.setCurrentIndex(current - 1)
            combo.blockSignals(False)

        self.update_section_totals()

    def balanced_assignment_sections(self, count: int) -> List[int]:
        """按一级标题原始顺序，把标题切成 count 个连续分节，并尽量均衡字数。"""
        total_rows = len(self.block_word_counts)
        if total_rows == 0:
            return []
        count = max(1, min(count, total_rows))
        if count == 1:
            return [1] * total_rows

        prefix = [0]
        for value in self.block_word_counts:
            prefix.append(prefix[-1] + max(0, int(value)))
        target = prefix[-1] / count if count else 0.0

        # dp[section_count][row_count] = 最小平方偏差；row_count 表示已覆盖前 row_count 个标题。
        inf = float("inf")
        dp = [[inf] * (total_rows + 1) for _ in range(count + 1)]
        back = [[-1] * (total_rows + 1) for _ in range(count + 1)]
        dp[0][0] = 0.0

        for section_count in range(1, count + 1):
            # 每节至少一个标题，因此 i 至少为 section_count。
            for row_count in range(section_count, total_rows + 1):
                # previous 是上一节结束位置。
                for previous in range(section_count - 1, row_count):
                    if dp[section_count - 1][previous] == inf:
                        continue
                    section_words = prefix[row_count] - prefix[previous]
                    cost = dp[section_count - 1][previous] + (section_words - target) ** 2
                    if cost < dp[section_count][row_count]:
                        dp[section_count][row_count] = cost
                        back[section_count][row_count] = previous

        sections = [1] * total_rows
        row_count = total_rows
        for section_index in range(count, 0, -1):
            previous = back[section_index][row_count]
            if previous < 0:
                # 理论上不会发生；保底退回顺序均分。
                return [min(count, int(row * count / total_rows) + 1) for row in range(total_rows)]
            for row in range(previous, row_count):
                sections[row] = section_index
            row_count = previous
        return sections

    def rebalance_assignments(self) -> None:
        count = self.count_spin.value()
        self.update_combo_items()
        sections = self.balanced_assignment_sections(count)
        for row, section in enumerate(sections):
            combo = self.table.cellWidget(row, 0)
            if not isinstance(combo, QComboBox):
                continue
            combo.setCurrentIndex(max(0, min(count - 1, section - 1)))
        self.update_section_totals()

    def assignments(self) -> List[List[int]]:
        groups: List[List[int]] = [[] for _ in range(self.count_spin.value())]
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            if not isinstance(combo, QComboBox):
                continue
            value = combo.currentData()
            if isinstance(value, int) and 1 <= value <= len(groups):
                groups[value - 1].append(row)
        return groups

    def section_word_totals(self) -> List[int]:
        groups = self.assignments()
        return [sum(self.block_word_counts[row] for row in rows) for rows in groups]

    def update_section_totals(self) -> None:
        if not hasattr(self, "total_label"):
            return
        groups = self.assignments()
        totals = [sum(self.block_word_counts[row] for row in rows) for rows in groups]
        overall = sum(self.block_word_counts)
        parts = [f"一级标题总字数：{overall}"]
        for index, (rows, total) in enumerate(zip(groups, totals), start=1):
            parts.append(f"第 {index} 节：{total} 字 / {len(rows)} 个一级标题")
        self.total_label.setText("；".join(parts))

    def accept_checked(self) -> None:
        groups = self.assignments()
        empty = [str(index + 1) for index, rows in enumerate(groups) if not rows]
        if empty:
            QMessageBox.warning(self, "分节不完整", "以下节没有选择任何一级标题：" + "、".join(empty))
            return
        self.accept()
