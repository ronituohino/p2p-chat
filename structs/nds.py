from dataclasses import dataclass
from dataclasses_json import dataclass_json

from .generic import Response

"""
Structs for NDS objects.
Make sure to add re-exports to __init__.py for new additions.
"""


@dataclass_json
@dataclass
class NDS_Group:
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


@dataclass_json
@dataclass
class FetchGroupResponse(Response):
	groups: list[NDS_Group]


@dataclass_json
@dataclass
class CreateGroupResponse(Response):
	group: NDS_Group


@dataclass_json
@dataclass
class HeartbeatResponse(Response):
	"""Represents a heartbeat message sent back to a leader of a Group from NDS.

	Attributes
	----------
	message : str
		The response to the heartbeat to indicate different statuses.
	"""

	message: str  # a status message
