class BaseAdapter:
    def send(self, to: str, message: str, subject: str = "", text: str = "") -> None:
        raise NotImplementedError
