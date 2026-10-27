import tempfile
import unittest
from pathlib import Path
from gongsi.catalog import MAJOR_SCHEMAS,MAJOR_CHILDREN,MAJOR_PAGE,matches,matching_keys
from gongsi.storage import Store
from gongsi.bot import Bot

class MajorMenuTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db');self.addCleanup(self.store.close)
        self.bot=Bot(None,self.store,6766930417)
    def test_all_36_child_filters_are_scoped_and_distinct(self):
        self.assertEqual(len(MAJOR_CHILDREN),36)
        for schema in MAJOR_SCHEMAS:
            child='major_'+schema['endpoint']
            title='주요사항보고서('+schema['title']+')'
            with self.subTest(child=child):
                self.assertTrue(matches('[기재정정]'+title,[child]))
                self.assertFalse(matches(schema['title'],[child]))
                self.assertEqual(set(MAJOR_CHILDREN).intersection(matching_keys(title)),{child})
    def test_business_parent_opens_submenu_instead_of_toggling_all(self):
        _,markup=self.bot.menu(0)
        buttons=[b for row in markup['inline_keyboard'] for b in row]
        self.assertTrue(any(b['callback_data']==f'p:{MAJOR_PAGE}' for b in buttons))
        self.assertFalse(any(b['callback_data'].startswith('s:major:') for b in buttons))
    def test_old_whole_selection_preserved_and_child_uncheck_expands_other_35(self):
        self.store.change_settings('set','major',True)
        child='major_piicDecsn'
        _,markup=self.bot.menu(MAJOR_PAGE)
        self.assertTrue(any(b['callback_data'].startswith('s:major:0:') for row in markup['inline_keyboard'] for b in row))
        self.store.change_settings('set',child,False)
        selected=self.store.settings()['selected']
        self.assertNotIn('major',selected);self.assertNotIn(child,selected)
        self.assertEqual(len(selected),35)
        self.assertFalse(matches('주요사항보고서(유상증자결정)',selected))
        self.assertTrue(matches('주요사항보고서(회사합병결정)',selected))
    def test_select_whole_compresses_children_and_deselect_clears_family_only(self):
        self.store.change_settings('set','major_piicDecsn',True)
        self.store.change_settings('set','assets',True)
        self.store.change_settings('set','major',True)
        self.assertEqual(set(self.store.settings()['selected']),{'major','assets'})
        self.store.change_settings('set','major',False)
        self.assertEqual(self.store.settings()['selected'],['assets'])
    def test_group_bulk_clear_preserves_unrelated_selection(self):
        self.store.change_settings('set','assets',True)
        self.store.change_settings('set_group','major_detail',True)
        self.assertEqual(set(self.store.settings()['selected']),{'assets','major'})
        self.store.change_settings('set_group','major_detail',False)
        self.assertEqual(self.store.settings()['selected'],['assets'])
    def test_stale_child_callback_does_not_change_selection(self):
        self.store.change_settings('set','major',True)
        self.assertFalse(self.store.change_settings('set','major_piicDecsn',False,revision=0))
        self.assertEqual(self.store.settings()['selected'],['major'])
    def test_all_children_reachable_with_safe_callback_lengths(self):
        found=set()
        for offset in range(7):
            _,markup=self.bot.menu(MAJOR_PAGE+offset)
            for row in markup['inline_keyboard']:
                for b in row:
                    self.assertLessEqual(len(b['callback_data'].encode()),64)
                    if b['callback_data'].startswith('s:major_'):
                        found.add(b['callback_data'].split(':')[1])
        self.assertEqual(found,set(MAJOR_CHILDREN))