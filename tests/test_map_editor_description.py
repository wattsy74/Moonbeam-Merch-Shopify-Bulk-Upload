import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

import shopify_uploader_gui as gui_module

# The GUI preview uses WebEngine, which is not reliable in this headless environment.
# Keep the usable editor behavior covered by instantiating the dialog and asserting
# the source/preview sync logic without actually rendering the page.
class QWebEngineViewStub(gui_module.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._html = ""

    def setHtml(self, html, *args, **kwargs):
        self._html = html

    def setUrl(self, *args, **kwargs):
        return None

    def toHtml(self):
        return self._html


gui_module.QWebEngineView = QWebEngineViewStub

from shopify_uploader_gui import MapEditorDialog


class MapEditorDescriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_load_style_populates_rich_description_editor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "map.json"
            map_path.write_text("{}", encoding="utf-8")

            dialog = MapEditorDialog(str(map_path))
            dialog.map_data = {"STYLE1": {"description": "<p>Hello <b>world</b></p>"}}

            dialog.load_style("STYLE1")

            self.assertEqual(dialog.description_source_edit.toPlainText().strip(), "<p>Hello <b>world</b></p>")
            self.assertIn("Hello", dialog.description_preview.toHtml())

    def test_clone_description_file_creates_new_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "map.json"
            map_path.write_text("{}", encoding="utf-8")
            template_path = Path(temp_dir) / "template.html"
            template_path.write_text("<p>template content</p>", encoding="utf-8")

            dialog = MapEditorDialog(str(map_path))
            dialog._clone_from_test = True
            dialog._description_source_path = template_path
            dialog.desc_file_edit.setText(str(template_path))
            dialog.description_source_edit.setPlainText("<p>edited content</p>")

            cloned_path = Path(temp_dir) / "cloned.html"
            dialog._clone_description_file(cloned_path)

            self.assertTrue(cloned_path.exists())
            self.assertEqual(cloned_path.read_text(encoding="utf-8"), "<p>edited content</p>")
            self.assertEqual(dialog._description_source_path, cloned_path.resolve())
            self.assertIn("cloned.html", dialog.desc_file_edit.text())

    def test_clone_description_file_accepts_button_checked_signal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "map.json"
            map_path.write_text("{}", encoding="utf-8")

            dialog = MapEditorDialog(str(map_path))
            dialog._clone_from_test = True
            dialog.description_source_edit.setPlainText("<p>from button</p>")
            cloned_path = Path(temp_dir) / "button_clone.html"

            with patch("shopify_uploader_gui.QFileDialog.getSaveFileName", return_value=(str(cloned_path), "")):
                result = dialog._clone_description_file(False)

            self.assertEqual(result, cloned_path.resolve())
            self.assertTrue(cloned_path.exists())


if __name__ == "__main__":
    unittest.main()
