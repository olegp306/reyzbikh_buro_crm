from crm.db.models.enums import (
    ChannelKind,
    ClientSource,
    ContractStatusComputed,
    DocumentKind,
    DocumentOwnerType,
    FollowUpKind,
    FollowUpStatus,
    JobStatus,
    LeadStatus,
    ProjectStatus,
    ProposalStatus,
    UserRole,
)


def test_lead_status_is_strenum_with_expected_values() -> None:
    assert LeadStatus.new.value == "new"
    assert LeadStatus.qualified.value == "qualified"
    assert "proposal_sent" in [s.value for s in LeadStatus]


def test_proposal_status_revised_exists() -> None:
    assert ProposalStatus.revised.value == "revised"


def test_follow_up_subject_kind_present() -> None:
    assert FollowUpKind.reminder.value == "reminder"
    assert FollowUpKind.deadline.value == "deadline"


def test_document_owner_type_covers_all_polymorphic_targets() -> None:
    owners = {o.value for o in DocumentOwnerType}
    assert owners == {"lead", "client", "project", "proposal", "contract"}


def test_job_status_terminal_states_present() -> None:
    assert JobStatus.done.value == "done"
    assert JobStatus.failed.value == "failed"


def test_all_enums_are_str_subclasses() -> None:
    for enum_cls in (
        ChannelKind,
        ClientSource,
        ContractStatusComputed,
        DocumentKind,
        DocumentOwnerType,
        FollowUpKind,
        FollowUpStatus,
        JobStatus,
        LeadStatus,
        ProjectStatus,
        ProposalStatus,
        UserRole,
    ):
        member = next(iter(enum_cls))
        assert isinstance(member, str), f"{enum_cls.__name__} is not StrEnum"
