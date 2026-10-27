import unittest,tempfile
from pathlib import Path
from unittest.mock import Mock
from gongsi.assets import amount,change,config,check,menu
from gongsi.storage import Store

class AssetTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.s=Store(Path(t.name)/'db');self.addCleanup(self.s.close)
    def test_amounts_and_bounds_persist(self):
        self.assertEqual(amount('1.5조'),1500000000000)
        self.assertEqual(amount('5000'),500000000000)
        change(self.s,'min',100,0)
        self.assertEqual(config(self.s)['min'],100)
        with self.assertRaises(ValueError): change(self.s,'max',99,1)
        self.assertFalse(change(self.s,'max',1000,0))
    def test_disabled_never_queries(self):
        ex=Mock()
        self.assertEqual(check(ex,{},config(self.s)),(True,None))
        ex.json.assert_not_called()
    def test_menu_callbacks_fit_and_private_settings_not_reset(self):
        for field in (None,'min','max'):
            text,markup=menu(self.s,field)
            for row in markup['inline_keyboard']:
                for button in row: self.assertLessEqual(len(button['callback_data'].encode()),64)
