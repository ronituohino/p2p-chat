from dataclasses import dataclass
from dataclasses_json import dataclass_json

"""
Structs for generic classes or base classes.
Make sure to add re-exports to __init__.py for new additions.
"""


@dataclass_json
@dataclass
class Response:
	"""
	Represents a generic response object, which is used as a base for all responses.

	Attributes
	----------
	ok : bool
		Indicates whether the response was successful or not.
	"""

	ok: bool
