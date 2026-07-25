# 1차 필터링 (기업 기준 공고 하드필터) — 설계/핸드오프

> 이 문서 하나로 새 세션이 맥락 없이 이어서 구현할 수 있도록 정리한 핸드오프.
> 관련 파이프라인: [matching-pipeline.md](matching-pipeline.md)(기존 소프트 매칭),
> [secondary-filtering-llm-judge-guide.md](secondary-filtering-llm-judge-guide.md).

## 0. 목표

기업(사용자) 프로필을 입력으로, **하드필터를 통과한 `notice.id[]`를 반환**하는 API를 만든다.
필터 축은 4개: **① 지역 ② 대상(기업형태) 게이트 ③ 업력 ④ 당일 기준 신청기간**.

기존 [`matching_service.py`](../backend/app/services/matching_service.py)의 `_eligibility_score`는
"점수화/감점"(soft)일 뿐 탈락(hard)이 아니다. 이 작업은 **명시적 탈락 후 id 목록 반환**이라
목적이 다르다. (2차 필터링/임베딩/LLM 판정과도 별개의 앞단.)

## 1. 확정된 핵심 원칙

- **기업측 데이터 소스 = `company_profile` 단일 기준.** 업력·기업형태만 값이 비면
  `business_plan.analysis_json`으로 폴백. **지역은 폴백 없음**(아래 근거 참조).
- **공고측 = 수집 시 이미 구조화된 테이블/컬럼 사용** (`notice_region`,
  `notice_target_type`, `notice.application_*`, `notice.status`). 예외: **업력만**
  kstartup 원문 `biz_enyy`를 파싱해야 함(구조화 안 돼 있음).
- **제한 정보가 없으면 통과(permissive).** 공고에 해당 축 제한이 없거나 기업측 값이
  없으면 그 축에서는 탈락시키지 않는다. (제한이 "있을 때"만 대조해서 탈락.)
- 개인/법인 구분은 **하드 게이트가 아님**(데이터로만 보관). 개인사업자도 중소기업·
  창업기업·소상공인일 수 있어 대부분 공고에서 배제 대상이 아니다.

## 2. 데이터 모델 (관련 부분)

- 공고: [`Notice`](../backend/app/models/notice.py) — `external_id`(원문 키),
  `application_start_date/end_date`, `status`(모집중/마감/예정/확인필요),
  `is_actionable`, **`target_business_years_max`(스키마에 있으나 현재 미채움 — 업력용으로 채울 예정)**.
- 공고 자식: `NoticeRegion`(region_code 행정표준코드 앞2자리, 전국=ALL),
  `NoticeTargetType`(target_type 자유서술).
- 원문: [`KstartupRaw`/`BizinfoRaw`](../backend/app/models/raw.py) — `key`=external_id,
  `field`=JSON 원문 문자열(json.dumps), `notice_id`.
- 기업: [`CompanyProfile`](../backend/app/models/company.py) — `region_code`,
  `business_type`(개인사업자/법인사업자/예비창업자), `company_stage`(예비창업/초기창업/도약/소상공인),
  `company_size`(소/중/중견), `founded_date`, `business_years`.
- 사업계획서: [`BusinessPlan.analysis_json`](../backend/app/models/business_plan.py) →
  [`NormalizedBusinessPlanSchema`](../backend/app/schemas/business_plan.py). **주의:
  `CompanyInfo`에 region 필드가 아예 없음.** `founded_year`,
  `business_registration_status`만 폴백 가능.

### 원문 필드 매핑 (수집 파서 기준)

| 축 | kstartup 원문 키 | bizinfo 원문 키 | 구조화 위치 |
|----|-----------------|----------------|-----------|
| 지역 | `supt_regin` | `hashtags`(지역명 섞임) | `notice_region` |
| 대상 | `aply_trgt` | `trgetNm` | `notice_target_type` |
| 업력 | **`biz_enyy`** | (없음) | **미구조화 → 채울 것** |
| 기간 | `pbanc_rcpt_bgng_dt`/`pbanc_rcpt_end_dt`, `rcrt_prgs_yn` | `reqstBeginEndDe` | `application_*`, `status` |
| 키 | `pbanc_sn` | `pblancId` | `external_id` |

수집 진입점: [`_process_kstartup_item`](../backend/app/services/notice_collection_service.py),
[`_process_bizinfo_item`](../backend/app/services/notice_collection_service.py).
지역 파서: `_parse_regions`(kstartup), `_parse_bizinfo_regions`(bizinfo),
사전 `REGION_CODE_BY_NAME`.

