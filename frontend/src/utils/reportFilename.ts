/**
 * 브라우저 인쇄("PDF로 저장") 시 저장 대화상자의 기본 파일명이 되는 문자열을
 * 만든다. 파일명은 document.title 에서 오므로, 이 값을 인쇄 직전에 지정하면
 * 사용자가 이름을 직접 타이핑하지 않아도 된다.
 *
 * 형식: `<접두어>_<YYYYMMDD>_<랜덤6자>`
 * 고정 접두어 뒤에 날짜와 랜덤 접미어를 붙여, 같은 리포트를 여러 번 받아도
 * 파일명이 겹치지 않게 한다. 확장자(.pdf)는 브라우저가 자동으로 붙이므로
 * 여기서는 붙이지 않는다. 파일명에 부적합한 공백·특수문자도 넣지 않는다.
 */
/**
 * 인쇄로 PDF를 저장할 때 파일명이 자동으로 채워지려면 인쇄 대상(destination)을
 * 브라우저 내장 "PDF로 저장"으로 골라야 한다는 안내. Windows "Microsoft Print to
 * PDF" 등 OS 프린터 드라이버는 document.title 을 무시하고 빈 파일명을 띄운다.
 */
export const PRINT_DESTINATION_HINT =
  '인쇄 대상을 "PDF로 저장"으로 선택하면 파일명이 자동으로 채워집니다.'

export function reportFileTitle(prefix: string): string {
  const now = new Date()
  const date =
    `${now.getFullYear()}` +
    `${String(now.getMonth() + 1).padStart(2, '0')}` +
    `${String(now.getDate()).padStart(2, '0')}`
  const random = Math.random().toString(36).slice(2, 8)
  return `${prefix}_${date}_${random}`
}

/**
 * document.title 을 fileTitle 로 바꾼 뒤 인쇄 대화상자를 연다. 브라우저는 이
 * 제목을 "PDF로 저장" 기본 파일명으로 쓰므로 사용자가 이름을 타이핑하지 않아도
 * 된다. 인쇄가 끝나면 제목을 원래대로 되돌린다.
 *
 * 복원을 afterprint 에서 곧바로 하지 않고 잠깐 늦추는 이유: Chrome 등에서
 * afterprint 직후에 OS 저장 대화상자가 열리면서 document.title 로 기본 파일명을
 * 잡는데, 여기서 바로 원복하면 대화상자가 원래 제목을 읽어 파일명이 비워진다.
 */
export function printWithFilename(fileTitle: string): void {
  const previousTitle = document.title
  document.title = fileTitle

  const restore = () => {
    window.removeEventListener('afterprint', restore)
    window.setTimeout(() => {
      document.title = previousTitle
    }, 2000)
  }
  window.addEventListener('afterprint', restore)

  window.print()
}
