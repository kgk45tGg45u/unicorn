from django.db import models


class ReputationScore(models.Model):
    """A cache of how helpful a member's answers on one topic were. It can always be rebuilt from the marks.

    It is used only to suggest who might answer a ticket (HF-15). Never for work, pay, votes, prices, draws or trust.
    """

    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="reputation_scores")
    topic = models.CharField(max_length=60)  # the ticket type, and the trade if there is one: "question:wood"
    score = models.DecimalField(max_digits=12, decimal_places=4)
    computed_at = models.DateTimeField()

    class Meta:
        ordering = ["member", "-score"]
        constraints = [models.UniqueConstraint(fields=["member", "topic"], name="one_score_per_member_and_topic")]
        indexes = [models.Index(fields=["topic", "-score"])]

    def __str__(self):
        return f"{self.member.number} {self.topic}: {self.score}"


class SuggestionLog(models.Model):
    """Who was told "You might know the answer" for which ticket, so nobody is told twice."""

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="+")
    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ticket", "member"], name="one_suggestion_each")]

    def __str__(self):
        return f"{self.member.number} suggested for {self.ticket.number}"


class Recognition(models.Model):
    """Recognition instead of extra pay: "first maker of X", "filled a need", thanks from the people served.

    It pays nothing (HF-2) and there is no ranking list. A row with no member is the unit's; the others are its
    workers' at that time, and each worker may hide theirs from their portfolio.
    """

    KINDS = [("first_maker", "first maker"), ("filled_need", "filled a need"), ("thanks", "thanks")]

    member = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=12, choices=KINDS)
    item = models.ForeignKey("catalogue.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    review = models.ForeignKey("market.Review", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    text = models.CharField(max_length=280, blank=True)
    from_member = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    hidden_by_owner = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["unit", "kind"]), models.Index(fields=["member", "hidden_by_owner"])]

    def __str__(self):
        return f"{self.kind} for {self.unit.name if self.unit_id else self.member.number}"