## 3. 축별 규칙 (전부 permissive)

### ① 지역
- 기업 `company_profile.region_code = R`.
- 공고 통과: `notice_region` 비어있음 **또는** `ALL` 포함 **또는** `R` 포함.
- 그 외(특정지역인데 R 없음) → 탈락. `R`이 없으면(프로필 미입력) 필터 못 하므로 통과.
- **파서 수정 불필요.** 실측(아래 §5)으로 `notice_region`이 신뢰 가능하게 채워져 있음 확인.

### ② 대상(기업형태) 게이트 — 2분류
- **회사측 값 불필요.** 공고 target_type만 본다.
- **비기업전용 집합** = `{청소년, 대학생, 대학, 연구기관}`.
- 규칙: `notice_target_type`이 비어있음 → 통과. 값이 있고 **전부** 비기업전용 →
  **탈락**. 그 외(기업가능 값이 하나라도 있으면) → 통과.
- 미지의 새 값은 기본 "기업가능"으로 취급(블록리스트만 관리 → 오탈락 방지).
- **후순위 개선(오픈 이슈)**: bizinfo는 `trgetNm`이 대부분 비어있지만 `hashtags`에
  `중소기업/소상공인/중견기업/벤처기업/사회적기업/개인사업자` 신호가 있음. 필요 시
  hashtags에서 기업형태를 추출해 `notice_target_type`에 병합하면 커버리지 향상.
  permissive라 필수는 아님.

### ③ 업력 — kstartup `biz_enyy`, 해석 A(누적 상한)
`biz_enyy` = 콤마 구분. 토큰: `예비창업자` + `1·2·3·5·7·10년미만`.

**파싱(해석 A — 확정):**
```
allow_prestartup = ("예비창업자" in tokens)
year_ceilings    = [N for "N년미만" in tokens]
max_years        = max(year_ceilings) if year_ceilings else None
```
**기업 판정:**
- 기업이 예비창업(등록 전) → `allow_prestartup` 일 때만 통과.
- 기업이 기창업(업력 y) → `max_years is not None` 이고 `y < max_years` 이면 통과.
  (`max_years is None` = 공고가 "예비창업자"만 대상 → 기창업 **탈락**.)
- `biz_enyy` 없음/빈값(bizinfo 전부, kstartup 일부) → **통과(permissive)**.

**기업측 예비/업력 도출:**
- `is_prestartup` = `business_type == "예비창업자"` 또는 `company_stage == "예비창업"`
  (폴백: `analysis_json.company.business_registration_status`).
- `business_years` = `company_profile.business_years` 우선, 없으면 `founded_date`로 계산
  (`today - founded_date`, 만나이식 내림), 없으면 `analysis_json.company.founded_year`.
- 업력을 못 구하고 예비도 아니면 → 업력 축 permissive 통과.

> 해석 A 선택 이유 & 리스크: 작성자마다 "상한만(예: `7년미만`)" vs "전부 나열
> (`1,2,3,5,7년미만`)"이 섞여 일관성이 없어, 최댓값을 상한으로 보는 A가 가장 견고.
> 이산 구간(B)으로 읽으면 `예비창업자,7년미만`이 "예비 or 5~7년차"라는 이상한 뜻이 됨.
> A의 리스크: 하한 있는 "도약(3~7년)" 류 공고에서 어린 기업 과다포함 → 드물고
> permissive 원칙에 부합하므로 수용.

### ④ 기간 — 당일 기준
- 통과: `status == '모집중'` **또는** (`application_start_date <= today` **그리고**
  (`application_end_date is null` **또는** `application_end_date >= today`)).
- `status == '마감'`/`예정`은 탈락. `상시모집`은 수집 시 `status='모집중'`/
  `is_actionable=True`로 이미 처리됨(`_is_rolling_open`).
- **주의(staleness)**: status/is_actionable은 수집 시점 계산값이라 시간이 지나면
  낡을 수 있음. `refresh_notice_statuses`(이미 존재)를 주기 실행해야 최신. 필터에서
  날짜를 직접 비교하면 status 낡음의 영향을 줄일 수 있음.

## 4. API 계약 (안)

