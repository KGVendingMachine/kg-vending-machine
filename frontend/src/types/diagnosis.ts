export type DiagnosisStatus = 'complete' | 'incomplete'

export interface DiagnosisGroup {
  key: string
  label: string
  status: DiagnosisStatus
  message: string
}
