"""Per-model parameters and the pages' clarity options (ADR-20261009-Q).

contracts/model-parameters.json lists, per model family, the parameters an administrator may set
(stored with the model and delivered with its lease) and how "画质：高清" and the "高清" size are
requested. Java refuses choices a model cannot do; the Worker applies them and OpenRouter still
checks every value before a paid call.
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


def family(model, purpose="IMAGE"):
    for item in catalog()["families"]:
        if item["purpose"] == purpose and re.search(item["match"], model):
            return item
    return {}


def for_call(config, request, *, gift=False):
    """Extra parameters for one image call: the model's stored ones, then "画质：高清", then the
    2K output the "高清" size needs (not for the gift re-shot, which is small in the card)."""
    if config is None:
        return ()
    found = family(config.model)
    values = dict(config.parameters)
    if request.get("quality") == "HIGH":
        if "high" not in found:
            raise BackgroundError("UNSUPPORTED_CAPABILITY")
        values.update(found["high"])
    output = request["output"]
    if not gift and max(output["width"], output["height"]) > catalog()["standard_max_side"]:
        if "large" not in found:
            raise BackgroundError("UNSUPPORTED_CAPABILITY")
        values.update(found["large"])
    return tuple(sorted(values.items()))
