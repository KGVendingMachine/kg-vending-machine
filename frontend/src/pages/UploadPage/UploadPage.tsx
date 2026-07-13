import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMyBusinessPlan, uploadBusinessPlan } from '../../api/businessPlan'
import type { BusinessPlanSummary } from '../../api/businessPlan'
import { ApiError } from '../../api/client'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import { ANALYSIS_STATUS_LABELS } from '../../constants/analysisStatus'
import styles from './UploadPage.module.css'

// 서버 설정(MAX_UPLOAD_SIZE_BYTES)과 일치. 큰 파일을 다 올린 뒤 413으로
// 거절당하지 않도록 선택 시점에 미리 걸러준다.
const MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024

function formatFileSize(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function analysisStatusLabel(status: BusinessPlanSummary['analysis_status']): string {
  if (status == null) return '분석 대기'
  return ANALYSIS_STATUS_LABELS[status] ?? '분석 대기'
}

/** uploaded_at은 tz 표기 없는 UTC naive 문자열로 내려오므로 UTC로 명시 파싱한다. */
function formatUploadedAt(uploadedAt: string): string {
  const iso = uploadedAt.endsWith('Z') ? uploadedAt : `${uploadedAt}Z`
  return new Date(iso).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

/** FastAPI 오류 본문({ detail: "..." })에서 detail 문자열을 안전하게 꺼낸다. */
function extractDetail(body: unknown): string | null {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return null
}

function resolveUploadErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // 4xx는 형식·크기·인증처럼 사용자가 고칠 수 있는 문제라 서버 메시지를
    // 그대로 보여준다("다시 시도"는 오해를 준다). 5xx는 일시적 서버 문제로 본다.
    if (err.status >= 400 && err.status < 500) {
      return extractDetail(err.body) ?? '업로드할 수 없는 파일이에요.'
    }
    return '서버 오류로 업로드하지 못했어요. 잠시 후 다시 시도해 주세요.'
  }
  return '네트워크 오류로 업로드하지 못했어요.'
}

export function UploadPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)
  const [existingPlan, setExistingPlan] = useState<BusinessPlanSummary | null>(null)
  const [replacing, setReplacing] = useState(false)

  useEffect(() => {
    let cancelled = false
    getMyBusinessPlan()
      .then((plan) => {
        if (!cancelled) setExistingPlan(plan)
      })
      .catch(() => {
        // 조회 실패가 업로드 흐름을 막을 이유는 없다 — 빈 드롭존으로 폴백.
      })
      .finally(() => {
        if (!cancelled) setChecking(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const showExistingCard = !checking && existingPlan != null && !replacing && !file

  function handleFiles(files: FileList | null) {
    if (files && files.length > 0) {
      const selected = files[0]
      if (selected.size > MAX_UPLOAD_SIZE_BYTES) {
        setFile(null)
        setError(
          `파일이 너무 커요 (${formatFileSize(selected.size)}). 최대 50MB까지 업로드할 수 있어요.`,
        )
        return
      }
      setFile(selected)
      setError(null)
    }
  }

  async function handleStartAnalysis() {
    if (!file || uploading) return
    setUploading(true)
    setError(null)
    try {
      const { id } = await uploadBusinessPlan(file)
      // 무거운 분석(OCR·정규화·매칭)은 다음 단계에서 백그라운드 잡으로 돌린다.
      // 여기서는 업로드로 생성된 id만 넘기고 진행 페이지로 이동한다.
      navigate(PATHS.ANALYSIS, { state: { businessPlanId: id } })
    } catch (err) {
      setError(resolveUploadErrorMessage(err))
      setUploading(false)
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragOver(false)
    handleFiles(event.dataTransfer.files)
  }

  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    handleFiles(event.target.files)
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>사업계획서 업로드</div>
        <div className={styles.subheading}>
          사업계획서를 올리면 맞는 공고를 찾아드려요
        </div>

        <div className={styles.dropzoneCol}>
          {checking ? null : showExistingCard && existingPlan ? (
            <>
              <div className={styles.uploadedItem}>
                <span className={styles.fileIcon} />
                <div className={styles.fileInfo}>
                  <div className={styles.fileName}>
                    {existingPlan.title ?? '사업계획서'}
                  </div>
                  <div className={styles.fileMeta}>
                    {formatUploadedAt(existingPlan.uploaded_at)} 업로드
                  </div>
                </div>
                <span className={styles.fileStatus}>
                  {analysisStatusLabel(existingPlan.analysis_status)}
                </span>
              </div>
              <button
                type="button"
                className={styles.linkButton}
                onClick={() => setReplacing(true)}
              >
                다른 파일 업로드
              </button>
            </>
          ) : (
            <>
              <div
                className={
                  dragOver ? `${styles.dropzone} ${styles.dragOver}` : styles.dropzone
                }
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                role="button"
                tabIndex={0}
              >
                <div className={styles.dropIcon} />
                <div className={styles.dropTitle}>
                  파일을 끌어다 놓거나 클릭해 선택
                </div>
                <div className={styles.dropHint}>
                  PDF · HWP · HWPX · 이미지(JPG/PNG/TIFF)
                </div>
                <div className={styles.dropLimit}>최대 50MB</div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.hwp,.hwpx,.jpg,.jpeg,.png,.tiff"
                  hidden
                  onChange={handleFileInputChange}
                />
              </div>

              {file ? (
                <div className={styles.uploadedItem}>
                  <span className={styles.fileIcon} />
                  <div className={styles.fileInfo}>
                    <div className={styles.fileName}>{file.name}</div>
                    <div className={styles.fileMeta}>{formatFileSize(file.size)}</div>
                  </div>
                  <span className={styles.fileStatus}>선택됨</span>
                </div>
              ) : null}

              {replacing && existingPlan ? (
                <button
                  type="button"
                  className={styles.linkButton}
                  onClick={() => {
                    setReplacing(false)
                    setFile(null)
                    setError(null)
                  }}
                >
                  취소
                </button>
              ) : null}
            </>
          )}

          {error ? <div className={styles.error}>{error}</div> : null}
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={uploading}
            onClick={() => navigate(PATHS.COMPANY_PROFILE)}
          >
            ← 기업 프로필
          </button>
          {showExistingCard && existingPlan ? (
            <button
              type="button"
              className={styles.primaryButton}
              onClick={() =>
                navigate(PATHS.ANALYSIS, {
                  state: { businessPlanId: existingPlan.id },
                })
              }
            >
              이어서 진행 →
            </button>
          ) : (
            <button
              type="button"
              className={styles.primaryButton}
              disabled={!file || uploading}
              onClick={handleStartAnalysis}
            >
              {uploading ? '업로드 중…' : '분석 시작 →'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
