class Warehouse:
    def __init__(self):
        raise NotImplementedError

    def apply(self, events):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
