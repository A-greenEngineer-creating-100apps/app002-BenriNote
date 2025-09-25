# benrinote.py
# =========================================================
# 便利ノート（PySide6 / 単一ファイル）
# =========================================================

from __future__ import annotations
import json, os, sys, uuid, time, re, traceback
from typing import Dict, Any, List, Optional, Tuple
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
ACCENT, ACCENT_HOVER, ACCENT_WEAK = "#4F8AF3", "#6BA0F6", "#E6E6FF"
FG, BG, PANEL_BG = "#222222", "#FAFAFB", "#FFFFFF"
BORDER, HANDLE = "#E6E6EA", "#EAEAEA"

DEFAULT_STATE = {
    "todo": {"items": [], "archive": []},   # items: {id,title,done,html}
    "categories": {},                        # "カテゴリ名": {"items":[{id,title,html},...]}
    "category_order": [],
    "memo2": {"html": ""},                   # フリースペース
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
def html_to_plain(html: str) -> str:
    if not html: return ""
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.I | re.S)
    html = re.sub(r"<head\b[^>]*>.*?</head>", "", html, flags=re.I | re.S)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    return QtGui.QTextDocumentFragment.fromHtml(html).toPlainText().strip()

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

# =========================================================
# リスト用：区切り線 delegate
# =========================================================
class SeparatorDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter, option, index):
        super().paint(painter, option, index)
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(BORDER)); pen.setWidth(1)
        painter.setPen(pen)
        y = option.rect.bottom() - 1
        painter.drawLine(option.rect.left() + 6, y, option.rect.right() - 6, y)
        painter.restore()

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        return QtCore.QSize(sz.width(), max(sz.height(), 24))

# =========================================================
# 画像リサイズ用：右下ハンドル付き QTextEdit
# =========================================================
class _ResizeHandle(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget, drag_cb):
        super().__init__(parent)
        self.setCursor(QtCore.Qt.SizeFDiagCursor)
        self.setFixedSize(10, 10)
        self.setStyleSheet("background:#ffffff;border:1px solid #4F8AF3;border-radius:1px;")
        self._drag_cb = drag_cb
        self._press_pos: Optional[QtCore.QPoint] = None

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint(); e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self._press_pos is not None:
            delta = e.globalPosition().toPoint() - self._press_pos
            self._drag_cb(delta.x(), delta.y())
            self._press_pos = e.globalPosition().toPoint()
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        self._press_pos = None
        super().mouseReleaseEvent(e)

