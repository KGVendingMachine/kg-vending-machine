import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadBusinessPlan } from '../../api/businessPlan'
import { ApiError } from '../../api/client'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import styles from './UploadPage.module.css'

function formatFileSize(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
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

  function handleFiles(files: FileList | null) {
    if (files && files.length > 0) {
      setFile(files[0])
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
            <div className={styles.dropLimit}>
              최대 50MB · 악성파일 검사 자동 수행
            </div>
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
          <button
            type="button"
            className={styles.primaryButton}
            disabled={!file || uploading}
            onClick={handleStartAnalysis}
          >
            {uploading ? '업로드 중…' : '분석 시작 →'}
          </button>
        </div>
      </div>
    </div>
  )
}
