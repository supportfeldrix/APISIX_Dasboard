"""YAML <-> JSON conversion utilities."""
import json
import yaml


def yaml_to_json(yaml_str: str) -> str:
    """Convert a YAML string to a JSON string. Raises ValueError on parse failure."""
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e
    if data is None:
        raise ValueError("YAML content is empty or null")
    return json.dumps(data, indent=2)


def json_to_yaml(json_str: str) -> str:
    """Convert a JSON string to a YAML string. Raises ValueError on parse failure."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e
    return yaml.dump(data, default_flow_style=False, allow_unicode=True)
