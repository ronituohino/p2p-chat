from .generic import Response
from munch import Munch

"""
Structs for NDS objects.
Make sure to add re-exports to __init__.py for new additions.
"""


class NDS_Group(Munch):
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


### RESPONSES


class FetchGroupResponse(Response):
	groups: list[NDS_Group]


class CreateGroupResponse(Response):
	group: NDS_Group
