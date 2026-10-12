"""What the shop owner sets up: who they are, what the agent may say about the shop, and the limits.
Kept with the shop's records, so nothing about a particular shop lives in the code."""
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import demo_data as demo
from . import emails
from .policy import Policy


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_name: str = Field(max_length=80, min_length=1)
    owner_email: str = Field(max_length=200)
    knowledge: str = Field("", max_length=4000, description="the facts the agent may state about the shop")
    policy: Policy = Field(default_factory=Policy)
    alerts: bool = Field(True, description="email the owner when a request is waiting for approval")

    @field_validator("owner_email")
    @classmethod
    def _address(cls, v: str) -> str:
        v = v.strip()
        if not emails.is_email(v):
            raise ValueError("the owner's address is not a valid email address")
        return v

    @field_validator("shop_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip() or "My shop"


def demo_profile() -> Profile:
    return Profile(shop_name=demo.SHOP, owner_email=demo.OWNER_EMAIL, knowledge=demo.SHOP_FACTS)


def load(store) -> Profile | None:
    raw = store.get_setting("profile")
    return Profile.model_validate_json(raw) if raw else None


def save(store, profile: Profile):
    store.set_setting("profile", profile.model_dump_json())


def changes(old: Profile, new: Profile) -> dict:
    """Field by field, what is different, for showing the owner before they confirm."""
    out = {}
    for key in ("shop_name", "owner_email", "knowledge", "alerts"):
        if getattr(old, key) != getattr(new, key):
            out[key] = [getattr(old, key), getattr(new, key)]
    for key in Policy.model_fields:
        a, b = getattr(old.policy, key), getattr(new.policy, key)
        if a != b:
            out[f"policy.{key}"] = [str(a), str(b)]
    return out


def json_safe(profile: Profile) -> dict:
    return json.loads(profile.model_dump_json())
