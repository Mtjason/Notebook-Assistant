"""JSON values as the model and the changeset records exchange them."""

from __future__ import annotations

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]
