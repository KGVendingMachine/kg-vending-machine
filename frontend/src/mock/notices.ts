import type { Notice } from '../types/notice'

export const notices: Notice[] = [
  {
    id: 'smart-factory-2025',
    category: 'R&D·기술',
    deadlineLabel: 'D-6',
    isUrgent: true,
    title: '2025 스마트공장 구축 지원사업',
    org: '중소벤처기업부 · 한국산업단지공단',
    amountLabel: '최대 1.2억원',
    dueDateLabel: '~2025.07.18',
    score: 94,
    scoreLevel: 'high',
    matchReasonShort:
      "근거: 제조업·소기업 요건 충족, 계획서의 '설비 자동화' 목표가 사업 취지와 일치",
    scoreBreakdown: [
      {
        label: '분야 적합',
        weightLabel: '가중 40%',
        score: 40,
        max: 40,
        note: "계획서 분야 '제조(설비 자동화)'가 공고 모집분야와 완전히 일치합니다.",
        status: 'good',
      },
      {
        label: '자격 충족',
        weightLabel: '가중 30%',
        score: 30,
        max: 30,
        note: '중소기업·제조업·업력 3년 이상 등 필수 자격을 모두 충족합니다.',
        status: 'good',
      },
      {
        label: '사업 정합',
        weightLabel: '가중 30%',
        score: 24,
        max: 30,
        note: '사업 목표는 부합하나, 자부담 매칭 계획이 계획서에 명시되지 않아 일부 감점되었습니다.',
        status: 'warn',
      },
    ],
    reasons: [
      {
        tone: 'good',
        label: '강점',
        detail:
          "계획서의 '생산라인 자동화·불량률 개선' 목표가 사업의 핵심 취지와 직접 부합합니다.",
      },
      {
        tone: 'good',
        label: '강점',
        detail: '소기업 가점 대상으로 선정 가능성이 상대적으로 높습니다.',
      },
      {
        tone: 'warn',
        label: '주의',
        detail:
          '자부담 30%(약 3,600만원)에 대한 자금조달 계획을 신청 전 보완해야 합니다.',
      },
    ],
    requirements: [
      {
        label: '중소기업 여부',
        detail: '소기업으로 충족 (계획서 p.1)',
        status: 'ok',
      },
      { label: '제조업종', detail: '한국표준산업분류 C 해당', status: 'ok' },
      { label: '업력 3년 이상', detail: '2021년 설립, 4년차', status: 'ok' },
      {
        label: '자부담 30% 매칭',
        detail: '약 3,600만원 필요 — 확인 필요',
        status: 'warn',
      },
      {
        label: '중복 수혜 제한',
        detail: '동일 설비 타 사업 수혜 이력 없음',
        status: 'ok',
      },
    ],
  },
  {
    id: 'tech-innovation-2025',
    category: 'R&D·기술',
    deadlineLabel: 'D-21',
    isUrgent: false,
    title: '중소기업 기술혁신개발(혁신형)',
    org: '중소벤처기업부 · 중소기업기술정보진흥원',
    amountLabel: '최대 4억원',
    dueDateLabel: '~2025.08.02',
    score: 88,
    scoreLevel: 'high',
    matchReasonShort:
      '근거: R&D 역량 강화 목표와 부합하나, 기술성 평가 준비가 추가로 필요합니다.',
    scoreBreakdown: [
      {
        label: '분야 적합',
        weightLabel: '가중 40%',
        score: 36,
        max: 40,
        note: "계획서의 'R&D 역량 강화' 목표가 사업 모집분야와 대체로 일치합니다.",
        status: 'good',
      },
      {
        label: '자격 충족',
        weightLabel: '가중 30%',
        score: 28,
        max: 30,
        note: '중소기업·제조업 요건은 충족하나 기술등급 증빙이 일부 부족합니다.',
        status: 'warn',
      },
      {
        label: '사업 정합',
        weightLabel: '가중 30%',
        score: 24,
        max: 30,
        note: '기술성 평가 비중이 높아 준비 기간이 추가로 필요합니다.',
        status: 'warn',
      },
    ],
    reasons: [
      {
        tone: 'good',
        label: '강점',
        detail: 'R&D 과제로 지원규모가 커 설비투자 이후 성장 단계에 적합합니다.',
      },
      {
        tone: 'warn',
        label: '주의',
        detail: '기술성 평가 비중이 높아 준비 기간이 더 필요합니다.',
      },
    ],
    requirements: [
      { label: '중소기업 여부', detail: '소기업으로 충족', status: 'ok' },
      { label: '제조업종', detail: '한국표준산업분류 C 해당', status: 'ok' },
      {
        label: '기술등급 증빙',
        detail: '기술신용평가 등급 확인 필요',
        status: 'warn',
      },
    ],
  },
  {
    id: 'export-voucher-2025',
    category: '수출·글로벌',
    deadlineLabel: '상시',
    isUrgent: false,
    title: '수출바우처 사업(중견·중소)',
    org: '산업통상자원부 · KOTRA',
    amountLabel: '최대 1억원',
    dueDateLabel: '상시 모집',
    score: 76,
    scoreLevel: 'medium',
    matchReasonShort: '근거: 수출 실적이 아직 없어 초기 단계 항목만 부분 충족합니다.',
    scoreBreakdown: [
      {
        label: '분야 적합',
        weightLabel: '가중 40%',
        score: 28,
        max: 40,
        note: '계획서에 수출 계획이 일부 언급되어 있으나 핵심 목표는 아닙니다.',
        status: 'warn',
      },
      {
        label: '자격 충족',
        weightLabel: '가중 30%',
        score: 26,
        max: 30,
        note: '중소기업 요건은 충족하나 수출 실적 증빙이 없습니다.',
        status: 'warn',
      },
      {
        label: '사업 정합',
        weightLabel: '가중 30%',
        score: 22,
        max: 30,
        note: '상시 모집이라 신청 시점에 여유가 있습니다.',
        status: 'good',
      },
    ],
    reasons: [
      {
        tone: 'good',
        label: '강점',
        detail: '상시 모집이라 준비가 되는 대로 언제든 신청할 수 있습니다.',
      },
      {
        tone: 'warn',
        label: '주의',
        detail: '수출 실적이 없어 바우처 활용 계획을 구체적으로 제시해야 합니다.',
      },
    ],
    requirements: [
      { label: '중소기업 여부', detail: '소기업으로 충족', status: 'ok' },
      {
        label: '수출 실적 또는 계획',
        detail: '수출 계획 증빙 보완 필요',
        status: 'warn',
      },
    ],
  },
]

export function findNoticeById(id: string): Notice | undefined {
  return notices.find((notice) => notice.id === id)
}
