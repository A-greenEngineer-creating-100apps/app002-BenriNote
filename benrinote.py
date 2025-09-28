# benrinote.py
# =========================================================
# 便利ノート（PySide6 / 単一ファイル）
# - ToDo：タイトル/詳細を分離、完了→アーカイブ、アーカイブ編集/削除（タブ）
# - 常駐事項：カテゴリ＝タブ、項目追加/改名/削除、D&Dで並べ替え
# - 左：ToDo/アーカイブ + 常駐（上下スプリッタで可変）
# - 右：詳細（選択中ToDo/常駐の本文を編集） & フリースペース
# - 画像：貼付・D&D・挿入はすべて base64 埋め込み（外部参照は保存時にも自動で埋め込み直し）
# - 背景色変更（各エディタ）
# - リスト行の区切り線（ToDo/常駐）
# - 「常に手前」トグル（起動時は必ずOFF）、トレイ常駐、×は常に押せる
# - ツールバーをダブルクリックで 70% サイズ↔前回サイズ
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

DEFAULT_STATE: Dict[str, Any] = {
    # ToDo: items: {id, title, done, html}
    "todo": {"items": [], "archive": []},  # archive: {id, title, html, archived_at}
    # 常駐： "カテゴリ名": {"items":[{"id","title","html"}]}
    "categories": {},
    "category_order": [],
    # フリースペース
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
    """QTextEdit.toHtml() から素のテキストを抽出。"""
    if not html: return ""
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.I | re.S)
    html = re.sub(r"<head\b[^>]*>.*?</head>", "", html, flags=re.I | re.S)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    txt = QtGui.QTextDocumentFragment.fromHtml(html).toPlainText()
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

# =========================================================
# リスト用：区切り線 delegate
# =========================================================
class SeparatorDelegate(QtWidgets.QStyledItemDelegate):
    """各行の下に1pxの区切り線を描く。"""
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex):
        super().paint(painter, option, index)
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        y = option.rect.bottom() - 1
        painter.drawLine(option.rect.left() + 6, y, option.rect.right() - 6, y)
        painter.restore()

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex):
        sz = super().sizeHint(option, index)
        return QtCore.QSize(sz.width(), max(sz.height(), 24))  # ちょい高めに

# =========================================================
# 画像：常に base64 埋め込み
# =========================================================
def _qimage_to_data_url(img: QtGui.QImage, fmt: str = "PNG") -> str:
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, fmt)
    ba = buf.data().toBase64().data().decode("ascii")
    mime = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{ba}"

def inline_external_images(html: str) -> str:
    """HTML内の <img src=...> で data: 以外をQImage読込→dataURLに差し替える。"""
    if not html:
        return html

    def replace_tag(m: re.Match) -> str:
        whole = m.group(0)
        before = m.group(1)
        src = m.group(2)
        after = m.group(3)
        # すでに data:
        if src.lower().startswith("data:"):
            return whole

        # file:/// または C:\... → ローカルファイル扱い
        path = None
        if src.lower().startswith("file:///"):
            path = QtCore.QUrl(src).toLocalFile()
        elif re.match(r"^[a-zA-Z]:[\\/]", src):
            path = src

        if path and os.path.exists(path):
            qimg = QtGui.QImage(path)
            if not qimg.isNull():
                dataurl = _qimage_to_data_url(qimg, "PNG")
                return f"<img{before}src=\"{dataurl}\"{after}>"
        return whole

    return re.sub(r'<img([^>]*?)\bsrc=["\']([^"\']+)["\']([^>]*)>',
                  replace_tag, html, flags=re.I)

