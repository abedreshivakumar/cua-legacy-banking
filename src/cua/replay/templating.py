"""Resolve `{{ inputs.x }}` and `$labels.key` references in a string."""

import re


def render(text: str, inputs: dict[str, object], labels: dict[str, str]) -> str:
    def repl_input(m: re.Match[str]) -> str:
        return str(inputs.get(m.group(1), m.group(0)))

    def repl_label(m: re.Match[str]) -> str:
        return labels.get(m.group(1), m.group(0))

    text = re.sub(r"\{\{\s*inputs\.(\w+)\s*\}\}", repl_input, text)
    return re.sub(r"\$labels\.(\w+)", repl_label, text)
