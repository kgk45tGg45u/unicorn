from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyModel


class Petition(models.Model):
    """Signatures that force a referendum (docs/05 section 3 step 7)."""

    STATUSES = [("open", _("open")), ("succeeded", _("succeeded")), ("failed", _("failed"))]

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="petitions")
    question = models.CharField(max_length=300)
    opened_by = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="petitions_opened")
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    threshold = models.PositiveIntegerField()  # fixed when the petition opens
    status = models.CharField(max_length=10, choices=STATUSES, default="open")

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"petition on {self.ticket.number} ({self.status})"


class PetitionSignature(models.Model):
    petition = models.ForeignKey(Petition, on_delete=models.CASCADE, related_name="signatures")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="signatures_on_petitions")
    signed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["petition", "member"], name="one_signature_each")]

    def __str__(self):
        return f"signature {self.pk} on petition {self.petition_id}"


class Referendum(models.Model):
    """A vote of all members. Ballots are secret: a Ballot holds the choice and a receipt, never a member."""

    METHODS = [("yes_no", _("yes or no")), ("ranked_irv", _("ranked choice"))]
    MAJORITIES = [("simple", _("simple majority")), ("two_thirds", _("two thirds"))]
    STATUSES = [("scheduled", _("scheduled")), ("open", _("open")), ("closed", _("closed"))]

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="referendums")
    question = models.CharField(max_length=300)
    method = models.CharField(max_length=12, choices=METHODS, default="yes_no")
    options = models.JSONField(default=list, blank=True)  # for ranked votes
    brief_for_md = models.TextField(blank=True)
    brief_against_md = models.TextField(blank=True)
    forecast = models.ForeignKey(
        "members.PrivateFile", null=True, blank=True, on_delete=models.PROTECT, related_name="referendums"
    )
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    quorum_share = models.DecimalField(max_digits=4, decimal_places=3)
    majority = models.CharField(max_length=10, choices=MAJORITIES, default="simple")
    eligible_count = models.PositiveIntegerField(default=0)  # fixed when the vote opens
    status = models.CharField(max_length=10, choices=STATUSES, default="scheduled")
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"referendum on {self.ticket.number}: {self.question}"


class Ballot(AppendOnlyModel):
    """One secret ballot. No member and no time are stored (docs/05 section 4); the table is append-only.

    The receipt is the primary key, so the order of the rows says nothing about who voted when.
    """

    referendum = models.ForeignKey(Referendum, null=True, on_delete=models.PROTECT, related_name="ballots")
    election = models.ForeignKey("Election", null=True, on_delete=models.PROTECT, related_name="ballots")
    receipt = models.CharField(max_length=12, primary_key=True)
    choice = models.JSONField()  # "yes", "no", "abstain", or a ranked list of options; for elections a list of ids

    def __str__(self):
        return f"ballot {self.receipt}"


class VoterRecord(AppendOnlyModel):
    """Says only that a member voted, and on which day. Append-only."""

    referendum = models.ForeignKey(Referendum, null=True, on_delete=models.PROTECT, related_name="voters")
    election = models.ForeignKey("Election", null=True, on_delete=models.PROTECT, related_name="voters")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="voter_records")
    voted_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["referendum", "member"], name="one_vote_each"),
            models.UniqueConstraint(fields=["election", "member"], name="one_election_vote_each"),
        ]

    def __str__(self):
        return f"voter record {self.pk}"


class Election(models.Model):
    """An election of members to a role for a year, by approval voting with secret ballots (P07.T09)."""

    ROLES = [("auditor", _("auditor")), ("trust_review", _("trust review group"))]
    STATUSES = [("open", _("open")), ("closed", _("closed"))]

    role = models.CharField(max_length=14, choices=ROLES)
    seats = models.PositiveSmallIntegerField()
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    eligible_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"election of {self.get_role_display()} ({self.status})"


class Candidate(models.Model):
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="candidates")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="candidacies")
    statement = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["election", "member"], name="one_candidacy_each")]

    def __str__(self):
        return f"{self.member.number} for {self.election}"


class Term(models.Model):
    """A member holds a role from `starts_at` to `ends_at` (one year)."""

    role = models.CharField(max_length=14, choices=Election.ROLES)
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="terms")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    election = models.ForeignKey(Election, null=True, blank=True, on_delete=models.PROTECT, related_name="terms")

    class Meta:
        ordering = ["role", "-starts_at"]

    def __str__(self):
        return f"{self.member.number} as {self.get_role_display()}"
