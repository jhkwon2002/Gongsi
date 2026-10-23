"""Private Telegram command menu and paginated, persistent report buttons."""
from .catalog import CATALOG, BY_KEY
from .api import ApiError

PAGE_SIZE = 6
COMMANDS = [
    {"command": "reports", "description": "받을 보고서 선택"},
    {"command": "status", "description": "선택 목록과 감시 상태"},
    {"command": "pause", "description": "알림 일시정지"},
    {"command": "resume", "description": "알림 다시 시작"},
]

class Bot:
    def __init__(self, telegram, store, owner_id):
        self.tg, self.store, self.owner_id = telegram, store, owner_id

    def register_menu(self):
        self.tg.call("setMyCommands", commands=COMMANDS,
                     scope={"type": "chat", "chat_id": self.owner_id})
        self.tg.call("setChatMenuButton", chat_id=self.owner_id, menu_button={"type": "commands"})

    def send(self, text, **kwargs):
        return self.tg.call("sendMessage", chat_id=self.owner_id, text=text,
                            link_preview_options={"is_disabled": True}, **kwargs)

    def menu(self, page=0):
        prefs = self.store.settings()
        pages = (len(CATALOG) + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(0, min(page, pages - 1))
        selected = set(prefs["selected"])
        rows = []
        for item in CATALOG[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
            checked = item.key in selected
            rows.append([{"text": ("✅ " if checked else "⬜ ") + item.label,
                          "callback_data": f"s:{item.key}:{0 if checked else 1}:{prefs['revision']}:{page}"}])
        nav = []
        if page:
            nav.append({"text": "◀ 이전", "callback_data": f"p:{page - 1}"})
        if page < pages - 1:
            nav.append({"text": "다음 ▶", "callback_data": f"p:{page + 1}"})
        if nav:
            rows.append(nav)
        rows.append([{"text": "전체 선택 해제", "callback_data": f"c:{prefs['revision']}:{page}"},
                     {"text": "선택 내역", "callback_data": "status"}])
        text = (f"받을 보고서 선택 ({page + 1}/{pages})\n"
                f"선택 {len(selected)}개 · {'일시정지' if prefs['paused'] else '알림 켜짐'}\n"
                "버튼을 누르면 바로 저장됩니다. 여러 개를 선택할 수 있습니다.\n"
                "새로 선택한 보고서는 다음 조회에서 새로 발견되는 공시부터 알립니다.\n"
                "‘전체’ 항목과 세부 항목이 겹쳐도 같은 공시는 한 번만 보냅니다.")
        return text, {"inline_keyboard": rows}

    def show_menu(self, page=0, message_id=None):
        text, markup = self.menu(page)
        if message_id is None:
            return self.send(text, reply_markup=markup)
        try:
            return self.tg.call("editMessageText", chat_id=self.owner_id,
                                message_id=message_id, text=text, reply_markup=markup)
        except ApiError as exc:
            if exc.code != "message_not_modified":
                raise

    def status(self):
        prefs = self.store.settings()
        names = [BY_KEY[key].label for key in prefs["selected"] if key in BY_KEY]
        last = self.store.get("last_scan_success", "아직 없음")
        error = self.store.get("last_scan_error", "")
        release = self.store.get("release", "local")[:12]
        return ("전체 기업 DART 알림\n"
                f"감시: {'일시정지' if prefs['paused'] else '켜짐'}"
                f"\n선택: {', '.join(names) if names else '없음 — 메뉴에서 선택해주세요'}\n"
                f"조회 주기: {self.store.get('poll_seconds', 300)}초\n버전: {release}\n마지막 성공: {last}"
                + (f"\n최근 오류: {error}" if error else ""))

    def handle(self, update):
        callback = update.get("callback_query")
        message = callback.get("message", {}) if callback else update.get("message", {})
        sender = (callback or message).get("from", {})
        chat = message.get("chat", {})
        # Private owner only. A forwarded message never authorizes its original sender.
        if sender.get("id") != self.owner_id or chat.get("id") != self.owner_id or chat.get("type") != "private":
            return
        if callback:
            data = callback.get("data", "")
            page = 0
            if data == "status":
                self.tg.call("answerCallbackQuery", callback_query_id=callback["id"])
                self.send(self.status())
                return
            try:
                parts = data.split(":")
                if parts[0] == "s" and len(parts) == 5 and parts[1] in BY_KEY and parts[2] in ("0", "1"):
                    page = int(parts[4])
                    changed = self.store.change_settings("set", parts[1], parts[2] == "1", int(parts[3]))
                elif parts[0] == "c" and len(parts) == 3:
                    page = int(parts[2])
                    changed = self.store.change_settings("clear", revision=int(parts[1]))
                elif parts[0] == "p" and len(parts) == 2:
                    page = int(parts[1])
                    changed = None
                else:
                    return
            except ValueError:
                return
            self.tg.call("answerCallbackQuery", callback_query_id=callback["id"],
                         text="저장했습니다" if changed else "선택 화면을 갱신합니다")
            self.show_menu(page, message["message_id"])
            return
        command = message.get("text", "").split(maxsplit=1)[0] if message.get("text") else ""
        command = command.split("@")[0]
        if command in ("/start", "/reports"):
            self.show_menu()
        elif command == "/status":
            self.send(self.status())
        elif command in ("/pause", "/resume"):
            self.store.change_settings(command[1:])
            self.send(self.status())

