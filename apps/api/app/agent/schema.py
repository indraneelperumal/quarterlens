from __future__ import annotations
from pydantic import BaseModel


class Citation(BaseModel):
    accession_number: str
    date: str
    form_type: str
    excerpt: str | None = None
    source_url: str = ""


class KeyNumber(BaseModel):
    label: str
    value: str
    vs_estimate: str | None = None


class InvestorResponse(BaseModel):
    answer: str
    key_numbers: list[KeyNumber] = []
    citations: list[Citation] = []
    sentiment: str | None = None
    disclaimer: str = "This is for research and education only. Not investment advice."
