from munch import Munch

"""
Structs for generic classes or base classes.
Make sure to add re-exports to __init__.py for new additions.
"""


class Response(Munch):
	"""
	Represents a generic response object, which is used as a base for all responses.
	ok & message don't show in auto-completion, but they are there.

	Attributes
	----------
	ok : bool
		Indicates whether the response was successful or not.
	message : str
		The message associated with the response.
	"""

	ok: bool
	message: str
