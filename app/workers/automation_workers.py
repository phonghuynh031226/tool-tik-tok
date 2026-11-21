"""Background prompt interpretation; no raw SDK exception or prompt logging."""
from PySide6.QtCore import QRunnable, QObject, Signal, Slot
from app.core.cancel import CancelToken
from app.errors import AppError
from app.workers.base import register_worker, tracked_run

class PromptSignals(QObject):
    finished = Signal(object)
    error = Signal(str)

class InterpretPromptWorker(QRunnable):
    def __init__(self, interpreter, prompt):
        super().__init__()
        self.interpreter, self.prompt = interpreter, prompt
        self.signals = PromptSignals()
        self.cancel_token = CancelToken()
        self.setAutoDelete(True)
        register_worker(self)

    def cancel(self):
        self.cancel_token.cancel()

    @Slot()
    @tracked_run
    def run(self):
        if self.cancel_token.is_cancelled:
            return
        try:
            res = self.interpreter.interpret(self.prompt)
            if not self.cancel_token.is_cancelled:
                self.signals.finished.emit(res)
        except Exception as error:
            message = getattr(error, 'user_message', '') if isinstance(error, AppError) else ''
            self.signals.error.emit(message or 'Không phân tích được prompt. Kiểm tra Gemini key, mô hình hoặc diễn đạt lại yêu cầu.')
