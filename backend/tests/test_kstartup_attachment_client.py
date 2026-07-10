"""
tests/test_kstartup_attachment_client.py

crawler/kstartup_attachment_client.py의 _parse_attachments(HTML 파싱) 테스트.
실제 상세페이지 구조(app/crawler/kstartup_attachment_client.py 참고)를 최소
재현한 HTML로 검증한다. 네트워크 호출은 하지 않는다.
"""

from app.crawler.kstartup_attachment_client import _BASE_URL, _parse_attachments

_SAMPLE_HTML = """
<ul>
  <li>
    <a class="file_bg" title="[첨부파일] 공고문.pdf"></a>
    <a class="btn_down" href="/afile/fileDownload/abc123"></a>
  </li>
  <li>
    <a class="file_bg" title="[첨부파일] 신청서.hwp"></a>
    <a class="btn_down" href="/afile/fileDownload/def456"></a>
  </li>
</ul>
"""


def test_parse_attachments_extracts_file_name_and_absolute_url():
    result = _parse_attachments(_SAMPLE_HTML)

    assert result == [
        ("공고문.pdf", f"{_BASE_URL}/afile/fileDownload/abc123"),
        ("신청서.hwp", f"{_BASE_URL}/afile/fileDownload/def456"),
    ]


def test_parse_attachments_empty_when_no_file_links():
    assert _parse_attachments("<html><body>첨부파일 없음</body></html>") == []


def test_parse_attachments_skips_entry_missing_download_link():
    html = """
    <ul>
      <li>
        <a class="file_bg" title="[첨부파일] 공고문.pdf"></a>
      </li>
    </ul>
    """
    assert _parse_attachments(html) == []
