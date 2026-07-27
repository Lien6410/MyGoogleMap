import re

_CID_RE = re.compile(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', re.IGNORECASE)
_PUNCT_RE = re.compile(r'[（）()\s/,、．·　【】『』「」{}｛｝\[\]]')


def extract_cid(url):
    if not url:
        return None
    m = _CID_RE.search(url)
    return m.group(1).lower() if m else None


def _normalize(s):
    return _PUNCT_RE.sub('', s or '')


def place_key(url, title, address):
    cid = extract_cid(url)
    if cid:
        return cid
    return f"name:{_normalize(title)}|{_normalize(address)}"
