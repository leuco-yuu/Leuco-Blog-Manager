from core import *
from dialogs import *
from workers import *


class AiToolsMixin:
    def save_settings(self, show_message: bool = False) -> None:
        """保存普通配置；绝不把密码或解密后的 API Key 写入磁盘。"""
        self.app_config.data.update({
            "blog_root": self.root_edit.text().strip() or str(DEFAULT_BLOG_ROOT),
            "api_base_url": self.api_base_edit.text().strip() or "https://api.deepseek.com",
            "api_model": self.api_model_edit.text().strip() or "deepseek-v4-flash",
            "git_remote": self.git_remote_edit.text().strip() or "origin",
            "git_branch": self.git_branch_edit.text().strip() or "main",
            "git_rebase": self.git_rebase_check.isChecked(),
            "git_autostash": self.git_autostash_check.isChecked(),
            "blog_url": self.blog_url_edit.text().strip(),
            "slug_concurrency": (
                self.post_slug_concurrency.value()
                if hasattr(self, "post_slug_concurrency")
                else 20
            ),
            "slug_batch_size": (
                self.post_slug_batch_size.value()
                if hasattr(self, "post_slug_batch_size")
                else 40
            ),
        })
        self.app_config.save()
        if show_message:
            QMessageBox.information(self, "配置已保存", "AI 与 Git 参数已保存。")

    def login_api_key(self) -> None:
        """使用界面中输入的密码解密程序目录下的 API Key 文件。"""
        self.save_settings(False)
        password = self.api_key_edit.text()

        if not password:
            QMessageBox.warning(
                self,
                "缺少密码",
                "请输入 config/apikey_data.bin 的解密密码。",
            )
            self.api_key_edit.setFocus()
            return

        try:
            with self.waiting("正在解密并验证 API Key……"):
                api_key = decrypt_api_key(password, API_KEY_FILE)
                if not api_key:
                    raise ValueError("解密成功，但 API Key 内容为空。")
        except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
            self._decrypted_api_key = ""
            self.api_key_edit.selectAll()
            self.api_key_edit.setFocus()
            QMessageBox.critical(self, "登录失败", str(exc))
            self.set_status("API 登录失败。")
            return
        except Exception as exc:
            self._decrypted_api_key = ""
            QMessageBox.critical(
                self,
                "登录失败",
                f"解密 API Key 时发生异常：\n{exc}",
            )
            self.set_status("API 登录失败。")
            return

        self._decrypted_api_key = api_key
        self.api_key_edit.clear()
        self.api_key_edit.setPlaceholderText("已登录；重新输入密码可重新登录")
        self.set_status("API 登录成功，解密后的密钥仅保存在当前进程内存中。")

    def save_api_config(self) -> None:
        self.save_settings(False)

    def read_api_key(self) -> str:
        return self._decrypted_api_key.strip()

    def call_ai(self, prompt: str, temperature: float = 0.2) -> str:
        self.save_api_config()
        api_key = self.read_api_key()
        if not api_key:
            raise RuntimeError("尚未登录。请在主界面输入解密密码并点击‘登录’。")
        base = self.api_base_edit.text().strip().rstrip("/")
        endpoint = base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"
        model = self.api_model_edit.text().strip()
        system_prompt = load_prompt("system.txt")
        with self.waiting("AI 正在处理，请稍候……"):
            return ai_chat_completion(
                endpoint,
                api_key,
                model,
                system_prompt,
                prompt,
                temperature=temperature,
            )

    def ai_request(self, prompt: str, temperature: float = 0.2) -> Optional[str]:
        try:
            return self.call_ai(prompt, temperature)
        except Exception as exc:
            QMessageBox.critical(self, "AI 请求失败", str(exc))
            return None

    def parse_ai_list(self, raw: str, limit: Optional[int] = None) -> List[str]:
        def finish(values: Iterable[str]) -> List[str]:
            result = unique(values)
            return result[:limit] if limit is not None else result

        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return finish(str(x).strip() for x in data if str(x).strip())
            if isinstance(data, dict):
                merged: List[str] = []
                for value in data.values():
                    if isinstance(value, list):
                        merged.extend(str(x).strip() for x in value if str(x).strip())
                if merged:
                    return finish(merged)
        except Exception:
            pass
        bracket = re.search(r"\[[\s\S]*\]", text)
        if bracket:
            try:
                data = json.loads(bracket.group(0))
                if isinstance(data, list):
                    return finish(str(x).strip() for x in data if str(x).strip())
            except Exception:
                pass
        parts = re.split(r"[\n,，;；]+", text)
        cleaned = []
        for part in parts:
            item = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", part).strip().strip('"\'')
            if item:
                cleaned.append(item)
        return finish(cleaned)

    def record_ai_context(self, rec: ContentRecord) -> str:
        data = {
            "type": "文章" if rec.kind == "post" else "项目",
            "title": rec.title,
            "description": rec.description,
            "summary": rec.summary,
            "tags": rec.tags,
            "categories": rec.categories,
            "series": rec.series,
            "body": rec.body,
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def record_ai_independent_taxonomy_context(self, rec: ContentRecord) -> str:
        """AI 总结专用上下文：不包含当前或已有的标签、分类、系列。"""
        data = {
            "type": "文章" if rec.kind == "post" else "项目",
            "title": rec.title,
            "description": rec.description,
            "summary": rec.summary,
            "body": rec.body,
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def suggest_slug(self, title: str) -> str:
        try:
            prompt = load_prompt("slug.txt", title=title)
            raw = self.call_ai(prompt, temperature=0)
            value = sanitize_slug_guess(raw)
            return value if SLUG_RE.match(value) else sanitize_slug_guess(title)
        except Exception:
            return sanitize_slug_guess(title)

    def ai_slug_for_record(self, rec: ContentRecord) -> Optional[str]:
        prompt = load_prompt("slug.txt", title=rec.title)
        raw = self.ai_request(prompt, temperature=0)
        if not raw:
            return None
        return sanitize_slug_guess(raw)

    def ai_text_for_record(self, rec: ContentRecord, field_name: str) -> Optional[str]:
        prompt_file = "article_summary.txt" if field_name == "summary" else "article_description.txt"
        prompt = load_prompt(
            prompt_file,
            title=rec.title,
            current_description=rec.description,
            current_summary=rec.summary,
            tags=json.dumps(rec.tags, ensure_ascii=False),
            body=rec.body,
        )
        return self.ai_request(prompt, temperature=0.2)

    def ai_taxonomy_values(self, rec: ContentRecord, field_name: str, mode: str, count: int) -> List[str]:
        count = max(1, int(count))
        labels = {"tags": "标签", "categories": "分类", "series": "系列"}
        available_map = {
            "tags": self.all_tags(),
            "categories": self.all_categories(),
            "series": self.all_series(),
        }
        available = available_map[field_name]
        context = self.record_ai_context(rec)

        if mode == "select":
            if not available:
                return []
            prompt = load_prompt(
                "taxonomy_select.txt",
                taxonomy_name=labels[field_name],
                count=count,
                available=json.dumps(available, ensure_ascii=False),
                content=context,
            )
            raw = self.ai_request(prompt, temperature=0.1)
            if not raw:
                return []
            canonical = {x.casefold(): x for x in available}
            return unique(
                canonical[x.casefold()]
                for x in self.parse_ai_list(raw, count)
                if x.casefold() in canonical
            )[:count]

        if mode == "summarize":
            # 不把已有条目列表和当前标签/分类/系列发送给 AI。
            independent_context = self.record_ai_independent_taxonomy_context(rec)
            candidate_count = max(count * 2, count + 6)
            prompt = load_prompt(
                "taxonomy_summarize.txt",
                taxonomy_name=labels[field_name],
                count=candidate_count,
                content=independent_context,
            )
            raw = self.ai_request(prompt, temperature=0.45)
            candidates = self.parse_ai_list(raw or "", candidate_count)
            existing_keys = {value.casefold() for value in available}
            independent_values = unique(
                value for value in candidates
                if value.casefold() not in existing_keys
            )
            return independent_values[:count]

        # AI 建议严格拆成两部分：一半从已有条目选取，一半独立总结。
        select_count = count // 2
        summarize_count = count - select_count
        selected = (
            self.ai_taxonomy_values(rec, field_name, "select", select_count)
            if select_count > 0 else []
        )
        summarized = (
            self.ai_taxonomy_values(rec, field_name, "summarize", summarize_count)
            if summarize_count > 0 else []
        )
        return unique(selected + summarized)[:count]

    def parse_tag_merge_suggestions(self, raw: str, available_tags: List[str]) -> List[TagMergeSuggestion]:
        text = (raw or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except Exception:
            match = re.search(r"[\[{][\s\S]*[\]}]", text)
            if not match:
                return []
            try:
                data = json.loads(match.group(0))
            except Exception:
                return []

        if isinstance(data, dict):
            for key in ("groups", "pairs", "suggestions", "merges", "items"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                data = [data]
        if not isinstance(data, list):
            return []

        canonical = {tag.casefold(): tag for tag in available_tags}
        suggestions: List[TagMergeSuggestion] = []
        seen_groups: set[Tuple[str, ...]] = set()

        for item in data:
            if not isinstance(item, dict):
                continue
            raw_tags = (
                item.get("tags")
                or item.get("pair")
                or item.get("source_tags")
                or item.get("similar_tags")
                or item.get("merge")
            )
            tags = listify(raw_tags)
            normalized = unique(
                canonical[tag.casefold()]
                for tag in tags
                if tag.casefold() in canonical
            )
            if len(normalized) < 2:
                continue
            group_key = tuple(sorted(tag.casefold() for tag in normalized))
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)

            target = scalar(
                item.get("target")
                or item.get("suggested")
                or item.get("merge_to")
                or item.get("canonical")
            )
            if not target:
                target = normalized[0]
            reason = scalar(item.get("reason") or item.get("why") or item.get("explanation"))
            suggestions.append(TagMergeSuggestion(normalized, target, reason))

        return suggestions

    def merge_similar_tags(self) -> None:
        tags = self.all_tags()
        if len(tags) < 2:
            QMessageBox.information(self, "标签不足", "当前标签数量不足，无法合并。")
            return

        prompt = load_prompt("merge_tags.txt", tags=json.dumps(tags, ensure_ascii=False, indent=2))
        raw = self.ai_request(prompt, temperature=0.05)
        if not raw:
            return
        suggestions = self.parse_tag_merge_suggestions(raw, tags)
        if not suggestions:
            QMessageBox.information(self, "没有建议", "AI 没有找到需要合并的高相似标签。")
            return

        dlg = MergeTagsDialog(suggestions, tags, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        merges = dlg.values()
        if not merges:
            return

        reply = QMessageBox.question(
            self,
            "确认合并标签",
            f"将执行 {len(merges)} 组标签合并，并更新所有文章/项目头数据。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with self.waiting("正在合并标签并更新头数据……"):
                changed, removed = self.apply_tag_merges(merges)
            self.mark_modified(True)
            self.load_blog()
            self.set_status(f"标签合并完成：更新 {changed} 个内容，删除 {removed} 个被替换标签目录。")
        except Exception as exc:
            QMessageBox.critical(self, "合并标签失败", str(exc))

    def apply_tag_merges(self, merges: List[Tuple[List[str], str]]) -> Tuple[int, int]:
        mapping: Dict[str, str] = {}
        replaced_keys: set[str] = set()
        for source_tags, target in merges:
            target = target.strip()
            if not target:
                continue
            for source in source_tags:
                source = source.strip()
                if not source or source.casefold() == target.casefold():
                    continue
                mapping[source.casefold()] = target
                replaced_keys.add(source.casefold())

        if not mapping:
            return 0, 0

        changed = 0
        for content in self.posts + self.projects:
            new_tags = unique(mapping.get(tag.casefold(), tag) for tag in content.tags)
            if new_tags != content.tags:
                content.tags = new_tags
                content.lastmod = now_iso()
                write_content(content, self.cfg)
                changed += 1

        tag_root = self.cfg.taxonomy_root("tag")
        for target in unique(mapping.values()):
            folder = tag_root / target
            ensure_dir(folder)
            index = folder / "_index.md"
            if not index.exists():
                write_taxonomy(TaxonomyRecord("tag", target, target, "", "", index, folder, "", {}))

        target_keys = {target.casefold() for target in mapping.values()}
        removed = 0
        for rec in list(self.taxonomies["tag"]):
            keys = {rec.name.casefold(), rec.title.casefold()}
            if keys & replaced_keys and not keys & target_keys and rec.folder.exists():
                shutil.rmtree(rec.folder)
                removed += 1

        return changed, removed

    def taxonomy_members(self, rec: TaxonomyRecord) -> List[ContentRecord]:
        keys = {rec.name.casefold(), rec.title.casefold()}
        if rec.kind == "category":
            return [
                item for item in self.posts + self.projects
                if any(value.casefold() in keys for value in item.categories)
            ]
        if rec.kind == "series":
            return [
                item for item in self.posts
                if any(value.casefold() in keys for value in item.series)
            ]
        return []

    def ai_taxonomy_description(self, rec: TaxonomyRecord) -> Optional[str]:
        members = self.taxonomy_members(rec)
        if not members:
            QMessageBox.warning(self, "没有可总结内容", "该分类或系列中没有文章/项目。")
            return None
        items = [
            {
                "type": "文章" if item.kind == "post" else "项目",
                "title": item.title,
                "description": item.description,
                "summary": item.summary,
                "tags": item.tags,
                "body": item.body,
            }
            for item in members
        ]
        prompt = load_prompt(
            "taxonomy_description.txt",
            taxonomy_type="分类" if rec.kind == "category" else "系列",
            taxonomy_name=rec.title,
            items=json.dumps(items, ensure_ascii=False, indent=2),
        )
        return self.ai_request(prompt, temperature=0.25)
