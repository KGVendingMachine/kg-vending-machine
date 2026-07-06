export interface ScoreBreakdownItem {
  label: string
  weightLabel: string
  score: number
  max: number
  note: string
  status: 'good' | 'warn'
}

export interface ReasonItem {
  tone: 'good' | 'warn'
  label: string
  detail: string
}

export interface RequirementCheck {
  label: string
  detail: string
  status: 'ok' | 'warn'
}

export interface Notice {
  id: string
  category: string
  deadlineLabel: string
  isUrgent: boolean
  title: string
  org: string
  amountLabel: string
  dueDateLabel: string
  score: number
  scoreLevel: 'high' | 'medium'
  matchReasonShort: string
  scoreBreakdown: ScoreBreakdownItem[]
  reasons: ReasonItem[]
  requirements: RequirementCheck[]
}
