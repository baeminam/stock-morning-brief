# 증시 모닝 브리프 (Stock Morning Brief)

한국 / 미국 / 일본 증시 종목을 매일 모니터링하여,
단기(수 일~수 주)와 장기(2~3년) 관점에서 주가 상승이 기대되는 종목과 업종을 추천하는 리포트를 매일 아침 이메일로 발송하는 앱입니다.

- **기술적 분석**: RSI, MACD, 이동평균, 볼린저밴드, 거래량 급증
- **기본적 분석**: IB(애널리스트) 의견·목표가, 뉴스/공시 감성, 업종 모멘텀
- **종합 점수**: 기술 40% + 기본 60%
- **비용**: 묣 데이터 + GitHub Actions 묣 티어 사용

## 구조

```
stock-morning-brief/
├── .github/workflows/morning_report.yml  # GitHub Actions 스케줄
├── config/                               # 설정 파일
├── src/                                  # 소스 코드
├── data/                                 # 실행 시 생성되는 데이터
├── requirements.txt
├── run_local.py                          # 로컬 테스트
└── README.md
```

## 로컬 설치 및 테스트

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 설정 편집 (선택)
# config/universe.yaml

# 로컬 실행 (메일 발송 없이 콘솔/파일 출력)
python run_local.py

# 메일 발송 테스트
python run_local.py --send-email
```

로컬에서 메일/AI 해설을 테스트하려면 프로젝트 루트에 `.env` 파일을 만들고 값을 넣으세요
(`.env`는 git에 올라가지 않습니다):

```
GMAIL_USER=...
GMAIL_APP_PASSWORD=...
REPORT_EMAIL=...
GROQ_API_KEY=...   # 선택
```

## GitHub Actions 배포

1. 이 저장소를 **public repository**로 GitHub에 push합니다.
2. `Settings > Secrets and variables > Actions` 에 다음 Secret을 등록합니다.
   - `GMAIL_USER`: 발송할 Gmail 주소
   - `GMAIL_APP_PASSWORD`: Gmail 앱 비밀번호
   - `REPORT_EMAIL`: 리포트를 받을 이메일 주소
   - `GROQ_API_KEY`: (선택) Groq API 키 — 등록하면 종목별 AI 해설이 리포트에 추가됩니다.
     https://console.groq.com 에서 묣 발급 (Llama 3.3 70B, 일 1,000회 묣)
3. `.github/workflows/morning_report.yml` 의 cron 시간을 원하는대로 조정합니다.
   - 기본: 매일 08:00 KST

## 수신 이메일 추가

- **여러 명에게 발송**: `config/recipients.txt`에 한 줄에 하나씩 이메일을 추가하면 됩니다.
  GitHub 웹에서 파일 편집(연필 아이콘) → commit만으로 바로 반영됩니다.
- `REPORT_EMAIL` Secret에 등록된 주소도 함께 발송됩니다 (쉼표로 여러 개 지정 가능).

## 주의사항

- 본 리포트는 투자 권유가 아닌 정보 제공용입니다.
- 묣 데이터를 사용하므로 지연·누락이 있을 수 있습니다.
- 웹 데이터 수집은 robots.txt 및 사이트 정책을 준수하며, 과도한 호출을 피합니다.
- 최신 pykrx는 KRX 자격 증명(`KRX_ID`/`KRX_PW` 환경 변수)을 요구합니다. 설정되어 있지 않으면
  `config/universe.yaml`의 `kr.fallback_tickers`(KOSPI 대표 종목)를 yfinance로 조회하는 방식으로 자동 전환됩니다.
