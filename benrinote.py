# benrinote.py
# =========================================================
# 便利ノート（PySide6 / 単一ファイル）
#
# 機能：
# - ToDo：ダブルクリック編集（リッチ）、完了→アーカイブ、アーカイブ編集/削除（タブ切替）
# - 常駐事項：ドラッグ&ドロップで並べ替え、ダブルクリックでリッチ編集ポップアップ
# - メモA/B：左右分割、白背景、リッチ編集、下端に少し余白
# - ツールバー：『常に手前に表示』トグル（起動時は必ずOFF）
# - トレイ：表示/最小化/終了、『常に手前に表示』トグル
# =========================================================

from __future__ import annotations
import json, os, sys, uuid, time, re, traceback
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

APP_TITLE = "便利ノート"

# 保存先（Winなら %LOCALAPPDATA%\BenriNote）
DATA_DIR  = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "BenriNote"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / "notes.json"
CONF_FILE = DATA_DIR / "window.json"
LOG_FILE  = DATA_DIR / "error.log"

# ===== Theme =====
ACCENT        = "#4F8AF3"
ACCENT_HOVER  = "#6BA0F6"
ACCENT_WEAK   = "#E6F0FF"
FG            = "#222222"
BG            = "#FAFAFB"
PANEL_BG      = "#FFFFFF"  # ← メモはホワイトにしたい要望を満たす
BORDER        = "#E6E6EA"
HANDLE        = "#EAEAEA"

DEFAULT_STATE = {
    "categories": {},           # name -> {"html": "..."}
    "category_order": [],
    "todo": {"items": [], "archive": []},  # item: {id, text, done, html, archived_at?}
    "memo1": {"html": ""},
    "memo2": {"html": ""},
}

# ---------- JSON I/O ----------
def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))

def save_json(path: Path, data: Dict[str, Any]):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

# ---------- utils ----------
def plain_to_html(text: str) -> str:
    import html
    if text is None: text = ""
    return f"<p>{html.escape(text).replace('\\n', '<br>')}</p>"

