import { Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { PATHS } from '../../routes/paths'

const NAV_LINKS = ['서비스 소개', '이용 방법', '지원 형식', '자주 묻는 질문']

const STATS = [
  { value: '23만+', label: '누적 분석 계획서' },
  { value: '8종', label: '지원 문서 형식' },
  { value: '1~2분', label: '평균 분석 시간' },
]

const LOGO_STRIP = ['기업마당', 'K-Startup']

const STEPS = [
  {
    title: '계획서 업로드',
    desc: 'PDF·DOCX·PPTX·HWP·이미지 어떤 형식이든 끌어다 놓으면 됩니다.',
  },
  {
    title: 'AI 내용 분석',
    desc: '텍스트·표·이미지를 추출하고 분야와 핵심 내용을 표준화합니다.',
  },
  {
    title: '자격·적합도 매칭',
    desc: '자격요건을 대조해 0~100 적합도 점수와 추천 근거를 산출합니다.',
  },
  {
    title: '맞춤 공고 추천',
    desc: '적합도 순으로 공고를 추천하고 보고서·챗봇으로 의사결정을 돕습니다.',
    highlighted: true,
  },
]



export function LandingPage() {
  const navigate = useNavigate()
  const goToUpload = () => navigate(PATHS.COMPANY_PROFILE)

  return (
    <div className="flex-1 bg-white text-[#15181c]">
      <nav className="flex h-16 items-center gap-8 border-b border-[#ececf0] px-10">
        <div className="flex items-center gap-[9px]">
          <span className="flex h-[30px] w-[30px] items-center justify-center rounded-md bg-[#15181c] text-sm font-extrabold text-white">
            K
          </span>
          <span className="text-lg font-extrabold tracking-[-0.4px]">
            KGVendingMachine
          </span>
        </div>
        <div className="flex gap-[26px] text-sm font-medium text-[#5b6168]">
          {NAV_LINKS.map((link) => (
            <span key={link}>{link}</span>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3">
          <button
            type="button"
            className="flex h-[38px] cursor-pointer items-center gap-[7px] rounded-md bg-kakao px-4 text-sm font-bold text-kakao-ink"
            onClick={() => navigate(PATHS.LOGIN)}
          >
            <span className="h-4 w-4 rounded bg-kakao-ink opacity-85" />
            카카오로 시작
          </button>
        </div>
      </nav>

      <section className="border-b border-[#ececf0] bg-[linear-gradient(180deg,#fafbfc,#fff)]">
        <div className="mx-auto grid max-w-7xl grid-cols-[1.1fr_0.9fr] items-center gap-14 px-[60px] pt-20 pb-[88px]">
          <div>
            <div className="mb-[22px] inline-flex h-[30px] items-center gap-2 rounded-full bg-primary-soft px-3 text-[13px] font-semibold text-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              매일 갱신되는 정부지원 공고 2,400+건
            </div>
            <div className="mb-[18px] text-[44px] leading-[1.18] font-extrabold tracking-[-1.2px]">
              사업계획서 한 장으로
              <br />
              맞는 <em className="text-primary not-italic">정부지원사업</em>을
              <br />
              찾아드립니다
            </div>
            <div className="mb-[30px] max-w-[440px] text-[17px] leading-[1.65] text-[#5b6168]">
              PDF·HWP·PPT 어떤 형식이든 올리면 AI가 내용을 분석해 자격이 맞는
              공고를 적합도 순으로 추천해요. 흩어진 공고를 직접 찾아 헤맬
              필요가 없습니다.
            </div>
            <div className="flex items-center gap-[26px]">
              {STATS.map((stat, index) => (
                <Fragment key={stat.label}>
                  {index > 0 ? (
                    <div className="h-[34px] w-px bg-[#e4e7eb]" />
                  ) : null}
                  <div>
                    <div className="text-[25px] font-extrabold">
                      {stat.value}
                    </div>
                    <div className="text-[13px] text-[#868d95]">
                      {stat.label}
                    </div>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-[#e6e9ed] bg-white p-[34px] shadow-[0_8px_30px_rgba(20,30,50,0.06)]">
            <div className="text-xl font-extrabold tracking-[-0.4px]">
              3초 만에 시작하기
            </div>
            <div className="mt-2 text-sm leading-[1.55] text-[#5b6168]">
              카카오 계정으로 로그인하면 바로 분석을 시작할 수 있어요. 별도
              가입 절차가 없습니다.
            </div>
            <button
              type="button"
              className="mt-6 flex h-[54px] w-full cursor-pointer items-center justify-center gap-[9px] rounded-lg bg-kakao text-base font-bold text-kakao-ink"
              onClick={() => navigate(PATHS.LOGIN)}
            >
              <span className="h-5 w-5 rounded-[5px] bg-kakao-ink opacity-85" />
              카카오로 3초 만에 시작하기
            </button>
            <div className="my-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-[#ececf0]" />
              <span className="text-xs text-[#aab0b7]">간편하고 안전하게</span>
              <div className="h-px flex-1 bg-[#ececf0]" />
            </div>
            <div className="flex flex-col gap-[11px]">
              <div className="flex items-start gap-2.5 text-[13px] leading-[1.5] text-[#454b52]">
                <span className="font-extrabold text-success">✓</span> 카카오
                OAuth 인증 — 비밀번호를 따로 만들 필요 없음
              </div>
              <div className="flex items-start gap-2.5 text-[13px] leading-[1.5] text-[#454b52]">
                <span className="font-extrabold text-success">✓</span> 업로드한
                사업계획서는 분석 용도로만 사용
              </div>
              <div className="flex items-start gap-2.5 text-[13px] leading-[1.5] text-[#454b52]">
                <span className="font-extrabold text-success">✓</span> 언제든
                연결 해제 및 데이터 삭제 가능
              </div>
            </div>
            <div className="mt-5 text-center text-[11px] leading-[1.6] text-[#aab0b7]">
              시작 시 <u>이용약관</u> 및 <u>개인정보처리방침</u>에 동의하게
              됩니다
            </div>
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-9 border-b border-[#ececf0] px-[60px] py-7">
        <span className="text-[13px] font-semibold text-[#aab0b7]">
          공공 데이터 연동
        </span>
        {LOGO_STRIP.map((name) => (
          <span className="text-base font-bold text-[#c2c7cd]" key={name}>
            {name}
          </span>
        ))}
      </div>

      <section className="border-b border-[#ececf0] bg-[#fafbfc] px-[60px] py-[76px]">
        <div className="text-center">
          <div className="text-[13px] font-bold tracking-[0.5px] text-primary">
            HOW IT WORKS
          </div>
          <div className="mt-2.5 mb-12 text-center text-[32px] font-extrabold tracking-[-0.8px]">
            올리면 끝, 4단계로 추천까지
          </div>
        </div>
        <div className="mx-auto grid max-w-7xl grid-cols-4 gap-[18px]">
          {STEPS.map((step, index) => (
            <div
              className="rounded-[10px] border border-[#e6e9ed] bg-white p-6"
              key={step.title}
            >
              <div
                className={
                  step.highlighted
                    ? 'mb-4 flex h-[38px] w-[38px] items-center justify-center rounded-lg bg-primary font-extrabold text-white'
                    : 'mb-4 flex h-[38px] w-[38px] items-center justify-center rounded-lg bg-[#15181c] font-extrabold text-white'
                }
              >
                {index + 1}
              </div>
              <div className="mb-2 text-[17px] font-extrabold">
                {step.title}
              </div>
              <div className="text-[13.5px] leading-[1.6] text-[#5b6168]">
                {step.desc}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="border-b border-[#ececf0] px-[60px] py-[76px]">
        <div className="mx-auto grid max-w-7xl grid-cols-2 items-center gap-14">
          <div>
            <div className="text-[13px] font-bold tracking-[0.5px] text-primary">
              근거 있는 추천
            </div>
            <div className="mt-3 mb-4 text-[29px] leading-[1.3] font-extrabold tracking-[-0.7px]">
              왜 추천했는지
              <br />
              근거까지 보여드려요
            </div>
            <div className="mb-5 text-[15.5px] leading-[1.7] text-[#5b6168]">
              단순 키워드 매칭이 아닙니다. 공고의 자격요건과 내 계획서 내용을
              한 줄씩 대조해, 점수의 근거가 되는 문장을 함께 제시합니다.
            </div>
            <div className="flex flex-col gap-[11px]">
              <div className="flex gap-2.5 text-sm text-[#454b52]">
                <span className="font-extrabold text-primary">·</span> 분야·자격·사업정합
                항목별 점수 분해
              </div>
              <div className="flex gap-2.5 text-sm text-[#454b52]">
                <span className="font-extrabold text-primary">·</span> 출처(공고문
                페이지·계획서 문단) 표기
              </div>
              <div className="flex gap-2.5 text-sm text-[#454b52]">
                <span className="font-extrabold text-primary">·</span> 자부담·결격
                등 주의사항 사전 안내
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-[#e6e9ed] bg-[#fafbfc] p-6">
            <div className="rounded-lg border border-[#e6e9ed] bg-white p-[18px]">
              <div className="flex items-start justify-between">
                <div>
                  <span className="rounded bg-primary-soft px-2 py-[3px] text-[11px] font-bold text-primary">
                    제조 · D-6
                  </span>
                  <div className="mt-2.5 text-base font-extrabold">
                    2025 스마트공장 구축 지원사업
                  </div>
                  <div className="mt-[3px] text-[12.5px] text-[#868d95]">
                    중소벤처기업부 · 최대 1.2억원
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-3xl font-extrabold text-success">
                    94
                  </div>
                  <div className="text-[10px] text-[#aab0b7]">적합도</div>
                </div>
              </div>
              <div className="mt-3.5 flex flex-col gap-2">
                <div className="border-l-2 border-success pl-[9px] text-xs leading-[1.5] text-[#454b52]">
                  제조·소기업 자격요건 모두 충족
                </div>
                <div className="border-l-2 border-success pl-[9px] text-xs leading-[1.5] text-[#454b52]">
                  '설비 자동화' 목표가 사업 취지와 일치
                </div>
                <div className="border-l-2 border-warning pl-[9px] text-xs leading-[1.5] text-[#454b52]">
                  자부담 30% 매칭 필요 — 자금계획 확인
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-[#ececf0] px-[60px] py-[76px] text-center">
        <div className="text-[13px] font-bold tracking-[0.5px] text-primary">
          한국 환경에 맞춤
        </div>
        <div
          className="mt-2.5 mb-12 text-center text-[32px] font-extrabold tracking-[-0.8px]"
          style={{ marginBottom: 10 }}
        >
          HWP까지 완벽 대응하는 문서 처리
        </div>
        <div className="mx-auto mb-10 max-w-[560px] text-[15px] leading-[1.6] text-[#5b6168]">
          스캔본은 OCR로, 텍스트 적은 PPT는 이미지까지 읽어 분석합니다. 한글
          (HWP) 사업계획서도 그대로 올리면 됩니다.
        </div>
   
      </section>

      <section className="bg-[#15181c] px-[60px] py-20 text-center">
        <div className="mb-3.5 text-4xl leading-[1.25] font-extrabold tracking-[-1px] text-white">
          놓치고 있던 지원사업,
          <br />
          지금 1분이면 확인합니다
        </div>
        <div className="mb-8 text-base text-[#9aa1a9]">
          카카오 로그인하고 사업계획서만 올리면 됩니다. 비용은 들지 않아요.
        </div>
        <button
          type="button"
          className="mt-6 flex h-[54px] w-full cursor-pointer items-center justify-center gap-[9px] rounded-lg bg-kakao text-base font-bold text-kakao-ink"
          style={{ width: 'auto', padding: '0 32px', margin: '0 auto' }}
          onClick={goToUpload}
        >
          <span className="h-5 w-5 rounded-[5px] bg-kakao-ink opacity-85" />
          카카오로 시작하기
        </button>
      </section>

      <footer className="flex flex-wrap items-center gap-5 border-t border-[#2a2e34] bg-[#15181c] px-[60px] py-8">
        <span className="text-[15px] font-extrabold text-white">
          KGVendingMachine
        </span>
        <span className="text-[12.5px] text-[#6b7178]">
          이용약관 · 개인정보처리방침 · 고객문의
        </span>
        <span className="ml-auto text-[12.5px] text-[#6b7178]">
          © 2026 KGVendingMachine. 공공데이터 기반 정부지원사업 매칭 서비스
        </span>
      </footer>
    </div>
  )
}
