export const NOTICE_CATEGORIES = [
  '자금',
  'R&D·기술',
  '수출·글로벌',
  '인력',
  '시설·공간·보육',
  '멘토링·컨설팅',
  '교육·행사·네트워킹',
  '기타',
] as const

export type NoticeCategory = (typeof NOTICE_CATEGORIES)[number]
