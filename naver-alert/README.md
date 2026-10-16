# 네이버 부동산 오피스텔 월세 알림

30분마다 네이버 부동산을 조회해 조건에 맞는 **신규** 매물만 텔레그램으로 보낸다.

## 조건 (`config.json`)

| 항목 | 값 |
|---|---|
| 지역 | 용산, 강남, 서초, 송파, 마포, 강서, 은평, 중, 종로구 |
| 종류 | 오피스텔 |
| 거래 | 월세 |
| 보증금 | 3,000만원 이하 |
| 월세 | 50만원 이하 |
| 입주가능일 | 2026-11-15 ~ 2026-11-20 |
| 전입신고 | 가능 |

입주일은 기본적으로 **11-20 이전이면 통과**시킨다. 먼저 비는 집도 그 기간에 들어갈 수
있기 때문이다. 희망 기간 안에 정확히 들어오는 매물만 보려면 `config.json`의
`moveInStrict`를 `true`로 바꾼다.

> 강남·서초는 보증금 3,000만 / 월세 50만 조건에 맞는 오피스텔이 거의 없을 것이다.
> 0건이 나오더라도 오류가 아니다.

## 설정 (1회)

1. 텔레그램 `@BotFather`에서 `/newbot` → 토큰 받기
2. 만든 봇에게 아무 메시지 보내고
   `https://api.telegram.org/bot<토큰>/getUpdates` 열어 `chat.id` 확인
3. GitHub 저장소 → Settings → Secrets and variables → Actions → New secret
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

## 실행

```bash
pip3 install requests

# 지금 당장 조건 맞는 매물 보기 (알림 안 보냄)
python3 naver-alert/monitor.py --dry-run --no-state --report

# 실제 알림 보내기 (.env 또는 환경변수에 토큰 필요)
python3 naver-alert/monitor.py
```

**네이버는 해외 데이터센터 IP를 차단한다.** 국내 네트워크에서 돌려야 한다.
자동 실행 설정은 [SETUP_LOCAL.md](SETUP_LOCAL.md) 참고.

## 동작 방식

- 목록 API(`m.land.naver.com/cluster/ajax/articleList`)를 구 → 동 단위로 순회
- 1차 필터(하드): 오피스텔 / 월세 / 보증금 / 월세 금액 → 불일치는 버림
- 2차 필터(상세): 입주가능일, 전입신고
  - `✅` 조건 확인됨
  - `❓` 상세에서 못 읽음 → **그래도 알림 보냄** (놓치는 쪽이 손해라서)
  - `❌` 명확히 불일치 → 제외하고 재조회 대상에서도 제외
- 중복: `naver-alert/state/seen.json`에 매물번호 + 지문(단지·면적·층·가격)을 기록.
  중개사만 다른 동일 매물도 한 번만 알림. 30일 지나면 기록 삭제.
- 알림 전송이 실패한 건은 기록하지 않아 다음 회차에 재시도.

## 수동 실행 / 조건 변경

- Actions → `naver-realestate-alert` → Run workflow (기본 dry-run)
- 조건은 `config.json`만 고치면 된다. `moveInFrom`, `moveInTo`, `moveInStrict`,
  `maxDeposit`, `maxMonthlyRent`, `districts`.
