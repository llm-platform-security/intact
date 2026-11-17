"""Rule registry. Aggregates RULES from each family module.

Adding a new family: create `rules/<name>.py` exporting `RULES: list[Rule]`,
then import it here and extend the registry in `all_rules()`.
"""

from intact.gentree.taxonomy.rules._base import Rule


def all_rules() -> list[Rule]:
    """All rules in deterministic registration order across families."""
    from intact.gentree.taxonomy.rules import (
        anchors, custom, embedded, forms, media, modal, scripting, static, tables,
    )
    out: list[Rule] = []
    out.extend(static.RULES)
    out.extend(anchors.RULES)
    out.extend(forms.RULES)
    out.extend(media.RULES)
    out.extend(embedded.RULES)
    out.extend(tables.RULES)
    out.extend(modal.RULES)
    out.extend(scripting.RULES)
    out.extend(custom.RULES)
    return out
