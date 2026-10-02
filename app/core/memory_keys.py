"""The preference slots long-term memory may hold — one source of truth.

A "personalization" is a small, named preference (preferred time, preferred
doctor, …). Each slot is identified by a key, and there is at most **one value
per key per user** (``uq_memory_user_key``), so writing a key that already exists
replaces its value instead of adding a row.

Both writers use this list:

* the chat extractor, which fills slots from what the patient says, and
* ``POST /api/memories``, where the user sets one by hand from their profile.

Keeping it here (rather than in the service) means the API schema can derive its
accepted values from the same tuple, so a key the extractor may write is exactly
a key the user may type — and vice versa. The frontend mirrors this list in
``lib/types.ts``.
"""

from typing import Final

#: Every preference slot, in the order the UI should offer them.
MEMORY_KEYS: Final[tuple[str, ...]] = (
    "preferred_time",
    "preferred_doctor",
    "preferred_specialty",
    "language",
    "contact_preference",
    "books_for_family",
)

#: Membership form, for the validation hot path.
ALLOWED_MEMORY_KEYS: Final[frozenset[str]] = frozenset(MEMORY_KEYS)
