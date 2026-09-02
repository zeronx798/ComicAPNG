"""Qt Create-page reorder and context-menu regression tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QByteArray,
    QItemSelectionModel,
    QMimeData,
    QPointF,
    QSettings,
    Qt,
)
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QListView

import comicapng.ui.widgets.thumbnail_view as thumbnail_view_module
from comicapng.core.models import ComicBook, ComicPage
from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.pages.creator_page import CreatorPage
from comicapng.ui.widgets.thumbnail_view import INTERNAL_PAGE_MOVE_MIME


@contextmanager
def _creator(tmp_path: Path, labels: str = "ABCDE"):
    application = QApplication.instance() or QApplication([])
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    creator = CreatorPage(I18n("en"), settings, ThumbnailCache(tmp_path / "thumbnails"))
    pages: list[ComicPage] = []
    thumbnails: list[Path] = []
    for index, label in enumerate(labels):
        path = tmp_path / f"{label}.png"
        Image.new("RGBA", (32 + index, 48 - index), (index * 35, 40, 180, 255)).save(path)
        pages.append(ComicPage(path, None, 32 + index, 48 - index, is_cover=index == 0))
        thumbnails.append(path)
    creator._finish_source_book_load((ComicBook(pages=pages), thumbnails))
    creator.resize(900, 600)
    creator.show()
    application.processEvents()
    try:
        yield creator, application
    finally:
        creator.close()
        application.processEvents()


def _order(creator: CreatorPage) -> list[str]:
    return [
        page.source_path.stem
        for page in creator.book.pages
        if page.source_path is not None
    ]


def _action(creator: CreatorPage, page_id: str, operation: str):
    menu = creator._build_page_context_menu(page_id)
    action = next(
        item
        for item in menu.actions()
        if item.objectName() == f"create_page_{operation}"
    )
    return menu, action


def test_locally_imported_pages_use_the_same_arbitrary_move_path(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    settings = AppSettings(
        QSettings(str(tmp_path / "local-settings.ini"), QSettings.Format.IniFormat)
    )
    creator = CreatorPage(I18n("en"), settings, ThumbnailCache(tmp_path / "local-thumbnails"))
    imported: list[tuple] = []
    for index, label in enumerate("ABCD"):
        path = tmp_path / f"local-{label}.png"
        Image.new("RGBA", (30 + index, 40 + index), (index * 45, 30, 190, 255)).save(path)
        imported.append((path, 30 + index, 40 + index, "PNG", path))
    try:
        creator._finish_import((imported, []))
        creator.page_list.item(3).setSelected(True)
        creator.page_list.pages_move_requested.emit([3], 0)

        assert _order(creator) == ["local-D", "local-A", "local-B", "local-C"]
        assert all(type(page) is ComicPage for page in creator.book.pages)
    finally:
        creator.close()
        application.processEvents()


def test_drag_move_signal_supports_arbitrary_and_multi_page_moves(tmp_path: Path) -> None:
    with _creator(tmp_path) as (creator, application):
        final_id = creator.book.pages[4].page_id
        creator.page_list.item(4).setSelected(True)
        creator.page_list.pages_move_requested.emit([4], 1)
        application.processEvents()
        assert _order(creator) == ["A", "E", "B", "C", "D"]
        assert creator.page_list.item(1).isSelected()
        assert creator.book.pages[1].page_id == final_id

        creator.page_list.clearSelection()
        creator.page_list.item(0).setSelected(True)
        creator.page_list.pages_move_requested.emit([0], 4)
        application.processEvents()
        assert _order(creator) == ["E", "B", "C", "D", "A"]

        creator.page_list.clearSelection()
        creator.page_list.item(2).setSelected(True)
        creator.page_list.pages_move_requested.emit([2], 0)
        application.processEvents()
        assert _order(creator) == ["C", "E", "B", "D", "A"]

        creator.page_list.clearSelection()
        creator.page_list.item(1).setSelected(True)
        creator.page_list.item(3).setSelected(True)
        creator.page_list.pages_move_requested.emit([1, 3], 0)
        application.processEvents()
        assert _order(creator) == ["E", "D", "C", "B", "A"]
        assert sum(item.isSelected() for item in creator.page_list.findItems("*", Qt.MatchFlag.MatchWildcard)) == 2


def test_drag_drop_boundary_uses_before_and_after_item_halves(tmp_path: Path) -> None:
    with _creator(tmp_path) as (creator, _application):
        view = creator.page_list
        rectangle = view.visualItemRect(view.item(2))
        before = rectangle.center()
        after = rectangle.center()
        if view.flow() == QListView.Flow.LeftToRight:
            before.setX(rectangle.left() + 1)
            after.setX(rectangle.right() - 1)
        else:
            before.setY(rectangle.top() + 1)
            after.setY(rectangle.bottom() - 1)

        assert view.dragEnabled() is True
        assert view.acceptDrops() is True
        assert view.movement() == QListView.Movement.Snap
        assert view.drop_insertion_boundary(before) == 2
        assert view.drop_insertion_boundary(after) == 3


def test_internal_qt_drop_event_moves_last_page_to_the_beginning(tmp_path: Path) -> None:
    with _creator(tmp_path) as (creator, _application):
        view = creator.page_list
        view.clearSelection()
        view.item(4).setSelected(True)
        view.setCurrentItem(view.item(4))
        first_rectangle = view.visualItemRect(view.item(0))
        drop_position = first_rectangle.center()
        drop_position.setX(first_rectangle.left() + 1)
        mime_data = QMimeData()
        mime_data.setData(INTERNAL_PAGE_MOVE_MIME, QByteArray(b"1"))
        event = QDropEvent(
            QPointF(drop_position),
            Qt.DropAction.MoveAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        view.dropEvent(event)

        assert event.isAccepted() is True
        assert _order(creator) == ["E", "A", "B", "C", "D"]
        assert view.currentItem().data(Qt.ItemDataRole.UserRole) == creator.book.pages[0].page_id


def test_start_drag_marks_the_internal_page_payload(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeDrag:
        def __init__(self, parent) -> None:
            captured["parent"] = parent

        def setMimeData(self, mime_data) -> None:
            captured["mime_data"] = mime_data

        def setPixmap(self, pixmap) -> None:
            captured["pixmap"] = pixmap

        def setHotSpot(self, point) -> None:
            captured["hot_spot"] = point

        def exec(self, action) -> None:
            captured["action"] = action

    monkeypatch.setattr(thumbnail_view_module, "QDrag", FakeDrag)
    with _creator(tmp_path) as (creator, _application):
        view = creator.page_list
        view.clearSelection()
        view.item(1).setSelected(True)
        view.item(3).setSelected(True)
        view.setCurrentItem(view.item(3), QItemSelectionModel.SelectionFlag.NoUpdate)

        view.startDrag(Qt.DropAction.MoveAction)

        mime_data = captured["mime_data"]
        assert isinstance(mime_data, QMimeData)
        assert mime_data.hasFormat(INTERNAL_PAGE_MOVE_MIME)
        assert captured["parent"] is view
        assert captured["action"] == Qt.DropAction.MoveAction


def test_context_menu_actions_share_model_reorder_semantics(tmp_path: Path) -> None:
    with _creator(tmp_path, "ABCD") as (creator, _application):
        page_c = creator.book.pages[2]

        menu, action = _action(creator, page_c.page_id, "move_up")
        action.trigger()
        assert _order(creator) == ["A", "C", "B", "D"]
        menu.deleteLater()

        menu, action = _action(creator, page_c.page_id, "move_down")
        action.trigger()
        assert _order(creator) == ["A", "B", "C", "D"]
        menu.deleteLater()

        menu, action = _action(creator, page_c.page_id, "move_top")
        action.trigger()
        assert _order(creator) == ["C", "A", "B", "D"]
        menu.deleteLater()

        menu, action = _action(creator, page_c.page_id, "move_bottom")
        action.trigger()
        assert _order(creator) == ["A", "B", "D", "C"]
        assert creator.book.pages[-1] is page_c
        menu.deleteLater()

        assert [creator.page_list.item(row).text().split(".", 1)[0] for row in range(4)] == [
            "1",
            "2",
            "3",
            "4",
        ]


def test_context_menu_boundary_states(tmp_path: Path) -> None:
    with _creator(tmp_path, "ABCD") as (creator, _application):
        first_menu = creator._build_page_context_menu(creator.book.pages[0].page_id)
        first = {action.objectName(): action for action in first_menu.actions()}
        assert first["create_page_move_up"].isEnabled() is False
        assert first["create_page_move_top"].isEnabled() is False
        assert first["create_page_move_down"].isEnabled() is True
        assert first["create_page_move_bottom"].isEnabled() is True

        last_menu = creator._build_page_context_menu(creator.book.pages[-1].page_id)
        last = {action.objectName(): action for action in last_menu.actions()}
        assert last["create_page_move_up"].isEnabled() is True
        assert last["create_page_move_top"].isEnabled() is True
        assert last["create_page_move_down"].isEnabled() is False
        assert last["create_page_move_bottom"].isEnabled() is False


def test_context_click_preserves_selected_block_or_selects_clicked_page(tmp_path: Path) -> None:
    with _creator(tmp_path, "ABCD") as (creator, _application):
        first = creator.page_list.item(0)
        second = creator.page_list.item(1)
        third = creator.page_list.item(2)
        first.setSelected(True)
        third.setSelected(True)

        creator._prepare_context_item(third)
        assert creator.page_list.currentItem() is third
        assert creator.page_list.selectedItems() == [first, third]

        creator._prepare_context_item(second)
        assert creator.page_list.currentItem() is second
        assert creator.page_list.selectedItems() == [second]


def test_cover_marker_and_selection_follow_the_page_object(tmp_path: Path) -> None:
    with _creator(tmp_path, "ABCD") as (creator, _application):
        cover = creator.book.pages[0]
        creator.page_list.item(0).setSelected(True)

        creator.page_list.pages_move_requested.emit([0], 3)

        assert creator.book.pages[-1] is cover
        assert cover.is_cover is True
        assert creator.page_list.item(3).isSelected() is True
        assert creator.i18n.tr("creator.cover_suffix") in creator.page_list.item(3).text()
        assert creator.book.export_pages()[0] is cover
