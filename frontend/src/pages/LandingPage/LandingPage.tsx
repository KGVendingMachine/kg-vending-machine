import { Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { PATHS } from '../../routes/paths'
import styles from './LandingPage.module.css'

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

const FORMATS = [
  { name: 'PDF', desc: '텍스트·스캔' },
  { name: 'HWP', desc: '한글 문서' },
  { name: 'DOCX', desc: '워드' },
  { name: 'PPTX', desc: '비전 분석' },
  { name: '이미지', desc: 'OCR' },
  { name: '스캔본', desc: 'OCR 폴백' },
]

export function LandingPage() {
  const navigate = useNavigate()
  const goToUpload = () => navigate(PATHS.COMPANY_PROFILE)

  return (
    <div className={styles.page}>
      <nav className={styles.nav}>
        <div className={styles.logo}>
          <span className={styles.logoMark}>K</span>
          <span className={styles.logoText}>KGVendingMachine</span>
        </div>
        <div className={styles.navLinks}>
          {NAV_LINKS.map((link) => (
            <span key={link}>{link}</span>
          ))}
        </div>
        <div className={styles.navRight}>
          <button
            type="button"
            className={styles.kakaoButtonSmall}
            onClick={() => navigate(PATHS.LOGIN)}
          >
            <span className={styles.kakaoDotSmall} />
            카카오로 시작
          </button>
        </div>
      </nav>

      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div>
            <div className={styles.badge}>
              <span className={styles.badgeDot} />
              매일 갱신되는 정부지원 공고 2,400+건
            </div>
            <div className={styles.headline}>
              사업계획서 한 장으로
              <br />
              맞는 <em>정부지원사업</em>을
              <br />
              찾아드립니다
            </div>
            <div className={styles.heroDesc}>
              PDF·HWP·PPT 어떤 형식이든 올리면 AI가 내용을 분석해 자격이 맞는
              공고를 적합도 순으로 추천해요. 흩어진 공고를 직접 찾아 헤맬
              필요가 없습니다.
            </div>
            <div className={styles.stats}>
              {STATS.map((stat, index) => (
                <Fragment key={stat.label}>
                  {index > 0 ? <div className={styles.statDivider} /> : null}
                  <div>
                    <div className={styles.statValue}>{stat.value}</div>
                    <div className={styles.statLabel}>{stat.label}</div>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>

          <div className={styles.loginCard}>
            <div className={styles.loginCardTitle}>3초 만에 시작하기</div>
            <div className={styles.loginCardDesc}>
              카카오 계정으로 로그인하면 바로 분석을 시작할 수 있어요. 별도
              가입 절차가 없습니다.
            </div>
            <button
              type="button"
              className={styles.kakaoButtonLarge}
              onClick={() => navigate(PATHS.LOGIN)}
            >
              <span className={styles.kakaoDotLarge} />
              카카오로 3초 만에 시작하기
            </button>
            <div className={styles.orDivider}>
              <div className={styles.line} />
              <span>간편하고 안전하게</span>
              <div className={styles.line} />
            </div>
            <div className={styles.checklist}>
              <div className={styles.checklistItem}>
                <span className={styles.checklistCheck}>✓</span> 카카오 OAuth
                인증 — 비밀번호를 따로 만들 필요 없음
              </div>
              <div className={styles.checklistItem}>
                <span className={styles.checklistCheck}>✓</span> 업로드한
                사업계획서는 분석 용도로만 사용
              </div>
              <div className={styles.checklistItem}>
                <span className={styles.checklistCheck}>✓</span> 언제든 연결
                해제 및 데이터 삭제 가능
              </div>
            </div>
            <div className={styles.loginFootnote}>
              시작 시 <u>이용약관</u> 및 <u>개인정보처리방침</u>에 동의하게
              됩니다
            </div>
          </div>
        </div>
      </section>

      <div className={styles.logoStrip}>
        <span className={styles.logoStripLabel}>공공 데이터 연동</span>
        {LOGO_STRIP.map((name) => (
          <span className={styles.logoStripItem} key={name}>
            {name}
          </span>
        ))}
      </div>

      <section className={`${styles.section} ${styles.sectionSubtle}`}>
        <div className={styles.sectionCenter}>
          <div className={styles.eyebrow}>HOW IT WORKS</div>
          <div className={styles.sectionTitleCenter}>
            올리면 끝, 4단계로 추천까지
          </div>
        </div>
        <div className={styles.steps}>
          {STEPS.map((step, index) => (
            <div className={styles.stepCard} key={step.title}>
              <div
                className={
                  step.highlighted
                    ? `${styles.stepNumber} ${styles.highlighted}`
                    : styles.stepNumber
                }
              >
                {index + 1}
              </div>
              <div className={styles.stepTitle}>{step.title}</div>
              <div className={styles.stepDesc}>{step.desc}</div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.feature}>
          <div>
            <div className={styles.eyebrow}>근거 있는 추천</div>
            <div className={styles.featureTitle}>
              왜 추천했는지
              <br />
              근거까지 보여드려요
            </div>
            <div className={styles.featureDesc}>
              단순 키워드 매칭이 아닙니다. 공고의 자격요건과 내 계획서 내용을
              한 줄씩 대조해, 점수의 근거가 되는 문장을 함께 제시합니다.
            </div>
            <div className={styles.featureList}>
              <div className={styles.featureListItem}>
                <span>·</span> 분야·자격·사업정합 항목별 점수 분해
              </div>
              <div className={styles.featureListItem}>
                <span>·</span> 출처(공고문 페이지·계획서 문단) 표기
              </div>
              <div className={styles.featureListItem}>
                <span>·</span> 자부담·결격 등 주의사항 사전 안내
              </div>
            </div>
          </div>
          <div className={styles.mockCard}>
            <div className={styles.mockCardInner}>
              <div className={styles.mockCardRow}>
                <div>
                  <span className={styles.mockBadge}>제조 · D-6</span>
                  <div className={styles.mockTitle}>
                    2025 스마트공장 구축 지원사업
                  </div>
                  <div className={styles.mockOrg}>
                    중소벤처기업부 · 최대 1.2억원
                  </div>
                </div>
                <div className={styles.mockScore}>
                  <div className={styles.mockScoreValue}>94</div>
                  <div className={styles.mockScoreLabel}>적합도</div>
                </div>
              </div>
              <div className={styles.mockReasons}>
                <div className={styles.mockReason}>
                  제조·소기업 자격요건 모두 충족
                </div>
                <div className={styles.mockReason}>
                  '설비 자동화' 목표가 사업 취지와 일치
                </div>
                <div className={`${styles.mockReason} ${styles.warn}`}>
                  자부담 30% 매칭 필요 — 자금계획 확인
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`}>
        <div className={styles.feature}>
          <div className={styles.chatMock}>
            <div className={styles.chatUserRow}>
              <div className={styles.chatUserBubble}>
                스마트공장 사업, 자부담 없이 신청 가능해?
              </div>
            </div>
            <div className={styles.chatAiRow}>
              <div className={styles.chatAvatar} />
              <div className={styles.chatAiBubble}>
                아니요, 해당 사업은 <b>자부담 30%</b>가 필요해요. 1.2억 기준
                약 3,600만원의 자기부담이 발생합니다.
                <div className={styles.chatSources}>
                  <span className={styles.chatSourceTag}>📄 공고문 p.4</span>
                  <span className={styles.chatSourceTag}>
                    📄 계획서 자금계획
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div>
            <div className={styles.eyebrow}>대화형 도우미</div>
            <div className={styles.featureTitle}>
              궁금한 건 채팅으로
              <br />
              바로 물어보세요
            </div>
            <div className={styles.featureDesc}>
              추천 결과·공고 DB·내 계획서를 근거로 답하는 AI 챗봇이 자격·마감·
              필요서류 등 무엇이든 답해드립니다. 근거가 없는 내용은 추측하지
              않아요.
            </div>
            <div className={styles.featureList}>
              <div className={styles.featureListItem}>
                <span>·</span> 항상 출처를 함께 제시
              </div>
              <div className={styles.featureListItem}>
                <span>·</span> 공고 비교·우선순위 추천
              </div>
              <div className={styles.featureListItem}>
                <span>·</span> 추천 결과를 보고서로 내보내기
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionCenter}`}>
        <div className={styles.eyebrow}>한국 환경에 맞춤</div>
        <div className={styles.sectionTitleCenter} style={{ marginBottom: 10 }}>
          HWP까지 완벽 대응하는 문서 처리
        </div>
        <div className={styles.sectionDesc}>
          스캔본은 OCR로, 텍스트 적은 PPT는 이미지까지 읽어 분석합니다. 한글
          (HWP) 사업계획서도 그대로 올리면 됩니다.
        </div>
        <div className={styles.formats}>
          {FORMATS.map((format) => (
            <div className={styles.formatCard} key={format.name}>
              <div className={styles.formatName}>{format.name}</div>
              <div className={styles.formatDesc}>{format.desc}</div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.finalCta}>
        <div className={styles.finalCtaTitle}>
          놓치고 있던 지원사업,
          <br />
          지금 1분이면 확인합니다
        </div>
        <div className={styles.finalCtaDesc}>
          카카오 로그인하고 사업계획서만 올리면 됩니다. 비용은 들지 않아요.
        </div>
        <button type="button" className={styles.kakaoButtonLarge} style={{ width: 'auto', padding: '0 32px', margin: '0 auto' }} onClick={goToUpload}>
          <span className={styles.kakaoDotLarge} />
          카카오로 시작하기
        </button>
      </section>

      <footer className={styles.footer}>
        <span className={styles.footerLogo}>KGVendingMachine</span>
        <span className={styles.footerLinks}>
          이용약관 · 개인정보처리방침 · 고객문의
        </span>
        <span className={styles.footerCopyright}>
          © 2026 KGVendingMachine. 공공데이터 기반 정부지원사업 매칭 서비스
        </span>
      </footer>
    </div>
  )
}
