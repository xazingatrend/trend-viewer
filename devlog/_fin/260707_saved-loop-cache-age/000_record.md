# 저장 루프와 캐시 나이 표시 기록

## 맥락

이번 작업은 백엔드에 이미 준비된 `/api/saved` 계약을 바꾸지 않고, 단일 프론트엔드 파일 안에서 저장 루프를 완성하는 것이 핵심이었다. 카드 전체가 `wireCardAction()`으로 버튼처럼 동작하기 때문에, 북마크 버튼은 별도 `button`으로 만들되 click, keydown, keyup 이벤트 전파를 모두 막아 카드 열기와 저장 토글이 섞이지 않게 했다.

캐시 나이 표시는 새 API 필드인 `fetchedAt`, `cacheTtl`을 소비하는 일이다. 화면의 밀도를 흔들지 않도록 기존 status/count 영역 안에 작은 muted 라인으로 넣었고, 홈 브리핑은 각 섹션 헤더의 개수 옆에 수집 시점을 붙였다.

---

### src/frontend/index.html — 저장 루프와 저장됨 탭
- **Changes**: `savedByUrl` Map을 시작 시 `GET /api/saved`로 초기화하고, 토글 후 서버 응답의 `items` 배열로 항상 재구성하도록 만들었다. 북마크 버튼은 `createTrendCard()` 내부에서 `bookmarkData.url`이 있을 때만 생성하며, 기존 `#i-bookmark` 심볼을 쓴다.
- **File refs**: `src/frontend/index.html:661`, `src/frontend/index.html:679`, `src/frontend/index.html:690`, `src/frontend/index.html:699`, `src/frontend/index.html:756`
- **Impact**: 유튜브/쇼츠, 릴스/틱톡, X/스레드 카드가 동일한 저장 상태를 공유한다. 저장 토글 뒤 보이는 모든 북마크 버튼은 `updateBookmarkButtons()`로 `aria-pressed`와 라벨이 갱신된다.
- **Verification**: `TREND_VIEWER_PORT=8794 python3 src/main.py` 실행 후 Python urllib로 `/api/saved` add/get/remove를 확인했다. 결과는 `add_found=True`, `get_found=True`, `remove_found=False`.

### src/frontend/index.html — 저장됨 탭 렌더링
- **Changes**: `VIEWS` 마지막에 `saved` 탭을 추가하고 `savedView`를 만들었다. 저장 항목은 `savedAt` 내림차순으로 카드 렌더링하며, HTTP 썸네일은 `/api/img` 프록시를 사용한다. 삭제 버튼은 항상 보이고 키보드 포커스가 가능하다.
- **File refs**: `src/frontend/index.html:398`, `src/frontend/index.html:424`, `src/frontend/index.html:1380`, `src/frontend/index.html:1397`, `src/frontend/index.html:1427`
- **Impact**: 저장 탭은 toolbar 없이 독립적으로 렌더링된다. 유튜브 URL은 가능한 경우 기존 플레이어 모달로 열고, 그 외 URL은 새 탭으로 연다.
- **Verification**: Playwright + 로컬 Chrome으로 `http://localhost:8794/`를 렌더링하고 저장 탭을 클릭했다. 결과는 `tabs=9`, 빈 상태 문구 `저장한 카드가 없습니다 | 카드의 북마크 아이콘을 누르면 여기에 모입니다`, 스크린샷 `/tmp/trend-viewer-saved-smoke.png`.

### src/frontend/index.html — cache age와 fallback banner
- **Changes**: `formatAge()`, `formatDuration()`, `cacheAgeText()`를 추가해 `방금/N분 전/N시간 전 수집 · 1시간 캐시` 형식의 라인을 만든다. 영상/AI/릴스/X/스레드/틱톡 로드 경로에 적용했고, 홈 섹션 헤더에는 `N분 전`을 개수 옆에 붙였다.
- **File refs**: `src/frontend/index.html:482`, `src/frontend/index.html:499`, `src/frontend/index.html:504`, `src/frontend/index.html:1038`, `src/frontend/index.html:1603`, `src/frontend/index.html:1631`, `src/frontend/index.html:1756`
- **Impact**: 피드 수집 시점과 캐시 TTL을 사용자에게 노출한다. reels/threads는 기존 “빈 결과 + 계정 있음” 추론을 유지하면서, 바로가기 목록 위에 동일한 muted 정보 배너를 표시한다.
- **Verification**: `curl -s http://localhost:8794/ | grep -n "savedView\\|저장됨\\|bookmark-toggle"`로 HTML 노출을 확인했다. `python3 -m unittest discover -s src -p 'test_*.py'` 결과는 `Ran 60 tests`, `OK`.

## 최종 확인

- `git diff --check` 통과.
- 인라인 스크립트 추출 후 `node --check /tmp/trend_viewer_index.js` 통과.
- `python3 -m unittest discover -s src -p 'test_*.py'` 통과: 60 tests OK.
- 서버 스모크 후 생성된 `config/*.json` 실행 부산물은 변경 범위에서 제외했다.
