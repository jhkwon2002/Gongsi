"""Private Telegram command menu and paginated, persistent report buttons."""
from .catalog import CATALOG, BY_KEY, GROUPS, GROUP_BY_KEY, MAJOR_CHILDREN, MAJOR_PAGE
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

    def menu(self, page=-1):
        prefs = self.store.settings()
        selected = set(prefs['selected'])
        rev = prefs['revision']
        rows = []
        if page < 0:
            for index, (group_key, label, keys) in enumerate(GROUPS):
                if group_key=='major_detail':
                    continue
                count = len(selected.intersection(keys))
                if 'major' in keys and 'major' not in selected and selected.intersection(MAJOR_CHILDREN):
                    count += 1
                rows.append([{'text': f'{label} — {count}/{len(keys)}개 선택', 'callback_data': f'p:{index * 100}'}])
            text = f"보고서 분류를 선택하세요\n총 {len(selected)}개 선택 · " + ('일시정지' if prefs['paused'] else '감시 켜짐')
        else:
            group_index, offset = divmod(page, 100)
            if group_index >= len(GROUPS):
                return self.menu(-1)
            group_key, label, keys = GROUPS[group_index]
            pages = (len(keys) + PAGE_SIZE - 1) // PAGE_SIZE
            offset = min(offset, pages - 1)
            page = group_index * 100 + offset
            for key in keys[offset * PAGE_SIZE:(offset + 1) * PAGE_SIZE]:
                if key=='major' and group_key!='major_detail':
                    number=36 if 'major' in selected else len(selected.intersection(MAJOR_CHILDREN))
                    rows.append([{'text':f'주요사항보고서 ▶ {number}/36종 선택','callback_data':f'p:{MAJOR_PAGE}'}])
                    continue
                checked = key in selected or (key in MAJOR_CHILDREN and 'major' in selected)
                rows.append([{'text': ('☑ ' if checked else '☐ ') + BY_KEY[key].label,
                              'callback_data': f's:{key}:{0 if checked else 1}:{rev}:{page}'}])
            rows.append([{'text': '분류 전체 선택', 'callback_data': f'b:{group_key}:1:{rev}:{page}'},
                         {'text': '분류 전체 해제', 'callback_data': f'b:{group_key}:0:{rev}:{page}'}])
            nav = []
            if offset:
                nav.append({'text': '◀ 이전', 'callback_data': f'p:{page-1}'})
            if offset + 1 < pages:
                nav.append({'text': '다음 ▶', 'callback_data': f'p:{page+1}'})
            if nav:
                rows.append(nav)
            rows.append([{'text': '↩ 전체 분류', 'callback_data': 'p:-1'}])
            text = f'{label} ({offset+1}/{pages})\n체크하면 바로 저장됩니다. 중복 공시는 한 번만 보냅니다.\n새 선택은 이후 새로 발견되는 공시부터 적용되며 과거 공시를 재발송하지 않습니다.'
        if page>=MAJOR_PAGE:
            rows.append([{'text':'◀ 경영·계약','callback_data':'p:0'}])
            text+='\n전체 선택 시 모든 주요사항보고서를 받습니다. 전체 선택 상태에서 1종을 해제하면 나머지 35종 선택으로 전환됩니다. 다른 분류의 선택도 함께 적용됩니다.'
        rows.append([{'text': '전체 선택 해제', 'callback_data': f'c:{rev}:{page}'},
                     {'text': '현재 상태', 'callback_data': 'status'}])
        return text, {'inline_keyboard': rows}

    def show_menu(self, page=-1, message_id=None):
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
        sync = self.store.get('github_report_status',{}).get('status','not_checked')
        test = self.store.get('test_replay_last')
        test_status = (f"\n테스트 재전송: {test['sent']}/{test['requested']} · {test['status']}" if test else '')
        return ("전체 기업 DART 알림\n"
                f"감시: {'일시정지' if prefs['paused'] else '켜짐'}"
                f"\n선택: {', '.join(names) if names else '없음 — 메뉴에서 선택해주세요'}\n"
                f"조회 주기: {self.store.get('poll_seconds', 300)}초\n버전: {release}\n마지막 성공: {last}"
                + (f"\n최근 오류: {error}" if error else "") + test_status + "\nGitHub 결과 동기화: " + sync)

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
                elif parts[0] == 'b' and len(parts) == 5 and parts[1] in GROUP_BY_KEY and parts[2] in ('0', '1'):
                    page = int(parts[4])
                    changed = self.store.change_settings('set_group', parts[1], parts[2] == '1', int(parts[3]))
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

