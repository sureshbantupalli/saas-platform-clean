class BaseAdapter:
    def send(self, to: str, message: str, subject: str = "") -> None:
        raise NotImplementedError
