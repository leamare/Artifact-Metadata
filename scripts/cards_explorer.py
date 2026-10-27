#!/usr/bin/env python3
"""Cards explorer: browse every card of Classic, Foundry and Reborn with its rendered face,
text in any language, data, balance history and chat wheel lines.

    python3 scripts/cards_explorer.py [--game foundry] [--lang russian] [--card 10001]

Needs PySide6 (or PyQt6 + PyQt6-WebEngine): pip install -r requirements.txt. Card faces are drawn by ui/render, so they need the game
assets in ui/assets/ (scripts/extract_assets.py); "Save PNG" also needs Chrome/Chromium
(the same screenshots as scripts/render_cards.py).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QSize, QSortFilterProxyModel, Qt, QUrl
    from PySide6.QtGui import QColor, QIcon, QPixmap, QStandardItem, QStandardItemModel
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                                   QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                                   QMessageBox, QPushButton, QSplitter, QTableView, QTabWidget, QTextBrowser,
                                   QVBoxLayout, QWidget)
except ImportError:
    try:
        from PyQt6.QtCore import QSize, QSortFilterProxyModel, Qt, QUrl
        from PyQt6.QtGui import QColor, QIcon, QPixmap, QStandardItem, QStandardItemModel
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                                     QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                                     QMessageBox, QPushButton, QSplitter, QTableView, QTabWidget, QTextBrowser,
                                     QVBoxLayout, QWidget)
    except ImportError:
        sys.exit('The cards explorer needs Qt for Python with QtWebEngine:\n'
                 '    pip install PySide6        (or: pip install PyQt6 PyQt6-WebEngine)')

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from compare_render import serve  # noqa: E402

GAMES = ('classic', 'foundry', 'reborn')
FILES = ('heroes', 'creeps', 'spells', 'improvements', 'items', 'abilities', 'mutations', 'default', 'other')
FACE_TYPES = {2, 3, 4, 5, 6, 7, 8, 9}   # abilities: drawn with their mini icon
COLUMNS = ('ID', 'Name', 'Type', 'Colour', 'Rarity', 'Set', 'Cost', 'Attack', 'Armor', 'Health')
SORT_ROLE = Qt.ItemDataRole.UserRole.value   # roles as ints work with PySide6 and PyQt6
TYPE_ROLE = SORT_ROLE + 1
TYPES = {int(k): v for k, v in json.loads((ROOT / 'commons/card_types.json').read_text()).items()}


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)


class Game:
    """One game folder: card records, localization, history, chat wheel."""

    def __init__(self, name: str):
        self.name = name
        base = ROOT / name
        self.cards = load(base / 'cards.json')
        self.details = {}
        for f in FILES:
            self.details.update(load(base / f'{f}.json'))
        self.history = load(base / 'history.json')
        self.chat_wheel = load(base / 'chat_wheel.json')
        self.text = load(base / 'cards_text.json')   # English text for cards the localization lacks
        self.languages = sorted(p.stem for p in (base / 'localization').glob('*.json'))
        self.loc = {}

    def art(self, kind: str, cid: str):
        """Path of a card's art (full_art, mini_icons, hero_icons) in ui/assets/, or None."""
        ids = [str(self.details.get(cid, {}).get('artwork', {}).get('artwork_id', cid)), cid]
        for game in (self.name, 'classic'):
            for i in ids:
                p = ROOT / 'ui/assets' / game / 'art' / kind / f'{i}.png'
                if p.exists():
                    return p
        return None

    def has_face(self, cid: str):
        return self.cards.get(cid, {}).get('type') in FACE_TYPES and bool(self.art('full_art', cid) or self.art('mini_icons', cid))

    def localization(self, lang: str):
        if lang not in self.loc:
            self.loc[lang] = load(ROOT / self.name / 'localization' / f'{lang}.json', {'cards': {}, 'voice_lines': {}})
        return self.loc[lang]


def cell(value, numeric=False):
    """A table cell; SORT_ROLE is its sort key (numbers sort as numbers, blanks first)."""
    item = QStandardItem('' if value is None else str(value))
    if numeric:
        item.setData(float(value) if isinstance(value, (int, float)) else -1e9, SORT_ROLE)
    else:
        item.setData(str(value or '').lower(), SORT_ROLE)
    item.setEditable(False)
    return item


