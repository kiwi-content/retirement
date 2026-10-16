# 내 컴퓨터에서 30분마다 돌리기

네이버는 해외 데이터센터 IP를 차단한다. 그래서 GitHub Actions 같은 클라우드에서는
응답을 안 준다. 국내 네트워크(집/회사 인터넷)에서 돌려야 한다.

## 1. 준비

```bash
git clone https://github.com/kiwi-content/retirement.git
cd retirement
pip3 install requests
```

## 2. 텔레그램 토큰 넣기

`naver-alert/.env` 파일을 만들고 두 줄을 넣는다. (이 파일은 git에 올라가지 않는다)

```
TELEGRAM_BOT_TOKEN=123456:AAAA....
TELEGRAM_CHAT_ID=123456789
```

## 3. 먼저 한 번 테스트 (알림 안 보내고 화면에만)

```bash
python3 naver-alert/monitor.py --dry-run --no-state --report
```

끝에 가격 낮은 순으로 요약표가 나온다. 빨리 한번 보려면 `--limit-dongs 2`를 붙여
구마다 동 2개만 본다.

- 매물이 출력되면 성공.
- `[중단] 네이버 부동산에 접속하지 못했습니다` 가 나오면 네트워크가 막힌 것.

실제로 한 번 보내보려면:

```bash
python3 naver-alert/monitor.py --no-state --limit-dongs 1
```

## 4. 30분마다 자동 실행

### macOS / Linux

```bash
crontab -e
```

아래 한 줄 추가 (경로는 본인 것으로):

```
*/30 * * * * cd /Users/본인이름/retirement && /usr/bin/python3 naver-alert/monitor.py >> /tmp/naver-alert.log 2>&1
```

macOS는 터미널에 "전체 디스크 접근 권한"이 필요할 수 있다.
로그 확인: `tail -f /tmp/naver-alert.log`

### Windows

PowerShell에서:

```powershell
$action  = New-ScheduledTaskAction -Execute "python" `
             -Argument "naver-alert\monitor.py" -WorkingDirectory "C:\Users\본인\retirement"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
             -RepetitionInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "naver-alert" -Action $action -Trigger $trigger
```

## 컴퓨터를 꺼도 돌게 하려면

국내 리전 서버가 필요하다. 네이버 클라우드 / 카페24 / 가비아 중 가장 싼 것이면 충분하다
(월 몇천원대). 해외 리전(AWS 도쿄, Oracle 등)은 차단될 수 있으니 **서울 리전**으로.
서버에서는 위 crontab 방법 그대로 쓰면 된다.

## 조건 바꾸기

`naver-alert/config.json` 만 고치면 된다.

| 키 | 뜻 |
|---|---|
| `districts` | 지역 (구 이름: 법정동코드) |
| `maxDeposit` | 보증금 상한 (만원) |
| `maxMonthlyRent` | 월세 상한 (만원) |
| `moveInFrom` / `moveInTo` | 희망 입주 기간 |
| `moveInStrict` | `true`면 기간 안에 정확히 들어오는 매물만 |
| `requireResidentRegistration` | 전입신고 조건 사용 여부 |
