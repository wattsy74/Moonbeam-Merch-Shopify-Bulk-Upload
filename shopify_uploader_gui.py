#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def configure_qt_environment() -> None:
    if sys.platform != "darwin":
        return

    try:
        import PySide6
    except Exception:
        return

    os.environ.setdefault("QT_QPA_PLATFORM", "cocoa")

    pyside_root = Path(PySide6.__file__).resolve().parent
    plugin_dir = pyside_root / "Qt" / "plugins"
    platforms_dir = plugin_dir / "platforms"
    qt_lib_dir = pyside_root / "Qt" / "lib"

    def prepend_env(name: str, value: str) -> None:
        current = os.environ.get(name, "")
        entries = [item for item in current.split(os.pathsep) if item]
        if str(value) not in entries:
            entries.insert(0, str(value))
        os.environ[name] = os.pathsep.join(entries)

    if plugin_dir.exists():
        prepend_env("QT_PLUGIN_PATH", str(plugin_dir))
    if platforms_dir.exists():
        prepend_env("QT_QPA_PLATFORM_PLUGIN_PATH", str(platforms_dir))
    if qt_lib_dir.exists():
        prepend_env("DYLD_FALLBACK_LIBRARY_PATH", str(qt_lib_dir))
        prepend_env("DYLD_FRAMEWORK_PATH", str(qt_lib_dir))


configure_qt_environment()

from PySide6.QtCore import QPoint, QRect, QSize, QThread, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPalette, QPainter, QTextBlockFormat, QTextCursor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

BASE_DIR = Path(__file__).resolve().parent
CLI_SCRIPT = BASE_DIR / "shopify_bulk_upload.py"
DEFAULT_MAP_PATH = BASE_DIR / "product_type_map.json"
GUI_BUILD = "GUI_BUILD_2026-08-05_qt1"


def quote_arg(value: str) -> str:
    if any(ch in value for ch in [" ", "\t", "\""]):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


class RichHtmlTextEdit(QTextEdit):
    def __init__(self, drop_handler=None, parent=None):
        super().__init__(parent)
        self._drop_handler = drop_handler
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path and self._drop_handler:
                    self._drop_handler(Path(path))
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class UploaderWorker(QThread):
    line = Signal(str)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, cmd: list[str], cwd: Path):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd

    def run(self):
        try:
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.line.emit(line)
            code = proc.wait()
            self.done.emit(code)
        except Exception as exc:
            self.failed.emit(str(exc))


class _FlowLayout(QLayout):
    def __init__(self, parent=None, h_spacing: int = 4, v_spacing: int = 4):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list[QLayoutItem] = []

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def horizontalSpacing(self):
        return self._h_spacing

    def verticalSpacing(self):
        return self._v_spacing

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def count(self):
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            space_x = self._h_spacing
            space_y = self._v_spacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + margins.bottom()


