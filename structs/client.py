"""
Structs for client objects.
Make sure to add re-exports to __init__.py for new additions.
"""


class Node(dict):
	"""
	A class used to represent any Node (i.e. another client).

	Attributes
	----------
	node_id: str
		The id that is set to the Node withing a Group.
	name : str
		The name of the Node.
	ip : str
		The IP address of the Node.
	"""

	node_id: str
	name: str
	ip: str


class Group(dict):
	"""
	A class used to represent a Group (i.e. a chat room).

	Attributes
	----------
	group_id : str
		The unique identifier of the group.
	name : str
		The name of the group.
	leader_ip : str
		The group leader IP, which points to a Node.
	vector_clock : int
		The current vector clock value used to keep track of message order.
	peers : dict
		The Nodes within the Group, key is the id of the Node. This include self.
	nds_ip : str
		The IP address of the NDS that this Group is registered to.
	self_id : str
		The id that this Node has within this Group.
	"""

	group_id: str
	name: str
	leader_ip: str
	vector_clock: int
	peers: dict[str, Node]
	nds_ip: str


class Message(dict):
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