def html_to_plain(html: str) -> str:
    if not html: return ""
    txt = re.sub(r"<br\\s*/?>", "\n", html, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = QtGui.QTextDocumentFragment.fromHtml(txt).toPlainText()
    return txt.strip()

# ---------- excepthook ----------
def install_excepthook():
    def _hook(t, v, tb):
        try:
            LOG_FILE.write_text(
                f"[{datetime.now()}]\n" + "".join(traceback.format_exception(t, v, tb)),
                encoding="utf-8"
            )
        except Exception:
            pass
        try:
            app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
            QtWidgets.QMessageBox.critical(None, APP_TITLE, f"エラーが発生しました。\n{v}\n\n詳細: {LOG_FILE}")
        except Exception:
            pass
    sys.excepthook = _hook

# ---------- Icons（簡易生成） ----------
def make_icon_A_underline(size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    font = QtGui.QFont("Segoe UI"); font.setBold(True); font.setPointSizeF(size * 0.65)
    p.setFont(font); p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
    rect = QtCore.QRectF(0, -2, size, size)
    p.drawText(rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, "A")
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
    y = int(size * 0.82); p.drawLine(int(size*0.18), y, int(size*0.82), y)
    p.end(); return QtGui.QIcon(pm)

def make_icon_palette(color: QtGui.QColor, size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    path = QtGui.QPainterPath()
    r = size - 2
    path.addRoundedRect(QtCore.QRectF(1, 2, r, r-2), size*0.3, size*0.3)
    hole = QtGui.QPainterPath(); hole.addEllipse(QtCore.QRectF(size*0.45, size*0.55, size*0.28, size*0.28))
    shape = path.subtracted(hole)
    p.fillPath(shape, QtGui.QBrush(QtGui.QColor(245,245,245)))
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 1)); p.drawPath(shape)
    p.setBrush(QtGui.QBrush(color)); p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
    p.drawEllipse(QtCore.QRectF(size*0.18, size*0.22, size*0.28, size*0.28))
    p.end(); return QtGui.QIcon(pm)

# ---------- RichBar ----------
class RichBar(QtWidgets.QToolBar):
    htmlChanged = QtCore.Signal()
    def __init__(self, target: QtWidgets.QTextEdit, parent=None):
        super().__init__(parent)
        self.target = target
        self.setIconSize(QtCore.QSize(18, 18))
        self.setStyleSheet("QToolBar{border:0; background: transparent;}")
        self.actUnderline = QtGui.QAction(make_icon_A_underline(), "下線", self)
        self.actUnderline.setCheckable(True); self.actUnderline.toggled.connect(self.toggle_underline)
        self.addAction(self.actUnderline)
        self._color = QtGui.QColor(FG)
        self.actColor = QtGui.QAction(make_icon_palette(self._color), "文字色", self)
        self.actColor.triggered.connect(self.pick_color); self.addAction(self.actColor)
    def toggle_underline(self, on: bool):
        fmt = QtGui.QTextCharFormat(); fmt.setFontUnderline(on); self._merge(fmt)
    def pick_color(self):
        col = QtWidgets.QColorDialog.getColor(self._color, self, "文字色を選択")
        if col.isValid():
            self._color = col; self.actColor.setIcon(make_icon_palette(self._color))
            fmt = QtGui.QTextCharFormat(); fmt.setForeground(QtGui.QBrush(col)); self._merge(fmt)
    def _merge(self, fmt: QtGui.QTextCharFormat):
        cur = self.target.textCursor()
        if cur.hasSelection(): cur.mergeCharFormat(fmt)
        else: self.target.mergeCurrentCharFormat(fmt)
        self.htmlChanged.emit()

# ---------- ToDo Model ----------
class TodoModel(QtCore.QAbstractListModel):
    def __init__(self, items: List[Dict[str, Any]]):
        super().__init__(); self.items = items
    def rowCount(self, parent=QtCore.QModelIndex()): return len(self.items)
    def data(self, index, role):
        if not index.isValid(): return None
        it = self.items[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return ("[✓] " if it.get("done") else "[ ] ") + it.get("text","")
        if role == QtCore.Qt.FontRole and it.get("done"):
            f = QtGui.QFont(); f.setStrikeOut(True); return f
        return None
    def add(self, text: str, html: str = None):
        self.beginInsertRows(QtCore.QModelIndex(), len(self.items), len(self.items))
        self.items.append({"id": str(uuid.uuid4()), "text": text, "done": False, "html": html or plain_to_html(text)})
        self.endInsertRows()
    def toggle(self, row: int):
        if 0 <= row < len(self.items):
            self.items[row]["done"] = not self.items[row]["done"]
            self.dataChanged.emit(self.index(row), self.index(row))
    def remove(self, row: int):
        if 0 <= row < len(self.items):
            self.beginRemoveRows(QtCore.QModelIndex(), row, row)
            self.items.pop(row); self.endRemoveRows()

# ---------- Html dialog ----------
class HtmlEditDialog(QtWidgets.QDialog):
    def __init__(self, title: str, html: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(640, 460)
        self.editor = QtWidgets.QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.setHtml(html or "")
        self.editor.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.editor.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.editor.setStyleSheet(f"QTextEdit{{background:{PANEL_BG};}}")  # 白背景
        bar = RichBar(self.editor)
        btnBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btnBox.accepted.connect(self.accept); btnBox.rejected.connect(self.reject)
        lay = QtWidgets.QVBoxLayout(self); lay.addWidget(bar); lay.addWidget(self.editor, 1); lay.addWidget(btnBox)
    def get_html(self) -> str: return self.editor.toHtml()

# ---------- Main Window ----------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QtGui.QIcon.fromTheme("sticky-notes"))
        self.prev_geometry: QtCore.QRect | None = None

        self.state = load_json(DATA_FILE, DEFAULT_STATE)
        self.conf  = load_json(CONF_FILE, {"geometry": None})  # ← always_on_top は保存・復元しない

        # Global style
        self._apply_global_style()

        # ===== Top toolbar =====
        self.topBar = QtWidgets.QToolBar()
        self.topBar.setMovable(False)
        self.topBar.setIconSize(QtCore.QSize(18,18))
        self.topBar.setStyleSheet(f"""
            QToolBar{{padding:6px; border:0; background: {BG};}}
            QToolButton{{
                padding:6px 12px; border:1px solid {BORDER}; border-radius:8px; background:{PANEL_BG};
            }}
            QToolButton:checked{{background:{ACCENT_WEAK}; border-color:{ACCENT}; color:{FG};}}
            QToolButton:hover{{border-color:{ACCENT_HOVER};}}
        """)
        self.addToolBar(QtCore.Qt.TopToolBarArea, self.topBar)

        # 『常に手前』は起動時OFF固定（保存・復元しない）
        self.actOnTop = QtGui.QAction("常に手前に表示", self, checkable=True, checked=False)
        self.actOnTop.toggled.connect(self._toggle_always_on_top)
        btnOnTop = QtWidgets.QToolButton(); btnOnTop.setDefaultAction(self.actOnTop); btnOnTop.setCheckable(True)
        self.topBar.addWidget(btnOnTop)

        # ダブルクリックで 70%サイズトグル
        self.topBar.installEventFilter(self)

        # ===== Left Top: ToDo / Archive Tabs =====
        self.todoModel = TodoModel(self.state["todo"]["items"])
        self.todoList  = QtWidgets.QListView(); self.todoList.setModel(self.todoModel)
        self.todoList.doubleClicked.connect(self._edit_todo_item)

        self.todoInput = QtWidgets.QLineEdit(); self.todoInput.setPlaceholderText("ToDo を入力して Enter")
        self.todoInput.returnPressed.connect(self._add_todo)

        btnTgl = QtWidgets.QPushButton("完了/未完了")
        btnDel = QtWidgets.QPushButton("選択削除")
        btnArc = QtWidgets.QPushButton("完了→アーカイブ")
        btnTgl.clicked.connect(self._toggle_selected_todo)
        btnDel.clicked.connect(self._del_selected_todo)
        btnArc.clicked.connect(self._archive_done)

        todoPane = QtWidgets.QWidget(); vct = QtWidgets.QVBoxLayout(todoPane)
        vct.setContentsMargins(8,8,8,8)
        vct.addWidget(self.todoList); vct.addWidget(self.todoInput)
        hb2 = QtWidgets.QHBoxLayout(); hb2.addWidget(btnTgl); hb2.addWidget(btnArc); hb2.addWidget(btnDel)
        vct.addLayout(hb2)

        # Archive（タブで切替）
        self.archiveList = QtWidgets.QListWidget(); self._refresh_archive_list()
        self.archiveList.itemDoubleClicked.connect(self._edit_archive_item)
        btnArcDel = QtWidgets.QPushButton("選択アーカイブ削除")
        btnArcDel.clicked.connect(self._delete_selected_archive)
        arcPane = QtWidgets.QWidget(); varc = QtWidgets.QVBoxLayout(arcPane)
        varc.setContentsMargins(8,8,8,8)
        varc.addWidget(self.archiveList)
        varc.addWidget(btnArcDel, alignment=QtCore.Qt.AlignRight)

        self.centerTabs = QtWidgets.QTabWidget()
        self.centerTabs.addTab(todoPane, "ToDo")
        self.centerTabs.addTab(arcPane, "アーカイブ")

        # ===== Left Bottom: 常駐事項 =====
        self.categoryList = QtWidgets.QListWidget()
        self.categoryList.setDragEnabled(True)
        self.categoryList.setAcceptDrops(True)
        self.categoryList.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.categoryList.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)  # D&D 並べ替え
        self.categoryList.model().rowsMoved.connect(self._on_category_rows_moved)
        self._reload_category_list()
        self.categoryList.itemDoubleClicked.connect(self._open_category_popup)

        btnAdd = QtWidgets.QToolButton(); btnAdd.setText("＋")
        btnRen = QtWidgets.QToolButton(); btnRen.setText("改")
        btnDel = QtWidgets.QToolButton(); btnDel.setText("削")
        btnAdd.clicked.connect(self._add_category)
        btnRen.clicked.connect(self._rename_category)
        btnDel.clicked.connect(self._delete_category)

        leftBottom = QtWidgets.QWidget()
        vlb = QtWidgets.QVBoxLayout(leftBottom); vlb.setContentsMargins(8,0,8,8)
        titleCat = QtWidgets.QLabel("常駐事項"); titleCat.setStyleSheet("font-weight: bold; color: %s;" % FG)
        toolRow = QtWidgets.QHBoxLayout(); toolRow.addWidget(titleCat); toolRow.addStretch(1)
        toolRow.addWidget(btnAdd); toolRow.addWidget(btnRen); toolRow.addWidget(btnDel)
        vlb.addLayout(toolRow); vlb.addWidget(self.categoryList)

        # Left stack: ToDo (3) / 常駐 (7)
        leftStack = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(leftStack); grid.setContentsMargins(0,0,0,0)
        grid.setRowStretch(0,3); grid.setRowStretch(1,7)
        grid.addWidget(self.centerTabs, 0, 0)
        grid.addWidget(leftBottom,   1, 0)

        # ===== Right: Memo A/B（白背景・左右）=====
        self.memoEditor1 = QtWidgets.QTextEdit(); self.memoEditor1.setAcceptRichText(True)
        self.memoEditor2 = QtWidgets.QTextEdit(); self.memoEditor2.setAcceptRichText(True)
        # 白背景 & 余白
        for ed in (self.memoEditor1, self.memoEditor2):
            ed.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            ed.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            ed.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")

        # 初期内容
        self.memoEditor1.setHtml(self.state["memo1"]["html"])
        self.memoEditor2.setHtml(self.state["memo2"]["html"])
        self.memoEditor1.textChanged.connect(self._on_memo1_html_changed)
        self.memoEditor2.textChanged.connect(self._on_memo2_html_changed)

        memoBar1 = RichBar(self.memoEditor1)
        memoBar2 = RichBar(self.memoEditor2)

        memoPane1 = QtWidgets.QWidget(); v1 = QtWidgets.QVBoxLayout(memoPane1)
        v1.setContentsMargins(10,10,5,10); v1.setSpacing(6)
        lab1 = QtWidgets.QLabel("Memo A"); lab1.setStyleSheet("font-weight: bold; color:%s;" % FG)
        v1.addWidget(lab1); v1.addWidget(memoBar1); v1.addWidget(self.memoEditor1, 1)

        memoPane2 = QtWidgets.QWidget(); v2 = QtWidgets.QVBoxLayout(memoPane2)
        v2.setContentsMargins(5,10,10,10); v2.setSpacing(6)
        lab2 = QtWidgets.QLabel("Memo B"); lab2.setStyleSheet("font-weight: bold; color:%s;" % FG)
        v2.addWidget(lab2); v2.addWidget(memoBar2); v2.addWidget(self.memoEditor2, 1)

        rightSplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        rightSplitter.addWidget(memoPane1)
        rightSplitter.addWidget(memoPane2)
        rightSplitter.setStretchFactor(0, 1)
        rightSplitter.setStretchFactor(1, 1)
        rightSplitter.setChildrenCollapsible(False)
        rightSplitter.setHandleWidth(10)
        rightSplitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {HANDLE};
                border-left: 1px solid {BORDER};
                border-right: 1px solid {BORDER};
                margin: 6px 0;
            }}
        """)

        # 右全体の下端に少し余白
        rightWrap = QtWidgets.QWidget()
        vrw = QtWidgets.QVBoxLayout(rightWrap)
        vrw.setContentsMargins(0,0,0,8)
        vrw.addWidget(rightSplitter)

        # ===== Whole splitter =====
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(leftStack)
        splitter.addWidget(rightWrap)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setHandleWidth(10)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {HANDLE};
                border-left: 1px solid {BORDER};
                border-right: 1px solid {BORDER};
            }}
        """)
        self.setCentralWidget(splitter)

        # 起動時は必ず「常に手前 OFF」に固定（復元しない）
        self._force_standard_window_buttons()
        self._apply_on_top(False, first_time=True)

        self._restore_geometry()
        self._setup_tray()

        # Save timer
        self.saveTimer = QtCore.QTimer(self); self.saveTimer.setInterval(2000)
        self.saveTimer.timeout.connect(self._save_all); self.saveTimer.start()

    # ----- Global style -----
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {BG}; color: {FG}; }}
            QLineEdit, QListView, QTabWidget::pane, QMenu {{
                background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 8px;
            }}
            QListView::item:selected {{ background: {ACCENT_WEAK}; color: {FG}; }}
            QLineEdit {{ padding:6px 8px; }}
            QPushButton {{
                background: {PANEL_BG}; border:1px solid {BORDER}; border-radius:8px; padding:6px 10px;
            }}
            QPushButton:hover {{ border-color: {ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: #f2f6ff; border-color:{ACCENT}; }}
            QTabBar::tab {{
                background: {PANEL_BG}; border:1px solid {BORDER}; border-bottom: none; padding:6px 12px; margin-right:2px;
                border-top-left-radius:8px; border-top-right-radius:8px;
            }}
            QTabBar::tab:selected {{ background: {ACCENT_WEAK}; border-color:{ACCENT}; }}
            QTabWidget::pane {{ border-top: 1px solid {ACCENT}; border-radius:8px; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 6px; }}
            QScrollBar::handle:vertical:hover {{ background: {ACCENT_HOVER}; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 2px; }}
            QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 6px; }}
        """)

    # ----- Event filter (double-click topbar to size toggle) -----
    def eventFilter(self, obj, event):
        if obj is self.topBar and event.type() == QtCore.QEvent.MouseButtonDblClick:
            self._toggle_size_70(); return True
        return super().eventFilter(obj, event)

    def _toggle_size_70(self):
        # 最大化中は一旦通常に戻してから、70%サイズ or 前回サイズへ。
        if self.isMaximized():
            self.showNormal()
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        cur = self.geometry()
        target_w, target_h = int(avail.width()*0.7), int(avail.height()*0.7)
        near_70 = abs(cur.width()-target_w) <= int(avail.width()*0.02) and \
                  abs(cur.height()-target_h) <= int(avail.height()*0.02)
        if near_70 and self.prev_geometry:
            self.setGeometry(self.prev_geometry); self.prev_geometry = None
        else:
            self.prev_geometry = QtCore.QRect(cur)
            x = avail.left() + (avail.width()-target_w)//2
            y = avail.top()  + (avail.height()-target_h)//3
            self.setGeometry(x, y, target_w, target_h)
        self._save_window_conf()

    # ----- Tray -----
    def _setup_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self.windowIcon(), self)
        menu = QtWidgets.QMenu()
        act_show = menu.addAction("表示／前面へ"); act_hide = menu.addAction("最小化")
        menu.addSeparator()
        self.actTrayOnTop = menu.addAction("常に手前に表示")
        self.actTrayOnTop.setCheckable(True)
        self.actTrayOnTop.setChecked(False)                     # 起動時は必ずOFF
        self.actTrayOnTop.toggled.connect(self._toggle_always_on_top)
        menu.addSeparator()
        act_quit = menu.addAction("終了")
        act_show.triggered.connect(self._bring_front); act_hide.triggered.connect(self.showMinimized)
        act_quit.triggered.connect(QtWidgets.QApplication.quit)
        self.tray.setContextMenu(menu); self.tray.setToolTip(APP_TITLE); self.tray.show()

    # ----- Always on Top -----
    def _toggle_always_on_top(self, on: bool):
        # ボタン状態同期（相互反映）
        if hasattr(self, "actOnTop") and self.actOnTop.isChecked() != on:
            self.actOnTop.blockSignals(True); self.actOnTop.setChecked(on); self.actOnTop.blockSignals(False)
        if hasattr(self, "actTrayOnTop") and self.actTrayOnTop.isChecked() != on:
            self.actTrayOnTop.blockSignals(True); self.actTrayOnTop.setChecked(on); self.actTrayOnTop.blockSignals(False)

        self._apply_on_top(bool(on))

    def _apply_on_top(self, on: bool, first_time: bool = False):
        # - setWindowFlag(Qt.WindowStaysOnTopHint, on) で“そのフラグだけ”を切り替える。
        # - 標準ボタン（×/最小/最大）を常に有効化して、グレー化を防ぐ。
        # - show() / raise_() / activateWindow() で枠を安定再描画。
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, on)
        self._force_standard_window_buttons()

        # フラグ変更をOS側に反映
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()

        self.raise_(); self.activateWindow()

        # 起動直後は必ずOFFを維持（ツールバー側もOFFに戻す）
        if first_time and hasattr(self, "actOnTop"):
            self.actOnTop.blockSignals(True); self.actOnTop.setChecked(False); self.actOnTop.blockSignals(False)

    def _force_standard_window_buttons(self):
        # WindowCloseButtonHint / WindowMinMaxButtonsHint を常に True に固定。
        # これで OnTop 切替後も「×」が押せる状態を維持しやすい。
        self.setWindowFlag(QtCore.Qt.Window, True)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowMinMaxButtonsHint, True)

    # ----- Geometry -----
    def _restore_geometry(self):
        geo = self.conf.get("geometry")
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        if geo:
            rect = QtCore.QRect(*geo)
            # 画面ほぼいっぱいに広がっていたら70%から開始
            if rect.width() > int(avail.width()*0.98) or rect.height() > int(avail.height()*0.98):
                self._apply_percent_size(0.7)
            else:
                self.setGeometry(rect)
        else:
            self._apply_percent_size(0.7)

    def _apply_percent_size(self, ratio: float):
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        w, h = int(avail.width()*ratio), int(avail.height()*ratio)
        x = avail.left() + (avail.width()-w)//2
        y = avail.top()  + (avail.height()-h)//3
        self.setGeometry(x, y, w, h)

    def moveEvent(self, e): self._save_window_conf()
    def resizeEvent(self, e): self._save_window_conf()
    def _save_window_conf(self):
        g = self.geometry()
        self.conf["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        save_json(CONF_FILE, self.conf)

    # ----- 常駐事項 -----
    def _reload_category_list(self):
        self.categoryList.clear()
        order = self.state.get("category_order", [])
        keys  = list(self.state["categories"].keys())
        for k in keys:
            if k not in order: order.append(k)
        self.state["category_order"] = order
        for name in order:
            if name in self.state["categories"]:
                self.categoryList.addItem(name)

    def _on_category_rows_moved(self, *_):
        new_order = [self.categoryList.item(i).text() for i in range(self.categoryList.count())]
        self.state["category_order"] = new_order
        self._save_all()

    def _current_category_name(self):
        it = self.categoryList.currentItem()
        return it.text() if it else None

    def _add_category(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "常駐事項の追加", "名称：")
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "重複", "同名が既にあります。"); return
        self.state["categories"][name] = {"html": ""}
        self.state["category_order"].append(name)
        self._reload_category_list()
        items = self.categoryList.findItems(name, QtCore.Qt.MatchExactly)
        if items: self.categoryList.setCurrentItem(items[0]); self._save_all()

    def _rename_category(self):
        cur = self._current_category_name()
        if not cur: return
        new, ok = QtWidgets.QInputDialog.getText(self, "名称変更", "新しい名称：", text=cur)
        if not ok: return
        new = new.strip()
        if not new: return
        if new != cur and new in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "重複", "同名が既にあります。"); return
        self.state["categories"][new] = self.state["categories"].pop(cur)
        order = self.state["category_order"]
        self.state["category_order"] = [new if x == cur else x for x in order]
        self._reload_category_list()
        items = self.categoryList.findItems(new, QtCore.Qt.MatchExactly)
        if items: self.categoryList.setCurrentItem(items[0]); self._save_all()

    def _delete_category(self):
        cur = self._current_category_name()
        if not cur: return
        if QtWidgets.QMessageBox.question(self, "削除確認", f"「{cur}」を削除しますか？\n（内容も消えます）") != QtWidgets.QMessageBox.Yes:
            return
        self.state["categories"].pop(cur, None)
        self.state["category_order"] = [x for x in self.state["category_order"] if x != cur]
        self._reload_category_list(); self._save_all()

    def _open_category_popup(self, item: QtWidgets.QListWidgetItem):
        name = item.text()
        html = self.state["categories"].get(name, {}).get("html", "")
        dlg = HtmlEditDialog(f"常駐事項メモ：{name}", html, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.state["categories"][name]["html"] = dlg.get_html()
            self._save_all()

    # ----- ToDo -----
    def _add_todo(self):
        text = self.todoInput.text().strip()
        if not text: return
        self.todoModel.add(text); self.todoInput.clear(); self._save_all()

    def _selected_row(self):
        idx = self.todoList.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _toggle_selected_todo(self):
        row = self._selected_row()
        if row >= 0:
            self.todoModel.toggle(row); self._save_all()

    def _del_selected_todo(self):
        row = self._selected_row()
        if row >= 0:
            self.todoModel.remove(row); self._save_all()

    def _edit_todo_item(self, model_index: QtCore.QModelIndex):
        row = model_index.row()
        if row < 0 or row >= len(self.state["todo"]["items"]): return
        it = self.state["todo"]["items"][row]
        dlg = HtmlEditDialog("ToDo 編集", it.get("html", plain_to_html(it.get("text",""))), self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            new_html = dlg.get_html()
            it["html"] = new_html
            it["text"] = html_to_plain(new_html)
            self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
            self._save_all()

    def _archive_done(self):
        done = [it for it in self.state["todo"]["items"] if it.get("done")]
        if not done:
            QtWidgets.QMessageBox.information(self, "情報", "完了済みのToDoがありません。"); return
        now = int(time.time())
        for it in done:
            self.state["todo"]["archive"].append({
                "id": it["id"], "text": it["text"], "archived_at": now,
                "html": it.get("html", plain_to_html(it["text"]))
            })
        self.state["todo"]["items"] = [it for it in self.state["todo"]["items"] if not it.get("done")]
        self.todoModel.layoutChanged.emit()
        self._refresh_archive_list()
        self._save_all()
        self.centerTabs.setCurrentIndex(1)

    # ----- Archive -----
    def _delete_selected_archive(self):
        row = self.archiveList.currentRow()
        if row < 0: return
        if QtWidgets.QMessageBox.question(self, "削除確認", "選択したアーカイブ項目を削除しますか？") != QtWidgets.QMessageBox.Yes:
            return
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        target = sorted_arc[row]
        self.state["todo"]["archive"] = [it for it in self.state["todo"]["archive"] if it["id"] != target["id"]]
        self._refresh_archive_list(); self._save_all()

    def _edit_archive_item(self, item: QtWidgets.QListWidgetItem):
        row = self.archiveList.row(item)
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        target = sorted_arc[row]
        dlg = HtmlEditDialog("アーカイブ編集", target.get("html", plain_to_html(target.get("text",""))), self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            new_html = dlg.get_html()
            for it in self.state["todo"]["archive"]:
                if it["id"] == target["id"]:
                    it["html"] = new_html
                    it["text"] = html_to_plain(new_html)
                    break
            self._refresh_archive_list(); self._save_all()

    def _refresh_archive_list(self):
        self.archiveList.clear()
        for it in sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True):
            ts = QtCore.QDateTime.fromSecsSinceEpoch(it.get("archived_at", 0)).toString("yyyy-MM-dd HH:mm")
            self.archiveList.addItem(f"{ts}  -  {it['text']}")

    # ----- Memo -----
    def _on_memo1_html_changed(self): self.state["memo1"]["html"] = self.memoEditor1.toHtml()
    def _on_memo2_html_changed(self): self.state["memo2"]["html"] = self.memoEditor2.toHtml()

    # ----- Common -----
    def _bring_front(self):
        self.showNormal(); self.raise_(); self.activateWindow()
    def _save_all(self):
        save_json(DATA_FILE, self.state)

# ---------- Entry ----------
def main():
    install_excepthook()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    w = MainWindow(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":

    main()
