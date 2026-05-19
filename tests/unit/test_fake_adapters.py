from crm.adapters.ai.extractor import ExtractedLead, FakeAIExtractor
from crm.adapters.ai.proposal_writer import FakeProposalWriter, ProposalDraft
from crm.adapters.gdocs.client import FakeGDocsClient
from crm.adapters.telegram.sender import FakeTelegramSender


async def test_fake_extractor_echoes_input_as_summary() -> None:
    extractor = FakeAIExtractor()
    result: ExtractedLead = await extractor.extract("  Привет, нужен дом 200м2.  ")
    assert result.summary.startswith("Привет")
    assert result.confidence == 0.0
    assert result.raw_response["provider"] == "fake"


async def test_fake_extractor_handles_empty_input() -> None:
    extractor = FakeAIExtractor()
    result = await extractor.extract("")
    assert result.summary == "(empty input)"


async def test_fake_proposal_writer_produces_nonempty_body() -> None:
    writer = FakeProposalWriter()
    draft: ProposalDraft = await writer.generate(
        lead_summary="дом 200м2",
        extracted={},
    )
    assert "дом 200м2" in draft.body
    assert draft.currency == "RUB"


async def test_fake_gdocs_records_creations_and_returns_url() -> None:
    client = FakeGDocsClient()
    ref = await client.create_doc(title="t", body="b")
    assert ref.url.startswith("https://docs.example.com/")
    assert client.created == [ref]


async def test_fake_telegram_records_messages() -> None:
    sender = FakeTelegramSender()
    await sender.send_message(chat_id=42, text="hi")
    await sender.send_message(chat_id=42, text="bye")
    assert len(sender.sent) == 2
    assert sender.sent[0].text == "hi"