class HandleTextEdit(QtWidgets.QTextEdit):
    """画像上にカーソルを置くと右下に□が出て、ドラッグで幅を変更できる。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(True)
        self._handle = _ResizeHandle(self.viewport(), self._on_drag_delta)
        self._handle.hide()
        self._img_cursor: Optional[QtGui.QTextCursor] = None

        self.cursorPositionChanged.connect(self._refresh_handle)
        self.textChanged.connect(self._refresh_handle)
        self.viewport().installEventFilter(self)

    def _get_image_cursor(self) -> Tuple[Optional[QtGui.QTextCursor], Optional[QtGui.QTextImageFormat]]:
        cur = self.textCursor()

        def fmt_of(c: QtGui.QTextCursor):
            f = c.charFormat()
            return (c, f.toImageFormat()) if f.isImageFormat() else (None, None)

        c, f = fmt_of(cur)
        if f: return c, f
        cur2 = QtGui.QTextCursor(cur)
        if cur2.position() > 0:
            cur2.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.MoveAnchor, 1)
            c, f = fmt_of(cur2)
            if f: return c, f
        return None, None

    def _calc_image_rect(self, c: QtGui.QTextCursor, f: QtGui.QTextImageFormat) -> QtCore.QRect:
        caret = self.cursorRect(c)
        w = int(f.width()) if f.width() > 0 else 400
        h = int(f.height()) if f.height() > 0 else w
        top_left = QtCore.QPoint(caret.left(), caret.bottom() - h)
        return QtCore.QRect(top_left, QtCore.QSize(w, h))

    def _refresh_handle(self):
        cur, imgf = self._get_image_cursor()
        if not imgf or not cur:
            self._img_cursor = None; self._handle.hide(); return
        self._img_cursor = QtGui.QTextCursor(cur)
        rect = self._calc_image_rect(cur, imgf)
        self._handle.move(rect.right() - self._handle.width() + 1,
                          rect.bottom() - self._handle.height() + 1)
        self._handle.show()
        self.viewport().update()

    def eventFilter(self, obj, ev):
        if obj is self.viewport():
            if ev.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Wheel, QtCore.QEvent.Paint,
                             QtCore.QEvent.Scroll, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
                QtCore.QTimer.singleShot(0, self._refresh_handle)
        return super().eventFilter(obj, ev)

    def _on_drag_delta(self, dx: int, dy: int):
        if not self._img_cursor: return
        cur = QtGui.QTextCursor(self._img_cursor)
        fmt = cur.charFormat()
        if not fmt.isImageFormat(): return
        imgf = fmt.toImageFormat()
        cur_w = imgf.width() if imgf.width() > 0 else 400.0
        new_w = max(48.0, cur_w + dx)
        imgf.setWidth(float(new_w))
        cur.mergeCharFormat(imgf)
        self._refresh_handle()

# =========================================================
# リッチツールバー
# =========================================================
def _icon_under(size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    font = QtGui.QFont("Segoe UI"); font.setBold(True); font.setPointSizeF(size * 0.65)
    p.setFont(font); p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
    rect = QtCore.QRectF(0, -2, size, size)
    p.drawText(rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, "A")
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
    y = int(size * 0.82); p.drawLine(int(size*0.18), y, int(size*0.82), y); p.end()
    return QtGui.QIcon(pm)

def _icon_palette(color: QtGui.QColor, size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    path = QtGui.QPainterPath(); r = size - 2
    path.addRoundedRect(QtCore.QRectF(1, 2, r, r-2), size*0.3, size*0.3)
    hole = QtGui.QPainterPath(); hole.addEllipse(QtCore.QRectF(size*0.45, size*0.55, size*0.28, size*0.28))
    shape = path.subtracted(hole)
    p.fillPath(shape, QtGui.QBrush(QtGui.QColor(245,245,245)))
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 1)); p.drawPath(shape)
    p.setBrush(QtGui.QBrush(color)); p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
    p.drawEllipse(QtCore.QRectF(size*0.18, size*0.22, size*0.28, size*0.28)); p.end()
    return QtGui.QIcon(pm)

def _icon_picture(size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 1)); p.setBrush(QtGui.QBrush(QtGui.QColor("#eaeefc")))
    p.drawRoundedRect(1,3,size-2,size-6,4,4)
    p.setBrush(QtGui.QBrush(QtGui.QColor("#b7d2ff")))
    points = [QtCore.QPointF(size*0.2,size*0.7), QtCore.QPointF(size*0.45,size*0.45), QtCore.QPointF(size*0.75,size*0.75)]
    p.drawPolygon(QtGui.QPolygonF(points))
    p.setBrush(QtGui.QBrush(QtGui.QColor("#ffd866"))); p.setPen(QtGui.QPen(QtGui.QColor(FG), 0))
    p.drawEllipse(QtCore.QRectF(size*0.58,size*0.22,size*0.16,size*0.16)); p.end()
    return QtGui.QIcon(pm)

def _icon_resize(size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 2)); p.drawRect(3,3,size-6,size-6)
    p.drawLine(size-8,size-3,size-3,size-8); p.end()
    return QtGui.QIcon(pm)

class RichBar(QtWidgets.QToolBar):
    htmlChanged = QtCore.Signal()
    def __init__(self, target: QtWidgets.QTextEdit, parent=None):
        super().__init__(parent)
        self.target = target
        self.setIconSize(QtCore.QSize(18, 18))
        self.setStyleSheet("QToolBar{border:0; background: transparent;}")

        self.actUnderline = QtGui.QAction(_icon_under(), "下線", self)
        self.actUnderline.setCheckable(True); self.actUnderline.toggled.connect(self._underline)
        self.addAction(self.actUnderline)

        self._color = QtGui.QColor(FG)
        self.actColor = QtGui.QAction(_icon_palette(self._color), "文字色", self)
        self.actColor.triggered.connect(self._pick_text_color); self.addAction(self.actColor)

        self.addSeparator()

        self._bg = QtGui.QColor(PANEL_BG)
        self.actBG = QtGui.QAction(_icon_palette(self._bg), "背景色（エディタ）", self)
        self.actBG.triggered.connect(self._pick_bg_color); self.addAction(self.actBG)

        self.actPasteImg = QtGui.QAction(_icon_picture(), "画像貼り付け（クリップボード）", self)
        self.actPasteImg.triggered.connect(self._paste_image_from_clipboard); self.addAction(self.actPasteImg)

        self.actInsertImg = QtGui.QAction(_icon_picture(), "画像挿入（ファイル）", self)
        self.actInsertImg.triggered.connect(self._insert_image_from_file); self.addAction(self.actInsertImg)

        self.actResizeImg = QtGui.QAction(_icon_resize(), "画像サイズ変更（数値指定）", self)
        self.actResizeImg.triggered.connect(self._resize_selected_image); self.addAction(self.actResizeImg)

    def _underline(self, on: bool):
        fmt = QtGui.QTextCharFormat(); fmt.setFontUnderline(on); self._merge(fmt)

    def _pick_text_color(self):
        col = QtWidgets.QColorDialog.getColor(self._color, self, "文字色を選択")
        if col.isValid():
            self._color = col; self.actColor.setIcon(_icon_palette(self._color))
            fmt = QtGui.QTextCharFormat(); fmt.setForeground(QtGui.QBrush(col)); self._merge(fmt)

    def _merge(self, fmt: QtGui.QTextCharFormat):
        cur = self.target.textCursor()
        if cur.hasSelection(): cur.mergeCharFormat(fmt)
        else: self.target.mergeCurrentCharFormat(fmt)
        self.htmlChanged.emit()

    def _pick_bg_color(self):
        col = QtWidgets.QColorDialog.getColor(self._bg, self, "背景色（エディタ）を選択")
        if not col.isValid(): return
        self._bg = col; self.actBG.setIcon(_icon_palette(self._bg))
        self.target.setStyleSheet(
            f"QTextEdit{{background:{col.name()}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}"
        )

    def _paste_image_from_clipboard(self):
        cb = QtWidgets.QApplication.clipboard()
        if img := cb.image():
            self.target.textCursor().insertImage(QtGui.QImage(img))
            self.htmlChanged.emit()
        else:
            QtWidgets.QMessageBox.information(self, "情報", "クリップボードに画像がありません。")

    def _insert_image_from_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "画像を選択", "", "画像ファイル (*.png *.jpg *.jpeg *.bmp *.gif)")
        if not path: return
        qimg = QtGui.QImage(path)
        if qimg.isNull():
            QtWidgets.QMessageBox.warning(self, "失敗", "画像を読み込めませんでした。"); return
        self.target.textCursor().insertImage(qimg)
        self.htmlChanged.emit()

    def _resize_selected_image(self):
        cur = self.target.textCursor()
        fmt = cur.charFormat()
        if not fmt.isImageFormat():
            QtWidgets.QMessageBox.information(self, "情報", "サイズ変更したい画像を選択（画像上にカーソル）してください。")
            return
        imgf = fmt.toImageFormat()
        current_w = int(imgf.width()) if imgf.width() > 0 else 400
        new_w, ok = QtWidgets.QInputDialog.getInt(self, "画像の幅", "幅 (px)：", current_w, 48, 4000, 1)
        if not ok: return
        imgf.setWidth(float(new_w))
        cur.mergeCharFormat(imgf)
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
            return ("[✓] " if it.get("done") else "[ ] ") + it.get("title","")
        if role == QtCore.Qt.FontRole and it.get("done"):
            f = QtGui.QFont(); f.setStrikeOut(True); return f
        return None
    def add(self, title: str):
        self.beginInsertRows(QtCore.QModelIndex(), len(self.items), len(self.items))
        self.items.append({"id": str(uuid.uuid4()), "title": title, "done": False, "html": ""})
        self.endInsertRows()
    def toggle(self, row: int):
        if 0 <= row < len(self.items):
            self.items[row]["done"] = not self.items[row]["done"]
            self.dataChanged.emit(self.index(row), self.index(row))
    def remove(self, row: int):
        if 0 <= row < len(self.items):
            self.beginRemoveRows(QtCore.QModelIndex(), row, row)
            self.items.pop(row); self.endRemoveRows()

# ---------- Main Window ----------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, app_icon: QtGui.QIcon):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon)
        self.prev_geometry: Optional[QtCore.QRect] = None

        self.state = load_json(DATA_FILE, DEFAULT_STATE)
        # ToDo: 古い text フィールドの移行
        changed = False
        for it in self.state["todo"]["items"]:
            if "title" not in it: it["title"] = it.get("text",""); changed = True
        for it in self.state["todo"]["archive"]:
            if "title" not in it: it["title"] = it.get("text",""); changed = True
        if changed: save_json(DATA_FILE, self.state)

        self._migrate_categories_to_items()
        self.conf = load_json(CONF_FILE, {"geometry": None})

        self._detail_ref: Optional[Tuple] = None
        self._apply_global_style()

        # ===== Top toolbar =====
        self.topBar = QtWidgets.QToolBar()
        self.topBar.setMovable(False)
        self.topBar.setIconSize(QtCore.QSize(18,18))
        self.topBar.setStyleSheet(f"""
            QToolBar{{padding:6px; border:0; background: {BG};}}
            QToolButton{{padding:6px 12px; border:1px solid {BORDER}; border-radius:8px; background:{PANEL_BG};}}
            QToolButton:checked{{background:{ACCENT_WEAK}; border-color:{ACCENT}; color:{FG};}}
            QToolButton:hover{{border-color:{ACCENT_HOVER};}}
        """)
        self.addToolBar(QtCore.Qt.TopToolBarArea, self.topBar)
        self.actOnTop = QtGui.QAction("常に手前に表示", self, checkable=True, checked=False)
        self.actOnTop.toggled.connect(self._toggle_always_on_top)
        btnOnTop = QtWidgets.QToolButton(); btnOnTop.setDefaultAction(self.actOnTop); btnOnTop.setCheckable(True)
        self.topBar.addWidget(btnOnTop)
        self.topBar.installEventFilter(self)

        # ===== 右：詳細 & フリースペース =====
        self.detailEditor = HandleTextEdit()
        self.detailEditor.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")
        self.detailBar = RichBar(self.detailEditor)
        self.detailLabel = QtWidgets.QLabel("詳細"); self.detailLabel.setStyleSheet("font-weight:bold; color:%s;" % FG)

        self._detailTimer = QtCore.QTimer(self); self._detailTimer.setSingleShot(True); self._detailTimer.setInterval(400)
        self.detailEditor.textChanged.connect(lambda: self._detailTimer.start())
        self._detailTimer.timeout.connect(self._apply_detail_to_state)

        detailPane = QtWidgets.QWidget(); v1 = QtWidgets.QVBoxLayout(detailPane)
        v1.setContentsMargins(10,10,5,10); v1.setSpacing(6)
        v1.addWidget(self.detailLabel); v1.addWidget(self.detailBar); v1.addWidget(self.detailEditor, 1)

        self.memoFree = HandleTextEdit()
        self.memoFree.setHtml(self.state["memo2"]["html"])
        self.memoFree.textChanged.connect(self._on_free_html_changed)
        self.memoFree.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")
        self.memoFreeBar = RichBar(self.memoFree)
        labFree = QtWidgets.QLabel("フリースペース"); labFree.setStyleSheet("font-weight:bold; color:%s;" % FG)

        freePane = QtWidgets.QWidget(); v2 = QtWidgets.QVBoxLayout(freePane)
        v2.setContentsMargins(5,10,10,10); v2.setSpacing(6)
        v2.addWidget(labFree); v2.addWidget(self.memoFreeBar); v2.addWidget(self.memoFree, 1)

        rightSplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        rightSplitter.addWidget(detailPane); rightSplitter.addWidget(freePane)
        rightSplitter.setStretchFactor(0, 1); rightSplitter.setStretchFactor(1, 1)
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
        rightWrap = QtWidgets.QWidget()
        vrw = QtWidgets.QVBoxLayout(rightWrap); vrw.setContentsMargins(0,0,0,8); vrw.addWidget(rightSplitter)

        # ===== 左：ToDo / アーカイブ =====
        self.todoModel = TodoModel(self.state["todo"]["items"])
        self.todoList  = QtWidgets.QListView(); self.todoList.setModel(self.todoModel)
        self.todoList.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.todoList.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.todoList.setItemDelegate(SeparatorDelegate(self.todoList))
        self.todoList.selectionModel().currentChanged.connect(self._on_todo_selected)
        self.todoList.clicked.connect(lambda idx: self._load_detail(("todo", idx.row())))
        self.todoInput = QtWidgets.QLineEdit(); self.todoInput.setPlaceholderText("ToDo を入力して Enter")
        self.todoInput.returnPressed.connect(self._add_todo)
        btnTgl = QtWidgets.QPushButton("完了/未完了")
        btnDel = QtWidgets.QPushButton("選択削除")
        btnArc = QtWidgets.QPushButton("完了→アーカイブ")
        btnRen = QtWidgets.QPushButton("タイトル変更")
        btnTgl.clicked.connect(self._toggle_selected_todo)
        btnDel.clicked.connect(self._del_selected_todo)
        btnArc.clicked.connect(self._archive_done)
        btnRen.clicked.connect(self._rename_selected_todo)
        todoPane = QtWidgets.QWidget(); vct = QtWidgets.QVBoxLayout(todoPane)
        vct.setContentsMargins(8,8,8,8)
        vct.addWidget(self.todoList); vct.addWidget(self.todoInput)
        hb2 = QtWidgets.QHBoxLayout()
        hb2.addWidget(btnTgl); hb2.addWidget(btnArc); hb2.addWidget(btnRen); hb2.addWidget(btnDel)
        vct.addLayout(hb2)

        # Archive
        self.archiveList = QtWidgets.QListWidget(); self._refresh_archive_list()
        self.archiveList.setItemDelegate(SeparatorDelegate(self.archiveList))
        self.archiveList.itemDoubleClicked.connect(self._edit_archive_item)
        btnArcDel = QtWidgets.QPushButton("選択アーカイブ削除")
        btnArcDel.clicked.connect(self._delete_selected_archive)
        arcPane = QtWidgets.QWidget(); varc = QtWidgets.QVBoxLayout(arcPane)
        varc.setContentsMargins(8,8,8,8); varc.addWidget(self.archiveList)
        varc.addWidget(btnArcDel, alignment=QtCore.Qt.AlignRight)

        self.centerTabs = QtWidgets.QTabWidget()
        self.centerTabs.addTab(todoPane, "ToDo")
        self.centerTabs.addTab(arcPane, "アーカイブ")

        # ===== 左：常駐カテゴリ（タブ）=====
        self.residentTabs = QtWidgets.QTabWidget()
        self.residentTabs.setTabsClosable(False)
        self.residentTabs.tabBar().setMovable(True)
        self.residentTabs.tabBar().installEventFilter(self)
        btnAddCat = QtWidgets.QToolButton(); btnAddCat.setText("＋"); btnAddCat.clicked.connect(self._add_resident_tab)
        btnRenCat = QtWidgets.QToolButton(); btnRenCat.setText("改"); btnRenCat.clicked.connect(self._rename_resident_tab)
        btnDelCat = QtWidgets.QToolButton(); btnDelCat.setText("削"); btnDelCat.clicked.connect(self._delete_resident_tab)
        leftBottom = QtWidgets.QWidget()
        vlb = QtWidgets.QVBoxLayout(leftBottom); vlb.setContentsMargins(8,0,8,8)
        titleCat = QtWidgets.QLabel("常駐事項"); titleCat.setStyleSheet("font-weight: bold; color: %s;" % FG)
        toolRow = QtWidgets.QHBoxLayout(); toolRow.addWidget(titleCat); toolRow.addStretch(1)
        toolRow.addWidget(btnAddCat); toolRow.addWidget(btnRenCat); toolRow.addWidget(btnDelCat)
        vlb.addLayout(toolRow); vlb.addWidget(self.residentTabs)
        self._rebuild_resident_tabs()

        # ===== 左：上下スプリッタ =====
        leftSplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        leftSplit.addWidget(self.centerTabs)
        leftSplit.addWidget(leftBottom)
        leftSplit.setStretchFactor(0, 3); leftSplit.setStretchFactor(1, 7)
        leftSplit.setHandleWidth(10)
        leftSplit.setStyleSheet(f"QSplitter::handle{{background:{HANDLE}; border:1px solid {BORDER};}}")

        # ===== 全体スプリッタ =====
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(leftSplit); splitter.addWidget(rightWrap)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 3)
        splitter.setHandleWidth(10)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {HANDLE};
                border-left: 1px solid {BORDER};
                border-right: 1px solid {BORDER};
            }}
        """)
        self.setCentralWidget(splitter)

        # 起動時は OnTop OFF 固定
        self._force_standard_window_buttons()
        self._apply_on_top(False, first_time=True)
        self._restore_geometry()
        self._setup_tray()

        # 定期保存
        self.saveTimer = QtCore.QTimer(self); self.saveTimer.setInterval(2000)
        self.saveTimer.timeout.connect(self._save_all); self.saveTimer.start()

        # 初期選択（1件でも確実に詳細が出る）
        self._load_detail(None)
        if self.todoModel.rowCount() > 0:
            self.todoList.setCurrentIndex(self.todoModel.index(0))
            self._load_detail(("todo", 0))

    # ====== 旧データ形式 → 新形式への移行 ======
    def _migrate_categories_to_items(self):
        self.state.setdefault("categories", {})
        self.state.setdefault("category_order", [])
        changed = False
        cats = self.state["categories"]
        for name, val in list(cats.items()):
            if isinstance(val, dict) and "items" not in val:
                html = val.get("html", "")
                cats[name] = {"items": []}
                if html:
                    cats[name]["items"].append({"id": str(uuid.uuid4()), "title": "メモ", "html": html})
                changed = True
            else:
                items = cats[name].get("items", [])
                for it in items:
                    if "id" not in it: it["id"] = str(uuid.uuid4()); changed = True
                    if "title" not in it: it["title"] = "無題"; changed = True
                    if "html" not in it: it["html"] = ""; changed = True
        if changed: save_json(DATA_FILE, self.state)

    # ====== 常駐カテゴリ UI ======
    def _rebuild_resident_tabs(self):
        self.residentTabs.blockSignals(True)
        self.residentTabs.clear()
        order = list(self.state.get("category_order", []))
        for k in self.state["categories"].keys():
            if k not in order: order.append(k)
        self.state["category_order"] = order
        for name in order:
            self.residentTabs.addTab(self._build_category_widget(name), name)
        self.residentTabs.tabBar().tabMoved.connect(self._on_resident_tab_moved)
        self.residentTabs.blockSignals(False)

    def _build_category_widget(self, cat_name: str) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap); v.setContentsMargins(6,6,6,6); v.setSpacing(6)

        lst = QtWidgets.QListWidget(objectName=f"list_{cat_name}")
        lst.setStyleSheet("QListWidget{background:%s; border:1px solid %s; border-radius:8px;}" % (PANEL_BG, BORDER))
        lst.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        lst.setDefaultDropAction(QtCore.Qt.MoveAction)
        lst.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        lst.setItemDelegate(SeparatorDelegate(lst))

        lst.currentRowChanged.connect(lambda row, cn=cat_name: self._on_resident_selected(cn, row))
        lst.itemClicked.connect(lambda _it, cn=cat_name, w=lst: self._on_resident_selected(cn, w.currentRow()))
        lst.model().rowsMoved.connect(lambda *_a, cn=cat_name, w=lst: self._on_resident_item_rows_moved(cn, w))

        for it in self.state["categories"].get(cat_name, {}).get("items", []):
            lst.addItem(it.get("title", "無題"))

        hb = QtWidgets.QHBoxLayout()
        btnAdd = QtWidgets.QPushButton("項目追加")
        btnRen = QtWidgets.QPushButton("項目名変更")
        btnDel = QtWidgets.QPushButton("項目削除")
        hb.addWidget(btnAdd); hb.addWidget(btnRen); hb.addWidget(btnDel); hb.addStretch(1)

        btnAdd.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._add_resident_item(cn, w))
        btnRen.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._rename_resident_item(cn, w))
        btnDel.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._delete_resident_item(cn, w))

        v.addWidget(lst, 1); v.addLayout(hb)

        if lst.count() > 0:
            lst.setCurrentRow(0)
            self._on_resident_selected(cat_name, 0)

        return wrap

    # --- 常駐：項目操作 ---
    def _add_resident_item(self, cat_name: str, list_widget: QtWidgets.QListWidget):
        title, ok = QtWidgets.QInputDialog.getText(self, "項目の追加", "項目名：")
        if not ok or not title.strip(): return
        item = {"id": str(uuid.uuid4()), "title": title.strip(), "html": ""}
        self.state["categories"][cat_name]["items"].append(item)
        list_widget.addItem(item["title"])
        row = list_widget.count() - 1
        list_widget.setCurrentRow(row)
        self._on_resident_selected(cat_name, row)
        self._save_all()

    def _rename_resident_item(self, cat_name: str, list_widget: QtWidgets.QListWidget):
        row = list_widget.currentRow()
        if row < 0: return
        cur_title = self.state["categories"][cat_name]["items"][row]["title"]
        new, ok = QtWidgets.QInputDialog.getText(self, "項目名の変更", "新しい名前：", text=cur_title)
        if not ok: return
        new = new.strip()
        if not new: return
        self.state["categories"][cat_name]["items"][row]["title"] = new
        list_widget.item(row).setText(new)
        if self._detail_ref and self._detail_ref[0] == "resident" and self._detail_ref[1] == cat_name and self._detail_ref[2] == row:
            self.detailLabel.setText(f"詳細（{cat_name} / {new}）")
        self._save_all()

    def _delete_resident_item(self, cat_name: str, list_widget: QtWidgets.QListWidget):
        row = list_widget.currentRow()
        if row < 0: return
        title = self.state["categories"][cat_name]["items"][row]["title"]
        if QtWidgets.QMessageBox.question(self, "削除確認", f"「{title}」を削除しますか？") != QtWidgets.QMessageBox.Yes:
            return
        self.state["categories"][cat_name]["items"].pop(row)
        list_widget.takeItem(row)
        if list_widget.currentRow() < 0:
            self._load_detail(None)
        self._save_all()

    def _on_resident_item_rows_moved(self, cat_name: str, list_widget: QtWidgets.QListWidget):
        items = self.state["categories"][cat_name]["items"]
        new_titles = [list_widget.item(i).text() for i in range(list_widget.count())]
        title_to_list: Dict[str, List[Dict[str,Any]]] = {}
        for it in items:
            title_to_list.setdefault(it["title"], []).append(it)
        new_items = []
        for t in new_titles:
            new_items.append(title_to_list[t].pop(0))
        self.state["categories"][cat_name]["items"] = new_items
        self._save_all()

    # --- セレクション → 詳細に読み込み ---
    def _on_todo_selected(self, current: QtCore.QModelIndex, previous: QtCore.QModelIndex):
        self._load_detail(("todo", current.row()) if current.isValid() else None)

    def _on_resident_selected(self, cat_name: str, row: int):
        self._load_detail(("resident", cat_name, row) if row >= 0 else None)

    # --- 詳細欄ロード／保存 ---
    def _load_detail(self, ref: Optional[Tuple]):
        self._apply_detail_to_state()
        self._detail_ref = ref
        if ref is None:
            self.detailLabel.setText("詳細")
            self.detailEditor.blockSignals(True)
            self.detailEditor.clear()
            self.detailEditor.setPlaceholderText("ToDo または 常駐事項の項目を選択すると、ここで詳細編集できます。")
            self.detailEditor.blockSignals(False)
            return
        if ref[0] == "todo":
            row = ref[1]
            if 0 <= row < len(self.state["todo"]["items"]):
                it = self.state["todo"]["items"][row]
                self.detailLabel.setText(f"詳細（ToDo / {it.get('title','')}）")
                self.detailEditor.blockSignals(True)
                self.detailEditor.setHtml(it.get("html", ""))
                self.detailEditor.blockSignals(False)
        else:
            _, cat, row = ref
            items = self.state["categories"].get(cat, {}).get("items", [])
            if 0 <= row < len(items):
                it = items[row]
                self.detailLabel.setText(f"詳細（{cat} / {it.get('title','無題')}）")
                self.detailEditor.blockSignals(True)
                self.detailEditor.setHtml(it.get("html",""))
                self.detailEditor.blockSignals(False)

    def _apply_detail_to_state(self):
        if not self._detail_ref: return
        html = self.detailEditor.toHtml()
        if self._detail_ref[0] == "todo":
            row = self._detail_ref[1]
            if 0 <= row < len(self.state["todo"]["items"]):
                self.state["todo"]["items"][row]["html"] = html
                self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
        else:
            _, cat, row = self._detail_ref
            items = self.state["categories"][cat]["items"]
            if 0 <= row < len(items):
                items[row]["html"] = html
        self._save_all()

    # --- カテゴリ（タブ）操作 ---
    def _on_resident_tab_moved(self, from_idx: int, to_idx: int):
        self.state["category_order"] = [self.residentTabs.tabText(i) for i in range(self.residentTabs.count())]
        self._save_all()

    def _add_resident_tab(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "カテゴリの追加", "カテゴリ名：")
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "重複", "同名のカテゴリが既にあります。"); return
        self.state["categories"][name] = {"items": []}
        self.state["category_order"].append(name)
        self._rebuild_resident_tabs()
        for i in range(self.residentTabs.count()):
            if self.residentTabs.tabText(i) == name:
                self.residentTabs.setCurrentIndex(i); break
        self._save_all()

    def _rename_resident_tab(self):
        cur = self.residentTabs.currentIndex()
        if cur < 0: return
        old = self.residentTabs.tabText(cur)
        new, ok = QtWidgets.QInputDialog.getText(self, "カテゴリ名の変更", "新しい名前：", text=old)
        if not ok: return
        new = new.strip()
        if not new or new == old: return
        if new in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "重複", "同名のカテゴリが既にあります。"); return
        self.state["categories"][new] = self.state["categories"].pop(old)
        self.state["category_order"] = [new if x == old else x for x in self.state["category_order"]]
        self._rebuild_resident_tabs()
        for i in range(self.residentTabs.count()):
            if self.residentTabs.tabText(i) == new:
                self.residentTabs.setCurrentIndex(i); break
        self._save_all()

    def _delete_resident_tab(self):
        cur = self.residentTabs.currentIndex()
        if cur < 0: return
        name = self.residentTabs.tabText(cur)
        if QtWidgets.QMessageBox.question(self, "削除確認", f"カテゴリ「{name}」を削除しますか？\n（項目も全て消えます）") != QtWidgets.QMessageBox.Yes:
            return
        self.state["categories"].pop(name, None)
        self.state["category_order"] = [x for x in self.state["category_order"] if x != name]
        self._rebuild_resident_tabs()
        if self._detail_ref and self._detail_ref[0] == "resident" and self._detail_ref[1] == name:
            self._load_detail(None)
        self._save_all()

    # ----- ToDo 操作 -----
    def _add_todo(self):
        title = self.todoInput.text().strip()
        if not title: return
        self.todoModel.add(title); self.todoInput.clear(); self._save_all()
        # 追加直後に選択
        row = self.todoModel.rowCount(None) - 1
        self.todoList.setCurrentIndex(self.todoModel.index(row))
        self._load_detail(("todo", row))

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
            self.todoModel.remove(row)
            self._save_all()
            if self.todoModel.rowCount(None) == 0:
                self._load_detail(None)

    def _rename_selected_todo(self):
        row = self._selected_row()
        if row < 0: return
        cur_title = self.state["todo"]["items"][row]["title"]
        new, ok = QtWidgets.QInputDialog.getText(self, "タイトル変更", "新しいタイトル：", text=cur_title)
        if not ok: return
        new = new.strip()
        if not new: return
        self.state["todo"]["items"][row]["title"] = new
        self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
        if self._detail_ref and self._detail_ref[0] == "todo" and self._detail_ref[1] == row:
            self.detailLabel.setText(f"詳細（ToDo / {new}）")
        self._save_all()

    def _archive_done(self):
        done = [it for it in self.state["todo"]["items"] if it.get("done")]
        if not done:
            QtWidgets.QMessageBox.information(self, "情報", "完了済みのToDoがありません。"); return
        now = int(time.time())
        for it in done:
            self.state["todo"]["archive"].append({
                "id": it["id"], "title": it["title"], "archived_at": now,
                "html": it.get("html", "")
            })
        self.state["todo"]["items"] = [it for it in self.state["todo"]["items"] if not it.get("done")]
        self.todoModel.layoutChanged.emit()
        self._refresh_archive_list()
        self._save_all()
        self.centerTabs.setCurrentIndex(1)

    # ----- Archive -----
    def _refresh_archive_list(self):
        self.archiveList.clear()
        for it in sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True):
            ts = QtCore.QDateTime.fromSecsSinceEpoch(it.get("archived_at", 0)).toString("yyyy-MM-dd HH:mm")
            self.archiveList.addItem(f"{ts}  -  {it['title']}")

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
        # アーカイブの詳細は右の「詳細」ではなく、この場で編集（簡易）
        text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "アーカイブ編集", "本文（テキスト）", html_to_plain(target.get("html","")))
        if ok:
            target["html"] = QtGui.QTextDocumentFragment.fromPlainText(text).toHtml()
            self._save_all()

    # ----- 右側：フリースペース保存 -----
    def _on_free_html_changed(self):
        self.state["memo2"]["html"] = self.memoFree.toHtml()
        self._save_all()

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

    # ----- Event / Window flags -----
    def eventFilter(self, obj, ev):
        if obj is self.topBar and ev.type() == QtCore.QEvent.MouseButtonDblClick:
            self._toggle_size_70(); return True
        return super().eventFilter(obj, ev)

    def _toggle_size_70(self):
        if self.isMaximized(): self.showNormal()
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
        self.actTrayOnTop.setCheckable(True); self.actTrayOnTop.setChecked(False)
        self.actTrayOnTop.toggled.connect(self._toggle_always_on_top)
        menu.addSeparator()
        act_quit = menu.addAction("終了")
        act_show.triggered.connect(self._bring_front); act_hide.triggered.connect(self.showMinimized)
        act_quit.triggered.connect(QtWidgets.QApplication.quit)
        self.tray.setContextMenu(menu); self.tray.setToolTip(APP_TITLE); self.tray.show()

    # ----- Always on Top -----
    def _toggle_always_on_top(self, on: bool):
        if hasattr(self, "actOnTop") and self.actOnTop.isChecked() != on:
            self.actOnTop.blockSignals(True); self.actOnTop.setChecked(on); self.actOnTop.blockSignals(False)
        if hasattr(self, "actTrayOnTop") and self.actTrayOnTop.isChecked() != on:
            self.actTrayOnTop.blockSignals(True); self.actTrayOnTop.setChecked(on); self.actTrayOnTop.blockSignals(False)
        self._apply_on_top(bool(on))

    def _apply_on_top(self, on: bool, first_time: bool = False):
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, on)
        self._force_standard_window_buttons()
        if self.isMinimized(): self.showNormal()
        else: self.show()
        self.raise_(); self.activateWindow()
        if first_time and hasattr(self, "actOnTop"):
            self.actOnTop.blockSignals(True); self.actOnTop.setChecked(False); self.actOnTop.blockSignals(False)

    def _force_standard_window_buttons(self):
        self.setWindowFlag(QtCore.Qt.Window, True)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowMinMaxButtonsHint, True)

    # ----- Geometry -----
    def _restore_geometry(self):
        geo = self.conf.get("geometry")
        avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        if geo:
            rect = QtCore.QRect(*geo)
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

    # ----- Common -----
    def _bring_front(self):
        self.showNormal(); self.raise_(); self.activateWindow()
    def _save_all(self):
        save_json(DATA_FILE, self.state)

# ---------- Entry ----------
def main():
    install_excepthook()
    app = QtWidgets.QApplication(sys.argv)

    # タスクトレイ用の簡易アイコン（生成）
    pm = QtGui.QPixmap(32, 32); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setBrush(QtGui.QBrush(QtGui.QColor("#4F8AF3"))); p.setPen(QtGui.QPen(QtGui.QColor("#2c5fb8"), 1))
    p.drawRoundedRect(1,1,30,30,6,6)
    p.setPen(QtGui.QPen(QtCore.Qt.white, 2)); p.drawText(QtCore.QRectF(0,0,32,32), QtCore.Qt.AlignCenter, "B")
    p.end()
    icon = QtGui.QIcon(pm)

    app.setApplicationName(APP_TITLE)
    w = MainWindow(icon); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
