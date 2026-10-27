"""URL slugs for blog post titles."""

import re


def slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9]", "-", slug)
    return slug.strip("-")
