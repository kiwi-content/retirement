# 네이버 부동산 오피스텔 월세 알림

30분마다 네이버 부동산을 조회해 조건에 맞는 **신규** 매물만 텔레그램으로 보낸다.

## 조건 (`config.json`)

| 항목 | 값 |
|---|---|
| 지역 | 송파구, 마포구, 광진구, 은평구, 강서구 |
| 종류 | 오피스텔 |
| 거래 | 월세 |
| 보증금 | 3,000만원 이하 |
| 월세 | 50만원 이하 |
| 입주가능일 | 2026-11-20 이전 (그날 이사 가능해야 하므로 "이하") |
| 전입신고 | 가능 |

## 설정 (1회)

1. 텔레그램 `@BotFather`에서 `/newbot` → 토큰 받기
2. 만든 봇에게 아무 메시지 보내고
   `https://api.telegram.org/bot<토큰>/getUpdates` 열어 `chat.id` 확인
3. GitHub 저장소 → Settings → Secrets and variables → Actions → New secret
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

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
- 조건은 `config.json`만 고치면 된다. `moveInBy`, `maxDeposit`, `maxMonthlyRent`, `districts`.
