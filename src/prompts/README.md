# Prompts

AI 功能使用的提示词文件。运行时由 `load_prompt()` 从 `src/prompts` 或 PyInstaller 资源目录读取。

- `slug.txt`：单个标题生成 slug。
- `slug_batch.txt`：一键更新 slug 的批量编号提示词。
- `article_description.txt` / `article_summary.txt`：文章或项目描述、摘要。
- `taxonomy_*.txt`：分类、系列、标签相关选择和生成。
- `merge_tags.txt`：相似标签合并建议。
- `system.txt`：统一系统约束。
