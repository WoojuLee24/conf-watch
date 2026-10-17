# conf-watch

CVPR · ICCV · ECCV · AAAI · ICLR · ICML · NeurIPS · IROS · ICRA · RSS · CoRL 의
**논문 마감일**과 **설정한 검색어에 맞는 challenge/competition** 을 7일마다 모아 메일로 보낸다.

- 마감일: [ccfddl/ccf-deadlines](https://github.com/ccfddl/ccf-deadlines) 데이터
- challenge: 각 학회 workshop/competition 목록 페이지 → 워크숍 사이트까지 따라가 검색어 매칭, + EvalAI 공개 API
- 실행: GitHub Actions (매주 월 09:00 KST), 결과는 메일 + `docs/report.html`, `docs/latest.json`

## 설정 — `config.yaml`

| 항목 | 내용 |
|---|---|
| `keywords` | 검색어. 대소문자·하이픈 무시, `re:` 접두사면 정규식, 비우면 모든 challenge |
| `conferences.*.seeds` | 학회별 workshop/competition 목록 URL (`{year}`, `{yy}` 치환). 학회 사이트가 개편되면 여기만 고친다 |
| `editions.past_days` | 개최일이 오늘-N일 이후인 회차만 탐색 |
| `mail.*` | 제목 머리말, 새 소식이 없을 때도 보낼지, 마감일 표시 범위 |

## 로컬 (Docker)

```bash
docker compose build
docker compose run --rm test      # 단위 테스트 (네트워크 불필요)
docker compose run --rm verify    # 검증 모드
docker compose run --rm preview   # 메일/상태 갱신 없이 docs/report.html 생성
docker compose run --rm run       # 실제 실행 (.env 의 SMTP 설정으로 메일 발송)
```

`.env` 예시 (git 에 올리지 않음):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=<Gmail 앱 비밀번호 16자리>
```

## 검증 모드 — `verify/ground_truth.yaml`

실제로 열렸던(과거) / 진행 중인 challenge 와 알려진 마감일을 정답으로 두고,
해당 회차를 처음부터 다시 수집해서 찾아내는지 확인한다. recall 80% 미만이거나 마감일이 하나라도 틀리면 실패(exit 1).
코드나 설정이 바뀌어 push 되면 Actions 에서 자동으로 돈다.

## GitHub Actions

Settings → Secrets and variables → Actions 에 `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` (선택 `MAIL_FROM`) 등록. 받는 사람은 `config.yaml` 의 `mail.to`.
Actions 탭 → weekly → Run workflow 로 수동 실행 (`run` / `verify` 선택).
새 항목 판별용 상태는 `state/seen.json` 에 커밋된다.
