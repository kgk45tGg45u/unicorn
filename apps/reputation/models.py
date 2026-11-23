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
