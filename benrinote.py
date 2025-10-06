from __future__ import annotations
import json, os, sys, uuid, time, re, traceback
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

APP_TITLE = "めもめも"

# 保存先（Winなら %LOCALAPPDATA%\BenriNote）
DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "BenriNote"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / "notes.json"
CONF_FILE = DATA_DIR / "window.json"
LOG_FILE = DATA_DIR / "error.log"

# ===== Theme =====
ACCENT, ACCENT_HOVER, ACCENT_WEAK = "#4F8AF3", "#6BA0F6", "#E6E6FF"
FG, BG, PANEL_BG = "#222222", "#FAFAFB", "#FFFFFF"
BORDER, HANDLE = "#E6E6EA", "#EAEAEA"

# ---------- JSON ----------
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

# ---------- 例外ハンドラ ----------
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
# ユーティリティ
# =========================================================
def plain_to_html(text: str) -> str:
    import html
    if text is None: text = ""
    return f"<p>{html.escape(text).replace('\\n', '<br>')}</p>"

def html_to_plain(html: str) -> str:
    if not html: return ""
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.I | re.S)
    html = re.sub(r"<head\b[^>]*>.*?</head>", "", html, flags=re.I | re.S)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    txt = QtGui.QTextDocumentFragment.fromHtml(html).toPlainText()
    return txt.strip()

# =========================================================
# 画像埋め込み / 区切り線 / リンク対応テキストエディタ
# =========================================================
def _qimage_to_data_url(img: QtGui.QImage, fmt: str = "PNG") -> str:
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, fmt)
    ba = buf.data().toBase64().data().decode("ascii")
    mime = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{ba}"

def _qimage_to_html_tag(img: QtGui.QImage) -> str:
    return f'<img src="{_qimage_to_data_url(img)}" alt="image" />'

def inline_external_images(html: str) -> str:
    if not html: return html
    def replace_tag(m: re.Match) -> str:
        whole, before, src, after = m.group(0), m.group(1), m.group(2), m.group(3)
        if src.lower().startswith("data:"): return whole
        path = None
        if src.lower().startswith("file:///"):
            path = QtCore.QUrl(src).toLocalFile()
        elif re.match(r"^[a-zA-Z]:[\\/]", src):
            path = src
        if path and os.path.exists(path):
            qimg = QtGui.QImage(path)
            if not qimg.isNull():
                return f"<img{before}src=\"{_qimage_to_data_url(qimg,'PNG')}\"{after}>"
        return whole
    return re.sub(r'<img([^>]*?)\bsrc=["\']([^"\']+)["\']([^>]*)>', replace_tag, html, flags=re.I)

class SeparatorDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex):
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

class EmbedImageTextEdit(QtWidgets.QTextEdit):
    def canInsertFromMimeData(self, source: QtCore.QMimeData) -> bool:
        return source.hasImage() or source.hasUrls() or source.hasHtml() or source.hasText() or \
                super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QtCore.QMimeData):
        if source.hasImage():
            qimg = QtGui.QImage(source.imageData())
            if not qimg.isNull():
                self.textCursor().insertHtml(_qimage_to_html_tag(qimg)); return
        if source.hasUrls():
            handled = False
            for url in source.urls():
                if url.isLocalFile():
                    path = url.toLocalFile().lower()
                    if path.endswith((".png",".jpg",".jpeg",".bmp",".gif",".webp")):
                        qimg = QtGui.QImage(url.toLocalFile())
                        if not qimg.isNull():
                            self.textCursor().insertHtml(_qimage_to_html_tag(qimg)); handled = True
            if handled: return
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
                        self.textCursor().insertHtml(_qimage_to_html_tag(qimg)); return ""
                return m.group(0)
            html_wo_imgs = re.sub(r'<img[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', repl, html, flags=re.I)
            self.insertHtml(html_wo_imgs); return
        super().insertFromMimeData(source)

    # ▼ リンク挿入（青下線）＆クリックで開く
    def insert_link(self, href: Optional[str] = None, text: Optional[str] = None):
        if href is None:
            menu = QtWidgets.QMenu(self)
            act_url = menu.addAction("URLを入力して挿入")
            act_file = menu.addAction("ファイルを選んで挿入")
            picked = menu.exec(QtGui.QCursor.pos())
            if not picked: return
            if picked is act_url:
                href, ok = QtWidgets.QInputDialog.getText(self, "リンクのURL", "URL（http(s):// / file:/// / C:\\...）：")
                if not ok or not href.strip(): return
                href = href.strip()
            else:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "リンクするファイルを選択", "", "すべてのファイル (*.*)")
                if not path: return
                href = QtCore.QUrl.fromLocalFile(path).toString()

        if text is None or not text.strip():
            text, ok = QtWidgets.QInputDialog.getText(self, "リンクの表示文字", "表示文字：", text=href)
            if not ok: return
            text = text.strip() or href

        html = f'<a href="{href}"><span style="color:#1155cc;text-decoration:underline;">{text}</span></a>'
        self.textCursor().insertHtml(html)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        anchor = self.anchorAt(e.pos())
        if anchor:
            if re.match(r"^[a-zA-Z]:[\\/]", anchor):
                url = QtCore.QUrl.fromLocalFile(anchor)
            else:
                url = QtCore.QUrl(anchor)
                if not url.scheme():
                    url = QtCore.QUrl.fromLocalFile(anchor)
            QtGui.QDesktopServices.openUrl(url); e.accept(); return
        super().mouseReleaseEvent(e)

