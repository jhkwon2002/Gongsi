"""Bounded same-filing HTML fallback; no JavaScript execution or guessed IDs."""
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_PAGE = 4 * 1024 * 1024


class OriginalSourceError(ValueError):
    def __init__(self, stage, reason):
        self.stage, self.reason = stage, reason
        super().__init__(reason)


def failure(exc, stage):
    """Export fixed codes only; exception strings may contain credentials."""
    codes = {
        'DART original document unavailable': ('document_api', 'not_zip'),
        'Document exceeds download budget': ('document_download', 'size_limit'),
        'Document exceeds memory budget': ('archive', 'size_limit'),
        'Main document cannot be identified safely': ('archive', 'ambiguous_main'),
        'Unsupported document encoding': ('document_decode', 'unsupported_encoding'),
        'Entity declarations are unsupported': ('table', 'entity_declaration'),
        'Unclosed table cannot be interpreted safely': ('table', 'unclosed_table'),
        'Table nesting exceeds memory budget': ('table', 'nesting_limit'),
        'Table row budget exceeded': ('table', 'row_limit'),
        'Table width exceeds extraction budget': ('table', 'width_limit'),
    }
    if isinstance(exc, OriginalSourceError):
        stage, reason = exc.stage, exc.reason
    else:
        stage, reason = codes.get(str(exc), (stage, 'request_or_parse_error'))
    return {'stage': stage, 'reason': reason, 'error_type': type(exc).__name__}


def read_html(url):
    request = Request(url, headers={'User-Agent': 'GongsiBot/1.0'})
    with urlopen(request, timeout=8) as response:
        target = urlsplit(response.geturl())
        if target.scheme != 'https' or target.hostname != 'dart.fss.or.kr':
            raise OriginalSourceError('html_download', 'unexpected_redirect')
        data = response.read(MAX_PAGE + 1)
        encoding = response.headers.get_content_charset()
    if len(data) > MAX_PAGE:
        raise OriginalSourceError('html_download', 'size_limit')
    if not encoding:
        match = re.search(br'charset\s*=\s*[\'\"]?([a-zA-Z0-9_.-]+)', data[:4096], re.I)
        encoding = match.group(1).decode('ascii') if match else 'utf-8'
    if encoding.lower() not in ('utf-8', 'utf8', 'euc-kr', 'cp949', 'ks_c_5601-1987'):
        raise OriginalSourceError('html_decode', 'unsupported_encoding')
    return data.decode(encoding, errors='strict')


def viewer_params(page, receipt):
    """Read only literal DART viewer parameters belonging to the exact receipt."""
    candidates = []
    for match in re.finditer(
            r'viewDoc\(\s*[\'\"](\d{14})[\'\"]\s*,\s*[\'\"](\d+)[\'\"]\s*,\s*'
            r'[\'\"](\d+)[\'\"]\s*,\s*[\'\"](\d+)[\'\"]\s*,\s*'
            r'[\'\"](\d+)[\'\"]\s*,\s*[\'\"]([a-zA-Z0-9_.-]+)[\'\"]'
            r'(?:\s*,\s*[\'\"][a-zA-Z0-9_.-]*[\'\"])?\s*\)', page):
        rcp, dcm, element, offset, length, dtd = match.groups()
        if rcp == receipt:
            candidates.append((dcm, element, offset, length, dtd))
    nodes = {}
    for match in re.finditer(
            r'(node\d+)\s*\[\s*[\'\"](rcpNo|rceptNo|dcmNo|eleId|offset|length|dtd)[\'\"]\s*\]'
            r'\s*=\s*[\'\"]([a-zA-Z0-9_.-]+)[\'\"]', page):
        node, name, value = match.groups()
        nodes.setdefault(node, {})[name] = value
    for node in nodes.values():
        if node.get('rcpNo', node.get('rceptNo')) != receipt:
            continue
        values = tuple(node.get(k, '') for k in ('dcmNo', 'eleId', 'offset', 'length', 'dtd'))
        if all(re.fullmatch(r'\d+', v) for v in values[:4]) and re.fullmatch(r'[a-zA-Z0-9_.-]+', values[4]):
            candidates.append(values)
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        raise OriginalSourceError('html_document_selection', 'viewer_not_found')
    if len({row[0] for row in candidates}) != 1:
        raise OriginalSourceError('html_document_selection', 'ambiguous_document')
    whole = [row for row in candidates if row[1:4] == ('0', '0', '0')]
    if len(whole) == 1:
        selected = whole[0]
    elif len(candidates) == 1:
        selected = candidates[0]
    else:
        raise OriginalSourceError('html_document_selection', 'ambiguous_section')
    return dict(zip(('rcpNo', 'dcmNo', 'eleId', 'offset', 'length', 'dtd'), (receipt,) + selected))


def html_document(extractor, receipt):
    if not re.fullmatch(r'\d{14}', receipt):
        raise OriginalSourceError('html_document_selection', 'invalid_receipt')
    extractor.store.reserve_dart_request(extractor.daily_limit)
    page = read_html('https://dart.fss.or.kr/dsaf001/main.do?' + urlencode({'rcpNo': receipt}))
    params = viewer_params(page, receipt)
    extractor.store.reserve_dart_request(extractor.daily_limit)
    return read_html('https://dart.fss.or.kr/report/viewer.do?' + urlencode(params))


def original_fields(extractor, receipt, aliases, evidence):
    from .extraction import raw_fields
    attempts = evidence.setdefault('original_attempts', [])
    try:
        fields = raw_fields(extractor.original(receipt), aliases)
        attempts.append({'source': 'document_api', 'stage': 'table',
                         'reason': 'fields_available' if fields else 'no_matching_fields',
                         'field_count': len(fields)})
        if fields:
            evidence['original_source'] = 'document_api'
            return fields
    except Exception as exc:
        evidence['original_error'] = type(exc).__name__
        attempts.append(dict(source='document_api', **failure(exc, 'document_download')))
        if not isinstance(exc, (ValueError, OSError, UnicodeError)):
            raise
        if isinstance(exc, OriginalSourceError) and exc.reason in (
                'api_status_010', 'api_status_011', 'api_status_012', 'api_status_020'):
            raise
    try:
        fields = raw_fields(html_document(extractor, receipt), aliases)
        attempts.append({'source': 'dart_html', 'stage': 'table',
                         'reason': 'fields_available' if fields else 'no_matching_fields',
                         'field_count': len(fields)})
        if fields:
            evidence['original_source'] = 'dart_html'
        return fields
    except Exception as exc:
        attempts.append(dict(source='dart_html', **failure(exc, 'html_download')))
        raise



def parent_reference(extractor, receipt):
    """Only a unique root report explicitly linked by the DART family selector."""
    from html import unescape
    from urllib.parse import parse_qs
    extractor.store.reserve_dart_request(extractor.daily_limit)
    page=read_html('https://dart.fss.or.kr/dsaf001/main.do?'+urlencode({'rcpNo':receipt}))
    roots=set()
    for value in re.findall(r'<option\b[^>]*\bvalue\s*=\s*[\'\"]([^\'\"]+)[\'\"]',page,re.I):
        params=parse_qs(unescape(value))
        candidate=params.get('rcpNo',[''])[0]
        if set(params)=={'rcpNo'} and re.fullmatch(r'\d{14}',candidate) and candidate<receipt:
            roots.add(candidate)
    return roots.pop() if len(roots)==1 else None
