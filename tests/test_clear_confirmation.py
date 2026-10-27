import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from gongsi.bot import Bot
from gongsi.catalog import MAJOR_PAGE
from gongsi.storage import Store

OWNER = 6766930417


class ClearConfirmationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / 'state.db')
        self.addCleanup(self.store.close)
        self.telegram = Mock()
        self.bot = Bot(self.telegram, self.store, OWNER)
        for key in ('major_piicDecsn', 'assets', 'annual'):
            self.store.change_settings('set', key, True)

    def callback(self, data, owner=OWNER):
        return {'callback_query': {
            'id': 'clear-test', 'data': data, 'from': {'id': owner},
            'message': {'message_id': 9, 'chat': {'id': OWNER, 'type': 'private'}},
        }}

    def buttons(self):
        return [button for row in self.telegram.call.call_args.kwargs['reply_markup']['inline_keyboard']
                for button in row]

    def open_confirmation(self, page):
        before = self.store.settings()
        self.bot.handle(self.callback(f"c:{before['revision']}:{page}"))
        self.assertEqual(self.store.settings(), before)
        buttons = self.buttons()
        for button in buttons:
            self.assertLessEqual(len(button['callback_data'].encode('utf-8')), 64)
        return {button['text']: button['callback_data'] for button in buttons}

    def test_clear_requires_confirmation_from_home_group_and_nested_pages(self):
        for page in (-1, 0, MAJOR_PAGE + 3):
            with self.subTest(page=page):
                buttons = self.open_confirmation(page)
                self.assertEqual(buttons['취소 · 선택 유지'], f'p:{page}')
                self.bot.handle(self.callback(buttons['해제 확인']))
                prefs = self.store.settings()
                self.assertEqual(prefs['selected'], [])
                self.assertFalse(prefs['paused'])
                self.assertTrue(any(b['callback_data'].startswith(f"c:{prefs['revision']}:")
                                    for b in self.buttons()))
                self.store.change_settings('set', 'major', True)
                self.store.change_settings('set', 'annual', True)

    def test_cancel_preserves_selection_and_returns_to_original_page(self):
        before = self.store.settings()
        buttons = self.open_confirmation(MAJOR_PAGE + 2)
        self.bot.handle(self.callback(buttons['취소 · 선택 유지']))
        self.assertEqual(self.store.settings(), before)
        self.assertEqual(self.telegram.call.call_args.kwargs['text'], self.bot.menu(MAJOR_PAGE + 2)[0])

    def test_old_confirmation_cannot_erase_new_selection(self):
        buttons = self.open_confirmation(-1)
        self.store.change_settings('set', 'cb', True)
        before = self.store.settings()
        self.bot.handle(self.callback(buttons['해제 확인']))
        self.assertEqual(self.store.settings(), before)
        self.assertFalse(any(b['callback_data'].startswith('cc:') for b in self.buttons()))

    def test_stale_original_clear_button_refreshes_without_confirmation(self):
        self.bot.handle(self.callback('c:0:-1'))
        self.assertEqual(len(self.store.settings()['selected']), 3)
        self.assertFalse(any(b['callback_data'].startswith('cc:') for b in self.buttons()))

    def test_confirmation_is_owner_only_and_duplicate_click_is_harmless(self):
        buttons = self.open_confirmation(-1)
        before = self.store.settings()
        self.bot.handle(self.callback(buttons['해제 확인'], owner=999))
        self.assertEqual(self.store.settings(), before)
        self.bot.handle(self.callback(buttons['해제 확인']))
        cleared = self.store.settings()
        self.bot.handle(self.callback(buttons['해제 확인']))
        self.assertEqual(self.store.settings(), cleared)


if __name__ == '__main__':
    unittest.main()
