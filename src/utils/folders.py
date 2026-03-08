from pathlib import Path


class CustomFolders(type):
    def __getattribute__(cls, name):
        value = super().__getattribute__(name)
        if isinstance(value, Path):
            return str(value)
        return value


class Folders(metaclass=CustomFolders):
    root = Path(__file__).parent.parent.parent
    models = root / "models"
    temp = root / "temp"
    log = root / "log"
