"""HTTP wrappers deliberately omit URLs, response bodies and credentials from errors."""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

def now_kst():
    return datetime.now(KST)

class ApiError(RuntimeError):
    def __init__(self, service, code="network", retry_after=0):
        self.service, self.code, self.retry_after = service, str(code), retry_after
        super().__init__(f"{service} request failed (code={code})")

def request_json(service, url, payload=None, timeout=40):
    headers = {"User-Agent": "GongsiBot/1.0"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        retry_after = 0
        code = exc.code
        try:
            error = json.load(exc)
            if str(error.get("description", "")).startswith("Bad Request: message is not modified"):
                code = "message_not_modified"
            retry_after = min(3600, max(0, int(error.get("parameters", {}).get("retry_after", 0))))
        except (ValueError, TypeError, OSError):
            pass
        raise ApiError(service, code, retry_after) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, OSError):
        raise ApiError(service) from None

class Telegram:
    def __init__(self, token):
        self.base = "https://api.telegram.org/bot" + token + "/"

    def call(self, method, **body):
        result = request_json("Telegram", self.base + method, body)
        if not result.get("ok"):
            raise ApiError("Telegram", result.get("error_code", "invalid"),
                           result.get("parameters", {}).get("retry_after", 0))
        return result["result"]

class Dart:
    def __init__(self, key, store, daily_limit=18000):
        self.key, self.store, self.daily_limit = key, store, daily_limit

    def page(self, start, end, page):
        day = now_kst().date().isoformat()
        quota = self.store.get("dart_quota", {"day": day, "count": 0})
        if quota["day"] != day:
            quota = {"day": day, "count": 0}
        if quota["count"] >= self.daily_limit:
            raise ApiError("OpenDART", "local_daily_limit")
        quota["count"] += 1
        self.store.set("dart_quota", quota)
        params = {"crtfc_key": self.key, "bgn_de": start, "end_de": end,
                  "last_reprt_at": "N", "sort": "date", "sort_mth": "asc",
                  "page_count": 100, "page_no": page}
        result = request_json("OpenDART", "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(params))
        if result.get("status") == "013":
            return {"total_page": 0, "list": []}
        if result.get("status") != "000":
            raise ApiError("OpenDART", result.get("status", "invalid"))
        return result

    def reports(self, start, end):
        # Every range is <=31 days, safely below the no-corporation 3-month limit.
        first = self.page(start, end, 1)
        pages = int(first["total_page"])
        if pages > 1000:
            raise ApiError("OpenDART", "too_many_pages")
        found = {}
        for number in range(1, pages + 1):
            result = first if number == 1 else self.page(start, end, number)
            for report in result.get("list", []):
                receipt = report.get("rcept_no", "")
                if len(receipt) != 14 or not receipt.isdigit() or not report.get("report_nm"):
                    raise ApiError("OpenDART", "invalid_report")
                found[receipt] = report
        return sorted(found.values(), key=lambda report: (report["rcept_dt"], report["rcept_no"]))

