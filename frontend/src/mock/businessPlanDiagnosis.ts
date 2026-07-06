import type { DiagnosisGroup } from '../types/diagnosis'

export const businessPlanDiagnosis: DiagnosisGroup[] = [
  {
    key: 'general',
    label: '일반현황',
    status: 'complete',
    message: '기업명·대표자·설립일 등 기본 정보가 모두 확인됐어요.',
  },
  {
    key: 'problem',
    label: '문제인식 (P)',
    status: 'incomplete',
    message:
      '문제 제기는 있으나 통계적 근거가 부족해요 — 시장 통계나 수치를 추가하면 신뢰도가 올라가요.',
  },
  {
    key: 'solution',
    label: '실현가능성 (S)',
    status: 'complete',
    message: '차별성 4가지와 지적재산권 현황까지 확인됐어요.',
  },
  {
    key: 'scaleup',
    label: '성장전략 (Sc)',
    status: 'incomplete',
    message:
      '시장규모는 언급됐지만 TAM/SAM/SOM을 숫자로 쪼개지 않았어요 — 구체적인 수치가 있으면 사업 정합 점수가 올라가요.',
  },
  {
    key: 'team',
    label: '팀구성 (T)',
    status: 'complete',
    message: '대표자 이력과 팀원 구성·채용계획까지 구조화되어 있어요.',
  },
  {
    key: 'registration',
    label: '사업자 증빙',
    status: 'complete',
    message:
      '사업자등록번호·개업일이 확인돼 아래 자격요건 대조(중소기업 여부·업력)에 자동으로 활용됐어요.',
  },
]
