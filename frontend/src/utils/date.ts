export interface DeadlineInfo {
  /** "D-6" | "D-day" | "마감" | "상시" */
  label: string
  /** "~2025.07.18" | "상시 모집" */
  dueDateLabel: string
  /** 마감까지 7일 이하로 남았는지 (마감/상시는 false) */
  isUrgent: boolean
}

/** application_end_date(YYYY-MM-DD, null=상시)를 카드/상세 화면 표시용 라벨로 변환한다. */
export function formatDeadline(endDate: string | null): DeadlineInfo {
  if (!endDate) {
    return { label: '상시', dueDateLabel: '상시 모집', isUrgent: false }
  }

  const end = new Date(`${endDate}T00:00:00`)
  if (Number.isNaN(end.getTime())) {
    return { label: '상시', dueDateLabel: '상시 모집', isUrgent: false }
  }

  const dueDateLabel = `~${endDate.replaceAll('-', '.')}`
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diffDays = Math.round((end.getTime() - today.getTime()) / 86_400_000)

  if (diffDays < 0) {
    return { label: '마감', dueDateLabel, isUrgent: false }
  }
  return {
    label: diffDays === 0 ? 'D-day' : `D-${diffDays}`,
    dueDateLabel,
    isUrgent: diffDays <= 7,
  }
}
