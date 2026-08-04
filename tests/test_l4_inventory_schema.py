from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p


def test_inventory_wire_schema_omits_unsupported_unique_items():
    schema = l4_inventory.discovery_schema(l4p)

    def walk(value):
        if isinstance(value, dict):
            if "uniqueItems" in value:
                yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    assert list(walk(schema)) == []