class Filter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.text = ''
        self.type = None
        self.colour = ''
        self.faces_only = False

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel()
        get = lambda col: m.item(row, col).text()
        if self.type is not None and get(2) != TYPES.get(self.type, ''):
            return False
        if self.colour and get(3) != self.colour:
            return False
        if self.faces_only and not m.item(row, 0).data(TYPE_ROLE + 1):
            return False
        return not self.text or self.text in get(0) or self.text in get(1).lower()


class Explorer(QMainWindow):
    def __init__(self, game: str, lang: str, card: str | None):
        super().__init__()
        self.setWindowTitle('Artifact cards explorer')
        self.resize(1500, 950)
        self.server = serve()
        self.port = self.server.server_address[1]
        self.games = {}
        self.current = None

        # toolbar row
        self.game_box = QComboBox()
        self.game_box.addItems(GAMES)
        self.lang_box = QComboBox()
        self.type_box = QComboBox()
        self.type_box.addItem('all types', None)
        for t, name in sorted(TYPES.items(), key=lambda kv: kv[1]):
            self.type_box.addItem(name, t)
        self.colour_box = QComboBox()
        self.colour_box.addItems(['all colours', 'Red', 'Green', 'Blue', 'Black'])
        self.faces = QCheckBox('with a card face')
        self.search = QLineEdit()
        self.search.setPlaceholderText('name or id')
        self.count = QLabel()
        top = QHBoxLayout()
        for w in (QLabel('Game'), self.game_box, QLabel('Language'), self.lang_box, self.type_box,
                  self.colour_box, self.faces, self.search):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.count)

        # card list
        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = Filter()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setIconSize(QSize(28, 28))
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 190)

        # card face
        self.view = QWebEngineView()
        self.view.setMinimumSize(300, 500)
        self.view.page().setBackgroundColor(QColor('#1c1c1c'))
        self.mode = QComboBox()
        self.mode.addItem('Card face', 'face')
        self.mode.addItem('Small preview', 'mini')
        self.art_box = QComboBox()
        self.compare = QCheckBox("overlay Valve's render")
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.25, 8)
        self.scale.setSingleStep(0.5)
        self.scale.setValue(1)
        self.scale.setSuffix('x')
        save = QPushButton('Save PNG…')
        face_bar = QHBoxLayout()
        for w in (self.mode, QLabel('Artwork'), self.art_box, self.compare, QLabel('Scale'), self.scale, save):
            face_bar.addWidget(w)
        face_bar.addStretch(1)
        face = QWidget()
        fl = QVBoxLayout(face)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addLayout(face_bar)
        fl.addWidget(self.view, 1)

        # details
        self.text = QTextBrowser()
        self.data = QTextBrowser()
        self.history = QTextBrowser()
        self.voice = QTextBrowser()
        self.related = QListWidget()
        tabs = QTabWidget()
        tabs.addTab(self.text, 'Text')
        tabs.addTab(self.related, 'Related cards')
        tabs.addTab(self.data, 'Data')
        tabs.addTab(self.history, 'History')
        tabs.addTab(self.voice, 'Chat wheel')

        right = QSplitter(Qt.Orientation.Horizontal)
        right.addWidget(face)
        right.addWidget(tabs)
        right.setSizes([560, 520])
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        split.addWidget(right)
        split.setSizes([640, 860])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        self.setCentralWidget(central)

        self.game_box.currentTextChanged.connect(self.load_game)
        self.lang_box.currentTextChanged.connect(self.reload_language)
        self.type_box.currentIndexChanged.connect(self.refilter)
        self.colour_box.currentIndexChanged.connect(self.refilter)
        self.faces.toggled.connect(self.refilter)
        self.search.textChanged.connect(self.refilter)
        self.table.selectionModel().currentRowChanged.connect(self.selected)
        self.art_box.currentIndexChanged.connect(self.draw)
        self.mode.currentIndexChanged.connect(self.draw)
        self.compare.toggled.connect(self.draw)
        self.related.itemDoubleClicked.connect(lambda it: self.select(it.data(SORT_ROLE)))
        self.view.loadFinished.connect(self.fit_view)
        save.clicked.connect(self.save_png)

        self.wanted_lang = lang
        self.game_box.setCurrentText(game)
        self.load_game(game)
        if card:
            self.select(card)

    # data ---------------------------------------------------------------
    @property
    def game(self) -> Game:
        name = self.game_box.currentText()
        if name not in self.games:
            self.games[name] = Game(name)
        return self.games[name]

    @property
    def lang(self) -> str:
        return self.lang_box.currentText() or 'english'

    def name_of(self, cid):
        loc = self.game.localization(self.lang)['cards'].get(str(cid), {})
        return loc.get('name') or self.game.cards.get(str(cid), {}).get('name', '')

    def load_game(self, _=None):
        game = self.game
        self.lang_box.blockSignals(True)
        want = self.wanted_lang or self.lang
        self.lang_box.clear()
        self.lang_box.addItems(game.languages)
        self.lang_box.setCurrentText(want if want in game.languages else 'english')
        self.lang_box.blockSignals(False)
        self.wanted_lang = None
        self.fill()

    def reload_language(self, _=None):
        keep = self.current
        self.fill()
        if keep:
            self.select(keep)

    def fill(self):
        game = self.game
        self.model.removeRows(0, self.model.rowCount())
        self.table.setSortingEnabled(False)
        for cid, entry in game.cards.items():
            d = game.details.get(cid, {})
            cost = d.get('gold_cost') if d.get('type') == 5 else d.get('mana_cost')
            row = [cell(int(cid), True), cell(self.name_of(cid)), cell(TYPES.get(entry['type'], entry['type'])),
                   cell(d.get('color')), cell(d.get('rarity')), cell(d.get('set'), True), cell(cost, True),
                   cell(d.get('attack'), True), cell(d.get('armor'), True), cell(d.get('health'), True)]
            row[0].setData(entry['type'], TYPE_ROLE)
            row[0].setData(game.has_face(cid), TYPE_ROLE + 1)
            icon = game.art('mini_icons', cid) or game.art('hero_icons', cid)
            if icon:
                row[0].setIcon(QIcon(QPixmap(str(icon))))
            self.model.appendRow(row)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.refilter()

    def refilter(self, *_):
        self.proxy.text = self.search.text().strip().lower()
        self.proxy.type = self.type_box.currentData()
        self.proxy.colour = '' if self.colour_box.currentIndex() == 0 else self.colour_box.currentText()
        self.proxy.faces_only = self.faces.isChecked()
        self.proxy.invalidateFilter()
        self.count.setText(f'{self.proxy.rowCount()} / {self.model.rowCount()} cards')

    def select(self, cid):
        cid = str(cid)
        for row in range(self.proxy.rowCount()):
            if self.proxy.index(row, 0).data() == cid:
                self.table.selectRow(row)
                self.table.scrollTo(self.proxy.index(row, 0))
                return
        if cid in self.game.cards:   # filtered out: clear the filters and retry
            self.search.clear()
            self.type_box.setCurrentIndex(0)
            self.colour_box.setCurrentIndex(0)
            self.faces.setChecked(False)
            self.select(cid)

    # selection ----------------------------------------------------------
    def selected(self, index, _prev=None):
        if not index.isValid():
            return
        cid = self.proxy.index(index.row(), 0).data()
        self.current = cid
        game = self.game
        d = game.details.get(cid, {'id': int(cid), **game.cards.get(cid, {})})
        loc = {**game.text.get(cid, {}), **game.localization('english')['cards'].get(cid, {}),
               **game.localization(self.lang)['cards'].get(cid, {})}

        self.art_box.blockSignals(True)
        self.art_box.clear()
        art = d.get('artwork', {})
        self.art_box.addItem(f"base ({art.get('artwork_id', cid)})", None)
        for alt in art.get('alternate_artwork_ids', []):
            self.art_box.addItem(f'alternate {alt}', alt)
        self.art_box.blockSignals(False)
        self.compare.setEnabled(game.name == 'classic')

        esc = lambda s: str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        html = f"<h2>{esc(loc.get('name') or d.get('name', ''))}</h2>"
        html += f"<p><i>{esc(TYPES.get(d.get('type'), ''))}</i></p>"
        if loc.get('text_plain'):
            html += f"<p>{esc(loc['text_plain'])}</p>"
        if loc.get('lore'):
            html += f"<p style='color:#888'><i>{esc(loc['lore'])}</i></p>"
        for key in ('effects', 'modifications'):
            if loc.get(key):
                html += f"<h4>{key}</h4><pre>{esc(json.dumps(loc[key], ensure_ascii=False, indent=1))}</pre>"
        self.text.setHtml(html)
        self.data.setPlainText(json.dumps(d, ensure_ascii=False, indent=2))
        hist = game.history.get(cid)
        self.history.setPlainText(json.dumps(hist, ensure_ascii=False, indent=2) if hist else 'no balance changes')
        voice = game.localization(self.lang).get('voice_lines', {})
        lines = game.chat_wheel.get(cid, [])
        self.voice.setHtml(''.join(f"<p><b>{esc(v)}</b><br>{esc(voice.get(v, ''))}</p>" for v in lines)
                           or 'no chat wheel lines')

        self.related.clear()
        refs = []
        for key in ('abilities', 'ability_of', 'signature_of', 'references', 'referenced_by', 'related_cards'):
            for r in d.get(key, []) or []:
                refs.append((key, r.get('card_id') if isinstance(r, dict) else r))
        for s in d.get('signature', []) or []:
            refs.append(('signature', s.get('card_id')))
        for key, rid in refs:
            if rid is None:
                continue
            it = QListWidgetItem(f'{key}: {rid} {self.name_of(rid)}')
            it.setData(SORT_ROLE, str(rid))
            self.related.addItem(it)
        self.draw()

    def size_of(self):
        return (267, 267) if self.mode.currentData() == 'mini' else (526, 890)

    def url(self, cid, art=None):
        u = f'http://127.0.0.1:{self.port}/ui/render/render.html?game={self.game.name}&id={cid}&lang={self.lang}'
        if art:
            u += f'&art={art}'
        if self.mode.currentData() == 'mini':
            u += '&kind=mini'
        elif self.compare.isChecked() and self.game.name == 'classic':
            u += '&compare=1'
        return u

    def draw(self, *_):
        cid = self.current
        if not cid:
            return
        if not self.game.has_face(cid):
            self.view.setHtml('<body style="background:#1c1c1c;color:#888;font:16px sans-serif">'
                              'This card has no card face (no art; mutations are rules, not cards).</body>')
            return
        self.view.load(QUrl(self.url(cid, self.art_box.currentData())))
        self.fit_view()

    def fit_view(self, _ok=True):
        size = self.view.size()
        w, h = self.size_of()
        self.view.setZoomFactor(max(0.25, min(size.width() / (w + 4), size.height() / (h + 4))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_view()

    def save_png(self):
        cid = self.current
        if not cid or not self.game.has_face(cid):
            return
        art = self.art_box.currentData()
        name = (f'{cid}_{art}' if art else cid) + ('_preview' if self.mode.currentData() == 'mini' else '') + '.png'
        path, _ = QFileDialog.getSaveFileName(self, 'Save card image', str(Path.home() / name), 'PNG (*.png)')
        if not path:
            return
        from PIL import Image
        from cdp import Browser
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with Browser() as b:
                png = b.screenshot(self.url(cid, art).replace('&compare=1', ''), *self.size_of(), scale=self.scale.value())
            Image.open(io.BytesIO(png)).save(path, optimize=True)
        except Exception as e:  # Chrome missing, timeout...
            QMessageBox.warning(self, 'Save PNG', str(e))
        finally:
            QApplication.restoreOverrideCursor()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', choices=GAMES, default='classic')
    ap.add_argument('--lang', default='english')
    ap.add_argument('--card')
    args = ap.parse_args()
    app = QApplication(sys.argv[:1])
    win = Explorer(args.game, args.lang, args.card)
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
