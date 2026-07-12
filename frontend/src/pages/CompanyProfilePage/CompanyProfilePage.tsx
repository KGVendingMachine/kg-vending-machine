import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
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
import styles from './CompanyProfilePage.module.css'

export function CompanyProfilePage() {
  const navigate = useNavigate()
  const [representativeName, setRepresentativeName] = useState('')
  const [businessRegistrationNumber, setBusinessRegistrationNumber] = useState('')
  const [businessType, setBusinessType] = useState('')
  const [companyStage, setCompanyStage] = useState('')
  const [industryCode, setIndustryCode] = useState('')
  const [region, setRegion] = useState('')
  const [foundedYear, setFoundedYear] = useState('')
  const [companySize, setCompanySize] = useState('')
  const [employeeCount, setEmployeeCount] = useState('')
  const [annualRevenue, setAnnualRevenue] = useState('')
  const [saving, setSaving] = useState(false)

  /** 예비창업자는 사업자등록 전이므로 등록번호·설립연도·규모 관련 입력이 무의미하다. */
  const isPreFounder = businessType === '예비창업자'
  const stageOptions = isPreFounder
    ? COMPANY_STAGES.filter((stage) => stage === '예비창업')
    : businessType
      ? COMPANY_STAGES.filter((stage) => stage !== '예비창업')
      : COMPANY_STAGES

  function handleBusinessTypeChange(value: string) {
    setBusinessType(value)
    if (value === '예비창업자') {
      setCompanyStage('예비창업')
      setBusinessRegistrationNumber('')
      setFoundedYear('')
      setCompanySize('')
      setEmployeeCount('')
      setAnnualRevenue('')
    } else if (value && companyStage === '예비창업') {
      setCompanyStage('')
    }
  }

  function goToUpload() {
    navigate(PATHS.UPLOAD)
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
    if (companySize) payload.company_size = companySize
    const employees = Number(employeeCount)
    if (employeeCount.trim() && Number.isFinite(employees))
      payload.employee_count = employees
    const revenueEok = Number(annualRevenue)
    if (annualRevenue.trim() && Number.isFinite(revenueEok) && revenueEok >= 0)
      payload.annual_revenue = Math.round(revenueEok * 100_000_000)

    setSaving(true)
    try {
      await saveMyCompanyProfile(payload)
    } finally {
      setSaving(false)
    }
    navigate(PATHS.UPLOAD)
  }

  return (
    <div className={styles.page}>
      <div className={styles.body}>
        <div className={styles.card}>
          <div className={styles.heading}>기업 프로필을 알려주세요</div>
          <div className={styles.subheading}>
            정확한 매칭을 위해 몇 가지만 입력해주세요. 선택 입력이며, 비워두면
            사업계획서에서 자동으로 채워요.
          </div>

          <div className={styles.formFields}>
            <div className={styles.fieldRow}>
              <div className={styles.field}>
                <label>대표자명</label>
                <input
                  value={representativeName}
                  placeholder="예: 홍길동"
                  onChange={(event) => setRepresentativeName(event.target.value)}
                />
              </div>
              <div className={styles.field}>
                <label>사업자등록번호</label>
                <input
                  value={businessRegistrationNumber}
                  placeholder="예: 000-00-00000"
                  disabled={isPreFounder}
                  onChange={(event) =>
                    setBusinessRegistrationNumber(event.target.value)
                  }
                />
              </div>
            </div>
            <div className={styles.fieldRow}>
              <div className={styles.field}>
                <label>사업자 유형</label>
                <select
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
              <div className={styles.field}>
                <label>기업 단계</label>
                <select
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
            <div className={styles.field}>
              <label>업종 (한국표준산업분류)</label>
              <select
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
            <div className={styles.field}>
              <label>지역</label>
              <select
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
            <div className={styles.fieldRow}>
              <div className={styles.field}>
                <label>설립연도</label>
                <input
                  value={foundedYear}
                  placeholder="예: 2021"
                  disabled={isPreFounder}
                  onChange={(event) => setFoundedYear(event.target.value)}
                />
              </div>
              <div className={styles.field}>
                <label>기업 규모</label>
                <select
                  value={companySize}
                  disabled={isPreFounder}
                  onChange={(event) => setCompanySize(event.target.value)}
                >
                  <option value="">선택 안 함</option>
                  <option value="소기업">소기업</option>
                  <option value="중기업">중기업</option>
                  <option value="중견기업">중견기업</option>
                </select>
              </div>
            </div>
            <div className={styles.fieldRow}>
              <div className={styles.field}>
                <label>상시근로자 수</label>
                <input
                  value={employeeCount}
                  placeholder="예: 15"
                  disabled={isPreFounder}
                  onChange={(event) => setEmployeeCount(event.target.value)}
                />
              </div>
              <div className={styles.field}>
                <label>매출액 (억원)</label>
                <input
                  value={annualRevenue}
                  placeholder="예: 12"
                  disabled={isPreFounder}
                  onChange={(event) => setAnnualRevenue(event.target.value)}
                />
              </div>
            </div>
            <div className={styles.hint}>
              입력값은 계획서에서 추출한 정보를 보완하는 데 쓰여요. 비워두면
              문서에서 자동 추론합니다.
            </div>
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={goToUpload}
            >
              건너뛰기
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? '저장 중…' : '저장하고 계속 →'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
