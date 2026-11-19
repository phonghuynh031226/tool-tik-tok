from unittest.mock import Mock
from PySide6.QtCore import Qt
from app.contracts import ChannelAccount, ChannelStats, VideoStats
from app.ui.pages.youtube_channels_page import YouTubeChannelsPage, AccountCardWidget
from app.ui.services import ServiceContainer
from app.ui.state import JobState


def test_compact_channels_and_separate_details(qtbot, monkeypatch):
    monkeypatch.setattr(YouTubeChannelsPage, '_load_accounts', lambda self: None)
    page = YouTubeChannelsPage(JobState(), ServiceContainer.create_fake())
    qtbot.addWidget(page)
    page.thread_pool = Mock()
    accounts = [ChannelAccount(id='a', title='Channel A', is_default=True), ChannelAccount(id='b', title='Channel B')]
    page._on_accounts_loaded(accounts)
    page.resize(1100, 800)
    page.show()
    assert page._selected_account is None
    assert page.details_placeholder.isVisible()
    assert page.tbl_videos.isHidden()
    page._on_stats_loaded(ChannelStats(channel_id='a', subscribers=123, total_views=456, video_count=7))
    assert '123' in page._card_widgets[0].lbl_metrics.text()
    assert '456' in page._card_widgets[0].lbl_metrics.text()
    qtbot.wait(30)
    before = [c.geometry() for c in page._card_widgets]
    qtbot.mouseClick(page._card_widgets[0], Qt.MouseButton.LeftButton)
    assert page._selected_account.id == 'a'
    assert not page.tbl_videos.isHidden()
    assert [c.geometry() for c in page._card_widgets] == before
    page._select_account(accounts[1])
    page._on_channel_videos_loaded('a', [VideoStats(video_id='old')])
    assert page.tbl_videos.rowCount() == 0
    page._on_channel_videos_loaded('b', [VideoStats(video_id='new')])
    assert page.tbl_videos.item(0, 0).text() == 'new'
    assert not any(b.text() in ('Làm mới', 'Mở video trên YouTube') for b in page.findChildren(__import__('PySide6.QtWidgets', fromlist=['QPushButton']).QPushButton))


def test_avatar_image_and_menu(qtbot):
    from PySide6.QtGui import QPixmap
    card = AccountCardWidget(ChannelAccount(id='a', title='Channel A'))
    qtbot.addWidget(card)
    image = QPixmap(80, 80)
    image.fill(Qt.GlobalColor.red)
    card._set_avatar(image)
    assert not card.lbl_avatar.pixmap().isNull()
    assert card.btn_menu.menu() is not None


def test_thumbnail_request_decodes_logo_and_failed_image_keeps_fallback(qtbot, monkeypatch):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QPixmap
    from PySide6.QtNetwork import QNetworkReply
    from app.ui.pages import youtube_channels_page as module
    reply = Mock()
    manager = Mock()
    manager.get.return_value = reply
    monkeypatch.setattr(module, 'QNetworkAccessManager', lambda parent: manager)
    card = AccountCardWidget(ChannelAccount(id='logo', title='Logo', thumbnail_url='https://yt3.ggpht.com/logo.png'))
    qtbot.addWidget(card)
    assert manager.get.call_args.args[0].url().host() == 'yt3.ggpht.com'
    image = QPixmap(80, 80)
    image.fill(Qt.GlobalColor.blue)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    reply.error.return_value = QNetworkReply.NetworkError.NoError
    reply.readAll.return_value = data
    card._avatar_finished(reply)
    assert not card.lbl_avatar.pixmap().isNull()
    failed = AccountCardWidget(ChannelAccount(id='missing', title='Missing'))
    qtbot.addWidget(failed)
    reply.error.return_value = QNetworkReply.NetworkError.ContentNotFoundError
    failed._avatar_finished(reply)
    assert failed.lbl_avatar.text() == 'M'


def test_long_title_keeps_actions_inside_row(qtbot):
    card = AccountCardWidget(ChannelAccount(id='long', title='Long channel name ' * 20))
    qtbot.addWidget(card)
    card.resize(650, 84)
    card.show()
    qtbot.wait(30)
    assert card.lbl_title.text() != card.account.title
    assert card.btn_menu.geometry().right() < card.width()
    assert card.lbl_title.toolTip().startswith(card.account.title)


def test_account_reload_removes_old_rows_and_stats_error_is_visible(qtbot, monkeypatch):
    monkeypatch.setattr(YouTubeChannelsPage, '_load_accounts', lambda self: None)
    page = YouTubeChannelsPage(JobState(), ServiceContainer.create_fake())
    qtbot.addWidget(page)
    page.thread_pool = Mock()
    page._on_accounts_loaded([ChannelAccount(id='old', title='Old')])
    page._on_accounts_loaded([ChannelAccount(id='new', title='New')])
    assert page.accounts_container.count() == 1
    page._on_row_stats_error('new')
    assert page._card_widgets[0].lbl_metrics.text() == 'Chưa tải được thống kê'
