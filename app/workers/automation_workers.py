"""Background prompt interpretation; no raw SDK exception or prompt logging."""
from PySide6.QtCore import QRunnable, QObject, Signal, Slot
from app.errors import AppError

class PromptSignals(QObject):
    finished = Signal(object)
    error = Signal(str)

class InterpretPromptWorker(QRunnable):
    def __init__(self, interpreter, prompt):
        super().__init__()
        self.interpreter, self.prompt = interpreter, prompt
        self.signals = PromptSignals()

    @Slot()
    def run(self):
        try:
            self.signals.finished.emit(self.interpreter.interpret(self.prompt))
        except Exception as error:
            message = getattr(error, 'user_message', '') if isinstance(error, AppError) else ''
            self.signals.error.emit(message or 'Không phân tích được prompt. Kiểm tra Gemini key, mô hình hoặc diễn đạt lại yêu cầu.')
