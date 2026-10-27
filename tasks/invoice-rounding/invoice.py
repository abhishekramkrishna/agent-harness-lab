"""Invoice totals. Amounts arrive as strings from the billing export."""


def line_total(quantity: int, unit_price: str) -> float:
    return quantity * float(unit_price)


def invoice_total(lines: list[tuple[int, str]]) -> str:
    """Sum of all lines, rounded half-up to cents, formatted like "12.30"."""
    total = sum(line_total(q, p) for q, p in lines)
    return f"{round(total, 2):.2f}"