class EmbedImageTextEdit(QtWidgets.QTextEdit):
    """貼り付け/ドロップ/HTML貼付の画像を必ず埋め込み(QImage→dataURL)にする。"""
    def canInsertFromMimeData(self, source: QtCore.QMimeData) -> bool:
        return source.hasImage() or source.hasUrls() or source.hasHtml() or source.hasText() or \
               super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QtCore.QMimeData):
        # 1) 直接の画像
        if source.hasImage():
            qimg = QtGui.QImage(source.imageData())
            if not qimg.isNull():
                self.textCursor().insertImage(qimg)
                return

        # 2) URL/ファイル
        if source.hasUrls():
            handled = False
            for url in source.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path.lower().endswith((".png",".jpg",".jpeg",".bmp",".gif",".webp")):
                        qimg = QtGui.QImage(path)
                        if not qimg.isNull():
                            self.textCursor().insertImage(qimg)
                            handled = True
                        continue
            if handled:
                return

        # 3) HTML片（<img src="file:///..."> や C:\... → 埋め込み）
        if source.hasHtml():
            html = source.html()
            def repl(m: re.Match) -> str:
                src = m.group(1)
                path = None
                if src.lower().startswith("file:///"):
                    path = QtCore.QUrl(src).toLocalFile()
                elif re.match(r"^[a-zA-Z]:[\\/]", src):
                    path = src
                if path and os.path.exists(path):
                    qimg = QtGui.QImage(path)
                    if not qimg.isNull():
                        self.textCursor().insertImage(qimg)  # ここで埋め込み
                        return ""  # 元タグは消す
                return m.group(0)
            html_wo_imgs = re.sub(r'<img[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', repl, html, flags=re.I)
            self.insertHtml(html_wo_imgs)
            return

        # 4) それ以外は通常処理
        super().insertFromMimeData(source)

# =========================================================
# リッチツールバー
# =========================================================
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