```
GET /api/v1/company-profiles/{profile_id}/eligible-notices
  (인증 사용자의 프로필 소유 확인 필요. /me 변형도 고려 가능)

200 응답:
{
  "notice_ids": [123, 456, ...],
  "counts": {
    "input": N,          // 후보 공고 수
    "지역_탈락": a,
    "대상_탈락": b,
    "업력_탈락": c,
    "기간_탈락": d,
    "통과": p
  }
}
```
계층(백엔드 규약, [backend/CLAUDE.md](../backend/CLAUDE.md)):
`router → notice_eligibility_service → notice_eligibility_repository`.
라우터 등록은 `app/api/v1/router.py`에만.

## 5. 실측 데이터 (박제 — 재조회 없이 근거로 사용)

운영 DB는 임의로 건드리지 않는다([backend/CLAUDE.md] DB 경계). 아래는 사용자가
읽기전용 쿼리로 뽑아준 스냅샷.

### 5.1 `notice_target_type` 분포 (값 / 기업마당 / kstartup / 합계)
```
일반기업        0    1659  1659   ← kstartup: 담요 태그(변별력 낮음)
1인 창조기업    0    1168  1168
일반인          0    1127  1127
대학생          0    1002  1002   ← 비기업전용
연구기관        0     860   860   ← 비기업전용
대학            0     851   851   ← 비기업전용
청소년          0     697   697   ← 비기업전용
중소기업       132      0   132   ← 기업마당 trgetNm: 진짜 기업형태
소상공인        52      0    52
사회적기업       9      0     9
창업벤처         4      0     4
장애인기업       1      0     1
```
해석: kstartup은 대상 청중(변별력 낮음), 기업마당은 기업형태지만 **~198건뿐**
(전체 대비 대부분 비어있음). → 세밀한 기업형태 하드필터는 불가, "2분류 게이트"로 결정.

### 5.2 `biz_enyy` 분포 (kstartup, 상위)
```
예비창업자,1년미만,2년미만,3년미만,5년미만,7년미만,10년미만   467
1년미만,2년미만,3년미만,5년미만,7년미만,10년미만              307
7년미만                                                     236
예비창업자,1년미만,2년미만,3년미만,5년미만,7년미만            144
예비창업자                                                  124
예비창업자,1년미만,2년미만,3년미만                            82
10년미만                                                     65
예비창업자,7년미만                                            63
... (하위 생략; 5·7·10년미만 조합, 3년미만 단독 등 다양)
```
→ 상한만 쓰는 케이스와 전부 나열 케이스가 혼재 → 해석 A(누적 상한) 채택.

### 5.3 기업마당 `hashtags` 지역 구조
구조 = `[0]=금융(대분류 고정), 그 뒤 지역(들), 기타 태그`. 단 중분류
(`창업/경영/수출`)가 끼면 지역이 뒤로 밀림:
```
금융,서울,서울특별시,...              ← 지역 index 1
금융,창업,경영,전남,...               ← 지역 index 3
금융,경영,경남,...                    ← 지역 index 2
금융,수출,경기,...                    ← 지역 index 2
금융,서울,부산,대구,...,제주,...       ← 전국(17개 나열) → ALL
```
→ **위치기반(pos2) 추출은 ~15% 실패.** 현행 `_parse_bizinfo_regions`의
"모든 태그를 REGION_CODE_BY_NAME과 대조" 방식이 정답(다지역·전국 판정 포함).
시·군 태그(여수시 등)는 광역 사전에 없어 무시되지만 같은 공고에 광역명이 함께 있음.

### 5.4 업로드 사업계획서 표본 (필터 소스 아님 — 정규화 파서 픽스처)
- **지역(사업장 소재지)은 두 템플릿 모두 없음** → analysis_json으로 지역 못 채움(§1).
- DIC = 초기창업기업(업력 1~3년) 위주, 사업자구분/설립일 표 있음.
- 광운대 = 예비창업 위주(설립일 없음). → `biz_enyy`에 `예비창업자` 없는 공고에서
  정상 탈락하는지 검증용으로 유용.
- 광운대 PDF는 텍스트 추출 순서가 뒤섞임 → LLM 정규화 품질 검증 필요(별개 이슈).

## 6. 구현 계획 (체크리스트) — **구현 완료 (2026-07-15)**

### Phase 1 — 업력 데이터 구조화 (수집 + 백필)
- [x] `biz_enyy` 파서 추가(해석 A): [`parse_biz_enyy`](../backend/app/services/notice_business_years.py)
      → `(allow_prestartup, max_years) | None`. 제한 정보 없으면 None(permissive).
      단위테스트: [test_notice_business_years.py](../backend/tests/test_notice_business_years.py).
