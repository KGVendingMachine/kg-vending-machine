import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  getMyCompanyProfile,
  saveMyCompanyProfile,
  type CompanyProfileUpdate,
} from '../../api/companyProfile'
import {
  BUSINESS_TYPES,
  COMPANY_STAGES,
  KSIC_INDUSTRIES,
  REGIONS,
} from '../../constants/companyProfileOptions'
import { PATHS } from '../../routes/paths'

const FIELD_LABEL_CLASS = 'mb-1.5 block text-xs text-muted'
const FIELD_INPUT_CLASS =
  'h-[42px] w-full rounded border border-border-strong bg-white px-3 text-sm text-ink disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-faint'

export function CompanyProfilePage() {
  const navigate = useNavigate()
  const location = useLocation()
  // state가 없으면(랜딩 → 온보딩 진입) 기존대로 업로드 화면으로 이어진다.
  // 분석 페이지(매칭 전 확인 모달)에서 온 경우 businessPlanId를 함께 받는데,
  // 분석 페이지는 이 값을 router state로 요구하므로 복귀할 때 그대로 되돌려
  // 보내야 업로드 페이지로 튕기지 않는다.
  const navState = location.state as
    | { from?: string; businessPlanId?: number }
    | null
  const returnTo = navState?.from ?? PATHS.UPLOAD
  const returnState =
    navState?.businessPlanId != null
      ? { state: { businessPlanId: navState.businessPlanId } }
      : undefined
  const [representativeName, setRepresentativeName] = useState('')
  const [businessRegistrationNumber, setBusinessRegistrationNumber] = useState('')
  const [businessType, setBusinessType] = useState('')
  const [companyStage, setCompanyStage] = useState('')
  const [industryCode, setIndustryCode] = useState('')
  const [region, setRegion] = useState('')
  const [foundedYear, setFoundedYear] = useState('')
  const [employeeCount, setEmployeeCount] = useState('')
  const [annualRevenue, setAnnualRevenue] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  /** 수정 화면 진입 시 기존에 저장된 프로필을 불러와 폼에 채운다. */
  useEffect(() => {
    let cancelled = false
    async function loadProfile() {
      try {
        const profile = await getMyCompanyProfile()
        if (cancelled || !profile) return
        setRepresentativeName(profile.representative_name ?? '')
        setBusinessRegistrationNumber(profile.business_registration_number ?? '')
        setBusinessType(profile.business_type ?? '')
        setCompanyStage(profile.company_stage ?? '')
        setIndustryCode(profile.industry_code ?? '')
        setRegion(profile.region_name ?? '')
        setFoundedYear(
          profile.founded_date ? String(new Date(profile.founded_date).getFullYear()) : '',
        )
        setEmployeeCount(
          profile.employee_count != null ? String(profile.employee_count) : '',
        )
        setAnnualRevenue(
          profile.annual_revenue != null
            ? String(profile.annual_revenue / 100_000_000)
            : '',
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadProfile()
    return () => {
      cancelled = true
    }
  }, [])

  /** 예비창업자는 사업자등록 전이므로 등록번호·설립연도·근로자수·매출·기업단계 입력이 무의미하다. */
  const isPreFounder = businessType === '예비창업자'
  const stageOptions = isPreFounder ? [] : COMPANY_STAGES

  function handleBusinessTypeChange(value: string) {
    setBusinessType(value)
    if (value === '예비창업자') {
      setCompanyStage('')
      setBusinessRegistrationNumber('')
      setFoundedYear('')
      setEmployeeCount('')
      setAnnualRevenue('')
    }
  }

  function handleSkip() {
    navigate(returnTo, returnState)
  }

  /**
   * 비운 필드는 payload에서 빼서 부분 갱신되게 한다. 설립연도(연도→날짜)와
   * 지역(이름→행정코드) 변환은 서버가 담당하고, 매출액만 억원→원으로 환산해
   * 보낸다.
   */
  async function handleSave() {
    const payload: CompanyProfileUpdate = {}
    if (representativeName.trim())
      payload.representative_name = representativeName.trim()
    if (businessRegistrationNumber.trim())
      payload.business_registration_number = businessRegistrationNumber.trim()
    if (businessType) payload.business_type = businessType
    if (companyStage) payload.company_stage = companyStage
    if (industryCode) payload.industry_code = industryCode
    if (region) payload.region_name = region
    const year = Number(foundedYear)
    if (foundedYear.trim() && Number.isInteger(year)) payload.founded_year = year
    const employees = Number(employeeCount)
    if (employeeCount.trim() && Number.isFinite(employees))
      payload.employee_count = Math.round(employees)
    const revenueEok = Number(annualRevenue)
    if (annualRevenue.trim() && Number.isFinite(revenueEok) && revenueEok >= 0)
      payload.annual_revenue = Math.round(revenueEok * 100_000_000)

    setSaving(true)
    try {
      await saveMyCompanyProfile(payload)
    } finally {
      setSaving(false)
    }
    navigate(returnTo, returnState)
  }

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-[520px] max-w-full rounded-lg border border-border bg-white p-11 shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
          <div className="text-[22px] font-extrabold tracking-[-0.5px]">
            기업 프로필을 알려주세요
          </div>
          <div className="mt-1.5 text-sm leading-normal text-muted">
            정확한 매칭을 위해 몇 가지만 입력해주세요. 선택 입력이며, 비워두면
            사업계획서에서 자동으로 채워요.
          </div>

          <div className="mt-7 flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={FIELD_LABEL_CLASS}>대표자명</label>
                <input
                  className={FIELD_INPUT_CLASS}
                  value={representativeName}
                  placeholder="예: 홍길동"
                  onChange={(event) => setRepresentativeName(event.target.value)}
                />
              </div>
              <div>
                <label className={FIELD_LABEL_CLASS}>사업자등록번호</label>
                <input
                  className={FIELD_INPUT_CLASS}
                  value={businessRegistrationNumber}
                  placeholder="예: 000-00-00000"
                  disabled={isPreFounder}
                  onChange={(event) =>
                    setBusinessRegistrationNumber(event.target.value)
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={FIELD_LABEL_CLASS}>사업자 유형</label>
                <select
                  className={FIELD_INPUT_CLASS}
                  value={businessType}
                  onChange={(event) =>
                    handleBusinessTypeChange(event.target.value)
                  }
                >
                  <option value="">선택 안 함</option>
                  {BUSINESS_TYPES.map((type) => (
                    <option value={type} key={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={FIELD_LABEL_CLASS}>기업 단계</label>
                <select
                  className={FIELD_INPUT_CLASS}
                  value={companyStage}
                  disabled={isPreFounder}
                  onChange={(event) => setCompanyStage(event.target.value)}
                >
                  <option value="">선택 안 함</option>
                  {stageOptions.map((stage) => (
                    <option value={stage} key={stage}>
                      {stage}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className={FIELD_LABEL_CLASS}>업종 (한국표준산업분류)</label>
              <select
                className={FIELD_INPUT_CLASS}
                value={industryCode}
                onChange={(event) => setIndustryCode(event.target.value)}
              >
                <option value="">선택 안 함</option>
                {KSIC_INDUSTRIES.map((industry) => (
                  <option value={industry.code} key={industry.code}>
                    {industry.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={FIELD_LABEL_CLASS}>지역</label>
              <select
                className={FIELD_INPUT_CLASS}
                value={region}
                onChange={(event) => setRegion(event.target.value)}
              >
                <option value="">시/도 선택</option>
                {REGIONS.map((name) => (
                  <option value={name} key={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={FIELD_LABEL_CLASS}>설립연도</label>
                <input
                  className={FIELD_INPUT_CLASS}
                  value={foundedYear}
                  placeholder="예: 2021"
                  disabled={isPreFounder}
                  onChange={(event) => setFoundedYear(event.target.value)}
                />
              </div>
              <div>
                <label className={FIELD_LABEL_CLASS}>상시근로자 수</label>
                <input
                  className={FIELD_INPUT_CLASS}
                  value={employeeCount}
                  placeholder="예: 15"
                  disabled={isPreFounder}
                  onChange={(event) => setEmployeeCount(event.target.value)}
                />
              </div>
            </div>
            <div>
              <label className={FIELD_LABEL_CLASS}>매출액 (억원)</label>
              <input
                className={FIELD_INPUT_CLASS}
                value={annualRevenue}
                placeholder="예: 12"
                disabled={isPreFounder}
                onChange={(event) => setAnnualRevenue(event.target.value)}
              />
              <p className="mt-1.5 text-xs text-faint">
                업종·매출로 중소기업 여부를 자동 판정해요. 규모는 따로 고르지
                않아도 됩니다.
              </p>
            </div>
            <div className="rounded bg-surface-subtle p-3 text-xs leading-[1.6] text-faint">
              입력값은 계획서에서 추출한 정보를 보완하는 데 쓰여요. 비워두면
              문서에서 자동 추론합니다.
            </div>
          </div>

          <div className="mt-8 flex justify-end gap-2.5">
            <button
              type="button"
              className="h-[46px] cursor-pointer rounded border border-border-strong bg-white px-[22px] text-[15px] font-semibold text-muted"
              onClick={handleSkip}
            >
              건너뛰기
            </button>
            <button
              type="button"
              className="h-[46px] cursor-pointer rounded border-0 bg-primary px-7 text-[15px] font-bold text-white"
              onClick={handleSave}
              disabled={saving || loading}
            >
              {saving ? '저장 중…' : loading ? '불러오는 중…' : '저장하고 계속 →'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
