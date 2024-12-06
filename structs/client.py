from dataclasses import dataclass
from dataclasses_json import dataclass_json

from .generic import Response

"""
Structs for client objects.
Make sure to add re-exports to __init__.py for new additions.
"""


@dataclass_json
@dataclass
class Node:
	"""
	A class used to represent any Node (i.e. another client).

	Attributes
	----------
	node_id: int
		The id that is set to the Node withing a Group.
	name : str
		The name of the Node.
	ip : str
		The IP address of the Node.
	"""

	node_id: int
	name: str
	ip: str


@dataclass_json
@dataclass
class Group:
	"""
	A class used to represent a Group (i.e. a chat room).

	Attributes
	----------
	group_id : str
		The unique identifier of the group.
	name : str
		The name of the group.
	leader_id : int
		The group leader id, which points to a Node.
	self_id : int
		The id that this Node has within this Group.
	vector_clock : int
		The current vector clock value used to keep track of message order.
	peers : dict
		The Nodes within the Group, key is the id of the Node. This include self.
	nds_ip : str
		The IP address of the NDS that this Group is registered to.
	"""

	group_id: str
	name: str
	leader_id: int
	self_id: int
	vector_clock: int
	peers: dict[int, Node]
	nds_ip: str


@dataclass_json
@dataclass
class Message:
	"""
	A class used to represent a single Message sent in the Group.

	Attributes
	----------
	message_id : str
		The unique id assigned to the message.
	message : str
		The content of the message.
	group_id: str
		The group in which the message was sent in.
	source_id : str
		The id of the Node that sent the message.
	vector_clock : int
		The vector clock value for this message, used in ordering them.
	"""

	message_id: str
	message: str
	group_id: str
	source_id: str
	vector_clock: int


### RESPONSES


@dataclass_json
@dataclass
class JoinGroupResponse(Response):
	assigned_peer_id: int
	message: str
	group: Group


@dataclass_json
@dataclass
class ReceiveMessageResponse(Response):
	message: str  # a status message, not the actual text that was sent
