"""Per-model parameters and the pages' clarity (ADR-20261012-AB, replacing ADR-20261009-Q).

contracts/model-parameters.json lists, per interface type and model family, the official
parameters an administrator may fill in (stored with the model and delivered with its lease;
blank ones are absent, so the vendor's default applies) and how each clarity (1K or 2K output) is
requested. Java refuses a clarity a model cannot do; the Worker applies it and OpenRouter still
checks every value before a paid call. The output size is chosen separately: a 1K output exported
to a larger size is enlarged.
"""

import json
import re
from functools import cache
from pathlib import Path

from image_service.background import BackgroundError

CATALOG = Path(__file__).resolve().parents[2] / "contracts" / "model-parameters.json"


@cache
def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def parameter_set(kind, model, purpose="IMAGE"):
    """The first set for this interface type and purpose whose pattern matches the model id."""
    for item in catalog()["sets"]:
        if kind in item["kinds"] and item["purpose"] == purpose and re.search(item["match"], model):
            return item
    return {}


def for_call(config, request, *, gift=False):
    """Extra parameters for one image call: the model's stored ones, then the chosen clarity
    (not for the gift re-shot, which is small inside the card)."""
    if config is None:
        return ()
    values = dict(config.parameters)
    chosen = request.get("resolution")
    if chosen and not gift:
        offered = parameter_set(config.provider, config.model).get("resolutions", {})
        if chosen not in offered:
            raise BackgroundError("UNSUPPORTED_CAPABILITY")
        values.update(offered[chosen])
    return tuple(sorted(values.items()))
