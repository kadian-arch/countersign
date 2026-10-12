from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Policy(BaseModel):
    """What the guard enforces. The owner writes rules in plain English, a model
    compiles them into this shape, the owner confirms, and from then on it is
    plain code deciding, not a model."""

    model_config = ConfigDict(extra="forbid")

    refund_auto_max: Decimal = Field(Decimal("50.00"), ge=0, le=1_000_000, description="largest refund made automatically when a customer asks")
    refund_owner_max: Decimal = Field(Decimal("500.00"), ge=0, le=1_000_000, description="largest refund made when the owner asks")
    refund_day_max: Decimal = Field(Decimal("200.00"), ge=0, le=1_000_000, description="total refunded per day before the owner is asked")
    payout_auto_max: Decimal = Field(Decimal("500.00"), ge=0, le=1_000_000, description="largest payout to a known supplier against an invoice")
    payout_day_max: Decimal = Field(Decimal("1500.00"), ge=0, le=1_000_000, description="total paid to one supplier per day")
    hold_refund_on_dispute: bool = Field(True, description="hold a refund when the buyer has an open dispute on that payment")
    require_sender_match: bool = Field(True, description="a customer may only ask for a refund of their own order")

    @model_validator(mode="after")
    def _limits_make_sense(self):
        if self.refund_auto_max > self.refund_owner_max:
            raise ValueError("the automatic refund limit cannot be above the limit for refunds the owner asks for")
        return self
