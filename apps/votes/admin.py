from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Ballot, Candidate, Election, Petition, PetitionSignature, Referendum, Term, VoterRecord


@admin.register(Petition)
class PetitionAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "status", "threshold", "closes_at")


@admin.register(PetitionSignature)
class PetitionSignatureAdmin(ReadOnlyAdmin):
    list_display = ("petition", "signed_at")


@admin.register(Referendum)
class ReferendumAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "question", "method", "status", "closes_at")


@admin.register(Ballot)
class BallotAdmin(ReadOnlyAdmin):
    list_display = ("receipt", "referendum", "election")


@admin.register(VoterRecord)
class VoterRecordAdmin(ReadOnlyAdmin):
    list_display = ("referendum", "election", "voted_on")


@admin.register(Election)
class ElectionAdmin(ReadOnlyAdmin):
    list_display = ("role", "status", "closes_at")


@admin.register(Candidate)
class CandidateAdmin(ReadOnlyAdmin):
    list_display = ("election", "member")


@admin.register(Term)
class TermAdmin(ReadOnlyAdmin):
    list_display = ("role", "member", "starts_at", "ends_at")