def make_icon_A_underline(size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    font = QtGui.QFont("Segoe UI"); font.setBold(True); font.setPointSizeF(size * 0.65)
    p.setFont(font); p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
    rect = QtCore.QRectF(0, -2, size, size); p.drawText(rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, "A")
    p.setPen(QtGui.QPen(QtGui.QColor(FG), 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
    y = int(size * 0.82); p.drawLine(int(size*0.18), y, int(size*0.82), y)
    p.end(); return QtGui.QIcon(pm)

def make_icon_palette(color: QtGui.QColor, size=18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    path = QtGui.QPainterPath(); r = size - 2
    path.addRoundedRect(QtCore.QRectF(1, 2, r, r-2), size*0.3, size*0.3)
    hole = QtGui.QPainterPath(); hole.addEllipse(QtCore.QRectF(size*0.45, size*0.55, size*0.28, size*0.28))
    shape = path.subtracted(hole)
    p.fillPath(shape, QtGui.QBrush(QtGui.QColor(245,245,245))); p.setPen(QtGui.QPen(QtGui.QColor(FG), 1)); p.drawPath(shape)
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
    bgColorChanged = QtCore.Signal(QtGui.QColor)  # 背景色変更を通知（永続化用）

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

        self.addSeparator()
        self.actInsertLink = QtGui.QAction("リンク挿入", self)
        self.actInsertLink.setToolTip("URLやファイルへのリンクを挿入")
        self.actInsertLink.triggered.connect(self._insert_link)
        self.addAction(self.actInsertLink)

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
        self.bgColorChanged.emit(col)

    def paste_image_from_clipboard(self):
        cb = QtWidgets.QApplication.clipboard()
        if img := cb.image():
            qimg = QtGui.QImage(img)
            if not qimg.isNull():
                self.target.textCursor().insertHtml(_qimage_to_html_tag(qimg)); self.htmlChanged.emit()
        else:
            QtWidgets.QMessageBox.information(self, "情報", "クリップボードに画像がありません。")

    def insert_image_from_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "画像を選択", "", "画像ファイル (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not path: return
        qimg = QtGui.QImage(path)
        if qimg.isNull():
            QtWidgets.QMessageBox.warning(self, "失敗", "画像を読み込めませんでした。"); return
        self.target.textCursor().insertHtml(_qimage_to_html_tag(qimg)); self.htmlChanged.emit()

    def resize_selected_image(self):
        cur = self.target.textCursor()
        fmt = cur.charFormat()
        if not fmt.isImageFormat():
            cur2 = QtGui.QTextCursor(cur)
            if cur2.position() > 0:
                cur2.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.MoveAnchor, 1)
                fmt2 = cur2.charFormat()
                if fmt2.isImageFormat():
                    cur = cur2; fmt = fmt2
        if not fmt.isImageFormat():
            QtWidgets.QMessageBox.information(self, "情報", "サイズ変更したい画像の上（または直後）にカーソルを置いてください。")
            return
        imgf: QtGui.QTextImageFormat = fmt.toImageFormat()
        current_w = int(imgf.width()) if imgf.width() > 0 else 400
        new_w, ok = QtWidgets.QInputDialog.getInt(self, "画像の幅", "幅 (px)：", current_w, 48, 4000, 1)
        if not ok: return
        imgf.setWidth(float(new_w))
        cur.mergeCharFormat(imgf)
        self.htmlChanged.emit()

    def _insert_link(self):
        if hasattr(self.target, "insert_link"): self.target.insert_link()
        else:
            href, ok = QtWidgets.QInputDialog.getText(self, "リンクのURL", "URL：")
            if not ok or not href.strip(): return
            text, ok = QtWidgets.QInputDialog.getText(self, "リンクの表示文字", "表示文字：", text=href)
            if not ok: return
            html = f'<a href="{href}"><span style="color:#1155cc;text-decoration:underline;">{text}</span></a>'
            self.target.textCursor().insertHtml(html)

# =========================================================
# 常駐事項リスト（ドラッグ&ドロップ後のデータ同期用）
# =========================================================
class ResidentListWidget(QtWidgets.QListWidget):
    """
    常駐事項の項目リスト。
    項目のドラッグ＆ドロップ移動が完了した後、親ウィジェットのデータ順序を同期するために dropEvent をオーバーライドする。
    """
    # 📌 修正箇所: **kwargs を追加し、super().__init__ に渡す
    def __init__(self, cat_name: str, main_window: 'MainWindow', parent=None, **kwargs):
        super().__init__(parent, **kwargs) # **kwargs を親クラスに渡す
        self.cat_name = cat_name
        self.main_window = main_window
        self._select_callback = None
        self._update_order_callback = None
        
        # QListWidgetの設定
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

    def set_callbacks(self, select_callback, update_order_callback):
        self._select_callback = select_callback
        self._update_order_callback = update_order_callback
        
        # 通常の選択シグナルをカスタムクラス内で接続
        self.currentRowChanged.connect(lambda row: self._select_callback(self.cat_name, row))
        self.itemClicked.connect(lambda _it: self._select_callback(self.cat_name, self.currentRow()))

    def dropEvent(self, event: QtGui.QDropEvent):
        """アイテムのドロップが完了した際に、基底クラスの処理の後にデータ順序を更新する。"""
        # 🌟 重要: ドロップ前に現在の詳細エディタの内容を保存しておく
        self.main_window._apply_detail_to_state()
        
        # 基底クラスの dropEvent を呼び出し、アイテムの移動を完了させる
        super().dropEvent(event)
        
        # データ側のリストの順序を、UIの現在の順序に合わせて更新
        if self._update_order_callback:
            # 外部 (MainWindow) のメソッドを呼び出してデータ構造を更新する
            self._update_order_callback(self.cat_name, self)
        
        event.accept()

# =========================================================
# ToDoモデル（編集・色付き対応版）
# =========================================================
class TodoModel(QtCore.QAbstractListModel):
    def __init__(self, items: List[Dict[str, Any]]):
        super().__init__(); self.items = items

    def rowCount(self, parent=QtCore.QModelIndex()): 
        return len(self.items)

    def data(self, index, role):
        if not index.isValid(): return None
        it = self.items[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return it.get("title","")
        if role == QtCore.Qt.FontRole and it.get("done"):
            f = QtGui.QFont(); f.setStrikeOut(True); return f
        if role == QtCore.Qt.BackgroundRole:
            col = it.get("color")
            if col: return QtGui.QBrush(QtGui.QColor(col))
        return None

    def add(self, text: str, html: str = None):
        self.beginInsertRows(QtCore.QModelIndex(), len(self.items), len(self.items))
        self.items.append({
            "id": str(uuid.uuid4()),
            "title": text,
            "done": False,
            "html": html or "",
            "color": None,
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

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.ItemIsEnabled
        return (QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)

    def setData(self, index, value, role):
        if not index.isValid():
            return False
        if role == QtCore.Qt.EditRole:
            text = str(value).strip()
            self.items[index.row()]["title"] = text
            self.dataChanged.emit(index, index)
            return True
        return False

# =========================================================
# デフォルト状態
# =========================================================
DEFAULT_STATE: Dict[str, Any] = {
    "todo": {"items": [], "archive": []},
    "categories": {},
    "category_order": [],
    "memo2": {"html": ""},
}

# =========================================================
# MainWindow（UI構築〜起動直後セットアップ）
# =========================================================
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QtGui.QIcon.fromTheme("sticky-notes"))
        self.prev_geometry: Optional[QtCore.QRect] = None
        self._detail_ref_uuid: Optional[str] = None # 📌 追加: 常駐事項の選択UUIDを保持

        self.state = load_json(DATA_FILE, DEFAULT_STATE)
        self.conf = load_json(CONF_FILE, {"geometry": None})

        # 旧データのtitle移行 & 常駐構造の整備
        changed = False
        for it in self.state["todo"]["items"]:
            if "title" not in it: it["title"] = it.get("text",""); changed = True
        for it in self.state["todo"]["archive"]:
            if "title" not in it: it["title"] = it.get("text",""); changed = True
        for name, cat in list(self.state["categories"].items()):
            cat.setdefault("items", []); cat.setdefault("archive", [])
            # 既存の項目にUUIDがない場合は付与（バグ修正対応）
            for item in cat["items"]:
                item.setdefault("id", str(uuid.uuid4())); changed = True
        if changed: save_json(DATA_FILE, self.state)

        self._apply_global_style()

        # ===== Top Toolbar =====
        self.topBar = QtWidgets.QToolBar()
        self.topBar.setMovable(False); self.topBar.setIconSize(QtCore.QSize(18,18))
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
        self.topBar.addWidget(btnOnTop); self.topBar.installEventFilter(self)

        # ===== 右：詳細 & フリースペース =====
        # 詳細欄
        self.detailEditor = EmbedImageTextEdit()
        self.detailEditor.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")
        self.detailBar = RichBar(self.detailEditor)
        self.detailLabel = QtWidgets.QLabel("詳細"); self.detailLabel.setStyleSheet(f"font-weight:bold; color:{FG};")
        btnResizeImgDetail = QtWidgets.QPushButton("画像サイズ変更")
        btnResizeImgDetail.clicked.connect(self.detailBar.resize_selected_image)

        # ▼ 詳細欄の背景色 永続化（CONF_FILE: editor_bg.detail）
        bg_conf = self.conf.get("editor_bg", {})
        detail_bg = bg_conf.get("detail")
        if detail_bg:
            self.detailEditor.setStyleSheet(
                f"QTextEdit{{background:{detail_bg}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}"
            )
        self.detailBar.bgColorChanged.connect(lambda col: self._save_editor_bg("detail", col))

        self._detailTimer = QtCore.QTimer(self); self._detailTimer.setSingleShot(True); self._detailTimer.setInterval(400)
        self.detailEditor.textChanged.connect(lambda: self._detailTimer.start())
        self._detailTimer.timeout.connect(self._apply_detail_to_state)

        detailPane = QtWidgets.QWidget(); v1 = QtWidgets.QVBoxLayout(detailPane)
        v1.setContentsMargins(10,10,5,10); v1.setSpacing(6)
        v1.addWidget(self.detailLabel); v1.addWidget(self.detailBar)
        v1.addWidget(btnResizeImgDetail, alignment=QtCore.Qt.AlignLeft)
        v1.addWidget(self.detailEditor, 1)

        # フリースペース
        self.memoFree = EmbedImageTextEdit()
        self.memoFree.setHtml(self.state["memo2"]["html"])
        self.memoFree.textChanged.connect(self._on_free_html_changed)
        self.memoFree.setStyleSheet(f"QTextEdit{{background:{PANEL_BG}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}")
        self.memoFreeBar = RichBar(self.memoFree)
        labFree = QtWidgets.QLabel("フリースペース"); labFree.setStyleSheet(f"font-weight:bold; color:{FG};")
        btnResizeImgFree = QtWidgets.QPushButton("画像サイズ変更"); btnResizeImgFree.clicked.connect(self.memoFreeBar.resize_selected_image)

        # ▼ メモ欄の背景色 永続化（CONF_FILE: editor_bg.memo2）
        memo_bg = bg_conf.get("memo2")
        if memo_bg:
            self.memoFree.setStyleSheet(
                f"QTextEdit{{background:{memo_bg}; padding:6px; border:1px solid {BORDER}; border-radius:8px;}}"
            )
        self.memoFreeBar.bgColorChanged.connect(lambda col: self._save_editor_bg("memo2", col))

        freePane = QtWidgets.QWidget(); v2 = QtWidgets.QVBoxLayout(freePane)
        v2.setContentsMargins(5,10,10,10); v2.setSpacing(6)
        v2.addWidget(labFree); v2.addWidget(self.memoFreeBar)
        v2.addWidget(btnResizeImgFree, alignment=QtCore.Qt.AlignLeft)
        v2.addWidget(self.memoFree, 1)

        rightSplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        rightSplitter.addWidget(detailPane); rightSplitter.addWidget(freePane)
        rightSplitter.setStretchFactor(0, 1); rightSplitter.setStretchFactor(1, 1)
        rightSplitter.setChildrenCollapsible(False); rightSplitter.setHandleWidth(10)
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
        self.todoList = QtWidgets.QListView(); self.todoList.setModel(self.todoModel)
        self.todoList.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.todoList.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.todoList.setItemDelegate(SeparatorDelegate(self.todoList))
        self.todoList.selectionModel().currentChanged.connect(self._on_todo_selected)
        self.todoList.clicked.connect(lambda idx: self._load_detail(("todo", idx.row())))

        self.todoInput = QtWidgets.QLineEdit(); self.todoInput.setPlaceholderText("ToDo を入力して Enter")
        self.todoInput.returnPressed.connect(self._add_todo)

        btnTgl = QtWidgets.QPushButton("完了/未完了")
        btnDel = QtWidgets.QPushButton("選択削除")
        btnArc = QtWidgets.QPushButton("完了→アーカイブ")
        btnRen = QtWidgets.QPushButton("タイトル変更")
        btnColor = QtWidgets.QPushButton("色")

        btnTgl.clicked.connect(self._toggle_selected_todo)
        btnDel.clicked.connect(self._del_selected_todo)
        btnArc.clicked.connect(self._archive_done)
        btnRen.clicked.connect(self._rename_selected_todo)  # ← ボタン版も有効
        btnColor.clicked.connect(self._pick_color_for_selected_todo)

        todoPane = QtWidgets.QWidget(); vct = QtWidgets.QVBoxLayout(todoPane)
        vct.setContentsMargins(8,8,8,8)
        vct.addWidget(self.todoList); vct.addWidget(self.todoInput)
        hb2 = QtWidgets.QHBoxLayout()
        hb2.addWidget(btnTgl); hb2.addWidget(btnArc); hb2.addWidget(btnRen)
        hb2.addWidget(btnDel); hb2.addWidget(btnColor)
        vct.addLayout(hb2)

        self.archiveList = QtWidgets.QListWidget(); self._refresh_todo_archive_list()
        self.archiveList.setItemDelegate(SeparatorDelegate(self.archiveList))
        self.archiveList.itemDoubleClicked.connect(self._edit_archive_item)
        self.archiveList.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.archiveList.customContextMenuRequested.connect(self._show_archive_context_menu)

        btnArcDel = QtWidgets.QPushButton("選択アーカイブ削除")
        btnArcDel.clicked.connect(self._delete_selected_todo_archive)
        arcPane = QtWidgets.QWidget(); varc = QtWidgets.QVBoxLayout(arcPane)
        varc.setContentsMargins(8,8,8,8); varc.addWidget(self.archiveList)
        varc.addWidget(btnArcDel, alignment=QtCore.Qt.AlignRight)

        self.centerTabs = QtWidgets.QTabWidget()
        self.centerTabs.addTab(todoPane, "ToDo")
        self.centerTabs.addTab(arcPane, "ToDoアーカイブ")

        # ===== 左：常駐カテゴリ（タブ） =====
        self.residentTabs = QtWidgets.QTabWidget()
        self.residentTabs.setTabsClosable(False)
        self.residentTabs.tabBar().setMovable(True)
        self.residentTabs.tabBar().installEventFilter(self)

        btnAddCat = QtWidgets.QToolButton(); btnAddCat.setText("＋"); btnAddCat.clicked.connect(self._add_resident_tab)
        btnRenCat = QtWidgets.QToolButton(); btnRenCat.setText("改"); btnRenCat.clicked.connect(self._rename_resident_tab)
        btnDelCat = QtWidgets.QToolButton(); btnDelCat.setText("削"); btnDelCat.clicked.connect(self._delete_resident_tab)

        leftBottom = QtWidgets.QWidget()
        vlb = QtWidgets.QVBoxLayout(leftBottom); vlb.setContentsMargins(8,0,8,8)
        titleCat = QtWidgets.QLabel("常駐事項"); titleCat.setStyleSheet(f"font-weight: bold; color: {FG};")
        toolRow = QtWidgets.QHBoxLayout(); toolRow.addWidget(titleCat); toolRow.addStretch(1)
        toolRow.addWidget(btnAddCat); toolRow.addWidget(btnRenCat); toolRow.addWidget(btnDelCat)
        vlb.addLayout(toolRow); vlb.addWidget(self.residentTabs)

        self._rebuild_resident_tabs()

        # ===== 左の上下スプリッタ =====
        leftSplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        leftSplit.addWidget(self.centerTabs); leftSplit.addWidget(leftBottom)
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

        # ウィンドウ復元
        self._restore_geometry()

        # トレイ
        self._setup_tray()

        # 定期保存
        self.saveTimer = QtCore.QTimer(self); self.saveTimer.setInterval(2000)
        self.saveTimer.timeout.connect(self._save_all); self.saveTimer.start()

        # 詳細初期状態 + 初期選択
        self._load_detail(None)
        if self.todoModel.rowCount() > 0:
            self.todoList.setCurrentIndex(self.todoModel.index(0))
            self._load_detail(("todo", 0))

        # ▼ 最終状態の保存トリガ
        self.centerTabs.currentChanged.connect(self._save_last_state)
        self.todoList.selectionModel().currentChanged.connect(lambda *_: self._save_last_state())
        self.residentTabs.currentChanged.connect(lambda *_: self._save_last_state())

        # ▼ 起動時に前回ページ復元
        self._restore_last_state()
    # ====== 常駐カテゴリ：データ移行（後方互換） ======
    def _migrate_categories_to_items(self):
        changed = False
        cats = self.state.get("categories", {})
        for name, val in list(cats.items()):
            if isinstance(val, dict) and "items" not in val:
                html = val.get("html", "")
                cats[name] = {"items": [], "archive": []}
                if html:
                    cats[name]["items"].append({"id": str(uuid.uuid4()), "title": "メモ", "html": html})
                changed = True
            else:
                items = cats[name].get("items", [])
                for it in items:
                    it.setdefault("id", str(uuid.uuid4()))
                    it.setdefault("title", "無題")
                    it.setdefault("html", "")
                cats[name].setdefault("archive", [])
        if changed:
            save_json(DATA_FILE, self.state)

    # ====== 常駐カテゴリ UI ======
    def _rebuild_resident_tabs(self):
        self.residentTabs.blockSignals(True)
        current_text = self.residentTabs.tabText(self.residentTabs.currentIndex()) if self.residentTabs.count() else None

        self.residentTabs.clear()
        order = list(self.state.get("category_order", []))
        for k in self.state["categories"].keys():
            if k not in order: order.append(k)
        self.state["category_order"] = order

        new_index = 0
        for name in order:
            self.residentTabs.addTab(self._build_category_widget(name), name)
            if name == current_text:
                new_index = self.residentTabs.count() - 1

        if order:
            self.residentTabs.addTab(self._build_resident_archive_widget(), "アーカイブ")

        # タブの移動シグナルを再接続
        try:
             self.residentTabs.tabBar().tabMoved.disconnect()
        except TypeError:
             pass
        self.residentTabs.tabBar().tabMoved.connect(self._on_resident_tab_moved)

        if current_text == "アーカイブ":
            self.residentTabs.setCurrentIndex(self.residentTabs.count() - 1)
        elif new_index < self.residentTabs.count():
            self.residentTabs.setCurrentIndex(new_index)
        self.residentTabs.blockSignals(False)

    def _build_category_widget(self, cat_name: str) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap); v.setContentsMargins(6,6,6,6); v.setSpacing(6)

        lst = ResidentListWidget(cat_name, self, objectName=f"list_{cat_name}") 
        lst.setStyleSheet(f"QListWidget{{background:{PANEL_BG}; border:1px solid {BORDER}; border-radius:8px;}}")
        lst.setItemDelegate(SeparatorDelegate(lst))

        lst.set_callbacks(self._on_resident_selected, self._update_resident_items_order_from_list) 

        # ▼ UUIDを QListWidgetItem に埋める（順序安定）
        for it in self.state["categories"].get(cat_name, {}).get("items", []):
            itemw = QtWidgets.QListWidgetItem(it.get("title", "無題"))
            itemw.setData(QtCore.Qt.UserRole, it.get("id"))
            lst.addItem(itemw)

        hb = QtWidgets.QHBoxLayout()
        btnAdd = QtWidgets.QPushButton("項目追加")
        btnRen = QtWidgets.QPushButton("項目名変更")
        btnArcItem = QtWidgets.QPushButton("項目アーカイブ")
        btnDel = QtWidgets.QPushButton("項目削除")
        hb.addWidget(btnAdd); hb.addWidget(btnRen); hb.addWidget(btnArcItem); hb.addWidget(btnDel); hb.addStretch(1)

        btnAdd.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._add_resident_item(cn, w))
        btnRen.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._rename_resident_item(cn, w))
        btnArcItem.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._archive_resident_item(cn, w))
        btnDel.clicked.connect(lambda _=None, cn=cat_name, w=lst: self._delete_resident_item(cn, w))

        v.addWidget(lst, 1); v.addLayout(hb)

        # 🌟 修正: 選択状態の復元（前回選択していたUUIDに基づいて）
        initial_row = -1
        if self._detail_ref_uuid:
            for i in range(lst.count()):
                if lst.item(i).data(QtCore.Qt.UserRole) == self._detail_ref_uuid:
                    initial_row = i; break
        
        if initial_row >= 0:
            lst.setCurrentRow(initial_row)
            # 選択されたら _on_resident_selected が呼ばれるので、ここでは手動で呼ばない
        elif lst.count() > 0:
            lst.setCurrentRow(0)
            # 選択されたら _on_resident_selected が呼ばれるので、ここでは手動で呼ばない
        else:
            self._on_resident_selected(cat_name, -1) # 項目がない場合は詳細をクリア
        
        return wrap

    def _build_resident_archive_widget(self) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap); v.setContentsMargins(8,8,8,8)

        self.residentArchiveList = QtWidgets.QListWidget(objectName="list_resident_archive")
        self.residentArchiveList.setStyleSheet(f"QListWidget{{background:{PANEL_BG}; border:1px solid {BORDER}; border-radius:8px;}}")
        self.residentArchiveList.setItemDelegate(SeparatorDelegate(self.residentArchiveList))
        self.residentArchiveList.itemDoubleClicked.connect(self._edit_resident_archive_item)

        self._refresh_resident_archive_list()

        hb = QtWidgets.QHBoxLayout()
        btnRestore = QtWidgets.QPushButton("選択復元（元カテゴリへ）")
        btnDel = QtWidgets.QPushButton("選択削除")
        hb.addWidget(btnRestore); hb.addWidget(btnDel)

        btnRestore.clicked.connect(self._restore_resident_archive_item)
        btnDel.clicked.connect(self._delete_resident_archive_item)

        v.addWidget(self.residentArchiveList, 1); v.addLayout(hb)
        return wrap

    # --- 常駐：項目操作 ---
    def _add_resident_item(self, cat_name: str, list_widget: ResidentListWidget):
        title, ok = QtWidgets.QInputDialog.getText(self, "項目の追加", "項目名：")
        if not ok or not title.strip(): return
        title = title.strip()
        new_uuid = str(uuid.uuid4())
        item = {"id": new_uuid, "title": title, "html": ""}
        self.state["categories"][cat_name]["items"].append(item)

        # ▼ QListWidgetItem にも id を持たせる
        list_item = QtWidgets.QListWidgetItem(title)
        list_item.setData(QtCore.Qt.UserRole, new_uuid)
        list_widget.addItem(list_item)

        row = list_widget.count() - 1
        list_widget.setCurrentRow(row)
        self._on_resident_selected(cat_name, row)
        self._save_all()
        self._save_last_state()

    def _rename_resident_item(self, cat_name: str, list_widget: ResidentListWidget):
        row = list_widget.currentRow()
        if row < 0: return
        item_data = self.state["categories"][cat_name]["items"][row]
        cur_title = item_data["title"]
        
        new, ok = QtWidgets.QInputDialog.getText(self, "項目名の変更", "新しい名前：", text=cur_title)
        if not ok: return
        new = new.strip()
        if not new: return
        
        item_data["title"] = new
        list_widget.item(row).setText(new)
        
        # 🌟 修正: 詳細ラベルの更新もUUIDベースで安全に確認
        if hasattr(self, "_detail_ref") and self._detail_ref and self._detail_ref[0] == "resident" and self._detail_ref_uuid == item_data["id"]:
             self.detailLabel.setText(f"詳細（{cat_name} / {new}）")
             
        self._save_all()
        self._save_last_state()

    def _archive_resident_item(self, cat_name: str, list_widget: ResidentListWidget):
        row = list_widget.currentRow()
        if row < 0: return
        
        # 🌟 修正: 詳細エディタの内容を保存してから操作
        self._apply_detail_to_state()
        
        item_to_archive = self.state["categories"][cat_name]["items"].pop(row)
        list_widget.takeItem(row)
        item_to_archive["archived_at"] = int(time.time())
        item_to_archive["original_category"] = cat_name
        self.state["categories"][cat_name]["archive"].append(item_to_archive)
        
        if list_widget.currentRow() < 0:
            self._load_detail(None)
        
        self._refresh_resident_archive_list()
        self._save_all()
        
        for i in range(self.residentTabs.count()):
            if self.residentTabs.tabText(i) == "アーカイブ":
                self.residentTabs.setCurrentIndex(i); break

    def _delete_resident_item(self, cat_name: str, list_widget: ResidentListWidget):
        row = list_widget.currentRow()
        if row < 0: return
        
        # 🌟 修正: 詳細エディタの内容を保存してから操作
        self._apply_detail_to_state()
        
        title = self.state["categories"][cat_name]["items"][row]["title"]
        if QtWidgets.QMessageBox.question(self, "削除確認", f"「{title}」を削除しますか？") != QtWidgets.QMessageBox.Yes:
            return
            
        self.state["categories"][cat_name]["items"].pop(row)
        list_widget.takeItem(row)
        
        if list_widget.currentRow() < 0:
            self._load_detail(None)
            
        self._save_all()
        self._save_last_state()

    # 📌 修正: ドロップ時に呼び出され、データ側の順序をUIに合わせて更新するメソッド
    def _update_resident_items_order_from_list(self, cat_name: str, list_widget: ResidentListWidget):
        """リストウィジェットの現在のアイテム順序に基づいて、データ (self.state) の順序を更新する。"""
        # 🌟 ResidentListWidget の dropEvent で、既に detailEditor の内容は保存済み
        
        items = self.state["categories"][cat_name]["items"]
        # UUIDをキーとするアイテムの辞書を作成
        by_id = {it["id"]: it for it in items}
        
        new_items = []
        for i in range(list_widget.count()):
            itw = list_widget.item(i)
            # QListWidgetItemに埋め込んだUUIDを取得
            iid = itw.data(QtCore.Qt.UserRole)
            
            if iid and iid in by_id:
                new_items.append(by_id[iid])
            # 整合性チェックは重要だが、移動中に一時的にUUIDがない状態は発生し得ないのでスキップ
        
        # UI上のアイテム数とデータ上のアイテム数が一致しているか確認
        if len(new_items) == len(items) and len(new_items) == list_widget.count():
            # 順序が正しく反映されていれば、データリストを更新
            self.state["categories"][cat_name]["items"] = new_items
            self._save_all()
            self._save_last_state()
            
            # 🌟 最重要修正: 並び替え後、選択中の項目（UUIDベース）を再ロードする
            # これにより、並び替え前のインデックスで読み書きされる問題を回避
            
            current_row = list_widget.currentRow()
            if current_row >= 0:
                # 選択中のUUIDを取得
                selected_item_uuid = list_widget.item(current_row).data(QtCore.Qt.UserRole)
                # UUIDを元に詳細を再ロード (これが新しい行のデータであることを保証)
                self._load_detail(("resident", cat_name, selected_item_uuid))
                self._detail_ref_uuid = selected_item_uuid
            else:
                 self._load_detail(None)
        else:
            # アイテム数に不整合がある場合は警告 (稀なケース)
            QtWidgets.QMessageBox.warning(self, "エラー", f"常駐事項の並び替えでデータ不整合が発生しました: {cat_name} (再構築します)")
            self._rebuild_resident_tabs() 

    # 📌 修正: _on_resident_item_rows_moved はカスタムWidget内のdropEventで代替されるため、処理を削除
    def _on_resident_item_rows_moved(self, cat_name: str, list_widget: QtWidgets.QListWidget):
        pass


    # --- 常駐アーカイブ ---
    def _refresh_resident_archive_list(self):
        if not hasattr(self, 'residentArchiveList'): return
        self.residentArchiveList.clear()
        all_archives = []
        for cat_data in self.state["categories"].values():
            for item in cat_data.get("archive", []):
                all_archives.append(item)
        sorted_arc = sorted(all_archives, key=lambda x: x.get("archived_at", 0), reverse=True)
        for it in sorted_arc:
            ts = QtCore.QDateTime.fromSecsSinceEpoch(it.get("archived_at", 0)).toString("yyyy-MM-dd HH:mm")
            title = it.get('title','')
            orig_cat = it.get('original_category', '不明')
            list_item = QtWidgets.QListWidgetItem(f"[{orig_cat}] {ts} - {title}")
            list_item.setData(QtCore.Qt.UserRole, it["id"])
            self.residentArchiveList.addItem(list_item)

    def _get_resident_archive_item(self, row: int) -> Optional[Dict[str, Any]]:
        if not hasattr(self, 'residentArchiveList') or row < 0: return None
        item = self.residentArchiveList.item(row)
        if not item: return None
        item_id = item.data(QtCore.Qt.UserRole)
        for cat_data in self.state["categories"].values():
            for archive_item in cat_data.get("archive", []):
                if archive_item["id"] == item_id:
                    return archive_item
        return None

    def _restore_resident_archive_item(self):
        row = self.residentArchiveList.currentRow()
        archive_item = self._get_resident_archive_item(row)
        if not archive_item: return
        orig_cat = archive_item.get("original_category")
        if not orig_cat or orig_cat not in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "エラー", "復元先のカテゴリが見つかりません。"); return
        if QtWidgets.QMessageBox.question(self, "復元確認", f"「{archive_item['title']}」をカテゴリ「{orig_cat}」に復元しますか？") != QtWidgets.QMessageBox.Yes:
            return
        self.state["categories"][orig_cat]["archive"] = [it for it in self.state["categories"][orig_cat]["archive"] if it["id"] != archive_item["id"]]
        restored_item = {k: v for k, v in archive_item.items() if k not in ["archived_at", "original_category"]}
        self.state["categories"][orig_cat]["items"].append(restored_item)
        self._rebuild_resident_tabs(); self._refresh_resident_archive_list(); self._save_all()
        for i in range(self.residentTabs.count()):
            if self.residentTabs.tabText(i) == orig_cat:
                self.residentTabs.setCurrentIndex(i); break

    def _delete_resident_archive_item(self):
        row = self.residentArchiveList.currentRow()
        archive_item = self._get_resident_archive_item(row)
        if not archive_item: return
        if QtWidgets.QMessageBox.question(self, "削除確認", f"アーカイブ項目「{archive_item['title']}」を完全に削除しますか？") != QtWidgets.QMessageBox.Yes:
            return
        orig_cat = archive_item.get("original_category")
        if not orig_cat or orig_cat not in self.state["categories"]:
            for cat_data in self.state["categories"].values():
                cat_data["archive"] = [it for it in cat_data.get("archive", []) if it["id"] != archive_item["id"]]
        else:
            self.state["categories"][orig_cat]["archive"] = [it for it in self.state["categories"][orig_cat]["archive"] if it["id"] != archive_item["id"]]
        self._refresh_resident_archive_list(); self._save_all()

    def _edit_resident_archive_item(self, item: QtWidgets.QListWidgetItem):
        row = self.residentArchiveList.currentRow()
        target = self._get_resident_archive_item(row)
        if not target: return
        new_title, ok = QtWidgets.QInputDialog.getText(self, "アーカイブのタイトル", "タイトル：", text=target.get("title",""))
        if not ok: return
        dlg = QtWidgets.QInputDialog(self); dlg.setWindowTitle("アーカイブの本文（プレーンテキスト）")
        dlg.setLabelText("本文："); dlg.setTextValue(html_to_plain(target.get("html","")))
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            body_plain = dlg.textValue(); body_html = plain_to_html(body_plain)
            for cat_data in self.state["categories"].values():
                for it in cat_data.get("archive", []):
                    if it["id"] == target["id"]:
                        it["title"] = new_title; it["html"] = body_html; break
            self._refresh_resident_archive_list(); self._save_all()

    # --- セレクション → 詳細に読み込み ---
    def _on_todo_selected(self, current: QtCore.QModelIndex, previous: QtCore.QModelIndex):
        self._detail_ref_uuid = None # ToDo選択時はUUIDをクリア
        self._load_detail(("todo", current.row()) if current.isValid() else None)
        self._save_last_state()

    # 🌟 修正: 常駐事項選択時のロジック変更
    def _on_resident_selected(self, cat_name: str, row: int):
        # 選択されたリストアイテムからUUIDを取得
        selected_item_uuid = None
        if row >= 0:
            current_widget = self.residentTabs.currentWidget()
            lst = current_widget.findChild(ResidentListWidget, f"list_{cat_name}")
            if lst and lst.item(row):
                selected_item_uuid = lst.item(row).data(QtCore.Qt.UserRole)
        
        self._detail_ref_uuid = selected_item_uuid # 選択UUIDを保持
        
        if selected_item_uuid:
            # UUIDを引数に渡して詳細をロード
            self._load_detail(("resident", cat_name, selected_item_uuid))
        else:
            self._load_detail(None)
            
        self._save_last_state()

    # --- 詳細欄ロード／保存 ---
    def _load_detail(self, ref: Optional[Tuple]):
        # 🌟 修正: ここで、前の参照先の内容を必ず保存する
        if hasattr(self, "_detail_ref"):
            self._apply_detail_to_state()
            
        self._detail_ref = ref
        
        if ref is None:
            self.detailLabel.setText("詳細")
            self.detailEditor.blockSignals(True); self.detailEditor.clear()
            self.detailEditor.setPlaceholderText("ToDo または 常駐事項の項目を選択すると、ここで詳細編集できます。")
            self.detailEditor.blockSignals(False); return
            
        if ref[0] == "todo":
            row = ref[1]
            if 0 <= row < len(self.state["todo"]["items"]):
                it = self.state["todo"]["items"][row]
                self.detailLabel.setText(f"詳細（ToDo / {it.get('title','')}）")
                self.detailEditor.blockSignals(True); self.detailEditor.setHtml(it.get("html", "")); self.detailEditor.blockSignals(False)
        
        # 🌟 修正: 常駐事項はUUIDベースでデータを検索・読み込み
        elif ref[0] == "resident":
            _, cat, item_id = ref
            items = self.state["categories"].get(cat, {}).get("items", [])
            item_data = next((it for it in items if it.get("id") == item_id), None)
            
            if item_data:
                self.detailLabel.setText(f"詳細（{cat} / {item_data.get('title','無題')}）")
                self.detailEditor.blockSignals(True); self.detailEditor.setHtml(item_data.get("html","")); self.detailEditor.blockSignals(False)
            else:
                self._load_detail(None) # データが見つからない場合はクリア
                

    def _apply_detail_to_state(self):
        # 🌟 修正: detail_ref が存在しない場合は何もしない
        if not hasattr(self, "_detail_ref") or not self._detail_ref: return
        
        html = inline_external_images(self.detailEditor.toHtml())
        
        if self._detail_ref[0] == "todo":
            row = self._detail_ref[1]
            if 0 <= row < len(self.state["todo"]["items"]):
                self.state["todo"]["items"][row]["html"] = html
                self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
        
        # 🌟 修正: 常駐事項はUUIDベースでデータを検索・保存
        elif self._detail_ref[0] == "resident":
            # self._detail_ref は ("resident", cat_name, item_id) の形式
            _, cat, item_id = self._detail_ref 
            items = self.state["categories"].get(cat, {}).get("items", [])
            
            for item in items:
                if item.get("id") == item_id:
                    item["html"] = html
                    break
                    
        self._save_all()

    # --- カテゴリ（タブ）操作 ---
    def _on_resident_tab_moved(self, from_idx: int, to_idx: int):
        # 🌟 修正: タブを移動する前に、現在の詳細エディタの内容を保存
        self._apply_detail_to_state()
        
        new_order = [self.residentTabs.tabText(i) for i in range(self.residentTabs.count()) if self.residentTabs.tabText(i) != "アーカイブ"]
        self.state["category_order"] = new_order; self._save_all(); self._save_last_state()

    def _add_resident_tab(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "カテゴリの追加", "カテゴリ名：")
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "重複", "同名のカテゴリが既にあります。"); return
        self.state["categories"][name] = {"items": [], "archive": []}
        self.state["category_order"].append(name)
        self._rebuild_resident_tabs()
        for i in range(self.residentTabs.count()):
            if self.residentTabs.tabText(i) == name:
                self.residentTabs.setCurrentIndex(i); break
        self._save_all(); self._save_last_state()

    def _rename_resident_tab(self):
        cur = self.residentTabs.currentIndex()
        if cur < 0: return
        old = self.residentTabs.tabText(cur)
        if old == "アーカイブ":
            QtWidgets.QMessageBox.warning(self, "エラー", "アーカイブタブの名前は変更できません。"); return
        new, ok = QtWidgets.QInputDialog.getText(self, "カテゴリ名の変更", "新しい名前：", text=old)
        if not ok: return
        new = new.strip()
        if not new or new == old: return
        if new in self.state["categories"]:
            QtWidgets.QMessageBox.warning(self, "重複", "同名のカテゴリが既にあります。"); return
            
        # 🌟 修正: 詳細エディタの内容を保存してから操作
        self._apply_detail_to_state()
        
        self.state["categories"][new] = self.state["categories"].pop(old)
        self.state["category_order"] = [new if x == old else x for x in self.state["category_order"]]
        for arc in self.state["categories"][new]["archive"]:
            if arc.get("original_category") == old:
                arc["original_category"] = new
        self._rebuild_resident_tabs()
        for i in range(self.residentTabs.count()):
            if self.residentTabs.tabText(i) == new:
                self.residentTabs.setCurrentIndex(i); break
        self._save_all(); self._save_last_state()

    def _delete_resident_tab(self):
        cur = self.residentTabs.currentIndex()
        if cur < 0: return
        name = self.residentTabs.tabText(cur)
        if name == "アーカイブ":
            QtWidgets.QMessageBox.warning(self, "エラー", "アーカイブタブは削除できません。"); return
        if QtWidgets.QMessageBox.question(self, "削除確認", f"カテゴリ「{name}」を削除しますか？\n（項目とアーカイブ項目も全て消えます）") != QtWidgets.QMessageBox.Yes:
            return
            
        # 🌟 修正: 詳細エディタの内容を保存してから操作
        self._apply_detail_to_state()
        
        self.state["categories"].pop(name, None)
        self.state["category_order"] = [x for x in self.state["category_order"] if x != name]
        self._rebuild_resident_tabs()
        
        # 削除されたカテゴリの項目が選択されていた場合、詳細をクリア
        if hasattr(self, "_detail_ref") and self._detail_ref and self._detail_ref[0] == "resident" and self._detail_ref[1] == name:
            self._load_detail(None)
            
        self._save_all(); self._save_last_state()

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
        near_70 = abs(cur.width()-target_w) <= int(avail.width()*0.02) and abs(cur.height()-target_h) <= int(avail.height()*0.02)
        if near_70 and hasattr(self, "prev_geometry") and self.prev_geometry:
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
        self.actTrayOnTop = menu.addAction("常に手前に表示"); self.actTrayOnTop.setCheckable(True); self.actTrayOnTop.setChecked(False)
        self.actTrayOnTop.toggled.connect(self._toggle_always_on_top)
        menu.addSeparator()
        act_quit = menu.addAction("終了")
        act_show.triggered.connect(self._bring_front); act_hide.triggered.connect(self.showMinimized); act_quit.triggered.connect(QtWidgets.QApplication.quit)
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
        row = self.todoModel.rowCount() - 1
        self.todoList.setCurrentIndex(self.todoModel.index(row))
        self._load_detail(("todo", row))
        self._save_last_state()

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
            self._save_last_state()

    def _rename_selected_todo(self):
        row = self._selected_row()
        if row < 0: return
        cur = self.state["todo"]["items"][row].get("title","")
        new, ok = QtWidgets.QInputDialog.getText(self, "タイトル変更", "新しいタイトル：", text=cur)
        if not ok: return
        new = new.strip()
        if not new: return
        # 実体を書き換え & モデルへ通知
        self.state["todo"]["items"][row]["title"] = new
        self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
        if hasattr(self, "_detail_ref") and self._detail_ref and self._detail_ref[0] == "todo" and self._detail_ref[1] == row:
            self.detailLabel.setText(f"詳細（ToDo / {new}）")
        self._save_all()

    def _pick_color_for_selected_todo(self):
        row = self._selected_row()
        if row < 0: return
        menu = QtWidgets.QMenu(self)
        choices = [
            ("色なし（クリア）", None),
            ("赤（緊急）", "#ffcccc"),
            ("橙（高）", "#ffe5cc"),
            ("黄（中）", "#fff8c6"),
            ("緑（低）", "#e7ffd9"),
            ("青（情報）", "#e4f0ff"),
        ]
        for label, col in choices:
            act = menu.addAction(label); act.setData(col)
        picked = menu.exec(QtGui.QCursor.pos())
        if not picked: return
        col = picked.data()
        self.state["todo"]["items"][row]["color"] = col
        self.todoModel.dataChanged.emit(self.todoModel.index(row), self.todoModel.index(row))
        self._save_all()

    # ----- ToDo Archive -----
    def _edit_archive_item(self, item: QtWidgets.QListWidgetItem):
        row = self.archiveList.row(item)
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        target = sorted_arc[row]
        new_title, ok = QtWidgets.QInputDialog.getText(self, "アーカイブのタイトル", "タイトル：", text=target.get("title",""))
        if not ok: return
        dlg = QtWidgets.QInputDialog(self); dlg.setWindowTitle("アーカイブの本文（プレーンテキスト）")
        dlg.setLabelText("本文："); dlg.setTextValue(html_to_plain(target.get("html","")))
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            body_plain = dlg.textValue(); body_html = plain_to_html(body_plain)
            for it in self.state["todo"]["archive"]:
                if it["id"] == target["id"]:
                    it["title"] = new_title; it["html"] = body_html; break
            self._refresh_todo_archive_list(); self._save_all()

    def _archive_done(self):
        done = [it for it in self.state["todo"]["items"] if it.get("done")]
        if not done:
            QtWidgets.QMessageBox.information(self, "情報", "完了済みのToDoがありません。"); return
        now = int(time.time())
        for it in done:
            self.state["todo"]["archive"].append({
                "id": it["id"], "title": it.get("title",""), "archived_at": now,
                "html": it.get("html", ""), "color": it.get("color"),
            })
        self.state["todo"]["items"] = [it for it in self.state["todo"]["items"] if not it.get("done")]
        self.todoModel.layoutChanged.emit()
        self._refresh_todo_archive_list()
        self._save_all()
        self.centerTabs.setCurrentIndex(1)
        self._save_last_state()

    def _delete_selected_todo_archive(self):
        row = self.archiveList.currentRow()
        if row < 0: return
        if QtWidgets.QMessageBox.question(self, "削除確認", "選択したアーカイブ項目を削除しますか？") != QtWidgets.QMessageBox.Yes:
            return
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        target = sorted_arc[row]
        self.state["todo"]["archive"] = [it for it in self.state["todo"]["archive"] if it["id"] != target["id"]]
        self._refresh_todo_archive_list(); self._save_all()

    def _refresh_todo_archive_list(self):
        self.archiveList.clear()
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        for it in sorted_arc:
            ts = QtCore.QDateTime.fromSecsSinceEpoch(it.get("archived_at", 0)).toString("yyyy-MM-dd HH:mm")
            item = QtWidgets.QListWidgetItem(f"{ts}  -  {it.get('title','')}")
            col = it.get("color")
            if col: item.setBackground(QtGui.QBrush(QtGui.QColor(col)))
            self.archiveList.addItem(item)

    def _show_archive_context_menu(self, pos: QtCore.QPoint):
        row = self.archiveList.currentRow()
        if row < 0: return
        menu = QtWidgets.QMenu(self)
        choices = [
            ("色なし（クリア）", None),
            ("赤（緊急）", "#ffcccc"),
            ("橙（高）", "#ffe5cc"),
            ("黄（中）", "#fff8c6"),
            ("緑（低）", "#e7ffd9"),
            ("青（情報）", "#e4f0ff"),
        ]
        for label, col in choices:
            act = menu.addAction(label); act.setData(col)
        picked = menu.exec(self.archiveList.mapToGlobal(pos))
        if not picked: return
        sorted_arc = sorted(self.state["todo"]["archive"], key=lambda x: x.get("archived_at", 0), reverse=True)
        target = sorted_arc[row]
        for it in self.state["todo"]["archive"]:
            if it["id"] == target["id"]:
                it["color"] = picked.data(); break
        self._refresh_todo_archive_list(); self._save_all()

    # ----- フリースペース -----
    def _on_free_html_changed(self):
        self.state["memo2"]["html"] = inline_external_images(self.memoFree.toHtml())
        self._save_all()

    # ----- 共通 -----
    def _save_editor_bg(self, key: str, col: QtGui.QColor):
        bg = self.conf.get("editor_bg", {})
        bg[key] = col.name()
        self.conf["editor_bg"] = bg
        save_json(CONF_FILE, self.conf)

    def _save_last_state(self):
        last = self.conf.get("last", {})
        last["center_tab"] = self.centerTabs.currentIndex()
        idx = self.todoList.currentIndex()
        last["todo_row"] = idx.row() if idx.isValid() else -1
        rt_idx = self.residentTabs.currentIndex()
        rt_name = self.residentTabs.tabText(rt_idx) if rt_idx >= 0 else None
        last["resident_tab"] = rt_name
        
        resident_uuid = None
        if rt_name and rt_name != "アーカイブ":
            cat_widget = self.residentTabs.widget(rt_idx)
            lst = cat_widget.findChild(ResidentListWidget, f"list_{rt_name}")
            if lst:
                current_item = lst.currentItem()
                if current_item:
                    resident_uuid = current_item.data(QtCore.Qt.UserRole)
                    
        last["resident_uuid"] = resident_uuid # 📌 修正: 選択状態をUUIDで保存
        self.conf["last"] = last
        save_json(CONF_FILE, self.conf)

    def _restore_last_state(self):
        last = self.conf.get("last", {})
        ct = int(last.get("center_tab", 0)); ct = 0 if ct not in (0,1) else ct
        self.centerTabs.setCurrentIndex(ct)
        tr = int(last.get("todo_row", -1))
        if 0 <= tr < self.todoModel.rowCount():
            self.todoList.setCurrentIndex(self.todoModel.index(tr))
            self._load_detail(("todo", tr))
            
        rt_name = last.get("resident_tab")
        if rt_name:
            # 📌 修正: 選択UUIDをロードし、再構築時に利用
            self._detail_ref_uuid = last.get("resident_uuid") 
            
            for i in range(self.residentTabs.count()):
                if self.residentTabs.tabText(i) == rt_name:
                    self.residentTabs.setCurrentIndex(i); break
            
            # 再構築時に _detail_ref_uuid を元に選択状態が復元される
            if self.residentTabs.tabText(self.residentTabs.currentIndex()) == rt_name:
                pass # _build_category_widget で選択とロードが完了しているため何もしない

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
