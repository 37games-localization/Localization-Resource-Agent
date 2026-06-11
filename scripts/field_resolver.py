"""
field_resolver.py
=================
Resolve logical field keys to Lark field IDs/names from
config/lark-field-mapping.yaml.

Business scripts should gradually migrate from hard-coded field IDs to this
resolver after schema_validator.py has generated a mapping.
"""

from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
MAPPING_PATH = SKILL_ROOT / "config" / "lark-field-mapping.yaml"


class FieldMappingError(RuntimeError):
    pass


def load_field_mapping(path: Path = MAPPING_PATH) -> dict:
    if not path.exists():
        raise FieldMappingError(
            f"字段映射不存在：{path}。请先运行：python3 scripts/schema_validator.py --table all"
        )
    try:
        import yaml
    except ImportError as exc:
        raise FieldMappingError("缺少 pyyaml，请先安装 pyyaml") from exc
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def get_table_mapping(table_key: str, mapping: dict | None = None) -> dict:
    data = mapping or load_field_mapping()
    table = data.get("tables", {}).get(table_key)
    if not table:
        raise FieldMappingError(f"字段映射中不存在表：{table_key}")
    return table


def field_id(table_key: str, logical_key: str, mapping: dict | None = None) -> str:
    table = get_table_mapping(table_key, mapping)
    field = table.get("fields", {}).get(logical_key)
    if not field or not field.get("field_id"):
        raise FieldMappingError(f"未找到字段映射：{table_key}.{logical_key}")
    return field["field_id"]


def field_id_or(table_key: str, logical_key: str, fallback: str, mapping: dict | None = None) -> str:
    """Return mapped field_id, falling back to the legacy ID for old tables."""
    try:
        return field_id(table_key, logical_key, mapping)
    except FieldMappingError:
        return fallback


def field_name(table_key: str, logical_key: str, mapping: dict | None = None) -> str:
    table = get_table_mapping(table_key, mapping)
    field = table.get("fields", {}).get(logical_key)
    if not field:
        raise FieldMappingError(f"未找到字段映射：{table_key}.{logical_key}")
    return field.get("field_name") or field.get("expected_name") or logical_key


def field_name_or(table_key: str, logical_key: str, fallback: str, mapping: dict | None = None) -> str:
    """Return mapped field_name, falling back to a readable legacy name."""
    try:
        return field_name(table_key, logical_key, mapping)
    except FieldMappingError:
        return fallback


def table_ref(table_key: str, mapping: dict | None = None) -> tuple[str, str]:
    table = get_table_mapping(table_key, mapping)
    return table.get("base_token", ""), table.get("table_id", "")


def table_ref_or(
    table_key: str,
    fallback_base_token: str = "",
    fallback_table_id: str = "",
    mapping: dict | None = None,
) -> tuple[str, str]:
    """Return mapped base/table IDs, falling back to config.yaml values."""
    try:
        base_token, table_id = table_ref(table_key, mapping)
    except FieldMappingError:
        return fallback_base_token, fallback_table_id
    return base_token or fallback_base_token, table_id or fallback_table_id
