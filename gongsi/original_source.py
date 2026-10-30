"""Bounded same-filing HTML fallback; no JavaScript execution or guessed IDs."""
import re
import codecs
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_PAGE = 4 * 1024 * 1024


class OriginalSourceError(ValueError):
    def __init__(self, stage, reason, responses=None):
        self.stage, self.reason = stage, reason
        self.html_responses = list(responses or [])[:2]
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
    result = {'stage': stage, 'reason': reason, 'error_type': type(exc).__name__}
    if isinstance(exc, OriginalSourceError) and exc.html_responses:
        result['html_responses'] = exc.html_responses
    return result


class HtmlText(str):
    def __new__(cls, value, responses):
        result = super().__new__(cls, value)
        result.html_responses = list(responses)[:2]
        return result


def charset_name(value):
    """Resolve aliases only within the existing UTF-8/Korean encoding families."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,79}', value):
        return None
    value = {'windows-949': 'cp949', 'x-windows-949': 'cp949'}.get(value, value)
    try:
        name = codecs.lookup(value).name
    except LookupError:
        return None
    return name if name in ('utf-8', 'utf-8-sig', 'euc_kr', 'cp949') else None


def charset_label(value):
    if not value:
        return 'absent'
    if isinstance(value, str) and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{0,39}', value.strip()):
        return value.strip().lower()
    return 'invalid'


def decode_html(data, header_charset=None, response_info=None):
    """Compare declarations on the same bytes; never replace undecodable bytes."""
    info = dict(response_info or {})
    prefix = re.sub(br'<!--.*?-->', b'', data[:8192], flags=re.S)
    declarations = []
    for tag in re.findall(br'<meta\b[^>]{0,1024}>', prefix, re.I):
        match = re.search(br'charset\s*=\s*[\x27\x22]?([a-zA-Z0-9_.-]{1,80})', tag, re.I)
        if match:
            declarations.append(match.group(1).decode('ascii'))
    declarations = list(dict.fromkeys(declarations))[:4]
    info.update(header_charset=charset_label(header_charset),
                meta_charsets=[charset_label(value) for value in declarations])
    header = charset_name(header_charset)
    meta = list(dict.fromkeys(charset_name(value) for value in declarations if charset_name(value)))
    names = list(dict.fromkeys(([header] if header else []) + meta))
    info['declaration_conflict'] = len(names) > 1
    def fail(reason):
        raise OriginalSourceError('html_decode', reason, [info])
    if data.startswith(b'\xef\xbb\xbf'):
        candidates = [('utf-8-sig', 'bom')]
    elif data.startswith((b'\xff\xfe', b'\xfe\xff')):
        fail('unsupported_encoding')
    elif names:
        candidates = [(name, 'header' if name == header else 'meta') for name in names]
    else:
        # UTF-8 is the existing default; do not guess between legacy encodings.
        candidates = [('utf-8', 'utf8_fallback' if header_charset or declarations else 'default')]
    decoded = []
    for name, origin in candidates:
        try:
            text = data.decode(name, errors='strict')
        except UnicodeError:
            continue
        decoded.append((name, origin, text))
    if not decoded:
        fail('decode_error' if names or not (header_charset or declarations) else 'unsupported_encoding')
    if len({text for name, origin, text in decoded}) != 1:
        fail('ambiguous_encoding')
    name, origin, text = decoded[0]
    if not re.search(r'<(?:!doctype\s+html|html\b|head\b|body\b|meta\b|table\b)', text[:65536], re.I):
        fail('not_html')
    info.update(selected_encoding=name, encoding_source=origin)
    return HtmlText(text, [info])


def read_html(url):
    request = Request(url, headers={'User-Agent': 'GongsiBot/1.0'})
    page = {'/dsaf001/main.do': 'main', '/report/viewer.do': 'viewer'}.get(urlsplit(url).path, 'other')
    info = {'page': page}
    with urlopen(request, timeout=8) as response:
        target = urlsplit(response.geturl())
        if target.scheme != 'https' or target.hostname != 'dart.fss.or.kr':
            raise OriginalSourceError('html_download', 'unexpected_redirect', [info])
        data = response.read(MAX_PAGE + 1)
        encoding = response.headers.get_content_charset()
        content_type = response.headers.get_content_type()
        info['content_type'] = (content_type if content_type in (
            'text/html', 'application/xhtml+xml', 'text/plain', 'application/octet-stream') else 'other')
        status = response.getcode()
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
            info['http_status'] = status
    if len(data) > MAX_PAGE:
        raise OriginalSourceError('html_download', 'size_limit', [info])
    info['bytes'] = len(data)
    if info['content_type'] == 'other':
        raise OriginalSourceError('html_download', 'unexpected_content_type', [info])
    return decode_html(data, encoding, info)


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
    try:
        params = viewer_params(page, receipt)
        extractor.store.reserve_dart_request(extractor.daily_limit)
        body = read_html('https://dart.fss.or.kr/report/viewer.do?' + urlencode(params))
    except OriginalSourceError as exc:
        exc.html_responses = (list(getattr(page, 'html_responses', [])) + exc.html_responses)[:2]
        raise
    return HtmlText(body, list(getattr(page, 'html_responses', [])) +
                    list(getattr(body, 'html_responses', [])))


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
        body = html_document(extractor, receipt)
        if getattr(body, 'html_responses', None):
            evidence['html_responses'] = body.html_responses
        fields = raw_fields(body, aliases)
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
