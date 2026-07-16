# 2차 필터링 개선 가이드 — bizSupportNavigator의 LLM Judge 패턴 도입

`bizSupportNavigator`(별도 레포, 이 프로젝트 루트에 참고용으로 클론됨) 코드를 참고해
현재 2차 필터링(`docs/matching-pipeline.md` 4단계)을 어떻게 바꿀지 정리한 설계
문서다.

**구현 완료(PR #116, 2026-07-14 develop 병합).** 아래 "목표 설계"는 실제
`secondary_filtering_judge_service.py`/`secondary_filtering_judge_client.py`에
거의 그대로 반영됐다. "미정 항목"의 실제 해소 결과는 문서 하단을 참고.

## 왜 바꾸는가 (현재 문제)

현재 `secondary_filtering_service.py`는 공고 PDF 청크와 사업계획서 청크를
Chroma에 넣고 **코사인 거리 → 35~100 사이 숫자**로 바꾸는 것이 전부다
(`_similarity_to_score`). 이 점수는:

- **근거가 없다.** "왜 이 공고가 72점인지" 설명할 텍스트가 없고, 코드 주석에도
  "변환식 자체는 TBD"라고 명시돼 있다(`secondary_filtering_service.py:67`).
- **자격요건을 정확히 판단하지 못한다.** `docs/matching-pipeline.md` 4단계의
  원래 목적("1차에서 못 거른 기업규모 등 정확한 신청자격을 여기서 확인")을
  달성하지 못하고 있다 — 지금은 유사도 검색만 하고, 실제로 공고 원문을 읽고
  자격 요건을 판정하는 로직이 없다. 그 판정은 지금 `matching_service._eligibility_score`가
  담당하는데, 이건 **공고 PDF 원문이 아니라 정규화 JSON의 몇 개 필드(지역/기업규모/업력)만
  보는 손규칙 점수**라서 4단계가 원래 하려던 일과 다르다.
- **제외요건(disqualification)을 반영하지 않는다.** `NormalizedNoticeSchema.eligibility.excluded_targets`,
  `evaluation.disqualification_reasons`가 정규화 단계에서 이미 추출되고 있지만
  스코어링 어디에서도 쓰이지 않는다.

`bizSupportNavigator`는 정확히 이 문제(유사도 검색만으로는 자격 판정이
안 됨)를 **LLM이 요건 문장 단위로 충족/미충족을 판정하고, 그 판정을
가중 집계**하는 방식으로 푼다. 이 패턴을 가져온다.

## 매핑 — bizSupportNavigator → kg-vending-machine

| bizSupportNavigator | 역할 | 이 저장소의 대응/차이 |
| --- | --- | --- |
| `services/matching.py` `rag_search_candidates` | Chroma 벡터 검색으로 policy당 근거 청크(`matched_chunks`, 원문 포함) 확보 | `secondary_filtering_service.py`에 이미 있음. 단, 지금은 청크 원문을 버리고 `distance → score` 숫자만 남긴다. **원문 청크를 살리는 게 이번 변경의 1번 작업.** |
| `services/graph_reasoning.py` `fetch_graph_evidence` | Neo4j 그래프에서 policy별 eligibility/exclusion criteria 문장 목록 확보 | Neo4j 없음. 대신 `NormalizedNoticeSchema.eligibility`(`target_regions`/`target_company_size`/`target_business_stage`/`excluded_targets`)와 `evaluation`(`criteria`/`disqualification_reasons`)이 이미 LLM 정규화로 추출된 동일한 정보다. **그래프 대신 이 필드들을 criteria 문장 리스트로 변환하는 얇은 어댑터만 새로 만들면 된다 — Neo4j 도입은 이번 범위에 포함하지 않는다.** |
| `services/llm_judge.py` `judge_policy` | LLM structured output으로 요건 문장마다 기업 프로필+근거 청크 기준 충족/미충족/정보부족 판정 | **없음. 이번에 새로 추가하는 핵심 조각.** `app/ai/normalizer.py`의 `AsyncOpenAI` 클라이언트 구성+재시도 패턴, JSON 모드(`response_format={"type": "json_object"}`) 방식을 그대로 재사용한다(이 저장소는 `extra: dict` 자유필드 때문에 strict structured output을 안 쓰는 관례가 이미 있음 — `app/ai/normalizer.py:54-57` 참고). |
| `services/score_aggregate.py` `aggregate_score` | 판정 결과를 70/30 가중 평균 + 제외요건 확정 시 0점 캡으로 합산 | **없음. 새로 추가.** `_similarity_to_score`(코사인 거리 기반)를 대체한다. |
| `services/orchestrator.py` (LangGraph) | 위 단계를 그래프로 연결 | 이 저장소는 LangGraph를 쓰지 않고 `run_matching()` 안에서 순차 `await` 체인이다. **LangGraph 도입은 범위 밖 — 기존 방식대로 함수 호출 체인 유지.** |

## OCR은 언제, 어떻게 반영되는가 (중요 — 이번 변경의 전제 조건)

> **2026-07-15 갱신**: 아래 문단은 "1차 필터링이라는 이름의 별도 엔드포인트는
> 없다"던 당시(2026-07-13) 기준 설명이다. 지금은 `notice_eligibility_service.
> get_eligible_notices()`(`GET /api/eligible-notices/me`, [`first-filtering.md`](./first-filtering.md))가
> 실제 1차 필터링 엔드포인트로 존재한다. 다만 **"그 결과를 자동으로 OCR
> 배치에 넘기는 연결 코드가 없다"는 아래 결론 자체는 여전히 유효** — 1차
> 필터링은 신청기간이 지나지 않은 전체 저장 공고를 대상으로 하지, OCR
> 배치 트리거 자동화까지 포함하지 않는다.

**설계 의도: OCR은 1차 필터링 통과 후보만을 대상으로 한다.** `POST
/internal/notices/ocr/batch`의 목적이 바로 이것이라고 코드 주석에 명시돼
있다(`app/api/notice_ocr.py:11-15`): "배치 트리거는 매칭 파이프라인이 1차
필터링을 통과한 후보 여러 건에 대해 한 번에 OCR을 걸어야 하는 상황... 을
위한 것". 즉 전체 공고를 다 OCR하는 게 아니라, 분야/지역/마감일 같은
구조화 필드로 먼저 좁힌 후보에 한해서만 첨부파일을 열어본다는 설계는
맞고, 그 목적으로 만들어진 배치 엔드포인트도 이미 존재한다.

**그런데 그 "1차 필터링 후보 목록"을 자동으로 계산해서 OCR 배치에 넘기는
코드는 현재 저장소에 없다.**

- `POST /internal/notices/ocr/batch`의 요청 바디(`NoticeOcrBatchTriggerRequest`)는
  단순히 `{"notice_ids": [...]}` 다 — **호출하는 쪽이 이미 정해서 넘겨야** 한다.
- 분야/지역/마감일 기준으로 notice_id 목록을 뽑아주는 전용 함수·엔드포인트가
  없다. `GET /notices`(`api/notice.py`)가 category/region_code/exclude_closed
  필터를 제공하지만 이건 프론트·일반 조회용 API이지, "1차 필터링 결과를 OCR
  대상으로 넘기는" 전용 파이프라인이 아니다.
- `docs/matching-pipeline.md` "구현 현황" 절에도 "1차 필터링이라는 이름의
  별도 엔드포인트는 없다"고 명시돼 있다.

즉 지금은 **운영자/AI팀이 후보를 수동으로 정해서** OCR 배치 → 정규화 배치
순서로 직접 트리거하는 것으로 보이고(코드 상 자동화된 연결 고리는 없음),
이 수동 과정을 통해 `notice.normalized_json`이 채워진 공고만 이후
`run_matching()`의 `list_normalized_notice_candidates()`에 후보로 잡힌다.

```
전체 수집 공고
  → (설계 의도) 1차 필터링: 분야/지역/마감일 등 구조화 필드로 narrowing
      ※ 이 단계를 자동으로 수행하는 코드는 없음 — 현재는 사람이 판단
  → (운영자가 결정한 notice_id 목록으로) POST /internal/notices/ocr/batch
      → 첨부파일 다운로드 + OCR → notice_attachment.parsed_text 저장
  → POST /internal/notices/normalize/batch
      → parsed_text(없으면 summary_text)를 LLM 정규화 → notice.normalized_json 저장
  → 이 시점 이후에만 그 공고가 run_matching()의 candidates로 조회됨
  → run_matching() 내부: 품질 필터 + 자격요건 필터 (normalized_json 기준)
  → 2차 필터링 (이번 가이드가 다루는 부분)
```

**이번 LLM Judge 설계에 미치는 영향:**

- `run_matching()`은 이 OCR 배치를 직접 호출하지 않는다 — `run_matching()`이
  실행되는 시점에는 이미 OCR·정규화가 끝난 공고만 후보로 들어와 있다고
  가정한다. 이번 가이드가 새로 만드는 `judge_criteria()`도 이 전제를 그대로
  물려받는다 — 근거(evidence)는 새로 OCR을 트리거해서 만드는 게 아니라,
  `run_secondary_filtering()`이 이미 하듯 **이미 저장된** `parsed_text` 기반
  청크(`notice_embedding_service`가 Chroma에 넣어둔 것)를 재사용한다.
- 첨부파일이 있고 OCR·정규화가 이미 끝난 공고 → 청크 원문이 있어 LLM이 실제
  PDF 근거를 보고 판정 가능.
- 첨부파일이 없거나(전체 공고의 약 76%), 있어도 아직 수동 OCR 배치를 안 돌린
  공고 → 애초에 `normalized_json`이 없어 후보에 들지 못하거나, `summary_text`만으로
  정규화는 됐지만 첨부파일 원문은 없는 경우 → `evidence`가 비어 있어 LLM
  판정 없이 **전부 "정보부족"으로 처리**(기존 `skip_reason="no_text"` 경로와 동일).
- **이번 변경이 다루지 않는 갭(Non-goal):** "1차 필터링 후보를 자동으로 뽑아
  OCR 배치를 트리거하는 로직"은 이번 2차 필터링(LLM judge) 개선과는 **별개의
  선행 과제**다. 이게 없으면 아무리 2차 필터링을 잘 만들어도, 애초에
  OCR·정규화가 안 된 공고는 그 전 단계(품질 필터)에서부터 걸러지지 않고
  "후보에 들지 않음"으로 조용히 빠지므로 결과 커버리지가 제한된다. 이 문제는
  이 가이드가 아니라 별도 설계(1차 필터링 자동화)로 다뤄야 한다.

## 목표 설계 (To-Be)

### 새 파이프라인 (2차 필터링 내부)

```
1차 필터링 통과 후보 (passed)
  → run_secondary_filtering() [기존, 확장]
      - Chroma 유사도 검색은 그대로 수행하되
      - best_score만이 아니라 상위 N개 청크 원문(evidence)도 함께 반환
  → build_criteria_statements() [신규]
      - normalized_notice.eligibility/evaluation 필드 → 판정 대상 문장 리스트
      - 제외요건은 "~에 해당하지 않음"으로 긍정 재구성 (llm_judge.py 관례와 동일)
  → judge_criteria() [신규, LLM 호출]
      - 기업 프로필 + 사업계획서 요약 + 근거 청크 원문 + 요건 문장들을 LLM에 전달
      - 각 문장에 대해 충족/미충족/정보부족 + evidence 문장 반환
  → aggregate_secondary_score() [신규]
      - eligibility 그룹 평균 * 0.7 + exclusion 그룹 평균 * 0.3
      - 제외요건 중 하나라도 "미충족"(=제외 대상에 해당함) 확정되면 점수를 하한으로 캡
  → secondary_filter_score, reasons[] 를 matching_service._score_notice에 전달
```

### 새/변경 데이터 구조

`app/services/secondary_filtering_service.py` (확장):

```python
@dataclass(frozen=True)
class EvidenceChunk:
    content: str
    distance: float

@dataclass
class SecondaryFilteringResult:
    ...
    scores: dict[int, float]                       # 기존 유지(레거시/디버그용)
    evidence: dict[int, list[EvidenceChunk]] = field(default_factory=dict)  # 신규
```

`app/services/secondary_filtering_judge_service.py` (신규 — `llm_judge.py` + `score_aggregate.py` 대응):

```python
@dataclass(frozen=True)
class CriterionJudgment:
    criterion: str
    status: Literal["충족", "미충족", "정보부족"]
    evidence: str | None
    is_exclusion: bool

@dataclass(frozen=True)
class JudgedSecondaryScore:
    score: float                # 0~100
    excluded: bool              # 제외요건 확정 여부 (하한 캡 발동 사유)
    judgments: list[CriterionJudgment]

def build_criteria_statements(notice: NormalizedNoticeSchema) -> list[tuple[str, str, bool]]:
    """(criterion_id, statement, is_exclusion) 목록.
    eligibility: target_regions/target_company_size/target_business_stage 각각 문장화.
    exclusion: excluded_targets + evaluation.disqualification_reasons → "~에 해당하지 않음"."""

async def judge_criteria(
    *, profile: CompanyProfile, plan: NormalizedBusinessPlanSchema,
    notice: NormalizedNoticeSchema, evidence: list[EvidenceChunk],
) -> list[CriterionJudgment]: ...

def aggregate_secondary_score(judgments: list[CriterionJudgment]) -> JudgedSecondaryScore: ...
```

`app/ai/secondary_filtering_judge_client.py` (신규 — OpenAI 호출 레이어, `app/ai/normalizer.py` 패턴 재사용):

- `_build_client()` / 재시도 대상 예외(`_RETRYABLE_ERRORS`) 동일하게 복붙.
- `response_format={"type": "json_object"}` + pydantic 모델로 파싱(judgments 배열).
- 실패 시(재시도 소진, 파싱 실패) 예외를 던지지 않고 **전부 "정보부족"으로 폴백**
  (`bizSupportNavigator/llm_judge.py`의 `_fallback` 그대로 — 판정 실패가 매칭 전체를
  중단시키면 안 되므로).

### 점수 집계 공식 (bizSupportNavigator 그대로 이식)

```
eligibility_avg = mean(WEIGHT[status] for j in eligibility_judgments)   # WEIGHT = {충족:1.0, 정보부족:0.5, 미충족:0.0}
exclusion_avg   = mean(WEIGHT[status] for j in exclusion_judgments)
raw_score = (eligibility_avg * 0.7 + exclusion_avg * 0.3) * 100
score = 0 if any(exclusion judgment == "미충족") else round(raw_score)
```

각 그룹이 비어 있을 때(예: 이 공고에 제외요건이 없음)는 있는 쪽만 100% 반영—
`score_aggregate.py:68-73` 그대로.

**차이점(이 저장소에 맞춘 조정):** `bizSupportNavigator`는 제외요건 확정 시 점수를
`0`으로 완전히 캡한다. 이 저장소는 이미 `_eligibility_score`가 `likely_ineligible`일 때
`total_score`를 49점 이하로 캡하는 별도 규칙이 있다(`matching_service.py:261-262`).
두 캡이 같은 의도(부적격 공고를 상위에 노출하지 않음)이므로 **완전히 0으로
캡하는 대신, secondary_filter_score만 낮은 값(예: 5.0)으로 캡**하고 기존
`likely_ineligible` 49점 캡은 그대로 둔다 — 이중 안전장치로 유지, 값 자체는
아래 "미정 항목"에서 확정한다.

### `matching_service.py` 변경

- `_score_notice`의 `secondary_filter_score` 파라미터는 이제 코사인 유사도가
  아니라 `aggregate_secondary_score()`의 결과값을 받는다. 가중치(`* 0.20`)와
  중립값(임베딩/판정 불가 시 50.0) 로직은 그대로 유지.
- `run_matching()`에서 `run_secondary_filtering()` 호출 뒤, 임베딩된 공고마다
  `judge_criteria()` → `aggregate_secondary_score()`를 호출하는 단계 추가.
  **LLM 호출이므로 `notice_normalization_service.py`의 `_notice_llm_semaphore`와
  동일한 패턴으로 동시성 제한 세마포어를 둔다** (신규 설정값
  `SECONDARY_FILTERING_JUDGE_CONCURRENCY_LIMIT`, 기본값은 기존 10과 동일하게
  시작 후 실측으로 조정).
- `_build_secondary_filtering_log`의 `notices[]` 항목에 `reasons: list[{criterion, status, evidence}]`
  추가. 기존 필드(`secondary_filter_score`, `skip_reason` 등)는 그대로 유지 —
  하위 호환.

### 스키마/모델 변경

- `app/schemas/match_log.py`:
  - `SecondaryFilteringNoticeLog`에 `reasons: list[CriterionJudgmentSchema]` 필드 추가(신규 pydantic 모델).
  - `MatchResultResponse.result_json`이 감싸는 `score_breakdown.secondary_filter`는
    의미가 "코사인 유사도"에서 "LLM 판정 집계 점수"로 바뀐다 — 필드명/타입은
    그대로라 API 계약(response shape)은 안 바뀐다.
- `app/models/match.py`: **컬럼 변경 없음.** `secondary_filtering_log`는 이미
  JSONB라 새 키(`reasons`)를 추가하는 데 마이그레이션이 필요 없다.
- `app/core/config.py`: `SECONDARY_FILTERING_JUDGE_CONCURRENCY_LIMIT: int = 10`
  (가칭) 추가. 별도 LLM 모델을 쓸지(`OPENAI_MODEL` 재사용 vs 전용 모델)는
  미정 항목 참고.

### 프론트엔드 변경

- `frontend/src/api/matchLogs.ts`:
  - `SecondaryFilteringNoticeLog`에 `reasons: { criterion: string; status: string; evidence: string | null }[]` 추가(optional로 시작해 하위 호환 유지 가능).
- `frontend/src/components/SecondaryFilteringLogPanel/`: 공고별 판정 근거(충족/미충족/정보부족 + evidence 문장)를 펼쳐볼 수 있는 UI 추가. 지금은 점수 하나만 보여주는데, "왜 이 점수인지"를 사용자/운영자가 확인할 수 있게 하는 게 이번 변경의 핵심 가치이므로 이 UI가 없으면 백엔드 변경의 의미가 반감된다.

## 무엇이 달라지는가 (Before / After)

| 항목 | Before (현재) | After (이 변경 후) |
| --- | --- | --- |
| `secondary_filter_score`의 근거 | 코사인 거리 → 숫자 변환식(TBD로 명시된 임시 공식) | LLM이 판정한 요건별 충족/미충족/정보부족을 가중 집계한 값 |
| 판정 근거 텍스트 | 없음 | 요건 문장마다 evidence 문장 확보, `secondary_filtering_log.notices[].reasons`로 조회 가능 |
| 제외요건(`excluded_targets`, `disqualification_reasons`) 반영 | 전혀 반영 안 됨 | 제외요건 확정 시 `secondary_filter_score`를 낮은 값으로 캡 |
| 외부 API 호출량 | 공고당 임베딩 API 1회(저렴, 캐싱됨) | 임베딩 호출은 그대로 + **공고당 LLM 호출 1회 추가**(1차 필터링 통과 후보 전부 대상 — 캐싱 없음, 매 매칭 요청마다 재호출) |
| 매칭 요청 1건의 지연시간 | 임베딩 검색 위주(초 단위) | 후보 수만큼 LLM 호출이 늘어 수 초~수십 초 증가 예상(세마포어로 동시 실행하되, `notice_normalization_service`에서 실측된 것처럼 동시 호출 과다 시 타임아웃 위험 있음) |
| `total_score` 계산식 자체 | 안 바뀜 (`eligibility*0.25 + item_fit*0.20 + business_fit*0.20 + growth*0.10 + bonus*0.05 + secondary_filter*0.20`) | 안 바뀜 — `secondary_filter` 구성요소의 **산출 방식만** 교체 |
| API 응답 스키마 | `SecondaryFilteringLogResponse`, `MatchResultJson` | 필드 추가(`reasons`)만 있고 기존 필드 제거 없음 — 하위 호환 |
| DB 마이그레이션 | - | 불필요 (JSONB 컬럼 재사용) |

## 미정 항목 (TBD) — 실제 해소 결과 (2026-07-15)

1. **LLM 호출 비용/지연 감수 범위** — **해소.** "1차 통과 + 유사도 상위 K건"으로
   확정(`matching_service._SECONDARY_FILTERING_JUDGE_TOP_K = 15`). K건 밖의
   공고는 LLM 판정 없이 코사인 유사도 점수를 그대로 쓴다.
2. **제외요건 확정 시 캡 값** — **해소.** `5.0`으로 확정
   (`secondary_filtering_judge_service._EXCLUDED_SCORE_CAP`). 기존
   `likely_ineligible` 49점 캡과 별개의 이중 안전장치로 유지.
3. **사용할 모델** — **해소.** `OPENAI_MODEL`(gpt-4o-mini) 재사용, 전용 모델
   분리는 하지 않음. 동시 호출은 `SECONDARY_FILTERING_JUDGE_CONCURRENCY_LIMIT`
   (기본 10) 세마포어로 제한.
4. **`extra_facts`(사용자 채팅 답변) 도입 여부** — **Non-goal로 확정, 미도입.**
   아래 "이번 변경에 포함하지 않는 것" 참고.
5. **캐싱 여부** — **아직 미해결, 의도적 보류.** 현재 `judge_criteria()`는
   매 `run_matching()` 호출마다(=사용자가 매칭을 다시 돌릴 때마다) 상위 K건
   전부 재판정한다(캐싱 없음). 2026-07-15 기준으로도 결정되지 않았고, 2차
   필터링 완료 범위(1차 하드필터와의 연동)와는 별개의 후속 과제로 남긴다 —
   구현하려면 공고+사업계획서+기업프로필 조합을 캐시 키로 삼아야 하는데,
   기업 프로필은 사용자가 언제든 수정할 수 있어 임베딩과 달리 "성공하면
   영구 캐싱"이 그대로 적용되지 않는다(무효화 조건을 새로 설계해야 함).

## 이번 변경에 포함하지 않는 것 (Non-goals)

- Neo4j/그래프 DB 도입 — 정규화 JSON의 구조화 필드로 충분히 대체 가능.
- LangGraph 등 오케스트레이션 프레임워크 도입 — 기존 순차 `await` 체인 유지.
- 채팅 기반 추가 정보 수집 플로우(`extra_facts`) — 별도 기능이라 이번 범위 밖.
- `_eligibility_score`(정규화 JSON 필드 기반 손규칙 점수) 자체의 제거 —
  1차 필터링 단계 로직은 그대로 두고, 4단계(2차 필터링)만 이번에 바꾼다.
- **"1차 필터링 후보를 자동으로 뽑아 OCR 배치를 트리거하는 로직" 신설** —
  위 "OCR은 언제, 어떻게 반영되는가" 절에서 확인했듯 이 연결 고리(구조화
  필드 narrowing → OCR 배치 자동 트리거)는 현재 코드에 없고, 지금은 사람이
  수동으로 개입해서 채운다. 이번 가이드는 그 수동 과정을 거쳐 이미
  정규화된 공고만 다루는 2차 필터링(LLM judge)만 개선하고, 그 앞단
  자동화는 완전히 별개의 설계로 남겨둔다.
