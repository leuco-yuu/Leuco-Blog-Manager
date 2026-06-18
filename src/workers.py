from core import *


class GitWorker(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        root: Path,
        action: str,
        message: str = "",
        remote: str = "origin",
        branch: str = "main",
        rebase: bool = True,
        autostash: bool = True,
    ) -> None:
        super().__init__()
        self.root = root
        self.action = action
        self.message = message
        self.remote = remote.strip() or "origin"
        self.branch = branch.strip() or "main"
        self.rebase = rebase
        self.autostash = autostash

    def run(self) -> None:
        try:
            if self.action == "pull":
                self.progress.emit(f"正在从 {self.remote}/{self.branch} 拉取变更……")
                args = ["git", "pull"]
                if self.rebase:
                    args.append("--rebase")
                if self.autostash:
                    args.append("--autostash")
                args.extend([self.remote, self.branch])
                out = run_cmd(args, cwd=self.root, timeout=420)
                self.finished.emit(out.strip() or f"已从 {self.remote}/{self.branch} 拉取完成。")
                return

            scope = "content" if self.action == "commit-content" else "."
            self.progress.emit("正在检查变更……")
            if scope == "content":
                run_cmd(["git", "add", "content"], cwd=self.root, timeout=120)
                status = run_cmd(["git", "status", "--porcelain", "content"], cwd=self.root, timeout=60)
            else:
                run_cmd(["git", "add", "-A"], cwd=self.root, timeout=120)
                status = run_cmd(["git", "status", "--porcelain"], cwd=self.root, timeout=60)
            if not status.strip():
                self.finished.emit("没有需要提交的变更。")
                return
            self.progress.emit("正在提交……")
            run_cmd(["git", "commit", "-m", self.message], cwd=self.root, timeout=180)
            local_branch = run_cmd(["git", "branch", "--show-current"], cwd=self.root, timeout=60).strip() or self.branch
            self.progress.emit(f"正在推送到 {self.remote}/{self.branch}……")
            run_cmd(["git", "push", "-u", self.remote, f"{local_branch}:{self.branch}"], cwd=self.root, timeout=420)
            self.finished.emit(f"提交并推送完成：{local_branch} → {self.remote}/{self.branch}")
        except Exception:
            self.failed.emit(safe_traceback())
