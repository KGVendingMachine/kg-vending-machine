import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import styles from './UploadPage.module.css'

function formatFileSize(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

export function UploadPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)

  function handleFiles(files: FileList | null) {
    if (files && files.length > 0) {
      setFile(files[0])
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
              PDF · DOCX · PPTX · HWP · 이미지(JPG/PNG)
            </div>
            <div className={styles.dropLimit}>
              최대 50MB · 악성파일 검사 자동 수행
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.pptx,.hwp,.jpg,.jpeg,.png"
              hidden
              onChange={handleFileInputChange}
            />
          </div>

          {file ? (
            <div className={styles.uploadedItem}>
              <span className={styles.fileIcon} />
              <div className={styles.fileInfo}>
                <div className={styles.fileName}>{file.name}</div>
                <div className={styles.fileMeta}>
                  {formatFileSize(file.size)} · 업로드 완료
                </div>
              </div>
              <span className={styles.fileStatus}>✓ 검증 통과</span>
            </div>
          ) : null}
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => navigate(PATHS.COMPANY_PROFILE)}
          >
            ← 기업 프로필
          </button>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={!file}
            onClick={() => navigate(PATHS.ANALYSIS)}
          >
            분석 시작 →
          </button>
        </div>
      </div>
    </div>
  )
}
