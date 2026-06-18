from core import *
from dialogs import *
from workers import *
from .mixins.ui import UiMixin
from .mixins.blog_data import BlogDataMixin
from .mixins.references import ReferenceMixin
from .mixins.ai_tools import AiToolsMixin
from .mixins.bulk_ops import BulkOpsMixin
from .mixins.content_actions import ContentActionsMixin
from .mixins.taxonomy_resources import TaxonomyResourceMixin
from .mixins.git_hugo import GitHugoMixin


class MainWindow(
    UiMixin,
    BlogDataMixin,
    ReferenceMixin,
    AiToolsMixin,
    BulkOpsMixin,
    ContentActionsMixin,
    TaxonomyResourceMixin,
    GitHugoMixin,
    QMainWindow,
):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Leuco Blog Manager")
        self.resize(1080, 700)
        app_icon = icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.app_config = AppConfig()
        self.cfg = LeucoBlogConfig(Path(self.app_config["blog_root"]) if self.app_config["blog_root"] else DEFAULT_BLOG_ROOT)
        self.posts: List[ContentRecord] = []
        self.projects: List[ContentRecord] = []
        self.taxonomies: Dict[str, List[TaxonomyRecord]] = {"category": [], "series": [], "tag": []}
        self.modified = False
        self.git_thread: Optional[QThread] = None
        self.git_worker: Optional[GitWorker] = None
        self.hugo_process: Optional[QProcess] = None
        self._hugo_output: List[str] = []
        self._hugo_stop_requested = False
        self._hugo_error_reported = False
        self._suppress_hugo_browser_once = False
        self._sync_busy_depth = 0
        self._git_busy = False
        self._hugo_starting = False
        self._bulk_busy = False
        self.active_filter: Optional[Tuple[str, str]] = None
        self._decrypted_api_key = ""
        self.content_load_warnings: List[str] = []
        self.build_ui()
        self.apply_style()
        self.hugo_state_timer = QTimer(self)
        self.hugo_state_timer.setInterval(1500)
        self.hugo_state_timer.timeout.connect(self.update_hugo_button_state)
        self.hugo_state_timer.start()
        self.update_hugo_button_state()
        QTimer.singleShot(80, self.load_blog)