- [x] `notice` 모델에 `target_allows_prestartup: bool | None` 컬럼 추가
      (`target_business_years_max`는 기존 컬럼 재사용 = max_years 저장).
- [x] Alembic 마이그레이션 `b3d9f1c04e27`(로컬 Docker DB 5433에 적용 완료;
      **운영 DB 미적용 — 사용자 요청 대기**).
- [x] `upsert_notice`에 두 값 파라미터 추가, `_process_kstartup_item`에서 채움.
- [x] `backfill_notice_business_years()` 추가 + 라우터
      `POST /internal/notices/backfill-business-years`(로컬 실행 미수행 — 필요 시 호출).

### Phase 2 — 필터 API
- [x] [`notice_eligibility_repository`](../backend/app/repositories/notice_eligibility_repository.py):
      후보 공고 전체 + 지역/대상 자식 테이블을 벌크로 묶어 `NoticeEligibilityRow[]` 반환.
      (축 판정은 축별 탈락 집계 때문에 서비스에서 순차 파이썬 필터로 처리.)
- [x] [`notice_eligibility_service`](../backend/app/services/notice_eligibility_service.py):
      `company_profile`(+analysis_json 폴백)에서 `region_code`, `is_prestartup`,
      `business_years` 도출 → 4축 순차 필터 → counts 집계. 대상 축은 기존
      [`applicant_type_filter`](../backend/app/services/applicant_type_filter.py) 재사용.
- [x] 라우터 `GET /api/eligible-notices/me`(인증 사용자 대표 프로필 기준) + `router.py` 등록.
- [x] 스키마 [`EligibleNoticesResponse`](../backend/app/schemas/notice_eligibility.py).

### Phase 3 — 테스트
- [x] 축별 permissive 경계 + 탈락 귀속 순수 테스트, 기업값 도출 테스트.
- [x] 통합(DB): 예비/초기창업/업력초과·지역 일치/불일치·비기업전용·마감 시나리오.
      [test_notice_eligibility_service.py](../backend/tests/test_notice_eligibility_service.py).
      전체 스위트 412 passed.

## 7. 오픈 이슈 / 미결정
- 대상게이트 bizinfo `hashtags` 기업형태 병합(§3② 후순위). **미구현(permissive라 선택).**
- 해석 A의 하한 있는 공고 과다포함(수용하기로 함).
- 기간 status staleness → `refresh_notice_statuses` 스케줄(별도).
- ~~API 입력을 `profile_id` path vs `/me`~~ → **`/me`(인증 사용자 대표 프로필)로 확정.**
  `company_service.get_my_profile` 재사용 → 남의 프로필 지정 경로가 없어 소유확인 불필요.
- ~~`target_allows_prestartup` 컬럼명/방식~~ → **별도 nullable Boolean 컬럼으로 확정.**
- **대상 축**: 옛 §3② 텍스트(공고값만 봄, 비기업집합 `{청소년·대학생·대학·연구기관}`)
  대신, 이미 구현돼 있던 `applicant_type_filter`를 재사용했다. 이쪽은 실제 사업자
  (개인/법인)에게만 컷을 걸고 예비창업자·미입력은 통과시키며 비기업집합에 `일반인`도
  포함한다(오탈락 방지 목적의 상위호환). 단일 소스로 유지하려 재사용.
- **후보 집합 = 저장된 공고 전부**(기간 축이 파이프라인 안에서 마감/예정을 집계해야
  하므로 상태로 미리 거르지 않음). counts는 순차 필터라 각 `_탈락`은 그 축에서 처음
  걸린 수이고 합이 `input`.
- **마이그레이션 헤드**: 이 브랜치에 동일 부모를 병합한 중복 merge 리비전 2개
  (`ec70d31b6582` 커밋됨, `46d08b0edd5d` untracked)가 있어 head가 둘이었다. 업력 컬럼
  리비전 `b3d9f1c04e27`(← `46d08b0edd5d`)과 `ec70d31b6582`를 병합 리비전
  `6742607b62d0`으로 **통합 완료**(단일 head). 로컬 DB 적용됨. 체인상 `46d08b0edd5d`도
  히스토리에 남으므로 함께 커밋 대상.

## 8. 환경 주의 (필수)
- 코드+로컬 DB만 다룬다. 서버/docker/포트/프로세스 건드리지 말 것.
- `alembic upgrade`는 로컬 Docker DB(5433)에 적용됨. **운영 DB 마이그레이션은 먼저 물어볼 것.**
- 상세: [backend/CLAUDE.md](../backend/CLAUDE.md).
