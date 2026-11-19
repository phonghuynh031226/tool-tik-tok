from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
from PySide6.QtWidgets import QTableWidget,QDialog
from app.contracts import JobStatus
from app.ui.pages.history_page import HistoryPage
from app.ui.services import ServiceContainer
from app.ui.state import JobState


def build(qtbot):
    services=ServiceContainer.create_fake()
    services.history.add(dict(video_id='source-pending',title='Pending title',youtube_video_id='p'*11,
        status=JobStatus.SCHEDULED,scheduled_at=datetime.now(timezone.utc)+timedelta(hours=1),
        privacy='private',channel_title='My channel'))
    services.history.add(dict(video_id='source-public',title='Public title',youtube_video_id='u'*11,
        status=JobStatus.UPLOADED,scheduled_at=datetime.now(timezone.utc)-timedelta(hours=1),
        privacy='public',schedule_public_confirmed=True))
    services.history.add(dict(video_id='source-failed',title='Failed title',status=JobStatus.FAILED))
    page=HistoryPage(JobState(),services)
    qtbot.addWidget(page)
    return page


def test_one_table_has_one_row_per_video_and_no_id_column(qtbot):
    page=build(qtbot)
    assert len(page.findChildren(QTableWidget))==1
    assert page.table.rowCount()==3
    assert [page.table.horizontalHeaderItem(i).text() for i in range(5)]==[
        'Tiêu đề video','Kênh YouTube','Giờ công khai','Trạng thái','YouTube']
    assert 'Còn' in next(page.table.item(i,2).text() for i in range(3) if page.table.item(i,0).text()=='Pending title')


def test_filters_use_confirmed_public_and_pending_status(qtbot):
    page=build(qtbot)
    for key,title in [('waiting','Pending title'),('public','Public title'),('failed','Failed title')]:
        page.combo_status.setCurrentIndex(page.combo_status.findData(key))
        assert page.table.rowCount()==1
        assert page.table.item(0,0).text()==title
    page.combo_status.setCurrentIndex(0)
    assert page.table.rowCount()==3


def test_title_click_details_contains_ids_without_opening_browser(qtbot,monkeypatch):
    page=build(qtbot)
    from app.ui.pages import history_page as module
    shown=[]
    def display(dialog):
        shown.append(dialog)
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(module.VideoDetailsDialog,'exec',display)
    page._show_video_details(0,0)
    assert len(shown)==1
    labels=' '.join(label.text() for label in shown[0].findChildren(module.QLabel))
    assert 'source-' in labels
    assert 'ID TikTok' in labels
    assert 'Đường dẫn file' in labels
