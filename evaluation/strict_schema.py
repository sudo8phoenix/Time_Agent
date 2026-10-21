"""Evaluation-only Groq core wire schema; full domain validation remains in place.

Both comparison arms receive this exact schema. Every transformation is recorded;
this does not replace the application schema or assert full provider support.
"""
from copy import deepcopy


def build_wire_schema(schema):
    changes = []

    def visit(node, path):
        if not isinstance(node, dict):
            raise ValueError("Only object schema nodes are supported")
        result = {}
        for key, value in node.items():
            if key in {"properties", "$defs"}:
                result[key] = {name: visit(child, f"{path}/{key}/{name}")
                               for name, child in value.items()}
            elif key == "items":
                result[key] = visit(value, f"{path}/items")
            elif key == "anyOf":
                result[key] = [visit(child, f"{path}/anyOf/{i}") for i, child in enumerate(value)]
            elif key in {"type", "enum", "$ref", "description", "required", "additionalProperties"}:
                result[key] = deepcopy(value)
            else:
                changes.append({"path": path, "keyword": key, "removed": deepcopy(value)})
        if "anyOf" in result:
            branches = []
            for branch in result["anyOf"]:
                target = branch
                seen = set()
                while "$ref" in target:
                    reference = target["$ref"]
                    if reference in seen or not reference.startswith("#/"):
                        raise ValueError("Unsupported primitive union reference")
                    seen.add(reference)
                    target = schema
                    for token in reference[2:].split("/"):
                        target = target[token.replace("~1", "/").replace("~0", "~")]
                branches.append(target)
            primitives = {"string", "number", "integer", "boolean", "null"}
            if all(b.get("type") in primitives for b in branches):
                before = result.pop("anyOf")
                result["type"] = list(dict.fromkeys(b["type"] for b in branches))
                if any("enum" in b for b in branches):
                    if not all("enum" in b or b["type"] == "null" for b in branches):
                        raise ValueError("Cannot collapse mixed enum/unrestricted primitive union")
                    result["enum"] = [value for b in branches
                                      for value in b.get("enum", [None])]
                changes.append({"path": path, "keyword": "anyOf",
                                "before": before, "after": deepcopy(result),
                                "reason": "equivalent primitive type-array union for provider compatibility"})
        if result.get("type") == "object" or "properties" in result:
            required = list(result.get("properties", {}))
            if result.get("required") != required:
                changes.append({"path": path, "keyword": "required",
                                "before": result.get("required", []), "after": required})
            result["required"] = required
            if result.get("additionalProperties") is not False:
                changes.append({"path": path, "keyword": "additionalProperties", "after": False})
            result["additionalProperties"] = False
        return result

    converted = visit(schema, "#")
    if converted.get("type") != "object":
        raise ValueError("Pilot requires an object root")
    return converted, changes
