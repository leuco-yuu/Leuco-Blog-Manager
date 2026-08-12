from core import *
from dialogs import *
from workers import *

import re


def _proc_cmdline(pid: int) -> str:
    """读取 Linux /proc 中的进程命令行，避免依赖 ps/lsof。"""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _proc_name_is_hugo(pid: int) -> bool:
    """通过 /proc 验证指定 PID 是否属于 Hugo，避免误杀其他占用 1313 的服务。"""
    try:
        comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        comm = ""
    return "hugo" in comm.casefold() or "hugo" in _proc_cmdline(pid).casefold()


class GitHugoMixin:
    def pull_remote(self) -> None:
        self.start_git("pull")

    def commit(self, action: str) -> None:
        msg, ok = QInputDialog.getText(self, "提交", "Commit message", text="update blog content" if action == "commit-content" else "update blog project")
        if ok:
            self.start_git(action, msg.strip() or "update blog")

    def start_git(self, action: str, message: str = "") -> None:
        if shutil.which("git") is None:
            hint = (
                "未找到 git 命令。\n\nKali/Linux 可运行：\n"
                "    sudo apt-get install -y git\n"
                "或执行 scripts/install_kali.sh 完成全部环境配置。"
                if is_linux()
                else "请先安装 Git 后重试。"
            )
            QMessageBox.critical(self, "未找到 Git", hint)
            return
        self._git_busy = True
        self.set_status("正在启动 Git 操作……")
        self.update_progress_visibility()
        QApplication.processEvents()
        self.git_thread = QThread(self)
        self.save_settings(False)
        self.git_worker = GitWorker(
            self.cfg.root,
            action,
            message,
            remote=self.git_remote_edit.text().strip() or "origin",
            branch=self.git_branch_edit.text().strip() or "main",
            rebase=self.git_rebase_check.isChecked(),
            autostash=self.git_autostash_check.isChecked(),
        )
        self.git_worker.moveToThread(self.git_thread)
        self.git_thread.started.connect(self.git_worker.run)
        self.git_worker.progress.connect(self.set_status)
        self.git_worker.finished.connect(self.on_git_finished)
        self.git_worker.failed.connect(self.on_git_failed)
        self.git_worker.finished.connect(self.git_thread.quit)
        self.git_worker.failed.connect(self.git_thread.quit)
        self.git_worker.finished.connect(self.git_worker.deleteLater)
        self.git_worker.failed.connect(self.git_worker.deleteLater)
        self.git_thread.finished.connect(self.git_thread.deleteLater)
        self.git_thread.start()

    def on_git_finished(self, msg: str) -> None:
        self._git_busy = False
        self.update_progress_visibility()
        self.mark_modified(False)
        self.load_blog()
        self.set_status(msg)

    def on_git_failed(self, msg: str) -> None:
        self._git_busy = False
        self.update_progress_visibility()
        self.set_status("Git 操作失败。")
        QMessageBox.critical(self, "Git 失败", msg)

    def update_hugo_button_state(self) -> None:
        if self._hugo_starting:
            self.hugo_btn.setText("启动中…")
            return
        self.hugo_btn.setText("停止 Hugo" if hugo_preview_port_in_use() else "启动 Hugo")

    def append_hugo_output(self, is_error: bool = False) -> None:
        if not self.hugo_process:
            return
        raw = self.hugo_process.readAllStandardError() if is_error else self.hugo_process.readAllStandardOutput()
        text = bytes(raw).decode("utf-8", "replace").strip()
        if not text:
            return
        self._hugo_output.append(text)
        lines = text.splitlines()
        if lines:
            self.set_status(lines[-1])

    def open_hugo_browser_if_running(self) -> None:
        if hugo_preview_port_in_use():
            open_with_system(f"http://{HUGO_PREVIEW_HOST}:{HUGO_PREVIEW_PORT}/")

    def on_hugo_started(self) -> None:
        self._hugo_starting = False
        self.update_progress_visibility()
        self.update_hugo_button_state()
        self.set_status(f"Hugo 本地服务已启动：http://{HUGO_PREVIEW_HOST}:{HUGO_PREVIEW_PORT}/")
        if self._suppress_hugo_browser_once:
            self._suppress_hugo_browser_once = False
        else:
            QTimer.singleShot(800, self.open_hugo_browser_if_running)

    def on_hugo_error(self, _error: QProcess.ProcessError) -> None:
        if not self.hugo_process or self._hugo_error_reported:
            return
        self._hugo_error_reported = True
        self._hugo_starting = False
        self.update_progress_visibility()
        self.update_hugo_button_state()
        message = self.hugo_process.errorString() or "未知错误"
        self.set_status("Hugo 启动失败。")
        QMessageBox.critical(self, "Hugo 启动失败", message)

    def on_hugo_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if self.hugo_process:
            self.append_hugo_output(False)
            self.append_hugo_output(True)
        requested = self._hugo_stop_requested
        output = "\n".join(self._hugo_output).strip()
        self._hugo_starting = False
        self.update_progress_visibility()
        self.update_hugo_button_state()
        if requested:
            self.set_status("Hugo 服务已停止。")
        elif exit_code != 0:
            self.set_status("Hugo 本地服务启动或运行失败。")
            if not self._hugo_error_reported:
                QMessageBox.critical(
                    self,
                    "Hugo 运行失败",
                    f"Hugo 已异常退出，退出码：{exit_code}\n\n{output or '未返回错误输出。'}",
                )
        else:
            self.set_status("Hugo 服务已结束。")
        self._hugo_stop_requested = False
        QTimer.singleShot(250, self.update_hugo_button_state)

    def stop_owned_hugo_process(self) -> bool:
        process = self.hugo_process
        if not process or process.state() == QProcess.ProcessState.NotRunning:
            return False
        self._hugo_stop_requested = True
        process.terminate()
        if not process.waitForFinished(2500):
            process.kill()
            process.waitForFinished(2000)
        self.update_hugo_button_state()
        return True

    def external_hugo_pids_on_port(self) -> List[int]:
        """只返回可识别为 hugo 的外部进程，避免误杀占用 1313 的其他服务。"""
        pids: set[int] = set()
        try:
            if os.name == "nt":
                code, output = run_cmd_status(["netstat", "-ano", "-p", "tcp"], timeout=15)
                if code != 0:
                    return []
                for line in output.splitlines():
                    if f":{HUGO_PREVIEW_PORT}" not in line or "LISTEN" not in line.upper():
                        continue
                    parts = line.split()
                    if parts:
                        try:
                            pids.add(int(parts[-1]))
                        except ValueError:
                            pass
                verified: set[int] = set()
                for pid in pids:
                    code, task = run_cmd_status(
                        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                        timeout=10,
                    )
                    if code == 0 and "hugo" in task.lower():
                        verified.add(pid)
                return sorted(verified)

            # Linux：依次尝试 lsof、ss、fuser，并用 /proc 验证进程身份。
            raw_pids: set[int] = set()
            code, output = run_cmd_status(
                ["lsof", "-nP", f"-iTCP:{HUGO_PREVIEW_PORT}", "-sTCP:LISTEN", "-t"],
                timeout=10,
            )
            if code == 0 and output.strip():
                raw_pids = {int(raw) for raw in output.split() if raw.strip().isdigit()}
            else:
                code, output = run_cmd_status(
                    ["ss", "-ltnp", f"sport = :{HUGO_PREVIEW_PORT}"],
                    timeout=10,
                )
                if code == 0:
                    raw_pids = {int(match) for match in re.findall(r"pid=(\d+)", output)}
                if not raw_pids:
                    code, output = run_cmd_status(
                        ["fuser", "-n", "tcp", str(HUGO_PREVIEW_PORT)],
                        timeout=10,
                    )
                    if code == 0:
                        raw_pids = {
                            int(token.rstrip(":"))
                            for token in output.split()
                            if token.rstrip(":").isdigit()
                        }
            for pid in raw_pids:
                if is_linux():
                    if _proc_name_is_hugo(pid):
                        pids.add(pid)
                else:
                    code, name = run_cmd_status(["ps", "-p", str(pid), "-o", "comm="], timeout=10)
                    if code == 0 and "hugo" in name.lower():
                        pids.add(pid)
        except Exception:
            return []
        return sorted(pids)

    def stop_external_hugo_on_port(self) -> bool:
        pids = self.external_hugo_pids_on_port()
        if not pids:
            return False
        try:
            if os.name == "nt":
                for pid in pids:
                    run_cmd_status(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)
            else:
                for pid in pids:
                    run_cmd_status(["kill", str(pid)], timeout=10)
                deadline = time_module.monotonic() + 3.0
                while hugo_preview_port_in_use() and time_module.monotonic() < deadline:
                    time_module.sleep(0.15)
                if hugo_preview_port_in_use():
                    for pid in pids:
                        run_cmd_status(["kill", "-9", str(pid)], timeout=10)
        except Exception:
            return False
        QTimer.singleShot(350, self.update_hugo_button_state)
        return True

    def stop_hugo_service(self) -> None:
        if self.stop_owned_hugo_process():
            return
        if self.stop_external_hugo_on_port():
            self.set_status("已停止占用 1313 端口的 Hugo 服务。")
            return
        self.update_hugo_button_state()
        QMessageBox.warning(
            self,
            "无法安全停止 Hugo",
            "检测到 1313 端口被占用，但没有找到由本程序启动或可识别为 Hugo 的进程。\n"
            "请在终端中停止占用该端口的进程后再操作。",
        )

    def start_hugo_service(self) -> None:
        if shutil.which("hugo") is None:
            hint = (
                "未找到 hugo 命令。\n\nKali/Linux 可运行：\n"
                "    sudo apt-get install -y hugo\n"
                "或执行 scripts/install_kali.sh 完成全部环境配置。"
                if is_linux()
                else "请先安装 Hugo 后重试。"
            )
            QMessageBox.critical(self, "未找到 Hugo", hint)
            return
        if hugo_preview_port_in_use():
            self.update_hugo_button_state()
            self.set_status("1313 端口已被占用，未重复启动 Hugo。")
            return

        self._hugo_output = []
        self._hugo_stop_requested = False
        self._hugo_starting = True
        self.update_progress_visibility()
        self.update_hugo_button_state()
        self._hugo_error_reported = False
        self.hugo_process = QProcess(self)
        self.hugo_process.setWorkingDirectory(str(self.cfg.root))
        self.hugo_process.setProgram("hugo")
        self.hugo_process.setArguments([
            "server",
            "--bind",
            HUGO_PREVIEW_HOST,
            "--port",
            str(HUGO_PREVIEW_PORT),
            "--disableFastRender",
            "--noHTTPCache",
        ])
        self.hugo_process.readyReadStandardOutput.connect(lambda: self.append_hugo_output(False))
        self.hugo_process.readyReadStandardError.connect(lambda: self.append_hugo_output(True))
        self.hugo_process.started.connect(self.on_hugo_started)
        self.hugo_process.errorOccurred.connect(self.on_hugo_error)
        self.hugo_process.finished.connect(self.on_hugo_finished)
        self.set_status("正在启动 Hugo 本地服务……")
        QApplication.processEvents()
        self.hugo_process.start()
        if not self.hugo_process.waitForStarted(3000):
            self.on_hugo_error(self.hugo_process.error())

    def toggle_hugo(self) -> None:
        if hugo_preview_port_in_use():
            self.stop_hugo_service()
        else:
            self.start_hugo_service()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.hugo_process and self.hugo_process.state() != QProcess.ProcessState.NotRunning:
            self._hugo_stop_requested = True
            self.hugo_process.terminate()
            if not self.hugo_process.waitForFinished(2500):
                self.hugo_process.kill()
        event.accept()