def make_icon_picture(size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 1)); p.setBrush(QtGui.QBrush(QtGui.QColor("#eaeefc")))
    p.drawRoundedRect(1,3,size-2,size-6,4,4)
    p.setBrush(QtGui.QBrush(QtGui.QColor("#b7d2ff")))
    points = [QtCore.QPointF(size*0.2,size*0.7), QtCore.QPointF(size*0.45,size*0.45), QtCore.QPointF(size*0.75,size*0.75)]
    p.drawPolygon(QtGui.QPolygonF(points))
    p.setBrush(QtGui.QBrush(QtGui.QColor("#ffd866"))); p.setPen(QtGui.QPen(QtGui.QColor(FG), 0))
    p.drawEllipse(QtCore.QRectF(size*0.58,size*0.22,size*0.16,size*0.16))
    p.end(); return QtGui.QIcon(pm)

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
        self.actColor.triggered.connect(self.pick_text_color); self.addAction(self.actColor)

        self.addSeparator()

        self._bg = QtGui.QColor(PANEL_BG)
        self.actBG = QtGui.QAction(make_icon_palette(self._bg), "背景色（エディタ）", self)
        self.actBG.triggered.connect(self.pick_bg_color); self.addAction(self.actBG)

        self.actPasteImg = QtGui.QAction(make_icon_picture(), "画像貼り付け（クリップボード）", self)
        self.actPasteImg.triggered.connect(self.paste_image_from_clipboard); self.addAction(self.actPasteImg)

        self.actInsertImg = QtGui.QAction(make_icon_picture(), "画像挿入（ファイル）", self)
        self.actInsertImg.triggered.connect(self.insert_image_from_file); self.addAction(self.actInsertImg)

    def toggle_underline(self, on: bool):
        fmt = QtGui.QTextCharFormat(); fmt.setFontUnderline(on); self._merge(fmt)

    def pick_text_color(self):
        col = QtWidgets.QColorDialog.getColor(self._color, self, "文字色を選択")
        if col.isValid():
            self._color = col; self.actColor.setIcon(make_icon_palette(self._color))
            fmt = QtGui.QTextCharFormat(); fmt.setForeground(QtGui.QBrush(col)); self._merge(fmt)

    def _merge(self, fmt: QtGui.QTextCharFormat):
        cur = self.target.textCursor()
        if cur.hasSelection(): cur.mergeCharFormat(fmt)
        else: self.target.mergeCurrentCharFormat(fmt)
        self.htmlChanged.emit()

    def pick_bg_color(self):
        col = QtWidgets.QColorDialog.getColor(self._bg, self, "背景色（エディタ）を選択")
        if not col.isValid(): return
        self._bg = col; self.actBG.setIcon(make_icon_palette(self._bg))
        self.target.setStyleSheet(
            f"QTextEdit{{background:{col.name()}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}"
        )

    def paste_image_from_clipboard(self):
        cb = QtWidgets.QApplication.clipboard()
        if img := cb.image():
            qimg = QtGui.QImage(img)
            if not qimg.isNull():
                self.target.textCursor().insertImage(qimg)
                self.htmlChanged.emit()
        else:
            QtWidgets.QMessageBox.information(self, "情報", "クリップボードに画像がありません。")

    def insert_image_from_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "画像を選択", "", "画像ファイル (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not path: return
        qimg = QtGui.QImage(path)
        if qimg.isNull():
            QtWidgets.QMessageBox.warning(self, "失敗", "画像を読み込めませんでした。"); return
        self.target.textCursor().insertImage(qimg)
        self.htmlChanged.emit()

    def resize_selected_image(self):
        """カーソル位置の画像（または直前の画像）の幅をpx指定で変更"""
        cur = self.target.textCursor()
        fmt = cur.charFormat()

        # 画像直後にカーソルがあるケース：直前の1文字をチェック
        if not fmt.isImageFormat():
            cur2 = QtGui.QTextCursor(cur)
            if cur2.position() > 0:
                cur2.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.MoveAnchor, 1)
                fmt2 = cur2.charFormat()
                if fmt2.isImageFormat():
                    cur = cur2
                    fmt = fmt2

        if not fmt.isImageFormat():
            QtWidgets.QMessageBox.information(self, "情報", "サイズ変更したい画像の上（または直後）にカーソルを置いてください。")
            return

        imgf: QtGui.QTextImageFormat = fmt.toImageFormat()
        current_w = int(imgf.width()) if imgf.width() > 0 else 400  # 幅未設定なら暫定400px
        new_w, ok = QtWidgets.QInputDialog.getInt(self, "画像の幅", "幅 (px)：", current_w, 48, 4000, 1)
        if not ok:
            return

        imgf.setWidth(float(new_w))  # 高さはアスペクト比に従って自動
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
    def add(self, text: str, html: str = None):
        self.beginInsertRows(QtCore.QModelIndex(), len(self.items), len(self.items))
        self.items.append({
            "id": str(uuid.uuid4()),
            "title": text,
            "done": False,
            "html": html or ""
        })
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QtGui.QIcon.fromTheme("sticky-notes"))
        self.prev_geometry: Optional[QtCore.QRect] = None

        self.state = load_json(DATA_FILE, DEFAULT_STATE)

        # ToDo: text→title への移行（古いデータ保護）
        changed = False
        for it in self.state["todo"]["items"]:
            if "title" not in it:
                it["title"] = it.get("text", ""); changed = True
        for it in self.state["todo"]["archive"]:
            if "title" not in it:
                it["title"] = it.get("text", ""); changed = True
        if changed:
            save_json(DATA_FILE, self.state)

        self._migrate_categories_to_items()
        self.conf  = load_json(CONF_FILE, {"geometry": None})

        # ★ 詳細参照（どのアイテムを編集しているか）
        self._detail_ref: Optional[Tuple] = None

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

        self.actOnTop = QtGui.QAction("常に手前に表示", self, checkable=True, checked=False)
        self.actOnTop.toggled.connect(self._toggle_always_on_top)
        btnOnTop = QtWidgets.QToolButton(); btnOnTop.setDefaultAction(self.actOnTop); btnOnTop.setCheckable(True)
        self.topBar.addWidget(btnOnTop)
        self.topBar.installEventFilter(self)

        # ===== 右：詳細 & フリースペース =====
        self.detailEditor = EmbedImageTextEdit()
        self.detailEditor.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")
        self.detailBar = RichBar(self.detailEditor)
        self.detailLabel = QtWidgets.QLabel("詳細"); self.detailLabel.setStyleSheet("font-weight:bold; color:%s;" % FG)
        # 画像サイズ変更（詳細）
        btnResizeImgDetail = QtWidgets.QPushButton("画像サイズ変更")
        btnResizeImgDetail.clicked.connect(self.detailBar.resize_selected_image)

        self._detailTimer = QtCore.QTimer(self); self._detailTimer.setSingleShot(True); self._detailTimer.setInterval(400)
        self.detailEditor.textChanged.connect(lambda: self._detailTimer.start())
        self._detailTimer.timeout.connect(self._apply_detail_to_state)

        detailPane = QtWidgets.QWidget(); v1 = QtWidgets.QVBoxLayout(detailPane)
        v1.setContentsMargins(10,10,5,10); v1.setSpacing(6)
        v1.addWidget(self.detailLabel)
        v1.addWidget(self.detailBar)
        v1.addWidget(btnResizeImgDetail, alignment=QtCore.Qt.AlignLeft)
        v1.addWidget(self.detailEditor, 1)

        self.memoFree = EmbedImageTextEdit()
        self.memoFree.setHtml(self.state["memo2"]["html"])
        self.memoFree.textChanged.connect(self._on_free_html_changed)
        self.memoFree.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")
        self.memoFreeBar = RichBar(self.memoFree)
        labFree = QtWidgets.QLabel("フリースペース"); labFree.setStyleSheet("font-weight:bold; color:%s;" % FG)
        # 画像サイズ変更（フリースペース）
        btnResizeImgFree = QtWidgets.QPushButton("画像サイズ変更")
        btnResizeImgFree.clicked.connect(self.memoFreeBar.resize_selected_image)

        freePane = QtWidgets.QWidget(); v2 = QtWidgets.QVBoxLayout(freePane)
        v2.setContentsMargins(5,10,10,10); v2.setSpacing(6)
        v2.addWidget(labFree)
        v2.addWidget(self.memoFreeBar)
        v2.addWidget(btnResizeImgFree, alignment=QtCore.Qt.AlignLeft)
        v2.addWidget(self.memoFree, 1)

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

        # ===== 左：常駐カテゴリ =====
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

        # ===== 左の上下スプリッタ =====
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

        # 起動時は必ず OnTop OFF
        self._force_standard_window_buttons()
        self._apply_on_top(False, first_time=True)

        self._restore_geometry()
        self._setup_tray()

        # 定期保存
        self.saveTimer = QtCore.QTimer(self); self.saveTimer.setInterval(2000)
        self.saveTimer.timeout.connect(self._save_all); self.saveTimer.start()

        # 詳細初期状態 + 初期選択
        self._load_detail(None)
        if self.todoModel.rowCount() > 0:
            self.todoList.setCurrentIndex(self.todoModel.index(0))
            self._load_detail(("todo", 0))

    # ====== 常駐カテゴリ：データ移行 ======
    def _migrate_categories_to_items(self):
        changed = False
        cats = self.state.get("categories", {})
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
                    it.setdefault("id", str(uuid.uuid4()))
                    it.setdefault("title", "無題")
                    it.setdefault("html", "")
        if changed:
            save_json(DATA_FILE, self.state)

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

        # 初期選択（1件でも確実に詳細が出る）
        if lst.count() > 0:
            lst.setCurrentRow(0)
            self._on_resident_selected(cat_name, 0)

        return wrap

    # --- 項目操作 ---
    def _add_resident_item(self, cat_name: str, list_widget: QtWidgets.QListWidget):
        title, ok = QtWidgets.QInputDialog.getText(self, "項目の追加", "項目名：")
        if not ok or not title.strip(): return
        title = title.strip()
        item = {"id": str(uuid.uuid4()), "title": title, "html": ""}
        self.state["categories"][cat_name]["items"].append(item)
        list_widget.addItem(title)
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
        title_to_list: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            title_to_list.setdefault(it["title"], []).append(it)
        new_items: List[Dict[str, Any]] = []
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
                title = it.get("title", "")
                self.detailLabel.setText(f"詳細（ToDo / {title}）")
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
        if not self._detail_ref:
            return
        # ★ 保存直前に外部参照を dataURL に置換
        html = inline_external_images(self.detailEditor.toHtml())
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
        new_order = [self.residentTabs.tabText(i) for i in range(self.residentTabs.count())]
        self.state["category_order"] = new_order
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
        self.actTrayOnTop.setCheckable(True)
        self.actTrayOnTop.setChecked(False)
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

    # ----- ToDo -----
    def _add_todo(self):
        text = self.todoInput.text().strip()
        if not text: return
        self.todoModel.add(text); self.todoInput.clear(); self._save_all()
        # 追加直後に選択 & 詳細へ
        row = self.todoModel.rowCount() - 1
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
            self.todoModel.remove(row); self._save_all()
            self._load_detail(None)

    def _rename_selected_todo(self):
        row = self._selected_row()
        if row < 0: return
        cur = self.state["todo"]["items"][row].get("title","")
        new, ok = QtWidgets.QInputDialog.getText(self, "タイトル変更", "新しいタイトル：", text=cur)
        if not ok: return
        new = new.strip()
        if not new: return
        self.state["todo"]["items"][row]["title"] = new
        self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
        if self._detail_ref and self._detail_ref[0] == "todo" and self._detail_ref[1] == row:
            self.detailLabel.setText(f"詳細（ToDo / {new}）")
        self._save_all()

    def _edit_archive_item(self, item: QtWidgets.QListWidgetItem):
        # アーカイブはタイトル/本文の編集（ダイアログ）
        row = self.archiveList.row(item)
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        target = sorted_arc[row]
        # タイトル
        new_title, ok = QtWidgets.QInputDialog.getText(self, "アーカイブのタイトル", "タイトル：", text=target.get("title",""))
        if not ok: return
        # 本文（簡易）
        dlg = QtWidgets.QInputDialog(self); dlg.setWindowTitle("アーカイブの本文（プレーンテキスト）")
        dlg.setLabelText("本文：")
        dlg.setTextValue(html_to_plain(target.get("html","")))
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            body_plain = dlg.textValue()
            body_html = plain_to_html(body_plain)
            for it in self.state["todo"]["archive"]:
                if it["id"] == target["id"]:
                    it["title"] = new_title
                    it["html"] = body_html
                    break
            self._refresh_archive_list(); self._save_all()

    def _archive_done(self):
        done = [it for it in self.state["todo"]["items"] if it.get("done")]
        if not done:
            QtWidgets.QMessageBox.information(self, "情報", "完了済みのToDoがありません。"); return
        now = int(time.time())
        for it in done:
            self.state["todo"]["archive"].append({
                "id": it["id"], "title": it.get("title",""), "archived_at": now,
                "html": it.get("html", "")
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

    def _refresh_archive_list(self):
        self.archiveList.clear()
        for it in sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True):
            ts = QtCore.QDateTime.fromSecsSinceEpoch(it.get("archived_at", 0)).toString("yyyy-MM-dd HH:mm")
            self.archiveList.addItem(f"{ts}  -  {it.get('title','')}")

    # ----- フリースペース -----
    def _on_free_html_changed(self):
        # 保存直前に外部参照を dataURL に置換
        self.state["memo2"]["html"] = inline_external_images(self.memoFree.toHtml())
        self._save_all()

    # ----- 共通 -----
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
