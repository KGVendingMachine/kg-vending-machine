from app.services.text_chunking import chunk_text


def test_empty_input_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_paragraphs_pack_under_max_chars():
    paragraphs = ["가나다라마바사" * 10 for _ in range(5)]  # 각 70자, 5개
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_chars=200, overlap_chars=0)

    assert all(len(c.chunk_text) <= 200 for c in chunks)
    # 모든 원본 문단 내용이 어딘가의 청크에 그대로 남아있어야 한다.
    for paragraph in paragraphs:
        assert any(paragraph in c.chunk_text for c in chunks)


def test_oversized_paragraph_is_force_split():
    text = "가" * 500
    chunks = chunk_text(text, max_chars=200, overlap_chars=0)

    assert len(chunks) > 1
    assert all(len(c.chunk_text) <= 200 for c in chunks)
    # 이어붙이면 원문이 그대로 복원돼야 한다(오버랩 없을 때).
    assert "".join(c.chunk_text for c in chunks) == text


def test_oversized_paragraph_adjacent_chunks_overlap():
    text = "가" * 500
    chunks = chunk_text(text, max_chars=200, overlap_chars=50)

    assert len(chunks) > 1
    for prev, nxt in zip(chunks, chunks[1:]):
        # 앞 청크의 마지막 50자가 다음 청크의 시작 50자와 겹쳐야 한다.
        assert prev.chunk_text[-50:] == nxt.chunk_text[:50]


def test_paragraph_boundary_chunks_overlap():
    # 각 문단이 90자라 두 개면 180자 -> max_chars=200 안에 들어가지만
    # 세 번째부터는 새 청크로 넘어가면서 오버랩이 생겨야 한다.
    paragraphs = [f"문단{i}" + "가" * 85 for i in range(4)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_chars=200, overlap_chars=30)

    assert len(chunks) > 1
    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev.chunk_text[-30:] in nxt.chunk_text


def test_chunk_type_is_applied():
    chunks = chunk_text("본문 내용", chunk_type="attachment")
    assert all(c.chunk_type == "attachment" for c in chunks)