class MapEditorDialog(QDialog):
    def __init__(self, map_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Moonbeam Merch - Product Type Map Editor")
        self.resize(1400, 900)
        self._apply_moonbeam_theme()

        self.map_path = Path(map_path) if map_path else DEFAULT_MAP_PATH
        self.map_data: dict[str, dict] = {}
        self._updating_description_content = False
        self._description_source_path: Path | None = None

        self._build_ui()
        self.load_map()

    def _apply_moonbeam_theme(self):
        """Apply Moonbeam Merch celestial theme to dialog."""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#E8DFF5"))
        palette.setColor(QPalette.Base, QColor("#F5F2FB"))
        palette.setColor(QPalette.WindowText, QColor("#0A1E3F"))
        palette.setColor(QPalette.Text, QColor("#0A1E3F"))
        palette.setColor(QPalette.ButtonText, QColor("#0A1E3F"))
        palette.setColor(QPalette.Button, QColor("#D4C5E8"))
        palette.setColor(QPalette.Highlight, QColor("#6B4C99"))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(palette)

        stylesheet = """
            QDialog, QMainWindow {
                background-color: #E8DFF5;
            }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #FFFFFF;
                color: #0A1E3F;
                border: 2px solid #D4C5E8;
                border-radius: 6px;
                padding: 6px;
                font-size: 11px;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 2px solid #6B4C99;
            }
            QPushButton {
                background-color: #6B4C99;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #7D5BA6;
            }
            QPushButton:pressed {
                background-color: #5A3D7F;
            }
            QGroupBox {
                color: #0A1E3F;
                border: 2px solid #D4C5E8;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
            }
            QLabel {
                color: #0A1E3F;
                font-size: 11px;
            }
            QListWidget {
                background-color: #FFFFFF;
                color: #0A1E3F;
                border: 2px solid #D4C5E8;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background-color: #D4C5E8;
                color: #0A1E3F;
            }
            QTabBar::tab {
                background-color: #D4C5E8;
                color: #0A1E3F;
                padding: 8px 16px;
                border-bottom: 3px solid #E8DFF5;
            }
            QTabBar::tab:selected {
                background-color: #6B4C99;
                color: #FFFFFF;
                border-bottom: 3px solid #6B4C99;
            }
        """
        self.setStyleSheet(stylesheet)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Map File"))
        self.map_path_edit = QLineEdit(str(self.map_path))
        top.addWidget(self.map_path_edit, 1)

        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse_map)
        top.addWidget(browse)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.load_map)
        top.addWidget(reload_btn)

        save_btn = QPushButton("Save Map")
        save_btn.clicked.connect(self.save_map)
        top.addWidget(save_btn)

        layout.addLayout(top)

        split = QSplitter(Qt.Horizontal)

        left_wrap = QWidget()
        left_layout = QVBoxLayout(left_wrap)
        left_wrap.setMinimumWidth(260)

        entry_btns = QGridLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.new_entry)
        apply_btn = QPushButton("Apply To Entry")
        apply_btn.clicked.connect(self.apply_entry)
        del_btn = QPushButton("Delete Entry")
        del_btn.clicked.connect(self.delete_entry)
        clone_btn = QPushButton("Clone")
        clone_btn.setToolTip("Clone the current style entry")
        clone_btn.clicked.connect(lambda checked=False: self._clone_description_file())

        entry_btns.addWidget(new_btn, 0, 0)
        entry_btns.addWidget(apply_btn, 0, 1)
        entry_btns.addWidget(del_btn, 1, 0)
        entry_btns.addWidget(clone_btn, 1, 1)
        entry_btns.setColumnStretch(0, 1)
        entry_btns.setColumnStretch(1, 1)
        left_layout.addLayout(entry_btns)

        self.style_list = QListWidget()
        self.style_list.currentTextChanged.connect(self.load_style)
        left_layout.addWidget(self.style_list)

        split.addWidget(left_wrap)

        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)

        form_box = QGroupBox("Entry")
        form = QFormLayout(form_box)

        self.style_code_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.price_edit = QLineEdit("0.00")
        self.template_edit = QLineEdit()
        self.product_type_edit = QLineEdit()

        desc_file_row = QHBoxLayout()
        self.desc_file_edit = QLineEdit()
        desc_browse = QPushButton("Browse")
        desc_browse.clicked.connect(self.browse_description_file)
        desc_clone = QPushButton("Clone")
        desc_clone.setToolTip("Clone the current style entry")
        desc_clone.clicked.connect(lambda checked=False: self._clone_description_file())
        desc_file_row.addWidget(self.desc_file_edit, 1)
        desc_file_row.addWidget(desc_browse)
        desc_file_row.addWidget(desc_clone)

        form.addRow("style_code", self.style_code_edit)
        form.addRow("label", self.label_edit)
        form.addRow("price", self.price_edit)
        form.addRow("template_suffix", self.template_edit)
        form.addRow("product_type", self.product_type_edit)

        desc_file_wrap = QWidget()
        desc_file_wrap.setLayout(desc_file_row)
        form.addRow("description_file", desc_file_wrap)
        form.addRow("description", self._build_description_editor())

        right_layout.addWidget(form_box)

        split.addWidget(right_wrap)
        split.setSizes([280, 820])

        layout.addWidget(split, 1)

    def browse_map(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select product_type_map.json", str(BASE_DIR), "JSON (*.json);;All files (*)")
        if path:
            self.map_path_edit.setText(path)

    def _build_description_editor(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        # Wrapping toolbar using a flow layout
        toolbar_widget = QWidget()
        toolbar_layout = _FlowLayout(toolbar_widget, h_spacing=2, v_spacing=2)

        def _btn(label, tip, slot):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            b.setSizePolicy(b.sizePolicy().horizontalPolicy(), b.sizePolicy().verticalPolicy())
            return b

        toolbar_layout.addWidget(_btn("B", "Bold", self._apply_bold))
        toolbar_layout.addWidget(_btn("I", "Italic", self._apply_italic))
        toolbar_layout.addWidget(_btn("U", "Underline", self._apply_underline))

        toolbar_layout.addWidget(QLabel("Font"))
        self.font_family_combo = QComboBox()
        self.font_family_combo.addItems(QFontDatabase().families())
        self.font_family_combo.setCurrentText("Helvetica")
        self.font_family_combo.setFixedWidth(160)
        self.font_family_combo.currentTextChanged.connect(self._apply_font_family)
        toolbar_layout.addWidget(self.font_family_combo)

        toolbar_layout.addWidget(QLabel("Size"))
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems([str(size) for size in range(8, 33)])
        self.font_size_combo.setCurrentText("14")
        self.font_size_combo.setFixedWidth(54)
        self.font_size_combo.currentTextChanged.connect(self._apply_font_size)
        toolbar_layout.addWidget(self.font_size_combo)

        toolbar_layout.addWidget(_btn("Color", "Set font color", self._set_font_color))
        toolbar_layout.addWidget(_btn("• List", "Bullet list", self._insert_bullet_list))
        toolbar_layout.addWidget(_btn("1. List", "Numbered list", self._insert_numbered_list))
        toolbar_layout.addWidget(_btn("H1", "Heading 1", lambda: self._insert_heading(1)))
        toolbar_layout.addWidget(_btn("H2", "Heading 2", lambda: self._insert_heading(2)))
        toolbar_layout.addWidget(_btn("Quote", "Block quote", self._insert_blockquote))
        toolbar_layout.addWidget(_btn("L", "Align left", lambda: self._set_alignment(Qt.AlignLeft)))
        toolbar_layout.addWidget(_btn("C", "Align center", lambda: self._set_alignment(Qt.AlignCenter)))
        toolbar_layout.addWidget(_btn("R", "Align right", lambda: self._set_alignment(Qt.AlignRight)))
        toolbar_layout.addWidget(_btn("HR", "Horizontal rule", self._insert_horizontal_rule))
        toolbar_layout.addWidget(_btn("Table", "Insert table", self._insert_table))
        toolbar_layout.addWidget(_btn("Link", "Insert link", self._insert_link))
        toolbar_layout.addWidget(_btn("Image", "Insert image", self._insert_image))
        toolbar_layout.addWidget(_btn("Clear", "Clear formatting", self._clear_formatting))
        toolbar_layout.addWidget(_btn("Load HTML", "Load HTML from file", self._load_description_file))
        toolbar_layout.addWidget(_btn("Save HTML", "Save current HTML to a file", self._save_description_file))

        layout.addWidget(toolbar_widget)

        self.description_edit = RichHtmlTextEdit(self._handle_dropped_file)
        self.description_edit.setAcceptRichText(True)
        self.description_edit.setMinimumHeight(260)
        self.description_edit.setPlaceholderText("Create rich HTML content here...")
        self.description_edit.textChanged.connect(self._sync_description_from_visual)

        self.description_source_edit = QTextEdit()
        self.description_source_edit.setAcceptRichText(False)
        self.description_source_edit.setMinimumHeight(260)
        self.description_source_edit.setPlaceholderText("HTML source")
        self.description_source_edit.textChanged.connect(self._sync_description_from_source)

        self.description_preview = QWebEngineView()

        self.description_tabs = QTabWidget()
        self.description_tabs.addTab(self.description_edit, "Visual")
        self.description_tabs.addTab(self.description_source_edit, "HTML")
        self.description_tabs.addTab(self.description_preview, "Preview")

        layout.addWidget(self.description_tabs, 1)
        return container

    def browse_description_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select descriptor file", str(BASE_DIR), "HTML (*.html *.htm);;Text files (*.txt);;All files (*)")
        if not path:
            return
        self._set_description_file_path(path)
        self._load_description_file(path)

    def _set_description_file_path(self, path: str):
        try:
            map_parent = Path(self.map_path_edit.text()).resolve().parent
            rel = Path(path).resolve().relative_to(map_parent)
            self.desc_file_edit.setText(str(rel).replace("\\", "/"))
        except Exception:
            self.desc_file_edit.setText(path)

    def _resolve_description_path(self, path: str | None = None) -> Path | None:
        if not path:
            path = self.desc_file_edit.text().strip()
        if not path:
            return None
        candidate = Path(path)
        if not candidate.is_absolute():
            map_parent = Path(self.map_path_edit.text()).resolve().parent
            candidate = (map_parent / candidate).resolve()
        return candidate

    def _to_relative_description_path(self, path: Path) -> str:
        try:
            map_parent = Path(self.map_path_edit.text()).resolve().parent
            rel = path.resolve().relative_to(map_parent)
            return str(rel).replace("\\", "/")
        except Exception:
            return str(path)

    def _set_description_content(self, html_text: str):
        self._updating_description_content = True
        prepared_html = self._prepare_html_for_display(html_text or "")
        self.description_edit.setHtml(prepared_html)
        self.description_source_edit.setPlainText(html_text or "")
        self._refresh_rendered_html(prepared_html)
        self._updating_description_content = False

    def _preview_html(self, html_text: str) -> str:
        text = (html_text or "").strip()
        if not text:
            return "<p></p>"
        return f"<div style='font-family: Helvetica, Arial, sans-serif; font-size: 13px; line-height: 1.5;'>{text}</div>"

    def _prepare_html_for_display(self, html_text: str) -> str:
        if not html_text:
            return ""

        def replace_image_src(match: re.Match[str]) -> str:
            prefix, src_value, suffix = match.groups()
            resolved_path = self._resolve_media_path(src_value)
            if resolved_path is None:
                return match.group(0)
            if resolved_path.suffix.lower() == ".svg":
                png_path = self._render_svg_to_png(resolved_path)
                if png_path is not None:
                    return f"{prefix}{QUrl.fromLocalFile(str(png_path)).toString()}{suffix}"
                svg_text = resolved_path.read_text(encoding="utf-8")
                encoded_svg = svg_text.replace("\n", " ").replace('"', "'" )
                return f"{prefix}data:image/svg+xml;base64,{base64.b64encode(encoded_svg.encode('utf-8')).decode('ascii')}{suffix}"
            return f"{prefix}{QUrl.fromLocalFile(str(resolved_path)).toString()}{suffix}"

        return re.sub(r'(<img\b[^>]*src=["\'])([^"\']+)(["\'])', replace_image_src, html_text)

    def _resolve_media_path(self, src_value: str) -> Path | None:
        candidate = src_value.strip()
        if not candidate:
            return None
        if candidate.startswith("file://"):
            candidate = QUrl(candidate).toLocalFile()
            if not candidate:
                return None
            path = Path(candidate)
        else:
            path = Path(candidate)
            if not path.is_absolute():
                map_parent = Path(self.map_path_edit.text()).resolve().parent
                path = (map_parent / path).resolve()
        if not path.exists():
            return None
        return path

    def _render_svg_to_png(self, svg_path: Path) -> Path | None:
        if svg_path.suffix.lower() != ".svg":
            return None
        cache_dir = BASE_DIR / ".editor_cache" / "images"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = f"{svg_path.stem}_{abs(hash(svg_path.resolve().as_posix()))}.png"
        png_path = cache_dir / cache_key
        if png_path.exists() and png_path.stat().st_mtime >= svg_path.stat().st_mtime:
            return png_path
        try:
            renderer = QSvgRenderer(str(svg_path))
        except Exception:
            return None
        if not renderer.isValid():
            return None

        size = renderer.defaultSize()
        width = max(1, size.width()) if size.isValid() else 1200
        height = max(1, size.height()) if size.isValid() else 1200
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(png_path), "PNG"):
            return None
        return png_path

    def _refresh_rendered_html(self, html_text: str):
        content = self._preview_html(html_text)
        base_url = QUrl.fromLocalFile(str(BASE_DIR))
        self.description_preview.setHtml(content, base_url)

    def _sync_description_from_visual(self):
        if self._updating_description_content:
            return
        html_text = self.description_edit.toHtml().strip()
        self._updating_description_content = True
        self.description_source_edit.setPlainText(html_text)
        self._refresh_rendered_html(html_text)
        self._updating_description_content = False

    def _sync_description_from_source(self):
        if self._updating_description_content:
            return
        html_text = self.description_source_edit.toPlainText().strip()
        self._updating_description_content = True
        self.description_edit.setHtml(html_text)
        self._refresh_rendered_html(html_text)
        self._updating_description_content = False

    def _apply_bold(self):
        cursor = self.description_edit.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontWeight(QFont.Bold if fmt.fontWeight() != QFont.Bold else QFont.Normal)
        cursor.mergeCharFormat(fmt)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _apply_italic(self):
        cursor = self.description_edit.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontItalic(not fmt.fontItalic())
        cursor.mergeCharFormat(fmt)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _apply_underline(self):
        cursor = self.description_edit.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontUnderline(not fmt.fontUnderline())
        cursor.mergeCharFormat(fmt)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _set_font_size(self):
        cursor = self.description_edit.textCursor()
        current_font = cursor.charFormat().font()
        size, ok = QInputDialog.getInt(self, "Font Size", "Size:", current_font.pointSize() or 12, 6, 72, 1)
        if not ok:
            return
        self.font_size_combo.setCurrentText(str(size))
        self._apply_font_size(str(size))

    def _set_font_color(self):
        cursor = self.description_edit.textCursor()
        fmt = cursor.charFormat()
        current_color = fmt.foreground().color()
        if not current_color.isValid():
            current_color = QColor("#000000")
        color = QColorDialog.getColor(current_color, self, "Select Text Color")
        if not color.isValid():
            return
        fmt.setForeground(color)
        cursor.mergeCharFormat(fmt)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _apply_font_family(self, family: str):
        if not family:
            return
        cursor = self.description_edit.textCursor()
        fmt = cursor.charFormat()
        font = fmt.font()
        font.setFamily(family)
        fmt.setFont(font)
        cursor.mergeCharFormat(fmt)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _apply_font_size(self, size: str):
        if not size:
            return
        try:
            point_size = int(size)
        except ValueError:
            return
        cursor = self.description_edit.textCursor()
        fmt = cursor.charFormat()
        font = fmt.font()
        font.setPointSize(point_size)
        fmt.setFont(font)
        cursor.mergeCharFormat(fmt)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_bullet_list(self):
        cursor = self.description_edit.textCursor()
        cursor.insertHtml("<ul><li>List item</li></ul>")
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_numbered_list(self):
        cursor = self.description_edit.textCursor()
        cursor.insertHtml("<ol><li>List item</li></ol>")
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_heading(self, level: int):
        cursor = self.description_edit.textCursor()
        selected = cursor.selectedText() or f"Heading {level}"
        cursor.insertHtml(f"<h{level}>{selected}</h{level}>")
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_blockquote(self):
        cursor = self.description_edit.textCursor()
        selected = cursor.selectedText() or "Quote"
        cursor.insertHtml(f"<blockquote>{selected}</blockquote>")
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _set_alignment(self, alignment: Qt.AlignmentFlag):
        cursor = self.description_edit.textCursor()
        block_format = QTextBlockFormat()
        block_format.setAlignment(alignment)
        cursor.mergeBlockFormat(block_format)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_horizontal_rule(self):
        cursor = self.description_edit.textCursor()
        cursor.insertHtml("<hr />")
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_table(self):
        rows, ok_rows = QInputDialog.getInt(self, "Insert Table", "Rows:", 2, 1, 10, 1)
        cols, ok_cols = QInputDialog.getInt(self, "Insert Table", "Columns:", 2, 1, 10, 1)
        if not ok_rows or not ok_cols:
            return
        table_html = "<table style='border-collapse: collapse; width: 100%;'>"
        for _ in range(rows):
            table_html += "<tr>"
            for _ in range(cols):
                table_html += "<td style='border: 1px solid #ccc; padding: 6px;'>Cell</td>"
            table_html += "</tr>"
        table_html += "</table>"
        cursor = self.description_edit.textCursor()
        cursor.insertHtml(table_html)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _clear_formatting(self):
        cursor = self.description_edit.textCursor()
        char_format = cursor.charFormat()
        char_format.setFontWeight(QFont.Normal)
        char_format.setFontItalic(False)
        char_format.setFontUnderline(False)
        char_format.setForeground(QColor("#000000"))
        char_format.setFont(QFont("Helvetica", 12))
        cursor.mergeCharFormat(char_format)
        block_format = QTextBlockFormat()
        block_format.setAlignment(Qt.AlignLeft)
        cursor.mergeBlockFormat(block_format)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_link(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Insert Link")
        form = QFormLayout(dialog)

        url_edit = QLineEdit()
        url_edit.setPlaceholderText("https://example.com")
        text_edit = QLineEdit()
        text_edit.setPlaceholderText("Display text (leave blank to use URL)")
        title_edit = QLineEdit()
        title_edit.setPlaceholderText("Tooltip / alt text (optional)")

        # Pre-fill display text with selected editor text
        selected = self.description_edit.textCursor().selectedText().strip()
        if selected:
            text_edit.setText(selected)

        form.addRow("URL *", url_edit)
        form.addRow("Display text", text_edit)
        form.addRow("Title / tooltip", title_edit)

        btns = QHBoxLayout()
        ok_btn = QPushButton("Insert")
        ok_btn.setDefault(True)
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btns.addStretch(1)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        form.addRow(btns)

        if dialog.exec() != QDialog.Accepted:
            return

        url = url_edit.text().strip()
        if not url:
            return
        display = text_edit.text().strip() or url
        title = title_edit.text().strip()

        title_attr = f' title="{title}"' if title else ""
        html = f'<a href="{url}"{title_attr}>{display}</a>'
        cursor = self.description_edit.textCursor()
        cursor.insertHtml(html)
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _insert_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select image", str(BASE_DIR), "Images (*.png *.jpg *.jpeg *.gif *.webp);;All files (*)")
        if not path:
            return
        self._insert_image_markup(Path(path).resolve())

    def _insert_image_markup(self, resolved_path: Path):
        if resolved_path.suffix.lower() == ".svg":
            svg_text = resolved_path.read_text(encoding="utf-8")
            encoded_svg = svg_text.replace("\n", " ").replace('"', "'" )
            data_uri = f"data:image/svg+xml;base64,{base64.b64encode(encoded_svg.encode('utf-8')).decode('ascii')}"
            cursor = self.description_edit.textCursor()
            cursor.insertHtml(f'<img src="{data_uri}" alt="image" style="max-width: 100%;" />')
            self.description_edit.setTextCursor(cursor)
            self._sync_description_from_visual()
            return
        cursor = self.description_edit.textCursor()
        cursor.insertHtml(f'<img src="file://{resolved_path}" alt="image" style="max-width: 100%;" />')
        self.description_edit.setTextCursor(cursor)
        self._sync_description_from_visual()

    def _handle_dropped_file(self, path: Path):
        if not path.exists():
            return

        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            self._insert_image_markup(path.resolve())
        elif suffix in {".html", ".htm", ".txt"}:
            try:
                html_text = path.read_text(encoding="utf-8")
            except Exception as exc:
                QMessageBox.warning(self, "Drop Error", f"Could not read dropped file:\n{exc}")
                return
            self._set_description_content(html_text)
        else:
            QMessageBox.information(self, "Drop ignored", "Drop an image or HTML/text file to import it.")

    def _save_description_file(self):
        html_text = self.description_source_edit.toPlainText().strip()
        target = self._description_source_path or self._resolve_description_path(self.desc_file_edit.text().strip())
        if target is None:
            target, _ = QFileDialog.getSaveFileName(self, "Save HTML file", str(BASE_DIR), "HTML (*.html *.htm);;All files (*)")
            if not target:
                return
            if Path(target).suffix.lower() not in {".html", ".htm"}:
                target = f"{target}.html"
            target = Path(target).resolve()
        else:
            target = Path(target).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html_text, encoding="utf-8")
            self._description_source_path = target
            self._set_description_file_path(str(target))
            QMessageBox.information(self, "Saved", f"Description saved to:\n{target}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save description file:\n{exc}")

    def _clone_description_file(self, target_path: str | Path | None | bool = None):
        if isinstance(target_path, bool):
            target_path = None

        source_style = self.style_code_edit.text().strip() or (self.style_list.currentItem().text() if self.style_list.currentItem() else "")
        if not source_style:
            QMessageBox.warning(self, "No style selected", "Select a style entry to clone first")
            return None

        base_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_style).strip("_") or "style"
        proposed_style = f"copy_of_{base_name}"
        new_style = proposed_style
        suffix = 2
        while new_style in self.map_data:
            new_style = f"{proposed_style}_{suffix}"
            suffix += 1

        current_entry = self.normalize_entry(self.map_data.get(source_style, {}))
        label = self.label_edit.text().strip() or current_entry["label"]
        price = self.price_edit.text().strip() or current_entry["price"]
        template_suffix = self.template_edit.text().strip() or current_entry["template_suffix"]
        product_type = self.product_type_edit.text().strip() or current_entry["product_type"]
        description_text = self.description_source_edit.toPlainText().strip()
        description_file = self.desc_file_edit.text().strip()

        entry = {
            "label": label,
            "price": price,
        }
        if template_suffix:
            entry["template_suffix"] = template_suffix
        if product_type:
            entry["product_type"] = product_type

        if description_file:
            source_path = self._resolve_description_path(description_file)
            if source_path is not None:
                target_path = source_path.with_name(f"{new_style}{source_path.suffix}")
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(description_text or source_path.read_text(encoding="utf-8"), encoding="utf-8")
                    entry["description_file"] = self._to_relative_description_path(target_path)
                except Exception as exc:
                    QMessageBox.critical(self, "Clone Error", f"Could not write cloned description file:\n{exc}")
                    return None
            elif description_text:
                entry["description"] = description_text
        elif description_text:
            entry["description"] = description_text

        self.map_data[new_style] = entry
        self.refresh_style_list()

        for i in range(self.style_list.count()):
            if self.style_list.item(i).text() == new_style:
                self.style_list.setCurrentRow(i)
                break

        self.style_code_edit.setText(new_style)
        self.label_edit.setText(label)
        self.price_edit.setText(price)
        self.template_edit.setText(template_suffix)
        self.product_type_edit.setText(product_type)
        if entry.get("description_file"):
            self.desc_file_edit.setText(entry["description_file"])
            self._load_description_file(entry["description_file"])
        else:
            self.desc_file_edit.clear()
            self._description_source_path = None
            self._set_description_content(entry.get("description", ""))

        if not hasattr(self, "_clone_from_test"):
            QMessageBox.information(self, "Cloned", f"Created new style entry:\n{new_style}")
        return new_style

    def _load_description_file(self, path: str | None = None):
        target = path or self.desc_file_edit.text().strip()
        if not target:
            target, _ = QFileDialog.getOpenFileName(self, "Select HTML file", str(BASE_DIR), "HTML (*.html *.htm);;Text files (*.txt);;All files (*)")
            if not target:
                return
        resolved = self._resolve_description_path(target)
        if resolved is None:
            return
        try:
            html_text = resolved.read_text(encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Could not load description file:\n{exc}")
            return
        self._set_description_file_path(str(resolved))
        self._description_source_path = resolved
        self._set_description_content(html_text)

    def load_style(self, style_code: str):
        if not style_code:
            return
        entry = self.normalize_entry(self.map_data.get(style_code, {}))
        self.style_code_edit.setText(style_code)
        self.label_edit.setText(entry["label"])
        self.price_edit.setText(entry["price"])
        self.template_edit.setText(entry["template_suffix"])
        self.product_type_edit.setText(entry["product_type"])
        self.desc_file_edit.setText(entry["description_file"])
        if entry["description_file"]:
            self._load_description_file(entry["description_file"])
            return
        self._description_source_path = None
        self._set_description_content(entry["description"])

    def new_entry(self):
        self.style_code_edit.clear()
        self.label_edit.clear()
        self.price_edit.setText("0.00")
        self.template_edit.clear()
        self.product_type_edit.clear()
        self.desc_file_edit.clear()
        self._description_source_path = None
        self._set_description_content("")
        self.style_list.clearSelection()

    def apply_entry(self):
        style_code = self.style_code_edit.text().strip()
        label = self.label_edit.text().strip()
        price = self.price_edit.text().strip() or "0.00"
        template_suffix = self.template_edit.text().strip()
        product_type = self.product_type_edit.text().strip()
        description_file = self.desc_file_edit.text().strip()
        description = self.description_source_edit.toPlainText().strip()

        if not style_code:
            QMessageBox.warning(self, "Missing style_code", "style_code is required")
            return
        if not label:
            QMessageBox.warning(self, "Missing label", "label is required")
            return

        entry = {
            "label": label,
            "price": price,
        }
        if template_suffix:
            entry["template_suffix"] = template_suffix
        if product_type:
            entry["product_type"] = product_type

        if description_file:
            target_path = self._resolve_description_path(description_file)
            if target_path is None:
                QMessageBox.warning(self, "Missing description file", "The selected description file path is invalid")
                return
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                target_path.write_text(description, encoding="utf-8")
            except Exception as exc:
                QMessageBox.critical(self, "Save Error", f"Could not save description file:\n{exc}")
                return
            entry["description_file"] = self._to_relative_description_path(target_path)
        elif description:
            entry["description"] = description

        self.map_data[style_code] = entry
        self.refresh_style_list()

        for i in range(self.style_list.count()):
            if self.style_list.item(i).text() == style_code:
                self.style_list.setCurrentRow(i)
                break

    def normalize_entry(self, value):
        if isinstance(value, str):
            return {
                "label": value,
                "price": "0.00",
                "template_suffix": "",
                "product_type": "",
                "description_file": "",
                "description": "",
            }
        if not isinstance(value, dict):
            return {
                "label": "",
                "price": "0.00",
                "template_suffix": "",
                "product_type": "",
                "description_file": "",
                "description": "",
            }
        return {
            "label": str(value.get("label", "")),
            "price": str(value.get("price", "0.00")),
            "template_suffix": str(value.get("template_suffix", "") or ""),
            "product_type": str(value.get("product_type", "") or ""),
            "description_file": str(value.get("description_file", "") or ""),
            "description": str(value.get("description", "") or ""),
        }

    def load_map(self):
        self.map_path = Path(self.map_path_edit.text() or DEFAULT_MAP_PATH)
        if not self.map_path.exists():
            QMessageBox.warning(self, "Map Not Found", f"Map file not found:\n{self.map_path}")
            self.map_data = {}
            self.refresh_style_list()
            return
        try:
            data = json.loads(self.map_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Map root must be a JSON object")
            self.map_data = data
            self.refresh_style_list()
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Could not load map:\n{exc}")

    def save_map(self):
        self.map_path = Path(self.map_path_edit.text() or DEFAULT_MAP_PATH)
        try:
            self.map_path.parent.mkdir(parents=True, exist_ok=True)
            self.map_path.write_text(json.dumps(self.map_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            QMessageBox.information(self, "Saved", f"Map saved:\n{self.map_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save map:\n{exc}")

    def refresh_style_list(self):
        self.style_list.clear()
        for style_code in sorted(self.map_data.keys(), key=lambda s: s.lower()):
            self.style_list.addItem(style_code)

    def delete_entry(self):
        style_code = self.style_code_edit.text().strip()
        if style_code and style_code in self.map_data:
            del self.map_data[style_code]
            self.refresh_style_list()
            self.new_entry()


class MainWindow(QMainWindow):
    def __init__(self, folder: str = "", map_path: str = ""):
        super().__init__()
        self.setWindowTitle("Moonbeam Merch Uploader")
        self.resize(1100, 780)
        self._apply_moonbeam_theme()

        self.worker: UploaderWorker | None = None

        self._build_ui()
        if folder:
            self.folder_edit.setText(folder)
        if map_path:
            self.map_edit.setText(map_path)
        self.append_output(f"Moonbeam Merch Uploader loaded from: {BASE_DIR / 'shopify_uploader_gui.py'}\n")

    def _apply_moonbeam_theme(self):
        """Apply Moonbeam Merch celestial theme."""
        # Moonbeam color palette
        palette = QPalette()
        # Soft purple gradient base
        palette.setColor(QPalette.Window, QColor("#E8DFF5"))
        palette.setColor(QPalette.Base, QColor("#F5F2FB"))
        # Dark navy text
        palette.setColor(QPalette.WindowText, QColor("#0A1E3F"))
        palette.setColor(QPalette.Text, QColor("#0A1E3F"))
        palette.setColor(QPalette.ButtonText, QColor("#0A1E3F"))
        # Button styling
        palette.setColor(QPalette.Button, QColor("#D4C5E8"))
        # Highlights
        palette.setColor(QPalette.Highlight, QColor("#6B4C99"))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(palette)

        # Modern stylesheet with celestial theme
        stylesheet = """
            QMainWindow, QDialog {
                background-color: #E8DFF5;
            }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #FFFFFF;
                color: #0A1E3F;
                border: 2px solid #D4C5E8;
                border-radius: 6px;
                padding: 6px;
                font-size: 11px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 2px solid #6B4C99;
                outline: none;
            }
            QPushButton {
                background-color: #6B4C99;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 11px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
            }
            QPushButton:hover {
                background-color: #7D5BA6;
            }
            QPushButton:pressed {
                background-color: #5A3D7F;
            }
            QPushButton:disabled {
                background-color: #C9B5D9;
                color: #8A7FA8;
            }
            QGroupBox {
                color: #0A1E3F;
                border: 2px solid #D4C5E8;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
            }
            QLabel {
                color: #0A1E3F;
                font-size: 11px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
            }
            QCheckBox, QRadioButton {
                color: #0A1E3F;
                font-size: 11px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
            }
            QListWidget {
                background-color: #FFFFFF;
                color: #0A1E3F;
                border: 2px solid #D4C5E8;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background-color: #D4C5E8;
                color: #0A1E3F;
            }
            QListWidget::item:hover {
                background-color: #ECDAE5;
            }
            QTabBar::tab {
                background-color: #D4C5E8;
                color: #0A1E3F;
                padding: 8px 16px;
                border: none;
                border-bottom: 3px solid #E8DFF5;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
            }
            QTabBar::tab:selected {
                background-color: #6B4C99;
                color: #FFFFFF;
                border-bottom: 3px solid #6B4C99;
            }
            QTabWidget::pane {
                border: 2px solid #D4C5E8;
                border-radius: 6px;
            }
            QSplitter::handle {
                background-color: #D4C5E8;
            }
        """
        self.setStyleSheet(stylesheet)

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        title = QLabel("Moonbeam Merch Uploader")
        title.setStyleSheet("""
            color: #0A1E3F;
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 8px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
        """)
        layout.addWidget(title)

        form_box = QGroupBox("Upload Settings")
        form = QGridLayout(form_box)

        self.folder_edit = QLineEdit()
        self.map_edit = QLineEdit(str(DEFAULT_MAP_PATH))
        self.vendor_edit = QLineEdit("Moonbeam Merch")
        self.price_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.uploaded_dir_edit = QLineEdit("uploaded")
        self.dry_run_check = QCheckBox("Dry Run")
        self.dry_run_check.setChecked(True)
        self.publish_status_check = QCheckBox("Publish as Active")
        self.publish_status_check.setChecked(False)

        self._add_row(form, 0, "Folder", self.folder_edit, self.browse_folder)
        self._add_row(form, 1, "Map File", self.map_edit, self.browse_map)
        self._add_row(form, 2, "Vendor", self.vendor_edit)
        self._add_row(form, 3, "Price Override", self.price_edit)
        self._add_row(form, 4, "Description Override", self.description_edit)
        self._add_row(form, 5, "Uploaded Dir", self.uploaded_dir_edit)

        form.addWidget(self.dry_run_check, 6, 1)
        form.addWidget(self.publish_status_check, 7, 1)
        layout.addWidget(form_box)

        btns = QHBoxLayout()
        edit_map_btn = QPushButton("Edit Map")
        edit_map_btn.clicked.connect(self.edit_map)

        self.run_btn = QPushButton("Run Upload")
        self.run_btn.clicked.connect(self.run_upload)

        clear_btn = QPushButton("Clear Output")
        clear_btn.clicked.connect(self.clear_output)

        btns.addWidget(edit_map_btn)
        btns.addWidget(self.run_btn)
        btns.addWidget(clear_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Uploader output appears here...")
        layout.addWidget(self.output, 1)

        self.setCentralWidget(root)

    def _add_row(self, form: QGridLayout, row: int, label: str, edit: QLineEdit, browse_fn=None):
        form.addWidget(QLabel(label), row, 0)
        form.addWidget(edit, row, 1)
        if browse_fn:
            btn = QPushButton("Browse")
            btn.clicked.connect(browse_fn)
            form.addWidget(btn, row, 2)

    def append_output(self, text: str):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def clear_output(self):
        self.output.clear()

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose folder to read", str(BASE_DIR))
        if path:
            self.folder_edit.setText(path)

    def browse_map(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose product_type_map.json", str(BASE_DIR), "JSON (*.json);;All files (*)")
        if path:
            self.map_edit.setText(path)

    def edit_map(self):
        dlg = MapEditorDialog(self.map_edit.text().strip(), self)
        dlg.exec()

    def run_upload(self):
        folder = self.folder_edit.text().strip()
        map_path = self.map_edit.text().strip()

        if not folder:
            QMessageBox.warning(self, "Missing Folder", "Please choose a folder to read.")
            return
        if not map_path:
            QMessageBox.warning(self, "Missing Map", "Please choose a map file.")
            return

        cmd = [sys.executable, "-u", str(CLI_SCRIPT), "--folder", folder, "--product-type-map", map_path]

        uploaded_dir = self.uploaded_dir_edit.text().strip()
        if uploaded_dir:
            cmd += ["--uploaded-dir", uploaded_dir]

        vendor = self.vendor_edit.text().strip()
        if vendor:
            cmd += ["--vendor", vendor]

        price = self.price_edit.text().strip()
        if price:
            cmd += ["--price", price]

        description = self.description_edit.text().strip()
        if description:
            cmd += ["--description", description]

        if self.dry_run_check.isChecked():
            cmd.append("--dry-run")

        if self.publish_status_check.isChecked():
            cmd += ["--publish-status", "active"]
        else:
            cmd += ["--publish-status", "draft"]

        self.run_btn.setEnabled(False)
        self.append_output("\n$ " + " ".join(quote_arg(a) for a in cmd) + "\n\n")

        self.worker = UploaderWorker(cmd, BASE_DIR)
        self.worker.line.connect(self.append_output)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_done(self, code: int):
        self.append_output(f"\nProcess exited with code {code}\n")
        self.run_btn.setEnabled(True)
        self.worker = None

    def on_failed(self, message: str):
        self.append_output(f"\nFailed to run uploader: {message}\n")
        self.run_btn.setEnabled(True)
        self.worker = None


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--folder", default="", help="Optional folder to prefill in the GUI")
    parser.add_argument("--product-type-map", default="", help="Optional map path to prefill in the GUI")
    args = parser.parse_args()

    if not CLI_SCRIPT.exists():
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Missing Script", f"Could not find {CLI_SCRIPT}")
        return

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Simple, neutral palette for high readability.
    app.setStyleSheet(
        """
        QWidget { font-size: 13px; }
        QLineEdit, QTextEdit { background: #ffffff; color: #111827; border: 1px solid #9ca3af; border-radius: 4px; padding: 4px; }
        QPushButton { background: #e5e7eb; color: #111827; border: 1px solid #9ca3af; border-radius: 4px; padding: 6px 10px; }
        QPushButton:hover { background: #d1d5db; }
        QGroupBox { border: 1px solid #d1d5db; border-radius: 6px; margin-top: 8px; padding-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        """
    )

    win = MainWindow(folder=args.folder, map_path=args.product_type_map)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
