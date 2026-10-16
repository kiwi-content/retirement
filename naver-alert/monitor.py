#!/usr/bin/env python3
"""네이버 부동산 오피스텔 월세 매물 모니터 + 텔레그램 알림.

조건(config.json):
  - 지역: 송파/마포/광진/은평/강서구
  - 오피스텔(OPST), 월세(B2)
  - 보증금 <= 3000만, 월세 <= 50만
  - 입주가능일 <= 2026-11-20 (또는 즉시입주/협의)
  - 전입신고 가능

목록 API로 1차 하드 필터를 걸고, 매물 상세에서 입주일/전입신고를 2차로 본다.
상세를 못 읽은 매물은 버리지 않고 "확인필요"로 표시해 알린다(놓치는 게 더 손해).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse

import requests

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "seen.json"

LIST_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
BASE = "https://m.land.naver.com"

DONG_BBOX_PAD = 0.013  # 동 중심 기준 bbox 반경(도). 약 1.4km.


def log(*args):
    print(*args, flush=True)


# ---------------------------------------------------------------- http


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": LIST_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": f"{BASE}/search/result/%EC%84%9C%EC%9A%B8",
        }
    )
    return s


def get_json(session: requests.Session, url: str, *, params=None, tries=3):
    last = None
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
            else:
                return r.json()
        except Exception as exc:  # 네트워크/파싱 모두
            last = repr(exc)
        time.sleep(1.5 * (attempt + 1))
    log(f"  [warn] get_json 실패 {url} params={params} -> {last}")
    return None


# ---------------------------------------------------------------- naver


def fetch_dongs(session: requests.Session, gu_code: str) -> list[dict]:
    """구 코드로 동 목록(코드/이름/좌표)을 받는다."""
    data = get_json(
        session, f"{BASE}/map/getRegionList", params={"cortarNo": gu_code}
    )
    if not data:
        return []
    out = []
    for item in (data.get("result") or {}).get("list") or []:
        lat, lon = item.get("lat"), item.get("lon")
        if lat is None or lon is None:
            continue
        out.append(
            {
                "code": str(item.get("cortarNo")),
                "name": item.get("cortarNm") or "",
                "lat": float(lat),
                "lon": float(lon),
            }
        )
    return out


def fetch_articles(
    session: requests.Session, dong: dict, cfg: dict, delay: float
) -> list[dict]:
    """한 동의 매물 목록을 페이지 끝까지 긁는다."""
    lat, lon = dong["lat"], dong["lon"]
    base_params = {
        "rletTpCd": cfg["realEstateType"],
        "tradTpCd": cfg["tradeType"],
        "z": "13",
        "lat": lat,
        "lon": lon,
        "btm": lat - DONG_BBOX_PAD,
        "lft": lon - DONG_BBOX_PAD,
        "top": lat + DONG_BBOX_PAD,
        "rgt": lon + DONG_BBOX_PAD,
        "cortarNo": dong["code"],
        "itemId": "",
        "mapKey": "",
        "lgeo": "",
        "showR0": "",
        "totCnt": "0",
    }
    articles: list[dict] = []
    for page in range(1, 21):
        params = dict(base_params, page=str(page))
        data = get_json(session, f"{BASE}/cluster/ajax/articleList", params=params)
        if not data:
            break
        body = data.get("body") or []
        articles.extend(body)
        if not data.get("more") or not body:
            break
        time.sleep(delay)
    return articles


DETAIL_URLS = [
    "https://m.land.naver.com/article/info/{no}",
    "https://new.land.naver.com/api/articles/{no}?complexNo=",
]

RE_MOVE_YMD = re.compile(r'"moveInPossibleYmd"\s*:\s*"?(\d{8})')
RE_MOVE_TYPE = re.compile(r'"moveInTypeName"\s*:\s*"([^"]{1,30})"')
RE_MOVE_TEXT = re.compile(r"입주[가-힣]{0,4}일?[^0-9가-힣]{0,12}([0-9]{2,4}[.\-/년][^<\",]{0,18})")
RE_JEONIP = re.compile(r"전입(?:신고)?\s*(?:[:：]|이|가)?\s*(가능|불가|불가능|안됨|어려움|협의)")


def fetch_detail(session: requests.Session, atcl_no: str) -> dict:
    """상세 문서에서 입주가능일/전입신고 단서를 뽑는다. 못 뽑으면 빈 dict."""
    for tmpl in DETAIL_URLS:
        url = tmpl.format(no=atcl_no)
        try:
            r = session.get(url, timeout=20, headers={"Referer": f"{BASE}/"})
        except Exception:
            continue
        if r.status_code != 200 or not r.text:
            continue
        text = r.text
        info: dict = {"source": url, "raw_len": len(text)}

        m = RE_MOVE_YMD.search(text)
        if m:
            info["move_in_ymd"] = m.group(1)
        m = RE_MOVE_TYPE.search(text)
        if m:
            info["move_in_type"] = m.group(1)
        if "move_in_ymd" not in info and "move_in_type" not in info:
            m = RE_MOVE_TEXT.search(text)
            if m:
                info["move_in_text"] = m.group(1).strip()
            elif "즉시입주" in text:
                info["move_in_type"] = "즉시입주"

        m = RE_JEONIP.search(text)
        if m:
            info["jeonip"] = m.group(1)
        elif "전입신고" in text:
            info["jeonip"] = "언급있음"

        if len(info) > 2:
            return info
    return {}


# ---------------------------------------------------------------- filters

OK, UNKNOWN, NO = "ok", "unknown", "no"


def check_move_in(info: dict, move_in_by: dt.date) -> tuple[str, str]:
    """입주가능일이 희망 이사날짜(이하)를 만족하는지."""
    ymd = info.get("move_in_ymd")
    if ymd:
        try:
            d = dt.datetime.strptime(ymd, "%Y%m%d").date()
        except ValueError:
            d = None
        if d:
            label = d.strftime("%Y-%m-%d")
            return (OK if d <= move_in_by else NO), label

    blob = " ".join(
        str(info.get(k, "")) for k in ("move_in_type", "move_in_text")
    )
    if not blob.strip():
        return UNKNOWN, "확인필요"
    if any(k in blob for k in ("즉시", "협의", "면담")):
        return OK, blob.strip()

    m = re.search(r"(\d{2,4})[.\-/년]\s*(\d{1,2})(?:[.\-/월]\s*(\d{1,2}))?", blob)
    if m:
        year = int(m.group(1))
        year += 2000 if year < 100 else 0
        month = int(m.group(2))
        day = int(m.group(3) or 1)
        try:
            d = dt.date(year, month, day)
        except ValueError:
            return UNKNOWN, blob.strip()
        return (OK if d <= move_in_by else NO), d.strftime("%Y-%m-%d")
    return UNKNOWN, blob.strip()


def check_jeonip(info: dict, required: bool) -> tuple[str, str]:
    if not required:
        return OK, "미확인(조건아님)"
    v = info.get("jeonip")
    if not v:
        return UNKNOWN, "확인필요"
    if v in ("가능",):
        return OK, "가능"
    if v in ("불가", "불가능", "안됨", "어려움"):
        return NO, v
    return UNKNOWN, v  # 협의 / 언급있음


def passes_hard(article: dict, cfg: dict) -> bool:
    if (article.get("tradTpNm") or "") != "월세":
        return False
    if "오피스텔" not in (article.get("rletTpNm") or ""):
        return False
    deposit = to_manwon(article.get("prc"))
    rent = to_manwon(article.get("rentPrc"))
    if deposit is None or rent is None:
        return False
    return deposit <= cfg["maxDeposit"] and rent <= cfg["maxMonthlyRent"]


def to_manwon(value) -> int | None:
    """'1,000' / 1000 / '3억 2,000' 같은 표기를 만원 정수로."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).replace(",", "").replace(" ", "")
    if not s:
        return None
    m = re.fullmatch(r"(?:(\d+)억)?(\d+)?", s)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 10000 + int(m.group(2) or 0)
    digits = re.sub(r"\D", "", s)
    return int(digits) if digits else None


