import threading


class WorkerThread(threading.Thread):
    """A thread that runs a function or returns a result."""

    def __init__(self, func_or_result, name=None, daemon=True):
        # Store the original function/result
        self.func_or_result = func_or_result

        # If it's a function reference (not called), use it directly
        if callable(func_or_result):
            self.func = func_or_result
            func_name = func_or_result.__name__
        # If it's a result from a function call, create a lambda to return it
        else:
            self.func = lambda: self.func_or_result
            func_name = "lambda"

        super().__init__(name=f"{name}" if name is not None else f"{func_name}", daemon=daemon)

    def run(self):
        self.func()
