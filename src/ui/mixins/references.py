from core import *
from dialogs import *
from workers import *


class ReferenceMixin:
    def content_reference_format(self, rec: ContentRecord) -> str:
        return markdown_reference(rec.title, content_reference_path(rec.kind, rec.slug))

    def taxonomy_reference_format(self, rec: TaxonomyRecord) -> str:
        return markdown_reference(rec.title, taxonomy_reference_path(rec.kind, rec.name))

    def copy_reference_format(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.set_status(f"已复制引用格式：{text}")

    def markdown_files_for_reference_update(self) -> List[Path]:
        root = self.cfg.content
        paths: set[Path] = set()
        if root.exists():
            paths.update(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".md"
            )

        # 再显式加入已解析出的 index.md 与分片 Markdown，避免 glob 漏掉
        # 大写扩展名或 sections 字段中显式列出的分片文件。
        for record in self.posts + self.projects:
            paths.add(record.md_path)
            paths.update(record.section_files)
            paths.update(discover_numbered_section_files(record.bundle_dir))

        return sorted(
            [path for path in paths if path.is_file()],
            key=lambda item: str(item).casefold(),
        )

    def replace_slug_references_in_text(
        self,
        text: str,
        changes: List[Tuple[str, str, str]],
    ) -> Tuple[str, int]:
        """两阶段替换引用路径，覆盖 index.md 与分片 Markdown 中常见 slug 引用写法。"""
        tail = r"(?=$|[\/\?#\)\]\}\"'<\s])"
        total = 0
        placeholders: List[Tuple[str, str]] = []
        updated = text

        for index, (kind, old_slug, new_slug) in enumerate(changes):
            old = normalized_reference_slug(old_slug)
            new = normalized_reference_slug(new_slug)
            if not old or not new or old == new:
                continue
            escaped_old = re.escape(old)
            section = "posts" if kind == "post" else "projects"
            placeholder = f"__LBM_SLUG_REF_{index}_{hashlib.sha1((kind + old + new).encode('utf-8')).hexdigest()[:10]}__"
            placeholders.append((placeholder, new))
            prefix_patterns = [
                # [标题](/posts/old)、href="/posts/old"、以及完整站点地址。
                rf"(?P<prefix>https?://(?:www\.)?leuco\-yuu\.github\.io/{section}/){escaped_old}{tail}",
                rf"(?P<prefix>/{section}/){escaped_old}{tail}",
                # 兼容 posts/old 这种没有前导斜杠的相对写法。
                rf"(?<![A-Za-z0-9_./-])(?P<prefix>{section}/){escaped_old}{tail}",
                # 兼容 Markdown 链接或 HTML href 直接写 slug：[标题](old) / href="old"。
                rf"(?P<prefix>\]\(){escaped_old}(?P<suffix>(?=$|[\/\?#\)]))",
                rf"(?P<prefix>\bhref=[\"']){escaped_old}(?P<suffix>(?=$|[\/\?#\"']))",
                # 兼容 Hugo shortcode：{{< ref "old" >}} / {{< relref 'old' >}}。
                rf"(?P<prefix>\{{\{{[<%]\s*(?:ref|relref)\s+[\"']){escaped_old}(?P<suffix>[\"'])",
            ]
            for pattern in prefix_patterns:
                updated, count = re.subn(
                    pattern,
                    lambda match, ph=placeholder: (
                        match.group("prefix")
                        + ph
                        + (match.groupdict().get("suffix") or "")
                    ),
                    updated,
                    flags=re.IGNORECASE,
                )
                total += count

        for placeholder, new in placeholders:
            updated = updated.replace(placeholder, new)
        return updated, total

    def update_slug_references(
        self,
        changes: List[Tuple[str, str, str]],
    ) -> Tuple[int, int]:
        valid_changes = [
            (kind, old, new)
            for kind, old, new in changes
            if normalized_reference_slug(old) and normalized_reference_slug(old) != normalized_reference_slug(new)
        ]
        if not valid_changes:
            return 0, 0

        changed_files = 0
        replacements = 0
        for path in self.markdown_files_for_reference_update():
            try:
                old_text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            new_text, count = self.replace_slug_references_in_text(old_text, valid_changes)
            if count > 0 and new_text != old_text:
                path.write_text(new_text, encoding="utf-8", newline="")
                changed_files += 1
                replacements += count
        return changed_files, replacements

    def scan_broken_references(self) -> List[BrokenReference]:
        existing = {
            "post": {record.slug.casefold() for record in self.posts},
            "project": {record.slug.casefold() for record in self.projects},
        }
        slug_segment = r"[a-z0-9]+(?:-[a-z0-9]+)*"
        tail = r"(?=$|[\/\?#\)\]\}\"'<\s])"
        patterns = [
            re.compile(
                rf"(?P<ref>https?://(?:www\.)?leuco\-yuu\.github\.io/(?P<section>posts|projects)/(?P<slug>{slug_segment})){tail}",
                re.IGNORECASE,
            ),
            re.compile(
                rf"(?<![A-Za-z0-9_.-])(?P<ref>/(?P<section>posts|projects)/(?P<slug>{slug_segment})){tail}",
                re.IGNORECASE,
            ),
            re.compile(
                rf"(?<![A-Za-z0-9_./-])(?P<ref>(?P<section>posts|projects)/(?P<slug>{slug_segment})){tail}",
                re.IGNORECASE,
            ),
        ]

        broken: List[BrokenReference] = []
        seen: set[Tuple[str, int, str]] = set()
        for path in self.markdown_files_for_reference_update():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                for pattern in patterns:
                    for match in pattern.finditer(line):
                        section = match.group("section").lower()
                        kind = "post" if section == "posts" else "project"
                        slug = match.group("slug").lower()
                        if slug in existing[kind]:
                            continue
                        reference = match.group("ref")
                        key = (str(path), line_number, reference)
                        if key in seen:
                            continue
                        seen.add(key)
                        broken.append(
                            BrokenReference(
                                kind=kind,
                                slug=slug,
                                reference=reference,
                                path=path,
                                line=line_number,
                                context=line.strip(),
                            )
                        )
        return broken

    def check_references(self) -> None:
        try:
            with self.waiting("正在检查文章和项目引用……"):
                broken = self.scan_broken_references()
        except Exception as exc:
            QMessageBox.critical(self, "引用检查失败", str(exc))
            return

        if not broken:
            self.set_status("引用检查完成：未发现无效的 /posts/ 或 /projects/ 引用。")
            QMessageBox.information(self, "引用检查", "未发现无效的 /posts/ 或 /projects/ 引用。")
            return

        self.set_status(f"引用检查完成：发现 {len(broken)} 处无效引用。")
        BrokenReferencesDialog(broken, self.cfg.root, self.open_path, self).exec()
