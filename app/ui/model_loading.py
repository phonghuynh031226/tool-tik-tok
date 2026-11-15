"""Load Gemini model catalogs without blocking the Qt application thread."""

from PySide6.QtCore import QObject, QRunnable, QSignalBlocker, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from app.services.gemini import select_preferred_model


class _ModelSignals(QObject):
    loaded = Signal(object)


class _ModelWorker(QRunnable):
    def __init__(self, generator):
        super().__init__()
        self.generator = generator
        self.signals = _ModelSignals()

    def run(self):
        try:
            models = self.generator.list_models()
        except Exception:
            models = ["gemini-2.0-flash", "gemini-1.5-pro"]
        self.signals.loaded.emit(models)


class _ModelLoader(QObject):
    def __init__(self, combo, services, notify):
        super().__init__(combo)
        self.combo = combo
        self.services = services
        self.notify = notify
        self.worker = _ModelWorker(services.generator)
        self.worker.signals.loaded.connect(self.loaded)

    @Slot(object)
    def loaded(self, models):
        # A key change can request another catalog before this request finishes.
        if self.combo._model_loader is not self:
            self.deleteLater()
            return
        settings = self.services.settings
        saved = settings.get("gemini_model") if settings else None
        chosen, switched = select_preferred_model(models, saved)
        with QSignalBlocker(self.combo):
            self.combo.clear()
            for model in models:
                self.combo.addItem(model, model)
            index = self.combo.findData(chosen)
            if index >= 0:
                self.combo.setCurrentIndex(index)
        self.combo.setEnabled(True)
        if switched and saved and self.notify:
            if settings:
                settings.set("gemini_model", chosen)
            QMessageBox.information(
                self.combo.window(),
                "Cập nhật mô hình AI",
                f"Mô hình đã lưu '{saved}' không còn khả dụng trong danh sách Gemini. "
                f"Hệ thống đã tự động chuyển sang mô hình ưu tiên '{chosen}'.",
            )


def populate_models(combo, services, *, notify=True):
    """Keep saved selection visible while a production catalog loads in a worker."""
    loader = _ModelLoader(combo, services, notify)
    combo._model_loader = loader
    if type(services.generator).__module__ == "app.services.fakes":
        loader.worker.run()
        return
    saved = services.settings.get("gemini_model") if services.settings else None
    with QSignalBlocker(combo):
        combo.clear()
        combo.addItem(saved or "Đang tải mô hình AI…", saved)
    combo.setEnabled(False)
    QThreadPool.globalInstance().start(loader.worker)
