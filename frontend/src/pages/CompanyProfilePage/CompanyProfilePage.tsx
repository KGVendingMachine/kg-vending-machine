import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  saveMyCompanyProfile,
  type CompanyProfileUpdate,
} from '../../api/companyProfile'
import { NOTICE_CATEGORIES } from '../../mock/categories'
import { PATHS } from '../../routes/paths'
import styles from './CompanyProfilePage.module.css'

export function CompanyProfilePage() {
  const navigate = useNavigate()
  const [representativeName, setRepresentativeName] = useState('')
  const [businessRegistrationNumber, setBusinessRegistrationNumber] = useState('')
  const [industry, setIndustry] = useState('')
  const [region, setRegion] = useState('')
  const [foundedYear, setFoundedYear] = useState('')
  const [companySize, setCompanySize] = useState('')
  const [employeeCount, setEmployeeCount] = useState('')
  const [annualRevenue, setAnnualRevenue] = useState('')
  const [saving, setSaving] = useState(false)

  function goToUpload() {
    navigate(PATHS.UPLOAD)
  }

  /**
   * 지금은 폼-DB 형식이 딱 맞는 필드만 저장한다(대표자명·사업자등록번호·
   * 기업규모·상시근로자수). 비운 필드는 payload에서 빼서 부분 갱신되게 한다.
   * 업종·지역·설립연도·매출은 단위/코드 변환이 필요해 다음 라운드에서 붙인다.
   */
  async function handleSave() {
    const payload: CompanyProfileUpdate = {}
    if (representativeName.trim())
      payload.representative_name = representativeName.trim()
    if (businessRegistrationNumber.trim())
      payload.business_registration_number = businessRegistrationNumber.trim()
    if (companySize) payload.company_size = companySize
    const employees = Number(employeeCount)
    if (employeeCount.trim() && Number.isFinite(employees))
      payload.employee_count = employees

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
                  onChange={(event) =>
                    setBusinessRegistrationNumber(event.target.value)
                  }
                />
              </div>
            </div>
            <div className={styles.field}>
              <label>업종 / 분야</label>
              <select
                value={industry}
                onChange={(event) => setIndustry(event.target.value)}
              >
                <option value="">선택 안 함</option>
                {NOTICE_CATEGORIES.map((category) => (
                  <option value={category} key={category}>
                    {category}
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
                <option value="서울">서울</option>
                <option value="경기">경기</option>
                <option value="인천">인천</option>
                <option value="부산">부산</option>
              </select>
            </div>
            <div className={styles.fieldRow}>
              <div className={styles.field}>
                <label>설립연도</label>
                <input
                  value={foundedYear}
                  placeholder="예: 2021"
                  onChange={(event) => setFoundedYear(event.target.value)}
                />
              </div>
              <div className={styles.field}>
                <label>기업 규모</label>
                <select
                  value={companySize}
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
                  onChange={(event) => setEmployeeCount(event.target.value)}
                />
              </div>
              <div className={styles.field}>
                <label>매출액 (억원)</label>
                <input
                  value={annualRevenue}
                  placeholder="예: 12"
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
