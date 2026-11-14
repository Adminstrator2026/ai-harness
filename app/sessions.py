import threading, uuid, time
from queue import Queue, Empty

class AskWaiter:
    def __init__(self):
        self._q = Queue()
    def wait(self, timeout=600):
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None
    def resolve(self, value):
        self._q.put(value)

class Session:
    def __init__(self, sid):
        self.id = sid
        self.created = time.time()
        self.asks = {}
        self.lock = threading.Lock()

    def new_ask(self):
        aid = "ask_" + uuid.uuid4().hex[:10]
        with self.lock:
            w = AskWaiter()
            self.asks[aid] = w
        return aid, w

    def resolve_ask(self, aid, answers):
        with self.lock:
            w = self.asks.pop(aid, None)
        if w:
            w.resolve(answers)
            return True
        return False

SESSIONS = {}

def get_or_create(sid):
    if not sid:
        sid = "sess_" + uuid.uuid4().hex[:12]
    if sid not in SESSIONS:
        SESSIONS[sid] = Session(sid)
    return SESSIONS[sid]