def fingerprint(article: dict) -> str:
    """중개사만 다른 동일 매물을 묶기 위한 보조 키."""
    parts = [
        (article.get("atclNm") or "").strip(),
        str(article.get("spc2") or article.get("spc1") or ""),
        (article.get("flrInfo") or "").strip(),
        str(to_manwon(article.get("prc"))),
        str(to_manwon(article.get("rentPrc"))),
    ]
    return "|".join(parts)


# ---------------------------------------------------------------- state


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            log("  [warn] state 파싱 실패, 새로 시작")
    return {"articles": {}, "fingerprints": {}}


def save_state(state: dict, retention_days: int):
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=retention_days)).isoformat()
    for key in ("articles", "fingerprints"):
        state[key] = {
            k: v for k, v in (state.get(key) or {}).items() if str(v) >= cutoff
        }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- telegram


def esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


MARK = {OK: "✅", UNKNOWN: "❓", NO: "❌"}


def render(hit: dict) -> str:
    a = hit["article"]
    link = f"{BASE}/article/info/{a.get('atclNo')}"
    spec = " / ".join(
        x
        for x in [
            a.get("flrInfo") and f"{a['flrInfo']}층",
            a.get("spc2") and f"{a['spc2']}㎡(전용)",
            a.get("direction"),
        ]
        if x
    )
    lines = [
        f"🏢 <b>{esc(a.get('atclNm') or '오피스텔')}</b> · {esc(hit['gu'])} {esc(hit['dong'])}",
        f"💰 보증금 {to_manwon(a.get('prc')):,}만 / 월세 {to_manwon(a.get('rentPrc')):,}만",
    ]
    if spec:
        lines.append(f"📐 {esc(spec)}")
    lines.append(
        f"{MARK[hit['move_status']]} 입주가능 {esc(hit['move_label'])}"
        f"  {MARK[hit['jeonip_status']]} 전입신고 {esc(hit['jeonip_label'])}"
    )
    if a.get("atclFetrDesc"):
        lines.append(f"📝 {esc(a['atclFetrDesc'])[:120]}")
    if a.get("rltrNm"):
        lines.append(f"🏪 {esc(a['rltrNm'])}")
    lines.append(f"🔗 {link}")
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
    except Exception as exc:
        log(f"  [error] 텔레그램 전송 실패: {exc!r}")
        return False
    if r.status_code != 200:
        log(f"  [error] 텔레그램 {r.status_code}: {r.text[:300]}")
        return False
    return True


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만")
    ap.add_argument("--no-state", action="store_true", help="중복 기록 무시/저장 안 함")
    ap.add_argument("--limit-dongs", type=int, default=0, help="동 개수 제한(디버그)")
    args = ap.parse_args()

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    move_in_by = dt.datetime.strptime(cfg["moveInBy"], "%Y-%m-%d").date()
    delay = float(cfg.get("requestDelaySec", 0.4))

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    notify = bool(token and chat_id) and not args.dry_run
    if not notify:
        log(f"[info] 알림 비활성 (dry_run={args.dry_run}, token={bool(token)}, chat={bool(chat_id)})")

    session = make_session()
    state = {"articles": {}, "fingerprints": {}} if args.no_state else load_state()
    seen_articles = state.setdefault("articles", {})
    seen_fps = state.setdefault("fingerprints", {})
    now_iso = dt.datetime.now(dt.UTC).isoformat()

    candidates: list[dict] = []
    total_listed = 0

    for gu_name, gu_code in cfg["districts"].items():
        dongs = fetch_dongs(session, gu_code)
        if not dongs:
            log(f"[{gu_name}] 동 목록 0개 — API 응답 확인 필요")
            continue
        if args.limit_dongs:
            dongs = dongs[: args.limit_dongs]
        log(f"[{gu_name}] 동 {len(dongs)}개")
        for dong in dongs:
            arts = fetch_articles(session, dong, cfg, delay)
            total_listed += len(arts)
            hard = [a for a in arts if passes_hard(a, cfg)]
            if hard:
                log(f"  {dong['name']}: 목록 {len(arts)} → 조건부합 {len(hard)}")
            for a in hard:
                candidates.append({"article": a, "gu": gu_name, "dong": dong["name"]})
            time.sleep(delay)

    log(f"[집계] 전체 {total_listed}건 / 1차 통과 {len(candidates)}건")

    # 신규만 남기기
    fresh = []
    for c in candidates:
        no = str(c["article"].get("atclNo"))
        fp = fingerprint(c["article"])
        if no in seen_articles or fp in seen_fps:
            continue
        c["no"], c["fp"] = no, fp
        fresh.append(c)
    log(f"[집계] 신규 {len(fresh)}건")

    # 2차: 상세로 입주일/전입신고 확인
    hits = []
    detail_budget = int(cfg.get("detailFetchLimit", 40)) if cfg.get("fetchDetail") else 0
    for c in fresh:
        info = {}
        if detail_budget > 0:
            info = fetch_detail(session, c["no"])
            detail_budget -= 1
            time.sleep(delay)
        blob = " ".join(
            str(c["article"].get(k) or "")
            for k in ("atclFetrDesc", "tagList", "atclNm")
        )
        if "jeonip" not in info:
            m = RE_JEONIP.search(blob)
            if m:
                info["jeonip"] = m.group(1)
        c["move_status"], c["move_label"] = check_move_in(info, move_in_by)
        c["jeonip_status"], c["jeonip_label"] = check_jeonip(
            info, cfg.get("requireResidentRegistration", True)
        )
        if NO in (c["move_status"], c["jeonip_status"]):
            seen_articles[c["no"]] = now_iso  # 확실한 불일치는 다시 안 봄
            log(f"  제외 {c['no']} 입주={c['move_label']} 전입={c['jeonip_label']}")
            continue
        hits.append(c)

    # 확정 먼저, 확인필요 나중
    hits.sort(key=lambda h: (h["move_status"] != OK, h["jeonip_status"] != OK))
    log(f"[결과] 알림 대상 {len(hits)}건")

    for h in hits:
        text = render(h)
        if notify:
            if not send_telegram(token, chat_id, text):
                continue  # 실패한 건은 state에 기록하지 않고 다음 회차에 재시도
            time.sleep(0.6)
        else:
            log("-" * 40)
            log(re.sub(r"<[^>]+>", "", text))
        seen_articles[h["no"]] = now_iso
        seen_fps[h["fp"]] = now_iso

    if not args.no_state:
        save_state(state, int(cfg.get("seenRetentionDays", 30)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
