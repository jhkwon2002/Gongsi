import json
import unittest
from datetime import datetime,timezone,timedelta
from email.message import Message
from unittest.mock import Mock,patch
from gongsi.original_source import (decode_html,read_html,charset_name,OriginalSourceError,
                                   html_document,original_fields,failure)
from gongsi.storage import Store
from gongsi.extraction import Extractor

RECEIPT='20261029800841'
TABLE='<html><table><tr><td>양도목적</td><td>투자자금 회수</td></tr></table></html>'

class HtmlEncodingTests(unittest.TestCase):
    def test_aliases_resolve_only_to_approved_families(self):
        for value,expected in ((' UTF_8 ','utf-8'),('euc_kr','euc_kr'),
                               ('ms949','cp949'),('x-windows-949','cp949'),
                               ('windows-949','cp949'),('ks_c_5601-1987','euc_kr')):
            self.assertEqual(charset_name(value),expected)
        for value in ('utf-7','utf-16','unicode_escape','base64_codec','unknown','x'*100):
            self.assertIsNone(charset_name(value))

    def test_legacy_charset_alias_and_diagnostics(self):
        text=decode_html(TABLE.encode('cp949'),'ms949',{'page':'viewer'})
        self.assertEqual(str(text),TABLE)
        self.assertEqual(text.html_responses[0]['selected_encoding'],'cp949')
        self.assertEqual(text.html_responses[0]['header_charset'],'ms949')

    def test_meta_can_recover_unsupported_header_on_same_bytes(self):
        body='<html><meta charset="euc_kr">'+TABLE+'</html>'
        text=decode_html(body.encode('euc-kr'),'iso-8859-1')
        self.assertIn('투자자금 회수',text)
        self.assertEqual(text.html_responses[0]['encoding_source'],'meta')

    def test_supported_header_and_meta_try_strict_decoding(self):
        body='<html><meta charset="euc-kr">'+TABLE+'</html>'
        text=decode_html(body.encode('euc-kr'),'utf-8')
        self.assertIn('양도목적',text)
        self.assertTrue(text.html_responses[0]['declaration_conflict'])

    def test_ambiguous_decodings_do_not_choose_garbled_text(self):
        body=b'<html><meta charset="cp949">\xc2\xa1</html>'
        with self.assertRaises(OriginalSourceError) as caught:
            decode_html(body,'utf-8')
        self.assertEqual(caught.exception.reason,'ambiguous_encoding')

    def test_default_utf8_and_bom(self):
        self.assertEqual(str(decode_html(TABLE.encode('utf-8'))),TABLE)
        self.assertEqual(str(decode_html(b'\xef\xbb\xbf'+TABLE.encode('utf-8'),'cp949')),TABLE)
        fallback=decode_html(TABLE.encode('utf-8'),'iso-8859-1')
        self.assertEqual(fallback.html_responses[0]['encoding_source'],'utf8_fallback')

    def test_unmarked_legacy_bytes_and_invalid_bytes_are_not_guessed(self):
        for data in (TABLE.encode('cp949'),b'<html>\xff</html>'):
            with self.assertRaises(OriginalSourceError):
                decode_html(data)
        with self.assertRaises(OriginalSourceError):
            decode_html(TABLE.encode('utf-16'),'utf-16')

    def test_meta_in_comment_is_not_a_declaration(self):
        body='<html><!-- <meta charset="cp949"> -->'+TABLE+'</html>'
        result=decode_html(body.encode('utf-8'),'utf-8')
        self.assertEqual(result.html_responses[0]['meta_charsets'],[])

    def test_diagnostic_has_no_query_or_raw_body(self):
        response=Mock()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.geturl.return_value='https://dart.fss.or.kr/report/viewer.do?token=SECRET_SENTINEL'
        response.getcode.return_value=200
        headers=Message();headers['Content-Type']='text/html; charset=ms949'
        response.headers=headers;response.read.return_value=TABLE.encode('cp949')
        with patch('gongsi.original_source.urlopen',return_value=response) as opened:
            result=read_html(response.geturl())
        self.assertEqual(opened.call_count,1)
        info=result.html_responses[0]
        self.assertEqual(info['page'],'viewer')
        self.assertEqual(info['http_status'],200)
        self.assertNotIn('SECRET_SENTINEL',json.dumps(info))
        self.assertNotIn('투자자금',json.dumps(info,ensure_ascii=False))

    def test_non_html_content_and_bad_redirect_remain_rejected(self):
        response=Mock()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.geturl.return_value='https://dart.fss.or.kr/report/viewer.do'
        response.getcode.return_value=200
        headers=Message();headers['Content-Type']='application/pdf'
        response.headers=headers;response.read.return_value=b'%PDF-1.7'
        with patch('gongsi.original_source.urlopen',return_value=response):
            with self.assertRaises(OriginalSourceError) as caught:
                read_html(response.geturl())
        self.assertEqual(caught.exception.reason,'unexpected_content_type')
        with self.assertRaises(OriginalSourceError) as caught:
            decode_html(b'<result>error</result>','utf-8')
        self.assertEqual(caught.exception.reason,'not_html')
        response.geturl.return_value='https://example.com/'
        with patch('gongsi.original_source.urlopen',return_value=response):
            with self.assertRaises(OriginalSourceError):
                read_html('https://dart.fss.or.kr/report/viewer.do')

    def test_main_and_viewer_response_details_survive_success_and_failure(self):
        store=Store(':memory:');self.addCleanup(store.close)
        extractor=Extractor('SECRET_SENTINEL',store)
        main=decode_html(('<html><script>viewDoc("'+RECEIPT+
              '","123","0","0","0","HTML");</script></html>').encode(),'utf-8',{'page':'main'})
        body=decode_html(TABLE.encode('cp949'),'ms949',{'page':'viewer'})
        with patch('gongsi.original_source.read_html',side_effect=[main,body]):
            result=html_document(extractor,RECEIPT)
        self.assertEqual([x['page'] for x in result.html_responses],['main','viewer'])
        error=OriginalSourceError('html_decode','unsupported_encoding',[{'page':'viewer'}])
        with patch('gongsi.original_source.read_html',side_effect=[main,error]):
            with self.assertRaises(OriginalSourceError) as caught:
                html_document(extractor,RECEIPT)
        self.assertEqual([x['page'] for x in failure(caught.exception,'other')['html_responses']],
                         ['main','viewer'])

    def test_readonly_nhn_probe_is_bounded_and_never_sends(self):
        from gongsi.api_diagnostics import run_encoding_probe,ENCODING_KEY
        store=Store(':memory:');self.addCleanup(store.close)
        report={'corp_name':'NHN','report_nm':'타법인주식및출자증권처분결정',
                'rcept_no':RECEIPT,'rcept_dt':'20261029','corp_code':'00000001'}
        with store.tx() as db:
            db.execute('INSERT INTO reports VALUES (?,?)',(RECEIPT,json.dumps(report)))
        bot=Mock();bot.extractor=Extractor('SECRET_SENTINEL',store)
        now=datetime(2026,10,30,16,tzinfo=timezone(timedelta(hours=9)))
        with patch('gongsi.original_source.original_fields',return_value=[('양도목적','투자자금 회수')]) as original:
            run_encoding_probe(bot,store,now);run_encoding_probe(bot,store,now)
        self.assertEqual(original.call_count,1)
        self.assertTrue(store.get(ENCODING_KEY)['complete'])
        bot.send.assert_not_called()
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],0)
        store.set(ENCODING_KEY,{})
        with patch('gongsi.original_source.original_fields',side_effect=OSError()) as original:
            for minutes in (0,1,5,10,15,20):
                run_encoding_probe(bot,store,now+timedelta(minutes=minutes))
        self.assertEqual(original.call_count,3)
        with patch('gongsi.original_source.original_fields') as original:
            run_encoding_probe(bot,store,now+timedelta(days=3))
        original.assert_not_called()
