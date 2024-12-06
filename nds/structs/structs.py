"""
Structs for NDS objects.
Make sure to add re-exports to __init__.py for new additions.
"""


class NDS_Group(dict):
	"""
	A class used to represent a Group (i.e. a chat room). NDS does not need much info about groups.

	Attributes
	----------
	group_id : str
		The unique identifier of the group.
	name : str
		The name of the group.
	leader_ip : str
		The IP address of the group leader, which is a Node.
	"""

	group_id: str
	name: str
	leader_ip: str


class Response(dict):
	"""
	Represents a generic response object. Make sure this matches with client/structs/Response.

	Attributes
	----------
	ok : bool
		Indicates whether the response was successful or not.
	message : str
		The message associated with the response.
	data : dict
		The data associated with the response.
	"""

	ok: bool
	message: str
	data: dict
